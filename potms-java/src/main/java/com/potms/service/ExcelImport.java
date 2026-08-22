package com.potms.service;

import com.potms.util.Validators;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.DateUtil;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.jdbc.core.JdbcTemplate;

/** 批量导入 — 对应 Python 版 utils/excel_import.py。 */
public final class ExcelImport {

    private ExcelImport() {}

    /** 模板列顺序，与 Python 版逐列一致（导入的表格可在五版之间通用）。 */
    public static final List<String> FIELDS = List.of(
            "unit", "department", "name", "gender", "birth_date", "work_start_date",
            "id_number", "residence", "political_status", "position_or_title",
            "supervisor_unit", "education_code", "degree_code", "title_code", "rank_code",
            "party_join_date", "position", "tag", "informed", "remarks");

    public static final List<String> HEADERS = List.of(
            "单位", "部门", "姓名", "性别", "出生日期", "参加工作日期",
            "身份证号", "户口所在地", "政治面貌", "职务（级）或职称",
            "人事主管单位", "学历代码", "学位代码", "职称代码", "职级代码",
            "入党日期", "职务（岗位名称）", "标记", "已告知本人", "备注");

    /** 一处行内错误。 */
    public record RowError(int row, String field, String message) {}

    /** 导入结果。 */
    public record Result(int total, int success, List<RowError> errors, List<Long> importedIds) {
        /**
         * 未能导入的**行数**——一行可能同时有多处问题，
         * 直接拿 errors.size() 当失败行数会虚高（Python 版的文案就有这个歧义）。
         */
        public int failedRows() {
            return (int) errors.stream().map(RowError::row).distinct().count();
        }
    }

    /**
     * 解析并导入。逐行独立处理：某行有错只跳过该行，其余照常入库，
     * 报告里列出每一行的问题，便于一次性改完再传。
     */
    public static Result parse(InputStream in, JdbcTemplate jdbc, String operator) {
        List<RowError> errors = new ArrayList<>();
        List<Long> ids = new ArrayList<>();
        int total = 0;
        int success = 0;

        try (Workbook wb = new XSSFWorkbook(in)) {
            Sheet sheet = wb.getSheetAt(0);
            int last = sheet.getLastRowNum();
            for (int r = 1; r <= last; r++) {      // 跳过表头
                Row row = sheet.getRow(r);
                Map<String, String> data = parseRow(row);
                if (data.values().stream().allMatch(String::isEmpty)) {
                    continue;                       // 完全空行不计入总数
                }
                total++;
                int excelRow = r + 1;               // 展示给用户的是 1 起的行号

                List<RowError> rowErrors = validate(data, jdbc, excelRow);
                if (!rowErrors.isEmpty()) {
                    errors.addAll(rowErrors);
                    continue;
                }
                try {
                    ids.add(insert(jdbc, data, operator));
                    success++;
                } catch (RuntimeException e) {
                    errors.add(new RowError(excelRow, "—", "写入失败：" + e.getMessage()));
                }
            }
        } catch (IOException | RuntimeException e) {
            throw new IllegalStateException("解析 Excel 失败：" + e.getMessage(), e);
        }
        return new Result(total, success, errors, ids);
    }

    private static Map<String, String> parseRow(Row row) {
        Map<String, String> data = new LinkedHashMap<>();
        for (int i = 0; i < FIELDS.size(); i++) {
            data.put(FIELDS.get(i), row == null ? "" : cellText(row.getCell(i)));
        }
        data.put("birth_date", Validators.parseDateInput(data.get("birth_date")));
        data.put("work_start_date", Validators.parseDateInput(data.get("work_start_date")));
        data.put("party_join_date", Validators.parseDateInput(data.get("party_join_date")));
        return data;
    }

    /**
     * 单元格取文本。
     *
     * <p>数值型要特别处理：Excel 里手输的身份证号常被存成数值，
     * 直接 toString 会得到 1.10101E+17 这种科学计数法。
     */
    private static String cellText(Cell cell) {
        if (cell == null) {
            return "";
        }
        return switch (cell.getCellType()) {
            case STRING -> cell.getStringCellValue().trim();
            case BOOLEAN -> String.valueOf(cell.getBooleanCellValue());
            case NUMERIC -> {
                if (DateUtil.isCellDateFormatted(cell)) {
                    yield cell.getLocalDateTimeCellValue().toLocalDate()
                            .format(java.time.format.DateTimeFormatter.ofPattern("yyyyMMdd"));
                }
                double d = cell.getNumericCellValue();
                yield d == Math.floor(d) && !Double.isInfinite(d)
                        ? java.math.BigDecimal.valueOf(d).toBigInteger().toString()
                        : String.valueOf(d);
            }
            case FORMULA -> {
                try {
                    yield cell.getStringCellValue().trim();
                } catch (IllegalStateException e) {
                    yield String.valueOf((long) cell.getNumericCellValue());
                }
            }
            default -> "";
        };
    }

    private static List<RowError> validate(Map<String, String> d, JdbcTemplate jdbc, int excelRow) {
        List<RowError> out = new ArrayList<>();
        String[][] required = {
            {"unit", "单位"}, {"department", "部门"}, {"name", "姓名"},
            {"gender", "性别"}, {"birth_date", "出生日期"}, {"id_number", "身份证号"},
            {"political_status", "政治面貌"}, {"position", "职务（岗位名称）"},
        };
        for (String[] f : required) {
            if (d.getOrDefault(f[0], "").isEmpty()) {
                out.add(new RowError(excelRow, f[1], "必填项为空"));
            }
        }
        String id = d.getOrDefault("id_number", "").toUpperCase();
        if (!id.isEmpty()) {
            var c = Validators.validateIdNumber(id);
            if (!c.ok()) {
                out.add(new RowError(excelRow, "身份证号", c.message()));
            } else {
                if (!d.getOrDefault("birth_date", "").isEmpty()) {
                    var b = Validators.validateBirthDateMatch(id, d.get("birth_date"));
                    if (!b.ok()) {
                        out.add(new RowError(excelRow, "出生日期", b.message()));
                    }
                }
                if (!d.getOrDefault("gender", "").isEmpty()) {
                    var g = Validators.validateGenderMatch(id, d.get("gender"));
                    if (!g.ok()) {
                        out.add(new RowError(excelRow, "性别", g.message()));
                    }
                }
                // 与手工录入同一口径：同身份证已存在信息登记表则拒绝，避免产生同号孤儿行
                Long dup = jdbc.queryForObject(
                        "SELECT COUNT(*) FROM personnel_info WHERE id_number = ?", Long.class, id);
                if (dup != null && dup > 0) {
                    out.add(new RowError(excelRow, "身份证号", "该身份证号已存在信息登记表，跳过导入"));
                }
            }
        }
        if (Validators.isPartyMember(d.get("political_status"))
                && d.getOrDefault("party_join_date", "").isEmpty()) {
            out.add(new RowError(excelRow, "入党日期", "中共党员/预备党员须填写入党日期"));
        }
        return out;
    }

    /** 一次导入同时建「信息登记表」与「登记备案表」，与手工录入的两步流程等价。 */
    private static long insert(JdbcTemplate jdbc, Map<String, String> d, String operator) {
        jdbc.update("INSERT INTO personnel_info (unit, department, name, gender, birth_date, "
                + "id_number, work_start_date, education, degree, title, rank, political_status, "
                + "party_join_date, position, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                d.get("unit"), d.get("department"), d.get("name"), d.get("gender"),
                d.get("birth_date"), d.get("id_number").toUpperCase(), d.get("work_start_date"),
                d.get("education_code"), d.get("degree_code"), d.get("title_code"),
                d.get("rank_code"), d.get("political_status"), d.get("party_join_date"),
                d.get("position"), operator);
        Long infoId = jdbc.queryForObject(
                "SELECT id FROM personnel_info WHERE id_number = ? ORDER BY id DESC LIMIT 1",
                Long.class, d.get("id_number").toUpperCase());

        var split = splitName(d.get("name"));
        jdbc.update("INSERT INTO personnel_filing (personnel_info_id, surname, given_name, gender, "
                + "birth_date, id_number, residence, political_status, work_unit, "
                + "position_or_title, supervisor_unit, tag, informed, remarks, operator) "
                + "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                infoId, split[0], split[1], d.get("gender"), d.get("birth_date"),
                d.get("id_number").toUpperCase(),
                d.getOrDefault("residence", ""), d.get("political_status"), d.get("unit"),
                d.getOrDefault("position_or_title", ""), d.getOrDefault("supervisor_unit", ""),
                blankTo(d.get("tag"), "新增"), blankTo(d.get("informed"), "否"),
                d.getOrDefault("remarks", ""), operator);
        return infoId == null ? 0 : infoId;
    }

    private static final String[] COMPOUND = {
        "欧阳", "司马", "上官", "诸葛", "令狐", "皇甫", "尉迟", "长孙",
        "宇文", "慕容", "夏侯", "东方",
    };

    private static String[] splitName(String full) {
        String n = full == null ? "" : full.trim();
        if (n.isEmpty()) {
            return new String[] {"", ""};
        }
        for (String cs : COMPOUND) {
            if (n.length() > 2 && n.startsWith(cs)) {
                return new String[] {cs, n.substring(2)};
            }
        }
        return n.length() <= 1 ? new String[] {n, ""}
                : new String[] {n.substring(0, 1), n.substring(1)};
    }

    private static String blankTo(String v, String dflt) {
        return (v == null || v.isBlank()) ? dflt : v.trim();
    }

    /** 生成空白导入模板。 */
    public static Excel.SheetSpec templateSpec() {
        return new Excel.SheetSpec("备案人员批量导入模板", HEADERS, List.of(),
                List.of("填表说明：",
                        "1. 第 1 行为表头，请从第 2 行开始填写，不要调整列顺序。",
                        "2. 日期支持 20260801 / 2026-08-01 / 2026/8/1 三种写法。",
                        "3. 学历/学位/职称/职级填「代码」，可在「系统设置 → 数据字典」中查。",
                        "4. 身份证号须与出生日期、性别一致，否则该行会被拒绝。",
                        "5. 操作人由当前登录账户自动记录，无需在表中填写。",
                        "6. 一行同时生成「信息登记表」与「登记备案表」两条记录。"));
    }
}

package com.potms.web;

import static com.potms.web.PersonnelController.operator;
import static com.potms.web.PersonnelController.str;

import com.potms.Config;
import com.potms.data.Db;
import com.potms.service.Excel;
import com.potms.service.IssuanceOps;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;

/** Excel 导出六表 + 日志年度归档。对应 Python 版 blueprints/export.py。 */
@Controller
public class ExportController {

    private static final MediaType XLSX = MediaType.parseMediaType(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");

    private final Db db;
    private final Config cfg;

    public ExportController(Db db, Config cfg) {
        this.db = db;
        this.cfg = cfg;
    }

    // =====================================================================
    // 六张业务表
    // =====================================================================

    @GetMapping("/export/info")
    public Object exportInfo(HttpServletRequest req) {
        Filter f = PersonnelController.buildFilters(req, selectedIds(req));
        // 一律经 personnel_filing 关联导出：只导出有备案引用的信息登记表，
        // 无引用的孤儿行永不外泄（GROUP BY 去重，避免一人多条备案时重复）
        var rows = db.jdbc().queryForList(
                "SELECT pi.* FROM personnel_info pi "
                + "JOIN personnel_filing pf ON pf.personnel_info_id = pi.id "
                + "LEFT JOIN personnel_info pi2 ON pf.personnel_info_id = pi2.id "
                + "WHERE 1=1" + f.where() + " GROUP BY pi.id ORDER BY pi.created_at DESC",
                f.params());

        Map<String, Map<String, String>> dicts = dictMaps("education", "degree", "title", "rank");
        List<List<Object>> data = new ArrayList<>();
        for (var r : rows) {
            data.add(List.of(
                    s(r, "unit"), s(r, "department"), s(r, "name"), s(r, "gender"),
                    s(r, "birth_date"), s(r, "id_number"), s(r, "work_start_date"),
                    dv(dicts, "education", s(r, "education")), dv(dicts, "degree", s(r, "degree")),
                    dv(dicts, "title", s(r, "title")), dv(dicts, "rank", s(r, "rank")),
                    s(r, "political_status"), s(r, "party_join_date"), s(r, "position")));
        }
        return send(req, new Excel.SheetSpec("备案人员信息登记表",
                List.of("单位", "部门", "姓名", "性别", "出生日期", "身份证号", "参加工作日期",
                        "学历", "学位", "职称", "职级", "政治面貌", "入党日期", "职务（岗位名称）"),
                data,
                List.of("填表说明：",
                        "1. 出生日期格式为YYYYMMDD，需与身份证号对应。",
                        "2. 学历、学位、职称、职级、政治面貌从系统数据字典中选择。",
                        "3. 中共党员/预备党员须填写入党日期。")),
                "备案人员信息登记表", null, "personnel_info");
    }

    @GetMapping("/export/filing")
    public Object exportFiling(HttpServletRequest req) {
        Filter f = PersonnelController.buildFilters(req, selectedIds(req));
        var rows = db.jdbc().queryForList(
                "SELECT pf.* FROM personnel_filing pf "
                + "LEFT JOIN personnel_info pi ON pf.personnel_info_id = pi.id "
                + "WHERE 1=1" + f.where() + " ORDER BY pf.created_at DESC", f.params());
        List<List<Object>> data = new ArrayList<>();
        for (var r : rows) {
            data.add(List.of(
                    s(r, "surname"), s(r, "given_name"), s(r, "gender"), s(r, "birth_date"),
                    s(r, "id_number"), s(r, "residence"), s(r, "political_status"),
                    s(r, "work_unit"), s(r, "position_or_title"), s(r, "supervisor_unit"),
                    s(r, "tag"), s(r, "informed"), s(r, "remarks"),
                    Fmt.statusLabel(s(r, "status"))));
        }
        return send(req, new Excel.SheetSpec("因私事出国（境）人员登记备案表",
                List.of("中文姓", "中文名", "性别", "出生日期", "身份证号", "户口所在地", "政治面貌",
                        "工作单位", "职务（级）或职称", "人事主管单位", "标记", "已告知本人", "备注", "状态"),
                data,
                List.of("填表说明：",
                        "1. 复姓请完整填入「中文姓」栏。",
                        "2. 标记「新增」为首次备案，「更新」为撤控后重报。")),
                "因私事出国境人员登记备案表", null, "personnel_filing");
    }

    @GetMapping("/export/certificate")
    public Object exportCertificate(HttpServletRequest req) {
        Filter f = CertificateController.buildFilters(req, selectedIds(req));
        var rows = db.jdbc().queryForList(
                "SELECT * FROM certificates WHERE 1=1" + f.where() + " ORDER BY updated_at DESC",
                f.params());
        List<List<Object>> data = new ArrayList<>();
        for (var r : rows) {
            data.add(List.of(
                    s(r, "unit"), s(r, "department"), s(r, "name"),
                    s(r, "passport_no"), s(r, "passport_expiry"), s(r, "passport_submit_date"),
                    s(r, "hm_pass_no"), s(r, "hm_pass_expiry"), s(r, "hm_pass_submit_date"),
                    s(r, "tw_pass_no"), s(r, "tw_pass_expiry"), s(r, "tw_pass_submit_date")));
        }
        return send(req, new Excel.SheetSpec("因私出国（境）备案人员证照登记表",
                List.of("单位", "部门", "姓名",
                        "普通护照号", "护照有效期", "护照上交日期",
                        "港澳通行证号", "港澳有效期", "港澳上交日期",
                        "台湾通行证号", "台湾有效期", "台湾上交日期"),
                data, List.of("填表说明：证照有效期距今 30 天内的，系统会在首页与列表页预警。")),
                "因私出国境备案人员证照登记表", null, "certificate");
    }

    @GetMapping("/export/travel")
    public Object exportTravel(HttpServletRequest req, TravelController travel) {
        Filter f = travel.buildFilters(req, selectedIds(req));
        var rows = db.jdbc().queryForList(
                "SELECT * FROM travel_details WHERE 1=1" + f.where() + " ORDER BY created_at DESC",
                f.params());
        List<List<Object>> data = new ArrayList<>();
        for (var r : rows) {
            data.add(List.of(
                    s(r, "unit"), s(r, "department"), s(r, "name"), s(r, "position"),
                    s(r, "title"), s(r, "id_number"), s(r, "destination_passport"),
                    s(r, "category"), s(r, "travel_dates"), s(r, "approval_date"),
                    s(r, "need_new_passport"), s(r, "passport_no"),
                    s(r, "passport_collect_date"), s(r, "passport_return_date"),
                    s(r, "actual_return_date"),
                    "cancelled".equals(s(r, "trip_status")) ? "已取消" : "正常",
                    s(r, "cancel_date")));
        }
        return send(req, new Excel.SheetSpec("因私出国（境）人员明细表",
                List.of("单位", "部门", "姓名", "职务", "职称", "身份证号", "地点、证照", "类别",
                        "计划出行日期", "批准日期", "是否做证", "证件号码",
                        "证件领用日期", "证件归还日期", "实际回国日期", "行程状态", "取消日期"),
                data,
                List.of("填表说明：",
                        "1. 证件领用/归还日期为派生字段，由「证件领用」模块登记后自动带入。",
                        "2. 正常行程回国后 10 个工作日内、取消行程自取消日起 5 个工作日内交回证件。")),
                "因私出国境人员明细表", null, "travel_details");
    }

    @GetMapping("/export/decontrol")
    public Object exportDecontrol(HttpServletRequest req) {
        Filter f = DecontrolController.buildFilters(req, selectedIds(req));
        var rows = db.jdbc().queryForList(
                "SELECT * FROM decontrol_filing WHERE 1=1" + f.where() + " ORDER BY created_at DESC",
                f.params());
        List<List<Object>> data = new ArrayList<>();
        for (var r : rows) {
            data.add(List.of(
                    s(r, "surname"), s(r, "given_name"), s(r, "gender"), s(r, "birth_date"),
                    s(r, "id_number"), s(r, "residence"), s(r, "political_status"),
                    s(r, "work_unit"), s(r, "supervisor_unit"), s(r, "submit_unit_name"),
                    s(r, "submit_unit_type"), s(r, "submit_contact"), s(r, "submit_phone"),
                    s(r, "batch_no"), s(r, "reason"), s(r, "decontrol_date"),
                    s(r, "cert_handover_date")));
        }
        return send(req, new Excel.SheetSpec("因私事出国（境）人员撤控备案表",
                List.of("中文姓", "中文名", "性别", "出生日期", "身份证号", "户口所在地", "政治面貌",
                        "工作单位", "人事主管单位", "报送单位", "报送单位类别", "联系人", "联系电话",
                        "入库批号", "撤控原因", "撤控日期", "证件移交日期"),
                data, List.of("填表说明：撤控后该人员备案状态标记为「已撤控」；重新备案时系统自动关联新旧记录。")),
                "因私事出国境人员撤控备案表", null, "decontrol_filing");
    }

    /** 领用登记表：唯一带签名嵌图的导出。 */
    @GetMapping("/export/issuance")
    public Object exportIssuance(HttpServletRequest req) {
        Filter f = IssuanceController.buildFilters(req, selectedIds(req));
        var rows = db.jdbc().queryForList(
                IssuanceController.BASE_SELECT + f.where()
                + " ORDER BY i.issue_date DESC, i.id DESC", f.params());
        List<List<Object>> data = new ArrayList<>();
        for (var r : rows) {
            data.add(java.util.Arrays.asList(
                    s(r, "issue_date"), s(r, "holder_name"), s(r, "work_unit"),
                    s(r, "id_number"), IssuanceOps.typesLabel(db.jdbc(), s(r, "cert_types")),
                    s(r, "cert_nos"), s(r, "issuer"),
                    r.get("sign_image"),                    // 第 7 列：领用签名
                    s(r, "return_date"), s(r, "return_operator"),
                    r.get("return_sign_image"),             // 第 10 列：归还签名
                    statusLabel(s(r, "status")), s(r, "remarks")));
        }
        return send(req, new Excel.SheetSpec("因私出国（境）证件领用登记表",
                List.of("领用日期", "领用人", "工作单位", "身份证号", "证件种类", "证件号码", "发放人",
                        "领用人签名", "归还日期", "接收人", "归还人签名", "状态", "备注"),
                data,
                List.of("填表说明：",
                        "1. 签名为领用/归还时现场手写采集，保存后不可修改；登记有误须作废后重新登记。",
                        "2. 本系统另对签名施加国密 SM3withSM2 签章，任何改动都会导致验章失败。")),
                "因私出国境证件领用登记表", List.of(7, 10), "cert_issuance");
    }

    // =====================================================================
    // 操作日志年度归档
    // =====================================================================

    @GetMapping("/logs/export")
    public Object exportLogs(HttpServletRequest req) {
        String year = PersonnelController.param(req, "year", "");
        if (year.length() != 4 || !year.chars().allMatch(Character::isDigit)) {
            Flash.warning(req, "请选择要归档导出的年份。");
            return "redirect:/logs";
        }
        String tz = (cfg.tzOffsetHours >= 0 ? "+" : "") + cfg.tzOffsetHours + " hours";
        var rows = db.jdbc().queryForList(
                "SELECT * FROM operation_logs "
                + "WHERE strftime('%Y', datetime(created_at, ?)) = ? ORDER BY created_at", tz, year);
        List<List<Object>> data = new ArrayList<>();
        for (var r : rows) {
            data.add(List.of(
                    Helpers.toLocalTime(r.get("created_at"), cfg),
                    s(r, "operator"),
                    LogsController.ACTION_LABELS.getOrDefault(s(r, "action"), s(r, "action")),
                    LogsController.TARGET_LABELS.getOrDefault(s(r, "target_type"), s(r, "target_type")),
                    s(r, "target_id"), s(r, "detail"), s(r, "ip_address"),
                    changesText(s(r, "snapshot"))));
        }
        return send(req, new Excel.SheetSpec(year + " 年操作日志归档",
                List.of("时间", "操作人", "动作", "对象", "对象ID", "详情", "IP", "变更明细"),
                data, List.of("说明：本文件为审计副本，库内日志完整保留，不因导出而清理。")),
                year + "年操作日志", null, "operation_logs");
    }

    private static String changesText(String snapshot) {
        var changes = LogsController.computeChanges(snapshot);
        if (changes.isEmpty()) {
            return "";
        }
        List<String> parts = new ArrayList<>();
        for (var c : changes.items()) {
            parts.add(c.field() + "：" + (c.before().isEmpty() ? "（空）" : c.before())
                    + " → " + (c.after().isEmpty() ? "（空）" : c.after()));
        }
        return String.join("\n", parts);
    }

    // ------------------------------------------------------------------

    private Object send(HttpServletRequest req, Excel.SheetSpec spec, String prefix,
                        List<Integer> signColumns, String targetType) {
        try {
            var result = Excel.write(cfg.exportFolder, spec, prefix, operator(req), signColumns);
            Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                    "export", targetType, null,
                    "导出 " + result.fileName() + "（" + spec.rows().size() + " 条）", null, null);
            return ResponseEntity.ok()
                    .contentType(XLSX)
                    .header(HttpHeaders.CONTENT_DISPOSITION,
                            ContentDisposition.attachment()
                                    .filename(result.fileName(), java.nio.charset.StandardCharsets.UTF_8)
                                    .build().toString())
                    .body(new FileSystemResource(result.path()));
        } catch (RuntimeException e) {
            Flash.danger(req, "导出失败：" + e.getMessage());
            return "redirect:/";
        }
    }

    /** 前端「导出选中行」传来的 id 串。 */
    private static List<Long> selectedIds(HttpServletRequest req) {
        return Filter.parseIds(req.getParameter("ids"));
    }

    private Map<String, Map<String, String>> dictMaps(String... categories) {
        Map<String, Map<String, String>> out = new LinkedHashMap<>();
        for (String cat : categories) {
            Map<String, String> m = new LinkedHashMap<>();
            Helpers.dictOptions(db.jdbc(), cat).forEach(o -> m.put(o.code(), o.value()));
            out.put(cat, m);
        }
        return out;
    }

    private static String dv(Map<String, Map<String, String>> dicts, String cat, String code) {
        if (code.isEmpty()) {
            return "";
        }
        return dicts.getOrDefault(cat, Map.of()).getOrDefault(code, code);
    }

    private static String statusLabel(String s) {
        return switch (s) {
            case "issued" -> "已领用";
            case "returned" -> "已归还";
            case "voided" -> "已作废";
            default -> s;
        };
    }

    private static String s(Map<String, Object> row, String key) {
        return str(row.get(key));
    }
}

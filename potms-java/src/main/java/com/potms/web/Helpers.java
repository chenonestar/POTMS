package com.potms.web;

import tools.jackson.databind.ObjectMapper;
import com.potms.Config;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.jdbc.core.JdbcTemplate;

/** 通用助手 — 对应 Python 版 utils/helpers.py。 */
public final class Helpers {

    private Helpers() {}

    private static final ObjectMapper JSON = new ObjectMapper();
    private static final DateTimeFormatter SQL_TS =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    // ---- 时间：数据库统一存 UTC，展示按固定偏移换算 ----

    public static String toLocalTime(Object value, Config cfg) {
        return toLocalTime(value, cfg, "yyyy-MM-dd HH:mm:ss");
    }

    public static String toLocalTime(Object value, Config cfg, String pattern) {
        if (value == null) {
            return "";
        }
        String s = value.toString();
        if (s.isEmpty()) {
            return "";
        }
        try {
            LocalDateTime utc = LocalDateTime.parse(s.replace('T', ' ').substring(0,
                    Math.min(19, s.length())), SQL_TS);
            return utc.plusHours(cfg.tzOffsetHours)
                    .format(DateTimeFormatter.ofPattern(pattern));
        } catch (DateTimeParseException | StringIndexOutOfBoundsException e) {
            return s;   // 非时间戳内容原样返回
        }
    }

    public static String todayLocal(Config cfg) {
        return Instant.now().atOffset(ZoneOffset.UTC).plusHours(cfg.tzOffsetHours)
                .format(DateTimeFormatter.ofPattern("yyyyMMdd"));
    }

    public static String nowUtcSql() {
        return LocalDateTime.now(ZoneOffset.UTC).format(SQL_TS);
    }

    // ---- 操作日志 ----

    /** 快照中不记录的字段：时间戳无意义，签名 BLOB 过大且不应进日志。 */
    private static final Set<String> SNAPSHOT_SKIP = Set.of(
            "created_at", "updated_at",
            "sign_image", "sign_meta", "return_sign_image", "return_sign_meta");

    /** row_snapshot 允许查询的表白名单（防御性：杜绝动态表名注入）。 */
    private static final Set<String> SNAPSHOT_TABLES = Set.of(
            "personnel_info", "personnel_filing", "certificates", "travel_details",
            "decontrol_filing", "sys_dict", "sys_org", "sys_submit_unit", "cert_issuance");

    public static Map<String, Object> rowSnapshot(JdbcTemplate jdbc, String table, long id) {
        if (!SNAPSHOT_TABLES.contains(table)) {
            throw new IllegalArgumentException("rowSnapshot: 不允许的表名 " + table);
        }
        var rows = jdbc.queryForList("SELECT * FROM " + table + " WHERE id = ?", id);
        if (rows.isEmpty()) {
            return null;
        }
        Map<String, Object> out = new LinkedHashMap<>();
        for (var e : rows.get(0).entrySet()) {
            if (!SNAPSHOT_SKIP.contains(e.getKey())) {
                out.put(e.getKey(), e.getValue());
            }
        }
        return out;
    }

    public static void logAction(JdbcTemplate jdbc, String operator, String ip, String action,
                                 String targetType, Long targetId, String detail,
                                 Map<String, Object> before, Map<String, Object> after) {
        String snapshot = null;
        if (before != null || after != null) {
            Map<String, Object> both = new LinkedHashMap<>();
            both.put("before", before);
            both.put("after", after);
            try {
                snapshot = JSON.writeValueAsString(both);
            } catch (Exception e) {
                snapshot = null;   // 快照序列化失败不应阻断业务写入
            }
        }
        jdbc.update("INSERT INTO operation_logs (operator, action, target_type, target_id, "
                + "detail, ip_address, snapshot) VALUES (?, ?, ?, ?, ?, ?, ?)",
                operator, action, targetType, targetId, detail, ip, snapshot);
    }

    // ---- 数据字典 ----

    public record DictOption(String code, String value) {}

    public static List<DictOption> dictOptions(JdbcTemplate jdbc, String category) {
        return jdbc.query("SELECT code, value FROM sys_dict WHERE category = ? "
                + "ORDER BY sort_order, code",
                (rs, i) -> new DictOption(rs.getString("code"), rs.getString("value")), category);
    }

    /** 代码转显示值；查不到时原样返回代码，避免页面出现空白。 */
    public static String dictValue(JdbcTemplate jdbc, String category, String code) {
        if (code == null || code.isEmpty()) {
            return "";
        }
        var v = jdbc.queryForList("SELECT value FROM sys_dict WHERE category = ? AND code = ?",
                String.class, category, code);
        return v.isEmpty() ? code : v.get(0);
    }

    // ---- 组织架构 ----

    public record OrgNode(long id, String name, long parentId, long sortOrder) {}

    public record OrgOption(long id, String label, String name, int depth) {}

    public static List<OrgNode> orgFlat(JdbcTemplate jdbc) {
        return jdbc.query("SELECT id, name, parent_id, sort_order FROM sys_org "
                + "ORDER BY parent_id, sort_order, id",
                (rs, i) -> new OrgNode(rs.getLong("id"), rs.getString("name"),
                        rs.getLong("parent_id"), rs.getLong("sort_order")));
    }

    /** 层级缩进的下拉选项（父级用 — 前缀表示层级）。 */
    public static List<OrgOption> orgTreeOptions(JdbcTemplate jdbc) {
        List<OrgNode> all = orgFlat(jdbc);
        List<OrgOption> out = new ArrayList<>();
        walk(all, out, 0, 0);
        return out;
    }

    private static void walk(List<OrgNode> all, List<OrgOption> out, long parent, int depth) {
        for (OrgNode n : all) {
            if (n.parentId() == parent) {
                out.add(new OrgOption(n.id(), "—".repeat(depth) + (depth > 0 ? " " : "") + n.name(),
                        n.name(), depth));
                walk(all, out, n.id(), depth + 1);
            }
        }
    }

    public static List<OrgNode> orgChildren(JdbcTemplate jdbc, long parentId) {
        return jdbc.query("SELECT id, name, parent_id, sort_order FROM sys_org "
                + "WHERE parent_id = ? ORDER BY sort_order, id",
                (rs, i) -> new OrgNode(rs.getLong("id"), rs.getString("name"),
                        rs.getLong("parent_id"), rs.getLong("sort_order")), parentId);
    }

    public record SubmitUnit(long id, String name, String contact, String phone) {}

    public static List<SubmitUnit> submitUnits(JdbcTemplate jdbc) {
        return jdbc.query("SELECT id, name, contact, phone FROM sys_submit_unit "
                + "ORDER BY sort_order, id",
                (rs, i) -> new SubmitUnit(rs.getLong("id"), rs.getString("name"),
                        rs.getString("contact"), rs.getString("phone")));
    }

    // ---- 备案人员下拉（含证件号，供下游自动带入）----

    /**
     * @param certNos    该人已登记的全部证件号（扁平，供 datalist）
     * @param certByType 按证件种类代码索引（01 护照 / 02 港澳 / 03 台湾），供领用登记自动带入
     */
    public record PersonOption(long id, String name, String fullName, String unit, String department,
                               String idNumber, String position, String title,
                               List<String> certNos, Map<String, String> certByType) {}

    public static List<PersonOption> personnelOptions(JdbcTemplate jdbc) {
        var rows = jdbc.queryForList(
                "SELECT pf.id, pf.surname, pf.given_name, pf.work_unit, pf.id_number, "
                + "       pf.position_or_title, COALESCE(pi.department, '') AS department, "
                + "       (SELECT value FROM sys_dict WHERE category = 'title' AND code = pi.title) AS title_val "
                + "FROM personnel_filing pf "
                + "LEFT JOIN personnel_info pi ON pf.personnel_info_id = pi.id "
                + "WHERE pf.status = 'active' ORDER BY pf.surname, pf.given_name");

        // 每人已登记的证件号，一次查询建映射
        Map<Long, List<String>> certList = new LinkedHashMap<>();
        Map<Long, Map<String, String>> certByType = new LinkedHashMap<>();
        for (var c : jdbc.queryForList(
                "SELECT personnel_filing_id, passport_no, hm_pass_no, tw_pass_no FROM certificates")) {
            Object pidObj = c.get("personnel_filing_id");
            if (pidObj == null) {
                continue;
            }
            long pid = ((Number) pidObj).longValue();
            var list = certList.computeIfAbsent(pid, k -> new ArrayList<>());
            var byType = certByType.computeIfAbsent(pid, k -> new LinkedHashMap<>());
            String[][] pairs = {
                {"01", str(c.get("passport_no"))},
                {"02", str(c.get("hm_pass_no"))},
                {"03", str(c.get("tw_pass_no"))},
            };
            for (String[] p : pairs) {
                String v = p[1].trim();
                if (v.isEmpty()) {
                    continue;
                }
                if (!list.contains(v)) {
                    list.add(v);
                }
                byType.putIfAbsent(p[0], v);
            }
        }

        List<PersonOption> out = new ArrayList<>();
        for (var r : rows) {
            long id = ((Number) r.get("id")).longValue();
            String name = str(r.get("surname")) + str(r.get("given_name"));
            out.add(new PersonOption(id, name,
                    name + " (" + str(r.get("work_unit")) + ")",
                    str(r.get("work_unit")), str(r.get("department")), str(r.get("id_number")),
                    str(r.get("position_or_title")), str(r.get("title_val")),
                    certList.getOrDefault(id, List.of()),
                    certByType.getOrDefault(id, Map.of())));
        }
        return out;
    }

    private static String str(Object o) {
        return o == null ? "" : o.toString();
    }

    // ---- 分页 ----

    /** 分页结果 — 对应 Python 版 PageResult。 */
    public record Page<T>(List<T> rows, int page, int pages, int total) {
        public boolean hasPrev() {
            return page > 1;
        }

        public boolean hasNext() {
            return page < pages;
        }
    }

    public static Page<Map<String, Object>> paginate(JdbcTemplate jdbc, String sql,
                                                     Object[] params, int page, int perPage) {
        Integer total = jdbc.queryForObject("SELECT COUNT(*) FROM (" + sql + ")",
                Integer.class, params);
        int t = total == null ? 0 : total;
        int pages = Math.max(1, (int) Math.ceil(t / (double) perPage));
        int p = Math.min(Math.max(page <= 0 ? 1 : page, 1), pages);

        Object[] withLimit = new Object[params.length + 2];
        System.arraycopy(params, 0, withLimit, 0, params.length);
        withLimit[params.length] = perPage;
        withLimit[params.length + 1] = (p - 1) * perPage;

        var rows = jdbc.queryForList(sql + " LIMIT ? OFFSET ?", withLimit);
        return new Page<>(rows, p, pages, t);
    }

    /** 全量下发（前端按视口窗口化分页），与其它四版的 list_all 一致。 */
    public static Page<Map<String, Object>> listAll(JdbcTemplate jdbc, String sql, Object[] params) {
        var rows = jdbc.queryForList(sql, params);
        return new Page<>(rows, 1, 1, rows.size());
    }
}

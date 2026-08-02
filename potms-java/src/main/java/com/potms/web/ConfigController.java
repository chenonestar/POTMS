package com.potms.web;

import static com.potms.web.PersonnelController.operator;
import static com.potms.web.PersonnelController.param;
import static com.potms.web.PersonnelController.trim;

import com.potms.data.Db;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.ResponseBody;

/**
 * 系统配置：数据字典 / 组织架构 / 报送单位。
 * 对应 Python 版 dict_admin.py + organization.py + submit_unit.py。
 */
@Controller
public class ConfigController {

    /** 字典分类及其被业务表引用的位置——删除前据此统计引用数。 */
    public record Category(String key, String label, String[][] refs) {}

    public static final List<Category> CATEGORIES = List.of(
            new Category("education", "学历", new String[][] {{"personnel_info", "education"}}),
            new Category("degree", "学位", new String[][] {{"personnel_info", "degree"}}),
            new Category("title", "职称", new String[][] {
                {"personnel_info", "title"}, {"travel_details", "title"}}),
            new Category("rank", "职级", new String[][] {{"personnel_info", "rank"}}),
            new Category("political_status", "政治面貌", new String[][] {
                {"personnel_info", "political_status"}, {"personnel_filing", "political_status"},
                {"decontrol_filing", "political_status"}}),
            new Category("travel_category", "出国（境）类别", new String[][] {
                {"travel_details", "category"}}),
            new Category("submit_unit_type", "报送单位类别", new String[][] {
                {"decontrol_filing", "submit_unit_type"}}),
            new Category("cert_type", "证件种类", new String[][] {}),
            new Category("supervisor_unit", "人事主管单位", new String[][] {
                {"personnel_filing", "supervisor_unit"}, {"decontrol_filing", "supervisor_unit"}}));

    private static final Map<String, Category> CAT_MAP = new LinkedHashMap<>();

    static {
        CATEGORIES.forEach(c -> CAT_MAP.put(c.key(), c));
    }

    private final Db db;

    public ConfigController(Db db) {
        this.db = db;
    }

    // =====================================================================
    // 数据字典
    // =====================================================================

    /** 一个字典项 + 它被业务记录引用的次数。 */
    public record DictItem(long id, String category, String code, String value,
                           long sortOrder, long usage) {}

    /**
     * 统计某字典项被引用的次数（编码或显示值命中）。
     *
     * <p>表名与列名来自上面的常量表，不是用户输入——不存在注入面。
     */
    private long usageCount(String category, String code, String value) {
        Category cat = CAT_MAP.get(category);
        if (cat == null) {
            return 0;
        }
        long total = 0;
        for (String[] ref : cat.refs()) {
            Long n = db.jdbc().queryForObject(
                    "SELECT COUNT(*) FROM " + ref[0] + " WHERE " + ref[1] + " = ? OR " + ref[1] + " = ?",
                    Long.class, code, value);
            total += n == null ? 0 : n;
        }
        return total;
    }

    @GetMapping("/dict")
    public String dictIndex(HttpServletRequest req, Model model) {
        Map<String, List<DictItem>> grouped = new LinkedHashMap<>();
        for (Category cat : CATEGORIES) {
            List<DictItem> items = new ArrayList<>();
            for (var r : db.jdbc().queryForList(
                    "SELECT id, category, code, value, sort_order FROM sys_dict "
                    + "WHERE category = ? ORDER BY sort_order, code", cat.key())) {
                String code = Fmt.s(r, "code");
                String value = Fmt.s(r, "value");
                items.add(new DictItem(Fmt.n(r, "id"), cat.key(), code, value,
                        Fmt.n(r, "sort_order"), usageCount(cat.key(), code, value)));
            }
            grouped.put(cat.key(), items);
        }
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("categories", CATEGORIES);
        model.addAttribute("grouped", grouped);
        return "dict/index";
    }

    @PostMapping("/dict/add")
    public String dictAdd(HttpServletRequest req) {
        String category = trim(req, "category");
        String code = trim(req, "code");
        String value = trim(req, "value");
        if (!CAT_MAP.containsKey(category)) {
            Flash.danger(req, "未知的字典分类。");
            return "redirect:/dict";
        }
        if (code.isEmpty() || value.isEmpty()) {
            Flash.danger(req, "代码与显示值均为必填项。");
            return "redirect:/dict";
        }
        Long dup = db.jdbc().queryForObject(
                "SELECT COUNT(*) FROM sys_dict WHERE category = ? AND code = ?",
                Long.class, category, code);
        if (dup != null && dup > 0) {
            Flash.danger(req, "该分类下代码 " + code + " 已存在。");
            return "redirect:/dict";
        }
        long id = db.insert("INSERT INTO sys_dict (category, code, value, sort_order) "
                + "VALUES (?, ?, ?, ?)", category, code, value, intOr(req, "sort_order", 0));
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "create", "sys_dict", id, category + "：" + code + " " + value, null,
                Helpers.rowSnapshot(db.jdbc(), "sys_dict", id));
        Flash.success(req, "已添加字典项：" + value);
        return "redirect:/dict?cat=" + category;
    }

    @PostMapping("/dict/{id}/edit")
    public String dictEdit(@PathVariable long id, HttpServletRequest req) {
        var before = Helpers.rowSnapshot(db.jdbc(), "sys_dict", id);
        if (before == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/dict";
        }
        String value = trim(req, "value");
        if (value.isEmpty()) {
            Flash.danger(req, "显示值不能为空。");
            return "redirect:/dict";
        }
        db.jdbc().update("UPDATE sys_dict SET value = ?, sort_order = ? WHERE id = ?",
                value, intOr(req, "sort_order", 0), id);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "update", "sys_dict", id, value, before,
                Helpers.rowSnapshot(db.jdbc(), "sys_dict", id));
        Flash.success(req, "已更新：" + value);
        return "redirect:/dict?cat=" + before.get("category");
    }

    @PostMapping("/dict/{id}/delete")
    public String dictDelete(@PathVariable long id, HttpServletRequest req) {
        var before = Helpers.rowSnapshot(db.jdbc(), "sys_dict", id);
        if (before == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/dict";
        }
        String category = String.valueOf(before.get("category"));
        long used = usageCount(category, String.valueOf(before.get("code")),
                String.valueOf(before.get("value")));
        if (used > 0) {
            Flash.danger(req, "该字典项已被 " + used + " 条业务记录引用，不能删除。");
            return "redirect:/dict?cat=" + category;
        }
        db.jdbc().update("DELETE FROM sys_dict WHERE id = ?", id);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "delete", "sys_dict", id, null, before, null);
        Flash.info(req, "字典项已删除。");
        return "redirect:/dict?cat=" + category;
    }

    // =====================================================================
    // 组织架构
    // =====================================================================

    @GetMapping("/org")
    public String orgIndex(HttpServletRequest req, Model model) {
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("nodes", Helpers.orgFlatOptions(db.jdbc()));
        model.addAttribute("options", Helpers.orgTreeOptions(db.jdbc()));
        return "org/index";
    }

    @GetMapping("/org/tree-data")
    @ResponseBody
    public List<Map<String, Object>> orgTreeData() {
        return db.jdbc().queryForList(
                "SELECT id, name, parent_id FROM sys_org ORDER BY parent_id, sort_order");
    }

    @PostMapping("/org/add")
    public String orgAdd(HttpServletRequest req) {
        String name = trim(req, "name");
        if (name.isEmpty()) {
            Flash.danger(req, "请输入单位/部门名称。");
            return "redirect:/org";
        }
        long id = db.insert("INSERT INTO sys_org (name, parent_id, sort_order) VALUES (?, ?, ?)",
                name, intOr(req, "parent_id", 0), intOr(req, "sort_order", 0));
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "create", "sys_org", id, name, null, null);
        Flash.success(req, "已添加：" + name);
        return "redirect:/org";
    }

    @PostMapping("/org/{id}/edit")
    public String orgEdit(@PathVariable long id, HttpServletRequest req) {
        String name = trim(req, "name");
        if (name.isEmpty()) {
            Flash.danger(req, "名称不能为空。");
            return "redirect:/org";
        }
        int parentId = intOr(req, "parent_id", 0);
        if (parentId == id) {
            Flash.danger(req, "上级不能是自己。");
            return "redirect:/org";
        }
        var before = Helpers.rowSnapshot(db.jdbc(), "sys_org", id);
        db.jdbc().update("UPDATE sys_org SET name = ?, parent_id = ?, sort_order = ? WHERE id = ?",
                name, parentId, intOr(req, "sort_order", 0), id);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "update", "sys_org", id, name, before,
                Helpers.rowSnapshot(db.jdbc(), "sys_org", id));
        Flash.success(req, "已更新：" + name);
        return "redirect:/org";
    }

    @PostMapping("/org/{id}/delete")
    public String orgDelete(@PathVariable long id, HttpServletRequest req) {
        Long children = db.jdbc().queryForObject(
                "SELECT COUNT(*) FROM sys_org WHERE parent_id = ?", Long.class, id);
        if (children != null && children > 0) {
            Flash.danger(req, "该节点下还有子部门，请先删除子部门。");
            return "redirect:/org";
        }
        var before = Helpers.rowSnapshot(db.jdbc(), "sys_org", id);
        if (before == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/org";
        }
        // 被业务记录按名称引用时不允许删除，避免下拉里的历史值凭空消失
        String name = String.valueOf(before.get("name"));
        long used = count("SELECT COUNT(*) FROM personnel_info WHERE unit = ? OR department = ?", name, name)
                + count("SELECT COUNT(*) FROM personnel_filing WHERE work_unit = ?", name);
        if (used > 0) {
            Flash.danger(req, "「" + name + "」已被 " + used + " 条业务记录引用，不能删除。");
            return "redirect:/org";
        }
        db.jdbc().update("DELETE FROM sys_org WHERE id = ?", id);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "delete", "sys_org", id, name, before, null);
        Flash.info(req, "已删除。");
        return "redirect:/org";
    }

    // =====================================================================
    // 报送单位
    // =====================================================================

    @GetMapping("/submit-unit")
    public String submitUnitIndex(HttpServletRequest req, Model model) {
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("units", Helpers.submitUnits(db.jdbc()));
        return "submitunit/index";
    }

    @PostMapping("/submit-unit/add")
    public String submitUnitAdd(HttpServletRequest req) {
        String name = trim(req, "name");
        if (name.isEmpty()) {
            Flash.danger(req, "请输入报送单位名称。");
            return "redirect:/submit-unit";
        }
        Long dup = db.jdbc().queryForObject(
                "SELECT COUNT(*) FROM sys_submit_unit WHERE name = ?", Long.class, name);
        if (dup != null && dup > 0) {
            Flash.danger(req, "报送单位「" + name + "」已存在。");
            return "redirect:/submit-unit";
        }
        long id = db.insert("INSERT INTO sys_submit_unit (name, contact, phone, sort_order) "
                + "VALUES (?, ?, ?, ?)", name, trim(req, "contact"), trim(req, "phone"),
                intOr(req, "sort_order", 0));
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "create", "sys_submit_unit", id, name, null,
                Helpers.rowSnapshot(db.jdbc(), "sys_submit_unit", id));
        Flash.success(req, "已添加：" + name);
        return "redirect:/submit-unit";
    }

    @PostMapping("/submit-unit/{id}/edit")
    public String submitUnitEdit(@PathVariable long id, HttpServletRequest req) {
        var before = Helpers.rowSnapshot(db.jdbc(), "sys_submit_unit", id);
        if (before == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/submit-unit";
        }
        String name = trim(req, "name");
        if (name.isEmpty()) {
            Flash.danger(req, "名称不能为空。");
            return "redirect:/submit-unit";
        }
        db.jdbc().update("UPDATE sys_submit_unit SET name=?, contact=?, phone=?, sort_order=? "
                + "WHERE id=?", name, trim(req, "contact"), trim(req, "phone"),
                intOr(req, "sort_order", 0), id);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "update", "sys_submit_unit", id, name, before,
                Helpers.rowSnapshot(db.jdbc(), "sys_submit_unit", id));
        Flash.success(req, "已更新：" + name);
        return "redirect:/submit-unit";
    }

    @PostMapping("/submit-unit/{id}/delete")
    public String submitUnitDelete(@PathVariable long id, HttpServletRequest req) {
        var before = Helpers.rowSnapshot(db.jdbc(), "sys_submit_unit", id);
        if (before == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/submit-unit";
        }
        String name = String.valueOf(before.get("name"));
        long used = count("SELECT COUNT(*) FROM decontrol_filing WHERE submit_unit_name = ?", name);
        if (used > 0) {
            Flash.danger(req, "「" + name + "」已被 " + used + " 条撤控记录引用，不能删除。");
            return "redirect:/submit-unit";
        }
        db.jdbc().update("DELETE FROM sys_submit_unit WHERE id = ?", id);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "delete", "sys_submit_unit", id, name, before, null);
        Flash.info(req, "已删除。");
        return "redirect:/submit-unit";
    }

    // =====================================================================
    // 全局搜索
    // =====================================================================

    private static final int SEARCH_LIMIT = 50;   // 每模块最多展示条数

    @GetMapping("/search")
    public String search(HttpServletRequest req, Model model) {
        String q = param(req, "q", "");
        List<Map<String, Object>> personnel = List.of();
        List<Map<String, Object>> certificates = List.of();
        List<Map<String, Object>> travels = List.of();
        List<Map<String, Object>> decontrols = List.of();
        List<Map<String, Object>> issuances = List.of();

        if (!q.isEmpty()) {
            String like = "%" + q + "%";
            personnel = db.jdbc().queryForList(
                    "SELECT id, surname, given_name, id_number, work_unit, status "
                    + "FROM personnel_filing WHERE surname||given_name LIKE ? OR id_number LIKE ? "
                    + "ORDER BY created_at DESC LIMIT ?", like, like, SEARCH_LIMIT);
            certificates = db.jdbc().queryForList(
                    "SELECT id, name, unit, passport_no, hm_pass_no, tw_pass_no FROM certificates "
                    + "WHERE name LIKE ? OR passport_no LIKE ? OR hm_pass_no LIKE ? OR tw_pass_no LIKE ? "
                    + "ORDER BY created_at DESC LIMIT ?", like, like, like, like, SEARCH_LIMIT);
            travels = db.jdbc().queryForList(
                    "SELECT id, name, destination_passport, travel_dates, trip_status "
                    + "FROM travel_details WHERE name LIKE ? OR destination_passport LIKE ? "
                    + "OR passport_no LIKE ? ORDER BY created_at DESC LIMIT ?",
                    like, like, like, SEARCH_LIMIT);
            decontrols = db.jdbc().queryForList(
                    "SELECT id, surname, given_name, work_unit, reason, decontrol_date "
                    + "FROM decontrol_filing WHERE surname||given_name LIKE ? OR id_number LIKE ? "
                    + "OR reason LIKE ? ORDER BY created_at DESC LIMIT ?",
                    like, like, like, SEARCH_LIMIT);
            issuances = db.jdbc().queryForList(
                    "SELECT id, holder_name, cert_nos, issue_date, status FROM cert_issuance "
                    + "WHERE holder_name LIKE ? OR id_number LIKE ? OR cert_nos LIKE ? "
                    + "ORDER BY issue_date DESC LIMIT ?", like, like, like, SEARCH_LIMIT);
        }

        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("q", q);
        model.addAttribute("personnel", personnel);
        model.addAttribute("certificates", certificates);
        model.addAttribute("travels", travels);
        model.addAttribute("decontrols", decontrols);
        model.addAttribute("issuances", issuances);
        model.addAttribute("total", personnel.size() + certificates.size() + travels.size()
                + decontrols.size() + issuances.size());
        return "search/results";
    }

    // ------------------------------------------------------------------

    private long count(String sql, Object... params) {
        Long n = db.jdbc().queryForObject(sql, Long.class, params);
        return n == null ? 0 : n;
    }

    private static int intOr(HttpServletRequest req, String name, int dflt) {
        String v = req.getParameter(name);
        if (v == null || v.isBlank()) {
            return dflt;
        }
        try {
            return Integer.parseInt(v.trim());
        } catch (NumberFormatException e) {
            return dflt;
        }
    }
}

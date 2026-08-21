package com.potms.web;

import com.potms.data.Db;
import com.potms.util.Validators;
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
import org.springframework.web.bind.annotation.RequestParam;

/** 人员备案 — 信息登记表 + 登记备案表。对应 Python 版 blueprints/personnel.py。 */
@Controller
public class PersonnelController {

    private final Db db;

    public PersonnelController(Db db) {
        this.db = db;
    }

    // =====================================================================
    // 列表
    // =====================================================================

    /** 列表 WHERE 拼装，供列表页与导出复用（pf / pi 别名）。 */
    public static Filter buildFilters(HttpServletRequest req, List<Long> ids) {
        Filter f = new Filter();
        f.like("(pf.surname||pf.given_name LIKE ? OR pf.id_number LIKE ? OR pf.work_unit LIKE ?)",
                req.getParameter("search"), 3);
        f.eq("pf.status", req.getParameter("status"));
        f.eq("pf.political_status", req.getParameter("political_status"));
        f.eq("pi.rank", req.getParameter("rank"));
        f.eq("pf.gender", req.getParameter("gender"));
        f.eq("pf.tag", req.getParameter("tag"));
        f.like("pf.residence LIKE ?", req.getParameter("residence"), 1);
        if (ids != null && !ids.isEmpty()) {
            f.and("pf.id IN (" + "?,".repeat(ids.size() - 1) + "?)", ids.toArray());
        }
        return f;
    }

    private static final Map<String, String> SORTS = new LinkedHashMap<>();

    static {
        SORTS.put("created_at_desc", "pf.created_at DESC");
        SORTS.put("created_at_asc", "pf.created_at ASC");
        SORTS.put("name_asc", "pf.surname||pf.given_name ASC");
        SORTS.put("birth_date_asc", "pf.birth_date ASC");
    }

    @GetMapping("/personnel")
    public String list(HttpServletRequest req, Model model) {
        Filter f = buildFilters(req, null);
        String sortBy = param(req, "sort", "created_at_desc");
        String orderBy = SORTS.getOrDefault(sortBy, "pf.created_at DESC");

        String sql = "SELECT pf.id, pf.surname, pf.given_name, pf.gender, pf.birth_date, "
                + "pf.id_number, pf.work_unit, pf.position_or_title, pf.tag, pf.status, "
                + "pf.created_at, pi.id AS info_id "
                + "FROM personnel_filing pf "
                + "LEFT JOIN personnel_info pi ON pf.personnel_info_id = pi.id "
                + "WHERE 1=1" + f.where() + " ORDER BY " + orderBy;

        model.addAttribute("ctx", Ctx.of(req));
        // 全量下发，前端按视口窗口化分页（与其它四版一致）
        model.addAttribute("items", Helpers.listAll(db.jdbc(), sql, f.params()));
        model.addAttribute("search", param(req, "search", ""));
        model.addAttribute("statusFilter", param(req, "status", ""));
        model.addAttribute("politicalFilter", param(req, "political_status", ""));
        model.addAttribute("rankFilter", param(req, "rank", ""));
        model.addAttribute("genderFilter", param(req, "gender", ""));
        model.addAttribute("tagFilter", param(req, "tag", ""));
        model.addAttribute("residenceFilter", param(req, "residence", ""));
        model.addAttribute("sortBy", sortBy);
        model.addAttribute("politicalOpts", Helpers.dictOptions(db.jdbc(), "political_status"));
        model.addAttribute("rankOpts", Helpers.dictOptions(db.jdbc(), "rank"));
        return "personnel/list";
    }

    // =====================================================================
    // 信息登记表
    // =====================================================================

    @GetMapping("/personnel/info")
    public String infoList(HttpServletRequest req, Model model) {
        Filter f = new Filter();
        f.like("(pi.name LIKE ? OR pi.id_number LIKE ? OR pi.unit LIKE ? OR pi.department LIKE ?)",
                req.getParameter("search"), 4);
        String refCount = "(SELECT COUNT(*) FROM personnel_filing pf WHERE pf.personnel_info_id = pi.id)";
        String ref = param(req, "ref", "");
        if ("orphan".equals(ref)) {
            f.and(refCount + " = 0");
        } else if ("linked".equals(ref)) {
            f.and(refCount + " > 0");
        }
        String sql = "SELECT pi.*, " + refCount + " AS filing_count "
                + "FROM personnel_info pi WHERE 1=1" + f.where() + " ORDER BY pi.id";

        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("items", Helpers.listAll(db.jdbc(), sql, f.params()));
        model.addAttribute("search", param(req, "search", ""));
        model.addAttribute("ref", ref);
        return "personnel/info_list";
    }

    @GetMapping("/personnel/info/new")
    public String infoNew(HttpServletRequest req, Model model) {
        return renderInfoForm(req, model, Map.of(), false, null);
    }

    @PostMapping("/personnel/info/new")
    public String infoCreate(HttpServletRequest req, Model model) {
        Map<String, String> data = extractInfoForm(req);
        List<String> errors = validateInfoForm(data);

        // 防重复：同一身份证号已存在信息登记表则拦截，避免产生同号孤儿行
        if (errors.isEmpty() && !data.get("id_number").isEmpty()) {
            var dup = db.jdbc().queryForList(
                    "SELECT id FROM personnel_info WHERE id_number = ? LIMIT 1",
                    data.get("id_number"));
            if (!dup.isEmpty()) {
                errors.add("该身份证号已存在信息登记表（编号 " + dup.get(0).get("id")
                        + "），如需修改请直接编辑该记录，请勿重复录入。");
            }
        }
        if (!errors.isEmpty()) {
            errors.forEach(e -> Flash.danger(req, e));
            return renderInfoForm(req, model, data, false, null);
        }

        long infoId = db.insert(
                "INSERT INTO personnel_info (unit, department, name, gender, birth_date, "
                + "id_number, work_start_date, education, degree, title, rank, political_status, "
                + "party_join_date, position, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                data.get("unit"), data.get("department"), data.get("name"), data.get("gender"),
                data.get("birth_date"), data.get("id_number"), data.get("work_start_date"),
                data.get("education"), data.get("degree"), data.get("title"), data.get("rank"),
                data.get("political_status"), data.get("party_join_date"), data.get("position"),
                data.get("operator"));
        log(req, "create", "personnel_info", infoId, null,
                Helpers.rowSnapshot(db.jdbc(), "personnel_info", infoId), null);
        Flash.success(req, "备案人员信息登记表已保存。请继续填写登记备案表。");
        return "redirect:/personnel/filing/new?info_id=" + infoId;
    }

    @GetMapping("/personnel/info/{id}/edit")
    public String infoEdit(@PathVariable long id, HttpServletRequest req, Model model) {
        var row = one("SELECT * FROM personnel_info WHERE id = ?", id);
        if (row == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/personnel";
        }
        return renderInfoForm(req, model, toStringMap(row), true, id);
    }

    @PostMapping("/personnel/info/{id}/edit")
    public String infoUpdate(@PathVariable long id, HttpServletRequest req, Model model) {
        if (one("SELECT id FROM personnel_info WHERE id = ?", id) == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/personnel";
        }
        Map<String, String> data = extractInfoForm(req);
        List<String> errors = validateInfoForm(data);
        if (!errors.isEmpty()) {
            errors.forEach(e -> Flash.danger(req, e));
            return renderInfoForm(req, model, data, true, id);
        }
        var before = Helpers.rowSnapshot(db.jdbc(), "personnel_info", id);
        db.jdbc().update(
                "UPDATE personnel_info SET unit=?, department=?, name=?, gender=?, birth_date=?, "
                + "id_number=?, work_start_date=?, education=?, degree=?, title=?, rank=?, "
                + "political_status=?, party_join_date=?, position=?, operator=?, "
                + "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                data.get("unit"), data.get("department"), data.get("name"), data.get("gender"),
                data.get("birth_date"), data.get("id_number"), data.get("work_start_date"),
                data.get("education"), data.get("degree"), data.get("title"), data.get("rank"),
                data.get("political_status"), data.get("party_join_date"), data.get("position"),
                data.get("operator"), id);
        log(req, "update", "personnel_info", id, before,
                Helpers.rowSnapshot(db.jdbc(), "personnel_info", id), null);
        Flash.success(req, "信息登记表已更新。");
        return "redirect:/personnel";
    }

    /** 物理删除信息登记表：仅当无任何备案记录引用时才允许，防止悬空外键。 */
    @PostMapping("/personnel/info/{id}/delete")
    public String infoDelete(@PathVariable long id, HttpServletRequest req) {
        if (one("SELECT id FROM personnel_info WHERE id = ?", id) == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/personnel/info";
        }
        long ref = countOf("SELECT COUNT(*) FROM personnel_filing WHERE personnel_info_id = ?", id);
        if (ref > 0) {
            Flash.danger(req, "该信息登记表已被 " + ref + " 条备案记录引用，不能删除。请先删除相关备案记录。");
            return "redirect:/personnel/info";
        }
        var before = Helpers.rowSnapshot(db.jdbc(), "personnel_info", id);
        db.jdbc().update("DELETE FROM personnel_info WHERE id = ?", id);
        log(req, "delete", "personnel_info", id, before, null, null);
        Flash.info(req, "信息登记表已删除。");
        return "redirect:/personnel/info";
    }

    // =====================================================================
    // 登记备案表
    // =====================================================================

    @GetMapping("/personnel/filing/new")
    public String filingNew(HttpServletRequest req, Model model,
                            @RequestParam(name = "info_id", required = false) Long infoId) {
        Map<String, String> prefill = new LinkedHashMap<>();
        if (infoId != null) {
            var info = one("SELECT * FROM personnel_info WHERE id = ?", infoId);
            if (info != null) {
                var split = Helpers.detectSurnameSplit(str(info.get("name")));
                prefill.put("surname", split.surname());
                prefill.put("given_name", split.givenName());
                prefill.put("gender", str(info.get("gender")));
                prefill.put("birth_date", str(info.get("birth_date")));
                prefill.put("id_number", str(info.get("id_number")));
                prefill.put("political_status", str(info.get("political_status")));
                prefill.put("work_unit", str(info.get("unit")));
                String pos = str(info.get("position"));
                prefill.put("position_or_title", pos.isEmpty() ? str(info.get("rank")) : pos);
            }
        }
        return renderFilingForm(req, model, prefill, false, null, infoId);
    }

    @PostMapping("/personnel/filing/new")
    public String filingCreate(HttpServletRequest req, Model model,
                               @RequestParam(name = "info_id", required = false) Long infoId) {
        Map<String, String> data = extractFilingForm(req);
        List<String> errors = validateFilingForm(data, false);
        if (!errors.isEmpty()) {
            errors.forEach(e -> Flash.danger(req, e));
            return renderFilingForm(req, model, data, false, null, infoId);
        }

        long filingId = db.insert(
                "INSERT INTO personnel_filing (personnel_info_id, surname, given_name, gender, "
                + "birth_date, id_number, residence, political_status, work_unit, "
                + "position_or_title, supervisor_unit, tag, informed, remarks, operator) "
                + "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                infoId, data.get("surname"), data.get("given_name"), data.get("gender"),
                data.get("birth_date"), data.get("id_number"), data.get("residence"),
                data.get("political_status"), data.get("work_unit"), data.get("position_or_title"),
                data.get("supervisor_unit"), data.get("tag"), data.get("informed"),
                data.getOrDefault("remarks", ""), data.get("operator"));

        // 撤控重报关联：存在同身份证的已撤控旧记录时，建立新旧关联并标记为「更新」
        var prior = db.jdbc().queryForList(
                "SELECT id FROM personnel_filing WHERE id_number = ? AND status = 'decontrolled' "
                + "AND replaced_by_id IS NULL AND id != ? ORDER BY id DESC LIMIT 1",
                data.get("id_number"), filingId);
        if (!prior.isEmpty()) {
            Object priorId = prior.get(0).get("id");
            db.jdbc().update("UPDATE personnel_filing SET replaced_by_id = ? WHERE id = ?",
                    filingId, priorId);
            db.jdbc().update("UPDATE personnel_filing SET tag = '更新' WHERE id = ?", filingId);
            Flash.info(req, "已与原撤控记录（#" + priorId + "）建立关联，本记录标记为“更新”。");
        }

        log(req, "create", "personnel_filing", filingId, null,
                Helpers.rowSnapshot(db.jdbc(), "personnel_filing", filingId), null);
        Flash.success(req, "登记备案表已保存。");
        return "redirect:/personnel";
    }

    @GetMapping("/personnel/filing/{id}/edit")
    public String filingEdit(@PathVariable long id, HttpServletRequest req, Model model) {
        var row = one("SELECT * FROM personnel_filing WHERE id = ?", id);
        if (row == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/personnel";
        }
        return renderFilingForm(req, model, toStringMap(row), true, id, null);
    }

    @PostMapping("/personnel/filing/{id}/edit")
    public String filingUpdate(@PathVariable long id, HttpServletRequest req, Model model) {
        if (one("SELECT id FROM personnel_filing WHERE id = ?", id) == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/personnel";
        }
        Map<String, String> data = extractFilingForm(req);
        List<String> errors = validateFilingForm(data, true);
        if (!errors.isEmpty()) {
            errors.forEach(e -> Flash.danger(req, e));
            return renderFilingForm(req, model, data, true, id, null);
        }
        var before = Helpers.rowSnapshot(db.jdbc(), "personnel_filing", id);
        db.jdbc().update(
                "UPDATE personnel_filing SET surname=?, given_name=?, gender=?, birth_date=?, "
                + "id_number=?, residence=?, political_status=?, work_unit=?, position_or_title=?, "
                + "supervisor_unit=?, tag=?, informed=?, remarks=?, operator=?, "
                + "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                data.get("surname"), data.get("given_name"), data.get("gender"),
                data.get("birth_date"), data.get("id_number"), data.get("residence"),
                data.get("political_status"), data.get("work_unit"), data.get("position_or_title"),
                data.get("supervisor_unit"), data.get("tag"), data.get("informed"),
                data.getOrDefault("remarks", ""), data.get("operator"), id);
        log(req, "update", "personnel_filing", id, before,
                Helpers.rowSnapshot(db.jdbc(), "personnel_filing", id), null);
        Flash.success(req, "登记备案表已更新。");
        return "redirect:/personnel";
    }

    @GetMapping("/personnel/{id}")
    public String view(@PathVariable long id, HttpServletRequest req, Model model) {
        var filing = one("SELECT * FROM personnel_filing WHERE id = ?", id);
        if (filing == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/personnel";
        }
        Map<String, Object> info = null;
        Object infoId = filing.get("personnel_info_id");
        if (infoId != null) {
            info = one("SELECT * FROM personnel_info WHERE id = ?", infoId);
        }
        // 撤控重报关联链路
        Map<String, Object> successor = null;
        Object replacedBy = filing.get("replaced_by_id");
        if (replacedBy != null) {
            successor = one("SELECT id, surname, given_name, created_at "
                    + "FROM personnel_filing WHERE id = ?", replacedBy);
        }
        var predecessor = one("SELECT id, surname, given_name, created_at "
                + "FROM personnel_filing WHERE replaced_by_id = ?", id);

        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("filing", filing);
        model.addAttribute("info", info);
        model.addAttribute("successor", successor);
        model.addAttribute("predecessor", predecessor);
        // 字典代码在控制器里解析成显示值，模板不再持有 JdbcTemplate
        Map<String, String> labels = new LinkedHashMap<>();
        if (info != null) {
            for (String cat : new String[] {"education", "degree", "title", "rank"}) {
                String code = str(info.get(cat));
                if (!code.isEmpty()) {
                    labels.put(cat, Helpers.dictValue(db.jdbc(), cat, code));
                }
            }
        }
        model.addAttribute("infoLabels", labels);
        return "personnel/view";
    }

    /**
     * 删除备案。名下若有证照 / 出国明细 / 撤控 / 领用记录（均以 NOT NULL 外键引用本表），
     * 直接 DELETE 会因外键约束静默失败，故先检查并给出明确提示。
     */
    @PostMapping("/personnel/{id}/delete")
    public String delete(@PathVariable long id, HttpServletRequest req) {
        if (one("SELECT id FROM personnel_filing WHERE id = ?", id) == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/personnel";
        }
        long certCnt = countOf("SELECT COUNT(*) FROM certificates WHERE personnel_filing_id = ?", id);
        long travelCnt = countOf("SELECT COUNT(*) FROM travel_details WHERE personnel_filing_id = ?", id);
        long decCnt = countOf("SELECT COUNT(*) FROM decontrol_filing WHERE personnel_filing_id = ?", id);
        long issCnt = countOf("SELECT COUNT(*) FROM cert_issuance WHERE personnel_filing_id = ?", id);
        if (certCnt + travelCnt + decCnt + issCnt > 0) {
            Flash.danger(req, "该人员名下尚有证照 " + certCnt + " 条、出国明细 " + travelCnt
                    + " 条、撤控记录 " + decCnt + " 条、证件领用 " + issCnt
                    + " 条，请先删除或处理这些关联记录后再删除备案。");
            return "redirect:/personnel";
        }
        var before = Helpers.rowSnapshot(db.jdbc(), "personnel_filing", id);
        db.jdbc().update("DELETE FROM personnel_filing WHERE id = ?", id);
        log(req, "delete", "personnel_filing", id, before, null, null);
        Flash.info(req, "备案记录已删除。");
        return "redirect:/personnel";
    }

    // =====================================================================
    // 表单提取与校验
    // =====================================================================

    private Map<String, String> extractInfoForm(HttpServletRequest req) {
        Map<String, String> d = new LinkedHashMap<>();
        d.put("unit", trim(req, "unit"));
        d.put("department", trim(req, "department"));
        d.put("name", trim(req, "name"));
        d.put("gender", trim(req, "gender"));
        d.put("birth_date", Validators.parseDateInput(req.getParameter("birth_date")));
        d.put("id_number", trim(req, "id_number").toUpperCase());
        d.put("work_start_date", Validators.parseDateInput(req.getParameter("work_start_date")));
        d.put("education", trim(req, "education"));
        d.put("degree", trim(req, "degree"));
        d.put("title", trim(req, "title"));
        d.put("rank", trim(req, "rank"));
        d.put("political_status", trim(req, "political_status"));
        d.put("party_join_date", Validators.parseDateInput(req.getParameter("party_join_date")));
        d.put("position", trim(req, "position"));
        // 操作人一律取自会话，不接受前端提交
        d.put("operator", operatorName(req));
        return d;
    }

    private List<String> validateInfoForm(Map<String, String> d) {
        List<String> errors = new ArrayList<>(Validators.checkRequired(d, List.of(
                new Validators.Field("unit", "单位"),
                new Validators.Field("department", "部门"),
                new Validators.Field("name", "姓名"),
                new Validators.Field("gender", "性别"),
                new Validators.Field("birth_date", "出生日期"),
                new Validators.Field("id_number", "身份证号"),
                new Validators.Field("work_start_date", "参加工作日期"),
                new Validators.Field("education", "学历"),
                new Validators.Field("degree", "学位"),
                new Validators.Field("title", "职称"),
                new Validators.Field("rank", "职级"),
                new Validators.Field("political_status", "政治面貌"),
                new Validators.Field("position", "职务（岗位名称）"))));
        errors.addAll(Validators.checkDates(d, List.of(
                new Validators.Field("birth_date", "出生日期"),
                new Validators.Field("work_start_date", "参加工作日期"),
                new Validators.Field("party_join_date", "入党日期"))));
        errors.addAll(Validators.checkIdentity(d));
        if (Validators.isPartyMember(d.get("political_status"))
                && d.get("party_join_date").isEmpty()) {
            errors.add("中共党员/预备党员须填写入党日期。");
        }
        return errors;
    }

    private Map<String, String> extractFilingForm(HttpServletRequest req) {
        Map<String, String> d = new LinkedHashMap<>();
        d.put("surname", trim(req, "surname"));
        d.put("given_name", trim(req, "given_name"));
        d.put("gender", trim(req, "gender"));
        d.put("birth_date", Validators.parseDateInput(req.getParameter("birth_date")));
        d.put("id_number", trim(req, "id_number").toUpperCase());
        d.put("residence", Helpers.normalizeResidence(req.getParameter("residence")));
        d.put("political_status", trim(req, "political_status"));
        d.put("work_unit", trim(req, "work_unit"));
        d.put("position_or_title", trim(req, "position_or_title"));
        d.put("supervisor_unit", trim(req, "supervisor_unit"));
        String tag = trim(req, "tag");
        d.put("tag", tag.isEmpty() ? "新增" : tag);
        String informed = trim(req, "informed");
        d.put("informed", informed.isEmpty() ? "否" : informed);
        d.put("remarks", trim(req, "remarks"));
        d.put("operator", operatorName(req));
        return d;
    }

    private List<String> validateFilingForm(Map<String, String> d, boolean skipDupCheck) {
        List<String> errors = new ArrayList<>(Validators.checkRequired(d, List.of(
                new Validators.Field("surname", "中文姓"),
                new Validators.Field("given_name", "中文名"),
                new Validators.Field("gender", "性别"),
                new Validators.Field("birth_date", "出生日期"),
                new Validators.Field("id_number", "身份证号"),
                new Validators.Field("residence", "户口所在地"),
                new Validators.Field("political_status", "政治面貌"),
                new Validators.Field("work_unit", "工作单位"),
                new Validators.Field("position_or_title", "职务（级）或职称"),
                new Validators.Field("supervisor_unit", "人事主管单位"),
                new Validators.Field("tag", "标记"),
                new Validators.Field("informed", "已告知本人"))));
        errors.addAll(Validators.checkDates(d,
                List.of(new Validators.Field("birth_date", "出生日期"))));
        errors.addAll(Validators.checkIdentity(d));

        if (!d.get("id_number").isEmpty() && !skipDupCheck) {
            var dup = db.jdbc().queryForList(
                    "SELECT id FROM personnel_filing WHERE id_number = ? AND status = 'active'",
                    d.get("id_number"));
            if (!dup.isEmpty()) {
                errors.add("该身份证号已存在有效备案记录，请勿重复登记。");
            }
        }
        return errors;
    }

    // =====================================================================

    private String renderInfoForm(HttpServletRequest req, Model model, Map<String, String> data,
                                  boolean editing, Long infoId) {
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("data", data);
        model.addAttribute("editing", editing);
        model.addAttribute("infoId", infoId);
        model.addAttribute("educationOpts", Helpers.dictOptions(db.jdbc(), "education"));
        model.addAttribute("degreeOpts", Helpers.dictOptions(db.jdbc(), "degree"));
        model.addAttribute("titleOpts", Helpers.dictOptions(db.jdbc(), "title"));
        model.addAttribute("rankOpts", Helpers.dictOptions(db.jdbc(), "rank"));
        model.addAttribute("politicalOpts", Helpers.dictOptions(db.jdbc(), "political_status"));
        model.addAttribute("orgOpts", Helpers.orgFlatOptions(db.jdbc()));
        return "personnel/info_form";
    }

    private String renderFilingForm(HttpServletRequest req, Model model, Map<String, String> data,
                                    boolean editing, Long filingId, Long infoId) {
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("data", data);
        model.addAttribute("editing", editing);
        model.addAttribute("filingId", filingId);
        model.addAttribute("infoId", infoId);
        model.addAttribute("politicalOpts", Helpers.dictOptions(db.jdbc(), "political_status"));
        model.addAttribute("supervisorOpts", Helpers.dictOptions(db.jdbc(), "supervisor_unit"));
        model.addAttribute("orgOpts", Helpers.orgTreeOptions(db.jdbc()));
        return "personnel/filing_form";
    }

    // ---- 小工具 ----

    private Map<String, Object> one(String sql, Object... params) {
        var rows = db.jdbc().queryForList(sql, params);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private long countOf(String sql, Object... params) {
        Long n = db.jdbc().queryForObject(sql, Long.class, params);
        return n == null ? 0 : n;
    }

    private void log(HttpServletRequest req, String action, String target, long id,
                     Map<String, Object> before, Map<String, Object> after, String detail) {
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                action, target, id, detail, before, after);
    }

    /**
     * 操作日志里的**操作人**：登录账号。
     *
     * <p>账号是身份标识，姓名可以随时改。日志只记「张三」的话，改名之后历史记录
     * 就对不上人了；展示时再按账号查出姓名，渲染成「张三（admin）」。
     */
    static String operator(HttpServletRequest req) {
        String u = SecurityFilters.currentUser(req);
        return u == null ? "admin" : u;
    }

    /**
     * 业务单据上的**经办人**：真实姓名，没填则回退到登录账号。
     *
     * <p>单据、打印件、导出表上的「经办人」必须是真人名字——打印出来的领用凭证上
     * 一个 admin，没法拿去归档。
     */
    static String operatorName(HttpServletRequest req) {
        String n = SecurityFilters.operatorName(req);
        return n == null ? "admin" : n;
    }

    static String trim(HttpServletRequest req, String name) {
        String v = req.getParameter(name);
        return v == null ? "" : v.trim();
    }

    static String param(HttpServletRequest req, String name, String dflt) {
        String v = req.getParameter(name);
        return (v == null || v.isBlank()) ? dflt : v.trim();
    }

    static String str(Object o) {
        return o == null ? "" : o.toString();
    }

    /** 数据库行 → 表单回填用的字符串映射。 */
    static Map<String, String> toStringMap(Map<String, Object> row) {
        Map<String, String> m = new LinkedHashMap<>();
        row.forEach((k, v) -> m.put(k, v == null ? "" : v.toString()));
        return m;
    }
}

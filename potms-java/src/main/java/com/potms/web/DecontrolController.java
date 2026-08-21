package com.potms.web;

import static com.potms.web.PersonnelController.operator;
import static com.potms.web.PersonnelController.operatorName;
import static com.potms.web.PersonnelController.param;
import static com.potms.web.PersonnelController.str;
import static com.potms.web.PersonnelController.trim;

import com.potms.Config;
import com.potms.data.Db;
import com.potms.util.Validators;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
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

/** 撤控备案。对应 Python 版 blueprints/decontrol.py。 */
@Controller
public class DecontrolController {

    private static final DateTimeFormatter YMD = DateTimeFormatter.ofPattern("yyyyMMdd");

    private final Db db;
    private final Config cfg;

    public DecontrolController(Db db, Config cfg) {
        this.db = db;
        this.cfg = cfg;
    }

    /** 列表 WHERE 拼装，供列表页与导出复用。 */
    public static Filter buildFilters(HttpServletRequest req, List<Long> ids) {
        Filter f = new Filter();
        f.like("(surname||given_name LIKE ? OR id_number LIKE ? OR reason LIKE ?)",
                req.getParameter("search"), 3);
        f.eq("submit_unit_type", req.getParameter("submit_unit_type"));
        if (ids != null && !ids.isEmpty()) {
            f.and("id IN (" + "?,".repeat(ids.size() - 1) + "?)", ids.toArray());
        }
        return f;
    }

    @GetMapping("/decontrol")
    public String list(HttpServletRequest req, Model model) {
        Filter f = buildFilters(req, null);
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("items", Helpers.listAll(db.jdbc(),
                "SELECT * FROM decontrol_filing WHERE 1=1" + f.where() + " ORDER BY created_at DESC",
                f.params()));
        model.addAttribute("search", param(req, "search", ""));
        model.addAttribute("unitTypeFilter", param(req, "submit_unit_type", ""));
        model.addAttribute("unitTypeOpts", Helpers.dictOptions(db.jdbc(), "submit_unit_type"));
        return "decontrol/list";
    }

    @GetMapping("/decontrol/new")
    public String newForm(HttpServletRequest req, Model model,
                          @RequestParam(name = "filing_id") long filingId) {
        var filing = filing(filingId);
        if (filing == null) {
            Flash.danger(req, "备案人员不存在。");
            return "redirect:/decontrol";
        }
        if ("decontrolled".equals(str(filing.get("status")))) {
            Flash.warning(req, "该人员已被撤控。");
            return "redirect:/personnel/" + filingId;
        }
        Map<String, String> prefill = new LinkedHashMap<>();
        for (String k : new String[] {"surname", "given_name", "gender", "birth_date",
                "id_number", "residence", "political_status", "work_unit", "supervisor_unit"}) {
            prefill.put(k, str(filing.get(k)));
        }
        prefill.put("decontrol_date", today());
        return render(req, model, prefill, filingId);
    }

    @PostMapping("/decontrol/new")
    public String create(HttpServletRequest req, Model model,
                         @RequestParam(name = "filing_id") long filingId) {
        var filing = filing(filingId);
        if (filing == null) {
            Flash.danger(req, "备案人员不存在。");
            return "redirect:/decontrol";
        }
        if ("decontrolled".equals(str(filing.get("status")))) {
            Flash.warning(req, "该人员已被撤控。");
            return "redirect:/personnel/" + filingId;
        }
        Map<String, String> data = extract(req);
        List<String> errors = validate(data);
        if (!errors.isEmpty()) {
            errors.forEach(e -> Flash.danger(req, e));
            return render(req, model, data, filingId);
        }

        long id = db.insert(
                "INSERT INTO decontrol_filing (personnel_filing_id, surname, given_name, gender, "
                + "birth_date, id_number, residence, political_status, work_unit, supervisor_unit, "
                + "submit_unit_name, submit_unit_type, submit_contact, submit_phone, batch_no, "
                + "reason, decontrol_date, cert_handover_date, operator) "
                + "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                filingId, data.get("surname"), data.get("given_name"), data.get("gender"),
                data.get("birth_date"), data.get("id_number"), data.get("residence"),
                data.get("political_status"), data.get("work_unit"), data.get("supervisor_unit"),
                data.get("submit_unit_name"), data.get("submit_unit_type"),
                data.get("submit_contact"), data.get("submit_phone"), data.get("batch_no"),
                data.get("reason"), data.get("decontrol_date"), data.get("cert_handover_date"),
                data.get("operator"));

        // 将原备案标记为已撤控
        db.jdbc().update("UPDATE personnel_filing SET status = 'decontrolled', "
                + "updated_at = CURRENT_TIMESTAMP WHERE id = ?", filingId);

        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "create", "decontrol_filing", id, null, null,
                Helpers.rowSnapshot(db.jdbc(), "decontrol_filing", id));
        Flash.success(req, "撤控备案已提交。该人员备案状态已标记为“已撤控”。");
        return "redirect:/personnel";
    }

    @GetMapping("/decontrol/{id}")
    public String view(@PathVariable long id, HttpServletRequest req, Model model) {
        var rows = db.jdbc().queryForList("SELECT * FROM decontrol_filing WHERE id = ?", id);
        if (rows.isEmpty()) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/decontrol";
        }
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("dec", rows.get(0));
        return "decontrol/view";
    }

    // ------------------------------------------------------------------

    private Map<String, String> extract(HttpServletRequest req) {
        Map<String, String> d = new LinkedHashMap<>();
        d.put("surname", trim(req, "surname"));
        d.put("given_name", trim(req, "given_name"));
        d.put("gender", trim(req, "gender"));
        d.put("birth_date", Validators.parseDateInput(req.getParameter("birth_date")));
        d.put("id_number", trim(req, "id_number").toUpperCase());
        d.put("residence", Helpers.normalizeResidence(req.getParameter("residence")));
        d.put("political_status", trim(req, "political_status"));
        d.put("work_unit", trim(req, "work_unit"));
        d.put("supervisor_unit", trim(req, "supervisor_unit"));
        d.put("submit_unit_name", trim(req, "submit_unit_name"));
        d.put("submit_unit_type", trim(req, "submit_unit_type"));
        d.put("submit_contact", trim(req, "submit_contact"));
        d.put("submit_phone", trim(req, "submit_phone"));
        d.put("batch_no", trim(req, "batch_no"));
        d.put("reason", trim(req, "reason"));
        String dd = Validators.parseDateInput(req.getParameter("decontrol_date"));
        d.put("decontrol_date", dd.isEmpty() ? today() : dd);
        d.put("cert_handover_date", Validators.parseDateInput(req.getParameter("cert_handover_date")));
        d.put("operator", operatorName(req));
        return d;
    }

    private List<String> validate(Map<String, String> d) {
        List<String> errors = new ArrayList<>(Validators.checkRequired(d, List.of(
                new Validators.Field("surname", "中文姓"),
                new Validators.Field("given_name", "中文名"),
                new Validators.Field("gender", "性别"),
                new Validators.Field("birth_date", "出生日期"),
                new Validators.Field("id_number", "身份证号"),
                new Validators.Field("residence", "户口所在地"),
                new Validators.Field("political_status", "政治面貌"),
                new Validators.Field("work_unit", "工作单位"),
                new Validators.Field("supervisor_unit", "人事主管单位"),
                new Validators.Field("submit_unit_name", "报送单位名称"),
                new Validators.Field("submit_unit_type", "报送单位类别"),
                new Validators.Field("submit_contact", "报送单位联系人"),
                new Validators.Field("submit_phone", "报送单位联系电话"),
                new Validators.Field("batch_no", "入库批号"),
                new Validators.Field("reason", "撤控原因"))));
        errors.addAll(Validators.checkDates(d, List.of(
                new Validators.Field("birth_date", "出生日期"),
                new Validators.Field("cert_handover_date", "证件移交日期"),
                new Validators.Field("decontrol_date", "撤控日期"))));
        errors.addAll(Validators.checkIdentity(d));
        return errors;
    }

    private String render(HttpServletRequest req, Model model, Map<String, String> data,
                          long filingId) {
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("data", data);
        model.addAttribute("filingId", filingId);
        model.addAttribute("politicalOpts", Helpers.dictOptions(db.jdbc(), "political_status"));
        model.addAttribute("supervisorOpts", Helpers.dictOptions(db.jdbc(), "supervisor_unit"));
        model.addAttribute("unitTypeOpts", Helpers.dictOptions(db.jdbc(), "submit_unit_type"));
        model.addAttribute("submitUnits", Helpers.submitUnits(db.jdbc()));
        return "decontrol/form";
    }

    private Map<String, Object> filing(long id) {
        var rows = db.jdbc().queryForList("SELECT * FROM personnel_filing WHERE id = ?", id);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private String today() {
        return LocalDate.ofInstant(java.time.Instant.now(),
                ZoneOffset.ofHours(cfg.tzOffsetHours)).format(YMD);
    }
}

package com.potms.web;

import static com.potms.web.PersonnelController.operator;
import static com.potms.web.PersonnelController.param;
import static com.potms.web.PersonnelController.str;
import static com.potms.web.PersonnelController.toStringMap;
import static com.potms.web.PersonnelController.trim;

import com.potms.Config;
import com.potms.data.Db;
import com.potms.util.Validators;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;

/** 证照登记 — 护照 / 港澳通行证 / 台湾通行证。对应 Python 版 blueprints/certificate.py。 */
@Controller
public class CertificateController {

    private static final DateTimeFormatter YMD = DateTimeFormatter.ofPattern("yyyyMMdd");

    /** 三类证件的字段组：证件号 / 有效期 / 上交日期 / 展示名。 */
    private static final String[][] KINDS = {
        {"passport_no", "passport_expiry", "passport_submit_date", "护照", "普通护照"},
        {"hm_pass_no", "hm_pass_expiry", "hm_pass_submit_date", "港澳通行证", "往来港澳通行证"},
        {"tw_pass_no", "tw_pass_expiry", "tw_pass_submit_date", "台湾通行证", "大陆居民往来台湾通行证"},
    };

    private final Db db;
    private final Config cfg;

    public CertificateController(Db db, Config cfg) {
        this.db = db;
        this.cfg = cfg;
    }

    /** 列表 WHERE 拼装，供列表页与导出复用。 */
    public static Filter buildFilters(HttpServletRequest req, List<Long> ids) {
        Filter f = new Filter();
        f.like("(name LIKE ? OR unit LIKE ?)", req.getParameter("search"), 2);
        has(f, "passport_no", req.getParameter("has_passport"));
        has(f, "hm_pass_no", req.getParameter("has_hm"));
        has(f, "tw_pass_no", req.getParameter("has_tw"));
        if (ids != null && !ids.isEmpty()) {
            f.and("id IN (" + "?,".repeat(ids.size() - 1) + "?)", ids.toArray());
        }
        return f;
    }

    private static void has(Filter f, String column, String flag) {
        if ("1".equals(flag)) {
            f.and(column + " IS NOT NULL AND " + column + " != ''");
        } else if ("0".equals(flag)) {
            f.and("(" + column + " IS NULL OR " + column + " = '')");
        }
    }

    /** 某条证照的临期提示：证件展示名 → 有效期。 */
    public record Expiring(String label, String expiry) {}

    @GetMapping("/certificate")
    public String list(HttpServletRequest req, Model model) {
        Filter f = buildFilters(req, null);
        var items = Helpers.listAll(db.jdbc(),
                "SELECT * FROM certificates WHERE 1=1" + f.where() + " ORDER BY updated_at DESC",
                f.params());

        LocalDate now = LocalDate.ofInstant(java.time.Instant.now(),
                ZoneOffset.ofHours(cfg.tzOffsetHours));
        String today = now.format(YMD);
        String warnDate = now.plusDays(Config.CERT_EXPIRY_WARN_DAYS).format(YMD);

        // 行 id → 临期证件清单（一条记录可能同时有多本证件临期）
        Map<Long, List<Expiring>> expiring = new HashMap<>();
        for (var row : items.rows()) {
            for (String[] k : KINDS) {
                String expiry = str(row.get(k[1]));
                if (!expiry.isEmpty() && today.compareTo(expiry) <= 0
                        && expiry.compareTo(warnDate) <= 0) {
                    expiring.computeIfAbsent(Fmt.n(row, "id"), x -> new ArrayList<>())
                            .add(new Expiring(k[4], expiry));
                }
            }
        }

        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("items", items);
        model.addAttribute("search", param(req, "search", ""));
        model.addAttribute("hasPassport", param(req, "has_passport", ""));
        model.addAttribute("hasHm", param(req, "has_hm", ""));
        model.addAttribute("hasTw", param(req, "has_tw", ""));
        model.addAttribute("expiring", expiring);
        return "certificate/list";
    }

    @GetMapping("/certificate/new")
    public String newForm(HttpServletRequest req, Model model,
                          @RequestParam(name = "filing_id", required = false) Long filingId) {
        Map<String, String> prefill = new LinkedHashMap<>();
        if (filingId != null) {
            // 单位优先取信息登记表里的「单位」，缺失时回退备案表的「工作单位」
            var rows = db.jdbc().queryForList(
                    "SELECT id, work_unit, surname, given_name, "
                    + "COALESCE((SELECT unit FROM personnel_info WHERE id = "
                    + "  personnel_filing.personnel_info_id), work_unit) AS unit_val "
                    + "FROM personnel_filing WHERE id = ?", filingId);
            if (!rows.isEmpty()) {
                var r = rows.get(0);
                prefill.put("personnel_filing_id", String.valueOf(filingId));
                String unit = str(r.get("unit_val"));
                prefill.put("unit", unit.isEmpty() ? str(r.get("work_unit")) : unit);
                prefill.put("department", "");
                prefill.put("name", str(r.get("surname")) + str(r.get("given_name")));
            }
        }
        return render(req, model, prefill, false, null);
    }

    @PostMapping("/certificate/new")
    public String create(HttpServletRequest req, Model model) {
        Map<String, String> data = extract(req);
        List<String> errors = validate(data);
        if (!errors.isEmpty()) {
            errors.forEach(e -> Flash.danger(req, e));
            return render(req, model, data, false, null);
        }
        long id = db.insert(
                "INSERT INTO certificates (personnel_filing_id, unit, department, name, "
                + "passport_no, passport_expiry, passport_submit_date, "
                + "hm_pass_no, hm_pass_expiry, hm_pass_submit_date, "
                + "tw_pass_no, tw_pass_expiry, tw_pass_submit_date, operator) "
                + "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                values(data));
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "create", "certificate", id, null, null,
                Helpers.rowSnapshot(db.jdbc(), "certificates", id));
        Flash.success(req, "证照登记已保存。");
        return "redirect:/certificate";
    }

    @GetMapping("/certificate/{id}/edit")
    public String editForm(@PathVariable long id, HttpServletRequest req, Model model) {
        var row = one(id);
        if (row == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/certificate";
        }
        return render(req, model, toStringMap(row), true, id);
    }

    @PostMapping("/certificate/{id}/edit")
    public String update(@PathVariable long id, HttpServletRequest req, Model model) {
        if (one(id) == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/certificate";
        }
        Map<String, String> data = extract(req);
        List<String> errors = validate(data);
        if (!errors.isEmpty()) {
            errors.forEach(e -> Flash.danger(req, e));
            return render(req, model, data, true, id);
        }
        var before = Helpers.rowSnapshot(db.jdbc(), "certificates", id);
        Object[] v = values(data);
        Object[] withId = new Object[v.length + 1];
        System.arraycopy(v, 0, withId, 0, v.length);
        withId[v.length] = id;
        db.jdbc().update(
                "UPDATE certificates SET personnel_filing_id=?, unit=?, department=?, name=?, "
                + "passport_no=?, passport_expiry=?, passport_submit_date=?, "
                + "hm_pass_no=?, hm_pass_expiry=?, hm_pass_submit_date=?, "
                + "tw_pass_no=?, tw_pass_expiry=?, tw_pass_submit_date=?, "
                + "operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", withId);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "update", "certificate", id, null, before,
                Helpers.rowSnapshot(db.jdbc(), "certificates", id));
        Flash.success(req, "证照信息已更新。");
        return "redirect:/certificate";
    }

    @PostMapping("/certificate/{id}/delete")
    public String delete(@PathVariable long id, HttpServletRequest req) {
        if (one(id) == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/certificate";
        }
        var before = Helpers.rowSnapshot(db.jdbc(), "certificates", id);
        db.jdbc().update("DELETE FROM certificates WHERE id = ?", id);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "delete", "certificate", id, null, before, null);
        Flash.info(req, "证照记录已删除。");
        return "redirect:/certificate";
    }

    // ------------------------------------------------------------------

    private Map<String, String> extract(HttpServletRequest req) {
        Map<String, String> d = new LinkedHashMap<>();
        d.put("personnel_filing_id", trim(req, "personnel_filing_id"));
        d.put("unit", trim(req, "unit"));
        d.put("department", trim(req, "department"));
        d.put("name", trim(req, "name"));
        for (String[] k : KINDS) {
            d.put(k[0], trim(req, k[0]));
            d.put(k[1], Validators.parseDateInput(req.getParameter(k[1])));
            d.put(k[2], Validators.parseDateInput(req.getParameter(k[2])));
        }
        d.put("operator", operator(req));
        return d;
    }

    private List<String> validate(Map<String, String> d) {
        List<String> errors = new ArrayList<>(Validators.checkRequired(d, List.of(
                new Validators.Field("personnel_filing_id", "备案人员"),
                new Validators.Field("unit", "单位"),
                new Validators.Field("department", "部门"),
                new Validators.Field("name", "姓名"))));
        errors.addAll(Validators.checkDates(d, List.of(
                new Validators.Field("passport_expiry", "护照有效日期"),
                new Validators.Field("passport_submit_date", "护照上交日期"),
                new Validators.Field("hm_pass_expiry", "港澳通行证有效日期"),
                new Validators.Field("hm_pass_submit_date", "港澳通行证上交日期"),
                new Validators.Field("tw_pass_expiry", "台湾通行证有效日期"),
                new Validators.Field("tw_pass_submit_date", "台湾通行证上交日期"))));

        // 填写证件号时，有效日期与上交日期均为必填
        for (String[] k : KINDS) {
            if (!d.getOrDefault(k[0], "").isEmpty()) {
                if (d.getOrDefault(k[1], "").isEmpty()) {
                    errors.add("填写" + k[3] + "证件号时，有效日期为必填。");
                }
                if (d.getOrDefault(k[2], "").isEmpty()) {
                    errors.add("填写" + k[3] + "证件号时，上交日期为必填。");
                }
            }
        }
        return errors;
    }

    /** INSERT / UPDATE 共用的参数顺序。 */
    private Object[] values(Map<String, String> d) {
        String pfid = d.get("personnel_filing_id");
        return new Object[] {
            pfid == null || pfid.isEmpty() ? null : Long.valueOf(pfid),
            d.get("unit"), d.get("department"), d.get("name"),
            d.get("passport_no"), d.get("passport_expiry"), d.get("passport_submit_date"),
            d.get("hm_pass_no"), d.get("hm_pass_expiry"), d.get("hm_pass_submit_date"),
            d.get("tw_pass_no"), d.get("tw_pass_expiry"), d.get("tw_pass_submit_date"),
            d.get("operator"),
        };
    }

    private String render(HttpServletRequest req, Model model, Map<String, String> data,
                          boolean editing, Long certId) {
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("data", data);
        model.addAttribute("editing", editing);
        model.addAttribute("certId", certId);
        model.addAttribute("people", Helpers.personnelOptions(db.jdbc()));
        return "certificate/form";
    }

    private Map<String, Object> one(long id) {
        var rows = db.jdbc().queryForList("SELECT * FROM certificates WHERE id = ?", id);
        return rows.isEmpty() ? null : rows.get(0);
    }
}

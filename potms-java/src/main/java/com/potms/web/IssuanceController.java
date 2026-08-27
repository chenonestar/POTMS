package com.potms.web;

import static com.potms.web.PersonnelController.operator;
import static com.potms.web.PersonnelController.operatorName;
import static com.potms.web.PersonnelController.param;
import static com.potms.web.PersonnelController.str;
import static com.potms.web.PersonnelController.trim;

import com.potms.Config;
import com.potms.data.Db;
import com.potms.service.IssuanceOps;
import com.potms.service.SealStore;
import com.potms.service.Signature;
import com.potms.util.Validators;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.CacheControl;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;

/**
 * 证件领用管理 — 领用登记 / 归还登记 / 作废，含手写签名。
 * 对应 Python 版 blueprints/issuance.py。
 *
 * <p>三条与业务方审定过的约束：
 * <ol>
 *   <li>本模块是「证件领用/归还日期」的<b>唯一写入方</b>；travel_details 上那两个
 *       字段降级为派生只读，由本模块回写，杜绝双数据源。
 *   <li>签名一经保存<b>不可编辑</b>，登记有误只能作废后重新登记，
 *       以保证签名凭证的证据效力。
 *   <li>签名以 PNG 位图 + 笔迹矢量双存于数据库，随每日备份落盘；不落文件系统。
 * </ol>
 */
@Controller
public class IssuanceController {

    private static final DateTimeFormatter YMD = DateTimeFormatter.ofPattern("yyyyMMdd");

    /** 列表/导出共用：JOIN 备案表以排除孤儿行（延续既有数据完整性口径）。 */
    public static final String BASE_SELECT =
            "SELECT i.*, pf.work_unit AS work_unit "
            + "FROM cert_issuance i "
            + "JOIN personnel_filing pf ON i.personnel_filing_id = pf.id "
            + "WHERE 1=1";

    private final Db db;
    private final Config cfg;
    private final SealStore seals;

    public IssuanceController(Db db, Config cfg, SealStore seals) {
        this.db = db;
        this.cfg = cfg;
        this.seals = seals;
    }

    /** 列表 WHERE 拼装，供列表页与导出复用。 */
    public static Filter buildFilters(HttpServletRequest req, List<Long> ids) {
        Filter f = new Filter();
        f.like("(i.holder_name LIKE ? OR i.id_number LIKE ? OR i.cert_nos LIKE ?)",
                req.getParameter("search"), 3);
        String status = param(req, "status", "");
        if (List.of("issued", "returned", "voided").contains(status)) {
            f.and("i.status = ?", status);
        }
        String certType = param(req, "cert_type", "");
        if (IssuanceOps.CERT_TYPE_PENDING.equals(certType)) {
            // 历史回填里判不出种类的那批，cert_types 为空。下面那句 LIKE 对空值恒不
            // 匹配（'' 拼出来是 ',,'），所以单开一条——不能筛出来，这批待办就没法收口。
            f.and("(i.cert_types IS NULL OR i.cert_types = '')");
        } else if (!certType.isEmpty()) {
            // cert_types 存的是逗号串，两侧补逗号后做包含匹配，避免 1 命中 01
            f.and("(',' || i.cert_types || ',') LIKE ?", "%," + certType + ",%");
        }
        String from = Validators.parseDateInput(req.getParameter("date_from"));
        if (!from.isEmpty()) {
            f.and("i.issue_date >= ?", from);
        }
        String to = Validators.parseDateInput(req.getParameter("date_to"));
        if (!to.isEmpty()) {
            f.and("i.issue_date <= ?", to);
        }
        if (ids != null && !ids.isEmpty()) {
            f.and("i.id IN (" + "?,".repeat(ids.size() - 1) + "?)", ids.toArray());
        }
        return f;
    }

    @GetMapping("/issuance")
    public String list(HttpServletRequest req, Model model) {
        Filter f = buildFilters(req, null);
        var items = Helpers.listAll(db.jdbc(),
                BASE_SELECT + f.where() + " ORDER BY i.issue_date DESC, i.id DESC", f.params());

        // 每行的证件种类展示名，模板里不便逐行查字典
        Map<Long, String> labels = new LinkedHashMap<>();
        for (var r : items.rows()) {
            labels.put(Fmt.n(r, "id"), IssuanceOps.typesLabel(db.jdbc(), str(r.get("cert_types"))));
        }

        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("items", items);
        model.addAttribute("typeLabels", labels);
        model.addAttribute("search", param(req, "search", ""));
        model.addAttribute("statusFilter", param(req, "status", ""));
        model.addAttribute("certTypeFilter", param(req, "cert_type", ""));
        model.addAttribute("dateFrom", param(req, "date_from", ""));
        model.addAttribute("dateTo", param(req, "date_to", ""));
        model.addAttribute("certTypeOpts", Helpers.dictOptions(db.jdbc(), "cert_type"));
        return "issuance/list";
    }

    // =====================================================================
    // 新建领用
    // =====================================================================

    @GetMapping("/issuance/new")
    public String newForm(HttpServletRequest req, Model model,
                          @RequestParam(name = "travel_id", required = false) Long travelId) {
        Map<String, String> prefill = new LinkedHashMap<>();
        prefill.put("issue_date", today());
        var travel = travelBrief(travelId);
        // 领用必须挂在一条出国申请上。直接进本页（没带 travel_id）时，先让经办人挑一条
        // 申请，挑完再进登记表单——而不是给个能填空的表单，让人有机会登记出一条无主的
        // 领用记录。
        if (travel == null) {
            if (travelId != null) {
                Flash.warning(req, "指定的出国申请不存在。");
            }
            model.addAttribute("ctx", Ctx.of(req));
            model.addAttribute("travels", IssuanceOps.eligibleTravels(db.jdbc()));
            return "issuance/pick_travel";
        }
        prefill.put("travel_id", String.valueOf(travelId));
        prefill.put("personnel_filing_id", str(travel.get("personnel_filing_id")));
        prefill.put("holder_name", str(travel.get("name")));
        prefill.put("id_number", str(travel.get("id_number")));
        return render(req, model, prefill, travel);
    }

    @PostMapping("/issuance/new")
    public String create(HttpServletRequest req, Model model) {
        Map<String, String> data = extract(req);
        List<String> errors = validate(data);
        var sig = Signature.decode(req.getParameter("sign_png"), cfg.requireSignature);
        // 判据是 error 而不是 ok()：放宽模式下留空是**合法**结果，
        // 此时 bytes 为 null（ok() 为 false）但 error 为空，不该拦下。
        if (!sig.error().isEmpty()) {
            errors.add(sig.error());
        }
        if (!errors.isEmpty()) {
            errors.forEach(e -> Flash.danger(req, e));
            return render(req, model, data, travelBrief(longOrNull(data.get("travel_id"))));
        }

        Long travelId = longOrNull(data.get("travel_id"));
        long id = db.insert(
                "INSERT INTO cert_issuance (travel_id, personnel_filing_id, holder_name, id_number, "
                + "cert_types, cert_nos, issue_date, issuer, sign_image, sign_meta, status, "
                + "remarks, operator) VALUES (?,?,?,?,?,?,?,?,?,?,'issued',?,?)",
                travelId, longOrNull(data.get("personnel_filing_id")), data.get("holder_name"),
                data.get("id_number"), data.get("cert_types"), data.get("cert_nos"),
                data.get("issue_date"), data.get("issuer"), sig.bytes(),
                Signature.cleanMeta(req.getParameter("sign_meta")),
                data.get("remarks"), data.get("operator"));

        IssuanceOps.syncTravelDerived(db.jdbc(), travelId);
        sealQuietly(req, id, "issue", sig.bytes(), Signature.cleanMeta(req.getParameter("sign_meta")));
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "create", "cert_issuance", id,
                "证件领用登记：" + data.get("holder_name") + "，"
                        + IssuanceOps.typesLabel(db.jdbc(), data.get("cert_types")),
                null, Helpers.rowSnapshot(db.jdbc(), "cert_issuance", id));
        Flash.success(req, "证件领用登记已保存。");
        return "redirect:/issuance/" + id;
    }

    @GetMapping("/issuance/{id}")
    public String view(@PathVariable long id, HttpServletRequest req, Model model) {
        var row = one(id);
        if (row == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/issuance";
        }
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("item", row);
        model.addAttribute("travel", travelBrief(longOrNull(str(row.get("travel_id")))));
        model.addAttribute("typeLabels", IssuanceOps.typesLabel(db.jdbc(), str(row.get("cert_types"))));
        model.addAttribute("canFix", IssuanceOps.canFixCertTypes(row));
        model.addAttribute("certTypeOpts", Helpers.dictOptions(db.jdbc(), "cert_type"));
        model.addAttribute("issueSeal", seals.verify(db.jdbc(), id, "issue",
                blob(row.get("sign_image")), str(row.get("sign_meta")), row));
        model.addAttribute("returnSeal", seals.verify(db.jdbc(), id, "return",
                blob(row.get("return_sign_image")), str(row.get("return_sign_meta")), row));
        return "issuance/view";
    }

    // =====================================================================
    // 归还登记（同样需签名）
    // =====================================================================

    @GetMapping("/issuance/{id}/return")
    public String returnForm(@PathVariable long id, HttpServletRequest req, Model model) {
        var row = one(id);
        if (row == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/issuance";
        }
        if (!"issued".equals(str(row.get("status")))) {
            Flash.warning(req, "该记录不是「已领用」状态，无法办理归还。");
            return "redirect:/issuance/" + id;
        }
        return renderReturn(req, model, row, today());
    }

    @PostMapping("/issuance/{id}/return")
    public String doReturn(@PathVariable long id, HttpServletRequest req, Model model) {
        var row = one(id);
        if (row == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/issuance";
        }
        if (!"issued".equals(str(row.get("status")))) {
            Flash.warning(req, "该记录不是「已领用」状态，无法办理归还。");
            return "redirect:/issuance/" + id;
        }

        String returnDate = Validators.parseDateInput(req.getParameter("return_date"));
        List<String> errors = new ArrayList<>();
        if (returnDate.isEmpty()) {
            errors.add("归还日期为必填项。");
        } else {
            errors.addAll(Validators.checkDates(Map.of("return_date", returnDate),
                    List.of(new Validators.Field("return_date", "归还日期"))));
            String issueDate = str(row.get("issue_date"));
            if (returnDate.compareTo(issueDate) < 0) {
                errors.add("归还日期不应早于领用日期（" + issueDate + "）。");
            }
        }
        var sig = Signature.decode(req.getParameter("sign_png"), cfg.requireSignature);
        // 判据是 error 而不是 ok()：放宽模式下留空是**合法**结果，
        // 此时 bytes 为 null（ok() 为 false）但 error 为空，不该拦下。
        if (!sig.error().isEmpty()) {
            errors.add(sig.error());
        }
        if (!errors.isEmpty()) {
            errors.forEach(e -> Flash.danger(req, e));
            return renderReturn(req, model, row, returnDate);
        }

        var before = Helpers.rowSnapshot(db.jdbc(), "cert_issuance", id);
        db.jdbc().update(
                "UPDATE cert_issuance SET return_date=?, return_sign_image=?, return_sign_meta=?, "
                + "return_operator=?, status='returned', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                returnDate, sig.bytes(), Signature.cleanMeta(req.getParameter("sign_meta")),
                operatorName(req), id);

        IssuanceOps.syncTravelDerived(db.jdbc(), longOrNull(str(row.get("travel_id"))));
        sealQuietly(req, id, "return", sig.bytes(),
                Signature.cleanMeta(req.getParameter("sign_meta")));
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "update", "cert_issuance", id,
                "证件归还登记：" + str(row.get("holder_name")) + "，归还日期 " + returnDate,
                before, Helpers.rowSnapshot(db.jdbc(), "cert_issuance", id));
        Flash.success(req, "证件归还登记已保存。");
        return "redirect:/issuance/" + id;
    }

    // =====================================================================
    // 作废（签名不可编辑，登记有误走此路径）
    // =====================================================================

    @PostMapping("/issuance/{id}/void")
    public String voidRecord(@PathVariable long id, HttpServletRequest req) {
        var row = one(id);
        if (row == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/issuance";
        }
        if ("voided".equals(str(row.get("status")))) {
            Flash.info(req, "该记录已是作废状态。");
            return "redirect:/issuance/" + id;
        }
        String reason = trim(req, "void_reason");
        if (reason.isEmpty()) {
            Flash.danger(req, "作废原因为必填项。");
            return "redirect:/issuance/" + id;
        }
        var before = Helpers.rowSnapshot(db.jdbc(), "cert_issuance", id);
        db.jdbc().update("UPDATE cert_issuance SET status='voided', void_reason=?, "
                + "updated_at=CURRENT_TIMESTAMP WHERE id=?", reason, id);
        IssuanceOps.syncTravelDerived(db.jdbc(), longOrNull(str(row.get("travel_id"))));
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "void", "cert_issuance", id,
                "领用记录作废：" + str(row.get("holder_name")) + "，原因：" + reason,
                before, Helpers.rowSnapshot(db.jdbc(), "cert_issuance", id));
        Flash.info(req, "领用记录已作废，如需更正请重新登记。");
        return "redirect:/issuance/" + id;
    }

    // =====================================================================
    // 更正证件种类（仅限无签名的记录）
    // =====================================================================

    /**
     * 人工更正历史回填的证件种类。
     *
     * <p>没有这个入口，「判不出就留空」等于制造一批永远填不上的死数据：新建强制签名，
     * 回填行没有签名也无从重录，只能就地更正。判据见
     * {@link IssuanceOps#canFixCertTypes}。
     */
    @PostMapping("/issuance/{id}/cert-types")
    public String fixCertTypes(@PathVariable long id, HttpServletRequest req) {
        var row = one(id);
        if (row == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/issuance";
        }
        if (!IssuanceOps.canFixCertTypes(row)) {
            Flash.warning(req, "该记录已有领用人签名，证件种类不可更改；如登记有误请作废后重新登记。");
            return "redirect:/issuance/" + id;
        }

        List<String> picked = new ArrayList<>();
        String[] raw = req.getParameterValues("cert_types");
        if (raw != null) {
            for (String t : raw) {
                if (t != null && !t.isBlank()) {
                    picked.add(t.trim());
                }
            }
        }
        for (String c : picked) {
            if (!IssuanceOps.CERT_NO_FIELD.containsKey(c)) {
                Flash.danger(req, "无效的证件种类代码：" + c + "。");
                return "redirect:/issuance/" + id;
            }
        }
        if (picked.isEmpty()) {
            Flash.danger(req, "请选择证件种类。");
            return "redirect:/issuance/" + id;
        }
        // 与新建同一条规则：一次出国申请只领一本证
        if (picked.size() > 1) {
            Flash.danger(req, "一次出国申请只能领用一本证件。");
            return "redirect:/issuance/" + id;
        }

        var before = Helpers.rowSnapshot(db.jdbc(), "cert_issuance", id);
        // 备注里「待核实 / 按护照推定」这类字样已经不成立，一并清掉；
        // 人工核定的结果不该继续挂着机器推断的说明。
        String remarks = str(row.get("remarks"));
        if (remarks.startsWith("历史数据回填")) {
            remarks = "历史数据回填（证件种类已人工核定，无签名）";
        }
        String joined = String.join(",", picked);
        String oldLabel = IssuanceOps.typesLabel(db.jdbc(), str(row.get("cert_types")));
        String newLabel = IssuanceOps.typesLabel(db.jdbc(), joined);
        db.jdbc().update("UPDATE cert_issuance SET cert_types=?, remarks=?, "
                + "updated_at=CURRENT_TIMESTAMP WHERE id=?", joined, remarks, id);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "update", "cert_issuance", id,
                "更正证件种类：" + str(row.get("holder_name")) + "，" + oldLabel + " → " + newLabel,
                before, Helpers.rowSnapshot(db.jdbc(), "cert_issuance", id));
        Flash.success(req, "证件种类已更正。");
        return "redirect:/issuance/" + id;
    }

    // =====================================================================
    // 签名图片服务
    // =====================================================================

    @GetMapping("/issuance/{id}/signature.png")
    public ResponseEntity<byte[]> signature(@PathVariable long id,
                                            @RequestParam(defaultValue = "issue") String kind) {
        // 列名不能来自参数拼接，此处用白名单二选一
        String col = "return".equals(kind) ? "return_sign_image" : "sign_image";
        var rows = db.jdbc().queryForList(
                "SELECT " + col + " AS img FROM cert_issuance WHERE id = ?", id);
        if (rows.isEmpty() || !(rows.get(0).get("img") instanceof byte[] img) || img.length == 0) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok()
                .contentType(MediaType.IMAGE_PNG)
                // 签名一经保存不可变，可长期缓存
                .cacheControl(CacheControl.maxAge(java.time.Duration.ofDays(1)).cachePrivate())
                .body(img);
    }

    // =====================================================================

    private Map<String, String> extract(HttpServletRequest req) {
        String[] types = req.getParameterValues("cert_types");
        List<String> picked = new ArrayList<>();
        if (types != null) {
            for (String t : types) {
                if (t != null && !t.isBlank()) {
                    picked.add(t.trim());
                }
            }
        }
        Map<String, String> d = new LinkedHashMap<>();
        d.put("travel_id", trim(req, "travel_id"));
        d.put("personnel_filing_id", trim(req, "personnel_filing_id"));
        d.put("holder_name", trim(req, "holder_name"));
        d.put("id_number", trim(req, "id_number"));
        d.put("cert_types", String.join(",", picked));
        d.put("cert_nos", trim(req, "cert_nos"));
        d.put("issue_date", Validators.parseDateInput(req.getParameter("issue_date")));
        String issuer = trim(req, "issuer");
        d.put("issuer", issuer.isEmpty() ? operatorName(req) : issuer);
        d.put("remarks", trim(req, "remarks"));
        d.put("operator", operatorName(req));
        return d;
    }

    private List<String> validate(Map<String, String> d) {
        List<String> errors = new ArrayList<>(Validators.checkRequired(d, List.of(
                // 领用必须挂在一条出国申请上：证件是为某一次已批准的出行借出的，没有
                // 申请就没有借出的理由。无主的领用记录还会掉出逾期告警——告警按出行
                // 记录来算，挂不上申请的记录没人盯。
                new Validators.Field("travel_id", "关联出国申请"),
                new Validators.Field("personnel_filing_id", "领用人（备案人员）"),
                new Validators.Field("holder_name", "领用人姓名"),
                new Validators.Field("cert_types", "领用证件种类"),
                new Validators.Field("issue_date", "领用日期"))));
        errors.addAll(Validators.checkDates(d,
                List.of(new Validators.Field("issue_date", "领用日期"))));

        // 证件种类必须是字典内的合法代码。一次申请一本证，所以只能有一个。
        int codeCount = 0;
        for (String c : d.getOrDefault("cert_types", "").split(",")) {
            if (c.isEmpty()) {
                continue;
            }
            codeCount++;
            if (!IssuanceOps.CERT_NO_FIELD.containsKey(c)) {
                errors.add("无效的证件种类代码：" + c + "。");
            }
        }
        if (codeCount > 1) {
            errors.add("一次出国申请只能领用一本证件；需要多本请分别提交出国申请。");
        }

        Long travelId = longOrNull(d.get("travel_id"));
        if (travelId != null) {
            var tv = db.jdbc().queryForList(
                    "SELECT personnel_filing_id, trip_status FROM travel_details WHERE id = ?",
                    travelId);
            if (tv.isEmpty()) {
                errors.add("关联的出国申请不存在。");
            } else {
                if ("cancelled".equals(str(tv.get(0).get("trip_status")))) {
                    errors.add("该出国申请已取消行程，不能办理证件领用。");
                }
                // 领用人必须就是申请人——证是为这条申请借的，不能借给别人
                if (!str(tv.get(0).get("personnel_filing_id"))
                        .equals(d.getOrDefault("personnel_filing_id", ""))) {
                    errors.add("领用人与该出国申请的申请人不一致。");
                }
            }
            // 同一出行下不允许重复的未归还领用记录
            var dup = db.jdbc().queryForList(
                    "SELECT id FROM cert_issuance WHERE travel_id = ? AND status = 'issued'",
                    travelId);
            if (!dup.isEmpty()) {
                errors.add("该出行记录已有未归还的领用记录（#" + dup.get(0).get("id")
                        + "），请先办理归还或作废。");
            }
        }
        return errors;
    }

    private String render(HttpServletRequest req, Model model, Map<String, String> data,
                          Map<String, Object> travel) {
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("data", data);
        model.addAttribute("travel", travel);
        model.addAttribute("people", Helpers.personnelOptions(db.jdbc()));
        model.addAttribute("certTypeOpts", Helpers.dictOptions(db.jdbc(), "cert_type"));
        return "issuance/form";
    }

    private String renderReturn(HttpServletRequest req, Model model,
                                Map<String, Object> row, String returnDate) {
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("item", row);
        model.addAttribute("returnDate", returnDate);
        model.addAttribute("typeLabels", IssuanceOps.typesLabel(db.jdbc(), str(row.get("cert_types"))));
        return "issuance/return";
    }

    private Map<String, Object> one(long id) {
        var rows = db.jdbc().queryForList(
                "SELECT i.*, pf.work_unit FROM cert_issuance i "
                + "JOIN personnel_filing pf ON i.personnel_filing_id = pf.id WHERE i.id = ?", id);
        return rows.isEmpty() ? null : rows.get(0);
    }

    /** 出行记录摘要（用于带入与展示）。 */
    private Map<String, Object> travelBrief(Long travelId) {
        if (travelId == null) {
            return null;
        }
        var rows = db.jdbc().queryForList(
                "SELECT id, personnel_filing_id, name, id_number, unit, department, "
                + "destination_passport, travel_dates, approval_date, passport_no "
                + "FROM travel_details WHERE id = ?", travelId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private String today() {
        return LocalDate.ofInstant(java.time.Instant.now(),
                ZoneOffset.ofHours(cfg.tzOffsetHours)).format(YMD);
    }

    /**
     * 签章失败不阻断业务：领用登记本身已经成功，凭证仍在。
     * 详情页会把「未签章」如实显示出来，不会让人误以为已加固。
     */
    private void sealQuietly(HttpServletRequest req, long id, String kind,
                             byte[] signImage, String signMeta) {
        var rows = db.jdbc().queryForList("SELECT * FROM cert_issuance WHERE id = ?", id);
        if (rows.isEmpty()) {
            return;
        }
        try {
            seals.seal(db.jdbc(), id, kind, signImage, signMeta, rows.get(0));
        } catch (RuntimeException e) {
            Flash.warning(req, "国密签章未能生成（" + e.getMessage() + "），凭证已保存但未加固。");
        }
    }

    private static byte[] blob(Object o) {
        return o instanceof byte[] b ? b : null;
    }

    private static Long longOrNull(String s) {
        if (s == null || s.isBlank()) {
            return null;
        }
        try {
            return Long.valueOf(s.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }
}

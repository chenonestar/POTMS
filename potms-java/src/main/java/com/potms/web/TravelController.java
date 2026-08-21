package com.potms.web;

import static com.potms.web.PersonnelController.operator;
import static com.potms.web.PersonnelController.operatorName;
import static com.potms.web.PersonnelController.param;
import static com.potms.web.PersonnelController.str;
import static com.potms.web.PersonnelController.toStringMap;
import static com.potms.web.PersonnelController.trim;

import com.potms.Config;
import com.potms.data.Db;
import com.potms.util.TravelDates;
import com.potms.util.Validators;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.multipart.MultipartHttpServletRequest;

/** 出国（境）明细 + 附件。对应 Python 版 blueprints/travel.py。 */
@Controller
public class TravelController {

    private static final DateTimeFormatter YMD = DateTimeFormatter.ofPattern("yyyyMMdd");

    /** 各路径要求的必备附件类型。 */
    static final List<String> REQUIRED_A = List.of("个人申请报告", "审批表");
    static final List<String> REQUIRED_B = List.of("个人申请报告", "审批表", "同意申办函");

    /** 上传表单字段名 → 附件分类展示名。 */
    private static final Map<String, String> CATEGORIES = new LinkedHashMap<>();

    static {
        CATEGORIES.put("att_application", "个人申请报告");
        CATEGORIES.put("att_approval", "审批表");
        CATEGORIES.put("att_consent", "同意申办函");
    }

    private final Db db;
    private final Config cfg;

    public TravelController(Db db, Config cfg) {
        this.db = db;
        this.cfg = cfg;
    }

    // =====================================================================
    // 列表
    // =====================================================================

    /** 列表 WHERE 拼装，供列表页与导出复用。含出行日期区间与证件流转状态筛选。 */
    public Filter buildFilters(HttpServletRequest req, List<Long> ids) {
        Filter f = new Filter();
        f.like("(name LIKE ? OR destination_passport LIKE ?)", req.getParameter("search"), 2);
        f.eq("category", req.getParameter("category"));
        f.eq("need_new_passport", req.getParameter("need_new_passport"));

        String ps = param(req, "passport_status", "");
        if ("storage".equals(ps)) {
            f.and("(passport_collect_date IS NULL OR passport_collect_date = '')");
        } else if ("inuse".equals(ps)) {
            f.and("passport_collect_date IS NOT NULL AND passport_collect_date != '' "
                    + "AND (passport_return_date IS NULL OR passport_return_date = '')");
        } else if ("overdue".equals(ps)) {
            // 逾期口径需按行算工作日，SQL 表达不了，先算出 id 集合再以 id 限定
            Set<Long> oids = overdueIds();
            if (oids.isEmpty()) {
                f.and("1=0");
            } else {
                f.and("id IN (" + "?,".repeat(oids.size() - 1) + "?)", oids.toArray());
            }
        }

        // 出行日期区间：与 [date_from, date_to] 有交集
        String from = Validators.parseDateInput(req.getParameter("date_from"));
        String to = Validators.parseDateInput(req.getParameter("date_to"));
        if (!from.isEmpty()) {
            f.and("travel_end >= ? AND travel_end != ''", from);
        }
        if (!to.isEmpty()) {
            f.and("travel_start <= ? AND travel_start != ''", to);
        }
        if (ids != null && !ids.isEmpty()) {
            f.and("id IN (" + "?,".repeat(ids.size() - 1) + "?)", ids.toArray());
        }
        return f;
    }

    /** 全量计算「证件逾期未还」的 id 集合。 */
    private Set<Long> overdueIds() {
        String today = today();
        Set<Long> out = new HashSet<>();
        for (var r : db.jdbc().queryForList(
                "SELECT id, passport_collect_date, passport_return_date, actual_return_date, "
                + "travel_end, trip_status, cancel_date FROM travel_details "
                + "WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' "
                + "AND (passport_return_date IS NULL OR passport_return_date = '')")) {
            if (Validators.isCertOverdue(r, today)) {
                out.add(Fmt.n(r, "id"));
            }
        }
        return out;
    }

    @GetMapping("/travel")
    public String list(HttpServletRequest req, Model model) {
        Filter f = buildFilters(req, null);
        var items = Helpers.listAll(db.jdbc(),
                "SELECT * FROM travel_details WHERE 1=1" + f.where() + " ORDER BY created_at DESC",
                f.params());

        String today = today();
        Set<Long> overdue = new HashSet<>();
        Map<Long, String> deadlines = new HashMap<>();
        for (var row : items.rows()) {
            if (Validators.isCertOverdue(row, today)) {
                long id = Fmt.n(row, "id");
                overdue.add(id);
                deadlines.put(id, Validators.certOverdueDeadline(row));
            }
        }

        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("items", items);
        model.addAttribute("search", param(req, "search", ""));
        model.addAttribute("categoryFilter", param(req, "category", ""));
        model.addAttribute("needPassportFilter", param(req, "need_new_passport", ""));
        model.addAttribute("passportStatus", param(req, "passport_status", ""));
        model.addAttribute("dateFrom", param(req, "date_from", ""));
        model.addAttribute("dateTo", param(req, "date_to", ""));
        model.addAttribute("overdueIds", overdue);
        model.addAttribute("deadlines", deadlines);
        model.addAttribute("categoryOpts", Helpers.dictOptions(db.jdbc(), "travel_category"));
        return "travel/list";
    }

    // =====================================================================
    // 附件总览（跨记录汇总 + 缺件检查）
    // =====================================================================

    /** 缺件项：某条出行还差哪几类附件。 */
    public record MissingItem(long id, String name, String unit, String path, List<String> lack) {}

    @GetMapping("/travel/attachments")
    public String attachments(HttpServletRequest req, Model model) {
        Filter f = new Filter();
        f.like("(t.name LIKE ? OR a.file_name LIKE ?)", req.getParameter("search"), 2);
        f.eq("a.file_type", req.getParameter("file_type"));
        String from = param(req, "date_from", "");
        String to = param(req, "date_to", "");
        if (!from.isEmpty()) {
            f.and("date(a.uploaded_at) >= ?", from);
        }
        if (!to.isEmpty()) {
            f.and("date(a.uploaded_at) <= ?", to);
        }
        var items = Helpers.listAll(db.jdbc(),
                "SELECT a.id, a.file_name, a.file_type, a.file_size, a.uploaded_at, "
                + "t.id AS travel_id, t.name, t.unit, t.destination_passport, t.travel_dates "
                + "FROM attachments a JOIN travel_details t ON a.travel_id = t.id WHERE 1=1"
                + f.where() + " ORDER BY a.uploaded_at DESC", f.params());

        // 缺件检查：一次取全部附件建映射，避免逐条出行再查一次
        Map<Long, Set<String>> have = new HashMap<>();
        for (var r : db.jdbc().queryForList("SELECT travel_id, file_type FROM attachments")) {
            Object tid = r.get("travel_id");
            String type = str(r.get("file_type"));
            if (tid != null && !type.isEmpty()) {
                have.computeIfAbsent(((Number) tid).longValue(), k -> new HashSet<>()).add(type);
            }
        }
        List<MissingItem> missing = new ArrayList<>();
        for (var t : db.jdbc().queryForList(
                "SELECT id, name, unit, need_new_passport FROM travel_details ORDER BY created_at DESC")) {
            boolean pathB = "是".equals(str(t.get("need_new_passport")));
            List<String> required = pathB ? REQUIRED_B : REQUIRED_A;
            Set<String> owned = have.getOrDefault(Fmt.n(t, "id"), Set.of());
            List<String> lack = required.stream().filter(x -> !owned.contains(x)).toList();
            if (!lack.isEmpty()) {
                missing.add(new MissingItem(Fmt.n(t, "id"), str(t.get("name")),
                        str(t.get("unit")), pathB ? "B" : "A", lack));
            }
        }

        Map<String, Long> typeCounts = new LinkedHashMap<>();
        for (var g : db.jdbc().queryForList(
                "SELECT file_type, COUNT(*) AS cnt FROM attachments GROUP BY file_type")) {
            String key = str(g.get("file_type"));
            if (!key.isEmpty()) {           // 字典键不允许为 null
                typeCounts.put(key, Fmt.n(g, "cnt"));
            }
        }

        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("items", items);
        model.addAttribute("search", param(req, "search", ""));
        model.addAttribute("typeFilter", param(req, "file_type", ""));
        model.addAttribute("dateFrom", from);
        model.addAttribute("dateTo", to);
        model.addAttribute("missing", missing);
        model.addAttribute("typeCounts", typeCounts);
        model.addAttribute("totalAtt", count("SELECT COUNT(*) FROM attachments"));
        model.addAttribute("types", REQUIRED_B);
        return "travel/attachments";
    }

    // =====================================================================
    // 新增 / 编辑 / 查看 / 删除
    // =====================================================================

    @GetMapping("/travel/new")
    public String newForm(HttpServletRequest req, Model model,
                          @RequestParam(name = "filing_id", required = false) Long filingId) {
        Map<String, String> prefill = new LinkedHashMap<>();
        if (filingId != null) {
            var rows = db.jdbc().queryForList(
                    "SELECT pf.*, COALESCE((SELECT unit FROM personnel_info WHERE id = "
                    + "  pf.personnel_info_id), pf.work_unit) AS info_unit, "
                    + "COALESCE((SELECT department FROM personnel_info WHERE id = "
                    + "  pf.personnel_info_id), '') AS info_dept "
                    + "FROM personnel_filing pf WHERE pf.id = ?", filingId);
            if (!rows.isEmpty()) {
                var r = rows.get(0);
                prefill.put("personnel_filing_id", String.valueOf(filingId));
                String unit = str(r.get("info_unit"));
                prefill.put("unit", unit.isEmpty() ? str(r.get("work_unit")) : unit);
                prefill.put("department", str(r.get("info_dept")));
                prefill.put("name", str(r.get("surname")) + str(r.get("given_name")));
                prefill.put("position", str(r.get("position_or_title")));
                prefill.put("id_number", str(r.get("id_number")));
            }
        }
        return render(req, model, prefill, false, null, List.of());
    }

    @PostMapping("/travel/new")
    public String create(HttpServletRequest req, Model model) {
        Map<String, String> data = extract(req);
        List<String> errors = validate(data);
        errors.addAll(missingAttachmentErrors(req, data.get("need_new_passport")));
        if (!errors.isEmpty()) {
            errors.forEach(e -> Flash.danger(req, e));
            return render(req, model, data, false, null, List.of());
        }

        var range = TravelDates.parse(data.get("travel_dates"));
        String canon = TravelDates.format(range.start(), range.end());
        if (!canon.isEmpty()) {
            data.put("travel_dates", canon);
        }

        // 证件领用 / 归还日期为派生字段，由证件领用模块唯一写入，此处不落值
        long id = db.insert(
                "INSERT INTO travel_details (personnel_filing_id, unit, department, name, "
                + "position, title, id_number, destination_passport, category, travel_dates, "
                + "travel_start, travel_end, approval_date, need_new_passport, passport_no, "
                + "actual_return_date, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                longOrNull(data.get("personnel_filing_id")), data.get("unit"), data.get("department"),
                data.get("name"), data.get("position"), data.get("title"), data.get("id_number"),
                data.get("destination_passport"), data.get("category"), data.get("travel_dates"),
                range.start(), range.end(), data.get("approval_date"),
                data.get("need_new_passport"), data.get("passport_no"),
                data.get("actual_return_date"), data.get("operator"));

        saveAttachments(req, id);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "create", "travel_details", id, null, null,
                Helpers.rowSnapshot(db.jdbc(), "travel_details", id));
        Flash.success(req, "出国（境）明细表已保存。");
        return "redirect:/travel";
    }

    @GetMapping("/travel/{id}/edit")
    public String editForm(@PathVariable long id, HttpServletRequest req, Model model) {
        var row = one(id);
        if (row == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/travel";
        }
        return render(req, model, toStringMap(row), true, id, attachmentsOf(id));
    }

    @PostMapping("/travel/{id}/edit")
    public String update(@PathVariable long id, HttpServletRequest req, Model model) {
        if (one(id) == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/travel";
        }
        Map<String, String> data = extract(req);
        List<String> errors = validate(data);
        if (!errors.isEmpty()) {
            errors.forEach(e -> Flash.danger(req, e));
            return render(req, model, data, true, id, attachmentsOf(id));
        }
        var before = Helpers.rowSnapshot(db.jdbc(), "travel_details", id);
        var range = TravelDates.parse(data.get("travel_dates"));
        String canon = TravelDates.format(range.start(), range.end());
        if (!canon.isEmpty()) {
            data.put("travel_dates", canon);
        }
        // 同 create：不覆盖 passport_collect_date / passport_return_date 两个派生字段
        db.jdbc().update(
                "UPDATE travel_details SET personnel_filing_id=?, unit=?, department=?, name=?, "
                + "position=?, title=?, id_number=?, destination_passport=?, category=?, "
                + "travel_dates=?, travel_start=?, travel_end=?, approval_date=?, "
                + "need_new_passport=?, passport_no=?, actual_return_date=?, operator=?, "
                + "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                longOrNull(data.get("personnel_filing_id")), data.get("unit"), data.get("department"),
                data.get("name"), data.get("position"), data.get("title"), data.get("id_number"),
                data.get("destination_passport"), data.get("category"), data.get("travel_dates"),
                range.start(), range.end(), data.get("approval_date"),
                data.get("need_new_passport"), data.get("passport_no"),
                data.get("actual_return_date"), data.get("operator"), id);

        saveAttachments(req, id);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "update", "travel_details", id, null, before,
                Helpers.rowSnapshot(db.jdbc(), "travel_details", id));
        Flash.success(req, "明细表已更新。");
        return "redirect:/travel";
    }

    @GetMapping("/travel/{id}")
    public String view(@PathVariable long id, HttpServletRequest req, Model model) {
        var row = one(id);
        if (row == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/travel";
        }
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("travel", row);
        model.addAttribute("attachments", attachmentsOf(id));
        model.addAttribute("issuances", db.jdbc().queryForList(
                "SELECT * FROM cert_issuance WHERE travel_id = ? ORDER BY issue_date DESC", id));
        model.addAttribute("deadline", Validators.certOverdueDeadline(row));
        model.addAttribute("overdue", Validators.isCertOverdue(row, today()));
        return "travel/view";
    }

    /** 删除。已有证件领用记录（含签名凭证）时禁止删除，避免留下悬空引用。 */
    @PostMapping("/travel/{id}/delete")
    public String delete(@PathVariable long id, HttpServletRequest req) {
        if (one(id) == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/travel";
        }
        long iss = count("SELECT COUNT(*) FROM cert_issuance WHERE travel_id = ?", id);
        if (iss > 0) {
            Flash.danger(req, "该出行记录已有 " + iss + " 条证件领用记录，不能删除。"
                    + "如确需删除，请先作废相关领用记录。");
            return "redirect:/travel";
        }
        for (var att : db.jdbc().queryForList(
                "SELECT file_path FROM attachments WHERE travel_id = ?", id)) {
            deleteFile(str(att.get("file_path")));
        }
        var before = Helpers.rowSnapshot(db.jdbc(), "travel_details", id);
        db.jdbc().update("DELETE FROM attachments WHERE travel_id = ?", id);
        db.jdbc().update("DELETE FROM travel_details WHERE id = ?", id);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "delete", "travel_details", id, null, before, null);
        Flash.info(req, "出国申请记录已删除。");
        return "redirect:/travel";
    }

    // =====================================================================
    // 行程取消 / 恢复
    // =====================================================================

    /** 取消行程：已申领证件须在取消日起 5 个工作日内送回保管。 */
    @PostMapping("/travel/{id}/cancel")
    public String cancel(@PathVariable long id, HttpServletRequest req) {
        var row = one(id);
        if (row == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/travel";
        }
        if ("cancelled".equals(str(row.get("trip_status")))) {
            Flash.info(req, "该行程已处于取消状态。");
            return "redirect:/travel/" + id;
        }
        String cancelDate = Validators.parseDateInput(req.getParameter("cancel_date"));
        if (cancelDate.isEmpty()) {
            cancelDate = today();
        }
        var check = Validators.validateDateFormat(cancelDate);
        if (!check.ok()) {
            Flash.danger(req, "取消日期: " + check.message());
            return "redirect:/travel/" + id;
        }
        var before = Helpers.rowSnapshot(db.jdbc(), "travel_details", id);
        db.jdbc().update("UPDATE travel_details SET trip_status='cancelled', cancel_date=?, "
                + "updated_at=CURRENT_TIMESTAMP WHERE id=?", cancelDate, id);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "cancel", "travel_details", id, "取消行程（" + cancelDate + "）", before,
                Helpers.rowSnapshot(db.jdbc(), "travel_details", id));
        Flash.warning(req, "行程已取消（" + cancelDate + "）。已申领证件请于 5 个工作日内送回保管。");
        return "redirect:/travel/" + id;
    }

    @PostMapping("/travel/{id}/restore")
    public String restore(@PathVariable long id, HttpServletRequest req) {
        if (one(id) == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/travel";
        }
        var before = Helpers.rowSnapshot(db.jdbc(), "travel_details", id);
        db.jdbc().update("UPDATE travel_details SET trip_status='normal', cancel_date=NULL, "
                + "updated_at=CURRENT_TIMESTAMP WHERE id=?", id);
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "restore", "travel_details", id, "恢复行程为正常", before,
                Helpers.rowSnapshot(db.jdbc(), "travel_details", id));
        Flash.success(req, "行程已恢复为正常状态。");
        return "redirect:/travel/" + id;
    }

    // =====================================================================
    // 附件下载 / 预览 / 删除
    // =====================================================================

    @GetMapping("/travel/attachment/{id}/download")
    public Object download(@PathVariable long id, HttpServletRequest req) {
        return serve(id, req, true);
    }

    /** 在浏览器内联预览 PDF 附件。 */
    @GetMapping("/travel/attachment/{id}/preview")
    public Object preview(@PathVariable long id, HttpServletRequest req) {
        return serve(id, req, false);
    }

    private Object serve(long id, HttpServletRequest req, boolean asAttachment) {
        var rows = db.jdbc().queryForList("SELECT * FROM attachments WHERE id = ?", id);
        if (rows.isEmpty()) {
            Flash.danger(req, "附件不存在。");
            return "redirect:/travel";
        }
        var att = rows.get(0);
        Path p = cfg.uploadFolder.resolve(str(att.get("file_path"))).normalize();
        // 目录穿越守卫：拼出的路径必须仍在上传目录之内
        if (!p.startsWith(cfg.uploadFolder) || !Files.exists(p)) {
            Flash.danger(req, "附件文件已丢失。");
            return "redirect:/travel";
        }
        String fileName = str(att.get("file_name"));
        var disposition = asAttachment
                ? org.springframework.http.ContentDisposition.attachment()
                : org.springframework.http.ContentDisposition.inline();
        return ResponseEntity.ok()
                .contentType(MediaType.APPLICATION_PDF)
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        disposition.filename(fileName, java.nio.charset.StandardCharsets.UTF_8)
                                .build().toString())
                .body(new FileSystemResource(p));
    }

    @PostMapping("/travel/attachment/{id}/delete")
    public String attachmentDelete(@PathVariable long id, HttpServletRequest req) {
        var rows = db.jdbc().queryForList("SELECT * FROM attachments WHERE id = ?", id);
        if (rows.isEmpty()) {
            Flash.danger(req, "附件不存在。");
            return "redirect:/travel";
        }
        var att = rows.get(0);
        deleteFile(str(att.get("file_path")));
        long travelId = Fmt.n(att, "travel_id");
        db.jdbc().update("DELETE FROM attachments WHERE id = ?", id);
        Flash.info(req, "附件已删除。");
        return "redirect:/travel/" + travelId + "/edit";
    }

    // =====================================================================
    // 表单与附件辅助
    // =====================================================================

    private Map<String, String> extract(HttpServletRequest req) {
        Map<String, String> d = new LinkedHashMap<>();
        d.put("personnel_filing_id", trim(req, "personnel_filing_id"));
        d.put("unit", trim(req, "unit"));
        d.put("department", trim(req, "department"));
        d.put("name", trim(req, "name"));
        d.put("position", trim(req, "position"));
        d.put("title", trim(req, "title"));
        d.put("id_number", trim(req, "id_number").toUpperCase());
        d.put("destination_passport", trim(req, "destination_passport"));
        d.put("category", trim(req, "category"));
        d.put("travel_dates", trim(req, "travel_dates"));
        d.put("approval_date", Validators.parseDateInput(req.getParameter("approval_date")));
        // passport_collect_date / passport_return_date 是派生字段，
        // 由证件领用模块唯一写入，这里刻意不从表单读取——即便前端伪造也进不来。
        String need = trim(req, "need_new_passport");
        d.put("need_new_passport", need.isEmpty() ? "否" : need);
        d.put("passport_no", trim(req, "passport_no"));
        d.put("actual_return_date", Validators.parseDateInput(req.getParameter("actual_return_date")));
        d.put("operator", operatorName(req));
        return d;
    }

    private List<String> validate(Map<String, String> d) {
        List<String> errors = new ArrayList<>(Validators.checkRequired(d, List.of(
                new Validators.Field("personnel_filing_id", "备案人员"),
                new Validators.Field("unit", "单位"),
                new Validators.Field("department", "部门"),
                new Validators.Field("name", "姓名"),
                new Validators.Field("position", "职务"),
                new Validators.Field("id_number", "身份证号"),
                new Validators.Field("destination_passport", "地点、证照"),
                new Validators.Field("category", "类别"),
                new Validators.Field("travel_dates", "计划出行日期"),
                new Validators.Field("need_new_passport", "是否做证"))));
        // 明细表身份证由备案信息带入、无性别/出生字段，仅校验号码本身
        errors.addAll(Validators.checkIdentity(d, "id_number", null, null));

        if (!d.getOrDefault("travel_dates", "").isEmpty()) {
            var c = Validators.validateTravelRange(d.get("travel_dates"));
            if (!c.ok()) {
                errors.add("计划出行日期: " + c.message());
            }
        }
        errors.addAll(Validators.checkDates(d, List.of(
                new Validators.Field("approval_date", "批准日期"),
                new Validators.Field("actual_return_date", "实际回国日期"))));
        return errors;
    }

    /** 附件必填 + PDF 魔数预检：提交阶段就拒绝，避免「记录已存、必传附件被拒」的不一致。 */
    private List<String> missingAttachmentErrors(HttpServletRequest req, String needNewPassport) {
        List<String> errors = new ArrayList<>();
        if (!(req instanceof MultipartHttpServletRequest mreq)) {
            errors.add("附件《个人申请报告》为必传项（PDF）。");
            errors.add("附件《审批表》为必传项（PDF）。");
            if ("是".equals(needNewPassport)) {
                errors.add("需新办证件（路径B）时，《同意申办函》为必传项（PDF）。");
            }
            return errors;
        }
        if (!hasFile(mreq, "att_application")) {
            errors.add("附件《个人申请报告》为必传项（PDF）。");
        }
        if (!hasFile(mreq, "att_approval")) {
            errors.add("附件《审批表》为必传项（PDF）。");
        }
        if ("是".equals(needNewPassport) && !hasFile(mreq, "att_consent")) {
            errors.add("需新办证件（路径B）时，《同意申办函》为必传项（PDF）。");
        }
        for (String field : CATEGORIES.keySet()) {
            for (MultipartFile f : mreq.getFiles(field)) {
                if (!f.isEmpty() && !isPdf(f)) {
                    errors.add("文件 " + f.getOriginalFilename()
                            + " 内容不是有效的 PDF，请上传真实的 PDF 扫描件。");
                }
            }
        }
        return errors;
    }

    private static boolean hasFile(MultipartHttpServletRequest req, String field) {
        for (MultipartFile f : req.getFiles(field)) {
            if (!f.isEmpty() && f.getOriginalFilename() != null
                    && !f.getOriginalFilename().isBlank()) {
                return true;
            }
        }
        return false;
    }

    /** 魔数校验：真实 PDF 以 %PDF- 开头，防止改扩展名的任意文件入库。 */
    private static boolean isPdf(MultipartFile f) {
        try (InputStream in = f.getInputStream()) {
            byte[] head = in.readNBytes(5);
            return head.length == 5 && head[0] == '%' && head[1] == 'P'
                    && head[2] == 'D' && head[3] == 'F' && head[4] == '-';
        } catch (IOException e) {
            return false;
        }
    }

    private void saveAttachments(HttpServletRequest req, long travelId) {
        if (!(req instanceof MultipartHttpServletRequest mreq)) {
            return;
        }
        for (var entry : CATEGORIES.entrySet()) {
            for (MultipartFile f : mreq.getFiles(entry.getKey())) {
                String original = f.getOriginalFilename();
                if (f.isEmpty() || original == null || original.isBlank()) {
                    continue;
                }
                String ext = original.contains(".")
                        ? original.substring(original.lastIndexOf('.') + 1).toLowerCase() : "";
                if (!"pdf".equals(ext)) {
                    Flash.warning(req, "文件 " + original + " 格式不支持（仅允许 PDF）。");
                    continue;
                }
                if (!isPdf(f)) {
                    Flash.warning(req, "文件 " + original + " 内容不是有效的 PDF（已拒绝）。");
                    continue;
                }
                // 存盘名用 UUID，杜绝原始文件名带路径分隔符造成的目录穿越
                String savedName = UUID.randomUUID().toString().replace("-", "") + ".pdf";
                Path target = cfg.uploadFolder.resolve(savedName);
                try {
                    f.transferTo(target);
                    db.jdbc().update(
                            "INSERT INTO attachments (travel_id, file_name, file_path, file_type, "
                            + "file_size) VALUES (?, ?, ?, ?, ?)",
                            travelId, original, savedName, entry.getValue(), Files.size(target));
                } catch (IOException e) {
                    Flash.danger(req, "文件 " + original + " 保存失败：" + e.getMessage());
                }
            }
        }
    }

    private void deleteFile(String relative) {
        if (relative == null || relative.isEmpty()) {
            return;
        }
        Path p = cfg.uploadFolder.resolve(relative).normalize();
        if (p.startsWith(cfg.uploadFolder)) {
            try {
                Files.deleteIfExists(p);
            } catch (IOException ignored) {
                // 文件被占用时跳过，数据库记录仍会删除
            }
        }
    }

    // ------------------------------------------------------------------

    private String render(HttpServletRequest req, Model model, Map<String, String> data,
                          boolean editing, Long travelId, List<Map<String, Object>> atts) {
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("data", data);
        model.addAttribute("editing", editing);
        model.addAttribute("travelId", travelId);
        model.addAttribute("attachments", atts);
        model.addAttribute("people", Helpers.personnelOptions(db.jdbc()));
        model.addAttribute("categoryOpts", Helpers.dictOptions(db.jdbc(), "travel_category"));
        return "travel/form";
    }

    private List<Map<String, Object>> attachmentsOf(long travelId) {
        return db.jdbc().queryForList(
                "SELECT * FROM attachments WHERE travel_id = ? ORDER BY uploaded_at", travelId);
    }

    private Map<String, Object> one(long id) {
        var rows = db.jdbc().queryForList("SELECT * FROM travel_details WHERE id = ?", id);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private long count(String sql, Object... params) {
        Long n = db.jdbc().queryForObject(sql, Long.class, params);
        return n == null ? 0 : n;
    }

    private String today() {
        return LocalDate.ofInstant(java.time.Instant.now(),
                ZoneOffset.ofHours(cfg.tzOffsetHours)).format(YMD);
    }

    private static Long longOrNull(String s) {
        if (s == null || s.isEmpty()) {
            return null;
        }
        try {
            return Long.valueOf(s);
        } catch (NumberFormatException e) {
            return null;
        }
    }
}

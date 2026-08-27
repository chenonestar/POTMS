package com.potms.web;

import static com.potms.web.PersonnelController.str;

import com.potms.data.Db;
import com.potms.service.Excel;
import com.potms.service.ExcelImport;
import com.potms.service.IssuanceOps;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.io.InputStream;
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
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.multipart.MultipartFile;

/** 打印与批量打印 + 批量导入。对应 Python 版 export.print_view / import_data。 */
@Controller
public class PrintController {

    /** 打印类型 → 标题 / 取数表。 */
    private record Kind(String title, String table) {}

    private static final Map<String, Kind> KINDS = new LinkedHashMap<>();

    static {
        KINDS.put("info", new Kind("备案人员信息登记表", "personnel_info"));
        KINDS.put("filing", new Kind("因私事出国（境）人员登记备案表", "personnel_filing"));
        KINDS.put("certificate", new Kind("因私出国（境）备案人员证照登记表", "certificates"));
        KINDS.put("travel", new Kind("因私出国（境）人员明细表", "travel_details"));
        KINDS.put("decontrol", new Kind("因私事出国（境）人员撤控备案表", "decontrol_filing"));
        KINDS.put("issuance", new Kind("因私出国（境）证件领用登记表", "cert_issuance"));
    }

    /**
     * 支持批量打印的类型。
     *
     * <p>含 issuance：领用凭证虽是逐份签字的单据，但归档时要按批出，签名图按行取
     * （src 指向 /issuance/{id}/signature.png，不往页面里塞 BLOB），一行一份也摆得下。
     * 此前这里把 issuance 排除在外，并注称「与 Python 版一致」——那句注释是错的，
     * Python 版一直支持领用的批量打印。
     */
    private static final java.util.Set<String> BATCH_KINDS =
            java.util.Set.of("info", "filing", "certificate", "travel", "decontrol", "issuance");

    private final Db db;
    private final com.potms.Config cfg;

    public PrintController(Db db, com.potms.Config cfg) {
        this.db = db;
        this.cfg = cfg;
    }

    /** 单条打印。 */
    @GetMapping("/print/{type}/{id}")
    public String print(@PathVariable String type, @PathVariable long id,
                        HttpServletRequest req, Model model) {
        Kind kind = KINDS.get(type);
        if (kind == null) {
            Flash.danger(req, "不支持的打印类型。");
            return "redirect:/";
        }
        var doc = load(type, id);
        if (doc == null) {
            Flash.danger(req, "记录不存在。");
            return "redirect:/";
        }
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("mode", type);
        model.addAttribute("title", kind.title());
        model.addAttribute("docs", List.of(doc));
        return "print/view";
    }

    /** 批量打印：main.js 的 batchPrint() 把选中行 id 串拼在 ids 上。 */
    @GetMapping("/print/batch/{type}")
    public String batch(@PathVariable String type, HttpServletRequest req, Model model,
                        @RequestParam(required = false) String ids) {
        Kind kind = BATCH_KINDS.contains(type) ? KINDS.get(type) : null;
        if (kind == null) {
            Flash.danger(req, "不支持的打印类型。");
            return "redirect:/";
        }
        List<Long> idList = Filter.parseIds(ids);
        if (idList.isEmpty()) {
            Flash.warning(req, "请先选择要打印的记录。");
            return "redirect:/";
        }
        List<Map<String, String>> docs = new ArrayList<>();
        for (long id : idList) {
            var d = load(type, id);
            if (d != null) {
                docs.add(d);
            }
        }
        if (docs.isEmpty()) {
            Flash.warning(req, "未选择有效记录。");
            return "redirect:/";
        }
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("mode", type);
        model.addAttribute("title", kind.title());
        model.addAttribute("docs", docs);
        return "print/batch";
    }

    /**
     * 取一条记录并把字典代码换成显示值。
     *
     * <p>返回扁平的 字段名→展示值 映射：打印模板只负责排版，不再关心代码转换。
     */
    private Map<String, String> load(String type, long id) {
        Kind kind = KINDS.get(type);
        String sql = "issuance".equals(type)
                ? "SELECT i.*, pf.work_unit FROM cert_issuance i "
                  + "JOIN personnel_filing pf ON i.personnel_filing_id = pf.id WHERE i.id = ?"
                : "SELECT * FROM " + kind.table() + " WHERE id = ?";
        var rows = db.jdbc().queryForList(sql, id);
        if (rows.isEmpty()) {
            return null;
        }
        var r = rows.get(0);
        Map<String, String> doc = new LinkedHashMap<>();
        r.forEach((k, v) -> doc.put(k, v == null ? "" : v.toString()));

        // 字典代码 → 显示值
        for (String cat : new String[] {"education", "degree", "title", "rank"}) {
            String code = doc.getOrDefault(cat, "");
            if (!code.isEmpty()) {
                doc.put(cat, Helpers.dictValue(db.jdbc(), cat, code));
            }
        }
        if ("filing".equals(type)) {
            // 备案表打印需要信息登记表里的部门等字段
            String infoId = doc.getOrDefault("personnel_info_id", "");
            if (!infoId.isEmpty()) {
                var info = db.jdbc().queryForList(
                        "SELECT * FROM personnel_info WHERE id = ?", Long.valueOf(infoId));
                if (!info.isEmpty()) {
                    info.get(0).forEach((k, v) -> doc.putIfAbsent("info_" + k,
                            v == null ? "" : v.toString()));
                    // 关联信息表的字典字段同样要转中文。漏了这步打出来的是 04 这种
                    // 裸代码——Python 与 Rust 版当年就漏在这里，Go 与 .NET 是对的。
                    for (String cat : new String[] {"education", "degree", "title", "rank"}) {
                        String code = doc.getOrDefault("info_" + cat, "");
                        if (!code.isEmpty()) {
                            doc.put("info_" + cat, Helpers.dictValue(db.jdbc(), cat, code));
                        }
                    }
                }
            }
        }
        // 打印页只排版、不做判断，凡是要「代码 → 中文」的都在这里备好
        if ("travel".equals(type)) {
            doc.put("trip_status_label",
                    "cancelled".equals(doc.getOrDefault("trip_status", "")) ? "取消行程" : "正常");
        }
        if ("filing".equals(type)) {
            doc.put("status_label",
                    "active".equals(doc.getOrDefault("status", "")) ? "有效" : "已撤控");
        }
        if ("issuance".equals(type)) {
            // 签名图有没有，决定打印时是贴图还是留一条手签横线
            doc.put("has_sign", doc.getOrDefault("sign_image", "").isEmpty() ? "" : "1");
            doc.put("has_return_sign",
                    doc.getOrDefault("return_sign_image", "").isEmpty() ? "" : "1");
            doc.put("cert_types_label",
                    IssuanceOps.typesLabel(db.jdbc(), doc.getOrDefault("cert_types", "")));
            doc.put("status_label", switch (doc.getOrDefault("status", "")) {
                case "issued" -> "已领用";
                case "returned" -> "已归还";
                case "voided" -> "已作废";
                default -> doc.getOrDefault("status", "");
            });
        }
        doc.put("_id", String.valueOf(id));
        return doc;
    }

    // =====================================================================
    // 批量导入
    // =====================================================================

    @GetMapping("/import")
    public String importPage(HttpServletRequest req, Model model) {
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("result", null);
        return "importdata/form";
    }

    @PostMapping("/import")
    public String doImport(HttpServletRequest req, Model model,
                           @RequestParam(required = false) MultipartFile file) {
        ExcelImport.Result result = null;

        if (file == null || file.isEmpty() || file.getOriginalFilename() == null
                || file.getOriginalFilename().isBlank()) {
            Flash.warning(req, "请选择要上传的文件。");
        } else {
            String name = file.getOriginalFilename();
            String ext = name.contains(".")
                    ? name.substring(name.lastIndexOf('.') + 1).toLowerCase() : "";
            if (!"xlsx".equals(ext)) {
                Flash.danger(req, "仅支持 .xlsx 格式的 Excel 文件。");
            } else {
                try (InputStream in = file.getInputStream()) {
                    result = ExcelImport.parse(in, db.jdbc(), PersonnelController.operatorName(req));
                    Helpers.logAction(db.jdbc(), PersonnelController.operator(req),
                            SecurityFilters.clientIp(req), "import", "personnel_info", null,
                            "批量导入：共 " + result.total() + " 条，成功 " + result.success()
                                    + " 条，失败 " + result.failedRows() + " 条（"
                                    + result.errors().size() + " 处问题）", null, null);
                    if (result.success() > 0) {
                        Flash.success(req, "成功导入 " + result.success() + " 条记录（共 "
                                + result.total() + " 条）。");
                    }
                    if (result.failedRows() > 0) {
                        Flash.warning(req, result.failedRows() + " 条记录未能导入（"
                                + result.errors().size() + " 处问题），详见下方报告。");
                    }
                } catch (IOException | RuntimeException e) {
                    Flash.danger(req, "导入失败：" + e.getMessage());
                }
            }
        }

        // Ctx.of 会取走并清空闪现消息，故必须在所有 Flash.* 之后构造，
        // 否则提示会漏到下一次页面加载才显示。
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("result", result);
        return "importdata/form";
    }

    @GetMapping("/import/template")
    public Object template(HttpServletRequest req) {
        try {
            var result = Excel.write(cfg.exportFolder, ExcelImport.templateSpec(),
                    "备案人员批量导入模板", PersonnelController.operatorName(req), null);
            return ResponseEntity.ok()
                    .contentType(MediaType.parseMediaType(
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
                    .header(HttpHeaders.CONTENT_DISPOSITION,
                            ContentDisposition.attachment()
                                    .filename(result.fileName(), java.nio.charset.StandardCharsets.UTF_8)
                                    .build().toString())
                    .body(new FileSystemResource(result.path()));
        } catch (RuntimeException e) {
            Flash.danger(req, "模板生成失败：" + e.getMessage());
            return "redirect:/import";
        }
    }
}

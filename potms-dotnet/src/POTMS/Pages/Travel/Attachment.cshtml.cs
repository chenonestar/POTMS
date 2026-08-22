using Dapper;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using POTMS.Data;

namespace POTMS.Pages.Travel;

/// <summary>附件下载 / 在线预览。mode=preview 时以 inline 呈现，供浏览器内置阅读器打开。</summary>
public class AttachmentModel(Db db, Config cfg) : PageModel
{
    public IActionResult OnGet(long id, string? mode)
    {
        using var cn = db.Open();
        var a = cn.QueryFirstOrDefault<POTMS.Data.Attachment>(
            "SELECT * FROM attachments WHERE id=@id", new { id });
        if (a is null) return NotFound();
        var full = Path.Combine(cfg.UploadFolder, a.FilePath ?? "");
        if (!System.IO.File.Exists(full)) return NotFound();

        var bytes = System.IO.File.ReadAllBytes(full);
        if (mode == "preview")
        {
            Response.Headers.ContentDisposition =
                $"inline; filename*=UTF-8''{Uri.EscapeDataString(a.FileName ?? "attachment.pdf")}";
            return File(bytes, "application/pdf");
        }
        return File(bytes, "application/pdf", a.FileName ?? "attachment.pdf");
    }
}

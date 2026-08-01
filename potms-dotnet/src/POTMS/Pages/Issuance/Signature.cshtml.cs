using Dapper;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using POTMS.Data;

namespace POTMS.Pages.Issuance;

/// <summary>签名图片服务：签名一经保存不可变，可长期缓存。</summary>
public class SignatureModel(Db db) : PageModel
{
    public IActionResult OnGet(long id, string? kind)
    {
        var col = kind == "return" ? "return_sign_image" : "sign_image";
        using var cn = db.Open();
        var img = cn.QueryFirstOrDefault<byte[]?>($"SELECT {col} FROM cert_issuance WHERE id=@id", new { id });
        if (img is null || img.Length == 0) return NotFound();
        Response.Headers.CacheControl = "private, max-age=86400";
        return File(img, "image/png");
    }
}

using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace POTMS.Pages.Print;

/// <summary>批量打印入口：main.js 的 batchPrint() 打开 /Print/batch/{type}?ids=...，
/// 此处转交给 /Print/{type} 的 Batch 处理器统一渲染。</summary>
public class BatchModel : PageModel
{
    public IActionResult OnGet(string type, string? ids) =>
        Redirect($"/Print/{type}?handler=Batch&ids={Uri.EscapeDataString(ids ?? "")}");
}

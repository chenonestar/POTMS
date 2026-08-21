using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Import;

public class IndexModel(Db db, Flash flash) : AppPageModel(flash)
{
    public ExcelImport.Result? Result { get; private set; }

    public void OnGet() { }

    public IActionResult OnGetTemplate()
    {
        using var cn = db.Open();
        var bytes = ExcelImport.GenerateTemplate(cn);
        return File(bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "备案人员导入模板.xlsx");
    }

    public IActionResult OnPost(IFormFile? file)
    {
        if (file is null || file.Length == 0)
        {
            Flash.Warning("请选择要上传的文件。");
            return Page();
        }
        var ext = Path.GetExtension(file.FileName).ToLowerInvariant();
        if (ext != ".xlsx")
        {
            Flash.Danger("仅支持 .xlsx 格式的 Excel 文件。");
            return Page();
        }

        try
        {
            using var cn = db.Open();
            using var ms = new MemoryStream();
            file.CopyTo(ms);
            ms.Position = 0;
            Result = ExcelImport.Parse(cn, ms, OperatorName, ClientIp);

            if (Result.Success > 0)
                Flash.Success($"成功导入 {Result.Success} 条记录（共 {Result.Total} 条）。");
            if (Result.Errors.Count > 0)
                Flash.Warning($"{Result.Errors.Count} 条记录存在错误，详见下方报告。");
            if (Result is { Success: 0, Errors.Count: 0 })
                Flash.Info("文件中没有可导入的数据行。");
        }
        catch (Exception e)
        {
            Flash.Danger($"导入失败：无法解析文件（{e.GetType().Name}）。");
        }
        return Page();
    }
}

using System.Data;
using Dapper;
using Microsoft.AspNetCore.Http;

namespace POTMS.Services;

/// <summary>出国明细附件：分类上传的 PDF，含魔数校验。</summary>
public static class Attachments
{
    /// <summary>表单字段 → 附件类别显示名。</summary>
    public static readonly (string Field, string Label)[] Categories =
    {
        ("att_application", "个人申请报告"),
        ("att_approval", "审批表"),
        ("att_consent", "同意申办函"),
    };

    public static readonly string[] RequiredPathA = ["个人申请报告", "审批表"];
    public static readonly string[] RequiredPathB = ["个人申请报告", "审批表", "同意申办函"];

    private static readonly byte[] PdfMagic = "%PDF-"u8.ToArray();

    /// <summary>魔数校验：真实 PDF 以 %PDF- 开头，防止改扩展名的任意文件入库。</summary>
    public static bool IsPdf(IFormFile f)
    {
        if (f.Length < PdfMagic.Length) return false;
        using var s = f.OpenReadStream();
        var head = new byte[PdfMagic.Length];
        return s.ReadAtLeast(head, head.Length, throwOnEndOfStream: false) == head.Length
               && head.SequenceEqual(PdfMagic);
    }

    /// <summary>附件必填校验 + PDF 魔数预检。
    /// 在提交阶段即拒绝，避免「记录已存、必传附件被拒」的不一致。</summary>
    public static List<string> MissingErrors(IFormFileCollection files, string needNewPassport, bool isEdit)
    {
        var errs = new List<string>();
        bool Has(string field) => files.GetFiles(field).Any(f => f.Length > 0);

        if (!isEdit)   // 编辑时允许不重传（已有附件保留）
        {
            if (!Has("att_application")) errs.Add("附件《个人申请报告》为必传项（PDF）。");
            if (!Has("att_approval")) errs.Add("附件《审批表》为必传项（PDF）。");
            if (needNewPassport == "是" && !Has("att_consent"))
                errs.Add("需新办证件（路径B）时，《同意申办函》为必传项（PDF）。");
        }
        foreach (var (field, _) in Categories)
            foreach (var f in files.GetFiles(field))
                if (f.Length > 0 && !IsPdf(f))
                    errs.Add($"文件 {f.FileName} 内容不是有效的 PDF，请上传真实的 PDF 扫描件。");
        return errs;
    }

    public static void Save(IDbConnection cn, Config cfg, long travelId, IFormFileCollection files)
    {
        foreach (var (field, label) in Categories)
        {
            foreach (var f in files.GetFiles(field))
            {
                if (f.Length == 0) continue;
                var ext = Path.GetExtension(f.FileName).TrimStart('.').ToLowerInvariant();
                if (ext != "pdf" || !IsPdf(f)) continue;   // 已在校验阶段报错，此处静默跳过

                var savedName = $"{Guid.NewGuid():N}.pdf";
                var path = Path.Combine(cfg.UploadFolder, savedName);
                using (var fs = File.Create(path)) f.CopyTo(fs);
                cn.Execute(
                    "INSERT INTO attachments (travel_id, file_name, file_path, file_type, file_size) " +
                    "VALUES (@tid, @name, @path, @type, @size)",
                    new { tid = travelId, name = f.FileName, path = savedName,
                          type = label, size = new FileInfo(path).Length });
            }
        }
    }
}

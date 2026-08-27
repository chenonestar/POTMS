using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Travel;

public class ViewPageModel(Db db, Config cfg, Flash flash) : AppPageModel(flash)
{
    public TravelDetail Travel { get; private set; } = new();
    public List<Attachment> Files { get; private set; } = [];
    public List<CertIssuance> Issuances { get; private set; } = [];
    public bool IsOverdue { get; private set; }
    public string Deadline { get; private set; } = "";

    public IActionResult OnGet(long id)
    {
        using var cn = db.Open();
        var t = cn.QueryFirstOrDefault<TravelDetail>("SELECT * FROM travel_details WHERE id=@id", new { id });
        if (t is null) { Flash.Danger("记录不存在。"); return Redirect("/Travel"); }
        Travel = t;
        Files = cn.Query<Attachment>("SELECT * FROM attachments WHERE travel_id=@id ORDER BY " + Attachments.FileTypeOrderSql() + ", id",
            new { id }).AsList();
        Issuances = cn.Query<CertIssuance>("SELECT * FROM cert_issuance WHERE travel_id=@id ORDER BY issue_date DESC",
            new { id }).AsList();

        var today = Helpers.TodayLocal(cfg);
        IsOverdue = Validators.IsCertOverdue(t.PassportCollectDate, t.PassportReturnDate, t.TripStatus,
            t.CancelDate, t.ActualReturnDate, t.TravelEnd, today);
        Deadline = Validators.CertOverdueDeadline(t.TripStatus, t.CancelDate, t.ActualReturnDate, t.TravelEnd);
        return Page();
    }

    public IActionResult OnPostDeleteAttachment(long id, long attId)
    {
        using var cn = db.Open();
        var a = cn.QueryFirstOrDefault<Attachment>("SELECT * FROM attachments WHERE id=@a AND travel_id=@t",
            new { a = attId, t = id });
        if (a is null) { Flash.Danger("附件不存在。"); return Redirect($"/Travel/View/{id}"); }
        var full = Path.Combine(cfg.UploadFolder, a.FilePath ?? "");
        if (System.IO.File.Exists(full)) System.IO.File.Delete(full);
        cn.Execute("DELETE FROM attachments WHERE id=@a", new { a = attId });
        Log(cn, "delete", "attachments", attId, $"删除附件 {a.FileName}（出行 #{id}）");
        Flash.Info("附件已删除。");
        return Redirect($"/Travel/View/{id}");
    }
}

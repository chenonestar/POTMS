using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Issuance;

public class ReturnModel(Db db, Config cfg, Flash flash) : AppPageModel(flash)
{
    public CertIssuance Item { get; private set; } = new();
    public string TypeLabels { get; private set; } = "";
    public string ReturnDate { get; set; } = "";

    public IActionResult OnGet(long id)
    {
        using var cn = db.Open();
        var row = cn.QueryFirstOrDefault<CertIssuance>("SELECT * FROM cert_issuance WHERE id=@id", new { id });
        if (row is null) return NotFound();
        if (row.Status != "issued")
        {
            Flash.Warning("该记录不是「已领用」状态，无法办理归还。");
            return Redirect($"/Issuance/View/{id}");
        }
        Item = row;
        TypeLabels = IssuanceOps.TypesLabel(cn, row.CertTypes);
        ReturnDate = Helpers.TodayLocal(cfg);
        return Page();
    }

    public IActionResult OnPost(long id)
    {
        using var cn = db.Open();
        var row = cn.QueryFirstOrDefault<CertIssuance>("SELECT * FROM cert_issuance WHERE id=@id", new { id });
        if (row is null) return NotFound();
        if (row.Status != "issued")
        {
            Flash.Warning("该记录不是「已领用」状态，无法办理归还。");
            return Redirect($"/Issuance/View/{id}");
        }
        Item = row;
        TypeLabels = IssuanceOps.TypesLabel(cn, row.CertTypes);
        ReturnDate = Validators.ParseDateInput(Request.Form["return_date"]);

        var errors = new List<string>();
        if (ReturnDate.Length == 0) errors.Add("归还日期为必填项。");
        else
        {
            var (ok, msg) = Validators.ValidateDateFormat(ReturnDate);
            if (!ok) errors.Add($"归还日期: {msg}");
            else if (string.CompareOrdinal(ReturnDate, row.IssueDate) < 0)
                errors.Add($"归还日期不应早于领用日期（{row.IssueDate}）。");
        }
        var (blob, sigErr) = Signature.Decode(Request.Form["sign_png"], cfg.RequireSignature);
        if (sigErr.Length > 0) errors.Add(sigErr);

        if (errors.Count > 0) { foreach (var e in errors) Flash.Danger(e); return Page(); }

        var before = Helpers.RowSnapshot(cn, "cert_issuance", id);
        cn.Execute(
            "UPDATE cert_issuance SET return_date=@d, return_sign_image=@img, return_sign_meta=@meta, " +
            "return_operator=@op, status='returned', updated_at=CURRENT_TIMESTAMP WHERE id=@id",
            new { d = ReturnDate, img = blob, meta = Signature.CleanMeta(Request.Form["sign_meta"]),
                  op = OperatorName, id });
        IssuanceOps.SyncTravelDates(cn, row.TravelId);
        Log(cn, "update", "cert_issuance", id,
            $"证件归还登记：{row.HolderName}，归还日期 {ReturnDate}",
            before, Helpers.RowSnapshot(cn, "cert_issuance", id));
        Flash.Success("证件归还登记已保存。");
        return Redirect($"/Issuance/View/{id}");
    }
}

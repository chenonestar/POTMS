using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Issuance;

public class ViewModel(Db db, Flash flash) : AppPageModel(flash)
{
    public CertIssuance Item { get; private set; } = new();
    public TravelDetail? Travel { get; private set; }
    public string TypeLabels { get; private set; } = "";

    public IActionResult OnGet(long id)
    {
        using var cn = db.Open();
        var row = cn.QueryFirstOrDefault<CertIssuance>(IndexModel.BaseSelect + " AND i.id=@id", new { id });
        if (row is null) return NotFound();
        Item = row;
        TypeLabels = IssuanceOps.TypesLabel(cn, row.CertTypes);
        if (row.TravelId is not null)
            Travel = cn.QueryFirstOrDefault<TravelDetail>("SELECT * FROM travel_details WHERE id=@t",
                new { t = row.TravelId });
        return Page();
    }

    /// <summary>作废：签名不可编辑，登记有误走此路径。</summary>
    public IActionResult OnPostVoid(long id, string? voidReason)
    {
        using var cn = db.Open();
        var row = cn.QueryFirstOrDefault<CertIssuance>("SELECT * FROM cert_issuance WHERE id=@id", new { id });
        if (row is null) return NotFound();
        if (row.Status == "voided") { Flash.Info("该记录已是作废状态。"); return Redirect($"/Issuance/View/{id}"); }

        voidReason = (voidReason ?? "").Trim();
        if (voidReason.Length == 0)
        {
            Flash.Danger("作废原因为必填项。");
            return Redirect($"/Issuance/View/{id}");
        }

        var before = Helpers.RowSnapshot(cn, "cert_issuance", id);
        cn.Execute("UPDATE cert_issuance SET status='voided', void_reason=@r, updated_at=CURRENT_TIMESTAMP WHERE id=@id",
            new { r = voidReason, id });
        IssuanceOps.SyncTravelDates(cn, row.TravelId);
        Log(cn, "void", "cert_issuance", id, $"领用记录作废：{row.HolderName}，原因：{voidReason}",
            before, Helpers.RowSnapshot(cn, "cert_issuance", id));
        Flash.Info("领用记录已作废，如需更正请重新登记。");
        return Redirect($"/Issuance/View/{id}");
    }
}

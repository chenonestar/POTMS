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
    public bool CanFix { get; private set; }
    /// <summary>更正弹窗的证件种类选项。视图层不自己开连接，一律由此下发。</summary>
    public IReadOnlyList<DictOption> CertTypeOptions { get; private set; } = [];

    public IActionResult OnGet(long id)
    {
        using var cn = db.Open();
        var row = cn.QueryFirstOrDefault<CertIssuance>(IndexModel.BaseSelect + " AND i.id=@id", new { id });
        if (row is null) return NotFound();
        Item = row;
        TypeLabels = IssuanceOps.TypesLabel(cn, row.CertTypes);
        CanFix = IssuanceOps.CanFixCertTypes(row);
        CertTypeOptions = Helpers.GetDictOptions(cn, "cert_type");
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

    /// <summary>更正证件种类。仅限无签名的记录，判据见 IssuanceOps.CanFixCertTypes。</summary>
    public IActionResult OnPostCertTypes(long id, string[]? certTypes)
    {
        using var cn = db.Open();
        var row = cn.QueryFirstOrDefault<CertIssuance>("SELECT * FROM cert_issuance WHERE id=@id", new { id });
        if (row is null) return NotFound();

        IActionResult Back(string msg, Action<string> level)
        {
            level(msg);
            return Redirect($"/Issuance/View/{id}");
        }

        if (!IssuanceOps.CanFixCertTypes(row))
        {
            return Back("该记录已有领用人签名，证件种类不可更改；如登记有误请作废后重新登记。",
                        Flash.Warning);
        }

        var types = (certTypes ?? [])
            .Select(t => (t ?? "").Trim())
            .Where(t => t.Length > 0)
            .ToList();
        var bad = types.FirstOrDefault(t => !Db.CertTypeColumns.Any(c => c.Code == t));
        if (bad is not null) return Back($"无效的证件种类代码：{bad}。", Flash.Danger);
        if (types.Count == 0) return Back("请选择证件种类。", Flash.Danger);
        // 与新建同一条规则：一次出国申请只领一本证
        if (types.Count > 1) return Back("一次出国申请只能领用一本证件。", Flash.Danger);

        var before = Helpers.RowSnapshot(cn, "cert_issuance", id);
        // 备注里「待核实 / 按护照推定」这类字样已经不成立，一并清掉；
        // 人工核定的结果不该继续挂着机器推断的说明。
        var remarks = (row.Remarks ?? "").StartsWith("历史数据回填")
            ? "历史数据回填（证件种类已人工核定，无签名）"
            : row.Remarks;
        var joined = string.Join(",", types);
        var oldLabel = IssuanceOps.TypesLabel(cn, row.CertTypes);
        var newLabel = IssuanceOps.TypesLabel(cn, joined);
        cn.Execute(
            "UPDATE cert_issuance SET cert_types=@ct, remarks=@rm, updated_at=CURRENT_TIMESTAMP WHERE id=@id",
            new { ct = joined, rm = remarks, id });
        Log(cn, "update", "cert_issuance", id,
            $"更正证件种类：{row.HolderName}，{oldLabel} → {newLabel}",
            before, Helpers.RowSnapshot(cn, "cert_issuance", id));
        return Back("证件种类已更正。", Flash.Success);
    }
}

using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Personnel;

public class IndexModel(Db db, Flash flash) : AppPageModel(flash)
{
    public PageResult<PersonnelFiling> Items { get; private set; } = new();
    public string Search { get; set; } = "";
    public string StatusFilter { get; set; } = "";
    public string TagFilter { get; set; } = "";

    /// <summary>列表筛选，供导出复用。</summary>
    public static Filter BuildFilters(IQueryCollection q, IReadOnlyCollection<long>? ids = null)
    {
        var f = new Filter();
        f.Like("(pf.surname || pf.given_name LIKE {0} OR pf.id_number LIKE {1} OR pf.work_unit LIKE {2})",
               q["search"], 3);
        f.Eq("pf.status", q["status"]);
        f.Eq("pf.tag", q["tag"]);
        f.Ids("pf.id", ids);
        return f;
    }

    public void OnGet()
    {
        Search = Request.Query["search"].ToString();
        StatusFilter = Request.Query["status"].ToString();
        TagFilter = Request.Query["tag"].ToString();

        var f = BuildFilters(Request.Query);
        using var cn = db.Open();
        Items = Helpers.ListAll<PersonnelFiling>(cn,
            "SELECT pf.* FROM personnel_filing pf WHERE 1=1" + f.Where + " ORDER BY pf.created_at DESC",
            f.Params);
    }

    /// <summary>#3 删除守卫：名下有证照/明细/撤控/领用记录时禁止删除。</summary>
    public IActionResult OnPostDelete(long id)
    {
        using var cn = db.Open();
        if (cn.QueryFirstOrDefault<long?>("SELECT id FROM personnel_filing WHERE id=@id", new { id }) is null)
        {
            Flash.Danger("记录不存在。");
            return RedirectToPage();
        }
        var cert = cn.ExecuteScalar<int>("SELECT COUNT(*) FROM certificates WHERE personnel_filing_id=@id", new { id });
        var trav = cn.ExecuteScalar<int>("SELECT COUNT(*) FROM travel_details WHERE personnel_filing_id=@id", new { id });
        var dec = cn.ExecuteScalar<int>("SELECT COUNT(*) FROM decontrol_filing WHERE personnel_filing_id=@id", new { id });
        var iss = cn.ExecuteScalar<int>("SELECT COUNT(*) FROM cert_issuance WHERE personnel_filing_id=@id", new { id });
        if (cert + trav + dec + iss > 0)
        {
            Flash.Danger($"该人员名下尚有证照 {cert} 条、出国明细 {trav} 条、撤控记录 {dec} 条、证件领用 {iss} 条，" +
                         "请先删除或处理这些关联记录后再删除备案。");
            return RedirectToPage();
        }
        var before = Helpers.RowSnapshot(cn, "personnel_filing", id);
        cn.Execute("DELETE FROM personnel_filing WHERE id=@id", new { id });
        Log(cn, "delete", "personnel_filing", id, before: before);
        Flash.Info("备案记录已删除。");
        return RedirectToPage();
    }
}

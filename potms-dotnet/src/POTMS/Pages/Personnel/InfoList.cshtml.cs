using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Personnel;

/// <summary>#2 信息登记表管理页：显示关联备案数，仅孤儿行可删。</summary>
public class InfoListModel(Db db, Flash flash) : AppPageModel(flash)
{
    public PageResult<PersonnelInfo> Items { get; private set; } = new();
    public PaginationModel Pager { get; private set; } = new();
    public string Search { get; set; } = "";
    public string RefFilter { get; set; } = "";

    public static Filter BuildFilters(IQueryCollection q, IReadOnlyCollection<long>? ids = null)
    {
        var f = new Filter();
        f.Like("(pi.name LIKE {0} OR pi.id_number LIKE {1} OR pi.unit LIKE {2} OR pi.department LIKE {3})",
               q["search"], 4);
        var refFilter = q["ref"].ToString();
        if (refFilter == "orphan")
            f.Raw("NOT EXISTS (SELECT 1 FROM personnel_filing pf WHERE pf.personnel_info_id = pi.id)");
        else if (refFilter == "linked")
            f.Raw("EXISTS (SELECT 1 FROM personnel_filing pf WHERE pf.personnel_info_id = pi.id)");
        f.Ids("pi.id", ids);
        return f;
    }

    public void OnGet(int page = 1)
    {
        Search = Request.Query["search"].ToString();
        RefFilter = Request.Query["ref"].ToString();
        var f = BuildFilters(Request.Query);
        using var cn = db.Open();
        Items = Helpers.Paginate<PersonnelInfo>(cn,
            "SELECT pi.*, (SELECT COUNT(*) FROM personnel_filing pf WHERE pf.personnel_info_id = pi.id) AS filing_count " +
            "FROM personnel_info pi WHERE 1=1" + f.Where + " ORDER BY pi.created_at DESC",
            f.Params, page);
        Pager = PaginationModel.From(Items, Request);
    }

    /// <summary>#2 安全删除：仅当无任何备案表引用（孤儿行）时允许物理删除。</summary>
    public IActionResult OnPostDelete(long id)
    {
        using var cn = db.Open();
        var refs = cn.ExecuteScalar<int>(
            "SELECT COUNT(*) FROM personnel_filing WHERE personnel_info_id=@id", new { id });
        if (refs > 0)
        {
            Flash.Danger($"该信息登记表已被 {refs} 条备案记录引用，不能删除。");
            return RedirectToPage();
        }
        var before = Helpers.RowSnapshot(cn, "personnel_info", id);
        if (before is null) { Flash.Danger("记录不存在。"); return RedirectToPage(); }
        cn.Execute("DELETE FROM personnel_info WHERE id=@id", new { id });
        Log(cn, "delete", "personnel_info", id, detail: "删除无引用的信息登记表（孤儿行）", before: before);
        Flash.Info("信息登记表已删除。");
        return RedirectToPage();
    }
}

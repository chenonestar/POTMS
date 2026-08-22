using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Decontrol;

public class ViewPageModel(Db db, Flash flash) : AppPageModel(flash)
{
    public DecontrolFiling Item { get; private set; } = new();
    public PersonnelFiling? Successor { get; private set; }

    public IActionResult OnGet(long id)
    {
        using var cn = db.Open();
        var d = cn.QueryFirstOrDefault<DecontrolFiling>(
            "SELECT * FROM decontrol_filing WHERE id=@id", new { id });
        if (d is null) { Flash.Danger("记录不存在。"); return Redirect("/Decontrol"); }
        Item = d;
        // 原备案记录若已被重报替代，展示新记录链接
        var replaced = cn.QueryFirstOrDefault<long?>(
            "SELECT replaced_by_id FROM personnel_filing WHERE id=@id", new { id = d.PersonnelFilingId });
        if (replaced is not null)
            Successor = cn.QueryFirstOrDefault<PersonnelFiling>(
                "SELECT * FROM personnel_filing WHERE id=@i", new { i = replaced });
        return Page();
    }
}

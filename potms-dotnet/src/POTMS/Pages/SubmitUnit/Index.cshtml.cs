using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.SubmitUnit;

public class IndexModel(Db db, Flash flash) : AppPageModel(flash)
{
    public List<POTMS.Services.SubmitUnit> Items { get; private set; } = [];
    public Dictionary<long, int> Usage { get; private set; } = [];

    public void OnGet()
    {
        using var cn = db.Open();
        Items = Helpers.GetSubmitUnits(cn);
        foreach (var u in Items)
            Usage[u.Id] = cn.ExecuteScalar<int>(
                "SELECT COUNT(*) FROM decontrol_filing WHERE submit_unit_name=@n", new { n = u.Name });
    }

    public IActionResult OnPostSave(long? id, string? name, string? contact, string? phone, int sortOrder)
    {
        name = (name ?? "").Trim();
        if (name.Length == 0) { Flash.Danger("单位名称为必填项。"); return RedirectToPage(); }
        using var cn = db.Open();
        if (id is null)
        {
            cn.Execute("INSERT INTO sys_submit_unit (name, contact, phone, sort_order) VALUES (@n, @c, @p, @s)",
                new { n = name, c = contact?.Trim(), p = phone?.Trim(), s = sortOrder });
            var newId = cn.ExecuteScalar<long>("SELECT last_insert_rowid()");
            Log(cn, "create", "sys_submit_unit", newId, $"新增报送单位：{name}");
            Flash.Success("报送单位已新增。");
        }
        else
        {
            var before = Helpers.RowSnapshot(cn, "sys_submit_unit", id.Value);
            cn.Execute("UPDATE sys_submit_unit SET name=@n, contact=@c, phone=@p, sort_order=@s WHERE id=@id",
                new { n = name, c = contact?.Trim(), p = phone?.Trim(), s = sortOrder, id });
            Log(cn, "update", "sys_submit_unit", id, $"修改报送单位：{name}",
                before, Helpers.RowSnapshot(cn, "sys_submit_unit", id.Value));
            Flash.Success("报送单位已更新。");
        }
        return RedirectToPage();
    }

    public IActionResult OnPostDelete(long id)
    {
        using var cn = db.Open();
        var row = cn.QueryFirstOrDefault<string>("SELECT name FROM sys_submit_unit WHERE id=@id", new { id });
        if (row is null) { Flash.Danger("记录不存在。"); return RedirectToPage(); }
        var used = cn.ExecuteScalar<int>("SELECT COUNT(*) FROM decontrol_filing WHERE submit_unit_name=@n",
            new { n = row });
        if (used > 0)
        {
            Flash.Danger($"「{row}」已被 {used} 条撤控记录引用，不能删除。");
            return RedirectToPage();
        }
        var before = Helpers.RowSnapshot(cn, "sys_submit_unit", id);
        cn.Execute("DELETE FROM sys_submit_unit WHERE id=@id", new { id });
        Log(cn, "delete", "sys_submit_unit", id, $"删除报送单位：{row}", before);
        Flash.Info("报送单位已删除。");
        return RedirectToPage();
    }
}

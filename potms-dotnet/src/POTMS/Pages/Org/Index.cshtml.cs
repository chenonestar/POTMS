using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Org;

public class IndexModel(Db db, Flash flash) : AppPageModel(flash)
{
    public List<OrgOption> Tree { get; private set; } = [];
    public List<OrgNode> Flat { get; private set; } = [];
    public Dictionary<long, int> UsageCount { get; private set; } = [];

    public void OnGet()
    {
        using var cn = db.Open();
        Tree = Helpers.GetOrgTreeOptions(cn);
        Flat = Helpers.GetOrgFlat(cn);
        foreach (var n in Flat)
            UsageCount[n.Id] = cn.ExecuteScalar<int>(
                "SELECT (SELECT COUNT(*) FROM sys_org WHERE parent_id=@id) + " +
                "       (SELECT COUNT(*) FROM personnel_filing WHERE work_unit=@nm)", new { id = n.Id, nm = n.Name });
    }

    public IActionResult OnPostSave(long? id, string? name, long parentId, int sortOrder)
    {
        name = (name ?? "").Trim();
        if (name.Length == 0) { Flash.Danger("名称为必填项。"); return RedirectToPage(); }

        using var cn = db.Open();
        if (id is null)
        {
            cn.Execute("INSERT INTO sys_org (name, parent_id, sort_order) VALUES (@name, @p, @s)",
                new { name, p = parentId, s = sortOrder });
            var newId = cn.ExecuteScalar<long>("SELECT last_insert_rowid()");
            Log(cn, "create", "sys_org", newId, $"新增组织：{name}");
            Flash.Success("组织节点已新增。");
        }
        else
        {
            if (id == parentId) { Flash.Danger("上级不能是自己。"); return RedirectToPage(); }
            var before = Helpers.RowSnapshot(cn, "sys_org", id.Value);
            cn.Execute("UPDATE sys_org SET name=@name, parent_id=@p, sort_order=@s WHERE id=@id",
                new { name, p = parentId, s = sortOrder, id });
            Log(cn, "update", "sys_org", id, $"修改组织：{name}", before,
                Helpers.RowSnapshot(cn, "sys_org", id.Value));
            Flash.Success("组织节点已更新。");
        }
        return RedirectToPage();
    }

    /// <summary>删除守卫：有下级节点或被备案记录引用时禁止删除。</summary>
    public IActionResult OnPostDelete(long id)
    {
        using var cn = db.Open();
        var node = cn.QueryFirstOrDefault<OrgNode>(
            "SELECT id AS Id, name AS Name, parent_id AS ParentId, sort_order AS SortOrder " +
            "FROM sys_org WHERE id=@id", new { id });
        if (node is null) { Flash.Danger("节点不存在。"); return RedirectToPage(); }

        var children = cn.ExecuteScalar<int>("SELECT COUNT(*) FROM sys_org WHERE parent_id=@id", new { id });
        var used = cn.ExecuteScalar<int>("SELECT COUNT(*) FROM personnel_filing WHERE work_unit=@n",
            new { n = node.Name });
        if (children > 0 || used > 0)
        {
            Flash.Danger($"「{node.Name}」尚有下级节点 {children} 个、被 {used} 条备案记录引用，不能删除。");
            return RedirectToPage();
        }
        var before = Helpers.RowSnapshot(cn, "sys_org", id);
        cn.Execute("DELETE FROM sys_org WHERE id=@id", new { id });
        Log(cn, "delete", "sys_org", id, $"删除组织：{node.Name}", before);
        Flash.Info("组织节点已删除。");
        return RedirectToPage();
    }
}

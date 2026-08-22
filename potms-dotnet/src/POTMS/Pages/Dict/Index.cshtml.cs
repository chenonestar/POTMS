using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Dict;

public class IndexModel(Db db, Flash flash) : AppPageModel(flash)
{
    /// <summary>可维护的字典分类（分类本身固定，条目可增删改）。</summary>
    public static readonly (string Cat, string Label, string? UsageColumn, string? UsageTable)[] Categories =
    {
        ("education", "学历", "education", "personnel_info"),
        ("degree", "学位", "degree", "personnel_info"),
        ("title", "职称", "title", "personnel_info"),
        ("rank", "职级", "rank", "personnel_info"),
        ("political_status", "政治面貌", null, null),
        ("travel_category", "出国（境）类别", "category", "travel_details"),
        ("submit_unit_type", "报送单位类别", "submit_unit_type", "decontrol_filing"),
        ("supervisor_unit", "人事主管单位", null, null),
        ("cert_type", "证件种类（领用）", null, null),
    };

    public string Cat { get; private set; } = "education";
    public string CatLabel { get; private set; } = "";
    public List<Item> Items { get; private set; } = [];

    public void OnGet(string? cat)
    {
        Cat = Categories.Any(c => c.Cat == cat) ? cat! : "education";
        CatLabel = Categories.First(c => c.Cat == Cat).Label;
        var (_, _, col, tbl) = Categories.First(c => c.Cat == Cat);

        using var cn = db.Open();
        var rows = cn.Query<Item>(
            "SELECT id AS Id, code AS Code, value AS Value, sort_order AS SortOrder " +
            "FROM sys_dict WHERE category=@c ORDER BY sort_order, code", new { c = Cat }).AsList();

        // 统计引用数：仅对有对应业务列的分类统计
        foreach (var it in rows)
        {
            it.Usage = (col is null || tbl is null) ? -1
                : cn.ExecuteScalar<int>($"SELECT COUNT(*) FROM {tbl} WHERE {col} = @v",
                    new { v = Cat is "political_status" or "supervisor_unit" ? it.Value : it.Code });
        }
        Items = rows;
    }

    public IActionResult OnPostSave(string cat, long? id, string? code, string? value, int sortOrder)
    {
        code = (code ?? "").Trim();
        value = (value ?? "").Trim();
        if (code.Length == 0 || value.Length == 0)
        {
            Flash.Danger("代码与显示值均为必填项。");
            return RedirectToPage(new { cat });
        }
        using var cn = db.Open();
        var dup = cn.QueryFirstOrDefault<long?>(
            "SELECT id FROM sys_dict WHERE category=@c AND code=@code AND (@id IS NULL OR id != @id)",
            new { c = cat, code, id });
        if (dup is not null)
        {
            Flash.Danger($"代码 {code} 在该分类下已存在。");
            return RedirectToPage(new { cat });
        }

        if (id is null)
        {
            cn.Execute("INSERT INTO sys_dict (category, code, value, sort_order) VALUES (@c, @code, @v, @s)",
                new { c = cat, code, v = value, s = sortOrder });
            var newId = cn.ExecuteScalar<long>("SELECT last_insert_rowid()");
            Log(cn, "create", "sys_dict", newId, $"新增字典 {cat}: {code}={value}");
            Flash.Success("字典条目已新增。");
        }
        else
        {
            var before = Helpers.RowSnapshot(cn, "sys_dict", id.Value);
            cn.Execute("UPDATE sys_dict SET code=@code, value=@v, sort_order=@s WHERE id=@id",
                new { code, v = value, s = sortOrder, id });
            Log(cn, "update", "sys_dict", id, $"修改字典 {cat}: {code}={value}",
                before, Helpers.RowSnapshot(cn, "sys_dict", id.Value));
            Flash.Success("字典条目已更新。");
        }
        return RedirectToPage(new { cat });
    }

    /// <summary>删除守卫：已被业务数据引用的条目禁止删除。</summary>
    public IActionResult OnPostDelete(string cat, long id)
    {
        using var cn = db.Open();
        var row = cn.QueryFirstOrDefault("SELECT code, value FROM sys_dict WHERE id=@id", new { id });
        if (row is null) { Flash.Danger("条目不存在。"); return RedirectToPage(new { cat }); }

        var (_, label, col, tbl) = Categories.First(c => c.Cat == cat);
        if (col is not null && tbl is not null)
        {
            var v = cat is "political_status" or "supervisor_unit" ? (string)row.value : (string)row.code;
            var used = cn.ExecuteScalar<int>($"SELECT COUNT(*) FROM {tbl} WHERE {col} = @v", new { v });
            if (used > 0)
            {
                Flash.Danger($"「{row.value}」已被 {used} 条{label}数据引用，不能删除。");
                return RedirectToPage(new { cat });
            }
        }
        var before = Helpers.RowSnapshot(cn, "sys_dict", id);
        cn.Execute("DELETE FROM sys_dict WHERE id=@id", new { id });
        Log(cn, "delete", "sys_dict", id, $"删除字典 {cat}: {row.code}={row.value}", before);
        Flash.Info("字典条目已删除。");
        return RedirectToPage(new { cat });
    }

    public class Item
    {
        public long Id { get; set; }
        public string Code { get; set; } = "";
        public string Value { get; set; } = "";
        public long SortOrder { get; set; }
        public int Usage { get; set; }
    }
}

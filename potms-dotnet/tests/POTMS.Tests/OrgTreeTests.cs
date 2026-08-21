using System.Net;
using System.Text.RegularExpressions;
using Dapper;
using Microsoft.Data.Sqlite;
using Xunit;

namespace POTMS.Tests;

/// <summary>
/// 组织架构的树形界面。
///
/// 这一页原先是扁平表格 + 行内「排序」编辑框，改成与 Python / Go / Rust / Java
/// 一致的树形之后，有两处是靠人眼看不出来的：一是层级与展开次序，二是重命名时
/// 那个已经不在表单里的 sort_order 会不会被默默写成 0（模型绑定给非空 int 的
/// 默认值就是 0，一保存就把老库的排序抹平）。都在这里钉住。
/// </summary>
[Collection(AppCollection.Name)]
public class OrgTreeTests(SeededDbAppFactory factory)
{
    private static readonly Regex NodeName = new(
        """<span class="(?:fw-bold)?">([^<]+)</span>\s*<span class="badge""");

    [Fact]
    public async Task Tree_RendersHierarchyAndDropsSortField()
    {
        var client = await factory.LoggedInClientAsync();
        Exec("INSERT OR REPLACE INTO sys_org (id, name, parent_id, sort_order) VALUES " +
             "(41, '甲单位', 0, 1), (42, '乙部门', 41, 2), (43, '丙部门', 41, 1), (44, '丁科室', 43, 1)");

        var html = await (await client.GetAsync("/Org")).Content.ReadAsStringAsync();

        Assert.Contains("""badge bg-primary">单位""", html);
        Assert.Contains("""badge bg-info">部门""", html);
        Assert.Contains("""badge bg-secondary">子部门""", html);
        Assert.Contains("（下辖 2 个部门）", html);

        var names = NodeName.Matches(html).Select(m => m.Groups[1].Value.Trim()).ToList();
        var i = names.IndexOf("甲单位");
        Assert.True(i >= 0, "树里找不到甲单位：" + string.Join(" / ", names));
        Assert.Equal(new[] { "甲单位", "丙部门", "丁科室", "乙部门" }, names.Skip(i).Take(4));

        // 排序字段不再暴露在界面上
        Assert.DoesNotContain("""name="sortOrder""" + "\"", html);
    }

    [Fact]
    public async Task Rename_KeepsExistingSortOrder()
    {
        var client = await factory.LoggedInClientAsync();
        Exec("INSERT OR REPLACE INTO sys_org (id, name, parent_id, sort_order) VALUES (61, '戊单位', 0, 6)");

        var page = await (await client.GetAsync("/Org")).Content.ReadAsStringAsync();
        // 本项目把防伪字段名改成了与 Python 版一致的 csrf_token（Program.cs 里配的）
        var token = Regex.Match(page, """name="csrf_token"[^>]*value="([^"]+)""").Groups[1].Value;
        Assert.NotEmpty(token);

        // 树形界面的重命名表单只提交 id / name / parentId，没有 sortOrder
        var res = await client.PostAsync("/Org?handler=Save", new FormUrlEncodedContent(
            new Dictionary<string, string>
            {
                ["csrf_token"] = token,
                ["id"] = "61",
                ["name"] = "戊单位改名",
                ["parentId"] = "0",
            }));
        Assert.Equal(HttpStatusCode.Redirect, res.StatusCode);

        Assert.Equal("戊单位改名", Scalar<string>("SELECT name FROM sys_org WHERE id = 61"));
        Assert.Equal(6L, Scalar<long>("SELECT sort_order FROM sys_org WHERE id = 61"));
    }

    // ---- 直连库：验证「页面上看不见但库里必须对」的字段 ----

    private void Exec(string sql)
    {
        using var cn = Open();
        cn.Execute(sql);
    }

    private T? Scalar<T>(string sql)
    {
        using var cn = Open();
        return cn.ExecuteScalar<T>(sql);
    }

    private SqliteConnection Open()
    {
        var cn = new SqliteConnection($"Data Source={Path.Combine(factory.DataDir, "data.db")}");
        cn.Open();
        return cn;
    }
}

using System.Net;
using System.Text.RegularExpressions;
using Dapper;
using Microsoft.Data.Sqlite;
using Xunit;

namespace POTMS.Tests;

/// <summary>
/// 经办人身份的分层：业务单据记真实姓名，操作日志记登录账号。
///
/// 这不是显示细节，是两类字段的不同口径。账号是身份标识、姓名可以随时改，
/// 所以审计痕迹只能挂在账号上；而打印出来的领用凭证上一个 admin 没法拿去归档，
/// 必须是真人名字。改回任何一边都会被下面的用例抓住。
///
/// 每个用例结束时把 full_name 清回去——本 collection 的 HttpClient 是缓存复用的，
/// 留着姓名会渗进其它用例的库态。
/// </summary>
[Collection(AppCollection.Name)]
public class OperatorNameTests(SeededDbAppFactory factory)
{
    private const string Name = "张建国";

    [Fact]
    public void Users_HasFullNameColumn()
    {
        // 五版共用一个 data.db，users.full_name 必须由本版的建表 DDL 带出来
        using var cn = Open();
        var cols = cn.Query("PRAGMA table_info(users)").Select(r => (string)r.name).ToList();
        Assert.Contains("full_name", cols);
    }

    [Fact]
    public async Task Account_SavesFullNameAndRedirects()
    {
        var client = await factory.LoggedInClientAsync();
        try
        {
            await SaveFullName(client, Name);
            Assert.Equal(Name, Scalar<string>("SELECT full_name FROM users WHERE username='admin'"));
        }
        finally { await SaveFullName(client, ""); }
    }

    [Fact]
    public async Task IssuanceForm_ShowsRealNameAsOperator()
    {
        var client = await factory.LoggedInClientAsync();
        try
        {
            await SaveFullName(client, Name);
            var html = await (await client.GetAsync("/Issuance/Form")).Content.ReadAsStringAsync();
            Assert.Matches(new Regex("经办人（发放人）[\\s\\S]{0,200}value=\"" + Name + "\"[^>]*readonly"), html);
        }
        finally { await SaveFullName(client, ""); }
    }

    [Fact]
    public async Task PrintFooter_ShowsRealName()
    {
        var client = await factory.LoggedInClientAsync();
        try
        {
            await SaveFullName(client, Name);
            var html = await (await client.GetAsync("/Print/filing/1")).Content.ReadAsStringAsync();
            Assert.Contains($"操作人：{Name}", html);
        }
        finally { await SaveFullName(client, ""); }
    }

    [Fact]
    public async Task Dashboard_PromptsOnlyWhenNameMissing()
    {
        var client = await factory.LoggedInClientAsync();
        try
        {
            await SaveFullName(client, "");
            Assert.Contains("尚未填写", await (await client.GetAsync("/")).Content.ReadAsStringAsync());

            await SaveFullName(client, Name);
            Assert.DoesNotContain("尚未填写", await (await client.GetAsync("/")).Content.ReadAsStringAsync());
        }
        finally { await SaveFullName(client, ""); }
    }

    [Fact]
    public async Task LogsPage_RendersNameWithAccount()
    {
        var client = await factory.LoggedInClientAsync();
        try
        {
            await SaveFullName(client, Name);   // 这一步本身就会写一条 update users 日志
            var html = await (await client.GetAsync("/Logs")).Content.ReadAsStringAsync();
            Assert.Contains(Name, html);
            Assert.Contains("（admin）", html);
        }
        finally { await SaveFullName(client, ""); }
    }

    [Fact]
    public async Task Backfill_RewritesBusinessRowsButNotAuditTrail()
    {
        var client = await factory.LoggedInClientAsync();
        try
        {
            // 种子数据的经办人就是 admin，正是升级前的历史形态
            Assert.True(Scalar<long>("SELECT COUNT(*) FROM personnel_info WHERE operator='admin'") > 0);
            await SaveFullName(client, Name);

            var page = await (await client.GetAsync("/Account")).Content.ReadAsStringAsync();
            Assert.Contains("历史经办人回填", page);

            var res = await client.PostAsync("/Account?handler=Backfill", new FormUrlEncodedContent(
                new Dictionary<string, string> { ["csrf_token"] = Token(page) }));
            Assert.Equal(HttpStatusCode.Redirect, res.StatusCode);

            Assert.Equal(0L, Scalar<long>("SELECT COUNT(*) FROM personnel_info WHERE operator='admin'"));
            Assert.True(Scalar<long>($"SELECT COUNT(*) FROM personnel_info WHERE operator='{Name}'") > 0);
            // 审计痕迹不能被回填改掉
            Assert.Equal(0L, Scalar<long>($"SELECT COUNT(*) FROM operation_logs WHERE operator='{Name}'"));
            Assert.True(Scalar<long>("SELECT COUNT(*) FROM operation_logs WHERE operator='admin'") > 0);
        }
        finally
        {
            await SaveFullName(client, "");
            Exec($"UPDATE personnel_info SET operator='admin' WHERE operator='{Name}'");
            Exec($"UPDATE personnel_filing SET operator='admin' WHERE operator='{Name}'");
            Exec($"UPDATE certificates SET operator='admin' WHERE operator='{Name}'");
            Exec($"UPDATE travel_details SET operator='admin' WHERE operator='{Name}'");
            Exec($"UPDATE decontrol_filing SET operator='admin' WHERE operator='{Name}'");
            Exec($"UPDATE cert_issuance SET operator='admin' WHERE operator='{Name}'");
            Exec($"UPDATE cert_issuance SET issuer='admin' WHERE issuer='{Name}'");
        }
    }

    [Fact]
    public async Task Backfill_RefusedWithoutName()
    {
        var client = await factory.LoggedInClientAsync();
        await SaveFullName(client, "");
        var before = Scalar<long>("SELECT COUNT(*) FROM personnel_info WHERE operator='admin'");

        var page = await (await client.GetAsync("/Account")).Content.ReadAsStringAsync();
        var res = await client.PostAsync("/Account?handler=Backfill", new FormUrlEncodedContent(
            new Dictionary<string, string> { ["csrf_token"] = Token(page) }));
        Assert.Equal(HttpStatusCode.Redirect, res.StatusCode);

        Assert.Equal(before, Scalar<long>("SELECT COUNT(*) FROM personnel_info WHERE operator='admin'"));
    }

    // ---- 辅助 ----

    private async Task SaveFullName(HttpClient client, string name)
    {
        var page = await (await client.GetAsync("/Account")).Content.ReadAsStringAsync();
        var res = await client.PostAsync("/Account", new FormUrlEncodedContent(new Dictionary<string, string>
        {
            ["csrf_token"] = Token(page),
            ["currentPassword"] = "admin123",
            ["newUsername"] = "admin",
            ["newFullName"] = name,
        }));
        // 姓名没变时后端会以「未检测到任何修改」回 200，这在清理场景下是正常的
        Assert.True(res.StatusCode is HttpStatusCode.Redirect or HttpStatusCode.OK,
            $"保存姓名返回 {(int)res.StatusCode}");
    }

    private static string Token(string html) =>
        Regex.Match(html, """name="csrf_token"[^>]*value="([^"]+)""").Groups[1].Value;

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

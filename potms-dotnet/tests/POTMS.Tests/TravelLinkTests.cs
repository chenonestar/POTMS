using System.Net;
using System.Text.RegularExpressions;
using Dapper;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.DependencyInjection;
using POTMS.Services;
using Xunit;

namespace POTMS.Tests;

/// <summary>
/// 领用必须挂在出国申请上、路径B（做证）的逾期告警、证件号码派生、做证校验。
///
/// <para>四条规则同源：证件是为某一次已批准的出行借出/办理的。挂不上申请的领用记录
/// 是无主的，还会掉出逾期告警（告警按出行记录算）；路径B 压根没有领用记录（证是本人
/// 凭函去公安办的，从没进过保管处），原来的告警判据「passport_collect_date 非空」对它
/// 恒不成立，整类人不受监管；明细表上的证件号码原先手填，与领用记录各写各的，打印件上
/// 两个格子可能来自不同的证件；一本可用的证都没有却说不做证，这条申请本身就是错的。</para>
///
/// <para>造数刻意用<b>相对今天</b>的日期，让记录永远处于逾期状态，不依赖跑在哪一天。</para>
/// </summary>
[Collection(AppCollection.Name)]
public class TravelLinkTests(SeededDbAppFactory factory)
{
    private const long PathA = 801;      // 已有证件，走领用
    private const long PathB = 802;      // 做证，没有领用记录
    private const long FilingB = 802;    // 名下一本证都没有的备案人

    private static string YmdDaysAgo(int n) => DateTime.Now.AddDays(-n).ToString("yyyyMMdd");

    private SqliteConnection Open()
    {
        var cn = new SqliteConnection($"Data Source={Path.Combine(factory.DataDir, "data.db")}");
        cn.Open();
        return cn;
    }

    /// <summary>两条都已回国 90 天、证都没交回的申请，区别只在是否做证。</summary>
    private static void Seed(SqliteConnection cn)
    {
        var ago = YmdDaysAgo(90);
        cn.Execute(
            "INSERT OR REPLACE INTO personnel_filing (id, surname, given_name, gender, birth_date, " +
            "  id_number, residence, political_status, work_unit, position_or_title, " +
            "  supervisor_unit, operator) " +
            "VALUES (@f, '李', '四', '男', '19900101', '330201198001010011', '浙江宁波市鄞州区', " +
            "        '群众', '某某有限公司', '科长', '人事处', 'admin')", new { f = FilingB });
        cn.Execute(
            "INSERT OR REPLACE INTO travel_details (id, personnel_filing_id, unit, department, name, " +
            "  position, id_number, destination_passport, category, travel_dates, travel_start, " +
            "  travel_end, need_new_passport, actual_return_date, trip_status, operator) " +
            "VALUES (@a, 1, '某某有限公司', '工程技术部', '路径A张三', '工程师', '330201198001010011', " +
            "        '美国/护照', '因私', @dates, @ago, @ago, '否', @ago, 'normal', 'admin'), " +
            "       (@b, @f, '某某有限公司', '工程技术部', '路径B李四', '科长', '330201198001010011', " +
            "        '美国/护照', '因私', @dates, @ago, @ago, '是', @ago, 'normal', 'admin')",
            new { a = PathA, b = PathB, f = FilingB, dates = $"{ago}-{ago}", ago });
    }

    private static void Cleanup(SqliteConnection cn)
    {
        cn.Execute("DELETE FROM cert_issuance WHERE travel_id IN (@a, @b)", new { a = PathA, b = PathB });
        cn.Execute("DELETE FROM travel_details WHERE id IN (@a, @b)", new { a = PathA, b = PathB });
        cn.Execute("DELETE FROM certificates WHERE personnel_filing_id = @f", new { f = FilingB });
        cn.Execute("DELETE FROM personnel_filing WHERE id = @f", new { f = FilingB });
    }

    private static string Token(string html) =>
        Regex.Match(html, """name="csrf_token"[^>]*value="([^"]+)""").Groups[1].Value;

    /// <summary>提交一条挂在申请 801 上的领用登记，返回落地页 HTML。</summary>
    private static async Task<string> PostIssue(
        HttpClient client, params (string Key, string Value)[] over)
    {
        var page = await (await client.GetAsync($"/Issuance/Form?travelId={PathA}"))
            .Content.ReadAsStringAsync();
        var fields = new List<KeyValuePair<string, string>>
        {
            new("csrf_token", Token(page)),
            new("travel_id", PathA.ToString()),
            new("personnel_filing_id", "1"),
            new("holder_name", "路径A张三"),
            new("id_number", "330201198001010011"),
            new("cert_types", "01"),
            new("cert_nos", "E12345678"),
            new("issue_date", YmdDaysAgo(90)),
            new("sign_png", OnePixelPngDataUrl),
        };
        foreach (var (k, v) in over)
        {
            // cert_types 要能追加成多个；其余同名键替换
            if (k == "cert_types") { fields.Add(new(k, v)); continue; }
            var i = fields.FindIndex(kv => kv.Key == k);
            if (i >= 0) fields[i] = new(k, v); else fields.Add(new(k, v));
        }
        var res = await client.PostAsync("/Issuance/Form", new FormUrlEncodedContent(fields));
        // 成功是 302（跳详情），失败是 200（带 flash 重渲染）
        if (res.StatusCode == HttpStatusCode.Redirect)
            return await (await client.GetAsync(res.Headers.Location!.ToString())).Content.ReadAsStringAsync();
        return await res.Content.ReadAsStringAsync();
    }

    private static readonly string OnePixelPngDataUrl =
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ" +
        "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

    private static long IssuanceCount(SqliteConnection cn) =>
        cn.QuerySingle<long>("SELECT COUNT(*) FROM cert_issuance WHERE travel_id IN (@a, @b)",
            new { a = PathA, b = PathB });

    // -----------------------------------------------------------------------
    // A1 领用必须挂出国申请
    // -----------------------------------------------------------------------
    [Fact]
    public async Task IssueWithoutTravelIsRejected()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            Assert.Contains("关联出国申请", await PostIssue(client, ("travel_id", "")));
            Assert.Equal(0, IssuanceCount(cn));
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task IssueWithUnknownTravelIsRejected()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            Assert.Contains("关联的出国申请不存在", await PostIssue(client, ("travel_id", "999999")));
            Assert.Equal(0, IssuanceCount(cn));
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task HolderMustMatchApplicant()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            // 证是为这条申请借的，不能借给别人
            var html = await PostIssue(client,
                ("personnel_filing_id", FilingB.ToString()), ("holder_name", "路径B李四"));
            Assert.Contains("与该出国申请的申请人不一致", html);
            Assert.Equal(0, IssuanceCount(cn));
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task CancelledTripCannotIssue()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        cn.Execute("UPDATE travel_details SET trip_status='cancelled' WHERE id=@a", new { a = PathA });
        try
        {
            Assert.Contains("已取消行程", await PostIssue(client));
            Assert.Equal(0, IssuanceCount(cn));
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task OneCertPerApplication()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            Assert.Contains("只能领用一本证件", await PostIssue(client, ("cert_types", "02")));
            Assert.Equal(0, IssuanceCount(cn));
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task NewWithoutTravelIdShowsPicker()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            // 直接进新建页时先选申请，而不是给一个能不填的表单
            var html = await (await client.GetAsync("/Issuance/Form")).Content.ReadAsStringAsync();
            Assert.Contains("选择出国申请", html);
            Assert.Contains("登记领用", html);
            Assert.Contains("路径A张三", html);
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task PickerExcludesCancelledAndActiveIssuance()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            await PostIssue(client);      // 申请 801 现在有一条未归还记录
            cn.Execute("UPDATE travel_details SET trip_status='cancelled' WHERE id=@b", new { b = PathB });

            var html = await (await client.GetAsync("/Issuance/Form")).Content.ReadAsStringAsync();
            // 先确认这确实是选择页——否则「查不到那两个名字」在任何别的页面上都成立
            Assert.Contains("选择出国申请", html);
            Assert.DoesNotContain("路径A张三", html);
            Assert.DoesNotContain("路径B李四", html);
        }
        finally { Cleanup(cn); }
    }

    // -----------------------------------------------------------------------
    // A2 路径B 的逾期告警
    // -----------------------------------------------------------------------
    [Fact]
    public async Task PathBWithoutRegisteredCertIsOverdue()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            await PostIssue(client);      // 路径A 也造一条未归还的，作对照
            var ids = OverdueIds();
            Assert.Contains(PathA, ids);
            Assert.Contains(PathB, ids);
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task PathBClearedOnceCertRegistered()
    {
        await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            // 证交回入库、登记进台账之后就不该再告警
            cn.Execute("UPDATE travel_details SET passport_no='E99999999' WHERE id=@b", new { b = PathB });
            cn.Execute(
                "INSERT INTO certificates (personnel_filing_id, unit, department, name, " +
                "  passport_no, passport_expiry, passport_submit_date, operator) " +
                "VALUES (@f, '某某有限公司', '工程技术部', '路径B李四', 'E99999999', '20360101', " +
                "        '20260101', 'admin')", new { f = FilingB });
            Assert.DoesNotContain(PathB, OverdueIds());
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task PathBNumberRecordedButNotRegisteredStillOverdue()
    {
        await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            // 只在明细表补录了号码、没进台账，仍然算没交回
            cn.Execute("UPDATE travel_details SET passport_no='E99999999' WHERE id=@b", new { b = PathB });
            Assert.Contains(PathB, OverdueIds());
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task PathBNotOverdueBeforeDeadline()
    {
        await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            var today = YmdDaysAgo(0);
            cn.Execute("UPDATE travel_details SET actual_return_date=@t, travel_end=@t WHERE id=@b",
                       new { t = today, b = PathB });
            Assert.DoesNotContain(PathB, OverdueIds());
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task PathBShowsOnTravelListAndDashboard()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            Assert.Contains("路径B李四",
                await (await client.GetAsync("/Travel?passportStatus=overdue")).Content.ReadAsStringAsync());

            // 仪表盘不能只断言姓名出现——「近期出行」板块本来就会列出这个人，
            // 那样即使逾期统计完全失灵也照样通过。逾期清单那一行姓名后面跟的是
            // 单位与应还日期，查那个日期。
            var home = await (await client.GetAsync("/")).Content.ReadAsStringAsync();
            var m = Regex.Match(home, "路径B李四</td><td>[^<]*</td><td[^>]*>(\\d{8})</td>");
            Assert.True(m.Success, "仪表盘逾期清单里没有路径B（姓名后面没跟着应还日期）");
        }
        finally { Cleanup(cn); }
    }

    private List<long> OverdueIds() =>
        POTMS.Pages.Travel.IndexModel.OverdueIdSet(
            factory.Services.GetRequiredService<POTMS.Data.Db>(),
            factory.Services.GetRequiredService<POTMS.Config>());

    // -----------------------------------------------------------------------
    // C 证件号码派生
    // -----------------------------------------------------------------------
    [Fact]
    public async Task CertNoDerivedFromIssuance()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            await PostIssue(client, ("cert_nos", "E77778888"));
            Assert.Equal("E77778888", cn.QuerySingle<string>(
                "SELECT passport_no FROM travel_details WHERE id=@a", new { a = PathA }));

            // 表单上那一栏应变成只读。不能只查页面上有没有 readonly——领用日期、
            // 归还日期两栏本来就是只读的，那样查恒为真。只看 passport_no 这个 input。
            var html = await (await client.GetAsync($"/Travel/Form?id={PathA}")).Content.ReadAsStringAsync();
            var tag = PassportNoInput(html);
            Assert.Contains("readonly", tag);
        }
        finally { Cleanup(cn); }
    }

    private static string PassportNoInput(string html)
    {
        var i = html.IndexOf("name=\"passport_no\"", StringComparison.Ordinal);
        Assert.True(i >= 0, "页面上找不到证件号码输入框");
        var start = html.LastIndexOf("<input", i, StringComparison.Ordinal);
        var end = html.IndexOf('>', i);
        return html[start..(end + 1)];
    }

    // -----------------------------------------------------------------------
    // D 做证校验
    // -----------------------------------------------------------------------
    private static async Task<string> PostTravel(
        HttpClient client, params (string Key, string Value)[] over)
    {
        var page = await (await client.GetAsync("/Travel/Form")).Content.ReadAsStringAsync();
        var fields = new List<KeyValuePair<string, string>>
        {
            new("csrf_token", Token(page)),
            new("personnel_filing_id", FilingB.ToString()),
            new("unit", "某某有限公司"), new("department", "工程技术部"),
            new("name", "李四"), new("position", "科长"),
            new("id_number", "330201198001010011"),
            new("destination_passport", "美国-护照"), new("category", "因私"),
            new("travel_dates", "2026/09/01-2026/09/11"),
            new("need_new_passport", "否"),
        };
        foreach (var (k, v) in over)
        {
            var i = fields.FindIndex(kv => kv.Key == k);
            if (i >= 0) fields[i] = new(k, v); else fields.Add(new(k, v));
        }
        var res = await client.PostAsync("/Travel/Form", new FormUrlEncodedContent(fields));
        return await res.Content.ReadAsStringAsync();
    }

    [Fact]
    public async Task NoUsableCertMustMakeNew()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);      // 备案人 802 名下一本证都没有
        try
        {
            Assert.Contains("没有在有效期内的出入境证件", await PostTravel(client));
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task ExpiredCertCountsAsNone()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            // 一本过期护照等于没有——只看有没有号码是不够的
            cn.Execute(
                "INSERT INTO certificates (personnel_filing_id, unit, department, name, " +
                "  passport_no, passport_expiry, passport_submit_date, operator) " +
                "VALUES (@f, '某某有限公司', '工程技术部', '李四', 'E11112222', '20200101', " +
                "        '20190101', 'admin')", new { f = FilingB });
            Assert.Contains("没有在有效期内的出入境证件", await PostTravel(client));
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task ValidCertPassesPathA()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            cn.Execute(
                "INSERT INTO certificates (personnel_filing_id, unit, department, name, " +
                "  hm_pass_no, hm_pass_expiry, hm_pass_submit_date, operator) " +
                "VALUES (@f, '某某有限公司', '工程技术部', '李四', 'C11112222', '20360101', " +
                "        '20260101', 'admin')", new { f = FilingB });
            Assert.DoesNotContain("没有在有效期内的出入境证件", await PostTravel(client));
        }
        finally
        {
            cn.Execute("DELETE FROM travel_details WHERE personnel_filing_id=@f", new { f = FilingB });
            Cleanup(cn);
        }
    }

    [Fact]
    public async Task NeedNewPassportSkipsCertCheck()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            // 做证=是 时本来就没证，不该报这条
            Assert.DoesNotContain("没有在有效期内的出入境证件",
                await PostTravel(client, ("need_new_passport", "是")));
        }
        finally
        {
            cn.Execute("DELETE FROM travel_details WHERE personnel_filing_id=@f", new { f = FilingB });
            Cleanup(cn);
        }
    }
}

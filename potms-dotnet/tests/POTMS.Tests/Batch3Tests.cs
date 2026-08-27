using System.Net;
using System.Text.RegularExpressions;
using Dapper;
using Microsoft.Data.Sqlite;
using POTMS.Services;
using Xunit;

namespace POTMS.Tests;

/// <summary>
/// 第 3 批：领用列表批量打印、附件按办件顺序、证件种类单选、证照一人一行 + 换发提醒。
///
/// <para>四条都是「界面与语义」层面的：功能都在，但呈现或口径与 Python 版不一致，用起来
/// 会出错——批量打印缺一整个入口；附件按上传时间排，同一批次的先后跟办件顺序对不上；
/// 证件种类是复选框，而业务上一次申请只能领一本；证照允许同一个人建多条，于是两个
/// 编辑入口、预警报两遍。</para>
/// </summary>
[Collection(AppCollection.Name)]
public class Batch3Tests(SeededDbAppFactory factory)
{
    private SqliteConnection Open()
    {
        var cn = new SqliteConnection($"Data Source={Path.Combine(factory.DataDir, "data.db")}");
        cn.Open();
        return cn;
    }

    private static string Token(string html) =>
        Regex.Match(html, """name="csrf_token"[^>]*value="([^"]+)""").Groups[1].Value;

    // -----------------------------------------------------------------------
    // 1 批量打印
    // -----------------------------------------------------------------------
    [Fact]
    public async Task IssuanceListHasBatchPrint()
    {
        var client = await factory.LoggedInClientAsync();
        var html = await (await client.GetAsync("/Issuance")).Content.ReadAsStringAsync();
        Assert.Contains("批量打印", html);
        Assert.Contains("batchPrint('issuance')", html);
    }

    [Fact]
    public async Task BatchPrintIssuanceRendersRows()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        var id = cn.QuerySingle<long>("SELECT id FROM cert_issuance ORDER BY id LIMIT 1");

        var res = await client.GetAsync($"/Print/issuance?handler=Batch&ids={id}");
        Assert.Equal(HttpStatusCode.OK, res.StatusCode);
        var body = await res.Content.ReadAsStringAsync();
        Assert.Contains("因私出国（境）证件领用登记表", body);
        // 证件种类要印中文，不能印出 01
        Assert.Contains("因私护照", body);
    }

    [Fact]
    public async Task BatchPrintWithoutIdsIsRejected()
    {
        var client = await factory.LoggedInClientAsync();
        var res = await client.GetAsync("/Print/issuance?handler=Batch&ids=");
        Assert.Equal(HttpStatusCode.Redirect, res.StatusCode);
    }

    // -----------------------------------------------------------------------
    // 2 附件按办件顺序
    //
    // 本版的「附件总览」是按出行记录汇总的（一条申请一行 + 附件数），不是平铺的附件
    // 清单，所以「同一批次聚在一起」由结构本身保证。真正会错位的是单条申请下的附件
    // 列表：原来按 uploaded_at 排，补传过的件就会插到前面去，与办件顺序对不上。
    // -----------------------------------------------------------------------
    [Fact]
    public async Task TravelFilesOrderedByPaperworkSequence()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        const long travelId = 950;
        cn.Execute(
            "INSERT OR REPLACE INTO travel_details (id, personnel_filing_id, unit, department, name, " +
            "  position, id_number, destination_passport, category, travel_dates, need_new_passport, operator) " +
            "VALUES (@t, 1, '某某有限公司', '工程技术部', '附件某', '工程师', '330201198001010011', " +
            "        '美国/护照', '因私', '2026/03/01-2026/03/10', '是', 'admin')", new { t = travelId });
        // 刻意让上传时间与办件顺序相反：同意申办函最早传，个人申请报告最后补传
        cn.Execute(
            "INSERT OR REPLACE INTO attachments (id, travel_id, file_name, file_path, file_type, " +
            "  file_size, uploaded_at) VALUES " +
            "(9501, @t, 'c.pdf', 'x.pdf', '同意申办函', 1, '2026-03-01 10:00:00'), " +
            "(9502, @t, 'b.pdf', 'x.pdf', '审批表',     1, '2026-03-02 10:00:00'), " +
            "(9503, @t, 'a.pdf', 'x.pdf', '个人申请报告', 1, '2026-03-03 10:00:00')",
            new { t = travelId });
        try
        {
            var body = await (await client.GetAsync($"/Travel/View/{travelId}")).Content.ReadAsStringAsync();
            int ia = body.IndexOf("a.pdf", StringComparison.Ordinal);
            int ib = body.IndexOf("b.pdf", StringComparison.Ordinal);
            int ic = body.IndexOf("c.pdf", StringComparison.Ordinal);
            Assert.True(ia >= 0 && ib >= 0 && ic >= 0, "附件没有全部渲染出来");
            Assert.True(ia < ib && ib < ic,
                $"附件不是按办件顺序（个人申请报告 → 审批表 → 同意申办函），实际位置 {ia}/{ib}/{ic}");
        }
        finally
        {
            cn.Execute("DELETE FROM attachments WHERE travel_id=@t", new { t = travelId });
            cn.Execute("DELETE FROM travel_details WHERE id=@t", new { t = travelId });
        }
    }

    // -----------------------------------------------------------------------
    // 3 证件种类单选
    // -----------------------------------------------------------------------
    [Fact]
    public async Task IssuanceFormUsesRadioForCertType()
    {
        var client = await factory.LoggedInClientAsync();
        var body = await (await client.GetAsync("/Issuance/Form?travelId=1")).Content.ReadAsStringAsync();
        var i = body.IndexOf("name=\"cert_types\"", StringComparison.Ordinal);
        Assert.True(i >= 0, "表单上找不到证件种类控件");
        var start = body.LastIndexOf("<input", i, StringComparison.Ordinal);
        var tag = body[start..i];
        Assert.Contains("type=\"radio\"", tag);
    }

    // -----------------------------------------------------------------------
    // 4 证照一人一行 + 换发提醒
    // -----------------------------------------------------------------------
    private const long FilingC = 960;

    private static void SeedFiling(SqliteConnection cn) => cn.Execute(
        "INSERT OR REPLACE INTO personnel_filing (id, surname, given_name, gender, birth_date, " +
        "  id_number, residence, political_status, work_unit, position_or_title, supervisor_unit, operator) " +
        "VALUES (@f, '证', '照某', '男', '19900101', '330201198001010011', '浙江宁波市鄞州区', " +
        "        '群众', '某某有限公司', '科长', '人事处', 'admin')", new { f = FilingC });

    private static void CleanFiling(SqliteConnection cn)
    {
        cn.Execute("DELETE FROM certificates WHERE personnel_filing_id=@f", new { f = FilingC });
        cn.Execute("DELETE FROM personnel_filing WHERE id=@f", new { f = FilingC });
    }

    private static async Task<HttpResponseMessage> PostCert(
        HttpClient client, string url, params (string Key, string Value)[] over)
    {
        var page = await (await client.GetAsync(url)).Content.ReadAsStringAsync();
        var fields = new List<KeyValuePair<string, string>>
        {
            new("csrf_token", Token(page)),
            new("personnel_filing_id", FilingC.ToString()),
            new("unit", "某某有限公司"), new("department", "工程技术部"), new("name", "证照某"),
            new("passport_no", "E20000001"),
            new("passport_expiry", "20360101"), new("passport_submit_date", "20260101"),
        };
        foreach (var (k, v) in over)
        {
            var i = fields.FindIndex(kv => kv.Key == k);
            if (i >= 0) fields[i] = new(k, v); else fields.Add(new(k, v));
        }
        return await client.PostAsync(url, new FormUrlEncodedContent(fields));
    }

    [Fact]
    public async Task CertificateOneRowPerPerson()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        SeedFiling(cn);
        try
        {
            var first = await PostCert(client, "/Certificate/Form");
            Assert.Equal(HttpStatusCode.Redirect, first.StatusCode);

            var second = await PostCert(client, "/Certificate/Form", ("passport_no", "E30000003"));
            Assert.Equal(HttpStatusCode.OK, second.StatusCode);   // 被挡回，重渲染表单
            Assert.Contains("已有证照记录", await second.Content.ReadAsStringAsync());
            Assert.Equal(1, cn.QuerySingle<long>(
                "SELECT COUNT(*) FROM certificates WHERE personnel_filing_id=@f", new { f = FilingC }));
        }
        finally { CleanFiling(cn); }
    }

    [Fact]
    public async Task CertificateRenewalWarnsAboutDates()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        SeedFiling(cn);
        try
        {
            Assert.Equal(HttpStatusCode.Redirect, (await PostCert(client, "/Certificate/Form")).StatusCode);
            var certId = cn.QuerySingle<long>(
                "SELECT id FROM certificates WHERE personnel_filing_id=@f", new { f = FilingC });

            // 换发：只改号码，日期没跟着改
            var res = await PostCert(client, $"/Certificate/Form?id={certId}",
                ("passport_no", "E99999999"));
            Assert.Equal(HttpStatusCode.Redirect, res.StatusCode);
            var body = await (await client.GetAsync(res.Headers.Location!.ToString()))
                .Content.ReadAsStringAsync();
            Assert.Contains("号码已变更", body);
            Assert.Contains("护照", body);
        }
        finally { CleanFiling(cn); }
    }

    [Fact]
    public async Task CertificateEditWithoutNumberChangeIsQuiet()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        SeedFiling(cn);
        try
        {
            Assert.Equal(HttpStatusCode.Redirect, (await PostCert(client, "/Certificate/Form")).StatusCode);
            var certId = cn.QuerySingle<long>(
                "SELECT id FROM certificates WHERE personnel_filing_id=@f", new { f = FilingC });

            // 号码没动，只改了部门——不是换发，不该提醒
            var res = await PostCert(client, $"/Certificate/Form?id={certId}", ("department", "办公室"));
            Assert.Equal(HttpStatusCode.Redirect, res.StatusCode);
            var body = await (await client.GetAsync(res.Headers.Location!.ToString()))
                .Content.ReadAsStringAsync();
            Assert.DoesNotContain("号码已变更", body);
        }
        finally { CleanFiling(cn); }
    }
}

using System.Net;
using System.Text.RegularExpressions;
using Dapper;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Data.Sqlite;
using Xunit;

namespace POTMS.Tests;

/// <summary>全站 GET 页面冒烟：任何页面都不得返回 5xx。
///
/// 分两种库态各跑一遍，因为这两种状态触发的是不同的失败路径：
///
/// - **空库**：结果集为空时，<c>(SELECT COUNT(*) …)</c> 这类计算列没有声明类型，
///   Microsoft.Data.Sqlite 的 GetFieldType() 无值可推断而退化为 byte[]，
///   Dapper 便无法匹配位置式 record 的构造函数签名。/Travel/Attachments 曾因此 500，
///   而人工冒烟总是带着数据做，测不出来。
/// - **有数据**：dynamic 拆箱、字典键为 null、空集合上的 First() 等只有真取到行才会炸。
/// </summary>
[Collection(AppCollection.Name)]
public class EmptyDbPageSmokeTests(EmptyDbAppFactory factory)
{
    public static IEnumerable<object[]> Urls => SmokeUrls.All.Select(u => new object[] { u });

    [Theory]
    [MemberData(nameof(Urls))]
    public async Task Page_DoesNotFail(string url) => await SmokeUrls.AssertNot5xx(factory, url);

    /// <summary>登录本身在空库（仅有种子管理员）下必须可用。</summary>
    [Fact]
    public async Task Login_Succeeds()
    {
        var client = await factory.LoggedInClientAsync();
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/")).StatusCode);
    }
}

[Collection(AppCollection.Name)]
public class SeededDbPageSmokeTests(SeededDbAppFactory factory)
{
    public static IEnumerable<object[]> Urls => SmokeUrls.All.Select(u => new object[] { u });

    [Theory]
    [MemberData(nameof(Urls))]
    public async Task Page_DoesNotFail(string url) => await SmokeUrls.AssertNot5xx(factory, url);

    /// <summary>抽查若干页面确实取到了种子数据，避免"页面其实是空的所以不炸"的假通过。</summary>
    [Theory]
    [InlineData("/Travel/Attachments", "史迪威")]
    [InlineData("/Personnel", "史迪威")]
    [InlineData("/Issuance", "史迪威")]
    [InlineData("/Travel/View/1", "史迪威")]
    public async Task Page_RendersSeededRow(string url, string needle)
    {
        var client = await factory.LoggedInClientAsync();
        var res = await client.GetAsync(url);
        Assert.Equal(HttpStatusCode.OK, res.StatusCode);
        Assert.Contains(needle, await res.Content.ReadAsStringAsync());
    }
}

internal static class SmokeUrls
{
    /// <summary>全部 GET 页面。详情页统一用 id=1：空库下应 302 重定向，有数据时应 200。</summary>
    public static readonly string[] All =
    [
        "/",
        "/Login",
        "/Account",
        "/Search",
        "/Search?q=史",
        // 人员备案
        "/Personnel",
        "/Personnel?search=史&page=2",
        "/Personnel/InfoList",
        "/Personnel/InfoList?search=史&page=2",
        "/Personnel/InfoForm",
        "/Personnel/InfoForm?id=1",
        "/Personnel/FilingForm",
        "/Personnel/FilingForm?id=1",
        "/Personnel/View/1",
        // 证照
        "/Certificate",
        "/Certificate?search=史",
        "/Certificate/Form",
        "/Certificate/Form?id=1",
        // 出国明细（含本次出问题的附件总览）
        "/Travel",
        "/Travel?search=史",
        "/Travel/Form",
        "/Travel/Form?id=1",
        "/Travel/View/1",
        "/Travel/Attachments",
        "/Travel/Attachments?search=史",
        "/Travel/Attachment/1",
        // 证件领用
        "/Issuance",
        "/Issuance?search=史&status=issued&page=2",
        "/Issuance/Form",
        "/Issuance/Form?travel_id=1",
        "/Issuance/View/1",
        "/Issuance/Return/1",
        "/Issuance/Signature/1",
        // 撤控
        "/Decontrol",
        "/Decontrol?search=史",
        "/Decontrol/Form",
        "/Decontrol/Form?filing_id=1",
        "/Decontrol/View/1",
        // 配置与系统
        "/Dict",
        "/Dict?cat=title",
        "/Org",
        "/SubmitUnit",
        "/Logs",
        "/Logs?page=2&action=login",
        "/Import",
        "/Import?handler=Template",
        // 导出：空表与有数据都要能生成 xlsx
        "/Export",
        "/Export?handler=Info",
        "/Export?handler=Filing",
        "/Export?handler=Certificate",
        "/Export?handler=Travel",
        "/Export?handler=Decontrol",
        "/Export?handler=Issuance",
        "/Export?handler=Logs",
        // 打印
        "/Print/info/1",
        "/Print/filing/1",
        "/Print/certificate/1",
        "/Print/travel/1",
        "/Print/decontrol/1",
        "/Print/issuance/1",
        "/Print/batch/info?ids=1",
        "/Print/info?handler=Batch&ids=1",
    ];

    public static async Task AssertNot5xx(AppFactory factory, string url)
    {
        var client = await factory.LoggedInClientAsync();
        var res = await client.GetAsync(url);

        // 允许 200 / 302（记录不存在时重定向）/ 404，唯独不允许 5xx
        Assert.True((int)res.StatusCode < 500,
            $"GET {url} → {(int)res.StatusCode} {res.StatusCode}\n" +
            (res.StatusCode == HttpStatusCode.InternalServerError
                ? await res.Content.ReadAsStringAsync()
                : ""));
    }
}

/// <summary>两个 Factory 都通过进程级环境变量 POTMS_BASE 指定数据目录，
/// 必须串行；同一 collection 内的测试类由 xunit 顺序执行。</summary>
[CollectionDefinition(Name)]
public class AppCollection : ICollectionFixture<EmptyDbAppFactory>, ICollectionFixture<SeededDbAppFactory>
{
    public const string Name = "potms-app";
}

/// <summary>把应用跑在一个独立的临时数据目录上。</summary>
public abstract class AppFactory : WebApplicationFactory<Program>
{
    private readonly string _dir = Path.Combine(Path.GetTempPath(), "potms-smoke-" + Guid.NewGuid().ToString("N"));
    private Task<HttpClient>? _client;

    /// <summary>本实例的数据目录——用例要直连库核对「页面上看不见但必须对」的字段。</summary>
    public string DataDir => _dir;

    protected AppFactory() => Directory.CreateDirectory(_dir);

    /// <summary>建库、灌种子数据并登录一次，之后复用
    /// （Cookie 由 WAF 的 CookieContainerHandler 保持）。缓存的是 Task，
    /// 失败时也只跑一次，避免每个用例都重复插入种子而报唯一约束冲突、掩盖真正的首因。</summary>
    public Task<HttpClient> LoggedInClientAsync() => _client ??= CreateLoggedInAsync();

    private async Task<HttpClient> CreateLoggedInAsync()
    {
        // Program.cs 在建 Host 之前就读 POTMS_BASE 建库。两个 Factory 共用这个进程级变量，
        // 因此必须在自己 CreateClient 的紧邻处设置（构造函数里设会被另一个 Factory 覆盖），
        // 并靠同一 collection 的串行执行保证不交叉。Host 建好后 Config 已固化，改回也无妨。
        Environment.SetEnvironmentVariable("POTMS_BASE", _dir);
        // WAF 会先真跑一遍入口以捕获 Host 配置，UseUrls 的固定端口会与本机既有服务撞车；
        // 置 0 让内核分配临时端口（真正的请求走 TestServer，不经过它）
        Environment.SetEnvironmentVariable("POTMS_PORT", "0");

        var client = CreateClient(new WebApplicationFactoryClientOptions { AllowAutoRedirect = false });

        using (var cn = new SqliteConnection($"Data Source={Path.Combine(_dir, "data.db")}"))
        {
            cn.Open();
            Seed(cn);
        }

        var form = await (await client.GetAsync("/Login")).Content.ReadAsStringAsync();
        var token = Regex.Match(form, """name="csrf_token"[^>]*value="([^"]+)""").Groups[1].Value;
        Assert.NotEmpty(token);

        var res = await client.PostAsync("/Login", new FormUrlEncodedContent(new Dictionary<string, string>
        {
            ["csrf_token"] = token,
            ["username"] = "admin",
            ["password"] = "admin123",
        }));
        Assert.Equal(HttpStatusCode.Redirect, res.StatusCode);

        return client;
    }

    protected virtual void Seed(SqliteConnection cn) { }

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        if (!disposing) return;
        Environment.SetEnvironmentVariable("POTMS_BASE", null);
        Environment.SetEnvironmentVariable("POTMS_PORT", null);
        SqliteConnection.ClearAllPools();
        try { Directory.Delete(_dir, true); } catch (IOException) { }
    }
}

/// <summary>只有建表与种子字典，没有任何业务数据。</summary>
public sealed class EmptyDbAppFactory : AppFactory;

/// <summary>每张业务表各一行，且相互关联，使详情页 / 打印页 / 导出都能真正取到数据。</summary>
public sealed class SeededDbAppFactory : AppFactory
{
    /// <summary>1×1 透明 PNG，用作签名图——导出嵌图会解析 IHDR，必须是合法 PNG。</summary>
    private static readonly byte[] OnePixelPng = Convert.FromBase64String(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==");

    protected override void Seed(SqliteConnection cn)
    {
        cn.Execute(
            "INSERT INTO personnel_info (id, unit, department, name, gender, birth_date, rank, " +
            "  political_status, position, operator, education, degree, title) " +
            "VALUES (1, '某某有限公司', '工程技术部', '史迪威', '男', '19800101', '01', " +
            "        '中共党员', '工程师', 'admin', '01', '01', '01')");

        cn.Execute(
            "INSERT INTO personnel_filing (id, personnel_info_id, surname, given_name, gender, birth_date, " +
            "  id_number, residence, political_status, work_unit, position_or_title, supervisor_unit, " +
            "  operator, status) " +
            "VALUES (1, 1, '史', '迪威', '男', '19800101', '330201198001010011', '浙江宁波市鄞州区', " +
            "        '中共党员', '某某有限公司', '工程师', '某某国资委', 'admin', 'active')");

        cn.Execute(
            "INSERT INTO certificates (id, personnel_filing_id, unit, department, name, operator, " +
            "  passport_no, passport_expiry) " +
            "VALUES (1, 1, '某某有限公司', '工程技术部', '史迪威', 'admin', 'E12345678', '20301231')");

        cn.Execute(
            "INSERT INTO travel_details (id, personnel_filing_id, unit, department, name, position, id_number, " +
            "  destination_passport, category, travel_dates, travel_start, travel_end, operator, " +
            "  need_new_passport, trip_status) " +
            "VALUES (1, 1, '某某有限公司', '工程技术部', '史迪威', '工程师', '330201198001010011', " +
            "        '德国', '因公', '2026/09/01-2026/09/10', '20260901', '20260910', 'admin', '否', 'active')");

        cn.Execute(
            "INSERT INTO attachments (id, travel_id, file_name, file_path, file_type, file_size) " +
            "VALUES (1, 1, '申请表.pdf', 'uploads/nonexistent.pdf', 'application', 1024)");

        cn.Execute(
            "INSERT INTO decontrol_filing (id, personnel_filing_id, surname, given_name, gender, birth_date, " +
            "  id_number, residence, political_status, work_unit, supervisor_unit, submit_unit_name, " +
            "  submit_unit_type, submit_contact, submit_phone, batch_no, reason, operator) " +
            "VALUES (1, 1, '史', '迪威', '男', '19800101', '330201198001010011', '浙江宁波市鄞州区', " +
            "        '中共党员', '某某有限公司', '某某国资委', '某某国资委', '01', '张三', '0574-00000000', " +
            "        '2026-01', '岗位调整', 'admin')");

        cn.Execute(
            "INSERT INTO cert_issuance (id, travel_id, personnel_filing_id, holder_name, cert_types, " +
            "  issue_date, issuer, operator, status, sign_image, sign_meta) " +
            "VALUES (1, 1, 1, '史迪威', '01', '20260820', 'admin', 'admin', 'issued', @img, '{}')",
            new { img = OnePixelPng });

        cn.Execute(
            "INSERT INTO operation_logs (operator, action, target_type, target_id, detail, ip_address, snapshot) " +
            "VALUES ('admin', 'create', 'travel', 1, '新增出行记录', '127.0.0.1', " +
            "        '{\"before\":null,\"after\":{\"name\":\"史迪威\"}}')");
    }
}

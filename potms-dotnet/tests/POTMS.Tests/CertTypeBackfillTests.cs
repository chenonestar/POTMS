using System.Net;
using Dapper;
using Microsoft.Data.Sqlite;
using POTMS.Data;
using POTMS.Services;
using Xunit;

namespace POTMS.Tests;

/// <summary>
/// 历史回填的证件种类：三级推断 / 存量订正 / 待核实呈现 / 人工更正。
///
/// 原先回填一律把 cert_types 写成 '01'（因私护照）——往来港澳通行证、大陆居民往来
/// 台湾通行证全被标成护照。领用凭证是要归档的，错的种类比空着更糟。
///
/// 五版共用同一个 data.db，本版必须与 Python 版同口径：改对回填还不够，
/// 回填带幂等守卫，已经回填过的库要靠独立的订正迁移才能纠正。
/// </summary>
[Collection(AppCollection.Name)]      // 夹具要改进程级的 POTMS_BASE，必须与 Factory 串行
public class CertTypeBackfillTests
{
    // (姓名, certificates 填哪一列, 证件号, 出行表填的号, 「地点、证照」, 应判出)
    private static readonly (string Name, string Slot, string No, string TravNo, string Dest, string Want)[] Cases =
    [
        ("张三", "passport_no", "E12345678", "E12345678", "美国-护照", "01"),
        ("李四", "hm_pass_no", "C87654321", "C87654321", "香港", "02"),
        ("王五", "tw_pass_no", "T11112222", "T11112222", "台湾", "03"),
        ("赵六", "hm_pass_no", "C40000001", "", "澳门/港澳通行证", "02"),
        ("孙七", "passport_no", "E55556666", "", "泰国", "01"),
    ];

    /// <summary>造一个「升级前」的库：出行表已有领用日期。
    /// withIssuance=true 时先塞入错标的领用记录，模拟已被老版本回填过的存量库。</summary>
    private static void SeedLegacy(SqliteConnection cn, bool withIssuance)
    {
        for (int i = 0; i < Cases.Length; i++)
        {
            var c = Cases[i];
            long id = i + 1;
            cn.Execute(
                "INSERT INTO personnel_filing (id, surname, given_name, gender, birth_date, id_number, " +
                "  residence, political_status, work_unit, position_or_title, supervisor_unit, operator) " +
                "VALUES (@id, @nm, '', '男', '19900101', '330201198001010011', '浙江宁波市鄞州区', " +
                "        '群众', '总部', '科长', '人事处', 'admin')", new { id, nm = c.Name });
            cn.Execute(
                $"INSERT INTO certificates (personnel_filing_id, unit, department, name, {c.Slot}, operator) " +
                "VALUES (@id, '总部', '技术部', @nm, @no, 'admin')", new { id, nm = c.Name, no = c.No });
            cn.Execute(
                "INSERT INTO travel_details (id, personnel_filing_id, unit, department, name, position, " +
                "  id_number, destination_passport, category, travel_dates, need_new_passport, " +
                "  passport_no, passport_collect_date, operator) " +
                "VALUES (@id, @id, '总部', '技术部', @nm, '科长', '330201198001010011', @dest, '因私', " +
                "        '2026/03/01-2026/03/10', '否', @tno, '20260225', 'admin')",
                new { id, nm = c.Name, dest = c.Dest, tno = c.TravNo });
            if (withIssuance)
            {
                cn.Execute(
                    "INSERT INTO cert_issuance (id, travel_id, personnel_filing_id, holder_name, id_number, " +
                    "  cert_types, cert_nos, issue_date, issuer, status, remarks, operator) " +
                    "VALUES (@id, @id, @id, @nm, '330201198001010011', '01', @tno, '20260225', " +
                    "        'admin', 'issued', @rm, 'admin')",
                    new { id, nm = c.Name, tno = c.TravNo, rm = Db.BackfillRemarkLegacy });
            }
        }
    }

    private static Dictionary<string, string> StoredTypes(SqliteConnection cn) =>
        cn.Query("SELECT holder_name, cert_types FROM cert_issuance")
          .ToDictionary(r => (string)r.holder_name, r => (string?)r.cert_types ?? "");

    private static void AssertAllInferred(SqliteConnection cn)
    {
        var got = StoredTypes(cn);
        foreach (var c in Cases)
        {
            Assert.True(got.TryGetValue(c.Name, out var v) && v == c.Want,
                $"{c.Name} 的证件种类：得到 {got.GetValueOrDefault(c.Name)}，应为 {c.Want}");
        }
    }

    // -----------------------------------------------------------------------
    // 回填与订正（不经 HTTP，直接驱动迁移）
    // -----------------------------------------------------------------------
    [Fact]
    public void Backfill_InfersRealCertType()
    {
        using var f = new MigrationFixture();
        SeedLegacy(f.Cn, withIssuance: false);
        f.Migrate();
        AssertAllInferred(f.Cn);
    }

    [Fact]
    public void Backfill_MarksUndeterminableAsPending()
    {
        using var f = new MigrationFixture();
        // 三本证都有、出行表没填号码、文字里也没写证件名——数据里确实没有信息
        f.Cn.Execute(
            "INSERT INTO personnel_filing (id, surname, given_name, gender, birth_date, id_number, " +
            "  residence, political_status, work_unit, position_or_title, supervisor_unit, operator) " +
            "VALUES (9, '周', '八', '男', '19900101', '330201198001010011', '浙江宁波市鄞州区', " +
            "        '群众', '总部', '科长', '人事处', 'admin')");
        f.Cn.Execute(
            "INSERT INTO certificates (personnel_filing_id, unit, department, name, " +
            "  passport_no, hm_pass_no, tw_pass_no, operator) " +
            "VALUES (9, '总部', '技术部', '周八', 'E9', 'C9', 'T9', 'admin')");
        f.Cn.Execute(
            "INSERT INTO travel_details (id, personnel_filing_id, unit, department, name, position, " +
            "  id_number, destination_passport, category, travel_dates, need_new_passport, " +
            "  passport_collect_date, operator) " +
            "VALUES (9, 9, '总部', '技术部', '周八', '科长', '330201198001010011', '新加坡', '因私', " +
            "        '2026/03/01-2026/03/10', '否', '20260225', 'admin')");
        f.Migrate();

        Assert.Equal("", StoredTypes(f.Cn)["周八"]);
        Assert.Equal(Db.BackfillRemarkPending, f.Cn.QuerySingle<string>(
            "SELECT remarks FROM cert_issuance WHERE holder_name='周八'"));
    }

    [Fact]
    public void Correction_FixesExistingRows()
    {
        using var f = new MigrationFixture();
        SeedLegacy(f.Cn, withIssuance: true);
        Assert.All(StoredTypes(f.Cn).Values, v => Assert.Equal("01", v));   // 前置条件：全是错的

        // 光改回填没用——回填有幂等守卫，存量错标行不会被重算。必须有独立的订正。
        f.Migrate();
        AssertAllInferred(f.Cn);
    }

    [Fact]
    public void Correction_IsIdempotent()
    {
        using var f = new MigrationFixture();
        SeedLegacy(f.Cn, withIssuance: true);
        f.Migrate();
        var first = StoredTypes(f.Cn);

        f.Migrate();
        f.Migrate();
        Assert.Equal(first, StoredTypes(f.Cn));

        // 只比对结果不够：备注若没换掉，每次启动都会重跑、重复备份、重复写日志，
        // 而结果恰好相同，比对不出来。直接数日志条数。
        var n = f.Cn.QuerySingle<long>(
            "SELECT COUNT(*) FROM operation_logs WHERE action='migrate' AND target_type='cert_issuance'");
        Assert.True(n == 1, $"订正跑了 3 次，日志攒了 {n} 条——幂等守卫没生效");
    }

    [Fact]
    public void Correction_NeverTouchesSignedRecords()
    {
        using var f = new MigrationFixture();
        SeedLegacy(f.Cn, withIssuance: true);
        // 把李四那条伪装成「有签名但备注恰好也是旧串」的极端情形
        f.Cn.Execute("UPDATE cert_issuance SET sign_image = @b WHERE holder_name = '李四'",
                     new { b = new byte[] { 0x89, (byte)'P', (byte)'N', (byte)'G' } });
        f.Migrate();

        var got = StoredTypes(f.Cn);
        Assert.Equal("01", got["李四"]);      // 有签名的记录不该被订正改动
        Assert.Equal("03", got["王五"]);      // 无签名的记录照常订正
    }

    [Fact]
    public void Correction_LogsSummary()
    {
        using var f = new MigrationFixture();
        SeedLegacy(f.Cn, withIssuance: true);
        f.Migrate();
        var detail = f.Cn.QuerySingle<string>(
            "SELECT detail FROM operation_logs WHERE action='migrate' AND target_type='cert_issuance'");
        Assert.Contains("共 5 条", detail);
        Assert.Contains("推定 5 条", detail);
    }
}

/// <summary>
/// 人工更正入口与「待核实」的呈现 —— 走 HTTP，和用户看到的是同一条路。
///
/// 没有这个入口，「判不出就留空」等于制造一批永远填不上的死数据：新建强制签名，
/// 回填行没有签名也无从重录，只能就地更正。
/// </summary>
[Collection(AppCollection.Name)]
public class CertTypeCorrectionHttpTests(SeededDbAppFactory factory)
{
    private const long PendingId = 901;   // 回填判不出种类
    private const long SignedId = 902;    // 手工登记、已签名

    private SqliteConnection Open()
    {
        var cn = new SqliteConnection($"Data Source={Path.Combine(factory.DataDir, "data.db")}");
        cn.Open();
        return cn;
    }

    private static void Seed(SqliteConnection cn)
    {
        cn.Execute(
            "INSERT OR REPLACE INTO cert_issuance (id, personnel_filing_id, holder_name, id_number, " +
            "  cert_types, cert_nos, issue_date, issuer, status, remarks, operator, sign_image) " +
            "VALUES (@pid, 1, '待核实某', '330201198001010011', '', '', '20260225', 'admin', " +
            "        'issued', @rm, 'admin', NULL), " +
            "       (@sid, 1, '已签某', '330201198001010011', '01', 'E1', '20260225', 'admin', " +
            "        'issued', @rm, 'admin', @png)",
            new { pid = PendingId, sid = SignedId, rm = Db.BackfillRemarkPending,
                  png = new byte[] { 0x89, (byte)'P', (byte)'N', (byte)'G' } });
    }

    private static void Cleanup(SqliteConnection cn) =>
        cn.Execute("DELETE FROM cert_issuance WHERE id IN (@a, @b)",
                   new { a = PendingId, b = SignedId });

    private static string Types(SqliteConnection cn, long id) =>
        cn.QuerySingle<string>("SELECT cert_types FROM cert_issuance WHERE id=@id", new { id });

    private static string Token(string html) =>
        System.Text.RegularExpressions.Regex
            .Match(html, """name="csrf_token"[^>]*value="([^"]+)""").Groups[1].Value;

    /// <summary>提交更正并跟随重定向，返回落地页 HTML（flash 提示在那上面）。</summary>
    private static async Task<string> PostCertTypes(
        HttpClient client, long id, params string[] types)
    {
        var page = await (await client.GetAsync($"/Issuance/View/{id}")).Content.ReadAsStringAsync();
        var fields = new List<KeyValuePair<string, string>> { new("csrf_token", Token(page)) };
        fields.AddRange(types.Select(t => new KeyValuePair<string, string>("certTypes", t)));

        var res = await client.PostAsync($"/Issuance/View/{id}?handler=CertTypes",
                                         new FormUrlEncodedContent(fields));
        Assert.Equal(HttpStatusCode.Redirect, res.StatusCode);
        return await (await client.GetAsync(res.Headers.Location!.ToString())).Content.ReadAsStringAsync();
    }

    [Fact]
    public async Task PendingRow_CanBeCorrected()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            Assert.Equal("", Types(cn, PendingId));
            Assert.Contains("证件种类已更正", await PostCertTypes(client, PendingId, "02"));
            Assert.Equal("02", Types(cn, PendingId));
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task Correction_RejectedOnSignedRecord()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            // 有签名的记录连「更正」入口都不该出现
            var page = await (await client.GetAsync($"/Issuance/View/{SignedId}")).Content.ReadAsStringAsync();
            Assert.DoesNotContain("更正证件种类", page);
            // 就算绕过界面直接提交，服务端也要挡回
            Assert.Contains("不可更改", await PostCertTypes(client, SignedId, "02"));
            Assert.Equal("01", Types(cn, SignedId));
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task Correction_RejectsInvalidEmptyAndMulti()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            Assert.Contains("无效的证件种类代码", await PostCertTypes(client, PendingId, "99"));
            Assert.Contains("请选择证件种类", await PostCertTypes(client, PendingId));
            Assert.Contains("只能领用一本证件", await PostCertTypes(client, PendingId, "01", "02"));
            Assert.Equal("", Types(cn, PendingId));      // 一次都没被改坏
        }
        finally { Cleanup(cn); }
    }

    [Fact]
    public async Task PendingFilter_FindsThemAndShowsBadge()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        Seed(cn);
        try
        {
            // 现有筛选是 (','||cert_types||',') LIKE '%,01,%'，对空值恒不匹配，
            // 筛不出来这批待办就没法收口
            var html = await (await client.GetAsync("/Issuance?certType=pending"))
                .Content.ReadAsStringAsync();
            Assert.Contains("待核实某", html);
            Assert.DoesNotContain("已签某", html);
            // 列表与详情都要写明「待核实」，空白格子会被当成漏渲染
            Assert.Contains("待核实</span>", html);
            Assert.Contains("待核实</span>", await (await client.GetAsync($"/Issuance/View/{PendingId}"))
                .Content.ReadAsStringAsync());
        }
        finally { Cleanup(cn); }
    }
}

/// <summary>
/// 直接驱动迁移的夹具：独立的临时数据目录 + 一个可反复调用的 Migrate()。
///
/// cert_issuance 是在迁移里建的、不在基础 schema 里，所以构造时先空跑一次把表建出来
/// （此时还没有出行记录，回填无事可做），造完数据再调 Migrate() 才是被测的那一趟。
/// </summary>
public sealed class MigrationFixture : IDisposable
{
    private readonly string _dir;
    public SqliteConnection Cn { get; }

    public MigrationFixture()
    {
        _dir = Path.Combine(Path.GetTempPath(), "potms-bf-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_dir);
        Environment.SetEnvironmentVariable("POTMS_BASE", _dir);
        Migrate();
        Cn = new SqliteConnection($"Data Source={Path.Combine(_dir, "data.db")}");
        Cn.Open();
    }

    public void Migrate()
    {
        Environment.SetEnvironmentVariable("POTMS_BASE", _dir);
        var db = new Db(new Config());
        if (db.IsFirstRun)
        {
            db.Initialize();
            db.SeedData();
        }
        db.Migrate();
    }

    public void Dispose()
    {
        Cn.Dispose();
        Environment.SetEnvironmentVariable("POTMS_BASE", null);
        SqliteConnection.ClearAllPools();
        try { Directory.Delete(_dir, true); } catch (IOException) { }
    }
}

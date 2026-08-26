using System.Net;
using Dapper;
using Microsoft.Data.Sqlite;
using Xunit;

namespace POTMS.Tests;

/// <summary>
/// 出国明细列表的「证件逾期未还」分支。
///
/// 五版里这个分支从来没有任何用例覆盖过。Go 版因此带着一个到 2026-08-26 才引爆的
/// 故障：gonja 索引不了整数键的 map，模板里 deadlines[row.id] 一旦真有人逾期就
/// 渲染失败、整页 500——之前没暴露，只是因为测试数据还没跨过应还日期。
/// Rust 版同一处更隐蔽，minijinja 查不到键时静默渲染成空，页面上是「应还: )」。
///
/// 本版用的是 Dictionary&lt;long,string&gt;，键类型对得上，理应没问题——但「理应」
/// 不算数，补上用例把它钉住。
///
/// 造数刻意用**相对今天**的日期，让记录永远处于逾期状态，不依赖跑在哪一天。
/// </summary>
[Collection(AppCollection.Name)]
public class OverdueBranchTests(SeededDbAppFactory factory)
{
    private const long TravelId = 900;

    private static string YmdDaysAgo(int n) => DateTime.Now.AddDays(-n).ToString("yyyyMMdd");

    /// <summary>造一条「早就该交回却没交回」的出行记录：回国 90 天远超 10 个工作日。</summary>
    private static void SeedOverdue(SqliteConnection cn)
    {
        var ago = YmdDaysAgo(90);
        cn.Execute(
            "INSERT OR REPLACE INTO travel_details (id, personnel_filing_id, unit, department, name, " +
            "  position, id_number, destination_passport, category, travel_dates, travel_start, " +
            "  travel_end, operator, need_new_passport, trip_status, actual_return_date, " +
            "  passport_collect_date) " +
            "VALUES (@id, 1, '某某有限公司', '工程技术部', '逾期某', '工程师', '330201198001010011', " +
            "        '德国', '因私', @dates, @ago, @ago, 'admin', '否', 'normal', @ago, @collect)",
            new { id = TravelId, dates = $"{ago}-{ago}", ago, collect = YmdDaysAgo(120) });
    }

    private static void RemoveOverdue(SqliteConnection cn) =>
        cn.Execute("DELETE FROM travel_details WHERE id = @id", new { id = TravelId });

    private SqliteConnection Open()
    {
        var cn = new SqliteConnection($"Data Source={Path.Combine(factory.DataDir, "data.db")}");
        cn.Open();
        return cn;
    }

    [Fact]
    public async Task TravelList_RendersOverdueBranch()
    {
        // 先起 app：建表发生在应用启动时，早于它连库会「no such table」
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        SeedOverdue(cn);
        try
        {
            var res = await client.GetAsync("/Travel");
            Assert.Equal(HttpStatusCode.OK, res.StatusCode);
            var body = await res.Content.ReadAsStringAsync();

            Assert.Contains("逾期", body);
            Assert.Contains("逾期某", body);
            // 「应还」两个字在模板里是死的，光查它不够——必须确认后面真跟着日期。
            // 那正是 Go / Rust 两版失手的地方：字在、值是空的。
            var idx = body.IndexOf("应还", StringComparison.Ordinal);
            Assert.True(idx >= 0, "页面上没有「应还」字样");
            var after = body.Substring(idx + 2).TrimStart(' ', ':', '：');
            Assert.True(after.Length >= 8 && after[..8].All(char.IsAsciiDigit),
                $"应还到期日为空，实际渲染：「应还{after[..Math.Min(40, after.Length)]}」");
        }
        finally
        {
            RemoveOverdue(cn);
        }
    }

    [Fact]
    public async Task TravelList_OverdueFilterFindsIt()
    {
        var client = await factory.LoggedInClientAsync();
        using var cn = Open();
        SeedOverdue(cn);
        try
        {
            var res = await client.GetAsync("/Travel?passportStatus=overdue");
            Assert.Equal(HttpStatusCode.OK, res.StatusCode);
            Assert.Contains("逾期某", await res.Content.ReadAsStringAsync());
        }
        finally
        {
            RemoveOverdue(cn);
        }
    }
}

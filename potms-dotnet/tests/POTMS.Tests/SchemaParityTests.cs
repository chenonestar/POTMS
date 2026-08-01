using Dapper;
using Microsoft.Data.Sqlite;
using POTMS.Data;
using Xunit;

namespace POTMS.Tests;

/// <summary>Schema 与迁移的守护测试。
///
/// 四个语言版本（Python / Go / Rust / .NET）共用同一个 data.db，
/// 因此建表结果必须稳定；这些用例在 schema 意外漂移时先失败。
/// </summary>
public class SchemaParityTests : IDisposable
{
    private readonly string _dir = Path.Combine(Path.GetTempPath(), "potms-test-" + Guid.NewGuid().ToString("N"));
    private readonly Config _cfg;
    private readonly Db _db;

    public SchemaParityTests()
    {
        Dapper.DefaultTypeMap.MatchNamesWithUnderscores = true;
        Directory.CreateDirectory(_dir);
        _cfg = new Config(_dir);
        _db = new Db(_cfg);
        _db.Initialize();
        _db.SeedData();
        _db.Migrate();
    }

    public void Dispose()
    {
        SqliteConnection.ClearAllPools();
        try { Directory.Delete(_dir, true); } catch (IOException) { }
        GC.SuppressFinalize(this);
    }

    [Fact]
    public void CreatesAllExpectedTables()
    {
        using var cn = _db.Open();
        var tables = cn.Query<string>(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").ToHashSet();
        foreach (var t in new[]
                 {
                     "users", "personnel_info", "personnel_filing", "certificates", "travel_details",
                     "decontrol_filing", "sys_submit_unit", "cert_issuance", "attachments",
                     "sys_dict", "sys_org", "operation_logs",
                 })
            Assert.Contains(t, tables);
    }

    [Fact]
    public void CreatesAllExpectedIndexes()
    {
        using var cn = _db.Open();
        var idx = cn.Query<string>(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'").ToHashSet();
        foreach (var i in new[]
                 {
                     "idx_pf_id_number", "idx_pf_status", "idx_td_pf_id", "idx_cert_pf_id",
                     "idx_dec_pf_id", "idx_att_travel_id", "idx_logs_created_at",
                     "idx_issuance_travel", "idx_issuance_filing", "idx_issuance_status",
                 })
            Assert.Contains(i, idx);
    }

    [Fact]
    public void MigrateIsIdempotent()
    {
        using var cn = _db.Open();
        int Objects() => cn.ExecuteScalar<int>(
            "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'");
        int Dicts() => cn.ExecuteScalar<int>("SELECT COUNT(*) FROM sys_dict");

        var (o1, d1) = (Objects(), Dicts());
        _db.Migrate();
        _db.Migrate();
        Assert.Equal(o1, Objects());
        Assert.Equal(d1, Dicts());
    }

    [Fact]
    public void SeedsCertTypeDictionary()
    {
        using var cn = _db.Open();
        var codes = cn.Query<string>(
            "SELECT code FROM sys_dict WHERE category='cert_type' ORDER BY sort_order").AsList();
        Assert.Equal(new[] { "01", "02", "03" }, codes);
    }

    [Fact]
    public void SchemaGeneratorStaysInSyncWithPythonSource()
    {
        // Schema.cs 由 tools/gen-schema.py 从 Python 版 database.py 生成；
        // 这里确认生成物确实覆盖了三张关键表的关键列。
        Assert.Contains("CREATE TABLE IF NOT EXISTS cert_issuance", Schema.Ddl);
        Assert.Contains("sign_image BLOB", Schema.Ddl);
        Assert.Contains("personnel_filing_id INTEGER NOT NULL REFERENCES personnel_filing(id)", Schema.Ddl);
        Assert.Contains(Schema.SeedDict, x => x.Category == "cert_type" && x.Code == "01");
    }

    /// <summary>历史回填：旧库中出行表已有领用日期时，迁移应生成对应的领用记录。</summary>
    [Fact]
    public void BackfillsIssuanceFromLegacyTravelDates()
    {
        using (var cn = _db.Open())
        {
            cn.Execute(
                "INSERT INTO personnel_filing (id, surname, given_name, gender, birth_date, id_number, " +
                "residence, political_status, work_unit, position_or_title, supervisor_unit, operator) " +
                "VALUES (900, '张', '三', '男', '19900101', '110101199001012133', '北京', '群众', " +
                "'总部', '工程师', '人事处', 'admin')");
            cn.Execute(
                "INSERT INTO travel_details (id, personnel_filing_id, unit, department, name, position, " +
                "id_number, destination_passport, category, travel_dates, need_new_passport, " +
                "passport_no, passport_collect_date, passport_return_date, operator) " +
                "VALUES (900, 900, '总部', '技术部', '张三', '工程师', '110101199001012133', " +
                "'美国/护照', '01', '2026/07/01-2026/07/10', '否', 'E1', '20260701', NULL, 'admin')");
            cn.Execute(
                "INSERT INTO travel_details (id, personnel_filing_id, unit, department, name, position, " +
                "id_number, destination_passport, category, travel_dates, need_new_passport, " +
                "passport_no, passport_collect_date, passport_return_date, operator) " +
                "VALUES (901, 900, '总部', '技术部', '张三', '工程师', '110101199001012133', " +
                "'日本/护照', '01', '2026/06/01-2026/06/10', '否', 'E1', '20260601', '20260620', 'admin')");
        }

        _db.Migrate();

        using var c2 = _db.Open();
        var rows = c2.Query("SELECT travel_id, status, remarks FROM cert_issuance " +
                            "WHERE travel_id IN (900, 901) ORDER BY travel_id").AsList();
        Assert.Equal(2, rows.Count);
        Assert.Equal("issued", (string)rows[0].status);       // 未归还
        Assert.Equal("returned", (string)rows[1].status);     // 已归还
        Assert.Contains("历史数据回填", (string)rows[0].remarks);

        _db.Migrate();   // 幂等：不应重复回填
        Assert.Equal(2, c2.ExecuteScalar<int>(
            "SELECT COUNT(*) FROM cert_issuance WHERE travel_id IN (900, 901)"));
    }

    /// <summary>早期库的 travel_details 允许 personnel_filing_id 为空。
    /// 此类记录无法确定领用人，回填时应跳过而不是因 NOT NULL 约束崩溃。
    /// 现行 schema 已是 NOT NULL，故此处显式重建旧结构来模拟升级场景。</summary>
    [Fact]
    public void BackfillSkipsLegacyRowsWithoutFilingId()
    {
        using (var cn = _db.Open())
        {
            // 重建为旧结构：personnel_filing_id 可空
            cn.Execute("DROP TABLE travel_details");
            cn.Execute("""
                CREATE TABLE travel_details (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    personnel_filing_id INTEGER,
                    unit TEXT, department TEXT, name TEXT, position TEXT, title TEXT,
                    id_number TEXT, destination_passport TEXT, category TEXT,
                    travel_dates TEXT, approval_date TEXT, need_new_passport TEXT,
                    passport_no TEXT, passport_collect_date TEXT, passport_return_date TEXT,
                    operator TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
                """);
            cn.Execute(
                "INSERT INTO travel_details (id, personnel_filing_id, unit, name, travel_dates, " +
                "passport_collect_date, operator) VALUES (902, NULL, '总部', '李四', " +
                "'2026/07/01', '20260701', 'admin')");
        }

        _db.Migrate();   // 不应抛 NOT NULL 约束异常

        using var c2 = _db.Open();
        Assert.Equal(0, c2.ExecuteScalar<int>("SELECT COUNT(*) FROM cert_issuance WHERE travel_id = 902"));
        // 旧库缺失的列应被迁移补齐
        var cols = c2.Query("PRAGMA table_info(travel_details)").Select(r => (string)r.name).ToHashSet();
        Assert.Contains("travel_start", cols);
        Assert.Contains("trip_status", cols);
        Assert.Contains("actual_return_date", cols);
    }
}

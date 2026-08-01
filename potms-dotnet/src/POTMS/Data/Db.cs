using Dapper;
using Microsoft.Data.Sqlite;
using POTMS.Services;

namespace POTMS.Data;

/// <summary>数据访问 — 对应 Python 版 database.py / Rust 版 db.rs。
///
/// 设计说明：
/// - schema 由 tools/gen-schema.py 从 Python 版生成，四版共用同一个 data.db。
/// - 因此**不使用 EF Core Migrations**（它会引入 __EFMigrationsHistory 表并接管 schema，
///   破坏共用前提），而沿用与其它三版一致的「常量 DDL + 幂等 Migrate()」方式。
/// </summary>
public sealed class Db(Config cfg)
{
    private readonly Config _cfg = cfg;

    public SqliteConnection Open()
    {
        var cn = new SqliteConnection(_cfg.ConnectionString);
        cn.Open();
        cn.Execute("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;");
        return cn;
    }

    public bool IsFirstRun => !File.Exists(_cfg.Database);

    public void Initialize()
    {
        using var cn = Open();
        cn.Execute(Schema.Ddl);
    }

    // -----------------------------------------------------------------
    // 种子数据（幂等）
    // -----------------------------------------------------------------
    public void SeedData()
    {
        using var cn = Open();
        if (cn.QueryFirstOrDefault<long?>("SELECT id FROM users WHERE username = @u", new { u = "admin" }) is null)
        {
            cn.Execute("INSERT INTO users (username, password_hash) VALUES (@u, @p)",
                new { u = "admin", p = Security.HashPassword("admin123") });
        }
        SeedDict(cn);

        if (cn.QueryFirstOrDefault<long?>("SELECT id FROM sys_org LIMIT 1") is null)
        {
            var orgs = new (int Id, string Name, int Parent, int Sort)[]
            {
                (1, "总部", 0, 1), (2, "办公室", 1, 1), (3, "人事处", 1, 2),
                (4, "财务处", 1, 3), (5, "业务一部", 1, 4), (6, "业务二部", 1, 5),
            };
            // Dapper 不接受 ValueTuple 作参数对象，转匿名对象
            foreach (var (id, name, parent, sort) in orgs)
                cn.Execute("INSERT INTO sys_org (id, name, parent_id, sort_order) VALUES (@id, @name, @parent, @sort)",
                    new { id, name, parent, sort });
        }
    }

    private static void SeedDict(SqliteConnection cn)
    {
        foreach (var (cat, code, val, order) in Schema.SeedDict)
            cn.Execute("INSERT OR IGNORE INTO sys_dict (category, code, value, sort_order) " +
                       "VALUES (@cat, @code, @val, @order)",
                       new { cat, code, val, order });
    }

    // -----------------------------------------------------------------
    // 轻量迁移（幂等）—— 与 Python 版 run_migrations 逐条对应，
    // 使旧版本创建的 data.db 能被本版直接打开。
    // -----------------------------------------------------------------
    public void Migrate()
    {
        using var cn = Open();

        // 信息登记表：身份证号
        AddColumnIfMissing(cn, "personnel_info", "id_number", "TEXT");

        // 出国明细：规范化起止日期 / 实际回国 / 行程状态 / 取消日期
        var needBackfill = AddColumnIfMissing(cn, "travel_details", "travel_start", "TEXT");
        needBackfill |= AddColumnIfMissing(cn, "travel_details", "travel_end", "TEXT");
        AddColumnIfMissing(cn, "travel_details", "actual_return_date", "TEXT");
        if (AddColumnIfMissing(cn, "travel_details", "trip_status", "TEXT DEFAULT 'normal'"))
            cn.Execute("UPDATE travel_details SET trip_status = 'normal' " +
                       "WHERE trip_status IS NULL OR trip_status = ''");
        AddColumnIfMissing(cn, "travel_details", "cancel_date", "TEXT");

        // 操作日志：变更前后快照
        AddColumnIfMissing(cn, "operation_logs", "snapshot", "TEXT");

        // 撤控：证件移交日期 / 撤控日期
        AddColumnIfMissing(cn, "decontrol_filing", "cert_handover_date", "TEXT");
        if (AddColumnIfMissing(cn, "decontrol_filing", "decontrol_date", "TEXT"))
            cn.Execute("UPDATE decontrol_filing SET decontrol_date = strftime('%Y%m%d', created_at) " +
                       "WHERE decontrol_date IS NULL OR decontrol_date = ''");

        // 报送单位配置表
        cn.Execute("CREATE TABLE IF NOT EXISTS sys_submit_unit (" +
                   "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, " +
                   "contact TEXT, phone TEXT, sort_order INTEGER DEFAULT 0)");

        // 证件领用记录表（REQ-012）
        cn.Execute("""
            CREATE TABLE IF NOT EXISTS cert_issuance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                travel_id INTEGER REFERENCES travel_details(id),
                personnel_filing_id INTEGER NOT NULL REFERENCES personnel_filing(id),
                holder_name TEXT NOT NULL, id_number TEXT,
                cert_types TEXT NOT NULL, cert_nos TEXT,
                issue_date TEXT NOT NULL, issuer TEXT NOT NULL,
                sign_image BLOB, sign_meta TEXT,
                return_date TEXT, return_sign_image BLOB, return_sign_meta TEXT,
                return_operator TEXT,
                status TEXT NOT NULL DEFAULT 'issued', void_reason TEXT, remarks TEXT,
                operator TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
            """);
        cn.Execute("CREATE INDEX IF NOT EXISTS idx_issuance_travel ON cert_issuance(travel_id)");
        cn.Execute("CREATE INDEX IF NOT EXISTS idx_issuance_filing ON cert_issuance(personnel_filing_id)");
        cn.Execute("CREATE INDEX IF NOT EXISTS idx_issuance_status ON cert_issuance(status)");

        // 字典种子（存量库补齐新增分类，如 cert_type）
        SeedDict(cn);

        // 回填出行起止日期
        if (needBackfill)
        {
            var rows = cn.Query<(long Id, string? Dates)>(
                "SELECT id, travel_dates FROM travel_details").ToList();
            foreach (var (id, dates) in rows)
            {
                var (s, e) = Validators.ParseTravelRange(dates ?? "");
                cn.Execute("UPDATE travel_details SET travel_start=@s, travel_end=@e WHERE id=@id",
                    new { s, e, id });
            }
        }

        // 统一「计划出行日期」存储格式为 YYYY/MM/DD-YYYY/MM/DD。
        // 转换后含 '/'，以 NOT LIKE '%/%' 作幂等守卫，后续启动不再重复处理。
        var legacy = cn.Query<(long Id, string? Dates)>(
            "SELECT id, travel_dates FROM travel_details " +
            "WHERE travel_dates IS NOT NULL AND travel_dates != '' AND travel_dates NOT LIKE '%/%'").ToList();
        foreach (var (id, dates) in legacy)
        {
            var (s, e) = Validators.ParseTravelRange(dates ?? "");
            var canon = Validators.FormatTravelRange(s, e);
            if (canon.Length > 0)
                cn.Execute("UPDATE travel_details SET travel_dates=@c WHERE id=@id", new { c = canon, id });
        }

        BackfillIssuance(cn);
        BootstrapSupervisorUnits(cn);
        BootstrapSubmitUnits(cn);
        CreateIndexes(cn);
    }

    /// <summary>索引（幂等）：身份证查重、状态过滤、外键关联、日志时间筛选。
    /// 逐条容错：个别表/列在极旧库中缺失时跳过该条，不影响其余索引。</summary>
    private static void CreateIndexes(SqliteConnection cn)
    {
        string[] sqls =
        {
            "CREATE INDEX IF NOT EXISTS idx_pf_id_number ON personnel_filing(id_number)",
            "CREATE INDEX IF NOT EXISTS idx_pf_status ON personnel_filing(status)",
            "CREATE INDEX IF NOT EXISTS idx_td_pf_id ON travel_details(personnel_filing_id)",
            "CREATE INDEX IF NOT EXISTS idx_cert_pf_id ON certificates(personnel_filing_id)",
            "CREATE INDEX IF NOT EXISTS idx_dec_pf_id ON decontrol_filing(personnel_filing_id)",
            "CREATE INDEX IF NOT EXISTS idx_att_travel_id ON attachments(travel_id)",
            "CREATE INDEX IF NOT EXISTS idx_logs_created_at ON operation_logs(created_at)",
        };
        foreach (var sql in sqls)
        {
            try { cn.Execute(sql); }
            catch (SqliteException) { /* 极旧库缺表/缺列，跳过该条 */ }
        }
    }

    /// <summary>历史回填：已有「证件领用日期」的出行记录 → 生成对应领用记录（无签名）。
    /// 早期库允许 personnel_filing_id 为空，此类记录无法确定领用人，跳过。</summary>
    private static void BackfillIssuance(SqliteConnection cn)
    {
        // operator 是 C# 关键字，在 SQL 侧别名为 op 以便 dynamic 访问
        var rows = cn.Query(
            "SELECT t.id, t.personnel_filing_id, t.name, t.id_number, t.passport_no, " +
            "       t.passport_collect_date, t.passport_return_date, t.operator AS op " +
            "FROM travel_details t " +
            "WHERE t.passport_collect_date IS NOT NULL AND t.passport_collect_date != '' " +
            "  AND t.personnel_filing_id IS NOT NULL " +
            "  AND NOT EXISTS (SELECT 1 FROM cert_issuance c WHERE c.travel_id = t.id)").ToList();

        foreach (var r in rows)
        {
            string op = (string?)r.op ?? "system";
            string? ret = (string?)r.passport_return_date;
            cn.Execute(
                "INSERT INTO cert_issuance (travel_id, personnel_filing_id, holder_name, id_number, " +
                "cert_types, cert_nos, issue_date, issuer, return_date, return_operator, status, " +
                "remarks, operator) VALUES (@tid, @pfid, @nm, @idn, '01', @pno, @cdate, @op, " +
                "@ret, @retOp, @status, @remarks, @op)",
                new
                {
                    tid = (long)r.id,
                    pfid = (long)r.personnel_filing_id,
                    nm = (string?)r.name ?? "",
                    idn = (string?)r.id_number ?? "",
                    pno = (string?)r.passport_no ?? "",
                    cdate = (string)r.passport_collect_date,
                    op,
                    ret = string.IsNullOrEmpty(ret) ? null : ret,
                    retOp = string.IsNullOrEmpty(ret) ? null : op,
                    status = string.IsNullOrEmpty(ret) ? "issued" : "returned",
                    remarks = "历史数据回填（证件种类按护照推定，无签名）",
                });
        }
    }

    /// <summary>把已有记录中的人事主管单位去重补入字典。</summary>
    private static void BootstrapSupervisorUnits(SqliteConnection cn)
    {
        var existing = cn.Query<string>(
            "SELECT value FROM sys_dict WHERE category = 'supervisor_unit'").ToHashSet();
        var distinct = cn.Query<string>(
            "SELECT DISTINCT supervisor_unit FROM personnel_filing " +
            "WHERE supervisor_unit IS NOT NULL AND supervisor_unit != '' " +
            "UNION SELECT DISTINCT supervisor_unit FROM decontrol_filing " +
            "WHERE supervisor_unit IS NOT NULL AND supervisor_unit != ''").ToList();

        var maxN = 0;
        foreach (var code in cn.Query<string>("SELECT code FROM sys_dict WHERE category = 'supervisor_unit'"))
            if (code.StartsWith('S') && int.TryParse(code[1..], out var n)) maxN = Math.Max(maxN, n);

        var order = existing.Count;
        foreach (var val in distinct)
        {
            if (existing.Contains(val)) continue;
            maxN++; order++;
            cn.Execute("INSERT OR IGNORE INTO sys_dict (category, code, value, sort_order) " +
                       "VALUES ('supervisor_unit', @code, @val, @order)",
                       new { code = $"S{maxN:D2}", val, order });
            existing.Add(val);
        }
    }

    /// <summary>从已有撤控记录补齐报送单位配置（名称去重）。</summary>
    private static void BootstrapSubmitUnits(SqliteConnection cn)
    {
        var existing = cn.Query<string>("SELECT name FROM sys_submit_unit").ToHashSet();
        var rows = cn.Query(
            "SELECT submit_unit_name, submit_contact, submit_phone FROM decontrol_filing " +
            "WHERE submit_unit_name IS NOT NULL AND submit_unit_name != ''").ToList();
        var order = existing.Count;
        foreach (var r in rows)
        {
            string name = (string)r.submit_unit_name;
            if (existing.Contains(name)) continue;
            order++;
            cn.Execute("INSERT INTO sys_submit_unit (name, contact, phone, sort_order) " +
                       "VALUES (@name, @contact, @phone, @order)",
                       new { name, contact = (string?)r.submit_contact, phone = (string?)r.submit_phone, order });
            existing.Add(name);
        }
    }

    private static bool AddColumnIfMissing(SqliteConnection cn, string table, string column, string type)
    {
        var cols = cn.Query($"PRAGMA table_info({table})")
                     .Select(r => (string)r.name).ToHashSet(StringComparer.Ordinal);
        if (cols.Contains(column)) return false;
        cn.Execute($"ALTER TABLE {table} ADD COLUMN {column} {type}");
        return true;
    }
}

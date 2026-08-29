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

        // 登录账户的真实姓名。
        //
        // 单据上的「经办人」要写真人名字，不能写登录账号——打印出来的领用凭证上
        // 一个 admin，是没法拿去归档的。账号继续用于操作日志（账号是身份标识，
        // 姓名可以改；日志只记姓名的话，改名后历史记录就对不上人了）。
        AddColumnIfMissing(cn, "users", "full_name", "TEXT");

        // 撤控：证件移交日期 / 撤控日期
        AddColumnIfMissing(cn, "decontrol_filing", "cert_handover_date", "TEXT");
        if (AddColumnIfMissing(cn, "decontrol_filing", "decontrol_date", "TEXT"))
            cn.Execute("UPDATE decontrol_filing SET decontrol_date = strftime('%Y%m%d', created_at) " +
                       "WHERE decontrol_date IS NULL OR decontrol_date = ''");

        // 证件种类 01 的显示名与证照台账槽位标签对齐：因私护照 → 普通护照。
        // 业务表存的是编码（cert_issuance.cert_types = '01'），改显示值不动任何
        // 业务数据。五版共用一个 data.db，任何一版都要能把老库改过来。
        cn.Execute("UPDATE sys_dict SET value = '普通护照' " +
                   "WHERE category = 'cert_type' AND code = '01' AND value = '因私护照'");

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

    /// <summary>证件种类代码 → 证照登记表里对应的号码列。</summary>
    public static readonly (string Code, string Col)[] CertTypeColumns =
        [("01", "passport_no"), ("02", "hm_pass_no"), ("03", "tw_pass_no")];

    /// <summary>「地点、证照」自由文本里的证件名称关键字。
    /// 只认<b>证件名</b>不认地名——「香港」既可能持港澳通行证也可能持护照过境，
    /// 拿地名猜会猜错。顺序即优先级：先长后短。</summary>
    private static readonly (string Code, string[] Keywords)[] CertNameHints =
    [
        ("03", ["大陆居民往来台湾", "台湾通行证", "台胞证"]),
        ("02", ["往来港澳", "港澳通行证"]),
        ("01", ["护照"]),
    ];

    /// <summary>回填记录的备注。三个串互不相同，订正迁移靠「备注是否还是旧串」判断
    /// 是否已处理，改完备注下次启动自然扫不到，不需要额外的版本表。</summary>
    public const string BackfillRemarkLegacy = "历史数据回填（证件种类按护照推定，无签名）";
    public const string BackfillRemarkInferred = "历史数据回填（证件种类据证照登记推定，无签名）";
    public const string BackfillRemarkPending = "历史数据回填（证件种类待核实，无签名）";

    /// <summary>推断一条历史出行记录用的是哪种证件，判不出返回空串。
    ///
    /// <para>原先一律记作普通护照（'01'）。这是个<b>主动编造</b>的答案：往来港澳通行证、
    /// 台湾通行证都被写成护照，而领用凭证是要归档的，错的种类比空着更糟。</para>
    ///
    /// <para>三级判据，从硬到软：①出行记录上的证件号码对上证照登记表的哪一列（号码唯一，
    /// 最硬）；②「地点、证照」里出现的证件名称；③该人在证照登记表里只登记了一种证件。
    /// 三条都不成立时返回空串，宁可留空标「待核实」让人来补，也不替他猜一个。</para>
    ///
    /// <para>遍历该人<b>所有</b>证照记录合并三个槽位，不能只取一条：需求文档说证照登记
    /// 「一行为一人」，但现实里很容易出现「先登记了护照，过一阵办了港澳通行证时没找到
    /// 原记录，又新建了一条」。只看第一条会连着踩空三级判据，最后自信地答出错误答案。</para>
    /// </summary>
    public static string InferCertType(
        SqliteConnection cn, long personnelFilingId, string? certNo, string? destinationPassport)
    {
        var held = new string[3];
        foreach (var r in cn.Query(
            "SELECT passport_no, hm_pass_no, tw_pass_no FROM certificates " +
            "WHERE personnel_filing_id = @id ORDER BY id", new { id = personnelFilingId }))
        {
            string?[] vals = [(string?)r.passport_no, (string?)r.hm_pass_no, (string?)r.tw_pass_no];
            for (int i = 0; i < 3; i++)
            {
                held[i] ??= string.IsNullOrWhiteSpace(vals[i]) ? null! : vals[i]!.Trim();
            }
        }

        // ① 证件号匹配
        var no = (certNo ?? "").Trim();
        if (no.Length > 0)
        {
            for (int i = 0; i < 3; i++)
            {
                if (held[i] == no)
                {
                    return CertTypeColumns[i].Code;
                }
            }
        }

        // ② 「地点、证照」里的证件名称
        var text = destinationPassport ?? "";
        foreach (var (code, keywords) in CertNameHints)
        {
            if (keywords.Any(text.Contains))
            {
                return code;
            }
        }

        // ③ 该人只登记了一种证件
        var owned = Enumerable.Range(0, 3).Where(i => held[i] is not null).ToList();
        return owned.Count == 1 ? CertTypeColumns[owned[0]].Code : "";
    }

    /// <summary>历史回填：已有「证件领用日期」的出行记录 → 生成对应领用记录（无签名）。
    /// 早期库允许 personnel_filing_id 为空，此类记录无法确定领用人，跳过。</summary>
    private static void BackfillIssuance(SqliteConnection cn)
    {
        // operator 是 C# 关键字，在 SQL 侧别名为 op 以便 dynamic 访问
        var rows = cn.Query(
            "SELECT t.id, t.personnel_filing_id, t.name, t.id_number, t.passport_no, " +
            "       t.destination_passport, " +
            "       t.passport_collect_date, t.passport_return_date, t.operator AS op " +
            "FROM travel_details t " +
            "WHERE t.passport_collect_date IS NOT NULL AND t.passport_collect_date != '' " +
            "  AND t.personnel_filing_id IS NOT NULL " +
            "  AND NOT EXISTS (SELECT 1 FROM cert_issuance c WHERE c.travel_id = t.id)").ToList();

        foreach (var r in rows)
        {
            string op = (string?)r.op ?? "system";
            string? ret = (string?)r.passport_return_date;
            var ctype = InferCertType(cn, (long)r.personnel_filing_id,
                                      (string?)r.passport_no, (string?)r.destination_passport);
            cn.Execute(
                "INSERT INTO cert_issuance (travel_id, personnel_filing_id, holder_name, id_number, " +
                "cert_types, cert_nos, issue_date, issuer, return_date, return_operator, status, " +
                "remarks, operator) VALUES (@tid, @pfid, @nm, @idn, @ctype, @pno, @cdate, @op, " +
                "@ret, @retOp, @status, @remarks, @op)",
                new
                {
                    tid = (long)r.id,
                    pfid = (long)r.personnel_filing_id,
                    nm = (string?)r.name ?? "",
                    idn = (string?)r.id_number ?? "",
                    ctype,
                    pno = (string?)r.passport_no ?? "",
                    cdate = (string)r.passport_collect_date,
                    op,
                    ret = string.IsNullOrEmpty(ret) ? null : ret,
                    retOp = string.IsNullOrEmpty(ret) ? null : op,
                    status = string.IsNullOrEmpty(ret) ? "issued" : "returned",
                    remarks = ctype.Length > 0 ? BackfillRemarkInferred : BackfillRemarkPending,
                });
        }

        CorrectLegacyCertTypes(cn);
    }

    /// <summary>订正上一版回填留下的错标。
    ///
    /// <para>上面那段回填曾经把 cert_types 一律写成 '01'（普通护照），实际可能是往来港澳
    /// 通行证或大陆居民往来台湾通行证。而回填带幂等守卫（travel_id 已有记录就跳过），
    /// 光把上面改对，<b>对已经回填过的库毫无作用</b>——错的行会一直躺着。</para>
    ///
    /// <para>判据卡死在回填自己产的行上：备注是那句原文，且没有签名。手工登记的记录
    /// 有签名、备注也不同，碰不到。改完备注即失配，下次启动自然跳过。</para>
    /// </summary>
    private static void CorrectLegacyCertTypes(SqliteConnection cn)
    {
        var stale = cn.Query(
            "SELECT c.id, c.personnel_filing_id, c.cert_nos, c.travel_id " +
            "FROM cert_issuance c WHERE c.remarks = @legacy AND c.sign_image IS NULL",
            new { legacy = BackfillRemarkLegacy }).ToList();
        if (stale.Count == 0)
        {
            return;
        }
        // 动的是业务记录，先留一份改动前的快照。每日备份排在迁移之后，等它就晚了。
        // Db 的迁移不带 Config，这里就地构造一个——它只读环境变量与目录，代价可忽略。
        Backup.RunDaily(new Config(), force: true);

        int fixedCount = 0, pending = 0;
        foreach (var r in stale)
        {
            long? tid = (long?)r.travel_id;
            string? dest = tid is null ? null : cn.QuerySingleOrDefault<string>(
                "SELECT destination_passport FROM travel_details WHERE id = @id", new { id = tid });
            var ctype = InferCertType(cn, (long)r.personnel_filing_id, (string?)r.cert_nos, dest);
            if (ctype.Length > 0) { fixedCount++; } else { pending++; }
            cn.Execute(
                "UPDATE cert_issuance SET cert_types = @ct, remarks = @rm, " +
                "updated_at = CURRENT_TIMESTAMP WHERE id = @id",
                new
                {
                    ct = ctype,
                    rm = ctype.Length > 0 ? BackfillRemarkInferred : BackfillRemarkPending,
                    id = (long)r.id,
                });
        }
        // 直接写日志表：LogAction 依赖请求上下文，迁移跑在那之外。
        cn.Execute(
            "INSERT INTO operation_logs (operator, action, target_type, detail) " +
            "VALUES ('system', 'migrate', 'cert_issuance', @detail)",
            new
            {
                detail = $"订正历史回填的证件种类：共 {stale.Count} 条，" +
                         $"据证照登记推定 {fixedCount} 条，待核实 {pending} 条",
            });
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
        // PRAGMA 对不存在的表返回空集，这时直接返回——极旧的库可能连表都没有，
        // 对着不存在的表 ALTER 会抛异常，把启动整个搞挂。
        if (cols.Count == 0 || cols.Contains(column)) return false;
        cn.Execute($"ALTER TABLE {table} ADD COLUMN {column} {type}");
        return true;
    }
}

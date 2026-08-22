using System.Data;
using System.Globalization;
using System.Text.Json;
using Dapper;
using Microsoft.Data.Sqlite;

namespace POTMS.Services;

/// <summary>分页结果 — 对应 Python 版 PageResult。</summary>
public sealed class PageResult<T>
{
    public IReadOnlyList<T> Rows { get; init; } = [];
    public int Page { get; init; } = 1;
    public int Pages { get; init; } = 1;
    public int Total { get; init; }
    public bool HasPrev => Page > 1;
    public bool HasNext => Page < Pages;
}

/// <summary>通用助手 — 对应 Python 版 utils/helpers.py。</summary>
public static class Helpers
{
    // ---- 时间：数据库统一存 UTC，展示按固定偏移换算 ----
    public static string ToLocalTime(object? value, Config cfg, string fmt = "yyyy-MM-dd HH:mm:ss")
    {
        if (value is null) return "";
        var s = value as string ?? value.ToString() ?? "";
        if (s.Length == 0) return "";
        if (!DateTime.TryParse(s, CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out var utc))
            return s;   // 非时间戳内容原样返回
        return utc.AddHours(cfg.TzOffsetHours).ToString(fmt, CultureInfo.InvariantCulture);
    }

    public static string TodayLocal(Config cfg) =>
        DateTime.UtcNow.AddHours(cfg.TzOffsetHours).ToString("yyyyMMdd", CultureInfo.InvariantCulture);

    public static string NowUtcSql() =>
        DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);

    // ---- 姓名 / 户口 ----
    private static readonly string[] CompoundSurnames =
    {
        "欧阳", "司马", "上官", "诸葛", "令狐", "皇甫", "尉迟", "长孙",
        "宇文", "慕容", "夏侯", "东方",
    };

    /// <summary>按常见复姓拆分姓/名。</summary>
    public static (string Surname, string GivenName) DetectSurnameSplit(string fullName)
    {
        fullName = (fullName ?? "").Trim();
        if (fullName.Length == 0) return ("", "");
        foreach (var cs in CompoundSurnames)
            if (cs.Length == 2 && fullName.Length > 2 && fullName.StartsWith(cs, StringComparison.Ordinal))
                return (cs, fullName[2..]);
        return fullName.Length <= 1 ? (fullName, "") : (fullName[..1], fullName[1..]);
    }

    /// <summary>户口所在地规范化：省份不加"省"，历史区名统一映射。</summary>
    public static string NormalizeResidence(string? raw)
    {
        var s = (raw ?? "").Trim();
        if (s.Length == 0) return "";
        if (s.Contains("江东区", StringComparison.Ordinal) || s.Contains("鄞县", StringComparison.Ordinal))
            return "浙江宁波市鄞州区";
        return s;
    }

    // ---- 操作日志 ----
    private static readonly HashSet<string> SnapshotSkip = new(StringComparer.Ordinal)
    {
        "created_at", "updated_at",
        "sign_image", "sign_meta", "return_sign_image", "return_sign_meta",
    };

    /// <summary>row_snapshot 允许查询的表白名单（防御性：杜绝动态表名注入）。</summary>
    private static readonly HashSet<string> SnapshotTables = new(StringComparer.Ordinal)
    {
        "personnel_info", "personnel_filing", "certificates", "travel_details",
        "decontrol_filing", "sys_dict", "sys_org", "sys_submit_unit", "cert_issuance",
    };

    public static Dictionary<string, object?>? RowSnapshot(IDbConnection cn, string table, long id)
    {
        if (!SnapshotTables.Contains(table))
            throw new ArgumentException($"RowSnapshot: 不允许的表名 {table}", nameof(table));
        var row = cn.QueryFirstOrDefault($"SELECT * FROM {table} WHERE id = @id", new { id });
        if (row is null) return null;
        var dict = (IDictionary<string, object?>)row;
        return dict.Where(kv => !SnapshotSkip.Contains(kv.Key))
                   .ToDictionary(kv => kv.Key, kv => kv.Value);
    }

    public static void LogAction(IDbConnection cn, string @operator, string? ip, string action,
                                 string targetType, long? targetId = null, string? detail = null,
                                 Dictionary<string, object?>? before = null,
                                 Dictionary<string, object?>? after = null)
    {
        string? snapshot = null;
        if (before is not null || after is not null)
            snapshot = JsonSerializer.Serialize(new { before, after },
                new JsonSerializerOptions { Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping });

        cn.Execute(
            "INSERT INTO operation_logs (operator, action, target_type, target_id, detail, ip_address, snapshot) " +
            "VALUES (@op, @action, @tt, @tid, @detail, @ip, @snapshot)",
            new { op = @operator, action, tt = targetType, tid = targetId, detail, ip, snapshot });
    }

    // ---- 数据字典 ----
    public static List<DictOption> GetDictOptions(IDbConnection cn, string category) =>
        cn.Query<DictOption>(
            "SELECT code AS Code, value AS Value FROM sys_dict WHERE category = @c ORDER BY sort_order, code",
            new { c = category }).AsList();

    public static string GetDictValue(IDbConnection cn, string category, string? code)
    {
        if (string.IsNullOrEmpty(code)) return "";
        return cn.QueryFirstOrDefault<string>(
            "SELECT value FROM sys_dict WHERE category = @c AND code = @code",
            new { c = category, code }) ?? code;
    }

    // ---- 组织架构 ----
    public static List<OrgNode> GetOrgFlat(IDbConnection cn) =>
        cn.Query<OrgNode>("SELECT id AS Id, name AS Name, parent_id AS ParentId, sort_order AS SortOrder " +
                          "FROM sys_org ORDER BY parent_id, sort_order, id").AsList();

    /// <summary>层级缩进的下拉选项（父级用 — 前缀表示层级）。</summary>
    public static List<OrgOption> GetOrgTreeOptions(IDbConnection cn)
    {
        var all = GetOrgFlat(cn);
        var result = new List<OrgOption>();
        void Walk(long parent, int depth)
        {
            foreach (var n in all.Where(x => x.ParentId == parent))
            {
                result.Add(new OrgOption(n.Id, new string('—', depth) + (depth > 0 ? " " : "") + n.Name, n.Name, depth));
                Walk(n.Id, depth + 1);
            }
        }
        Walk(0, 0);
        return result;
    }

    public static List<OrgNode> GetOrgChildren(IDbConnection cn, long parentId = 0) =>
        cn.Query<OrgNode>("SELECT id AS Id, name AS Name, parent_id AS ParentId, sort_order AS SortOrder " +
                          "FROM sys_org WHERE parent_id = @p ORDER BY sort_order, id", new { p = parentId }).AsList();

    public static List<SubmitUnit> GetSubmitUnits(IDbConnection cn) =>
        cn.Query<SubmitUnit>("SELECT id AS Id, name AS Name, contact AS Contact, phone AS Phone " +
                             "FROM sys_submit_unit ORDER BY sort_order, id").AsList();

    // ---- 备案人员下拉（含证件号，供下游自动带入）----
    public static List<PersonOption> GetPersonnelOptions(IDbConnection cn)
    {
        var rows = cn.Query(
            "SELECT pf.id, pf.surname, pf.given_name, pf.work_unit, pf.id_number, pf.position_or_title, " +
            "COALESCE(pi.department, '') AS department, " +
            "(SELECT value FROM sys_dict WHERE category = 'title' AND code = pi.title) AS title_val " +
            "FROM personnel_filing pf " +
            "LEFT JOIN personnel_info pi ON pf.personnel_info_id = pi.id " +
            "WHERE pf.status = 'active' ORDER BY pf.surname, pf.given_name").ToList();

        // 每人已登记的证件号，一次查询建映射
        var certByType = new Dictionary<long, Dictionary<string, string>>();
        var certList = new Dictionary<long, List<string>>();
        foreach (var c in cn.Query("SELECT personnel_filing_id, passport_no, hm_pass_no, tw_pass_no FROM certificates"))
        {
            var pid = (long)c.personnel_filing_id;
            var byType = certByType.TryGetValue(pid, out var bt) ? bt : certByType[pid] = new();
            var list = certList.TryGetValue(pid, out var l) ? l : certList[pid] = new();
            foreach (var (code, v) in new (string, string?)[]
                     { ("01", c.passport_no), ("02", c.hm_pass_no), ("03", c.tw_pass_no) })
            {
                var val = v?.Trim();
                if (string.IsNullOrEmpty(val)) continue;
                if (!list.Contains(val)) list.Add(val);
                byType.TryAdd(code, val);
            }
        }

        var result = new List<PersonOption>();
        foreach (var r in rows)
        {
            long id = r.id;
            string name = $"{r.surname}{r.given_name}";
            result.Add(new PersonOption(
                id, name, $"{name} ({r.work_unit})", (string)r.work_unit,
                (string?)r.department ?? "", (string?)r.id_number ?? "",
                (string?)r.position_or_title ?? "", (string?)r.title_val ?? "",
                certList.TryGetValue(id, out var cl) ? cl : [],
                certByType.TryGetValue(id, out var cb) ? cb : []));
        }
        return result;
    }

    // ---- 分页 ----
    public static PageResult<T> Paginate<T>(IDbConnection cn, string sql, object? param,
                                            int page, int perPage = Config.PageSize)
    {
        var countSql = $"SELECT COUNT(*) FROM ({sql})";
        var total = cn.ExecuteScalar<int>(countSql, param);
        var pages = Math.Max(1, (int)Math.Ceiling(total / (double)perPage));
        page = Math.Clamp(page <= 0 ? 1 : page, 1, pages);
        var rows = cn.Query<T>($"{sql} LIMIT @limit OFFSET @offset",
            MergeParams(param, perPage, (page - 1) * perPage)).AsList();
        return new PageResult<T> { Rows = rows, Page = page, Pages = pages, Total = total };
    }

    /// <summary>全量下发（前端按视口窗口化分页），与其它三版的 list_all 一致。</summary>
    public static PageResult<T> ListAll<T>(IDbConnection cn, string sql, object? param)
    {
        var rows = cn.Query<T>(sql, param).AsList();
        return new PageResult<T> { Rows = rows, Page = 1, Pages = 1, Total = rows.Count };
    }

    private static DynamicParameters MergeParams(object? param, int limit, int offset)
    {
        var dp = new DynamicParameters(param);
        dp.Add("limit", limit);
        dp.Add("offset", offset);
        return dp;
    }
}

public record DictOption(string Code, string Value);
public record OrgNode(long Id, string Name, long ParentId, long SortOrder);
public record OrgOption(long Id, string Label, string Name, int Depth);
public record SubmitUnit(long Id, string Name, string? Contact, string? Phone);
public record PersonOption(long Id, string Name, string FullName, string Unit, string Department,
                           string IdNumber, string Position, string Title,
                           List<string> CertNos, Dictionary<string, string> CertByType);

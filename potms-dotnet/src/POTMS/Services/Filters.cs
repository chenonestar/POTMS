using Dapper;

namespace POTMS.Services;

/// <summary>列表筛选条件构造 —— 列表页与导出共用，保证「按当前筛选导出」口径一致。
/// 对应 Python 各蓝图的 build_filters。</summary>
public sealed class Filter
{
    private readonly List<string> _where = [];
    public DynamicParameters Params { get; } = new();
    private int _n;

    public string Where => _where.Count == 0 ? "" : " AND " + string.Join(" AND ", _where);

    public Filter Raw(string sql) { _where.Add(sql); return this; }

    public Filter Like(string sql, string? value, int placeholders = 1)
    {
        if (string.IsNullOrWhiteSpace(value)) return this;
        var names = new List<string>();
        for (var i = 0; i < placeholders; i++)
        {
            var n = $"p{_n++}";
            Params.Add(n, $"%{value.Trim()}%");
            names.Add("@" + n);
        }
        _where.Add(string.Format(sql, names.Cast<object>().ToArray()));
        return this;
    }

    public Filter Eq(string column, string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return this;
        var n = $"p{_n++}";
        Params.Add(n, value.Trim());
        _where.Add($"{column} = @{n}");
        return this;
    }

    public Filter Cmp(string column, string op, string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return this;
        var n = $"p{_n++}";
        Params.Add(n, Validators.ParseDateInput(value));
        _where.Add($"{column} {op} @{n}");
        return this;
    }

    /// <summary>选中行 ID 过滤（?ids=1,2,3）。</summary>
    public Filter Ids(string column, IReadOnlyCollection<long>? ids)
    {
        if (ids is null || ids.Count == 0) return this;
        var n = $"p{_n++}";
        Params.Add(n, ids);
        _where.Add($"{column} IN @{n}");
        return this;
    }

    public static List<long> ParseIds(string? raw) =>
        (raw ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries)
            .Select(s => long.TryParse(s.Trim(), out var v) ? v : -1)
            .Where(v => v > 0).ToList();

    /// <summary>导出范围说明，写入操作日志。</summary>
    public static string ScopeNote(string where, IReadOnlyCollection<long>? ids) =>
        ids is { Count: > 0 } ? $"选中{ids.Count}行" : where.Length > 0 ? "按筛选条件" : "全量";
}

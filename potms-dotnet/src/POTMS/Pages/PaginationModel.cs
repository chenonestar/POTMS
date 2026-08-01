using Microsoft.AspNetCore.Http;

namespace POTMS.Pages;

/// <summary>分页组件视图模型：保留当前查询串并替换其中的 page 参数。
/// 对应 Python 版 components/pagination.html 的 request.args.to_dict()+pop('page')。</summary>
public sealed class PaginationModel
{
    public int Page { get; init; } = 1;
    public int Pages { get; init; } = 1;
    public int Total { get; init; }
    public string Path { get; init; } = "";
    public IQueryCollection Query { get; init; } = new QueryCollection();

    public string PageUrl(int page)
    {
        var parts = Query
            .Where(kv => kv.Key != "page")
            .SelectMany(kv => kv.Value.Select(v => $"{Uri.EscapeDataString(kv.Key)}={Uri.EscapeDataString(v ?? "")}"))
            .ToList();
        parts.Add($"page={page}");
        return $"{Path}?{string.Join("&", parts)}";
    }

    public static PaginationModel From<T>(POTMS.Services.PageResult<T> pg, HttpRequest req) => new()
    {
        Page = pg.Page, Pages = pg.Pages, Total = pg.Total,
        Path = req.Path, Query = req.Query,
    };
}

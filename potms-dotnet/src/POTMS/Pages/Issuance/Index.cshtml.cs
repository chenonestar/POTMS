using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Issuance;

public class IndexModel(Db db, Flash flash) : AppPageModel(flash)
{
    public PageResult<CertIssuance> Items { get; private set; } = new();
    public PaginationModel Pager { get; private set; } = new();
    public string Search { get; set; } = "";
    public string StatusFilter { get; set; } = "";
    public string CertTypeFilter { get; set; } = "";
    public string DateFrom { get; set; } = "";
    public string DateTo { get; set; } = "";

    /// <summary>JOIN 备案表以排除孤儿行（延续 #4 的数据完整性口径）。</summary>
    public const string BaseSelect =
        "SELECT i.*, pf.work_unit AS work_unit FROM cert_issuance i " +
        "JOIN personnel_filing pf ON i.personnel_filing_id = pf.id WHERE 1=1";

    public static Filter BuildFilters(IQueryCollection q, IReadOnlyCollection<long>? ids = null)
    {
        var f = new Filter();
        f.Like("(i.holder_name LIKE {0} OR i.id_number LIKE {1} OR i.cert_nos LIKE {2})", q["search"], 3);
        var st = q["status"].ToString();
        if (st is "issued" or "returned" or "voided") f.Eq("i.status", st);
        var ct = q["certType"].ToString().Trim();
        if (ct == IssuanceOps.CertTypePending)
        {
            // 历史回填里判不出种类的那批，cert_types 为空。下面那句 LIKE 对空值恒不
            // 匹配（'' 拼出来是 ',,'），所以单开一条——不能筛出来，这批待办就没法收口。
            f.Raw("(i.cert_types IS NULL OR i.cert_types = '')");
        }
        else if (!string.IsNullOrWhiteSpace(ct))
        {
            f.Params.Add("ct", $"%,{ct},%");
            f.Raw("(',' || i.cert_types || ',') LIKE @ct");
        }
        f.Cmp("i.issue_date", ">=", q["dateFrom"]);
        f.Cmp("i.issue_date", "<=", q["dateTo"]);
        f.Ids("i.id", ids);
        return f;
    }

    public void OnGet(int page = 1)
    {
        Search = Request.Query["search"].ToString();
        StatusFilter = Request.Query["status"].ToString();
        CertTypeFilter = Request.Query["certType"].ToString();
        DateFrom = Request.Query["dateFrom"].ToString();
        DateTo = Request.Query["dateTo"].ToString();

        var f = BuildFilters(Request.Query);
        using var cn = db.Open();
        Items = Helpers.Paginate<CertIssuance>(cn,
            BaseSelect + f.Where + " ORDER BY i.issue_date DESC, i.id DESC", f.Params, page);
        Pager = PaginationModel.From(Items, Request);
    }
}

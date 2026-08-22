using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Certificate;

public class IndexModel(Db db, Config cfg, Flash flash) : AppPageModel(flash)
{
    public PageResult<POTMS.Data.Certificate> Items { get; private set; } = new();
    public string Search { get; set; } = "";
    public string HasPassport { get; set; } = "";
    public string HasHm { get; set; } = "";
    public string HasTw { get; set; } = "";
    /// <summary>(证照id, 证件名) → 到期日；用于列表高亮与顶部提示。</summary>
    public Dictionary<(long, string), string> Expiring { get; private set; } = [];

    public static Filter BuildFilters(IQueryCollection q, IReadOnlyCollection<long>? ids = null)
    {
        var f = new Filter();
        f.Like("(name LIKE {0} OR unit LIKE {1})", q["search"], 2);
        foreach (var (key, col) in new[] { ("hasPassport", "passport_no"), ("hasHm", "hm_pass_no"), ("hasTw", "tw_pass_no") })
        {
            var v = q[key].ToString();
            if (v == "1") f.Raw($"{col} IS NOT NULL AND {col} != ''");
            else if (v == "0") f.Raw($"({col} IS NULL OR {col} = '')");
        }
        f.Ids("id", ids);
        return f;
    }

    public void OnGet()
    {
        Search = Request.Query["search"].ToString();
        HasPassport = Request.Query["hasPassport"].ToString();
        HasHm = Request.Query["hasHm"].ToString();
        HasTw = Request.Query["hasTw"].ToString();

        var f = BuildFilters(Request.Query);
        using var cn = db.Open();
        Items = Helpers.ListAll<POTMS.Data.Certificate>(cn,
            "SELECT * FROM certificates WHERE 1=1" + f.Where + " ORDER BY updated_at DESC", f.Params);

        var today = Helpers.TodayLocal(cfg);
        var warn = DateTime.UtcNow.AddHours(cfg.TzOffsetHours)
            .AddDays(Config.CertExpiryWarnDays).ToString("yyyyMMdd");
        foreach (var r in Items.Rows)
            foreach (var (label, exp) in new[]
                     { ("普通护照", r.PassportExpiry), ("往来港澳通行证", r.HmPassExpiry),
                       ("大陆居民往来台湾通行证", r.TwPassExpiry) })
                if (!string.IsNullOrEmpty(exp) &&
                    string.CompareOrdinal(today, exp) <= 0 && string.CompareOrdinal(exp, warn) <= 0)
                    Expiring[(r.Id, label)] = exp;
    }

    public IActionResult OnPostDelete(long id)
    {
        using var cn = db.Open();
        var before = Helpers.RowSnapshot(cn, "certificates", id);
        if (before is null) { Flash.Danger("记录不存在。"); return RedirectToPage(); }
        cn.Execute("DELETE FROM certificates WHERE id=@id", new { id });
        Log(cn, "delete", "certificates", id, before: before);
        Flash.Info("证照记录已删除。");
        return RedirectToPage();
    }
}

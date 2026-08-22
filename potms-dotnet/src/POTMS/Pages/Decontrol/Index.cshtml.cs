using Microsoft.AspNetCore.Http;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Decontrol;

public class IndexModel(Db db, Flash flash) : AppPageModel(flash)
{
    public PageResult<DecontrolFiling> Items { get; private set; } = new();
    public string Search { get; set; } = "";
    public string BatchFilter { get; set; } = "";

    public static Filter BuildFilters(IQueryCollection q, IReadOnlyCollection<long>? ids = null)
    {
        var f = new Filter();
        f.Like("(surname || given_name LIKE {0} OR id_number LIKE {1} OR work_unit LIKE {2})", q["search"], 3);
        f.Eq("batch_no", q["batch"]);
        f.Ids("id", ids);
        return f;
    }

    public void OnGet()
    {
        Search = Request.Query["search"].ToString();
        BatchFilter = Request.Query["batch"].ToString();
        var f = BuildFilters(Request.Query);
        using var cn = db.Open();
        Items = Helpers.ListAll<DecontrolFiling>(cn,
            "SELECT * FROM decontrol_filing WHERE 1=1" + f.Where + " ORDER BY created_at DESC", f.Params);
    }
}

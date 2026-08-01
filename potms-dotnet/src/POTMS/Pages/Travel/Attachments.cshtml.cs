using Dapper;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Travel;

/// <summary>附件总览：按出行记录检查必传附件是否齐备，并统计各类型数量。</summary>
public class AttachmentsModel(Db db, Flash flash) : AppPageModel(flash)
{
    public string Search { get; set; } = "";
    public List<MissingItem> Missing { get; private set; } = [];
    public Dictionary<string, int> TypeCounts { get; private set; } = [];
    public List<Row> Items { get; private set; } = [];

    public void OnGet()
    {
        Search = Request.Query["search"].ToString();
        using var cn = db.Open();

        var f = new Filter();
        f.Like("(t.name LIKE {0} OR t.unit LIKE {1})", Search, 2);
        Items = cn.Query<Row>(
            "SELECT t.id AS Id, t.name AS Name, t.unit AS Unit, t.need_new_passport AS NeedNewPassport, " +
            "       t.travel_dates AS TravelDates, " +
            "       (SELECT COUNT(*) FROM attachments a WHERE a.travel_id = t.id) AS FileCount " +
            "FROM travel_details t WHERE 1=1" + f.Where + " ORDER BY t.created_at DESC", f.Params).AsList();

        // 缺件检查：路径A 须 2 类，路径B 须 3 类
        var have = cn.Query("SELECT travel_id, file_type FROM attachments")
            .GroupBy(r => (long)r.travel_id)
            .ToDictionary(g => g.Key, g => g.Select(x => (string)x.file_type).ToHashSet());

        foreach (var t in Items)
        {
            var required = t.NeedNewPassport == "是" ? Attachments.RequiredPathB : Attachments.RequiredPathA;
            var owned = have.TryGetValue(t.Id, out var s) ? s : [];
            var lack = required.Where(r => !owned.Contains(r)).ToList();
            if (lack.Count > 0)
                Missing.Add(new MissingItem(t.Id, t.Name, t.Unit,
                    t.NeedNewPassport == "是" ? "B" : "A", lack));
        }

        foreach (var g in cn.Query("SELECT file_type, COUNT(*) AS n FROM attachments GROUP BY file_type"))
            TypeCounts[(string)g.file_type] = (int)(long)g.n;
    }

    public record Row(long Id, string Name, string Unit, string? NeedNewPassport,
                      string? TravelDates, long FileCount);
    public record MissingItem(long Id, string Name, string Unit, string Path, List<string> Lack);
}

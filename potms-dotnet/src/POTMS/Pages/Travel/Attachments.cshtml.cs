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
                Missing.Add(new MissingItem(t.Id, t.Name ?? "", t.Unit ?? "",
                    t.NeedNewPassport == "是" ? "B" : "A", lack));
        }

        foreach (var g in cn.Query("SELECT file_type, COUNT(*) AS n FROM attachments GROUP BY file_type"))
        {
            var key = (string?)g.file_type;
            if (key is null) continue;      // 字典键不可为 null
            TypeCounts[key] = Convert.ToInt32(g.n);
        }
    }

    /// <summary>必须用属性式 record：FileCount 来自 COUNT(*) 子查询，是无声明类型的计算列。
    /// 结果集为空时 SQLite 无值可推断，Microsoft.Data.Sqlite 的 GetFieldType() 退化为 byte[]，
    /// 位置式 record 会因构造函数签名不匹配而在「出行表为空」时抛异常。
    /// 属性式走 setter，空结果集下不读取任何值，因而安全。</summary>
    public record Row
    {
        public long Id { get; init; }
        public string? Name { get; init; }
        public string? Unit { get; init; }
        public string? NeedNewPassport { get; init; }
        public string? TravelDates { get; init; }
        public long FileCount { get; init; }
    }
    public record MissingItem(long Id, string Name, string Unit, string Path, List<string> Lack);
}

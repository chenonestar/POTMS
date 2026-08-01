using System.Text.Json;
using Dapper;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Logs;

public class IndexModel(Db db, Config cfg, Flash flash) : AppPageModel(flash)
{
    public PageResult<OperationLog> Items { get; private set; } = new();
    public PaginationModel Pager { get; private set; } = new();
    public List<string> Years { get; private set; } = [];
    public string YearFilter { get; set; } = "";
    public string ActionFilter { get; set; } = "";
    public string TargetFilter { get; set; } = "";
    public string DateFrom { get; set; } = "";
    public string DateTo { get; set; } = "";
    /// <summary>日志 id → 变更字段列表（由 snapshot 前后对比得出）。</summary>
    public Dictionary<long, List<Change>> Changes { get; private set; } = [];

    public static readonly Dictionary<string, string> ActionLabels = new()
    {
        ["create"] = "新建", ["update"] = "修改", ["delete"] = "删除", ["void"] = "作废",
        ["cancel"] = "取消行程", ["restore"] = "恢复行程", ["lock"] = "登录锁定",
        ["login_fail"] = "登录失败", ["export"] = "导出", ["import"] = "导入", ["backup"] = "备份",
    };

    public static readonly Dictionary<string, string> TargetLabels = new()
    {
        ["personnel_info"] = "信息表", ["personnel_filing"] = "备案表", ["certificates"] = "证照表",
        ["travel_details"] = "明细表", ["decontrol_filing"] = "撤控表", ["cert_issuance"] = "领用表",
        ["attachments"] = "附件", ["sys_org"] = "组织架构", ["sys_dict"] = "数据字典",
        ["sys_submit_unit"] = "报送单位", ["auth"] = "认证", ["database"] = "数据库", ["batch"] = "批量导入",
    };

    public void OnGet(int page = 1)
    {
        YearFilter = Request.Query["year"].ToString();
        ActionFilter = Request.Query["action"].ToString();
        TargetFilter = Request.Query["target"].ToString();
        DateFrom = Request.Query["dateFrom"].ToString();
        DateTo = Request.Query["dateTo"].ToString();

        using var cn = db.Open();
        var tz = $"+{cfg.TzOffsetHours} hours";
        Years = cn.Query<string>(
            "SELECT DISTINCT strftime('%Y', datetime(created_at, @tz)) AS y FROM operation_logs " +
            "WHERE y IS NOT NULL ORDER BY y DESC", new { tz }).AsList();

        var f = new Filter();
        f.Eq("action", ActionFilter);
        f.Eq("target_type", TargetFilter);
        if (!string.IsNullOrWhiteSpace(YearFilter))
        {
            f.Params.Add("yr", YearFilter);
            f.Params.Add("tz1", tz);
            f.Raw("strftime('%Y', datetime(created_at, @tz1)) = @yr");
        }
        if (!string.IsNullOrWhiteSpace(DateFrom))
        {
            f.Params.Add("df", Validators.ParseDateInput(DateFrom));
            f.Params.Add("tz2", tz);
            f.Raw("strftime('%Y%m%d', datetime(created_at, @tz2)) >= @df");
        }
        if (!string.IsNullOrWhiteSpace(DateTo))
        {
            f.Params.Add("dt", Validators.ParseDateInput(DateTo));
            f.Params.Add("tz3", tz);
            f.Raw("strftime('%Y%m%d', datetime(created_at, @tz3)) <= @dt");
        }

        Items = Helpers.Paginate<OperationLog>(cn,
            "SELECT * FROM operation_logs WHERE 1=1" + f.Where + " ORDER BY created_at DESC, id DESC",
            f.Params, page, Config.PageSizeLogs);
        Pager = PaginationModel.From(Items, Request);

        foreach (var log in Items.Rows)
        {
            var ch = ComputeChanges(log.Snapshot);
            if (ch.Count > 0) Changes[log.Id] = ch;
        }
    }

    /// <summary>对比 snapshot 的 before/after，列出发生变化的字段。</summary>
    public static List<Change> ComputeChanges(string? snapshotJson)
    {
        var result = new List<Change>();
        if (string.IsNullOrWhiteSpace(snapshotJson)) return result;
        try
        {
            using var doc = JsonDocument.Parse(snapshotJson);
            var root = doc.RootElement;
            var hasBefore = root.TryGetProperty("before", out var b) && b.ValueKind == JsonValueKind.Object;
            var hasAfter = root.TryGetProperty("after", out var a) && a.ValueKind == JsonValueKind.Object;
            if (!hasBefore && !hasAfter) return result;

            var keys = new List<string>();
            if (hasBefore) keys.AddRange(b.EnumerateObject().Select(p => p.Name));
            if (hasAfter) foreach (var p in a.EnumerateObject()) if (!keys.Contains(p.Name)) keys.Add(p.Name);

            foreach (var k in keys)
            {
                if (k is "id") continue;
                var bv = hasBefore && b.TryGetProperty(k, out var bx) ? Str(bx) : "";
                var av = hasAfter && a.TryGetProperty(k, out var ax) ? Str(ax) : "";
                if (bv != av) result.Add(new Change(FieldLabel(k), bv, av));
            }
        }
        catch (JsonException) { /* 快照损坏时不展示变更详情，不影响日志本身 */ }
        return result;
    }

    private static string Str(JsonElement e) => e.ValueKind switch
    {
        JsonValueKind.Null or JsonValueKind.Undefined => "",
        JsonValueKind.String => e.GetString() ?? "",
        _ => e.ToString(),
    };

    private static readonly Dictionary<string, string> FieldLabels = new()
    {
        ["unit"] = "单位", ["department"] = "部门", ["name"] = "姓名", ["gender"] = "性别",
        ["birth_date"] = "出生日期", ["id_number"] = "身份证号", ["work_start_date"] = "参加工作日期",
        ["education"] = "学历", ["degree"] = "学位", ["title"] = "职称", ["rank"] = "职级",
        ["political_status"] = "政治面貌", ["party_join_date"] = "入党日期", ["position"] = "职务",
        ["surname"] = "中文姓", ["given_name"] = "中文名", ["residence"] = "户口所在地",
        ["work_unit"] = "工作单位", ["position_or_title"] = "职务/职称", ["supervisor_unit"] = "人事主管单位",
        ["tag"] = "标记", ["informed"] = "已告知本人", ["status"] = "状态", ["remarks"] = "备注",
        ["replaced_by_id"] = "被替代为", ["passport_no"] = "护照号", ["passport_expiry"] = "护照有效期",
        ["passport_submit_date"] = "护照上交日期", ["hm_pass_no"] = "港澳通行证号",
        ["hm_pass_expiry"] = "港澳通有效期", ["hm_pass_submit_date"] = "港澳通上交日期",
        ["tw_pass_no"] = "台湾通行证号", ["tw_pass_expiry"] = "台湾通有效期",
        ["tw_pass_submit_date"] = "台湾通上交日期", ["destination_passport"] = "地点、证照",
        ["category"] = "类别", ["travel_dates"] = "计划出行日期", ["travel_start"] = "出行起始",
        ["travel_end"] = "出行结束", ["approval_date"] = "批准日期", ["need_new_passport"] = "是否做证",
        ["passport_collect_date"] = "证件领用日期", ["passport_return_date"] = "证件归还日期",
        ["actual_return_date"] = "实际回国日期", ["trip_status"] = "行程状态", ["cancel_date"] = "取消日期",
        ["submit_unit_name"] = "报送单位", ["submit_unit_type"] = "报送单位类别",
        ["submit_contact"] = "联系人", ["submit_phone"] = "联系电话", ["batch_no"] = "入库批号",
        ["reason"] = "撤控原因", ["decontrol_date"] = "撤控日期", ["cert_handover_date"] = "证件移交日期",
        ["holder_name"] = "领用人", ["cert_types"] = "证件种类", ["cert_nos"] = "证件号码",
        ["issue_date"] = "领用日期", ["issuer"] = "经办人", ["return_date"] = "归还日期",
        ["return_operator"] = "归还经办人", ["void_reason"] = "作废原因",
        ["code"] = "代码", ["value"] = "显示值", ["sort_order"] = "排序", ["parent_id"] = "上级",
        ["operator"] = "操作人", ["personnel_info_id"] = "关联信息表", ["personnel_filing_id"] = "关联备案",
        ["travel_id"] = "关联出行", ["contact"] = "联系人", ["phone"] = "电话",
    };

    public static string FieldLabel(string key) => FieldLabels.TryGetValue(key, out var v) ? v : key;

    public record Change(string Field, string Before, string After);
}

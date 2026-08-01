using System.Data;
using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Export;

/// <summary>Excel 导出 —— 六类业务表 + 操作日志年度归档。
/// 各表复用列表页的 Filter 构造器，保证「按当前筛选导出」与页面所见一致。</summary>
public class ExportsModel(Db db, Config cfg, Flash flash) : AppPageModel(flash)
{
    private IActionResult Send(byte[] bytes, string baseName, string targetType, string scope)
    {
        using (var cn = db.Open())
            Log(cn, "export", targetType, detail: $"{baseName}（{scope}）");
        var name = $"{baseName}_{DateTime.UtcNow.AddHours(cfg.TzOffsetHours):yyyyMMddHHmmss}.xlsx";
        return File(bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", name);
    }

    private static string?[] Row(params string?[] cells) => cells;

    private List<long> Ids() => Filter.ParseIds(Request.Query["ids"]);

    // ---- 1. 备案人员信息登记表 ----
    public IActionResult OnGetInfo()
    {
        var ids = Ids();
        var f = Personnel.InfoListModel.BuildFilters(Request.Query, ids.Count > 0 ? ids : null);
        using var cn = db.Open();
        string DV(string c, string? v) => Helpers.GetDictValue(cn, c, v);
        var rows = cn.Query<PersonnelInfo>(
            "SELECT pi.* FROM personnel_info pi WHERE 1=1" + f.Where + " ORDER BY pi.created_at DESC",
            f.Params).Select(r => Row(r.Unit, r.Department, r.Name, r.Gender, r.BirthDate, r.IdNumber,
                r.WorkStartDate, DV("education", r.Education), DV("degree", r.Degree),
                DV("title", r.Title), DV("rank", r.Rank), r.PoliticalStatus, r.PartyJoinDate, r.Position)).ToList();

        using var w = new ExcelWriter();
        w.AddSheet("信息登记表", "备案人员信息登记表",
            ["单位", "部门", "姓名", "性别", "出生日期", "身份证号", "参加工作日期",
             "学历", "学位", "职称", "职级", "政治面貌", "入党日期", "职务"],
            rows, notes:
            ["1. 出生日期格式为 YYYYMMDD，须与身份证号一致。",
             "2. 学历 / 学位 / 职级为必填项。",
             "3. 党员及预备党员须填写入党日期。"]);
        return Send(w.ToArray(), "备案人员信息登记表", "personnel_info",
            Filter.ScopeNote(f.Where, ids));
    }

    // ---- 2. 登记备案表 ----
    public IActionResult OnGetFiling()
    {
        var ids = Ids();
        var f = Personnel.IndexModel.BuildFilters(Request.Query, ids.Count > 0 ? ids : null);
        using var cn = db.Open();
        var rows = cn.Query<PersonnelFiling>(
            "SELECT pf.* FROM personnel_filing pf WHERE 1=1" + f.Where + " ORDER BY pf.created_at DESC",
            f.Params).Select(r => Row(r.Surname, r.GivenName, r.Gender, r.BirthDate, r.IdNumber,
                r.Residence, r.PoliticalStatus, r.WorkUnit, r.PositionOrTitle, r.SupervisorUnit,
                r.Tag, r.Informed, r.Status == "active" ? "在案" : "已撤控", r.Remarks)).ToList();

        using var w = new ExcelWriter();
        w.AddSheet("登记备案表", "因私事出国（境）人员登记备案表",
            ["中文姓", "中文名", "性别", "出生日期", "身份证号", "户口所在地", "政治面貌",
             "工作单位", "职务（级）或职称", "人事主管单位", "标记", "已告知本人", "状态", "备注"],
            rows, notes:
            ["1. 复姓须正确拆分至「中文姓」「中文名」两列。",
             "2. 户口所在地填至区级，省份不加「省」字。",
             "3. 标记：新增 / 变更 / 更新（更新为撤控后重报）。"]);
        return Send(w.ToArray(), "登记备案表", "personnel_filing", Filter.ScopeNote(f.Where, ids));
    }

    // ---- 3. 证照登记表 ----
    public IActionResult OnGetCertificate()
    {
        var ids = Ids();
        var f = Certificate.IndexModel.BuildFilters(Request.Query, ids.Count > 0 ? ids : null);
        using var cn = db.Open();
        var rows = cn.Query<POTMS.Data.Certificate>(
            "SELECT * FROM certificates WHERE 1=1" + f.Where + " ORDER BY updated_at DESC",
            f.Params).Select(r => Row(r.Unit, r.Department, r.Name,
                r.PassportNo, r.PassportExpiry, r.PassportSubmitDate,
                r.HmPassNo, r.HmPassExpiry, r.HmPassSubmitDate,
                r.TwPassNo, r.TwPassExpiry, r.TwPassSubmitDate)).ToList();

        using var w = new ExcelWriter();
        w.AddSheet("证照登记表", "因私出国（境）备案人员证照登记表",
            ["单位", "部门", "姓名", "普通护照", "护照有效期", "护照上交日期",
             "往来港澳通行证", "港澳通有效期", "港澳通上交日期",
             "大陆居民往来台湾通行证", "台湾通有效期", "台湾通上交日期"],
            rows, notes: ["1. 填写证件号时，有效日期与上交日期均为必填。",
                          "2. 有效期距今 30 天内的证照在系统中标红预警。"]);
        return Send(w.ToArray(), "证照登记表", "certificates", Filter.ScopeNote(f.Where, ids));
    }

    // ---- 4. 出国明细表 ----
    public IActionResult OnGetTravel()
    {
        var ids = Ids();
        var f = Travel.IndexModel.BuildFilters(Request.Query, db, cfg, ids.Count > 0 ? ids : null);
        using var cn = db.Open();
        string DV(string? v) => Helpers.GetDictValue(cn, "travel_category", v);
        var rows = cn.Query<TravelDetail>(
            "SELECT * FROM travel_details WHERE 1=1" + f.Where + " ORDER BY created_at DESC",
            f.Params).Select(r => Row(r.Unit, r.Department, r.Name, r.Position, r.Title, r.IdNumber,
                r.DestinationPassport, DV(r.Category), r.TravelDates, r.ApprovalDate, r.NeedNewPassport,
                r.PassportNo, r.PassportCollectDate, r.PassportReturnDate, r.ActualReturnDate,
                r.TripStatus == "cancelled" ? "已取消" : "正常", r.CancelDate)).ToList();

        using var w = new ExcelWriter();
        w.AddSheet("出国明细表", "因私出国（境）人员明细表",
            ["单位", "部门", "姓名", "职务", "职称", "身份证号", "地点、证照", "类别",
             "计划出行日期", "批准日期", "是否做证", "证件号码", "证件领用日期", "证件归还日期",
             "实际回国日期", "行程状态", "取消日期"],
            rows, notes:
            ["1. 计划出行日期格式 YYYY/MM/DD-YYYY/MM/DD。",
             "2. 回国后须于 10 个工作日内交回证件；行程取消的于取消日起 5 个工作日内交回。",
             "3. 证件领用 / 归还日期由「证件领用」模块登记（须手写签名），此处为派生展示。"]);
        return Send(w.ToArray(), "出国明细表", "travel_details", Filter.ScopeNote(f.Where, ids));
    }

    // ---- 5. 撤控备案表 ----
    public IActionResult OnGetDecontrol()
    {
        var ids = Ids();
        var f = Decontrol.IndexModel.BuildFilters(Request.Query, ids.Count > 0 ? ids : null);
        using var cn = db.Open();
        string DV(string? v) => Helpers.GetDictValue(cn, "submit_unit_type", v);
        var rows = cn.Query<DecontrolFiling>(
            "SELECT * FROM decontrol_filing WHERE 1=1" + f.Where + " ORDER BY created_at DESC",
            f.Params).Select(r => Row(r.Surname, r.GivenName, r.Gender, r.BirthDate, r.IdNumber,
                r.Residence, r.PoliticalStatus, r.WorkUnit, r.SupervisorUnit, r.SubmitUnitName,
                DV(r.SubmitUnitType), r.SubmitContact, r.SubmitPhone, r.BatchNo,
                r.DecontrolDate, r.CertHandoverDate, r.Reason)).ToList();

        using var w = new ExcelWriter();
        w.AddSheet("撤控备案表", "因私事出国（境）人员撤控备案表",
            ["中文姓", "中文名", "性别", "出生日期", "身份证号", "户口所在地", "政治面貌",
             "工作单位", "人事主管单位", "报送单位名称", "报送单位类别", "报送单位联系人",
             "联系电话", "入库批号", "撤控日期", "证件移交日期", "撤控原因"],
            rows, notes:
            ["1. 出生日期格式为 YYYYMMDD，生日需与身份证号对应。",
             "2. 户口所在地填至区级，省份不加「省」字。",
             "3. 报送单位类别：党政机关 / 金融系统 / 教科文卫系统 / 国有大中型企业单位 / 其他单位。"]);
        return Send(w.ToArray(), "撤控备案表", "decontrol_filing", Filter.ScopeNote(f.Where, ids));
    }

    // ---- 6. 证件领用登记表（签名嵌图）----
    public IActionResult OnGetIssuance()
    {
        var ids = Ids();
        var f = Issuance.IndexModel.BuildFilters(Request.Query, ids.Count > 0 ? ids : null);
        using var cn = db.Open();
        var data = cn.Query<CertIssuance>(
            Issuance.IndexModel.BaseSelect + f.Where + " ORDER BY i.issue_date DESC, i.id DESC",
            f.Params).AsList();

        var statusLabel = new Dictionary<string, string>
            { ["issued"] = "已领用", ["returned"] = "已归还", ["voided"] = "已作废" };
        var rows = data.Select(r => Row(r.WorkUnit, r.HolderName, r.IdNumber,
            IssuanceOps.TypesLabel(cn, r.CertTypes), r.CertNos, r.IssueDate, r.Issuer,
            "",                                   // 第8列：领用签名（图片）
            r.ReturnDate, r.ReturnOperator,
            "",                                   // 第11列：归还签名（图片）
            statusLabel.GetValueOrDefault(r.Status ?? "", r.Status ?? ""), r.Remarks)).ToList();

        var sigs = new Dictionary<int, List<byte[]?>>
        {
            [8] = data.Select(r => r.SignImage).ToList(),
            [11] = data.Select(r => r.ReturnSignImage).ToList(),
        };

        using var w = new ExcelWriter();
        w.AddSheet("证件领用登记表", "因私出国（境）证件领用登记表",
            ["单位", "领用人", "身份证号", "证件种类", "证件号码", "领用日期", "经办人(发放)",
             "领用签名", "归还日期", "经办人(接收)", "归还签名", "状态", "备注"],
            rows, sigs, notes:
            ["1. 签名为领用 / 归还时现场手写采集，保存后不可修改；登记有误须作废后重新登记。",
             "2. 证件号码为领用当时的快照，后续修改证照信息不影响本次领用凭证。",
             "3. 状态：已领用（未归还）/ 已归还 / 已作废。"]);
        return Send(w.ToArray(), "证件领用登记表", "cert_issuance", Filter.ScopeNote(f.Where, ids));
    }

    // ---- 7. 操作日志年度归档 ----
    public IActionResult OnGetLogs(string? year)
    {
        using var cn = db.Open();
        var tz = $"+{cfg.TzOffsetHours} hours";
        year = string.IsNullOrWhiteSpace(year)
            ? DateTime.UtcNow.AddHours(cfg.TzOffsetHours).ToString("yyyy") : year.Trim();

        var rows = cn.Query<OperationLog>(
            "SELECT * FROM operation_logs WHERE strftime('%Y', datetime(created_at, @tz)) = @y " +
            "ORDER BY created_at", new { tz, y = year })
            .Select(r => Row(Helpers.ToLocalTime(r.CreatedAt, cfg), r.Operator,
                Logs.IndexModel.ActionLabels.GetValueOrDefault(r.Action ?? "", r.Action ?? ""),
                Logs.IndexModel.TargetLabels.GetValueOrDefault(r.TargetType ?? "", r.TargetType ?? ""),
                r.TargetId?.ToString(), r.Detail, r.IpAddress, r.Snapshot)).ToList();

        using var w = new ExcelWriter();
        w.AddSheet($"{year}年操作日志", $"操作日志年度归档（{year} 年）",
            ["时间（本地）", "操作人", "动作", "对象类型", "对象ID", "详情", "IP", "变更快照(JSON)"],
            rows, notes: [$"1. 本表为 {year} 年全部操作日志，时间已按本地时区换算。",
                          "2. 变更快照为 JSON 原文，记录变更前后的字段值。"]);
        return Send(w.ToArray(), $"操作日志_{year}", "operation_logs", $"{year}年");
    }
}

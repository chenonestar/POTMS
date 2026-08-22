using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Print;

/// <summary>在线打印：六类表单单张 + 批量。</summary>
public class ViewPageModel(Db db, Flash flash) : AppPageModel(flash)
{
    public string Mode { get; private set; } = "";
    public string Title { get; private set; } = "";
    /// <summary>每份打印件的数据（批量打印时多份，分页符隔开）。</summary>
    public List<Dictionary<string, string?>> Docs { get; private set; } = [];
    /// <summary>领用打印专用：文档序号 → (领用签名id, 归还签名id)。</summary>
    public List<(long Id, bool HasSign, bool HasReturnSign)> Signatures { get; private set; } = [];

    private static readonly Dictionary<string, string> Titles = new()
    {
        ["info"] = "备案人员信息登记表",
        ["filing"] = "因私事出国（境）人员登记备案表",
        ["certificate"] = "因私出国（境）备案人员证照登记表",
        ["travel"] = "因私出国（境）人员明细表",
        ["decontrol"] = "因私事出国（境）人员撤控备案表",
        ["issuance"] = "因私出国（境）证件领用登记表",
    };

    public IActionResult OnGet(string type, long id)
    {
        if (!Titles.ContainsKey(type)) { Flash.Danger("不支持的打印类型。"); return Redirect("/"); }
        Mode = type; Title = Titles[type];
        using var cn = db.Open();
        var doc = Load(cn, type, id);
        if (doc is null) { Flash.Danger("记录不存在。"); return Redirect("/"); }
        Docs.Add(doc);
        return Page();
    }

    public IActionResult OnGetBatch(string type, string? ids)
    {
        if (!Titles.ContainsKey(type)) { Flash.Danger("不支持的打印类型。"); return Redirect("/"); }
        Mode = type; Title = Titles[type];
        var idList = Filter.ParseIds(ids);
        if (idList.Count == 0) { Flash.Warning("请选择要打印的记录。"); return Redirect("/"); }

        using var cn = db.Open();
        foreach (var i in idList)
        {
            var d = Load(cn, type, i);
            if (d is not null) Docs.Add(d);
        }
        if (Docs.Count == 0) { Flash.Warning("未选择有效记录。"); return Redirect("/"); }
        return Page();
    }

    private Dictionary<string, string?>? Load(System.Data.IDbConnection cn, string type, long id)
    {
        string DV(string cat, string? code) => Helpers.GetDictValue(cn, cat, code);

        switch (type)
        {
            case "info":
            {
                var r = cn.QueryFirstOrDefault<PersonnelInfo>("SELECT * FROM personnel_info WHERE id=@id", new { id });
                if (r is null) return null;
                return new()
                {
                    ["单位"] = r.Unit, ["部门"] = r.Department, ["姓名"] = r.Name, ["性别"] = r.Gender,
                    ["出生日期"] = r.BirthDate, ["身份证号"] = r.IdNumber, ["参加工作日期"] = r.WorkStartDate,
                    ["学历"] = DV("education", r.Education), ["学位"] = DV("degree", r.Degree),
                    ["职称"] = DV("title", r.Title), ["职级"] = DV("rank", r.Rank),
                    ["政治面貌"] = r.PoliticalStatus, ["入党日期"] = r.PartyJoinDate, ["职务"] = r.Position,
                };
            }
            case "filing":
            {
                var r = cn.QueryFirstOrDefault<PersonnelFiling>("SELECT * FROM personnel_filing WHERE id=@id", new { id });
                if (r is null) return null;
                var d = new Dictionary<string, string?>
                {
                    ["中文姓"] = r.Surname, ["中文名"] = r.GivenName, ["性别"] = r.Gender,
                    ["出生日期"] = r.BirthDate, ["身份证号"] = r.IdNumber, ["户口所在地"] = r.Residence,
                    ["政治面貌"] = r.PoliticalStatus, ["工作单位"] = r.WorkUnit,
                    ["职务（级）或职称"] = r.PositionOrTitle, ["人事主管单位"] = r.SupervisorUnit,
                    ["标记"] = r.Tag, ["已告知本人"] = r.Informed, ["备注"] = r.Remarks,
                };
                // 关联信息登记表：字典字段须转中文，不能打出裸代码
                if (r.PersonnelInfoId is not null)
                {
                    var i = cn.QueryFirstOrDefault<PersonnelInfo>(
                        "SELECT * FROM personnel_info WHERE id=@i", new { i = r.PersonnelInfoId });
                    if (i is not null)
                    {
                        d["＿关联：部门"] = i.Department;
                        d["＿关联：学历"] = DV("education", i.Education);
                        d["＿关联：学位"] = DV("degree", i.Degree);
                        d["＿关联：职称"] = DV("title", i.Title);
                        d["＿关联：职级"] = DV("rank", i.Rank);
                        d["＿关联：参加工作日期"] = i.WorkStartDate;
                        d["＿关联：入党日期"] = i.PartyJoinDate;
                    }
                }
                return d;
            }
            case "certificate":
            {
                var r = cn.QueryFirstOrDefault<POTMS.Data.Certificate>("SELECT * FROM certificates WHERE id=@id", new { id });
                if (r is null) return null;
                return new()
                {
                    ["单位"] = r.Unit, ["部门"] = r.Department, ["姓名"] = r.Name,
                    ["普通护照"] = r.PassportNo, ["护照有效期"] = r.PassportExpiry,
                    ["护照上交日期"] = r.PassportSubmitDate,
                    ["往来港澳通行证"] = r.HmPassNo, ["港澳通有效期"] = r.HmPassExpiry,
                    ["港澳通上交日期"] = r.HmPassSubmitDate,
                    ["大陆居民往来台湾通行证"] = r.TwPassNo, ["台湾通有效期"] = r.TwPassExpiry,
                    ["台湾通上交日期"] = r.TwPassSubmitDate,
                };
            }
            case "travel":
            {
                var r = cn.QueryFirstOrDefault<TravelDetail>("SELECT * FROM travel_details WHERE id=@id", new { id });
                if (r is null) return null;
                return new()
                {
                    ["单位"] = r.Unit, ["部门"] = r.Department, ["姓名"] = r.Name, ["职务"] = r.Position,
                    ["职称"] = r.Title, ["身份证号"] = r.IdNumber, ["地点、证照"] = r.DestinationPassport,
                    ["类别"] = DV("travel_category", r.Category), ["计划出行日期"] = r.TravelDates,
                    ["批准日期"] = r.ApprovalDate, ["是否做证"] = r.NeedNewPassport,
                    ["证件号码"] = r.PassportNo, ["证件领用日期"] = r.PassportCollectDate,
                    ["证件归还日期"] = r.PassportReturnDate, ["实际回国日期"] = r.ActualReturnDate,
                    ["行程状态"] = r.TripStatus == "cancelled" ? "已取消" : "正常",
                    ["取消日期"] = r.CancelDate,
                };
            }
            case "decontrol":
            {
                var r = cn.QueryFirstOrDefault<DecontrolFiling>("SELECT * FROM decontrol_filing WHERE id=@id", new { id });
                if (r is null) return null;
                return new()
                {
                    ["中文姓"] = r.Surname, ["中文名"] = r.GivenName, ["性别"] = r.Gender,
                    ["出生日期"] = r.BirthDate, ["身份证号"] = r.IdNumber, ["户口所在地"] = r.Residence,
                    ["政治面貌"] = r.PoliticalStatus, ["工作单位"] = r.WorkUnit,
                    ["人事主管单位"] = r.SupervisorUnit, ["报送单位名称"] = r.SubmitUnitName,
                    ["报送单位类别"] = DV("submit_unit_type", r.SubmitUnitType),
                    ["报送单位联系人"] = r.SubmitContact, ["联系电话"] = r.SubmitPhone,
                    ["入库批号"] = r.BatchNo, ["撤控日期"] = r.DecontrolDate,
                    ["证件移交日期"] = r.CertHandoverDate, ["撤控原因"] = r.Reason,
                };
            }
            case "issuance":
            {
                var r = cn.QueryFirstOrDefault<CertIssuance>(
                    "SELECT i.*, pf.work_unit AS work_unit FROM cert_issuance i " +
                    "JOIN personnel_filing pf ON i.personnel_filing_id = pf.id WHERE i.id=@id", new { id });
                if (r is null) return null;
                Signatures.Add((r.Id, r.SignImage is { Length: > 0 }, r.ReturnSignImage is { Length: > 0 }));
                var d = new Dictionary<string, string?>
                {
                    ["单位"] = r.WorkUnit, ["领用人"] = r.HolderName, ["身份证号"] = r.IdNumber,
                    ["领用证件种类"] = IssuanceOps.TypesLabel(cn, r.CertTypes), ["证件号码"] = r.CertNos,
                    ["领用日期"] = r.IssueDate, ["经办人（发放）"] = r.Issuer,
                    ["归还日期"] = r.ReturnDate, ["经办人（接收）"] = r.ReturnOperator,
                    ["备注"] = r.Remarks,
                };
                if (r.Status == "voided") d["作废原因"] = r.VoidReason;
                return d;
            }
        }
        return null;
    }
}

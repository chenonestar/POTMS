using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Issuance;

public class FormModel(Db db, Config cfg, Flash flash) : AppPageModel(flash)
{
    public TravelDetail? Travel { get; private set; }
    public Dictionary<string, string?> Data { get; private set; } = new();
    public List<string> SelectedTypes { get; private set; } = [];

    /// <summary>证件种类代码 → certificates 表中对应的号码字段。</summary>
    public static readonly Dictionary<string, string> CertNoField = new()
    {
        ["01"] = "passport_no", ["02"] = "hm_pass_no", ["03"] = "tw_pass_no",
    };

    /// <summary>没带 travelId 时先让经办人挑一条申请，此处即可选申请列表。</summary>
    public List<TravelDetail> PickList { get; private set; } = [];

    public IActionResult OnGet(long? travelId)
    {
        using var cn = db.Open();
        Data["issue_date"] = Helpers.TodayLocal(cfg);
        if (travelId is not null)
        {
            Travel = cn.QueryFirstOrDefault<TravelDetail>(
                "SELECT * FROM travel_details WHERE id=@id", new { id = travelId });
        }
        // 领用必须挂在一条出国申请上。直接进本页（没带 travelId）时，先让经办人挑一条
        // 申请，挑完再进登记表单——而不是给个能填空的表单，让人有机会登记出一条无主的
        // 领用记录。
        if (Travel is null)
        {
            if (travelId is not null) Flash.Warning("指定的出国申请不存在。");
            PickList = IssuanceOps.EligibleTravels(cn).ToList();
            return Page();
        }
        Data["travel_id"] = travelId.ToString();
        Data["personnel_filing_id"] = Travel.PersonnelFilingId.ToString();
        Data["holder_name"] = Travel.Name;
        Data["id_number"] = Travel.IdNumber;
        return Page();
    }

    public IActionResult OnPost()
    {
        using var cn = db.Open();
        Data = Extract();
        SelectedTypes = Request.Form["cert_types"].Where(s => !string.IsNullOrEmpty(s)).Select(s => s!).ToList();
        Data["cert_types"] = string.Join(",", SelectedTypes);

        var errors = Validate(cn, Data);
        var (blob, sigErr) = Signature.Decode(Request.Form["sign_png"], cfg.RequireSignature);
        if (sigErr.Length > 0) errors.Add(sigErr);

        if (errors.Count > 0)
        {
            foreach (var e in errors) Flash.Danger(e);
            if (long.TryParse(Data["travel_id"], out var tid))
                Travel = cn.QueryFirstOrDefault<TravelDetail>("SELECT * FROM travel_details WHERE id=@id", new { id = tid });
            // 挂不上申请时退回选择页，而不是一个空表单
            if (Travel is null) PickList = IssuanceOps.EligibleTravels(cn).ToList();
            return Page();
        }

        cn.Execute(
            "INSERT INTO cert_issuance (travel_id, personnel_filing_id, holder_name, id_number, " +
            "cert_types, cert_nos, issue_date, issuer, sign_image, sign_meta, status, remarks, operator) " +
            "VALUES (@tid, @pfid, @name, @idn, @types, @nos, @date, @issuer, @img, @meta, 'issued', @remarks, @op)",
            new
            {
                tid = string.IsNullOrEmpty(Data["travel_id"]) ? (long?)null : long.Parse(Data["travel_id"]!),
                pfid = long.Parse(Data["personnel_filing_id"]!),
                name = Data["holder_name"], idn = Data["id_number"],
                types = Data["cert_types"], nos = Data["cert_nos"],
                date = Data["issue_date"], issuer = OperatorName,
                img = blob, meta = Signature.CleanMeta(Request.Form["sign_meta"]),
                remarks = Data["remarks"], op = OperatorName,
            });
        var id = cn.ExecuteScalar<long>("SELECT last_insert_rowid()");
        IssuanceOps.SyncTravelDerived(cn, Data["travel_id"]);
        Log(cn, "create", "cert_issuance", id,
            $"证件领用登记：{Data["holder_name"]}，{IssuanceOps.TypesLabel(cn, Data["cert_types"])}",
            after: Helpers.RowSnapshot(cn, "cert_issuance", id));
        Flash.Success("证件领用登记已保存。");
        return Redirect($"/Issuance/View/{id}");
    }

    private Dictionary<string, string?> Extract()
    {
        string G(string k) => (Request.Form[k].ToString() ?? "").Trim();
        return new Dictionary<string, string?>
        {
            ["travel_id"] = G("travel_id"),
            ["personnel_filing_id"] = G("personnel_filing_id"),
            ["holder_name"] = G("holder_name"),
            ["id_number"] = G("id_number"),
            ["cert_nos"] = G("cert_nos"),
            ["issue_date"] = Validators.ParseDateInput(G("issue_date")),
            ["remarks"] = G("remarks"),
            ["cert_types"] = "",
        };
    }

    private static List<string> Validate(System.Data.IDbConnection cn, Dictionary<string, string?> d)
    {
        var errs = Validators.CheckRequired(d,
            // 领用必须挂在一条出国申请上：证件是为某一次已批准的出行借出的，没有申请
            // 就没有借出的理由。无主的领用记录还会掉出逾期告警——告警按出行记录来算，
            // 挂不上申请的记录没人盯。
            ("travel_id", "关联出国申请"),
            ("personnel_filing_id", "领用人（备案人员）"), ("holder_name", "领用人姓名"),
            ("cert_types", "领用证件种类"), ("issue_date", "领用日期"));
        errs.AddRange(Validators.CheckDates(d, ("issue_date", "领用日期")));

        // 证件种类必须是字典内的合法代码。一次申请一本证，所以只能有一个。
        var codes = (d["cert_types"] ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries);
        foreach (var c in codes)
            if (!CertNoField.ContainsKey(c))
                errs.Add($"无效的证件种类代码：{c}。");
        if (codes.Length > 1)
            errs.Add("一次出国申请只能领用一本证件；需要多本请分别提交出国申请。");

        if (!string.IsNullOrEmpty(d["travel_id"]))
        {
            var tv = cn.QueryFirstOrDefault(
                "SELECT personnel_filing_id, trip_status FROM travel_details WHERE id=@t",
                new { t = d["travel_id"] });
            if (tv is null)
            {
                errs.Add("关联的出国申请不存在。");
            }
            else
            {
                if ((string?)tv.trip_status == "cancelled")
                    errs.Add("该出国申请已取消行程，不能办理证件领用。");
                // 领用人必须就是申请人——证是为这条申请借的，不能借给别人
                if (Convert.ToString(tv.personnel_filing_id) != d["personnel_filing_id"])
                    errs.Add("领用人与该出国申请的申请人不一致。");
            }
            // 同一出行下不允许重复的未归还领用记录
            var dup = cn.QueryFirstOrDefault<long?>(
                "SELECT id FROM cert_issuance WHERE travel_id=@t AND status='issued'",
                new { t = d["travel_id"] });
            if (dup is not null)
                errs.Add($"该出行记录已有未归还的领用记录（#{dup}），请先办理归还或作废。");
        }
        return errs;
    }
}

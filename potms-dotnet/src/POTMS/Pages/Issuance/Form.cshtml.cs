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

    public IActionResult OnGet(long? travelId)
    {
        using var cn = db.Open();
        Data["issue_date"] = Helpers.TodayLocal(cfg);
        if (travelId is not null)
        {
            Travel = cn.QueryFirstOrDefault<TravelDetail>(
                "SELECT * FROM travel_details WHERE id=@id", new { id = travelId });
            if (Travel is not null)
            {
                Data["travel_id"] = travelId.ToString();
                Data["personnel_filing_id"] = Travel.PersonnelFilingId.ToString();
                Data["holder_name"] = Travel.Name;
                Data["id_number"] = Travel.IdNumber;
            }
        }
        return Page();
    }

    public IActionResult OnPost()
    {
        using var cn = db.Open();
        Data = Extract();
        SelectedTypes = Request.Form["cert_types"].Where(s => !string.IsNullOrEmpty(s)).Select(s => s!).ToList();
        Data["cert_types"] = string.Join(",", SelectedTypes);

        var errors = Validate(cn, Data);
        var (blob, sigErr) = Signature.Decode(Request.Form["sign_png"]);
        if (sigErr.Length > 0) errors.Add(sigErr);

        if (errors.Count > 0)
        {
            foreach (var e in errors) Flash.Danger(e);
            if (long.TryParse(Data["travel_id"], out var tid))
                Travel = cn.QueryFirstOrDefault<TravelDetail>("SELECT * FROM travel_details WHERE id=@id", new { id = tid });
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
        IssuanceOps.SyncTravelDates(cn, Data["travel_id"]);
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
            ("personnel_filing_id", "领用人（备案人员）"), ("holder_name", "领用人姓名"),
            ("cert_types", "领用证件种类"), ("issue_date", "领用日期"));
        errs.AddRange(Validators.CheckDates(d, ("issue_date", "领用日期")));

        foreach (var c in (d["cert_types"] ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries))
            if (!CertNoField.ContainsKey(c))
                errs.Add($"无效的证件种类代码：{c}。");

        // 同一出行下不允许重复的未归还领用记录
        if (!string.IsNullOrEmpty(d["travel_id"]))
        {
            var dup = cn.QueryFirstOrDefault<long?>(
                "SELECT id FROM cert_issuance WHERE travel_id=@t AND status='issued'",
                new { t = d["travel_id"] });
            if (dup is not null)
                errs.Add($"该出行记录已有未归还的领用记录（#{dup}），请先办理归还或作废。");
        }
        return errs;
    }
}

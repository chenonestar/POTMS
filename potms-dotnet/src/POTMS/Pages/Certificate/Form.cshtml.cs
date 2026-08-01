using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Certificate;

public class FormModel(Db db, Flash flash) : AppPageModel(flash)
{
    public Dictionary<string, string?> Data { get; private set; } = new();
    public bool Editing { get; private set; }
    public long? CertId { get; private set; }

    /// <summary>三类证件：(号码字段, 有效期字段, 上交日期字段, 中文名)</summary>
    public static readonly (string No, string Exp, string Sub, string Label)[] CertGroups =
    {
        ("passport_no", "passport_expiry", "passport_submit_date", "护照"),
        ("hm_pass_no", "hm_pass_expiry", "hm_pass_submit_date", "港澳通行证"),
        ("tw_pass_no", "tw_pass_expiry", "tw_pass_submit_date", "台湾通行证"),
    };

    public IActionResult OnGet(long? id, long? filingId)
    {
        CertId = id; Editing = id.HasValue;
        using var cn = db.Open();
        if (id is not null)
        {
            var row = cn.QueryFirstOrDefault("SELECT * FROM certificates WHERE id=@id", new { id });
            if (row is null) { Flash.Danger("记录不存在。"); return Redirect("/Certificate"); }
            foreach (var kv in (IDictionary<string, object?>)row) Data[kv.Key] = kv.Value?.ToString();
            return Page();
        }
        // 从人员列表跳转：预填人员信息
        if (filingId is not null)
        {
            var f = cn.QueryFirstOrDefault<PersonnelFiling>(
                "SELECT * FROM personnel_filing WHERE id=@id", new { id = filingId });
            if (f is not null)
            {
                Data["personnel_filing_id"] = filingId.ToString();
                Data["unit"] = f.WorkUnit;
                Data["name"] = f.Name;
            }
        }
        return Page();
    }

    public IActionResult OnPost(long? id)
    {
        CertId = id; Editing = id.HasValue;
        Data = Extract();
        var errors = Validate(Data);
        if (errors.Count > 0) { foreach (var e in errors) Flash.Danger(e); return Page(); }

        using var cn = db.Open();
        var p = new DynamicParameters();
        foreach (var k in new[] { "personnel_filing_id", "unit", "department", "name",
                                  "passport_no", "passport_expiry", "passport_submit_date",
                                  "hm_pass_no", "hm_pass_expiry", "hm_pass_submit_date",
                                  "tw_pass_no", "tw_pass_expiry", "tw_pass_submit_date" })
            p.Add(k, Data[k]);

        if (Editing)
        {
            var before = Helpers.RowSnapshot(cn, "certificates", id!.Value);
            p.Add("id", id); p.Add("op", CurrentUser);
            cn.Execute("UPDATE certificates SET personnel_filing_id=@personnel_filing_id, unit=@unit, " +
                       "department=@department, name=@name, passport_no=@passport_no, " +
                       "passport_expiry=@passport_expiry, passport_submit_date=@passport_submit_date, " +
                       "hm_pass_no=@hm_pass_no, hm_pass_expiry=@hm_pass_expiry, hm_pass_submit_date=@hm_pass_submit_date, " +
                       "tw_pass_no=@tw_pass_no, tw_pass_expiry=@tw_pass_expiry, tw_pass_submit_date=@tw_pass_submit_date, " +
                       "operator=@op, updated_at=CURRENT_TIMESTAMP WHERE id=@id", p);
            Log(cn, "update", "certificates", id, before: before,
                after: Helpers.RowSnapshot(cn, "certificates", id.Value));
            Flash.Success("证照信息已更新。");
        }
        else
        {
            p.Add("op", CurrentUser);
            cn.Execute("INSERT INTO certificates (personnel_filing_id, unit, department, name, " +
                       "passport_no, passport_expiry, passport_submit_date, hm_pass_no, hm_pass_expiry, " +
                       "hm_pass_submit_date, tw_pass_no, tw_pass_expiry, tw_pass_submit_date, operator) " +
                       "VALUES (@personnel_filing_id, @unit, @department, @name, @passport_no, " +
                       "@passport_expiry, @passport_submit_date, @hm_pass_no, @hm_pass_expiry, " +
                       "@hm_pass_submit_date, @tw_pass_no, @tw_pass_expiry, @tw_pass_submit_date, @op)", p);
            var newId = cn.ExecuteScalar<long>("SELECT last_insert_rowid()");
            Log(cn, "create", "certificates", newId, after: Helpers.RowSnapshot(cn, "certificates", newId));
            Flash.Success("证照登记已保存。");
        }
        return Redirect("/Certificate");
    }

    private Dictionary<string, string?> Extract()
    {
        string G(string k) => (Request.Form[k].ToString() ?? "").Trim();
        var d = new Dictionary<string, string?>
        {
            ["personnel_filing_id"] = G("personnel_filing_id"),
            ["unit"] = G("unit"), ["department"] = G("department"), ["name"] = G("name"),
        };
        foreach (var (no, exp, sub, _) in CertGroups)
        {
            d[no] = G(no);
            d[exp] = Validators.ParseDateInput(G(exp));
            d[sub] = Validators.ParseDateInput(G(sub));
        }
        return d;
    }

    private static List<string> Validate(Dictionary<string, string?> d)
    {
        var errs = Validators.CheckRequired(d,
            ("personnel_filing_id", "备案人员"), ("unit", "单位"), ("department", "部门"), ("name", "姓名"));
        foreach (var (no, exp, sub, label) in CertGroups)
        {
            errs.AddRange(Validators.CheckDates(d, (exp, $"{label}有效日期"), (sub, $"{label}上交日期")));
            // 填写证件号时，有效日期与上交日期均为必填
            if (string.IsNullOrEmpty(d[no])) continue;
            if (string.IsNullOrEmpty(d[exp])) errs.Add($"填写{label}证件号时，有效日期为必填。");
            if (string.IsNullOrEmpty(d[sub])) errs.Add($"填写{label}证件号时，上交日期为必填。");
        }
        return errs;
    }
}

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

        using var cn = db.Open();
        // 一人一行：三种证件是同一行上的三组列，本来就装得下一个人的全部证件。
        // 需求文档写明「一行为一人」，但此前代码从未拦过，现实里很容易变成「没找到
        // 原记录就又建一条」——于是同一个人两个编辑入口，到期预警报两遍，想改护照
        // 有效期还得先点进去看哪条里有护照。
        if (!Editing && !string.IsNullOrEmpty(Data["personnel_filing_id"]))
        {
            var dup = cn.QueryFirstOrDefault<long?>(
                "SELECT id FROM certificates WHERE personnel_filing_id=@id ORDER BY id LIMIT 1",
                new { id = Data["personnel_filing_id"] });
            if (dup is not null)
                errors.Add($"该备案人员已有证照记录（#{dup}）。三类证件登记在同一条记录上，请直接编辑那一条，不要新建。");
        }
        if (errors.Count > 0) { foreach (var e in errors) Flash.Danger(e); return Page(); }
        var p = new DynamicParameters();
        foreach (var k in new[] { "personnel_filing_id", "unit", "department", "name",
                                  "passport_no", "passport_expiry", "passport_submit_date",
                                  "hm_pass_no", "hm_pass_expiry", "hm_pass_submit_date",
                                  "tw_pass_no", "tw_pass_expiry", "tw_pass_submit_date" })
            p.Add(k, Data[k]);

        if (Editing)
        {
            var before = Helpers.RowSnapshot(cn, "certificates", id!.Value);
            p.Add("id", id); p.Add("op", OperatorName);
            cn.Execute("UPDATE certificates SET personnel_filing_id=@personnel_filing_id, unit=@unit, " +
                       "department=@department, name=@name, passport_no=@passport_no, " +
                       "passport_expiry=@passport_expiry, passport_submit_date=@passport_submit_date, " +
                       "hm_pass_no=@hm_pass_no, hm_pass_expiry=@hm_pass_expiry, hm_pass_submit_date=@hm_pass_submit_date, " +
                       "tw_pass_no=@tw_pass_no, tw_pass_expiry=@tw_pass_expiry, tw_pass_submit_date=@tw_pass_submit_date, " +
                       "operator=@op, updated_at=CURRENT_TIMESTAMP WHERE id=@id", p);
            Log(cn, "update", "certificates", id, before: before,
                after: Helpers.RowSnapshot(cn, "certificates", id.Value));
            Flash.Success("证照信息已更新。");
            // 换发新证时最容易漏的一步：号码换了，有效期或上交日期还留着旧证的。
            // 台账是到期预警与「有没有可用证件」校验的唯一依据，日期不准这两样都会失灵。
            // 号码变化是换发的确切信号，此时提醒一次，成本为零。
            foreach (var label in RenewedLabels(before, Data))
                Flash.Warning($"{label}号码已变更：请确认有效日期与上交日期同步更新为新证的。");
        }
        else
        {
            p.Add("op", OperatorName);
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

    /// <summary>哪几类证件的号码发生了变化（旧号码非空且与新号码不同）。
    ///
    /// <para>只认「换发」：从空到有是首次登记，不提醒；改回空是注销，也不提醒。</para>
    /// </summary>
    private static List<string> RenewedLabels(Dictionary<string, object?>? before, Dictionary<string, string?> after)
    {
        var out_ = new List<string>();
        if (before is null) return out_;
        foreach (var (no, _, _, label) in CertGroups)
        {
            var old = (before.TryGetValue(no, out var v) ? v?.ToString() : "")?.Trim() ?? "";
            var now = (after.TryGetValue(no, out var w) ? w : "")?.Trim() ?? "";
            if (old.Length > 0 && now.Length > 0 && old != now) out_.Add(label);
        }
        return out_;
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

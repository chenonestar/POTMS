using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Decontrol;

public class FormModel(Db db, Config cfg, Flash flash) : AppPageModel(flash)
{
    public PersonnelFiling Filing { get; private set; } = new();
    public Dictionary<string, string?> Data { get; private set; } = new();

    public IActionResult OnGet(long filingId)
    {
        using var cn = db.Open();
        var f = cn.QueryFirstOrDefault<PersonnelFiling>(
            "SELECT * FROM personnel_filing WHERE id=@id", new { id = filingId });
        if (f is null) { Flash.Danger("备案记录不存在。"); return Redirect("/Personnel"); }
        if (f.Status == "decontrolled") { Flash.Warning("该记录已撤控。"); return Redirect("/Personnel"); }
        Filing = f;
        Data["decontrol_date"] = Helpers.TodayLocal(cfg);
        return Page();
    }

    public IActionResult OnPost(long filingId)
    {
        using var cn = db.Open();
        var f = cn.QueryFirstOrDefault<PersonnelFiling>(
            "SELECT * FROM personnel_filing WHERE id=@id", new { id = filingId });
        if (f is null) { Flash.Danger("备案记录不存在。"); return Redirect("/Personnel"); }
        Filing = f;
        Data = Extract();

        var errors = Validators.CheckRequired(Data,
            ("submit_unit_name", "报送单位名称"), ("submit_unit_type", "报送单位类别"),
            ("submit_contact", "报送单位联系人"), ("submit_phone", "联系电话"),
            ("batch_no", "入库批号"), ("reason", "撤控原因"));
        errors.AddRange(Validators.CheckDates(Data,
            ("decontrol_date", "撤控日期"), ("cert_handover_date", "证件移交日期")));
        if (errors.Count > 0) { foreach (var e in errors) Flash.Danger(e); return Page(); }

        cn.Execute(
            "INSERT INTO decontrol_filing (personnel_filing_id, surname, given_name, gender, birth_date, " +
            "id_number, residence, political_status, work_unit, supervisor_unit, submit_unit_name, " +
            "submit_unit_type, submit_contact, submit_phone, batch_no, reason, decontrol_date, " +
            "cert_handover_date, operator) VALUES (@pfid, @sn, @gn, @gender, @birth, @idn, @res, @pol, " +
            "@unit, @sup, @sun, @sut, @sc, @sp, @batch, @reason, @ddate, @hdate, @op)",
            new
            {
                pfid = filingId, sn = f.Surname, gn = f.GivenName, gender = f.Gender, birth = f.BirthDate,
                idn = f.IdNumber, res = f.Residence, pol = f.PoliticalStatus, unit = f.WorkUnit,
                sup = f.SupervisorUnit,
                sun = Data["submit_unit_name"], sut = Data["submit_unit_type"],
                sc = Data["submit_contact"], sp = Data["submit_phone"],
                batch = Data["batch_no"], reason = Data["reason"],
                ddate = Data["decontrol_date"], hdate = Data["cert_handover_date"], op = OperatorName,
            });
        var decId = cn.ExecuteScalar<long>("SELECT last_insert_rowid()");

        cn.Execute("UPDATE personnel_filing SET status='decontrolled', updated_at=CURRENT_TIMESTAMP WHERE id=@id",
            new { id = filingId });

        Log(cn, "create", "decontrol_filing", decId, $"撤控备案：{f.Name}，原因：{Data["reason"]}",
            after: Helpers.RowSnapshot(cn, "decontrol_filing", decId));
        Flash.Success($"{f.Name} 已撤控。如需重报，请新建备案表，系统会自动关联原记录。");
        return Redirect("/Decontrol");
    }

    private Dictionary<string, string?> Extract()
    {
        string G(string k) => (Request.Form[k].ToString() ?? "").Trim();
        return new Dictionary<string, string?>
        {
            ["submit_unit_name"] = G("submit_unit_name"), ["submit_unit_type"] = G("submit_unit_type"),
            ["submit_contact"] = G("submit_contact"), ["submit_phone"] = G("submit_phone"),
            ["batch_no"] = G("batch_no"), ["reason"] = G("reason"),
            ["decontrol_date"] = Validators.ParseDateInput(G("decontrol_date")),
            ["cert_handover_date"] = Validators.ParseDateInput(G("cert_handover_date")),
        };
    }
}

using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Personnel;

public class FilingFormModel(Db db, Flash flash) : AppPageModel(flash)
{
    public Dictionary<string, string?> Data { get; private set; } = new();
    public bool Editing { get; private set; }
    public long? FilingId { get; private set; }
    public long? InfoId { get; private set; }

    public IActionResult OnGet(long? id, long? infoId)
    {
        FilingId = id; Editing = id.HasValue; InfoId = infoId;
        using var cn = db.Open();

        if (id is not null)
        {
            var row = cn.QueryFirstOrDefault("SELECT * FROM personnel_filing WHERE id=@id", new { id });
            if (row is null) { Flash.Danger("记录不存在。"); return Redirect("/Personnel"); }
            var d = (IDictionary<string, object?>)row;
            foreach (var k in d.Keys) Data[k] = d[k]?.ToString();
            return Page();
        }

        Data["tag"] = "新增";
        Data["informed"] = "否";
        // 从信息登记表带入：姓名按复姓规则拆分，其余字段直填
        if (infoId is not null)
        {
            var info = cn.QueryFirstOrDefault<PersonnelInfo>(
                "SELECT * FROM personnel_info WHERE id=@id", new { id = infoId });
            if (info is not null)
            {
                var (sn, gn) = Helpers.DetectSurnameSplit(info.Name ?? "");
                Data["surname"] = sn; Data["given_name"] = gn;
                Data["gender"] = info.Gender;
                Data["birth_date"] = info.BirthDate;
                Data["id_number"] = info.IdNumber;
                Data["political_status"] = info.PoliticalStatus;
                Data["work_unit"] = info.Unit;
                Data["position_or_title"] = info.Position;
            }
        }
        return Page();
    }

    public IActionResult OnPost(long? id, long? infoId)
    {
        FilingId = id; Editing = id.HasValue; InfoId = infoId;
        Data = Extract();
        using var cn = db.Open();
        var errors = Validate(cn, Data, skipDupCheck: Editing);
        if (errors.Count > 0) { foreach (var e in errors) Flash.Danger(e); return Page(); }

        var p = new DynamicParameters(new
        {
            surname = Data["surname"], given_name = Data["given_name"], gender = Data["gender"],
            birth_date = Data["birth_date"], id_number = Data["id_number"], residence = Data["residence"],
            political_status = Data["political_status"], work_unit = Data["work_unit"],
            position_or_title = Data["position_or_title"], supervisor_unit = Data["supervisor_unit"],
            tag = Data["tag"], informed = Data["informed"], remarks = Data["remarks"], op = CurrentUser,
        });

        if (Editing)
        {
            var before = Helpers.RowSnapshot(cn, "personnel_filing", id!.Value);
            p.Add("id", id);
            cn.Execute("UPDATE personnel_filing SET surname=@surname, given_name=@given_name, gender=@gender, " +
                       "birth_date=@birth_date, id_number=@id_number, residence=@residence, " +
                       "political_status=@political_status, work_unit=@work_unit, " +
                       "position_or_title=@position_or_title, supervisor_unit=@supervisor_unit, " +
                       "tag=@tag, informed=@informed, remarks=@remarks, operator=@op, " +
                       "updated_at=CURRENT_TIMESTAMP WHERE id=@id", p);
            Log(cn, "update", "personnel_filing", id, before: before,
                after: Helpers.RowSnapshot(cn, "personnel_filing", id.Value));
            Flash.Success("登记备案表已更新。");
            return Redirect("/Personnel");
        }

        p.Add("infoId", infoId);
        cn.Execute("INSERT INTO personnel_filing (personnel_info_id, surname, given_name, gender, " +
                   "birth_date, id_number, residence, political_status, work_unit, position_or_title, " +
                   "supervisor_unit, tag, informed, remarks, operator) VALUES (@infoId, @surname, @given_name, " +
                   "@gender, @birth_date, @id_number, @residence, @political_status, @work_unit, " +
                   "@position_or_title, @supervisor_unit, @tag, @informed, @remarks, @op)", p);
        var newId = cn.ExecuteScalar<long>("SELECT last_insert_rowid()");

        // 撤控重报关联：若存在同一身份证的已撤控旧记录，建立新旧关联并标记为「更新」
        var prior = cn.QueryFirstOrDefault<long?>(
            "SELECT id FROM personnel_filing WHERE id_number=@n AND status='decontrolled' " +
            "AND replaced_by_id IS NULL AND id != @cur ORDER BY id DESC LIMIT 1",
            new { n = Data["id_number"], cur = newId });
        if (prior is not null)
        {
            cn.Execute("UPDATE personnel_filing SET replaced_by_id=@new WHERE id=@old",
                new { @new = newId, old = prior });
            cn.Execute("UPDATE personnel_filing SET tag='更新' WHERE id=@id", new { id = newId });
            Flash.Info($"已与原撤控记录（#{prior}）建立关联，本记录标记为「更新」。");
        }

        Log(cn, "create", "personnel_filing", newId, after: Helpers.RowSnapshot(cn, "personnel_filing", newId));
        Flash.Success("登记备案表已保存。");
        return Redirect("/Personnel");
    }

    private Dictionary<string, string?> Extract()
    {
        string G(string k) => (Request.Form[k].ToString() ?? "").Trim();
        return new Dictionary<string, string?>
        {
            ["surname"] = G("surname"), ["given_name"] = G("given_name"), ["gender"] = G("gender"),
            ["birth_date"] = Validators.ParseDateInput(G("birth_date")),
            ["id_number"] = G("id_number").ToUpperInvariant(),
            ["residence"] = Helpers.NormalizeResidence(G("residence")),
            ["political_status"] = G("political_status"), ["work_unit"] = G("work_unit"),
            ["position_or_title"] = G("position_or_title"), ["supervisor_unit"] = G("supervisor_unit"),
            ["tag"] = G("tag").Length > 0 ? G("tag") : "新增",
            ["informed"] = G("informed").Length > 0 ? G("informed") : "否",
            ["remarks"] = G("remarks"),
        };
    }

    private static List<string> Validate(System.Data.IDbConnection cn,
                                         Dictionary<string, string?> d, bool skipDupCheck)
    {
        var errs = Validators.CheckRequired(d,
            ("surname", "中文姓"), ("given_name", "中文名"), ("gender", "性别"),
            ("birth_date", "出生日期"), ("id_number", "身份证号"), ("residence", "户口所在地"),
            ("political_status", "政治面貌"), ("work_unit", "工作单位"),
            ("position_or_title", "职务（级）或职称"), ("supervisor_unit", "人事主管单位"),
            ("tag", "标记"), ("informed", "已告知本人"));
        errs.AddRange(Validators.CheckDates(d, ("birth_date", "出生日期")));
        errs.AddRange(Validators.CheckIdentity(d));

        if (!skipDupCheck && !string.IsNullOrEmpty(d["id_number"]))
        {
            var dup = cn.QueryFirstOrDefault<long?>(
                "SELECT id FROM personnel_filing WHERE id_number=@n AND status='active'",
                new { n = d["id_number"] });
            if (dup is not null) errs.Add("该身份证号已存在有效备案记录，请勿重复登记。");
        }
        return errs;
    }
}

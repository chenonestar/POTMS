using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Personnel;

public class InfoFormModel(Db db, Flash flash) : AppPageModel(flash)
{
    public Dictionary<string, string?> Data { get; private set; } = new();
    public bool Editing { get; private set; }
    public long? InfoId { get; private set; }

    private static readonly string[] Fields =
    {
        "unit","department","name","gender","birth_date","id_number","work_start_date",
        "education","degree","title","rank","political_status","party_join_date","position",
    };

    public IActionResult OnGet(long? id)
    {
        InfoId = id; Editing = id.HasValue;
        if (id is null) return Page();
        using var cn = db.Open();
        var row = cn.QueryFirstOrDefault("SELECT * FROM personnel_info WHERE id=@id", new { id });
        if (row is null) { Flash.Danger("记录不存在。"); return Redirect("/Personnel/InfoList"); }
        var d = (IDictionary<string, object?>)row;
        foreach (var f in Fields) Data[f] = d.TryGetValue(f, out var v) ? v?.ToString() : "";
        return Page();
    }

    public IActionResult OnPost(long? id)
    {
        InfoId = id; Editing = id.HasValue;
        Data = Extract();
        var errors = Validate(Data);

        using var cn = db.Open();
        // #5 身份证号防重：新建时若同号已存在信息表，拒绝保存
        if (!Editing && !string.IsNullOrEmpty(Data["id_number"]))
        {
            var dup = cn.QueryFirstOrDefault<long?>(
                "SELECT id FROM personnel_info WHERE id_number=@n", new { n = Data["id_number"] });
            if (dup is not null)
                errors.Add($"身份证号 {Data["id_number"]} 已存在信息登记表（#{dup}），如需修改请直接编辑原记录。");
        }
        if (errors.Count > 0) { foreach (var e in errors) Flash.Danger(e); return Page(); }

        var p = new DynamicParameters();
        foreach (var f in Fields) p.Add(f, Data[f]);

        if (Editing)
        {
            var before = Helpers.RowSnapshot(cn, "personnel_info", id!.Value);
            p.Add("id", id);
            cn.Execute("UPDATE personnel_info SET unit=@unit, department=@department, name=@name, " +
                       "gender=@gender, birth_date=@birth_date, id_number=@id_number, " +
                       "work_start_date=@work_start_date, education=@education, degree=@degree, " +
                       "title=@title, rank=@rank, political_status=@political_status, " +
                       "party_join_date=@party_join_date, position=@position, " +
                       "updated_at=CURRENT_TIMESTAMP WHERE id=@id", p);
            Log(cn, "update", "personnel_info", id, before: before,
                after: Helpers.RowSnapshot(cn, "personnel_info", id.Value));
            Flash.Success("信息登记表已更新。");
        }
        else
        {
            p.Add("op", OperatorName);
            cn.Execute("INSERT INTO personnel_info (unit, department, name, gender, birth_date, id_number, " +
                       "work_start_date, education, degree, title, rank, political_status, party_join_date, " +
                       "position, operator) VALUES (@unit, @department, @name, @gender, @birth_date, @id_number, " +
                       "@work_start_date, @education, @degree, @title, @rank, @political_status, " +
                       "@party_join_date, @position, @op)", p);
            var newId = cn.ExecuteScalar<long>("SELECT last_insert_rowid()");
            Log(cn, "create", "personnel_info", newId, after: Helpers.RowSnapshot(cn, "personnel_info", newId));
            Flash.Success("信息登记表已保存。");
        }
        return Redirect("/Personnel/InfoList");
    }

    private Dictionary<string, string?> Extract()
    {
        string G(string k) => (Request.Form[k].ToString() ?? "").Trim();
        return new Dictionary<string, string?>
        {
            ["unit"] = G("unit"), ["department"] = G("department"), ["name"] = G("name"),
            ["gender"] = G("gender"), ["birth_date"] = Validators.ParseDateInput(G("birth_date")),
            ["id_number"] = G("id_number"),
            ["work_start_date"] = Validators.ParseDateInput(G("work_start_date")),
            ["education"] = G("education"), ["degree"] = G("degree"), ["title"] = G("title"),
            ["rank"] = G("rank"), ["political_status"] = G("political_status"),
            ["party_join_date"] = Validators.ParseDateInput(G("party_join_date")),
            ["position"] = G("position"),
        };
    }

    private static List<string> Validate(Dictionary<string, string?> d)
    {
        var errs = Validators.CheckRequired(d,
            ("unit", "单位"), ("department", "部门"), ("name", "姓名"), ("gender", "性别"),
            ("birth_date", "出生日期"), ("education", "学历"), ("degree", "学位"),
            ("rank", "职级"), ("political_status", "政治面貌"), ("position", "职务"));
        errs.AddRange(Validators.CheckDates(d,
            ("birth_date", "出生日期"), ("work_start_date", "参加工作日期"), ("party_join_date", "入党日期")));
        errs.AddRange(Validators.CheckIdentity(d));
        return errs;
    }
}

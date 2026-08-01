using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Travel;

public class FormModel(Db db, Config cfg, Flash flash) : AppPageModel(flash)
{
    public Dictionary<string, string?> Data { get; private set; } = new();
    public bool Editing { get; private set; }
    public long? TravelId { get; private set; }
    public List<Attachment> ExistingAttachments { get; private set; } = [];

    public IActionResult OnGet(long? id, long? filingId)
    {
        TravelId = id; Editing = id.HasValue;
        using var cn = db.Open();
        if (id is not null)
        {
            var row = cn.QueryFirstOrDefault("SELECT * FROM travel_details WHERE id=@id", new { id });
            if (row is null) { Flash.Danger("记录不存在。"); return Redirect("/Travel"); }
            foreach (var kv in (IDictionary<string, object?>)row) Data[kv.Key] = kv.Value?.ToString();
            ExistingAttachments = cn.Query<Attachment>(
                "SELECT * FROM attachments WHERE travel_id=@id ORDER BY uploaded_at", new { id }).AsList();
            return Page();
        }
        Data["need_new_passport"] = "否";
        if (filingId is not null) Data["personnel_filing_id"] = filingId.ToString();
        return Page();
    }

    public IActionResult OnPost(long? id)
    {
        TravelId = id; Editing = id.HasValue;
        Data = Extract();
        var errors = Validate(Data);
        errors.AddRange(Attachments.MissingErrors(Request.Form.Files, Data["need_new_passport"] ?? "否", Editing));

        using var cn = db.Open();
        if (errors.Count > 0)
        {
            foreach (var e in errors) Flash.Danger(e);
            if (id is not null)
                ExistingAttachments = cn.Query<Attachment>(
                    "SELECT * FROM attachments WHERE travel_id=@id ORDER BY uploaded_at", new { id }).AsList();
            return Page();
        }

        var (ts, te) = Validators.ParseTravelRange(Data["travel_dates"]);
        var canon = Validators.FormatTravelRange(ts, te);
        if (canon.Length > 0) Data["travel_dates"] = canon;

        var p = new DynamicParameters(new
        {
            pfid = long.Parse(Data["personnel_filing_id"]!),
            unit = Data["unit"], department = Data["department"], name = Data["name"],
            position = Data["position"], title = Data["title"], id_number = Data["id_number"],
            dest = Data["destination_passport"], category = Data["category"],
            dates = Data["travel_dates"], ts, te,
            approval = Data["approval_date"], need = Data["need_new_passport"],
            pno = Data["passport_no"], actual = Data["actual_return_date"], op = CurrentUser,
        });

        long travelId;
        if (Editing)
        {
            var before = Helpers.RowSnapshot(cn, "travel_details", id!.Value);
            p.Add("id", id);
            // 证件领用/归还日期为派生字段，由证件领用模块维护，此处不覆盖
            cn.Execute("UPDATE travel_details SET personnel_filing_id=@pfid, unit=@unit, department=@department, " +
                       "name=@name, position=@position, title=@title, id_number=@id_number, " +
                       "destination_passport=@dest, category=@category, travel_dates=@dates, " +
                       "travel_start=@ts, travel_end=@te, approval_date=@approval, need_new_passport=@need, " +
                       "passport_no=@pno, actual_return_date=@actual, operator=@op, " +
                       "updated_at=CURRENT_TIMESTAMP WHERE id=@id", p);
            travelId = id.Value;
            Attachments.Save(cn, cfg, travelId, Request.Form.Files);
            Log(cn, "update", "travel_details", travelId, before: before,
                after: Helpers.RowSnapshot(cn, "travel_details", travelId));
            Flash.Success("出国申请已更新。");
        }
        else
        {
            cn.Execute("INSERT INTO travel_details (personnel_filing_id, unit, department, name, position, " +
                       "title, id_number, destination_passport, category, travel_dates, travel_start, travel_end, " +
                       "approval_date, need_new_passport, passport_no, actual_return_date, operator) " +
                       "VALUES (@pfid, @unit, @department, @name, @position, @title, @id_number, @dest, " +
                       "@category, @dates, @ts, @te, @approval, @need, @pno, @actual, @op)", p);
            travelId = cn.ExecuteScalar<long>("SELECT last_insert_rowid()");
            Attachments.Save(cn, cfg, travelId, Request.Form.Files);
            Log(cn, "create", "travel_details", travelId,
                after: Helpers.RowSnapshot(cn, "travel_details", travelId));
            Flash.Success("出国申请已保存。");
        }
        return Redirect($"/Travel/View/{travelId}");
    }

    private Dictionary<string, string?> Extract()
    {
        string G(string k) => (Request.Form[k].ToString() ?? "").Trim();
        return new Dictionary<string, string?>
        {
            ["personnel_filing_id"] = G("personnel_filing_id"),
            ["unit"] = G("unit"), ["department"] = G("department"), ["name"] = G("name"),
            ["position"] = G("position"), ["title"] = G("title"), ["id_number"] = G("id_number"),
            ["destination_passport"] = G("destination_passport"), ["category"] = G("category"),
            ["travel_dates"] = G("travel_dates"),
            ["approval_date"] = Validators.ParseDateInput(G("approval_date")),
            // 注意：passport_collect_date / passport_return_date 为派生字段，
            // 由证件领用模块唯一写入，此处不从表单读取。
            ["need_new_passport"] = G("need_new_passport").Length > 0 ? G("need_new_passport") : "否",
            ["passport_no"] = G("passport_no"),
            ["actual_return_date"] = Validators.ParseDateInput(G("actual_return_date")),
        };
    }

    private static List<string> Validate(Dictionary<string, string?> d)
    {
        var errs = Validators.CheckRequired(d,
            ("personnel_filing_id", "备案人员"), ("unit", "单位"), ("department", "部门"),
            ("name", "姓名"), ("position", "职务"), ("id_number", "身份证号"),
            ("destination_passport", "地点、证照"), ("category", "类别"),
            ("travel_dates", "计划出行日期"), ("need_new_passport", "是否做证"));
        // 明细表身份证由备案信息自动带入、无性别/出生字段，仅校验号码本身
        errs.AddRange(Validators.CheckIdentity(d, birthField: null, genderField: null));

        if (!string.IsNullOrEmpty(d["travel_dates"]))
        {
            var (ok, msg) = Validators.ValidateTravelRange(d["travel_dates"]);
            if (!ok) errs.Add($"计划出行日期: {msg}");
        }
        errs.AddRange(Validators.CheckDates(d,
            ("approval_date", "批准日期"), ("actual_return_date", "实际回国日期")));
        return errs;
    }
}

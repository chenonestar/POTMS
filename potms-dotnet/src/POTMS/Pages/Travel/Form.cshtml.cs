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

    /// <summary>证件号码是否已由领用记录派生——是则表单上那一栏只读。</summary>
    public bool CertNoDerived { get; private set; }

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
            CertNoDerived = IssuanceOps.TravelHasIssuance(cn, id);
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
        using var cn = db.Open();
        var errors = Validate(cn, Data, Helpers.TodayLocal(cfg));
        errors.AddRange(Attachments.MissingErrors(Request.Form.Files, Data["need_new_passport"] ?? "否", Editing));

        if (errors.Count > 0)
        {
            foreach (var e in errors) Flash.Danger(e);
            if (id is not null)
            {
                ExistingAttachments = cn.Query<Attachment>(
                    "SELECT * FROM attachments WHERE travel_id=@id ORDER BY uploaded_at", new { id }).AsList();
                CertNoDerived = IssuanceOps.TravelHasIssuance(cn, id);
            }
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
            pno = Data["passport_no"], actual = Data["actual_return_date"], op = OperatorName,
        });

        long travelId;
        if (Editing)
        {
            var before = Helpers.RowSnapshot(cn, "travel_details", id!.Value);
            p.Add("id", id);
            // 有领用记录时证件号码由领用记录派生，表单上是只读的，提交上来的值不能覆盖它
            if (IssuanceOps.TravelHasIssuance(cn, id))
            {
                p.Add("pno", cn.QueryFirstOrDefault<string>(
                    "SELECT passport_no FROM travel_details WHERE id=@id", new { id }));
            }
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

    private static List<string> Validate(System.Data.IDbConnection cn, Dictionary<string, string?> d, string today)
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

        // 一本可用的证都没有，却说不做证——这条记录本身就是错的。
        //
        // 「够不够用」判不了：系统不知道这趟要用哪种证（明细表只有「地点、证照」那段
        // 自由文本），有港澳通行证但要去美国这类情形只能靠经办人自己看。但「一本都
        // 没有」是可判的，而且无论去哪都不可能有证用，属于硬错误。
        //
        // 「有证」要算有效期：一本过期护照等于没有。证照登记里填了号码就必须填有效
        // 日期，所以这个判断的数据一定在。
        if (d["need_new_passport"] == "否" && !string.IsNullOrEmpty(d["personnel_filing_id"]))
        {
            // 一个人可能有多条证照记录（历史遗留），任意一条里有在有效期内的证就算数
            var usable = cn.QueryFirstOrDefault<long?>(
                "SELECT 1 FROM certificates WHERE personnel_filing_id=@id AND (" +
                "  (passport_no IS NOT NULL AND passport_no != '' AND passport_expiry >= @t) OR" +
                "  (hm_pass_no  IS NOT NULL AND hm_pass_no  != '' AND hm_pass_expiry  >= @t) OR" +
                "  (tw_pass_no  IS NOT NULL AND tw_pass_no  != '' AND tw_pass_expiry  >= @t)) LIMIT 1",
                new { id = d["personnel_filing_id"], t = today });
            if (usable is null)
                errs.Add("该备案人员名下没有在有效期内的出入境证件，「是否做证」应为「是」。");
        }
        return errs;
    }
}

using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages.Travel;

public class IndexModel(Db db, Config cfg, Flash flash) : AppPageModel(flash)
{
    public PageResult<TravelDetail> Items { get; private set; } = new();
    public string Search { get; set; } = "";
    public string CategoryFilter { get; set; } = "";
    public string NeedPassportFilter { get; set; } = "";
    public string PassportStatus { get; set; } = "";
    public string DateFrom { get; set; } = "";
    public string DateTo { get; set; } = "";
    public HashSet<long> OverdueIds { get; private set; } = [];
    public Dictionary<long, string> Deadlines { get; private set; } = [];

    public static Filter BuildFilters(IQueryCollection q, Db db, Config cfg,
                                      IReadOnlyCollection<long>? ids = null)
    {
        var f = new Filter();
        f.Like("(name LIKE {0} OR id_number LIKE {1} OR unit LIKE {2} OR destination_passport LIKE {3})",
               q["search"], 4);
        f.Eq("category", q["category"]);
        f.Eq("need_new_passport", q["needNewPassport"]);
        f.Cmp("travel_start", ">=", q["dateFrom"]);
        f.Cmp("travel_end", "<=", q["dateTo"]);

        switch (q["passportStatus"].ToString())
        {
            case "not_collected":
                f.Raw("(passport_collect_date IS NULL OR passport_collect_date = '')");
                break;
            case "in_use":
                f.Raw("passport_collect_date IS NOT NULL AND passport_collect_date != '' " +
                      "AND (passport_return_date IS NULL OR passport_return_date = '')");
                break;
            case "overdue":
                var oids = OverdueIdSet(db, cfg);
                // 无逾期记录时给一个不可能命中的条件，避免 IN () 语法错误
                if (oids.Count == 0) f.Raw("1=0"); else f.Ids("id", oids);
                break;
        }
        f.Ids("id", ids);
        return f;
    }

    /// <summary>全量计算「证件逾期未还」的 id 集合。</summary>
    public static List<long> OverdueIdSet(Db db, Config cfg)
    {
        using var cn = db.Open();
        var today = Helpers.TodayLocal(cfg);
        return cn.Query(
            "SELECT id, passport_collect_date, passport_return_date, actual_return_date, " +
            "       travel_end, trip_status, cancel_date FROM travel_details " +
            "WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' " +
            "  AND (passport_return_date IS NULL OR passport_return_date = '')")
            .Where(r => Validators.IsCertOverdue((string?)r.passport_collect_date, (string?)r.passport_return_date,
                (string?)r.trip_status, (string?)r.cancel_date, (string?)r.actual_return_date,
                (string?)r.travel_end, today))
            .Select(r => (long)r.id).ToList();
    }

    public void OnGet()
    {
        Search = Request.Query["search"].ToString();
        CategoryFilter = Request.Query["category"].ToString();
        NeedPassportFilter = Request.Query["needNewPassport"].ToString();
        PassportStatus = Request.Query["passportStatus"].ToString();
        DateFrom = Request.Query["dateFrom"].ToString();
        DateTo = Request.Query["dateTo"].ToString();

        var f = BuildFilters(Request.Query, db, cfg);
        using var cn = db.Open();
        Items = Helpers.ListAll<TravelDetail>(cn,
            "SELECT * FROM travel_details WHERE 1=1" + f.Where + " ORDER BY created_at DESC", f.Params);

        var today = Helpers.TodayLocal(cfg);
        foreach (var r in Items.Rows)
        {
            if (!Validators.IsCertOverdue(r.PassportCollectDate, r.PassportReturnDate, r.TripStatus,
                    r.CancelDate, r.ActualReturnDate, r.TravelEnd, today)) continue;
            OverdueIds.Add(r.Id);
            Deadlines[r.Id] = Validators.CertOverdueDeadline(r.TripStatus, r.CancelDate,
                r.ActualReturnDate, r.TravelEnd);
        }
    }

    /// <summary>删除守卫：已有证件领用记录（含签名凭证）时禁止删除。</summary>
    public IActionResult OnPostDelete(long id)
    {
        using var cn = db.Open();
        var iss = cn.ExecuteScalar<int>("SELECT COUNT(*) FROM cert_issuance WHERE travel_id=@id", new { id });
        if (iss > 0)
        {
            Flash.Danger($"该出行记录已有 {iss} 条证件领用记录，不能删除。如确需删除，请先作废相关领用记录。");
            return RedirectToPage();
        }
        foreach (var p in cn.Query<string>("SELECT file_path FROM attachments WHERE travel_id=@id", new { id }))
        {
            var full = Path.Combine(cfg.UploadFolder, p);
            if (System.IO.File.Exists(full)) System.IO.File.Delete(full);
        }
        var before = Helpers.RowSnapshot(cn, "travel_details", id);
        cn.Execute("DELETE FROM attachments WHERE travel_id=@id", new { id });
        cn.Execute("DELETE FROM travel_details WHERE id=@id", new { id });
        Log(cn, "delete", "travel_details", id, before: before);
        Flash.Info("出国申请记录已删除。");
        return RedirectToPage();
    }

    public IActionResult OnPostCancel(long id)
    {
        using var cn = db.Open();
        var row = cn.QueryFirstOrDefault<TravelDetail>("SELECT * FROM travel_details WHERE id=@id", new { id });
        if (row is null) { Flash.Danger("记录不存在。"); return RedirectToPage(); }
        if (row.TripStatus == "cancelled") { Flash.Info("该行程已是取消状态。"); return RedirectToPage(); }

        var cancelDate = Validators.ParseDateInput(Request.Form["cancel_date"]);
        if (cancelDate.Length == 0) cancelDate = Helpers.TodayLocal(cfg);
        var (ok, msg) = Validators.ValidateDateFormat(cancelDate);
        if (!ok) { Flash.Danger($"取消日期: {msg}"); return RedirectToPage(); }

        var before = Helpers.RowSnapshot(cn, "travel_details", id);
        cn.Execute("UPDATE travel_details SET trip_status='cancelled', cancel_date=@d, " +
                   "updated_at=CURRENT_TIMESTAMP WHERE id=@id", new { d = cancelDate, id });
        Log(cn, "cancel", "travel_details", id, $"行程取消，取消日期 {cancelDate}",
            before, Helpers.RowSnapshot(cn, "travel_details", id));
        Flash.Warning($"行程已取消。已申领证件须于 {cancelDate} 起 5 个工作日内送回保管。");
        return RedirectToPage();
    }

    public IActionResult OnPostRestore(long id)
    {
        using var cn = db.Open();
        var before = Helpers.RowSnapshot(cn, "travel_details", id);
        if (before is null) { Flash.Danger("记录不存在。"); return RedirectToPage(); }
        cn.Execute("UPDATE travel_details SET trip_status='normal', cancel_date=NULL, " +
                   "updated_at=CURRENT_TIMESTAMP WHERE id=@id", new { id });
        Log(cn, "restore", "travel_details", id, "行程恢复为正常",
            before, Helpers.RowSnapshot(cn, "travel_details", id));
        Flash.Success("行程已恢复为正常状态。");
        return RedirectToPage();
    }
}

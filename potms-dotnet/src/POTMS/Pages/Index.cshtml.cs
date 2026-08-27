using Dapper;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages;

public class IndexModel(Db db, Config cfg, Flash flash) : PageModel
{
    public int TotalActive { get; private set; }
    public int TotalDecontrolled { get; private set; }
    public int TotalCertificates { get; private set; }
    public int TotalTravel { get; private set; }
    public int CertInStorage { get; private set; }
    public int CertInUse { get; private set; }
    public int CertOverdue { get; private set; }
    public int IssPending { get; private set; }
    public int IssThisMonth { get; private set; }
    public string BackupDate { get; private set; } = "";
    public List<OverdueItem> Overdue { get; private set; } = [];
    public List<RecentTrip> RecentTravel { get; private set; } = [];

    public void OnGet()
    {
        // 长时间运行时，首页访问也触发每日备份检查（当天已备份则跳过）
        try { Backup.RunDaily(cfg); } catch { /* 备份失败不影响看板 */ }
        BackupDate = Backup.LatestBackup(cfg);

        using var cn = db.Open();
        var today = Helpers.TodayLocal(cfg);

        TotalActive = cn.ExecuteScalar<int>("SELECT COUNT(*) FROM personnel_filing WHERE status = 'active'");
        TotalDecontrolled = cn.ExecuteScalar<int>("SELECT COUNT(*) FROM personnel_filing WHERE status = 'decontrolled'");
        TotalCertificates = cn.ExecuteScalar<int>("SELECT COUNT(*) FROM certificates");
        TotalTravel = cn.ExecuteScalar<int>("SELECT COUNT(*) FROM travel_details");

        // 证件在库 / 在用（在用＝已领未还）
        CertInUse = cn.ExecuteScalar<int>(
            "SELECT COUNT(*) FROM travel_details " +
            "WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' " +
            "  AND (passport_return_date IS NULL OR passport_return_date = '')");
        CertInStorage = Math.Max(0, TotalCertificates - CertInUse);

        // 逾期未还
        var rows = cn.Query(
            "SELECT id, name, unit, passport_collect_date, passport_return_date, actual_return_date, " +
            "       travel_end, trip_status, cancel_date FROM travel_details " +
            "WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' " +
            "  AND (passport_return_date IS NULL OR passport_return_date = '')").ToList();
        foreach (var r in rows)
        {
            if (!Validators.IsCertOverdue((string?)r.passport_collect_date, (string?)r.passport_return_date,
                    (string?)r.trip_status, (string?)r.cancel_date, (string?)r.actual_return_date,
                    (string?)r.travel_end, today))
                continue;
            Overdue.Add(new OverdueItem((long)r.id, (string?)r.name ?? "", (string?)r.unit ?? "",
                Validators.CertOverdueDeadline((string?)r.trip_status, (string?)r.cancel_date,
                    (string?)r.actual_return_date, (string?)r.travel_end)));
        }
        // 路径B（做证）没有领用记录，上面那批取数条件（passport_collect_date 非空）
        // 一条都抓不到。它们按「新证是否已进入证照台账」判，口径见
        // IssuanceOps.RegisteredCertTravelIds 与 Validators.IsNewCertOverdue。
        var registered = IssuanceOps.RegisteredCertTravelIds(cn);
        foreach (var r in cn.Query(
            "SELECT id, name, unit, need_new_passport, actual_return_date, travel_end, " +
            "       trip_status, cancel_date FROM travel_details " +
            "WHERE need_new_passport = '是' " +
            "  AND (passport_collect_date IS NULL OR passport_collect_date = '')"))
        {
            if (!Validators.IsNewCertOverdue((string?)r.need_new_passport, registered.Contains((long)r.id),
                    (string?)r.trip_status, (string?)r.cancel_date, (string?)r.actual_return_date,
                    (string?)r.travel_end, today))
                continue;
            Overdue.Add(new OverdueItem((long)r.id, (string?)r.name ?? "", (string?)r.unit ?? "",
                Validators.CertOverdueDeadline((string?)r.trip_status, (string?)r.cancel_date,
                    (string?)r.actual_return_date, (string?)r.travel_end)));
        }
        Overdue = Overdue.OrderBy(o => o.Deadline, StringComparer.Ordinal).ToList();
        CertOverdue = Overdue.Count;

        // 证件领用
        IssPending = cn.ExecuteScalar<int>("SELECT COUNT(*) FROM cert_issuance WHERE status = 'issued'");
        IssThisMonth = cn.ExecuteScalar<int>(
            "SELECT COUNT(*) FROM cert_issuance WHERE status != 'voided' AND issue_date LIKE @m",
            new { m = today[..6] + "%" });

        RecentTravel = cn.Query<RecentTrip>(
            "SELECT name AS Name, destination_passport AS Destination, travel_dates AS TravelDates " +
            "FROM travel_details " +
            "ORDER BY CASE WHEN travel_start IS NULL OR travel_start = '' THEN 1 ELSE 0 END, " +
            "         travel_start DESC, created_at DESC LIMIT 5").AsList();
    }

    public IActionResult OnPostBackupNow()
    {
        try
        {
            var (date, _, pruned) = Backup.RunDaily(cfg, force: true);
            using var cn = db.Open();
            Helpers.LogAction(cn, User.Identity?.Name ?? "unknown",
                HttpContext.Connection.RemoteIpAddress?.ToString(), "backup", "database",
                detail: $"手动备份 {date}，清理旧备份 {pruned} 个");
            flash.Success($"备份完成（{date}），清理旧备份 {pruned} 个。");
        }
        catch (Exception e)
        {
            flash.Danger($"备份失败：{e.Message}");
        }
        return RedirectToPage();
    }

    public record OverdueItem(long Id, string Name, string Unit, string Deadline);
    public record RecentTrip(string Name, string Destination, string TravelDates);
}

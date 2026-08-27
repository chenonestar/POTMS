package com.potms.web;

import com.potms.Config;
import com.potms.data.Db;
import com.potms.service.Backup;
import com.potms.util.Validators;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;

/** 首页仪表盘 — 对应 Python 版 blueprints/dashboard.py。 */
@Controller
public class DashboardController {

    private static final DateTimeFormatter YMD = DateTimeFormatter.ofPattern("yyyyMMdd");

    private final Db db;
    private final Config cfg;

    public DashboardController(Db db, Config cfg) {
        this.db = db;
        this.cfg = cfg;
    }

    public record Bucket(String label, long count) {}

    public record OverdueItem(String name, String deadline, String tripStatus) {}


    public record RecentTrip(String name, String destination, String travelDates) {}

    @GetMapping("/")
    public String index(HttpServletRequest req, Model model) {
        // 长时间运行时，访问首页也触发每日备份检查（当天已备份则跳过）
        String backupDate = null;
        try {
            Backup.runDaily(cfg);
            backupDate = Backup.latest(cfg).date();
        } catch (RuntimeException ignored) {
            // 备份失败不应让首页打不开
        }

        var jdbc = db.jdbc();
        LocalDate now = LocalDate.ofInstant(java.time.Instant.now(),
                ZoneOffset.ofHours(cfg.tzOffsetHours));
        String today = now.format(YMD);

        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("totalActive", count(
                "SELECT COUNT(*) FROM personnel_filing WHERE status = 'active'"));
        model.addAttribute("totalDecontrolled", count(
                "SELECT COUNT(*) FROM personnel_filing WHERE status = 'decontrolled'"));
        model.addAttribute("totalCertificates", count("SELECT COUNT(*) FROM certificates"));
        model.addAttribute("totalTravel", count("SELECT COUNT(*) FROM travel_details"));

        // 这里刻意没有「按单位 / 按政治面貌 / 按职级」三项分布统计。
        // Python 版的 dashboard.py 确实算了 by_unit / by_political / by_rank，
        // 但 dashboard.html 从头到尾没有用过——那是留在源头的死查询。Java 版当初
        // 照着 controller 抄，把三张卡渲染了出来，成了五版里唯一多这一块的版本。
        // 现与 Python / Go / Rust / .NET 对齐：不查也不显示。

        // 证照状态分类
        model.addAttribute("certInStorage", count(
                "SELECT COUNT(*) FROM travel_details "
                + "WHERE passport_collect_date IS NULL OR passport_collect_date = ''"));

        var inUse = jdbc.queryForList(
                "SELECT id, name, passport_collect_date, passport_return_date, "
                + "actual_return_date, travel_end, trip_status, cancel_date "
                + "FROM travel_details "
                + "WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' "
                + "AND (passport_return_date IS NULL OR passport_return_date = '')");
        List<OverdueItem> overdue = new ArrayList<>();
        for (Map<String, Object> r : inUse) {
            if (Validators.isCertOverdue(r, today)) {
                Object st = r.get("trip_status");
                overdue.add(new OverdueItem(str(r.get("name")),
                        Validators.certOverdueDeadline(r),
                        st == null || str(st).isEmpty() ? "normal" : str(st)));
            }
        }
        // 路径B（做证）没有领用记录，上面那批取数条件（passport_collect_date 非空）
        // 一条都抓不到。它们按「新证是否已进入证照台账」判，口径见
        // IssuanceOps.registeredCertTravelIds 与 Validators.isNewCertOverdue。
        var registered = com.potms.service.IssuanceOps.registeredCertTravelIds(jdbc);
        for (Map<String, Object> r : jdbc.queryForList(
                "SELECT id, name, need_new_passport, actual_return_date, travel_end, "
                + "trip_status, cancel_date FROM travel_details "
                + "WHERE need_new_passport = '是' "
                + "AND (passport_collect_date IS NULL OR passport_collect_date = '')")) {
            long tid = ((Number) r.get("id")).longValue();
            if (Validators.isNewCertOverdue(r, today, registered.contains(tid))) {
                Object st = r.get("trip_status");
                overdue.add(new OverdueItem(str(r.get("name")),
                        Validators.certOverdueDeadline(r),
                        st == null || str(st).isEmpty() ? "normal" : str(st)));
            }
        }
        overdue.sort(Comparator.comparing(OverdueItem::deadline));
        model.addAttribute("certInUse", (long) inUse.size());
        model.addAttribute("certOverdue", (long) overdue.size());
        model.addAttribute("overdue", overdue);

        model.addAttribute("recentTravel", jdbc.query(
                "SELECT name, destination_passport, travel_dates FROM travel_details "
                + "ORDER BY CASE WHEN travel_start IS NULL OR travel_start = '' THEN 1 ELSE 0 END, "
                + "travel_start DESC, created_at DESC LIMIT 5",
                (rs, i) -> new RecentTrip(rs.getString("name"),
                        rs.getString("destination_passport"), rs.getString("travel_dates"))));

        model.addAttribute("issPending", count(
                "SELECT COUNT(*) FROM cert_issuance WHERE status = 'issued'"));
        model.addAttribute("issThisMonth", db.jdbc().queryForObject(
                "SELECT COUNT(*) FROM cert_issuance WHERE status != 'voided' AND issue_date LIKE ?",
                Long.class, today.substring(0, 6) + "%"));
        model.addAttribute("backupDate", backupDate == null ? "" : backupDate);
        return "dashboard";
    }

    @PostMapping("/backup/now")
    public String backupNow(HttpServletRequest req) {
        try {
            var r = Backup.runDaily(cfg, true);
            Helpers.logAction(db.jdbc(), SecurityFilters.currentUser(req),
                    SecurityFilters.clientIp(req), "backup", "database", null,
                    "手动备份 " + r.date() + "，清理旧备份 " + r.pruned() + " 个", null, null);
            Flash.success(req, "数据库已备份（" + r.date() + "）。");
        } catch (RuntimeException e) {
            Flash.danger(req, "备份失败：" + e.getMessage());
        }
        return "redirect:/";
    }

    private long count(String sql) {
        Long n = db.jdbc().queryForObject(sql, Long.class);
        return n == null ? 0 : n;
    }

    private List<Bucket> buckets(String sql) {
        return db.jdbc().query(sql, (rs, i) -> {
            String label = rs.getString("label");
            return new Bucket(label == null || label.isEmpty() ? "（未填）" : label, rs.getLong("cnt"));
        });
    }

    private static String str(Object o) {
        return o == null ? "" : o.toString();
    }
}

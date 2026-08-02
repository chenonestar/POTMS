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

    public record ExpiringItem(String name, String type, String expiry) {}

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
        String warnDate = now.plusDays(Config.CERT_EXPIRY_WARN_DAYS).format(YMD);

        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("totalActive", count(
                "SELECT COUNT(*) FROM personnel_filing WHERE status = 'active'"));
        model.addAttribute("totalDecontrolled", count(
                "SELECT COUNT(*) FROM personnel_filing WHERE status = 'decontrolled'"));
        model.addAttribute("totalCertificates", count("SELECT COUNT(*) FROM certificates"));
        model.addAttribute("totalTravel", count("SELECT COUNT(*) FROM travel_details"));

        model.addAttribute("byUnit", buckets(
                "SELECT work_unit AS label, COUNT(*) AS cnt FROM personnel_filing "
                + "WHERE status = 'active' GROUP BY work_unit ORDER BY cnt DESC LIMIT 8"));
        model.addAttribute("byPolitical", buckets(
                "SELECT political_status AS label, COUNT(*) AS cnt FROM personnel_filing "
                + "WHERE status = 'active' GROUP BY political_status ORDER BY cnt DESC"));
        model.addAttribute("byRank", buckets(
                "SELECT pi.rank AS label, COUNT(*) AS cnt FROM personnel_filing pf "
                + "JOIN personnel_info pi ON pf.personnel_info_id = pi.id "
                + "WHERE pf.status = 'active' GROUP BY pi.rank ORDER BY cnt DESC"));

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
        overdue.sort(Comparator.comparing(OverdueItem::deadline));
        model.addAttribute("certInUse", (long) inUse.size());
        model.addAttribute("certOverdue", (long) overdue.size());
        model.addAttribute("overdue", overdue);

        // 证照到期预警
        List<ExpiringItem> expiring = new ArrayList<>();
        String[][] kinds = {
            {"passport_expiry", "普通护照"},
            {"hm_pass_expiry", "往来港澳通行证"},
            {"tw_pass_expiry", "大陆居民往来台湾通行证"},
        };
        for (var row : jdbc.queryForList(
                "SELECT name, passport_expiry, hm_pass_expiry, tw_pass_expiry FROM certificates")) {
            for (String[] k : kinds) {
                String expiry = str(row.get(k[0]));
                if (!expiry.isEmpty() && today.compareTo(expiry) <= 0
                        && expiry.compareTo(warnDate) <= 0) {
                    expiring.add(new ExpiringItem(str(row.get("name")), k[1], expiry));
                }
            }
        }
        model.addAttribute("expiring", expiring);

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

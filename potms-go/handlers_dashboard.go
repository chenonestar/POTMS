// 首页仪表盘 + 手动备份
package main

import (
	"fmt"
	"net/http"
	"sort"
	"time"
)

func handleBackupNow(w http.ResponseWriter, r *http.Request) {
	res := runDailyBackup(true)
	logAction(r, "backup", "database", nil,
		fmt.Sprintf("手动备份 %s，清理旧备份 %d 个", res.Date, res.Pruned), nil, nil)
	flashMsg(w, r, fmt.Sprintf("数据库已备份（%s）。", res.Date), "success")
	redirect(w, r, "dashboard.index", nil)
}

func handleDashboard(w http.ResponseWriter, r *http.Request) {
	runDailyBackup(false) // 每日备份检查（进程内标记，同日零开销）
	_, backupDate := latestBackup()

	today := nowLocalYMD()
	warnDate := time.Now().AddDate(0, 0, CertWarnDays).Format("20060102")

	totalActive := countQuery("SELECT COUNT(*) FROM personnel_filing WHERE status = 'active'")
	totalDecontrolled := countQuery("SELECT COUNT(*) FROM personnel_filing WHERE status = 'decontrolled'")
	totalCertificates := countQuery("SELECT COUNT(*) FROM certificates")
	totalTravel := countQuery("SELECT COUNT(*) FROM travel_details")

	byUnit, _ := queryMaps("SELECT work_unit AS label, COUNT(*) AS cnt FROM personnel_filing " +
		"WHERE status = 'active' GROUP BY work_unit ORDER BY cnt DESC LIMIT 8")
	byPolitical, _ := queryMaps("SELECT political_status AS label, COUNT(*) AS cnt FROM personnel_filing " +
		"WHERE status = 'active' GROUP BY political_status ORDER BY cnt DESC")
	byRank, _ := queryMaps("SELECT pi.rank AS label, COUNT(*) AS cnt FROM personnel_filing pf " +
		"JOIN personnel_info pi ON pf.personnel_info_id = pi.id " +
		"WHERE pf.status = 'active' GROUP BY pi.rank ORDER BY cnt DESC")

	certInStorage := countQuery("SELECT COUNT(*) FROM travel_details WHERE passport_collect_date IS NULL OR passport_collect_date = ''")
	inUseRows, _ := queryMaps("SELECT id, name, passport_collect_date, passport_return_date, " +
		"actual_return_date, travel_end, trip_status, cancel_date FROM travel_details " +
		"WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' " +
		"AND (passport_return_date IS NULL OR passport_return_date = '')")
	certInUse := len(inUseRows)

	var overdue []Row
	for _, row := range inUseRows {
		if isCertOverdue(row, today) {
			ts := rowStr(row, "trip_status")
			if ts == "" {
				ts = "normal"
			}
			overdue = append(overdue, Row{
				"name": row["name"], "deadline": certOverdueDeadline(row), "trip_status": ts,
			})
		}
	}
	sort.Slice(overdue, func(i, j int) bool {
		return rowStr(overdue[i], "deadline") < rowStr(overdue[j], "deadline")
	})

	certRows, _ := queryMaps("SELECT name, passport_expiry, hm_pass_expiry, tw_pass_expiry FROM certificates")
	var expiring []Row
	for _, row := range certRows {
		for _, kv := range [][2]string{
			{"passport_expiry", "普通护照"},
			{"hm_pass_expiry", "往来港澳通行证"},
			{"tw_pass_expiry", "大陆居民往来台湾通行证"},
		} {
			expiry := rowStr(row, kv[0])
			if expiry != "" && today <= expiry && expiry <= warnDate {
				expiring = append(expiring, Row{"name": row["name"], "type": kv[1], "expiry": expiry})
			}
		}
	}

	recentTravel, _ := queryMaps("SELECT name, destination_passport, travel_dates, created_at " +
		"FROM travel_details " +
		"ORDER BY CASE WHEN travel_start IS NULL OR travel_start = '' THEN 1 ELSE 0 END, " +
		"travel_start DESC, created_at DESC LIMIT 5")

	render(w, r, "dashboard.html", Row{
		"total_active": totalActive, "total_decontrolled": totalDecontrolled,
		"total_certificates": totalCertificates, "total_travel": totalTravel,
		"by_unit": rowsIface(byUnit), "by_political": rowsIface(byPolitical), "by_rank": rowsIface(byRank),
		"cert_in_storage": certInStorage, "cert_in_use": certInUse, "cert_overdue": len(overdue),
		"expiring": rowsIface(expiring), "overdue": rowsIface(overdue),
		"recent_travel": rowsIface(recentTravel), "backup_date": backupDate,
	})
}

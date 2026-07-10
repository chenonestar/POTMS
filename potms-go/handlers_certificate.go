// 证照登记：护照 / 港澳通行证 / 台湾通行证
package main

import (
	"net/http"
	"strings"
	"time"
)

func certificateFilters(q map[string]string, ids []int64) (string, []interface{}) {
	where := ""
	var params []interface{}
	if s := strings.TrimSpace(q["search"]); s != "" {
		where += " AND (name LIKE ? OR unit LIKE ?)"
		like := "%" + s + "%"
		params = append(params, like, like)
	}
	for _, f := range []struct{ key, col string }{
		{"has_passport", "passport_no"}, {"has_hm", "hm_pass_no"}, {"has_tw", "tw_pass_no"},
	} {
		switch strings.TrimSpace(q[f.key]) {
		case "1":
			where += " AND " + f.col + " IS NOT NULL AND " + f.col + " != ''"
		case "0":
			where += " AND (" + f.col + " IS NULL OR " + f.col + " = '')"
		}
	}
	if len(ids) > 0 {
		where += " AND id IN (" + placeholders(len(ids)) + ")"
		for _, id := range ids {
			params = append(params, id)
		}
	}
	return where, params
}

func handleCertificateList(w http.ResponseWriter, r *http.Request) {
	q := queryArgs(r)
	where, params := certificateFilters(q, nil)
	pg := listAll("SELECT * FROM certificates WHERE 1=1"+where+" ORDER BY updated_at DESC", params...)

	today := nowLocalYMD()
	warnDate := time.Now().AddDate(0, 0, CertWarnDays).Format("20060102")

	// expiredMap: id → [id, label, expiry]（供模板 cert_warn 助手使用）
	warnSet := map[string]bool{}       // "id:label"
	expiredMap := map[int64][]string{} // id → {label, expiry}
	var warnIDs []interface{}
	for _, row := range pg.Rows {
		id := toInt64(row["id"])
		for _, kv := range [][2]string{
			{"passport_expiry", "普通护照"},
			{"hm_pass_expiry", "往来港澳通行证"},
			{"tw_pass_expiry", "大陆居民往来台湾通行证"},
		} {
			expiry := rowStr(row, kv[0])
			if expiry != "" && today <= expiry && expiry <= warnDate {
				warnSet[itoa(id)+":"+kv[1]] = true
				if _, seen := expiredMap[id]; !seen {
					expiredMap[id] = []string{kv[1], expiry}
					warnIDs = append(warnIDs, id)
				}
			}
		}
	}

	render(w, r, "certificate/list.html", Row{
		"items": pg.pageMap(), "search": q["search"],
		"has_passport": q["has_passport"], "has_hm": q["has_hm"], "has_tw": q["has_tw"],
		"warn_ids":  warnIDs,
		"cert_warn": func(id int64, label string) bool { return warnSet[itoa(id)+":"+label] },
		"cert_warn_label": func(id int64) string {
			if v, ok := expiredMap[id]; ok {
				return v[0]
			}
			return ""
		},
		"cert_warn_expiry": func(id int64) string {
			if v, ok := expiredMap[id]; ok {
				return v[1]
			}
			return ""
		},
	})
}

func extractCertForm(r *http.Request) map[string]string {
	f := func(k string) string { return strings.TrimSpace(r.PostFormValue(k)) }
	return map[string]string{
		"personnel_filing_id": f("personnel_filing_id"),
		"unit":                f("unit"), "department": f("department"), "name": f("name"),
		"passport_no": f("passport_no"), "passport_expiry": parseDateInput(f("passport_expiry")),
		"passport_submit_date": parseDateInput(f("passport_submit_date")),
		"hm_pass_no":           f("hm_pass_no"), "hm_pass_expiry": parseDateInput(f("hm_pass_expiry")),
		"hm_pass_submit_date": parseDateInput(f("hm_pass_submit_date")),
		"tw_pass_no":          f("tw_pass_no"), "tw_pass_expiry": parseDateInput(f("tw_pass_expiry")),
		"tw_pass_submit_date": parseDateInput(f("tw_pass_submit_date")),
		"operator":            sessionUser(r),
	}
}

func validateCertForm(data map[string]string) []string {
	var errs []string
	errs = append(errs, checkRequired(data, []fieldLabel{
		{"personnel_filing_id", "备案人员"}, {"unit", "单位"},
		{"department", "部门"}, {"name", "姓名"},
	})...)
	errs = append(errs, checkDates(data, []fieldLabel{
		{"passport_expiry", "护照有效日期"}, {"passport_submit_date", "护照上交日期"},
		{"hm_pass_expiry", "港澳通行证有效日期"}, {"hm_pass_submit_date", "港澳通行证上交日期"},
		{"tw_pass_expiry", "台湾通行证有效日期"}, {"tw_pass_submit_date", "台湾通行证上交日期"},
	})...)
	for _, g := range [][4]string{
		{"passport_no", "passport_expiry", "passport_submit_date", "护照"},
		{"hm_pass_no", "hm_pass_expiry", "hm_pass_submit_date", "港澳通行证"},
		{"tw_pass_no", "tw_pass_expiry", "tw_pass_submit_date", "台湾通行证"},
	} {
		if data[g[0]] != "" {
			if data[g[1]] == "" {
				errs = append(errs, "填写"+g[3]+"证件号时，有效日期为必填。")
			}
			if data[g[2]] == "" {
				errs = append(errs, "填写"+g[3]+"证件号时，上交日期为必填。")
			}
		}
	}
	return errs
}

func handleCertificateNew(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		data := extractCertForm(r)
		if errs := validateCertForm(data); len(errs) > 0 {
			for _, e := range errs {
				flashMsg(w, r, e, "danger")
			}
			render(w, r, "certificate/form.html", Row{"data": dataRow(data), "editing": false})
			return
		}
		res, _ := db.Exec("INSERT INTO certificates (personnel_filing_id, unit, department, name, "+
			"passport_no, passport_expiry, passport_submit_date, "+
			"hm_pass_no, hm_pass_expiry, hm_pass_submit_date, "+
			"tw_pass_no, tw_pass_expiry, tw_pass_submit_date, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
			data["personnel_filing_id"], data["unit"], data["department"], data["name"],
			data["passport_no"], data["passport_expiry"], data["passport_submit_date"],
			data["hm_pass_no"], data["hm_pass_expiry"], data["hm_pass_submit_date"],
			data["tw_pass_no"], data["tw_pass_expiry"], data["tw_pass_submit_date"], data["operator"])
		certID := lastInsertID(res)
		logAction(r, "create", "certificate", certID, "", nil, rowSnapshot("certificates", certID))
		flashMsg(w, r, "证照登记已保存。", "success")
		redirect(w, r, "certificate.list", nil)
		return
	}
	prefill := Row{}
	if fid := r.URL.Query().Get("filing_id"); fid != "" {
		filing := queryOne("SELECT id, work_unit, surname||given_name AS name, "+
			"COALESCE((SELECT unit FROM personnel_info WHERE id = personnel_filing.personnel_info_id), work_unit) AS unit_val "+
			"FROM personnel_filing WHERE id = ?", toInt64(fid))
		if filing != nil {
			unit := rowStr(filing, "unit_val")
			if unit == "" {
				unit = rowStr(filing, "work_unit")
			}
			prefill = Row{
				"personnel_filing_id": toInt64(fid), "unit": unit,
				"department": "", "name": filing["name"],
			}
		}
	}
	render(w, r, "certificate/form.html", Row{"data": prefill, "editing": false})
}

func handleCertificateEdit(w http.ResponseWriter, r *http.Request) {
	certID := pathInt(r, "cert_id")
	row := queryOne("SELECT * FROM certificates WHERE id = ?", certID)
	if row == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, "certificate.list", nil)
		return
	}
	if r.Method == http.MethodPost {
		data := extractCertForm(r)
		if errs := validateCertForm(data); len(errs) > 0 {
			for _, e := range errs {
				flashMsg(w, r, e, "danger")
			}
			render(w, r, "certificate/form.html", Row{"data": dataRow(data), "editing": true, "cert_id": certID})
			return
		}
		before := rowSnapshot("certificates", certID)
		db.Exec("UPDATE certificates SET personnel_filing_id=?, unit=?, department=?, name=?, "+
			"passport_no=?, passport_expiry=?, passport_submit_date=?, "+
			"hm_pass_no=?, hm_pass_expiry=?, hm_pass_submit_date=?, "+
			"tw_pass_no=?, tw_pass_expiry=?, tw_pass_submit_date=?, "+
			"operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
			data["personnel_filing_id"], data["unit"], data["department"], data["name"],
			data["passport_no"], data["passport_expiry"], data["passport_submit_date"],
			data["hm_pass_no"], data["hm_pass_expiry"], data["hm_pass_submit_date"],
			data["tw_pass_no"], data["tw_pass_expiry"], data["tw_pass_submit_date"],
			data["operator"], certID)
		logAction(r, "update", "certificate", certID, "", before, rowSnapshot("certificates", certID))
		flashMsg(w, r, "证照信息已更新。", "success")
		redirect(w, r, "certificate.list", nil)
		return
	}
	render(w, r, "certificate/form.html", Row{"data": row, "editing": true, "cert_id": certID})
}

func handleCertificateDelete(w http.ResponseWriter, r *http.Request) {
	certID := pathInt(r, "cert_id")
	before := rowSnapshot("certificates", certID)
	db.Exec("DELETE FROM certificates WHERE id = ?", certID)
	logAction(r, "delete", "certificate", certID, "", before, nil)
	flashMsg(w, r, "证照记录已删除。", "info")
	redirect(w, r, "certificate.list", nil)
}

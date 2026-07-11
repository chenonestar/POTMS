// 撤控备案
package main

import (
	"net/http"
	"strings"
	"time"
)

func decontrolFilters(q map[string]string, ids []int64) (string, []interface{}) {
	where := ""
	var params []interface{}
	if s := strings.TrimSpace(q["search"]); s != "" {
		where += " AND (surname||given_name LIKE ? OR id_number LIKE ? OR reason LIKE ?)"
		like := "%" + s + "%"
		params = append(params, like, like, like)
	}
	if v := strings.TrimSpace(q["submit_unit_type"]); v != "" {
		where += " AND submit_unit_type = ?"
		params = append(params, v)
	}
	if len(ids) > 0 {
		where += " AND id IN (" + placeholders(len(ids)) + ")"
		for _, id := range ids {
			params = append(params, id)
		}
	}
	return where, params
}

func handleDecontrolList(w http.ResponseWriter, r *http.Request) {
	q := queryArgs(r)
	where, params := decontrolFilters(q, nil)
	pg := listAll("SELECT * FROM decontrol_filing WHERE 1=1"+where+" ORDER BY created_at DESC", params...)
	render(w, r, "decontrol/list.html", Row{
		"items": pg.pageMap(), "search": q["search"],
		"unit_type_filter": q["submit_unit_type"],
		"unit_type_opts":   rowsIface(getDictOptions("submit_unit_type")),
	})
}

func extractDecontrolForm(r *http.Request) map[string]string {
	f := func(k string) string { return strings.TrimSpace(r.PostFormValue(k)) }
	decDate := parseDateInput(f("decontrol_date"))
	if decDate == "" {
		decDate = time.Now().Format("20060102")
	}
	return map[string]string{
		"surname": f("surname"), "given_name": f("given_name"), "gender": f("gender"),
		"birth_date":       parseDateInput(f("birth_date")),
		"id_number":        strings.ToUpper(f("id_number")),
		"residence":        normalizeResidence(f("residence")),
		"political_status": f("political_status"), "work_unit": f("work_unit"),
		"supervisor_unit": f("supervisor_unit"), "submit_unit_name": f("submit_unit_name"),
		"submit_unit_type": f("submit_unit_type"), "submit_contact": f("submit_contact"),
		"submit_phone": f("submit_phone"), "batch_no": f("batch_no"), "reason": f("reason"),
		"decontrol_date":     decDate,
		"cert_handover_date": parseDateInput(f("cert_handover_date")),
		"operator":           sessionUser(r),
	}
}

func validateDecontrolForm(data map[string]string) []string {
	var errs []string
	errs = append(errs, checkRequired(data, []fieldLabel{
		{"surname", "中文姓"}, {"given_name", "中文名"}, {"gender", "性别"},
		{"birth_date", "出生日期"}, {"id_number", "身份证号"},
		{"residence", "户口所在地"}, {"political_status", "政治面貌"},
		{"work_unit", "工作单位"}, {"supervisor_unit", "人事主管单位"},
		{"submit_unit_name", "报送单位名称"}, {"submit_unit_type", "报送单位类别"},
		{"submit_contact", "报送单位联系人"}, {"submit_phone", "报送单位联系电话"},
		{"batch_no", "入库批号"}, {"reason", "撤控原因"},
	})...)
	errs = append(errs, checkDates(data, []fieldLabel{
		{"birth_date", "出生日期"}, {"cert_handover_date", "证件移交日期"}, {"decontrol_date", "撤控日期"},
	})...)
	errs = append(errs, checkIdentity(data, "birth_date", "gender")...)
	return errs
}

func handleDecontrolNew(w http.ResponseWriter, r *http.Request) {
	filingID := pathInt(r, "filing_id")
	filing := queryOne("SELECT * FROM personnel_filing WHERE id = ?", filingID)
	if filing == nil {
		flashMsg(w, r, "备案人员不存在。", "danger")
		redirect(w, r, "decontrol.list", nil)
		return
	}
	if rowStr(filing, "status") == "decontrolled" {
		flashMsg(w, r, "该人员已被撤控。", "warning")
		redirect(w, r, "personnel.view", map[string]string{"filing_id": itoa(filingID)})
		return
	}
	if r.Method == http.MethodPost {
		data := extractDecontrolForm(r)
		if errs := validateDecontrolForm(data); len(errs) > 0 {
			for _, e := range errs {
				flashMsg(w, r, e, "danger")
			}
			render(w, r, "decontrol/form.html", Row{"data": dataRow(data), "filing": filing, "filing_id": filingID})
			return
		}
		res, _ := db.Exec("INSERT INTO decontrol_filing (personnel_filing_id, surname, given_name, "+
			"gender, birth_date, id_number, residence, political_status, work_unit, "+
			"supervisor_unit, submit_unit_name, submit_unit_type, submit_contact, "+
			"submit_phone, batch_no, reason, decontrol_date, cert_handover_date, operator) "+
			"VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
			filingID, data["surname"], data["given_name"], data["gender"],
			data["birth_date"], data["id_number"], data["residence"],
			data["political_status"], data["work_unit"], data["supervisor_unit"],
			data["submit_unit_name"], data["submit_unit_type"], data["submit_contact"],
			data["submit_phone"], data["batch_no"], data["reason"],
			data["decontrol_date"], data["cert_handover_date"], data["operator"])
		db.Exec("UPDATE personnel_filing SET status = 'decontrolled', updated_at = CURRENT_TIMESTAMP WHERE id = ?", filingID)
		decID := lastInsertID(res)
		logAction(r, "create", "decontrol_filing", decID, "", nil, rowSnapshot("decontrol_filing", decID))
		flashMsg(w, r, "撤控备案已提交。该人员备案状态已标记为'已撤控'。", "success")
		redirect(w, r, "personnel.list", nil)
		return
	}
	prefill := Row{
		"surname": filing["surname"], "given_name": filing["given_name"],
		"gender": filing["gender"], "birth_date": filing["birth_date"],
		"id_number": filing["id_number"], "residence": filing["residence"],
		"political_status": filing["political_status"], "work_unit": filing["work_unit"],
		"supervisor_unit": filing["supervisor_unit"],
		"decontrol_date":  time.Now().Format("20060102"),
	}
	render(w, r, "decontrol/form.html", Row{"data": prefill, "filing": filing, "filing_id": filingID})
}

func handleDecontrolView(w http.ResponseWriter, r *http.Request) {
	row := queryOne("SELECT * FROM decontrol_filing WHERE id = ?", pathInt(r, "dec_id"))
	if row == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, "decontrol.list", nil)
		return
	}
	render(w, r, "decontrol/view.html", Row{"dec": row})
}

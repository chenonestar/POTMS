// 人员备案：信息登记表 + 登记备案表
package main

import (
	"fmt"
	"net/http"
	"strings"
)

// personnelFilters 构建 WHERE 子句（列表与导出复用）
func personnelFilters(q map[string]string, ids []int64) (string, []interface{}) {
	where := ""
	var params []interface{}
	if s := strings.TrimSpace(q["search"]); s != "" {
		where += " AND (pf.surname||pf.given_name LIKE ? OR pf.id_number LIKE ? OR pf.work_unit LIKE ?)"
		like := "%" + s + "%"
		params = append(params, like, like, like)
	}
	for _, f := range []struct{ key, col string }{
		{"status", "pf.status"}, {"political_status", "pf.political_status"},
		{"rank", "pi.rank"}, {"gender", "pf.gender"}, {"tag", "pf.tag"},
	} {
		if v := strings.TrimSpace(q[f.key]); v != "" {
			where += " AND " + f.col + " = ?"
			params = append(params, v)
		}
	}
	if v := strings.TrimSpace(q["residence"]); v != "" {
		where += " AND pf.residence LIKE ?"
		params = append(params, "%"+v+"%")
	}
	if len(ids) > 0 {
		where += " AND pf.id IN (" + placeholders(len(ids)) + ")"
		for _, id := range ids {
			params = append(params, id)
		}
	}
	return where, params
}

func queryArgs(r *http.Request) map[string]string {
	out := map[string]string{}
	for k, v := range r.URL.Query() {
		if len(v) > 0 {
			out[k] = v[0]
		}
	}
	return out
}

func handlePersonnelList(w http.ResponseWriter, r *http.Request) {
	q := queryArgs(r)
	where, params := personnelFilters(q, nil)
	base := "SELECT pf.id, pf.surname, pf.given_name, pf.gender, pf.birth_date, " +
		"pf.id_number, pf.work_unit, pf.position_or_title, pf.tag, pf.status, " +
		"pf.created_at, pi.id AS info_id " +
		"FROM personnel_filing pf LEFT JOIN personnel_info pi ON pf.personnel_info_id = pi.id " +
		"WHERE 1=1" + where

	sortMap := map[string]string{
		"created_at_desc": "pf.created_at DESC", "created_at_asc": "pf.created_at ASC",
		"name_asc": "pf.surname||pf.given_name ASC", "birth_date_asc": "pf.birth_date ASC",
	}
	sortBy := strings.TrimSpace(q["sort"])
	order, ok := sortMap[sortBy]
	if !ok {
		order = "pf.created_at DESC"
	}
	if sortBy == "" {
		sortBy = "created_at_desc"
	}
	pg := listAll(base+" ORDER BY "+order, params...)

	render(w, r, "personnel/list.html", Row{
		"items": pg.pageMap(), "search": q["search"],
		"status_filter": q["status"], "political_filter": q["political_status"],
		"rank_filter": q["rank"], "gender_filter": q["gender"], "tag_filter": q["tag"],
		"residence_filter": q["residence"], "sort_by": sortBy,
		"statuses":       optList("active", "有效", "decontrolled", "已撤控"),
		"political_opts": rowsIface(getDictOptions("political_status")),
		"rank_opts":      rowsIface(getDictOptions("rank")),
		"tags":           optList("新增", "新增", "更新", "更新"),
		"genders":        optList("男", "男", "女", "女"),
		"sorts": []interface{}{
			Row{"code": "created_at_desc", "value": "录入时间（新→旧）"},
			Row{"code": "created_at_asc", "value": "录入时间（旧→新）"},
			Row{"code": "name_asc", "value": "姓名排序"},
			Row{"code": "birth_date_asc", "value": "出生日期"},
		},
	})
}

func optList(pairs ...string) []interface{} {
	var out []interface{}
	for i := 0; i+1 < len(pairs); i += 2 {
		out = append(out, Row{"code": pairs[i], "value": pairs[i+1]})
	}
	return out
}

// ---------------------------------------------------------------------------
// 信息登记表
// ---------------------------------------------------------------------------
func extractInfoForm(r *http.Request) map[string]string {
	f := func(k string) string { return strings.TrimSpace(r.PostFormValue(k)) }
	return map[string]string{
		"unit": f("unit"), "department": f("department"), "name": f("name"),
		"gender": f("gender"), "birth_date": parseDateInput(f("birth_date")),
		"id_number":       strings.ToUpper(f("id_number")),
		"work_start_date": parseDateInput(f("work_start_date")),
		"education":       f("education"), "degree": f("degree"), "title": f("title"),
		"rank": f("rank"), "political_status": f("political_status"),
		"party_join_date": parseDateInput(f("party_join_date")),
		"position":        f("position"), "operator": sessionUser(r),
	}
}

func validateInfoForm(data map[string]string) []string {
	var errs []string
	errs = append(errs, checkRequired(data, []fieldLabel{
		{"unit", "单位"}, {"department", "部门"}, {"name", "姓名"},
		{"gender", "性别"}, {"birth_date", "出生日期"}, {"id_number", "身份证号"},
		{"work_start_date", "参加工作日期"},
		{"education", "学历"}, {"degree", "学位"}, {"title", "职称"},
		{"rank", "职级"}, {"political_status", "政治面貌"},
		{"position", "职务（岗位名称）"},
	})...)
	errs = append(errs, checkDates(data, []fieldLabel{
		{"birth_date", "出生日期"}, {"work_start_date", "参加工作日期"}, {"party_join_date", "入党日期"},
	})...)
	errs = append(errs, checkIdentity(data, "birth_date", "gender")...)
	if isPartyMember(data["political_status"]) && data["party_join_date"] == "" {
		errs = append(errs, "中共党员/预备党员须填写入党日期。")
	}
	return errs
}

func dataRow(data map[string]string) Row {
	out := Row{}
	for k, v := range data {
		out[k] = v
	}
	return out
}

func handleInfoNew(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		data := extractInfoForm(r)
		errs := validateInfoForm(data)
		// #5 防重复：同一身份证号已存在信息登记表则拦截（避免同号孤儿行；
		// 如需修改请直接编辑原记录）
		if len(errs) == 0 && data["id_number"] != "" {
			if dup := queryOne("SELECT id FROM personnel_info WHERE id_number = ? LIMIT 1", data["id_number"]); dup != nil {
				errs = append(errs, fmt.Sprintf("该身份证号已存在信息登记表（编号 %d），如需修改请直接编辑该记录，请勿重复录入。", toInt64(dup["id"])))
			}
		}
		if len(errs) > 0 {
			for _, e := range errs {
				flashMsg(w, r, e, "danger")
			}
			render(w, r, "personnel/info_form.html", Row{"data": dataRow(data), "editing": false})
			return
		}
		res, _ := db.Exec("INSERT INTO personnel_info (unit, department, name, gender, birth_date, "+
			"id_number, work_start_date, education, degree, title, rank, political_status, "+
			"party_join_date, position, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
			data["unit"], data["department"], data["name"], data["gender"],
			data["birth_date"], data["id_number"], data["work_start_date"], data["education"],
			data["degree"], data["title"], data["rank"], data["political_status"],
			data["party_join_date"], data["position"], data["operator"])
		infoID := lastInsertID(res)
		logAction(r, "create", "personnel_info", infoID, "", nil, rowSnapshot("personnel_info", infoID))
		flashMsg(w, r, "备案人员信息登记表已保存。请继续填写登记备案表。", "success")
		redirect(w, r, "personnel.filing_new", map[string]string{"info_id": itoa(infoID)})
		return
	}
	render(w, r, "personnel/info_form.html", Row{"data": Row{}, "editing": false})
}

func handleInfoEdit(w http.ResponseWriter, r *http.Request) {
	infoID := pathInt(r, "info_id")
	row := queryOne("SELECT * FROM personnel_info WHERE id = ?", infoID)
	if row == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, "personnel.list", nil)
		return
	}
	if r.Method == http.MethodPost {
		data := extractInfoForm(r)
		if errs := validateInfoForm(data); len(errs) > 0 {
			for _, e := range errs {
				flashMsg(w, r, e, "danger")
			}
			render(w, r, "personnel/info_form.html", Row{"data": dataRow(data), "editing": true, "info_id": infoID})
			return
		}
		before := rowSnapshot("personnel_info", infoID)
		db.Exec("UPDATE personnel_info SET unit=?, department=?, name=?, gender=?, "+
			"birth_date=?, id_number=?, work_start_date=?, education=?, degree=?, title=?, rank=?, "+
			"political_status=?, party_join_date=?, position=?, operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
			data["unit"], data["department"], data["name"], data["gender"],
			data["birth_date"], data["id_number"], data["work_start_date"], data["education"],
			data["degree"], data["title"], data["rank"], data["political_status"],
			data["party_join_date"], data["position"], data["operator"], infoID)
		logAction(r, "update", "personnel_info", infoID, "", before, rowSnapshot("personnel_info", infoID))
		flashMsg(w, r, "信息登记表已更新。", "success")
		redirect(w, r, "personnel.list", nil)
		return
	}
	render(w, r, "personnel/info_form.html", Row{"data": row, "editing": true, "info_id": infoID})
}

// ---------------------------------------------------------------------------
// 登记备案表
// ---------------------------------------------------------------------------
func extractFilingForm(r *http.Request) map[string]string {
	f := func(k string) string { return strings.TrimSpace(r.PostFormValue(k)) }
	tag := f("tag")
	if tag == "" {
		tag = "新增"
	}
	informed := f("informed")
	if informed == "" {
		informed = "否"
	}
	return map[string]string{
		"surname": f("surname"), "given_name": f("given_name"), "gender": f("gender"),
		"birth_date":       parseDateInput(f("birth_date")),
		"id_number":        strings.ToUpper(f("id_number")),
		"residence":        normalizeResidence(f("residence")),
		"political_status": f("political_status"), "work_unit": f("work_unit"),
		"position_or_title": f("position_or_title"), "supervisor_unit": f("supervisor_unit"),
		"tag": tag, "informed": informed, "remarks": f("remarks"), "operator": sessionUser(r),
	}
}

func validateFilingForm(data map[string]string, skipDupCheck bool) []string {
	var errs []string
	errs = append(errs, checkRequired(data, []fieldLabel{
		{"surname", "中文姓"}, {"given_name", "中文名"}, {"gender", "性别"},
		{"birth_date", "出生日期"}, {"id_number", "身份证号"},
		{"residence", "户口所在地"}, {"political_status", "政治面貌"},
		{"work_unit", "工作单位"}, {"position_or_title", "职务（级）或职称"},
		{"supervisor_unit", "人事主管单位"}, {"tag", "标记"}, {"informed", "已告知本人"},
	})...)
	errs = append(errs, checkDates(data, []fieldLabel{{"birth_date", "出生日期"}})...)
	errs = append(errs, checkIdentity(data, "birth_date", "gender")...)
	if data["id_number"] != "" && !skipDupCheck {
		if queryOne("SELECT id FROM personnel_filing WHERE id_number = ? AND status = 'active'", data["id_number"]) != nil {
			errs = append(errs, "该身份证号已存在有效备案记录，请勿重复登记。")
		}
	}
	return errs
}

func handleFilingNew(w http.ResponseWriter, r *http.Request) {
	infoID := int64(0)
	if v := r.URL.Query().Get("info_id"); v != "" {
		infoID = toInt64(v)
	}
	var infoRow Row
	if infoID > 0 {
		infoRow = queryOne("SELECT * FROM personnel_info WHERE id = ?", infoID)
	}

	if r.Method == http.MethodPost {
		data := extractFilingForm(r)
		if errs := validateFilingForm(data, false); len(errs) > 0 {
			for _, e := range errs {
				flashMsg(w, r, e, "danger")
			}
			render(w, r, "personnel/filing_form.html", Row{"data": dataRow(data), "editing": false, "info_id": infoID})
			return
		}
		var infoIDArg interface{}
		if infoID > 0 {
			infoIDArg = infoID
		}
		res, _ := db.Exec("INSERT INTO personnel_filing (personnel_info_id, surname, given_name, gender, "+
			"birth_date, id_number, residence, political_status, work_unit, "+
			"position_or_title, supervisor_unit, tag, informed, remarks, operator) "+
			"VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
			infoIDArg, data["surname"], data["given_name"], data["gender"],
			data["birth_date"], data["id_number"], data["residence"],
			data["political_status"], data["work_unit"], data["position_or_title"],
			data["supervisor_unit"], data["tag"], data["informed"], data["remarks"], data["operator"])
		filingID := lastInsertID(res)

		// 撤控重报关联
		prior := queryOne("SELECT id FROM personnel_filing WHERE id_number = ? AND status = 'decontrolled' "+
			"AND replaced_by_id IS NULL AND id != ? ORDER BY id DESC LIMIT 1", data["id_number"], filingID)
		if prior != nil {
			db.Exec("UPDATE personnel_filing SET replaced_by_id = ? WHERE id = ?", filingID, prior["id"])
			db.Exec("UPDATE personnel_filing SET tag = '更新' WHERE id = ?", filingID)
			flashMsg(w, r, "已与原撤控记录（#"+itoa(toInt64(prior["id"]))+"）建立关联，本记录标记为“更新”。", "info")
		}
		logAction(r, "create", "personnel_filing", filingID, "", nil, rowSnapshot("personnel_filing", filingID))
		flashMsg(w, r, "登记备案表已保存。", "success")
		redirect(w, r, "personnel.list", nil)
		return
	}

	prefill := Row{}
	if infoRow != nil {
		surname, givenName := detectSurnameSplit(rowStr(infoRow, "name"))
		posOrTitle := rowStr(infoRow, "position")
		if posOrTitle == "" {
			posOrTitle = rowStr(infoRow, "rank")
		}
		prefill = Row{
			"surname": surname, "given_name": givenName,
			"gender": infoRow["gender"], "birth_date": infoRow["birth_date"],
			"id_number":        rowStr(infoRow, "id_number"),
			"political_status": infoRow["political_status"],
			"work_unit":        infoRow["unit"], "position_or_title": posOrTitle,
		}
	}
	render(w, r, "personnel/filing_form.html", Row{"data": prefill, "editing": false, "info_id": infoID})
}

func handleFilingEdit(w http.ResponseWriter, r *http.Request) {
	filingID := pathInt(r, "filing_id")
	row := queryOne("SELECT * FROM personnel_filing WHERE id = ?", filingID)
	if row == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, "personnel.list", nil)
		return
	}
	if r.Method == http.MethodPost {
		data := extractFilingForm(r)
		if errs := validateFilingForm(data, true); len(errs) > 0 {
			for _, e := range errs {
				flashMsg(w, r, e, "danger")
			}
			render(w, r, "personnel/filing_form.html", Row{"data": dataRow(data), "editing": true, "filing_id": filingID})
			return
		}
		before := rowSnapshot("personnel_filing", filingID)
		db.Exec("UPDATE personnel_filing SET surname=?, given_name=?, gender=?, birth_date=?, "+
			"id_number=?, residence=?, political_status=?, work_unit=?, "+
			"position_or_title=?, supervisor_unit=?, tag=?, informed=?, remarks=?, "+
			"operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
			data["surname"], data["given_name"], data["gender"], data["birth_date"],
			data["id_number"], data["residence"], data["political_status"], data["work_unit"],
			data["position_or_title"], data["supervisor_unit"], data["tag"], data["informed"],
			data["remarks"], data["operator"], filingID)
		logAction(r, "update", "personnel_filing", filingID, "", before, rowSnapshot("personnel_filing", filingID))
		flashMsg(w, r, "登记备案表已更新。", "success")
		redirect(w, r, "personnel.list", nil)
		return
	}
	render(w, r, "personnel/filing_form.html", Row{"data": row, "editing": true, "filing_id": filingID})
}

func handlePersonnelView(w http.ResponseWriter, r *http.Request) {
	filingID := pathInt(r, "filing_id")
	filing := queryOne("SELECT * FROM personnel_filing WHERE id = ?", filingID)
	if filing == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, "personnel.list", nil)
		return
	}
	var infoRow Row
	if filing["personnel_info_id"] != nil {
		infoRow = queryOne("SELECT * FROM personnel_info WHERE id = ?", filing["personnel_info_id"])
	}
	var successor Row
	if filing["replaced_by_id"] != nil {
		successor = queryOne("SELECT id, surname, given_name, created_at FROM personnel_filing WHERE id = ?",
			filing["replaced_by_id"])
	}
	predecessor := queryOne("SELECT id, surname, given_name, created_at FROM personnel_filing WHERE replaced_by_id = ?", filingID)

	render(w, r, "personnel/view.html", Row{
		"filing": filing, "info": infoRow, "successor": successor, "predecessor": predecessor,
	})
}

func handlePersonnelDelete(w http.ResponseWriter, r *http.Request) {
	filingID := pathInt(r, "filing_id")
	if queryOne("SELECT id FROM personnel_filing WHERE id = ?", filingID) == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, "personnel.list", nil)
		return
	}
	// #3 删除前拦截：名下若有证照/出国明细/撤控记录（均 NOT NULL 外键引用本表），
	// 直接 DELETE 会因外键约束静默失败，故先检查并给出明确提示。
	certCnt := countQuery("SELECT COUNT(*) FROM certificates WHERE personnel_filing_id = ?", filingID)
	travelCnt := countQuery("SELECT COUNT(*) FROM travel_details WHERE personnel_filing_id = ?", filingID)
	decCnt := countQuery("SELECT COUNT(*) FROM decontrol_filing WHERE personnel_filing_id = ?", filingID)
	if certCnt > 0 || travelCnt > 0 || decCnt > 0 {
		flashMsg(w, r, fmt.Sprintf("该人员名下尚有证照 %d 条、出国明细 %d 条、撤控记录 %d 条，请先删除或处理这些关联记录后再删除备案。",
			certCnt, travelCnt, decCnt), "danger")
		redirect(w, r, "personnel.list", nil)
		return
	}
	before := rowSnapshot("personnel_filing", filingID)
	db.Exec("DELETE FROM personnel_filing WHERE id = ?", filingID)
	logAction(r, "delete", "personnel_filing", filingID, "", before, nil)
	flashMsg(w, r, "备案记录已删除。", "info")
	redirect(w, r, "personnel.list", nil)
}

// handleInfoList 信息登记表一览（含关联备案数），供清理无备案引用的孤儿记录（#2）
func handleInfoList(w http.ResponseWriter, r *http.Request) {
	rows, _ := queryMaps(
		"SELECT pi.*, " +
			"(SELECT COUNT(*) FROM personnel_filing pf WHERE pf.personnel_info_id = pi.id) AS filing_count " +
			"FROM personnel_info pi ORDER BY pi.id")
	render(w, r, "personnel/info_list.html", Row{"rows": rowsIface(rows)})
}

// handleInfoDelete 物理删除信息登记表：仅当无任何备案引用时才允许，防止悬空外键（#2）
func handleInfoDelete(w http.ResponseWriter, r *http.Request) {
	infoID := pathInt(r, "info_id")
	if queryOne("SELECT id FROM personnel_info WHERE id = ?", infoID) == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, "personnel.info_list", nil)
		return
	}
	if ref := countQuery("SELECT COUNT(*) FROM personnel_filing WHERE personnel_info_id = ?", infoID); ref > 0 {
		flashMsg(w, r, fmt.Sprintf("该信息登记表已被 %d 条备案记录引用，不能删除。请先删除相关备案记录。", ref), "danger")
		redirect(w, r, "personnel.info_list", nil)
		return
	}
	before := rowSnapshot("personnel_info", infoID)
	db.Exec("DELETE FROM personnel_info WHERE id = ?", infoID)
	logAction(r, "delete", "personnel_info", infoID, "", before, nil)
	flashMsg(w, r, "信息登记表已删除。", "info")
	redirect(w, r, "personnel.info_list", nil)
}

// ---- 小工具 ----
func pathInt(r *http.Request, name string) int64 { return toInt64(r.PathValue(name)) }

func itoa(n int64) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		b[i] = '-'
	}
	return string(b[i:])
}

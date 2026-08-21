// 证件领用管理（REQ-012）— 领用登记 / 归还登记 / 作废，含手写签名。
// 与 Python 版 blueprints/issuance.py 逐条对应。
//
// 设计约束（已与业务方审定，五版一致）：
//  1. 本模块是「证件领用/归还日期」的**唯一写入方**；travel_details 上的
//     passport_collect_date / passport_return_date 降级为派生只读字段，
//     由本模块回写，避免双数据源。
//  2. 签名一经保存**不可编辑**，登记有误只能作废（voided）后重新登记，
//     以保证签名凭证的证据效力。
//  3. 签名以 PNG 位图 + 笔迹矢量双存于数据库，随每日备份一起落盘；
//     不落文件系统（uploads 目录不在备份范围内）。
package main

import (
	"fmt"
	"net/http"
	"strings"
	"time"
)

// certNoField 证件种类代码 → certificates 表中对应的号码字段
var certNoField = map[string]string{
	"01": "passport_no",
	"02": "hm_pass_no",
	"03": "tw_pass_no",
}

// 列表/导出共用：JOIN 备案表以排除孤儿行（延续既有数据完整性口径）
const issuanceBaseSelect = "SELECT i.*, pf.work_unit AS work_unit " +
	"FROM cert_issuance i " +
	"JOIN personnel_filing pf ON i.personnel_filing_id = pf.id " +
	"WHERE 1=1"

// buildIssuanceFilters 构建领用列表 WHERE 子句，供列表与导出复用。
func buildIssuanceFilters(q map[string]string, ids []string) (string, []interface{}) {
	where := ""
	var params []interface{}
	if s := strings.TrimSpace(q["search"]); s != "" {
		where += " AND (i.holder_name LIKE ? OR i.id_number LIKE ? OR i.cert_nos LIKE ?)"
		like := "%" + s + "%"
		params = append(params, like, like, like)
	}
	switch strings.TrimSpace(q["status"]) {
	case "issued", "returned", "voided":
		where += " AND i.status = ?"
		params = append(params, strings.TrimSpace(q["status"]))
	}
	if t := strings.TrimSpace(q["cert_type"]); t != "" {
		where += " AND (',' || i.cert_types || ',') LIKE ?"
		params = append(params, "%,"+t+",%")
	}
	if d := strings.TrimSpace(q["date_from"]); d != "" {
		where += " AND i.issue_date >= ?"
		params = append(params, parseDateInput(d))
	}
	if d := strings.TrimSpace(q["date_to"]); d != "" {
		where += " AND i.issue_date <= ?"
		params = append(params, parseDateInput(d))
	}
	if len(ids) > 0 {
		where += " AND i.id IN (" + strings.TrimSuffix(strings.Repeat("?,", len(ids)), ",") + ")"
		for _, id := range ids {
			params = append(params, id)
		}
	}
	return where, params
}

func handleIssuanceList(w http.ResponseWriter, r *http.Request) {
	q := queryArgs(r)
	where, params := buildIssuanceFilters(q, nil)
	pg := listAll(issuanceBaseSelect+where+" ORDER BY i.issue_date DESC, i.id DESC", params...)
	render(w, r, "issuance/list.html", Row{
		"items":            pg.pageMap(),
		"search":           strings.TrimSpace(q["search"]),
		"status_filter":    strings.TrimSpace(q["status"]),
		"cert_type_filter": strings.TrimSpace(q["cert_type"]),
		"date_from":        strings.TrimSpace(q["date_from"]),
		"date_to":          strings.TrimSpace(q["date_to"]),
	})
}

func handleIssuanceNew(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		data := extractIssuanceForm(r)
		errs := validateIssuanceForm(data)
		blob, sigErr := decodeSignature(r.PostFormValue("sign_png"), RequireSignature)
		if sigErr != "" {
			errs = append(errs, sigErr)
		}
		if len(errs) > 0 {
			for _, e := range errs {
				flashMsg(w, r, e, "danger")
			}
			render(w, r, "issuance/form.html", Row{
				"data": dataRow(data), "travel": travelBrief(data["travel_id"])})
			return
		}
		res, err := db.Exec(
			"INSERT INTO cert_issuance (travel_id, personnel_filing_id, holder_name, id_number, "+
				"cert_types, cert_nos, issue_date, issuer, sign_image, sign_meta, status, remarks, operator) "+
				"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'issued', ?, ?)",
			nullIfEmpty(data["travel_id"]), data["personnel_filing_id"], data["holder_name"],
			data["id_number"], data["cert_types"], data["cert_nos"], data["issue_date"],
			data["issuer"], blob, cleanMeta(r.PostFormValue("sign_meta")),
			data["remarks"], data["operator"])
		if err != nil {
			flashMsg(w, r, "保存失败："+err.Error(), "danger")
			render(w, r, "issuance/form.html", Row{
				"data": dataRow(data), "travel": travelBrief(data["travel_id"])})
			return
		}
		issID := lastInsertID(res)
		syncTravelDates(data["travel_id"])
		logAction(r, "create", "cert_issuance", issID,
			fmt.Sprintf("证件领用登记：%s，%s", data["holder_name"], certTypesLabel(data["cert_types"])),
			nil, rowSnapshot("cert_issuance", issID))
		flashMsg(w, r, "证件领用登记已保存。", "success")
		redirect(w, r, "issuance.view", map[string]string{"iss_id": fmt.Sprint(issID)})
		return
	}

	// GET：支持从出行记录跳转带入
	travelID := r.URL.Query().Get("travel_id")
	prefill := Row{"issue_date": time.Now().Format("20060102")}
	travel := travelBrief(travelID)
	if travel != nil {
		prefill["travel_id"] = travelID
		prefill["personnel_filing_id"] = travel["personnel_filing_id"]
		prefill["holder_name"] = travel["name"]
		prefill["id_number"] = travel["id_number"]
	}
	render(w, r, "issuance/form.html", Row{"data": prefill, "travel": travel})
}

func handleIssuanceView(w http.ResponseWriter, r *http.Request) {
	row := issuanceOr404(w, r)
	if row == nil {
		return
	}
	render(w, r, "issuance/view.html", Row{
		"item":        row,
		"travel":      travelBrief(rowStr(row, "travel_id")),
		"type_labels": certTypesLabel(rowStr(row, "cert_types")),
	})
}

// handleIssuanceReturn 归还登记（同样需签名）。
func handleIssuanceReturn(w http.ResponseWriter, r *http.Request) {
	row := issuanceOr404(w, r)
	if row == nil {
		return
	}
	issID := rowStr(row, "id")
	if rowStr(row, "status") != "issued" {
		flashMsg(w, r, "该记录不是「已领用」状态，无法办理归还。", "warning")
		redirect(w, r, "issuance.view", map[string]string{"iss_id": issID})
		return
	}
	typeLabels := certTypesLabel(rowStr(row, "cert_types"))

	if r.Method == http.MethodPost {
		returnDate := parseDateInput(r.PostFormValue("return_date"))
		var errs []string
		if returnDate == "" {
			errs = append(errs, "归还日期为必填项。")
		} else {
			errs = append(errs, checkDates(map[string]string{"return_date": returnDate},
				[]fieldLabel{{"return_date", "归还日期"}})...)
			if returnDate < rowStr(row, "issue_date") {
				errs = append(errs, fmt.Sprintf("归还日期不应早于领用日期（%s）。", rowStr(row, "issue_date")))
			}
		}
		blob, sigErr := decodeSignature(r.PostFormValue("sign_png"), RequireSignature)
		if sigErr != "" {
			errs = append(errs, sigErr)
		}
		if len(errs) > 0 {
			for _, e := range errs {
				flashMsg(w, r, e, "danger")
			}
			render(w, r, "issuance/return.html", Row{
				"item": row, "return_date": returnDate, "type_labels": typeLabels})
			return
		}

		before := rowSnapshot("cert_issuance", toInt64(issID))
		db.Exec("UPDATE cert_issuance SET return_date=?, return_sign_image=?, return_sign_meta=?, "+
			"return_operator=?, status='returned', updated_at=CURRENT_TIMESTAMP WHERE id=?",
			returnDate, blob, cleanMeta(r.PostFormValue("sign_meta")), operatorName(r), issID)
		syncTravelDates(rowStr(row, "travel_id"))
		logAction(r, "update", "cert_issuance", toInt64(issID),
			fmt.Sprintf("证件归还登记：%s，归还日期 %s", rowStr(row, "holder_name"), returnDate),
			before, rowSnapshot("cert_issuance", toInt64(issID)))
		flashMsg(w, r, "证件归还登记已保存。", "success")
		redirect(w, r, "issuance.view", map[string]string{"iss_id": issID})
		return
	}

	render(w, r, "issuance/return.html", Row{
		"item": row, "return_date": time.Now().Format("20060102"), "type_labels": typeLabels})
}

// handleIssuanceVoid 作废。签名不可编辑，登记有误走这条路径。
func handleIssuanceVoid(w http.ResponseWriter, r *http.Request) {
	row := issuanceOr404(w, r)
	if row == nil {
		return
	}
	issID := rowStr(row, "id")
	if rowStr(row, "status") == "voided" {
		flashMsg(w, r, "该记录已是作废状态。", "info")
		redirect(w, r, "issuance.view", map[string]string{"iss_id": issID})
		return
	}
	reason := strings.TrimSpace(r.PostFormValue("void_reason"))
	if reason == "" {
		flashMsg(w, r, "作废原因为必填项。", "danger")
		redirect(w, r, "issuance.view", map[string]string{"iss_id": issID})
		return
	}

	before := rowSnapshot("cert_issuance", toInt64(issID))
	db.Exec("UPDATE cert_issuance SET status='voided', void_reason=?, "+
		"updated_at=CURRENT_TIMESTAMP WHERE id=?", reason, issID)
	syncTravelDates(rowStr(row, "travel_id"))
	logAction(r, "void", "cert_issuance", toInt64(issID),
		fmt.Sprintf("领用记录作废：%s，原因：%s", rowStr(row, "holder_name"), reason),
		before, rowSnapshot("cert_issuance", toInt64(issID)))
	flashMsg(w, r, "领用记录已作废，如需更正请重新登记。", "info")
	redirect(w, r, "issuance.view", map[string]string{"iss_id": issID})
}

// handleIssuanceSignature 输出签名位图。kind=return 取归还签名，否则取领用签名。
func handleIssuanceSignature(w http.ResponseWriter, r *http.Request) {
	col := "sign_image"
	if r.URL.Query().Get("kind") == "return" {
		col = "return_sign_image"
	}
	var blob []byte
	err := db.QueryRow("SELECT "+col+" FROM cert_issuance WHERE id = ?",
		pathInt(r, "iss_id")).Scan(&blob)
	if err != nil || len(blob) == 0 {
		notFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "image/png")
	// 签名一经保存不可变，可长期缓存
	w.Header().Set("Cache-Control", "private, max-age=86400")
	w.Write(blob)
}

// ---------------------------------------------------------------------------
// 内部工具
// ---------------------------------------------------------------------------

func issuanceOr404(w http.ResponseWriter, r *http.Request) Row {
	row := queryOne("SELECT i.*, pf.work_unit FROM cert_issuance i "+
		"JOIN personnel_filing pf ON i.personnel_filing_id = pf.id WHERE i.id = ?",
		pathInt(r, "iss_id"))
	if row == nil {
		notFound(w, r)
		return nil
	}
	return row
}

// travelBrief 取出行记录摘要（用于带入与展示）。
func travelBrief(travelID string) Row {
	if strings.TrimSpace(travelID) == "" {
		return nil
	}
	return queryOne("SELECT id, personnel_filing_id, name, id_number, unit, department, "+
		"destination_passport, travel_dates, approval_date, passport_no "+
		"FROM travel_details WHERE id = ?", toInt64(travelID))
}

// certTypesLabel 把 "01,02" 转成 "因私护照、往来港澳通行证"。
func certTypesLabel(codes string) string {
	var out []string
	for _, c := range strings.Split(codes, ",") {
		if c = strings.TrimSpace(c); c == "" {
			continue
		}
		if v := getDictValue("cert_type", c); v != "" {
			out = append(out, v)
		} else {
			out = append(out, c)
		}
	}
	return strings.Join(out, "、")
}

// syncTravelDates 把领用/归还日期回写到出行表（派生字段，本模块为唯一写入方）。
//
// 取该出行下**未作废**记录中最早的领用日期与最晚的归还日期；若全部作废或无记录，
// 则清空，使逾期告警口径与领用记录始终一致。
func syncTravelDates(travelID string) {
	if strings.TrimSpace(travelID) == "" {
		return
	}
	agg := queryOne(
		"SELECT MIN(issue_date) AS c, "+
			"       CASE WHEN COUNT(*) = SUM(CASE WHEN return_date IS NOT NULL AND return_date != '' "+
			"                                     THEN 1 ELSE 0 END) "+
			"            THEN MAX(return_date) ELSE NULL END AS r "+
			"FROM cert_issuance WHERE travel_id = ? AND status != 'voided'", toInt64(travelID))
	var collect, ret interface{}
	if agg != nil {
		collect = nullIfEmpty(rowStr(agg, "c"))
		ret = nullIfEmpty(rowStr(agg, "r"))
	}
	db.Exec("UPDATE travel_details SET passport_collect_date=?, passport_return_date=? WHERE id=?",
		collect, ret, toInt64(travelID))
}

func extractIssuanceForm(r *http.Request) map[string]string {
	f := func(k string) string { return strings.TrimSpace(r.PostFormValue(k)) }
	var types []string
	for _, t := range r.PostForm["cert_types"] {
		if t = strings.TrimSpace(t); t != "" {
			types = append(types, t)
		}
	}
	return map[string]string{
		"travel_id":           f("travel_id"),
		"personnel_filing_id": f("personnel_filing_id"),
		"holder_name":         f("holder_name"),
		"id_number":           f("id_number"),
		"cert_types":          strings.Join(types, ","),
		"cert_nos":            f("cert_nos"),
		"issue_date":          parseDateInput(f("issue_date")),
		"issuer":              operatorName(r),
		"remarks":             f("remarks"),
		"operator":            operatorName(r),
	}
}

func validateIssuanceForm(data map[string]string) []string {
	errs := checkRequired(data, []fieldLabel{
		{"personnel_filing_id", "领用人（备案人员）"},
		{"holder_name", "领用人姓名"},
		{"cert_types", "领用证件种类"},
		{"issue_date", "领用日期"},
	})
	errs = append(errs, checkDates(data, []fieldLabel{{"issue_date", "领用日期"}})...)

	// 证件种类必须是字典内的合法代码
	for _, c := range strings.Split(data["cert_types"], ",") {
		if c != "" {
			if _, ok := certNoField[c]; !ok {
				errs = append(errs, "无效的证件种类代码："+c+"。")
			}
		}
	}

	// 同一出行下不允许重复的未归还领用记录
	if data["travel_id"] != "" {
		if dup := queryOne("SELECT id FROM cert_issuance WHERE travel_id = ? AND status = 'issued'",
			toInt64(data["travel_id"])); dup != nil {
			errs = append(errs, fmt.Sprintf(
				"该出行记录已有未归还的领用记录（#%s），请先办理归还或作废。", rowStr(dup, "id")))
		}
	}
	return errs
}

// nullIfEmpty 空串写入数据库时应为 NULL，而不是 ''——
// 派生日期字段的「无值」要能被 IS NULL 命中。
func nullIfEmpty(s string) interface{} {
	if strings.TrimSpace(s) == "" {
		return nil
	}
	return s
}

// 操作日志 / 组织架构 / 数据字典 / 报送单位 / 全局搜索
package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
)

// ---------------------------------------------------------------------------
// 操作日志（服务端分页 + 变更快照解析 + 年度归档导出）
// ---------------------------------------------------------------------------
var fieldLabels = map[string]string{
	"unit": "单位", "department": "部门", "name": "姓名", "gender": "性别",
	"birth_date": "出生日期", "id_number": "身份证号", "work_start_date": "参加工作日期",
	"education": "学历", "degree": "学位", "title": "职称", "rank": "职级",
	"political_status": "政治面貌", "party_join_date": "入党日期", "position": "职务",
	"surname": "中文姓", "given_name": "中文名", "residence": "户口所在地",
	"work_unit": "工作单位", "position_or_title": "职务/职称", "supervisor_unit": "人事主管单位",
	"tag": "标记", "informed": "已告知本人", "status": "状态", "remarks": "备注",
	"passport_no": "护照号", "passport_expiry": "护照有效期", "passport_submit_date": "护照上交日期",
	"hm_pass_no": "港澳通行证号", "hm_pass_expiry": "港澳有效期", "hm_pass_submit_date": "港澳上交日期",
	"tw_pass_no": "台湾通行证号", "tw_pass_expiry": "台湾有效期", "tw_pass_submit_date": "台湾上交日期",
	"destination_passport": "地点、证照", "category": "类别", "travel_dates": "计划出行日期",
	"travel_start": "出行起", "travel_end": "出行止", "approval_date": "批准日期",
	"need_new_passport": "是否做证", "passport_collect_date": "领用日期", "passport_return_date": "归还日期",
	"actual_return_date": "实际回国日期", "trip_status": "行程状态", "cancel_date": "取消日期",
	"submit_unit_name": "报送单位", "submit_unit_type": "报送类别", "submit_contact": "联系人",
	"submit_phone": "联系电话", "batch_no": "入库批号", "reason": "撤控原因", "operator": "操作人",
}

func fieldLabelOf(k string) string {
	if v, ok := fieldLabels[k]; ok {
		return v
	}
	return k
}

func computeChanges(snapshotJSON string) Row {
	if snapshotJSON == "" {
		return nil
	}
	var data struct {
		Before map[string]interface{} `json:"before"`
		After  map[string]interface{} `json:"after"`
	}
	if json.Unmarshal([]byte(snapshotJSON), &data) != nil {
		return nil
	}
	str := func(v interface{}) string {
		if v == nil {
			return ""
		}
		return fmt.Sprintf("%v", v)
	}
	if data.Before != nil && data.After != nil {
		var diffs []interface{}
		for k, a := range data.After {
			b := data.Before[k]
			if str(b) != str(a) {
				diffs = append(diffs, Row{"field": fieldLabelOf(k), "before": b, "after": a})
			}
		}
		if len(diffs) == 0 {
			return nil
		}
		return Row{"type": "update", "diffs": diffs}
	}
	collect := func(m map[string]interface{}) []interface{} {
		var out []interface{}
		for k, v := range m {
			if v != nil && str(v) != "" {
				out = append(out, Row{"field": fieldLabelOf(k), "value": v})
			}
		}
		return out
	}
	if data.After != nil {
		return Row{"type": "create", "data": collect(data.After)}
	}
	if data.Before != nil {
		return Row{"type": "delete", "data": collect(data.Before)}
	}
	return nil
}

func handleLogs(w http.ResponseWriter, r *http.Request) {
	q := queryArgs(r)
	page, _ := strconv.Atoi(q["page"])
	if page < 1 {
		page = 1
	}
	base := "SELECT * FROM operation_logs WHERE 1=1"
	var params []interface{}
	if v := strings.TrimSpace(q["action"]); v != "" {
		base += " AND action = ?"
		params = append(params, v)
	}
	if v := strings.TrimSpace(q["target_type"]); v != "" {
		base += " AND target_type = ?"
		params = append(params, v)
	}
	if v := strings.TrimSpace(q["date_from"]); v != "" {
		base += " AND date(created_at) >= ?"
		params = append(params, v)
	}
	if v := strings.TrimSpace(q["date_to"]); v != "" {
		base += " AND date(created_at) <= ?"
		params = append(params, v)
	}
	base += " ORDER BY created_at DESC"
	pg := paginate(base, params, page, PageSizeLogs)
	for _, row := range pg.Rows {
		row["changes"] = computeChanges(rowStr(row, "snapshot"))
	}

	render(w, r, "logs/view.html", Row{
		"items":         pg.pageMap(),
		"action_filter": q["action"], "target_filter": q["target_type"],
		"date_from": q["date_from"], "date_to": q["date_to"],
		"action_types": optList("create", "新建", "update", "修改", "delete", "删除",
			"cancel", "取消行程", "restore", "恢复行程", "lock", "登录锁定",
			"export", "导出", "import", "导入", "backup", "备份"),
		"target_types": optList("personnel_info", "人员信息表", "personnel_filing", "登记备案表",
			"certificates", "证照登记表", "travel_details", "出国明细表",
			"decontrol_filing", "撤控备案表", "sys_dict", "数据字典",
			"sys_submit_unit", "报送单位", "users", "账户", "batch", "批量导入"),
		"log_years":     logYears(),
		"action_badges": map[string]string{"create": "success", "update": "warning", "delete": "danger", "backup": "secondary"},
		"action_labels": map[string]string{"create": "新建", "update": "修改", "delete": "删除",
			"cancel": "取消行程", "restore": "恢复行程", "lock": "登录锁定",
			"export": "导出", "import": "导入", "backup": "备份"},
		"target_labels": map[string]string{"personnel_info": "信息表", "personnel_filing": "备案表",
			"certificates": "证照表", "travel_details": "明细表", "decontrol_filing": "撤控表",
			"batch": "批量导入"},
	})
}

func logYears() []interface{} {
	tz := fmt.Sprintf("+%d hours", TZOffsetHours)
	rows, _ := queryMaps("SELECT DISTINCT strftime('%Y', datetime(created_at, ?)) AS y "+
		"FROM operation_logs WHERE created_at IS NOT NULL ORDER BY y DESC", tz)
	var out []interface{}
	for _, r := range rows {
		if y := rowStr(r, "y"); y != "" {
			out = append(out, y)
		}
	}
	return out
}

func handleLogsExport(w http.ResponseWriter, r *http.Request) {
	year := strings.TrimSpace(r.URL.Query().Get("year"))
	if len(year) != 4 || !digitsOnly.MatchString(year) {
		flashMsg(w, r, "请选择要归档导出的年份。", "warning")
		redirect(w, r, "logs.index", nil)
		return
	}
	filepath_, filename, err := exportLogs(sessionUser(r), year)
	if err != nil {
		flashMsg(w, r, "日志归档导出失败: "+err.Error(), "danger")
		redirect(w, r, "logs.index", nil)
		return
	}
	logAction(r, "export", "operation_logs", nil, "归档导出 "+year+" 年操作日志："+filename, nil, nil)
	sendFile(w, r, filepath_, filename)
}

func sendFile(w http.ResponseWriter, r *http.Request, path, downloadName string) {
	w.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
	w.Header().Set("Content-Disposition", `attachment; filename*=UTF-8''`+urlPathEscape(downloadName))
	http.ServeFile(w, r, path)
}

// ---------------------------------------------------------------------------
// 组织架构
// ---------------------------------------------------------------------------
func handleOrgIndex(w http.ResponseWriter, r *http.Request) {
	orgs, _ := queryMaps("SELECT * FROM sys_org ORDER BY parent_id, sort_order")
	childCount := map[string]int64{}
	for _, o := range orgs {
		childCount[itoa(toInt64(o["parent_id"]))]++
	}
	render(w, r, "organization/tree.html", Row{
		"orgs": rowsIface(orgs), "child_counts": childCount,
	})
}

func handleOrgAdd(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimSpace(r.PostFormValue("name"))
	parentID := toInt64(r.PostFormValue("parent_id"))
	if name == "" {
		flashMsg(w, r, "请输入单位/部门名称。", "danger")
		redirect(w, r, "organization.index", nil)
		return
	}
	db.Exec("INSERT INTO sys_org (name, parent_id, sort_order) VALUES (?, ?, 0)", name, parentID)
	logAction(r, "create", "sys_org", nil, name, nil, nil)
	flashMsg(w, r, "已添加："+name, "success")
	redirect(w, r, "organization.index", nil)
}

func handleOrgEdit(w http.ResponseWriter, r *http.Request) {
	orgID := pathInt(r, "org_id")
	name := strings.TrimSpace(r.PostFormValue("name"))
	parentID := toInt64(r.PostFormValue("parent_id"))
	if name == "" {
		flashMsg(w, r, "名称不能为空。", "danger")
		redirect(w, r, "organization.index", nil)
		return
	}
	db.Exec("UPDATE sys_org SET name = ?, parent_id = ? WHERE id = ?", name, parentID, orgID)
	logAction(r, "update", "sys_org", orgID, name, nil, nil)
	flashMsg(w, r, "已更新："+name, "success")
	redirect(w, r, "organization.index", nil)
}

func handleOrgDelete(w http.ResponseWriter, r *http.Request) {
	orgID := pathInt(r, "org_id")
	if countQuery("SELECT COUNT(*) FROM sys_org WHERE parent_id = ?", orgID) > 0 {
		flashMsg(w, r, "该节点下还有子部门，请先删除子部门。", "danger")
		redirect(w, r, "organization.index", nil)
		return
	}
	db.Exec("DELETE FROM sys_org WHERE id = ?", orgID)
	logAction(r, "delete", "sys_org", orgID, "", nil, nil)
	flashMsg(w, r, "已删除。", "info")
	redirect(w, r, "organization.index", nil)
}

func handleOrgTreeData(w http.ResponseWriter, r *http.Request) {
	orgs, _ := queryMaps("SELECT id, name, parent_id FROM sys_org ORDER BY parent_id, sort_order")
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(orgs)
}

// ---------------------------------------------------------------------------
// 数据字典
// ---------------------------------------------------------------------------
type dictCategory struct {
	Key   string
	Label string
	Refs  [][2]string
}

var dictCategories = []dictCategory{
	{"education", "学历", [][2]string{{"personnel_info", "education"}}},
	{"degree", "学位", [][2]string{{"personnel_info", "degree"}}},
	{"title", "职称", [][2]string{{"personnel_info", "title"}, {"travel_details", "title"}}},
	{"rank", "职级", [][2]string{{"personnel_info", "rank"}}},
	{"political_status", "政治面貌", [][2]string{
		{"personnel_info", "political_status"}, {"personnel_filing", "political_status"},
		{"decontrol_filing", "political_status"}}},
	{"travel_category", "出国（境）类别", [][2]string{{"travel_details", "category"}}},
	{"submit_unit_type", "报送单位类别", [][2]string{{"decontrol_filing", "submit_unit_type"}}},
	{"supervisor_unit", "人事主管单位", [][2]string{
		{"personnel_filing", "supervisor_unit"}, {"decontrol_filing", "supervisor_unit"}}},
}

func dictCatByKey(key string) *dictCategory {
	for i := range dictCategories {
		if dictCategories[i].Key == key {
			return &dictCategories[i]
		}
	}
	return nil
}

func dictUsageCount(category, code, value string) int64 {
	cat := dictCatByKey(category)
	if cat == nil {
		return 0
	}
	var total int64
	for _, ref := range cat.Refs {
		total += countQuery("SELECT COUNT(*) FROM "+ref[0]+" WHERE "+ref[1]+" = ? OR "+ref[1]+" = ?", code, value)
	}
	return total
}

func handleDictIndex(w http.ResponseWriter, r *http.Request) {
	var groups []interface{}
	for _, cat := range dictCategories {
		items, _ := queryMaps("SELECT * FROM sys_dict WHERE category = ? ORDER BY sort_order, code", cat.Key)
		groups = append(groups, Row{"key": cat.Key, "label": cat.Label, "rows": rowsIface(items)})
	}
	render(w, r, "dict/list.html", Row{"groups": groups})
}

func handleDictAdd(w http.ResponseWriter, r *http.Request) {
	category := strings.TrimSpace(r.PostFormValue("category"))
	code := strings.TrimSpace(r.PostFormValue("code"))
	value := strings.TrimSpace(r.PostFormValue("value"))
	sortOrder := toInt64(strings.TrimSpace(r.PostFormValue("sort_order")))

	cat := dictCatByKey(category)
	if cat == nil {
		flashMsg(w, r, "无效的字典类别。", "danger")
		redirect(w, r, "dict_admin.index", nil)
		return
	}
	if code == "" || value == "" {
		flashMsg(w, r, "编码与显示值均为必填。", "danger")
		redirect(w, r, "dict_admin.index", nil)
		return
	}
	if queryOne("SELECT id FROM sys_dict WHERE category = ? AND code = ?", category, code) != nil {
		flashMsg(w, r, "「"+cat.Label+"」下编码 "+code+" 已存在。", "warning")
		redirect(w, r, "dict_admin.index", nil)
		return
	}
	res, _ := db.Exec("INSERT INTO sys_dict (category, code, value, sort_order) VALUES (?, ?, ?, ?)",
		category, code, value, sortOrder)
	newID := lastInsertID(res)
	logAction(r, "create", "sys_dict", newID, cat.Label+": "+code+"="+value,
		nil, rowSnapshot("sys_dict", newID))
	flashMsg(w, r, "字典项已添加。", "success")
	redirect(w, r, "dict_admin.index", nil)
}

func handleDictEdit(w http.ResponseWriter, r *http.Request) {
	dictID := pathInt(r, "dict_id")
	row := queryOne("SELECT * FROM sys_dict WHERE id = ?", dictID)
	if row == nil {
		flashMsg(w, r, "字典项不存在。", "danger")
		redirect(w, r, "dict_admin.index", nil)
		return
	}
	value := strings.TrimSpace(r.PostFormValue("value"))
	sortOrder := toInt64(strings.TrimSpace(r.PostFormValue("sort_order")))
	if value == "" {
		flashMsg(w, r, "显示值为必填。", "danger")
		redirect(w, r, "dict_admin.index", nil)
		return
	}
	db.Exec("UPDATE sys_dict SET value = ?, sort_order = ? WHERE id = ?", value, sortOrder, dictID)
	logAction(r, "update", "sys_dict", dictID, "", row, rowSnapshot("sys_dict", dictID))
	flashMsg(w, r, "字典项已更新。", "success")
	redirect(w, r, "dict_admin.index", nil)
}

func handleDictDelete(w http.ResponseWriter, r *http.Request) {
	dictID := pathInt(r, "dict_id")
	row := queryOne("SELECT * FROM sys_dict WHERE id = ?", dictID)
	if row == nil {
		flashMsg(w, r, "字典项不存在。", "danger")
		redirect(w, r, "dict_admin.index", nil)
		return
	}
	if used := dictUsageCount(rowStr(row, "category"), rowStr(row, "code"), rowStr(row, "value")); used > 0 {
		flashMsg(w, r, fmt.Sprintf("「%s」已被 %d 条记录使用，不能删除（可改用编辑或保留）。", rowStr(row, "value"), used), "warning")
		redirect(w, r, "dict_admin.index", nil)
		return
	}
	db.Exec("DELETE FROM sys_dict WHERE id = ?", dictID)
	logAction(r, "delete", "sys_dict", dictID, "", row, nil)
	flashMsg(w, r, "字典项已删除。", "info")
	redirect(w, r, "dict_admin.index", nil)
}

// ---------------------------------------------------------------------------
// 报送单位
// ---------------------------------------------------------------------------
func handleSubmitUnitIndex(w http.ResponseWriter, r *http.Request) {
	rows, _ := queryMaps("SELECT * FROM sys_submit_unit ORDER BY sort_order, name")
	render(w, r, "submit_unit/list.html", Row{"rows": rowsIface(rows)})
}

func handleSubmitUnitAdd(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimSpace(r.PostFormValue("name"))
	if name == "" {
		flashMsg(w, r, "单位名称为必填。", "danger")
		redirect(w, r, "submit_unit.index", nil)
		return
	}
	if queryOne("SELECT id FROM sys_submit_unit WHERE name = ?", name) != nil {
		flashMsg(w, r, "该报送单位已存在。", "warning")
		redirect(w, r, "submit_unit.index", nil)
		return
	}
	res, _ := db.Exec("INSERT INTO sys_submit_unit (name, contact, phone, sort_order) VALUES (?, ?, ?, ?)",
		name, strings.TrimSpace(r.PostFormValue("contact")), strings.TrimSpace(r.PostFormValue("phone")),
		toInt64(r.PostFormValue("sort_order")))
	nid := lastInsertID(res)
	logAction(r, "create", "sys_submit_unit", nid, name, nil, rowSnapshot("sys_submit_unit", nid))
	flashMsg(w, r, "报送单位已添加。", "success")
	redirect(w, r, "submit_unit.index", nil)
}

func handleSubmitUnitEdit(w http.ResponseWriter, r *http.Request) {
	uid := pathInt(r, "uid")
	row := queryOne("SELECT * FROM sys_submit_unit WHERE id = ?", uid)
	if row == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, "submit_unit.index", nil)
		return
	}
	name := strings.TrimSpace(r.PostFormValue("name"))
	if name == "" {
		flashMsg(w, r, "单位名称为必填。", "danger")
		redirect(w, r, "submit_unit.index", nil)
		return
	}
	db.Exec("UPDATE sys_submit_unit SET name = ?, contact = ?, phone = ?, sort_order = ? WHERE id = ?",
		name, strings.TrimSpace(r.PostFormValue("contact")), strings.TrimSpace(r.PostFormValue("phone")),
		toInt64(r.PostFormValue("sort_order")), uid)
	logAction(r, "update", "sys_submit_unit", uid, "", row, rowSnapshot("sys_submit_unit", uid))
	flashMsg(w, r, "报送单位已更新。", "success")
	redirect(w, r, "submit_unit.index", nil)
}

func handleSubmitUnitDelete(w http.ResponseWriter, r *http.Request) {
	uid := pathInt(r, "uid")
	row := queryOne("SELECT * FROM sys_submit_unit WHERE id = ?", uid)
	if row == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, "submit_unit.index", nil)
		return
	}
	if used := countQuery("SELECT COUNT(*) FROM decontrol_filing WHERE submit_unit_name = ?", row["name"]); used > 0 {
		flashMsg(w, r, fmt.Sprintf("「%s」已被 %d 条撤控记录使用，不能删除。", rowStr(row, "name"), used), "warning")
		redirect(w, r, "submit_unit.index", nil)
		return
	}
	db.Exec("DELETE FROM sys_submit_unit WHERE id = ?", uid)
	logAction(r, "delete", "sys_submit_unit", uid, "", row, nil)
	flashMsg(w, r, "报送单位已删除。", "info")
	redirect(w, r, "submit_unit.index", nil)
}

// ---------------------------------------------------------------------------
// 全局搜索
// ---------------------------------------------------------------------------
func handleSearch(w http.ResponseWriter, r *http.Request) {
	q := strings.TrimSpace(r.URL.Query().Get("q"))
	results := Row{
		"personnel": []interface{}{}, "certificate": []interface{}{},
		"travel": []interface{}{}, "decontrol": []interface{}{},
	}
	total := 0
	if q != "" {
		like := "%" + q + "%"
		const limit = 50
		p, _ := queryMaps("SELECT id, surname, given_name, id_number, work_unit, status "+
			"FROM personnel_filing WHERE surname||given_name LIKE ? OR id_number LIKE ? "+
			"ORDER BY created_at DESC LIMIT ?", like, like, limit)
		c, _ := queryMaps("SELECT id, name, unit, passport_no, hm_pass_no, tw_pass_no "+
			"FROM certificates WHERE name LIKE ? OR passport_no LIKE ? OR hm_pass_no LIKE ? OR tw_pass_no LIKE ? "+
			"ORDER BY created_at DESC LIMIT ?", like, like, like, like, limit)
		t, _ := queryMaps("SELECT id, name, destination_passport, travel_dates, trip_status "+
			"FROM travel_details WHERE name LIKE ? OR destination_passport LIKE ? OR passport_no LIKE ? "+
			"ORDER BY created_at DESC LIMIT ?", like, like, like, limit)
		d, _ := queryMaps("SELECT id, surname, given_name, work_unit, reason, decontrol_date "+
			"FROM decontrol_filing WHERE surname||given_name LIKE ? OR id_number LIKE ? OR reason LIKE ? "+
			"ORDER BY created_at DESC LIMIT ?", like, like, like, limit)
		results["personnel"] = rowsIface(p)
		results["certificate"] = rowsIface(c)
		results["travel"] = rowsIface(t)
		results["decontrol"] = rowsIface(d)
		total = len(p) + len(c) + len(t) + len(d)
	}
	render(w, r, "search/results.html", Row{"q": q, "results": results, "total": total})
}

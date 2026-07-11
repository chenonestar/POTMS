// 出国（境）申请：明细表 + 附件上传 + 行程取消/恢复 + 附件总览
package main

import (
	"crypto/rand"
	"encoding/hex"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

var (
	requiredAttA  = []string{"个人申请报告", "审批表"}
	requiredAttB  = []string{"个人申请报告", "审批表", "同意申办函"}
	attCategories = []struct{ Field, Label string }{
		{"att_application", "个人申请报告"},
		{"att_approval", "审批表"},
		{"att_consent", "同意申办函"},
	}
)

func travelOverdueIDs() map[int64]bool {
	today := nowLocalYMD()
	rows, _ := queryMaps("SELECT id, passport_collect_date, passport_return_date, actual_return_date, " +
		"travel_end, trip_status, cancel_date FROM travel_details " +
		"WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' " +
		"AND (passport_return_date IS NULL OR passport_return_date = '')")
	out := map[int64]bool{}
	for _, r := range rows {
		if isCertOverdue(r, today) {
			out[toInt64(r["id"])] = true
		}
	}
	return out
}

func travelFilters(q map[string]string, ids []int64) (string, []interface{}) {
	where := ""
	var params []interface{}
	if s := strings.TrimSpace(q["search"]); s != "" {
		where += " AND (name LIKE ? OR destination_passport LIKE ?)"
		like := "%" + s + "%"
		params = append(params, like, like)
	}
	if v := strings.TrimSpace(q["category"]); v != "" {
		where += " AND category = ?"
		params = append(params, v)
	}
	if v := strings.TrimSpace(q["need_new_passport"]); v != "" {
		where += " AND need_new_passport = ?"
		params = append(params, v)
	}
	switch strings.TrimSpace(q["passport_status"]) {
	case "storage":
		where += " AND (passport_collect_date IS NULL OR passport_collect_date = '')"
	case "inuse":
		where += " AND passport_collect_date IS NOT NULL AND passport_collect_date != '' " +
			"AND (passport_return_date IS NULL OR passport_return_date = '')"
	case "overdue":
		oids := travelOverdueIDs()
		if len(oids) > 0 {
			var list []string
			for id := range oids {
				list = append(list, itoa(id))
			}
			where += " AND id IN (" + strings.Join(list, ",") + ")"
		} else {
			where += " AND 1=0"
		}
	}
	if v := parseDateInput(q["date_from"]); v != "" {
		where += " AND travel_end >= ? AND travel_end != ''"
		params = append(params, v)
	}
	if v := parseDateInput(q["date_to"]); v != "" {
		where += " AND travel_start <= ? AND travel_start != ''"
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

func handleTravelList(w http.ResponseWriter, r *http.Request) {
	q := queryArgs(r)
	where, params := travelFilters(q, nil)
	pg := listAll("SELECT * FROM travel_details WHERE 1=1"+where+" ORDER BY created_at DESC", params...)

	today := nowLocalYMD()
	var overdueIDs []interface{}
	deadlines := map[string]string{}
	for _, row := range pg.Rows {
		if isCertOverdue(row, today) {
			id := toInt64(row["id"])
			overdueIDs = append(overdueIDs, id)
			deadlines[itoa(id)] = certOverdueDeadline(row)
		}
	}
	render(w, r, "travel/list.html", Row{
		"items": pg.pageMap(), "search": q["search"],
		"category_filter": q["category"], "need_passport_filter": q["need_new_passport"],
		"passport_status": q["passport_status"],
		"date_from":       q["date_from"], "date_to": q["date_to"],
		"overdue_ids": overdueIDs, "deadlines": deadlines,
		"category_opts": rowsIface(getDictOptions("travel_category")),
	})
}

// ---------------------------------------------------------------------------
// 附件总览
// ---------------------------------------------------------------------------
func handleTravelAttachments(w http.ResponseWriter, r *http.Request) {
	q := queryArgs(r)
	base := "SELECT a.id, a.file_name, a.file_type, a.file_size, a.uploaded_at, " +
		"t.id AS travel_id, t.name, t.unit, t.destination_passport, t.travel_dates " +
		"FROM attachments a JOIN travel_details t ON a.travel_id = t.id WHERE 1=1"
	var params []interface{}
	if s := strings.TrimSpace(q["search"]); s != "" {
		base += " AND (t.name LIKE ? OR a.file_name LIKE ?)"
		like := "%" + s + "%"
		params = append(params, like, like)
	}
	if v := strings.TrimSpace(q["file_type"]); v != "" {
		base += " AND a.file_type = ?"
		params = append(params, v)
	}
	if v := strings.TrimSpace(q["date_from"]); v != "" {
		base += " AND date(a.uploaded_at) >= ?"
		params = append(params, v)
	}
	if v := strings.TrimSpace(q["date_to"]); v != "" {
		base += " AND date(a.uploaded_at) <= ?"
		params = append(params, v)
	}
	pg := listAll(base+" ORDER BY a.uploaded_at DESC", params...)

	// 缺件检查
	travels, _ := queryMaps("SELECT id, name, unit, need_new_passport FROM travel_details ORDER BY created_at DESC")
	var missing []Row
	for _, tv := range travels {
		haveRows, _ := queryMaps("SELECT DISTINCT file_type FROM attachments WHERE travel_id = ?", tv["id"])
		have := map[string]bool{}
		for _, h := range haveRows {
			have[rowStr(h, "file_type")] = true
		}
		required := requiredAttA
		path := "A"
		if rowStr(tv, "need_new_passport") == "是" {
			required = requiredAttB
			path = "B"
		}
		var lack []interface{}
		for _, req := range required {
			if !have[req] {
				lack = append(lack, req)
			}
		}
		if len(lack) > 0 {
			missing = append(missing, Row{
				"id": tv["id"], "name": tv["name"], "unit": tv["unit"], "path": path, "lack": lack,
			})
		}
	}
	tcRows, _ := queryMaps("SELECT file_type, COUNT(*) AS cnt FROM attachments GROUP BY file_type")
	typeCounts := map[string]int64{"个人申请报告": 0, "审批表": 0, "同意申办函": 0}
	for _, tr := range tcRows {
		typeCounts[rowStr(tr, "file_type")] = toInt64(tr["cnt"])
	}
	render(w, r, "travel/attachments.html", Row{
		"items": pg.pageMap(), "search": q["search"], "type_filter": q["file_type"],
		"date_from": q["date_from"], "date_to": q["date_to"],
		"missing": rowsIface(missing), "type_counts": typeCounts,
		"total_att": countQuery("SELECT COUNT(*) FROM attachments"),
		"types":     []interface{}{"个人申请报告", "审批表", "同意申办函"},
	})
}

// ---------------------------------------------------------------------------
// 新增 / 编辑 / 查看 / 删除
// ---------------------------------------------------------------------------
func extractTravelForm(r *http.Request) map[string]string {
	f := func(k string) string { return strings.TrimSpace(r.PostFormValue(k)) }
	np := f("need_new_passport")
	if np == "" {
		np = "否"
	}
	return map[string]string{
		"personnel_filing_id": f("personnel_filing_id"),
		"unit":                f("unit"), "department": f("department"), "name": f("name"),
		"position": f("position"), "title": f("title"),
		"id_number":            strings.ToUpper(f("id_number")),
		"destination_passport": f("destination_passport"), "category": f("category"),
		"travel_dates":      f("travel_dates"),
		"approval_date":     parseDateInput(f("approval_date")),
		"need_new_passport": np, "passport_no": f("passport_no"),
		"passport_collect_date": parseDateInput(f("passport_collect_date")),
		"passport_return_date":  parseDateInput(f("passport_return_date")),
		"actual_return_date":    parseDateInput(f("actual_return_date")),
		"operator":              sessionUser(r),
	}
}

func validateTravelForm(data map[string]string) []string {
	var errs []string
	errs = append(errs, checkRequired(data, []fieldLabel{
		{"personnel_filing_id", "备案人员"}, {"unit", "单位"}, {"department", "部门"},
		{"name", "姓名"}, {"position", "职务"}, {"id_number", "身份证号"},
		{"destination_passport", "地点、证照"}, {"category", "类别"},
		{"travel_dates", "计划出行日期"}, {"need_new_passport", "是否做证"},
	})...)
	errs = append(errs, checkIdentity(data, "", "")...) // 仅校验号码本身
	if data["travel_dates"] != "" {
		if ok, msg := validateTravelRange(data["travel_dates"]); !ok {
			errs = append(errs, "计划出行日期: "+msg)
		}
	}
	errs = append(errs, checkDates(data, []fieldLabel{
		{"approval_date", "批准日期"}, {"passport_collect_date", "证件领用日期"},
		{"passport_return_date", "证件归还日期"}, {"actual_return_date", "实际回国日期"},
	})...)
	if data["need_new_passport"] == "否" && data["passport_collect_date"] == "" {
		errs = append(errs, "路径A（已有证件）时，证件领用日期为必填。")
	}
	return errs
}

func isPDF(f multipart.File) bool {
	head := make([]byte, 5)
	n, _ := io.ReadFull(f, head)
	f.Seek(0, io.SeekStart)
	return n == 5 && string(head) == "%PDF-"
}

// missingAttachmentErrors 必传附件 + PDF 魔数预检
func missingAttachmentErrors(r *http.Request, needNewPassport string) []string {
	var errs []string
	has := func(field string) bool {
		if r.MultipartForm == nil {
			return false
		}
		for _, fh := range r.MultipartForm.File[field] {
			if fh.Filename != "" {
				return true
			}
		}
		return false
	}
	if !has("att_application") {
		errs = append(errs, "附件《个人申请报告》为必传项（PDF）。")
	}
	if !has("att_approval") {
		errs = append(errs, "附件《审批表》为必传项（PDF）。")
	}
	if needNewPassport == "是" && !has("att_consent") {
		errs = append(errs, "需新办证件（路径B）时，《同意申办函》为必传项（PDF）。")
	}
	if r.MultipartForm != nil {
		for _, cat := range attCategories {
			for _, fh := range r.MultipartForm.File[cat.Field] {
				if fh.Filename == "" {
					continue
				}
				f, err := fh.Open()
				if err != nil {
					continue
				}
				ok := isPDF(f)
				f.Close()
				if !ok {
					errs = append(errs, "文件 "+fh.Filename+" 内容不是有效的 PDF，请上传真实的 PDF 扫描件。")
				}
			}
		}
	}
	return errs
}

func saveAttachments(w http.ResponseWriter, r *http.Request, travelID int64) {
	if r.MultipartForm == nil {
		return
	}
	for _, cat := range attCategories {
		for _, fh := range r.MultipartForm.File[cat.Field] {
			if fh.Filename == "" {
				continue
			}
			ext := strings.ToLower(filepath.Ext(fh.Filename))
			if ext != ".pdf" {
				flashMsg(w, r, "文件 "+fh.Filename+" 格式不支持（仅允许 PDF）。", "warning")
				continue
			}
			src, err := fh.Open()
			if err != nil {
				continue
			}
			if !isPDF(src) {
				src.Close()
				flashMsg(w, r, "文件 "+fh.Filename+" 内容不是有效的 PDF（已拒绝）。", "warning")
				continue
			}
			buf := make([]byte, 16)
			rand.Read(buf)
			savedName := hex.EncodeToString(buf) + ".pdf"
			dst, err := os.Create(filepath.Join(UploadDir, savedName))
			if err != nil {
				src.Close()
				continue
			}
			size, _ := io.Copy(dst, src)
			dst.Close()
			src.Close()
			db.Exec("INSERT INTO attachments (travel_id, file_name, file_path, file_type, file_size) VALUES (?,?,?,?,?)",
				travelID, fh.Filename, savedName, cat.Label, size)
		}
	}
}

func handleTravelNew(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		r.ParseMultipartForm(int64(MaxContentLength))
		data := extractTravelForm(r)
		errs := validateTravelForm(data)
		errs = append(errs, missingAttachmentErrors(r, data["need_new_passport"])...)
		if len(errs) > 0 {
			for _, e := range errs {
				flashMsg(w, r, e, "danger")
			}
			render(w, r, "travel/form.html", Row{"data": dataRow(data), "editing": false})
			return
		}
		tStart, tEnd := parseTravelRange(data["travel_dates"])
		if canon := formatTravelRange(tStart, tEnd); canon != "" {
			data["travel_dates"] = canon
		}
		res, _ := db.Exec("INSERT INTO travel_details (personnel_filing_id, unit, department, name, "+
			"position, title, id_number, destination_passport, category, travel_dates, "+
			"travel_start, travel_end, approval_date, need_new_passport, passport_no, "+
			"passport_collect_date, passport_return_date, actual_return_date, operator) "+
			"VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
			data["personnel_filing_id"], data["unit"], data["department"], data["name"],
			data["position"], data["title"], data["id_number"], data["destination_passport"],
			data["category"], data["travel_dates"], tStart, tEnd, data["approval_date"],
			data["need_new_passport"], data["passport_no"], data["passport_collect_date"],
			data["passport_return_date"], data["actual_return_date"], data["operator"])
		travelID := lastInsertID(res)
		saveAttachments(w, r, travelID)
		logAction(r, "create", "travel_details", travelID, "", nil, rowSnapshot("travel_details", travelID))
		flashMsg(w, r, "出国（境）明细表已保存。", "success")
		redirect(w, r, "travel.list", nil)
		return
	}

	prefill := Row{}
	if fid := r.URL.Query().Get("filing_id"); fid != "" {
		filing := queryOne("SELECT pf.*, "+
			"COALESCE((SELECT unit FROM personnel_info WHERE id = pf.personnel_info_id), pf.work_unit) AS info_unit, "+
			"COALESCE((SELECT department FROM personnel_info WHERE id = pf.personnel_info_id), '') AS info_dept "+
			"FROM personnel_filing pf WHERE pf.id = ?", toInt64(fid))
		if filing != nil {
			prefill = Row{
				"personnel_filing_id": toInt64(fid),
				"unit":                filing["info_unit"], "department": filing["info_dept"],
				"name":     rowStr(filing, "surname") + rowStr(filing, "given_name"),
				"position": filing["position_or_title"], "id_number": filing["id_number"],
			}
		}
	}
	render(w, r, "travel/form.html", Row{"data": prefill, "editing": false})
}

func handleTravelEdit(w http.ResponseWriter, r *http.Request) {
	travelID := pathInt(r, "travel_id")
	row := queryOne("SELECT * FROM travel_details WHERE id = ?", travelID)
	if row == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, "travel.list", nil)
		return
	}
	if r.Method == http.MethodPost {
		r.ParseMultipartForm(int64(MaxContentLength))
		data := extractTravelForm(r)
		if errs := validateTravelForm(data); len(errs) > 0 {
			for _, e := range errs {
				flashMsg(w, r, e, "danger")
			}
			render(w, r, "travel/form.html", Row{"data": dataRow(data), "editing": true, "travel_id": travelID})
			return
		}
		before := rowSnapshot("travel_details", travelID)
		tStart, tEnd := parseTravelRange(data["travel_dates"])
		if canon := formatTravelRange(tStart, tEnd); canon != "" {
			data["travel_dates"] = canon
		}
		db.Exec("UPDATE travel_details SET personnel_filing_id=?, unit=?, department=?, "+
			"name=?, position=?, title=?, id_number=?, destination_passport=?, "+
			"category=?, travel_dates=?, travel_start=?, travel_end=?, approval_date=?, need_new_passport=?, "+
			"passport_no=?, passport_collect_date=?, passport_return_date=?, actual_return_date=?, "+
			"operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
			data["personnel_filing_id"], data["unit"], data["department"], data["name"],
			data["position"], data["title"], data["id_number"], data["destination_passport"],
			data["category"], data["travel_dates"], tStart, tEnd, data["approval_date"],
			data["need_new_passport"], data["passport_no"], data["passport_collect_date"],
			data["passport_return_date"], data["actual_return_date"], data["operator"], travelID)
		saveAttachments(w, r, travelID)
		logAction(r, "update", "travel_details", travelID, "", before, rowSnapshot("travel_details", travelID))
		flashMsg(w, r, "明细表已更新。", "success")
		redirect(w, r, "travel.list", nil)
		return
	}
	atts, _ := queryMaps("SELECT * FROM attachments WHERE travel_id = ? ORDER BY uploaded_at", travelID)
	render(w, r, "travel/form.html", Row{
		"data": row, "editing": true, "travel_id": travelID, "attachments": rowsIface(atts),
	})
}

func handleTravelView(w http.ResponseWriter, r *http.Request) {
	travelID := pathInt(r, "travel_id")
	row := queryOne("SELECT * FROM travel_details WHERE id = ?", travelID)
	if row == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, "travel.list", nil)
		return
	}
	atts, _ := queryMaps("SELECT * FROM attachments WHERE travel_id = ? ORDER BY uploaded_at", travelID)
	render(w, r, "travel/view.html", Row{"travel": row, "attachments": rowsIface(atts)})
}

func handleTravelDelete(w http.ResponseWriter, r *http.Request) {
	travelID := pathInt(r, "travel_id")
	atts, _ := queryMaps("SELECT file_path FROM attachments WHERE travel_id = ?", travelID)
	for _, att := range atts {
		os.Remove(filepath.Join(UploadDir, rowStr(att, "file_path")))
	}
	before := rowSnapshot("travel_details", travelID)
	db.Exec("DELETE FROM attachments WHERE travel_id = ?", travelID)
	db.Exec("DELETE FROM travel_details WHERE id = ?", travelID)
	logAction(r, "delete", "travel_details", travelID, "", before, nil)
	flashMsg(w, r, "出国申请记录已删除。", "info")
	redirect(w, r, "travel.list", nil)
}

// ---------------------------------------------------------------------------
// 行程取消 / 恢复
// ---------------------------------------------------------------------------
func handleTravelCancel(w http.ResponseWriter, r *http.Request) {
	travelID := pathInt(r, "travel_id")
	row := queryOne("SELECT * FROM travel_details WHERE id = ?", travelID)
	if row == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, "travel.list", nil)
		return
	}
	if rowStr(row, "trip_status") == "cancelled" {
		flashMsg(w, r, "该行程已处于取消状态。", "info")
		redirect(w, r, "travel.view", map[string]string{"travel_id": itoa(travelID)})
		return
	}
	cancelDate := parseDateInput(r.PostFormValue("cancel_date"))
	if cancelDate == "" {
		cancelDate = time.Now().Format("20060102")
	}
	if ok, msg := validateDateFormat(cancelDate); !ok {
		flashMsg(w, r, "取消日期: "+msg, "danger")
		redirect(w, r, "travel.view", map[string]string{"travel_id": itoa(travelID)})
		return
	}
	before := rowSnapshot("travel_details", travelID)
	db.Exec("UPDATE travel_details SET trip_status='cancelled', cancel_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
		cancelDate, travelID)
	logAction(r, "cancel", "travel_details", travelID, "取消行程（"+cancelDate+"）",
		before, rowSnapshot("travel_details", travelID))
	flashMsg(w, r, "行程已取消（"+cancelDate+"）。已申领证件请于 5 个工作日内送回保管。", "warning")
	redirect(w, r, "travel.view", map[string]string{"travel_id": itoa(travelID)})
}

func handleTravelRestore(w http.ResponseWriter, r *http.Request) {
	travelID := pathInt(r, "travel_id")
	if queryOne("SELECT id FROM travel_details WHERE id = ?", travelID) == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, "travel.list", nil)
		return
	}
	before := rowSnapshot("travel_details", travelID)
	db.Exec("UPDATE travel_details SET trip_status='normal', cancel_date=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?", travelID)
	logAction(r, "restore", "travel_details", travelID, "恢复行程为正常",
		before, rowSnapshot("travel_details", travelID))
	flashMsg(w, r, "行程已恢复为正常状态。", "success")
	redirect(w, r, "travel.view", map[string]string{"travel_id": itoa(travelID)})
}

// ---------------------------------------------------------------------------
// 附件下载 / 预览 / 删除
// ---------------------------------------------------------------------------
func attachmentByID(r *http.Request) Row {
	return queryOne("SELECT * FROM attachments WHERE id = ?", pathInt(r, "att_id"))
}

func serveAttachment(w http.ResponseWriter, r *http.Request, att Row, inline bool) {
	full := filepath.Join(UploadDir, filepath.Base(rowStr(att, "file_path"))) // Base 防路径穿越
	disposition := "attachment"
	if inline {
		disposition = "inline"
	}
	w.Header().Set("Content-Type", "application/pdf")
	w.Header().Set("Content-Disposition", disposition+`; filename*=UTF-8''`+
		strings.ReplaceAll(urlPathEscape(rowStr(att, "file_name")), "+", "%20"))
	http.ServeFile(w, r, full)
}

func urlPathEscape(s string) string {
	const hex = "0123456789ABCDEF"
	var b strings.Builder
	for _, c := range []byte(s) {
		if (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' || c == '-' || c == '_' {
			b.WriteByte(c)
		} else {
			b.WriteByte('%')
			b.WriteByte(hex[c>>4])
			b.WriteByte(hex[c&15])
		}
	}
	return b.String()
}

func handleAttachmentDownload(w http.ResponseWriter, r *http.Request) {
	att := attachmentByID(r)
	if att == nil {
		flashMsg(w, r, "附件不存在。", "danger")
		redirect(w, r, "travel.list", nil)
		return
	}
	serveAttachment(w, r, att, false)
}

func handleAttachmentPreview(w http.ResponseWriter, r *http.Request) {
	att := attachmentByID(r)
	if att == nil {
		flashMsg(w, r, "附件不存在。", "danger")
		redirect(w, r, "travel.list", nil)
		return
	}
	serveAttachment(w, r, att, true)
}

func handleAttachmentDelete(w http.ResponseWriter, r *http.Request) {
	att := attachmentByID(r)
	if att == nil {
		flashMsg(w, r, "附件不存在。", "danger")
		redirect(w, r, "travel.list", nil)
		return
	}
	os.Remove(filepath.Join(UploadDir, filepath.Base(rowStr(att, "file_path"))))
	travelID := toInt64(att["travel_id"])
	db.Exec("DELETE FROM attachments WHERE id = ?", att["id"])
	flashMsg(w, r, "附件已删除。", "info")
	redirect(w, r, "travel.edit", map[string]string{"travel_id": itoa(travelID)})
}

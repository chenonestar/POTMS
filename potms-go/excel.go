// Excel 导出（5 类表单 + 日志归档）与批量导入 — excelize 纯 Go 实现
package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/xuri/excelize/v2"
)

const exportRetentionDays = 7

func pruneOldExports() {
	entries, err := os.ReadDir(ExportDir)
	if err != nil {
		return
	}
	cutoff := time.Now().Add(-exportRetentionDays * 24 * time.Hour)
	for _, e := range entries {
		if !strings.HasSuffix(strings.ToLower(e.Name()), ".xlsx") {
			continue
		}
		if info, err := e.Info(); err == nil && info.ModTime().Before(cutoff) {
			os.Remove(filepath.Join(ExportDir, e.Name()))
		}
	}
}

// styleSheet 表名标题行(合并) + 列头行 + 冻结（数据从第 3 行开始）
func styleSheet(f *excelize.File, sheet, title string, headers []string) {
	titleStyle, _ := f.NewStyle(&excelize.Style{
		Font:      &excelize.Font{Family: "微软雅黑", Bold: true, Size: 16},
		Alignment: &excelize.Alignment{Horizontal: "center", Vertical: "center"},
	})
	headerStyle, _ := f.NewStyle(&excelize.Style{
		Font:      &excelize.Font{Family: "微软雅黑", Bold: true, Size: 11, Color: "FFFFFF"},
		Fill:      excelize.Fill{Type: "pattern", Pattern: 1, Color: []string{"1A5276"}},
		Alignment: &excelize.Alignment{Horizontal: "center", Vertical: "center", WrapText: true},
		Border:    thinBorder(),
	})
	last, _ := excelize.CoordinatesToCellName(len(headers), 1)
	f.MergeCell(sheet, "A1", last)
	f.SetCellValue(sheet, "A1", title)
	f.SetCellStyle(sheet, "A1", last, titleStyle)
	f.SetRowHeight(sheet, 1, 30)
	for i, h := range headers {
		cell, _ := excelize.CoordinatesToCellName(i+1, 2)
		f.SetCellValue(sheet, cell, h)
	}
	h1, _ := excelize.CoordinatesToCellName(1, 2)
	h2, _ := excelize.CoordinatesToCellName(len(headers), 2)
	f.SetCellStyle(sheet, h1, h2, headerStyle)
	f.SetPanes(sheet, &excelize.Panes{Freeze: true, YSplit: 2, TopLeftCell: "A3", ActivePane: "bottomLeft"})
}

func thinBorder() []excelize.Border {
	return []excelize.Border{
		{Type: "left", Style: 1}, {Type: "right", Style: 1},
		{Type: "top", Style: 1}, {Type: "bottom", Style: 1},
	}
}

func styleData(f *excelize.File, sheet string, rowCount, colCount int) {
	if rowCount == 0 {
		return
	}
	dataStyle, _ := f.NewStyle(&excelize.Style{
		Alignment: &excelize.Alignment{Vertical: "center", WrapText: true},
		Border:    thinBorder(),
	})
	start, _ := excelize.CoordinatesToCellName(1, 3)
	end, _ := excelize.CoordinatesToCellName(colCount, rowCount+2)
	f.SetCellStyle(sheet, start, end, dataStyle)
}

func autoWidth(f *excelize.File, sheet string, colCount, maxRow int) {
	for c := 1; c <= colCount; c++ {
		maxLen := 0
		for row := 2; row <= maxRow; row++ {
			cell, _ := excelize.CoordinatesToCellName(c, row)
			v, _ := f.GetCellValue(sheet, cell)
			if l := len([]rune(v)); l > maxLen {
				maxLen = l
			}
		}
		w := float64(maxLen + 4)
		if w > 40 {
			w = 40
		}
		col, _ := excelize.ColumnNumberToName(c)
		f.SetColWidth(sheet, col, col, w)
	}
}

func addNotes(f *excelize.File, notes []string) {
	if len(notes) == 0 {
		return
	}
	f.NewSheet("填表说明")
	for i, n := range notes {
		f.SetCellValue("填表说明", fmt.Sprintf("A%d", i+1), n)
	}
}

func saveWorkbook(f *excelize.File, prefix, operator string) (string, string, error) {
	ts := time.Now().Format("20060102_150405")
	filename := fmt.Sprintf("%s_%s_%s.xlsx", prefix, ts, operator)
	os.MkdirAll(ExportDir, 0o755)
	pruneOldExports()
	path := filepath.Join(ExportDir, filename)
	return path, filename, f.SaveAs(path)
}

func writeRows(f *excelize.File, sheet string, rows [][]interface{}) {
	for i, vals := range rows {
		for c, v := range vals {
			cell, _ := excelize.CoordinatesToCellName(c+1, i+3)
			f.SetCellValue(sheet, cell, v)
		}
	}
}

func buildExport(sheetName, title string, headers []string, rows [][]interface{},
	prefix, operator string, notes []string) (string, string, error) {
	f := excelize.NewFile()
	f.SetSheetName("Sheet1", sheetName)
	styleSheet(f, sheetName, title, headers)
	writeRows(f, sheetName, rows)
	styleData(f, sheetName, len(rows), len(headers))
	autoWidth(f, sheetName, len(headers), len(rows)+2)
	addNotes(f, notes)
	return saveWorkbook(f, prefix, operator)
}

func s(r Row, k string) string { return rowStr(r, k) }

// ---------------------------------------------------------------------------
// 1. 备案人员信息登记表（学历/学位/职称/职级 编码 → 中文）
// ---------------------------------------------------------------------------
func exportPersonnelInfo(operator, whereSQL string, params []interface{}, joined bool) (string, string, error) {
	// #4 一律经 personnel_filing 关联导出：只导出有备案引用的信息登记表，
	// 无引用的孤儿行永不外泄（GROUP BY 去重，避免一人多条备案时重复）。
	// joined 参数保留以兼容调用，实际行为恒为关联导出。
	sqlq := "SELECT pi.* FROM personnel_info pi JOIN personnel_filing pf ON pf.personnel_info_id = pi.id " +
		"WHERE 1=1 " + whereSQL + " GROUP BY pi.id ORDER BY pi.created_at DESC"
	rows, err := queryMaps(sqlq, params...)
	if err != nil {
		return "", "", err
	}
	dictMaps := map[string]map[string]string{}
	for _, cat := range []string{"education", "degree", "title", "rank"} {
		m := map[string]string{}
		for _, o := range getDictOptions(cat) {
			m[rowStr(o, "code")] = rowStr(o, "value")
		}
		dictMaps[cat] = m
	}
	dv := func(cat, code string) string {
		if code == "" {
			return ""
		}
		if v, ok := dictMaps[cat][code]; ok {
			return v
		}
		return code
	}
	var data [][]interface{}
	for _, r := range rows {
		data = append(data, []interface{}{
			s(r, "unit"), s(r, "department"), s(r, "name"), s(r, "gender"),
			s(r, "birth_date"), s(r, "id_number"), s(r, "work_start_date"),
			dv("education", s(r, "education")), dv("degree", s(r, "degree")),
			dv("title", s(r, "title")), dv("rank", s(r, "rank")),
			s(r, "political_status"), s(r, "party_join_date"), s(r, "position"),
		})
	}
	return buildExport("备案人员信息登记表", "备案人员信息登记表",
		[]string{"单位", "部门", "姓名", "性别", "出生日期", "身份证号", "参加工作日期",
			"学历", "学位", "职称", "职级", "政治面貌", "入党日期", "职务（岗位名称）"},
		data, "备案人员信息登记表", operator,
		[]string{"填表说明：", "1. 出生日期格式为YYYYMMDD，需与身份证号对应。",
			"2. 学历、学位、职称、职级、政治面貌从系统数据字典中选择。",
			"3. 中共党员/预备党员须填写入党日期。"})
}

// ---------------------------------------------------------------------------
// 2. 登记备案表
// ---------------------------------------------------------------------------
func exportPersonnelFiling(operator, whereSQL string, params []interface{}) (string, string, error) {
	rows, err := queryMaps("SELECT pf.* FROM personnel_filing pf "+
		"LEFT JOIN personnel_info pi ON pf.personnel_info_id = pi.id "+
		"WHERE 1=1 "+whereSQL+" ORDER BY pf.created_at DESC", params...)
	if err != nil {
		return "", "", err
	}
	var data [][]interface{}
	for _, r := range rows {
		status := "有效"
		if s(r, "status") != "active" {
			status = "已撤控"
		}
		data = append(data, []interface{}{
			s(r, "surname"), s(r, "given_name"), s(r, "gender"), s(r, "birth_date"),
			s(r, "id_number"), s(r, "residence"), s(r, "political_status"),
			s(r, "work_unit"), s(r, "position_or_title"), s(r, "supervisor_unit"),
			s(r, "tag"), s(r, "informed"), status, s(r, "remarks"),
		})
	}
	return buildExport("登记备案表", "因私事出国（境）人员登记备案表",
		[]string{"中文姓", "中文名", "性别", "出生日期", "身份证号", "户口所在地",
			"政治面貌", "工作单位", "职务（级）或职称", "人事主管单位", "标记", "已告知本人", "状态", "备注"},
		data, "登记备案表", operator,
		[]string{"填表说明：", "1. 姓与名分开填写，特别注意复姓人员。",
			"2. 出生日期格式为YYYYMMDD，生日需与身份证号对应。", "3. 工作单位请写全称。",
			"4. 职务/职称栏：处级领导填'处级'或'副处级'，副处级单位班子成员填'正科'，其他人员填'副高'或'正高'。",
			"5. 人事主管单位名称需与印章一致。",
			"6. 户口所在地填至区级，省份不加'省'字，江东区、鄞县统一为'鄞州区'。",
			"7. 标记：新增、更新。", "8. 已告知本人：是、否。"})
}

// ---------------------------------------------------------------------------
// 3. 证照登记表
// ---------------------------------------------------------------------------
func exportCertificates(operator, whereSQL string, params []interface{}) (string, string, error) {
	rows, err := queryMaps("SELECT * FROM certificates WHERE 1=1 "+whereSQL+" ORDER BY updated_at DESC", params...)
	if err != nil {
		return "", "", err
	}
	var data [][]interface{}
	for _, r := range rows {
		data = append(data, []interface{}{
			s(r, "unit"), s(r, "department"), s(r, "name"),
			s(r, "passport_no"), s(r, "passport_expiry"), s(r, "passport_submit_date"),
			s(r, "hm_pass_no"), s(r, "hm_pass_expiry"), s(r, "hm_pass_submit_date"),
			s(r, "tw_pass_no"), s(r, "tw_pass_expiry"), s(r, "tw_pass_submit_date"),
		})
	}
	return buildExport("证照登记表", "因私出国（境）备案人员证照登记表",
		[]string{"单位", "部门", "姓名", "护照证件号", "护照有效日期", "护照上交日期",
			"港澳通行证号", "港澳有效日期", "港澳上交日期", "台湾通行证号", "台湾有效日期", "台湾上交日期"},
		data, "证照登记表", operator,
		[]string{"填表说明：", "1. 日期格式均为YYYYMMDD。", "2. 无对应证件的列留空。"})
}

// ---------------------------------------------------------------------------
// 4. 出国明细表
// ---------------------------------------------------------------------------
func exportTravelDetails(operator, whereSQL string, params []interface{}) (string, string, error) {
	rows, err := queryMaps("SELECT * FROM travel_details WHERE 1=1 "+whereSQL+" ORDER BY created_at DESC", params...)
	if err != nil {
		return "", "", err
	}
	var data [][]interface{}
	for _, r := range rows {
		status := "正常"
		if s(r, "trip_status") == "cancelled" {
			status = "取消行程"
		}
		data = append(data, []interface{}{
			s(r, "unit"), s(r, "department"), s(r, "name"), s(r, "position"),
			s(r, "title"), s(r, "id_number"), s(r, "destination_passport"),
			s(r, "category"), s(r, "travel_dates"), s(r, "approval_date"),
			s(r, "need_new_passport"), s(r, "passport_no"),
			s(r, "passport_collect_date"), s(r, "actual_return_date"),
			s(r, "passport_return_date"), status, s(r, "cancel_date"),
		})
	}
	return buildExport("出国明细表", "因私出国（境）人员明细表",
		[]string{"单位", "部门", "姓名", "职务", "职称", "身份证号",
			"地点、证照", "类别", "计划出行日期", "批准日期",
			"是否做证", "证件号码", "证件领用日期", "实际回国日期",
			"证件归还日期", "行程状态", "取消日期"},
		data, "出国明细表", operator,
		[]string{"1. 计划出行日期格式：起始日期-结束日期，如 2023-6-20-2023-6-26。",
			"2. 附件需线下查看系统存储的PDF扫描件。"})
}

// ---------------------------------------------------------------------------
// 5. 撤控备案表
// ---------------------------------------------------------------------------
func exportDecontrol(operator, whereSQL string, params []interface{}) (string, string, error) {
	rows, err := queryMaps("SELECT * FROM decontrol_filing WHERE 1=1 "+whereSQL+" ORDER BY created_at DESC", params...)
	if err != nil {
		return "", "", err
	}
	var data [][]interface{}
	for _, r := range rows {
		data = append(data, []interface{}{
			s(r, "surname"), s(r, "given_name"), s(r, "gender"), s(r, "birth_date"),
			s(r, "id_number"), s(r, "residence"), s(r, "political_status"), s(r, "work_unit"),
			s(r, "supervisor_unit"), s(r, "submit_unit_name"), s(r, "submit_unit_type"),
			s(r, "submit_contact"), s(r, "submit_phone"), s(r, "batch_no"),
			s(r, "decontrol_date"), s(r, "cert_handover_date"), s(r, "reason"),
		})
	}
	return buildExport("撤控备案表", "因私事出国（境）人员撤控备案表",
		[]string{"中文姓", "中文名", "性别", "出生日期", "身份证号", "户口所在地", "政治面貌",
			"工作单位", "人事主管单位", "报送单位名称", "报送类别", "联系人", "联系电话",
			"入库批号", "撤控日期", "证件移交日期", "撤控原因"},
		data, "撤控备案表", operator,
		[]string{"1. 出生日期格式为YYYYMMDD，生日需与身份证号对应。",
			"2. 户口所在地填至区级，省份不加'省'字。",
			"3. 报送单位类别：党政机关,金融系统,教科文卫系统,国有大中型企业单位,其他单位。"})
}

// ---------------------------------------------------------------------------
// 6. 操作日志年度归档
// ---------------------------------------------------------------------------
func exportLogs(operator, year string) (string, string, error) {
	tz := fmt.Sprintf("+%d hours", TZOffsetHours)
	rows, err := queryMaps("SELECT * FROM operation_logs "+
		"WHERE strftime('%Y', datetime(created_at, ?)) = ? ORDER BY created_at", tz, year)
	if err != nil {
		return "", "", err
	}
	var data [][]interface{}
	for _, r := range rows {
		data = append(data, []interface{}{
			toLocalTime(r["created_at"], "%Y-%m-%d %H:%M:%S"), s(r, "operator"), s(r, "action"),
			s(r, "target_type"), r["target_id"], s(r, "detail"), s(r, "ip_address"), s(r, "snapshot"),
		})
	}
	return buildExport(year+"年操作日志", "操作日志归档（"+year+" 年）",
		[]string{"时间（本地）", "操作人", "动作", "对象类型", "对象ID", "详情", "IP", "变更快照(JSON)"},
		data, "操作日志归档_"+year+"年", operator,
		[]string{"1. 时间已按系统配置时区换算为本地时间。",
			"2. 本文件为审计归档副本；数据库中的日志不可删除，仍完整保留。"})
}

// ---------------------------------------------------------------------------
// 导入模板 + 批量导入解析
// ---------------------------------------------------------------------------
var importHeaders = []string{
	"单位", "部门", "姓名", "性别", "出生日期", "参加工作日期",
	"身份证号", "户口所在地", "政治面貌", "职务（级）或职称",
	"人事主管单位", "学历", "学位", "职称", "职级",
	"入党日期", "职务（岗位名称）", "标记", "已告知本人", "备注",
}

func generateImportTemplate() (*excelize.File, error) {
	f := excelize.NewFile()
	sheet := "备案人员导入模板"
	f.SetSheetName("Sheet1", sheet)
	headerStyle, _ := f.NewStyle(&excelize.Style{
		Font: &excelize.Font{Bold: true, Color: "FFFFFF"},
		Fill: excelize.Fill{Type: "pattern", Pattern: 1, Color: []string{"3A5A7C"}},
	})
	for i, h := range importHeaders {
		cell, _ := excelize.CoordinatesToCellName(i+1, 1)
		f.SetCellValue(sheet, cell, h)
	}
	end, _ := excelize.CoordinatesToCellName(len(importHeaders), 1)
	f.SetCellStyle(sheet, "A1", end, headerStyle)
	example := []interface{}{
		"XX单位", "XX部门", "张三", "男", "19800103", "20000701",
		"330102198001031230", "浙江杭州市西湖区", "中共党员", "处级",
		"人事处", "大学本科", "学士", "副高", "处级",
		"20050701", "处长", "新增", "是", "",
	}
	for i, v := range example {
		cell, _ := excelize.CoordinatesToCellName(i+1, 2)
		f.SetCellValue(sheet, cell, v)
	}
	widths := []float64{18, 14, 10, 6, 12, 12, 20, 22, 14, 18, 14, 12, 10, 10, 10, 12, 18, 8, 12, 20}
	for i, wd := range widths {
		col, _ := excelize.ColumnNumberToName(i + 1)
		f.SetColWidth(sheet, col, col, wd)
	}
	return f, nil
}

type ImportResult struct {
	Total   int
	Success int
	Errors  []Row
}

func parseImportFile(reader io.Reader, operator string) (*ImportResult, error) {
	f, err := excelize.OpenReader(reader)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	sheet := f.GetSheetName(0)
	all, err := f.GetRows(sheet)
	if err != nil {
		return nil, err
	}
	res := &ImportResult{}
	if len(all) <= 1 {
		return res, nil
	}
	dataRows := all[1:]
	res.Total = len(dataRows)

	cell := func(row []string, i int) string {
		if i < len(row) {
			return strings.TrimSpace(row[i])
		}
		return ""
	}
	for idx, row := range dataRows {
		rowNo := idx + 2
		empty := true
		for _, v := range row {
			if strings.TrimSpace(v) != "" {
				empty = false
				break
			}
		}
		if empty {
			res.Total--
			continue
		}
		data := map[string]string{
			"unit": cell(row, 0), "department": cell(row, 1), "name": cell(row, 2),
			"gender":          cell(row, 3),
			"birth_date":      parseDateInput(cell(row, 4)),
			"work_start_date": parseDateInput(cell(row, 5)),
			"id_number":       strings.ToUpper(cell(row, 6)),
			"residence":       cell(row, 7), "political_status": cell(row, 8),
			"position_or_title": cell(row, 9), "supervisor_unit": cell(row, 10),
			"education_code": cell(row, 11), "degree_code": cell(row, 12),
			"title_code": cell(row, 13), "rank_code": cell(row, 14),
			"party_join_date": parseDateInput(cell(row, 15)),
			"position":        cell(row, 16), "tag": cell(row, 17),
			"informed": cell(row, 18), "remarks": cell(row, 19),
		}
		rowErrs := validateImportRow(data)
		if len(rowErrs) > 0 {
			for _, e := range rowErrs {
				res.Errors = append(res.Errors, Row{"row": rowNo, "field": e[0], "message": e[1]})
			}
			continue
		}
		infoRes, err := db.Exec("INSERT INTO personnel_info (unit, department, name, gender, birth_date, "+
			"id_number, work_start_date, education, degree, title, rank, political_status, "+
			"party_join_date, position, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
			data["unit"], data["department"], data["name"], data["gender"],
			data["birth_date"], data["id_number"], data["work_start_date"], data["education_code"],
			data["degree_code"], data["title_code"], data["rank_code"],
			data["political_status"], data["party_join_date"], data["position"], operator)
		if err != nil {
			res.Errors = append(res.Errors, Row{"row": rowNo, "field": "—", "message": "数据库写入失败: " + err.Error()})
			continue
		}
		infoID := lastInsertID(infoRes)
		surname, givenName := detectSurnameSplit(data["name"])
		supervisor := data["supervisor_unit"]
		if supervisor == "" {
			supervisor = "人事处"
		}
		informed := data["informed"]
		if informed == "" {
			informed = "是"
		}
		_, err = db.Exec("INSERT INTO personnel_filing (personnel_info_id, surname, given_name, gender, "+
			"birth_date, id_number, residence, political_status, work_unit, "+
			"position_or_title, supervisor_unit, tag, informed, remarks, operator) "+
			"VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
			infoID, surname, givenName, data["gender"],
			data["birth_date"], data["id_number"], normalizeResidence(data["residence"]),
			data["political_status"], data["unit"], data["position_or_title"],
			supervisor, "新增", informed, data["remarks"], operator)
		if err != nil {
			res.Errors = append(res.Errors, Row{"row": rowNo, "field": "—", "message": "数据库写入失败: " + err.Error()})
			continue
		}
		res.Success++
	}
	return res, nil
}

func validateImportRow(data map[string]string) [][2]string {
	var errs [][2]string
	for _, f := range []fieldLabel{
		{"unit", "单位"}, {"department", "部门"}, {"name", "姓名"},
		{"gender", "性别"}, {"birth_date", "出生日期"}, {"id_number", "身份证号"},
		{"political_status", "政治面貌"}, {"position", "职务（岗位名称）"},
	} {
		if data[f.Field] == "" {
			errs = append(errs, [2]string{f.Label, f.Label + "为必填项"})
		}
	}
	if len(errs) > 0 {
		return errs
	}
	if ok, msg := validateDateFormat(data["birth_date"]); !ok {
		errs = append(errs, [2]string{"出生日期", msg})
		return errs
	}
	if ok, msg := validateIDNumber(data["id_number"]); !ok {
		errs = append(errs, [2]string{"身份证号", msg})
		return errs
	}
	if ok, _ := validateBirthDateMatch(data["id_number"], data["birth_date"]); !ok {
		errs = append(errs, [2]string{"出生日期/身份证号",
			"出生日期与身份证号不一致（身份证中为 " + data["id_number"][6:14] + "）。"})
		return errs
	}
	if ok, msg := validateGenderMatch(data["id_number"], data["gender"]); !ok {
		errs = append(errs, [2]string{"性别", msg})
	}
	if queryOne("SELECT id FROM personnel_filing WHERE id_number = ? AND status = 'active'", data["id_number"]) != nil {
		errs = append(errs, [2]string{"身份证号", "系统中已存在有效备案记录"})
	}
	return errs
}

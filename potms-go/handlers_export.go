// 导出 / 打印 / 导入 处理器
package main

import (
	"fmt"
	"net/http"
	"strings"
)

func selectedIDs(r *http.Request) []int64 {
	var out []int64
	for _, x := range strings.Split(r.URL.Query().Get("ids"), ",") {
		x = strings.TrimSpace(x)
		if x != "" && digitsOnly.MatchString(x) {
			out = append(out, toInt64(x))
		}
	}
	return out
}

func scopeNote(whereSQL string, ids []int64) string {
	if len(ids) > 0 {
		return fmt.Sprintf("选中%d行", len(ids))
	}
	if whereSQL != "" {
		return "按筛选条件"
	}
	return "全量"
}

type exportSpec struct {
	filters func(map[string]string, []int64) (string, []interface{})
	export  func(string, string, []interface{}) (string, string, error)
	target  string
	backEP  string
}

func doExport(w http.ResponseWriter, r *http.Request, spec exportSpec) {
	ids := selectedIDs(r)
	where, params := spec.filters(queryArgs(r), ids)
	path, filename, err := spec.export(sessionUser(r), where, params)
	if err != nil {
		flashMsg(w, r, "导出失败: "+err.Error(), "danger")
		redirect(w, r, spec.backEP, nil)
		return
	}
	logAction(r, "export", spec.target, nil, filename+"（"+scopeNote(where, ids)+"）", nil, nil)
	sendFile(w, r, path, filename)
}

func handleExportInfo(w http.ResponseWriter, r *http.Request) {
	ids := selectedIDs(r)
	where, params := personnelFilters(queryArgs(r), ids)
	path, filename, err := exportPersonnelInfo(sessionUser(r), where, params, where != "")
	if err != nil {
		flashMsg(w, r, "导出失败: "+err.Error(), "danger")
		redirect(w, r, "personnel.list", nil)
		return
	}
	logAction(r, "export", "personnel_info", nil, filename+"（"+scopeNote(where, ids)+"）", nil, nil)
	sendFile(w, r, path, filename)
}

func handleExportFiling(w http.ResponseWriter, r *http.Request) {
	doExport(w, r, exportSpec{personnelFilters, exportPersonnelFiling, "personnel_filing", "personnel.list"})
}

func handleExportCertificate(w http.ResponseWriter, r *http.Request) {
	doExport(w, r, exportSpec{
		func(q map[string]string, ids []int64) (string, []interface{}) { return certificateFilters(q, ids) },
		exportCertificates, "certificates", "certificate.list"})
}

func handleExportTravel(w http.ResponseWriter, r *http.Request) {
	doExport(w, r, exportSpec{travelFilters, exportTravelDetails, "travel_details", "travel.list"})
}

func handleExportDecontrol(w http.ResponseWriter, r *http.Request) {
	doExport(w, r, exportSpec{decontrolFilters, exportDecontrol, "decontrol_filing", "decontrol.list"})
}

// ---------------------------------------------------------------------------
// 在线打印 / 批量打印
// ---------------------------------------------------------------------------
var printTables = map[string][2]string{
	"info":        {"personnel_info", "备案人员信息登记表"},
	"filing":      {"personnel_filing", "因私事出国（境）人员登记备案表"},
	"certificate": {"certificates", "因私出国（境）备案人员证照登记表"},
	"travel":      {"travel_details", "因私出国（境）人员明细表"},
	"decontrol":   {"decontrol_filing", "因私事出国（境）人员撤控备案表"},
}

var printBackEP = map[string]string{
	"info": "personnel.list", "filing": "personnel.list", "certificate": "certificate.list",
	"travel": "travel.list", "decontrol": "decontrol.list",
}

func handlePrintView(w http.ResponseWriter, r *http.Request) {
	printType := r.PathValue("print_type")
	id := toInt64(r.PathValue("id"))
	spec, ok := printTables[printType]
	if !ok {
		flashMsg(w, r, "不支持的打印类型。", "danger")
		redirect(w, r, "dashboard.index", nil)
		return
	}
	row := queryOne("SELECT * FROM "+spec[0]+" WHERE id = ?", id)
	if row == nil {
		flashMsg(w, r, "记录不存在。", "danger")
		redirect(w, r, printBackEP[printType], nil)
		return
	}
	data := Row{"title": spec[1], "row": row, "mode": printType}
	if printType == "filing" && row["personnel_info_id"] != nil {
		data["info"] = queryOne("SELECT * FROM personnel_info WHERE id = ?", row["personnel_info_id"])
	}
	render(w, r, "export/print.html", data)
}

func handleBatchPrint(w http.ResponseWriter, r *http.Request) {
	printType := r.PathValue("print_type")
	ids := selectedIDs(r)
	if len(ids) == 0 {
		flashMsg(w, r, "请选择要打印的记录。", "warning")
		redirect(w, r, "dashboard.index", nil)
		return
	}
	spec, ok := printTables[printType]
	if !ok {
		flashMsg(w, r, "不支持的打印类型。", "danger")
		redirect(w, r, "dashboard.index", nil)
		return
	}
	args := make([]interface{}, len(ids))
	for i, id := range ids {
		args[i] = id
	}
	rows, _ := queryMaps("SELECT * FROM "+spec[0]+" WHERE id IN ("+placeholders(len(ids))+") ORDER BY id", args...)
	render(w, r, "export/batch_print.html", Row{
		"title": spec[1], "rows": rowsIface(rows), "mode": printType, "total": len(rows),
	})
}

// ---------------------------------------------------------------------------
// 批量导入
// ---------------------------------------------------------------------------
func handleImport(w http.ResponseWriter, r *http.Request) {
	var result interface{}
	if r.Method == http.MethodPost {
		r.ParseMultipartForm(int64(MaxContentLength))
		file, header, err := r.FormFile("file")
		if err != nil || header.Filename == "" {
			flashMsg(w, r, "请选择要上传的文件。", "warning")
			render(w, r, "import/form.html", Row{"result": nil})
			return
		}
		defer file.Close()
		lower := strings.ToLower(header.Filename)
		if !strings.HasSuffix(lower, ".xlsx") && !strings.HasSuffix(lower, ".xls") {
			flashMsg(w, r, "仅支持 .xlsx 格式的 Excel 文件。", "danger")
			render(w, r, "import/form.html", Row{"result": nil})
			return
		}
		res, err := parseImportFile(file, sessionUser(r))
		if err != nil {
			flashMsg(w, r, "导入失败: "+err.Error(), "danger")
			render(w, r, "import/form.html", Row{"result": nil})
			return
		}
		logAction(r, "import", "batch", nil,
			fmt.Sprintf("total=%d, success=%d, errors=%d", res.Total, res.Success, len(res.Errors)), nil, nil)
		if res.Success > 0 {
			flashMsg(w, r, fmt.Sprintf("成功导入 %d 条记录（共 %d 条）。", res.Success, res.Total), "success")
		}
		if len(res.Errors) > 0 {
			flashMsg(w, r, fmt.Sprintf("%d 条记录存在错误，详见下方报告。", len(res.Errors)), "warning")
		}
		result = Row{
			"total": res.Total, "success": res.Success, "errors": rowsIface(res.Errors),
		}
	}
	render(w, r, "import/form.html", Row{"result": result})
}

func handleImportTemplate(w http.ResponseWriter, r *http.Request) {
	f, err := generateImportTemplate()
	if err != nil {
		serverError(w, r)
		return
	}
	w.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
	w.Header().Set("Content-Disposition", `attachment; filename*=UTF-8''`+urlPathEscape("备案人员导入模板.xlsx"))
	f.Write(w)
}

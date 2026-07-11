// 辅助函数 — 对应 Python 版 utils/helpers.py
package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
)

// ---------------------------------------------------------------------------
// 时间：store UTC / display local
// ---------------------------------------------------------------------------
func toLocalTime(value interface{}, format string) string {
	if value == nil {
		return ""
	}
	s := strings.TrimSpace(fmt.Sprintf("%v", value))
	if s == "" {
		return ""
	}
	s = strings.Replace(s, "T", " ", 1)
	if i := strings.Index(s, "."); i > 0 {
		s = s[:i]
	}
	if len(s) > 19 {
		s = s[:19]
	}
	t, err := time.Parse("2006-01-02 15:04:05", s)
	if err != nil {
		return fmt.Sprintf("%v", value) // 非预期格式原样返回
	}
	local := t.Add(time.Duration(TZOffsetHours) * time.Hour)
	// Python strftime 风格 → Go layout
	layout := strings.NewReplacer(
		"%Y", "2006", "%m", "01", "%d", "02",
		"%H", "15", "%M", "04", "%S", "05",
	).Replace(format)
	return local.Format(layout)
}

func nowLocalYMD() string { return time.Now().Format("20060102") }

// ---------------------------------------------------------------------------
// 复姓 / 户口
// ---------------------------------------------------------------------------
var compoundSurnames = []string{
	"欧阳", "司马", "上官", "诸葛", "令狐", "慕容", "独孤", "拓跋",
	"尉迟", "呼延", "端木", "皇甫", "东方", "南宫", "夏侯", "宇文",
	"长孙", "公孙", "闾丘", "亓官", "司寇", "巫马", "公西", "壤驷",
	"乐正", "公良", "季孙", "仲孙", "宰父", "谷梁", "段干", "百里",
	"东郭", "南门", "羊舌", "微生", "梁丘", "左丘", "西门", "第五",
}

func detectSurnameSplit(full string) (string, string) {
	rs := []rune(full)
	if len(rs) < 2 {
		return full, ""
	}
	head := string(rs[:2])
	for _, cs := range compoundSurnames {
		if head == cs {
			return head, string(rs[2:])
		}
	}
	return string(rs[:1]), string(rs[1:])
}

func normalizeResidence(raw string) string {
	raw = strings.TrimSpace(raw)
	raw = strings.ReplaceAll(raw, "省", "")
	raw = strings.ReplaceAll(raw, "江东区", "鄞州区")
	raw = strings.ReplaceAll(raw, "鄞县", "鄞州区")
	return raw
}

// ---------------------------------------------------------------------------
// 操作日志（含变更前后快照）
// ---------------------------------------------------------------------------
var snapshotSkip = map[string]bool{"created_at": true, "updated_at": true}

func cleanSnapshot(data Row) Row {
	if data == nil {
		return nil
	}
	out := Row{}
	for k, v := range data {
		if !snapshotSkip[k] {
			out[k] = v
		}
	}
	return out
}

// snapshotTables 表名白名单（防动态表名注入）
var snapshotTables = map[string]bool{
	"personnel_info": true, "personnel_filing": true, "certificates": true,
	"travel_details": true, "decontrol_filing": true, "sys_dict": true,
	"sys_org": true, "sys_submit_unit": true,
}

func rowSnapshot(table string, id int64) Row {
	if !snapshotTables[table] {
		panic("rowSnapshot: 不允许的表名 " + table)
	}
	return queryOne("SELECT * FROM "+table+" WHERE id = ?", id)
}

func logAction(r *http.Request, action, targetType string, targetID interface{}, detail string, before, after Row) {
	var snapshot interface{}
	if before != nil || after != nil {
		b, _ := json.Marshal(map[string]interface{}{
			"before": cleanSnapshot(before), "after": cleanSnapshot(after),
		})
		snapshot = string(b)
	}
	operator := "unknown"
	ip := ""
	if r != nil {
		if s := getSession(r); s != nil {
			if u, ok := s["username"].(string); ok {
				operator = u
			}
		}
		ip = clientIP(r)
	}
	var det interface{}
	if detail != "" {
		det = detail
	}
	db.Exec("INSERT INTO operation_logs (operator, action, target_type, target_id, detail, ip_address, snapshot, created_at) "+
		"VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
		operator, action, targetType, targetID, det, ip, snapshot,
		time.Now().UTC().Format("2006-01-02 15:04:05"))
}

func clientIP(r *http.Request) string {
	host := r.RemoteAddr
	if i := strings.LastIndex(host, ":"); i > 0 {
		host = host[:i]
	}
	return host
}

// ---------------------------------------------------------------------------
// 字典 / 组织 / 报送单位 / 人员选项（模板全局函数的数据源）
// ---------------------------------------------------------------------------
func getDictOptions(category string) []Row {
	rows, _ := queryMaps("SELECT code, value FROM sys_dict WHERE category = ? ORDER BY sort_order", category)
	return rows
}

func getDictValue(category, code string) string {
	if code == "" {
		return code
	}
	r := queryOne("SELECT value FROM sys_dict WHERE category = ? AND code = ?", category, code)
	if r == nil {
		return code
	}
	return rowStr(r, "value")
}

// getOrgFlat 组织节点先序遍历，含 depth/root_id/indent（树状级联用）
func getOrgFlat() []Row {
	rows, _ := queryMaps("SELECT id, name, parent_id FROM sys_org ORDER BY sort_order, id")
	children := map[int64][]Row{}
	for _, r := range rows {
		pid := toInt64(r["parent_id"])
		children[pid] = append(children[pid], r)
	}
	var out []Row
	var dfs func(parentID int64, depth int, rootID int64)
	dfs = func(parentID int64, depth int, rootID int64) {
		for _, r := range children[parentID] {
			rid := toInt64(r["id"])
			thisRoot := rootID
			if depth == 0 {
				thisRoot = rid
			}
			indent := ""
			if depth >= 1 {
				indent = strings.Repeat("　", depth-1) + "└ "
			}
			out = append(out, Row{
				"id": rid, "name": r["name"], "parent_id": pidOf(r),
				"depth": depth, "root_id": thisRoot, "indent": indent,
			})
			dfs(rid, depth+1, thisRoot)
		}
	}
	dfs(0, 0, 0)
	return out
}

func pidOf(r Row) int64 { return toInt64(r["parent_id"]) }

// getOrgTreeOptions 树形下拉（含缩进前缀，供 filing_form 使用）
func getOrgTreeOptions() []Row {
	rows, _ := queryMaps("SELECT id, name, parent_id FROM sys_org ORDER BY parent_id, sort_order")
	var out []Row
	var build func(parentID int64, depth int)
	build = func(parentID int64, depth int) {
		for _, o := range rows {
			if toInt64(o["parent_id"]) == parentID {
				prefix := ""
				if depth > 0 {
					prefix = strings.Repeat("　", depth) + "└ "
				}
				out = append(out, Row{"id": o["id"], "name": prefix + rowStr(o, "name")})
				build(toInt64(o["id"]), depth+1)
			}
		}
	}
	build(0, 0)
	return out
}

func getOrgChildren(parentID int64) []Row {
	rows, _ := queryMaps("SELECT id, name FROM sys_org WHERE parent_id = ? ORDER BY sort_order", parentID)
	return rows
}

func getSubmitUnits() []Row {
	rows, _ := queryMaps("SELECT id, name, contact, phone FROM sys_submit_unit ORDER BY sort_order, name")
	for _, r := range rows {
		if r["contact"] == nil {
			r["contact"] = ""
		}
		if r["phone"] == nil {
			r["phone"] = ""
		}
	}
	return rows
}

// getPersonnelOptions 有效备案人员下拉（含证件号候选）
func getPersonnelOptions() []Row {
	rows, _ := queryMaps(
		"SELECT pf.id, pf.surname, pf.given_name, pf.work_unit, pf.id_number, pf.position_or_title, " +
			"COALESCE(pi.department, '') AS department, " +
			"(SELECT value FROM sys_dict WHERE category = 'title' AND code = pi.title) AS title_val " +
			"FROM personnel_filing pf LEFT JOIN personnel_info pi ON pf.personnel_info_id = pi.id " +
			"WHERE pf.status = 'active' ORDER BY pf.surname, pf.given_name")
	certRows, _ := queryMaps("SELECT personnel_filing_id, passport_no, hm_pass_no, tw_pass_no FROM certificates")
	certMap := map[int64][]string{}
	for _, cr := range certRows {
		pid := toInt64(cr["personnel_filing_id"])
		for _, k := range []string{"passport_no", "hm_pass_no", "tw_pass_no"} {
			v := strings.TrimSpace(rowStr(cr, k))
			if v != "" && !containsStr(certMap[pid], v) {
				certMap[pid] = append(certMap[pid], v)
			}
		}
	}
	var out []Row
	for _, r := range rows {
		name := rowStr(r, "surname") + rowStr(r, "given_name")
		title := rowStr(r, "title_val")
		out = append(out, Row{
			"id": r["id"], "name": name,
			"full_name": fmt.Sprintf("%s (%s)", name, rowStr(r, "work_unit")),
			"unit":      r["work_unit"], "department": r["department"],
			"id_number": r["id_number"], "position": r["position_or_title"],
			"title":    title,
			"cert_nos": certMap[toInt64(r["id"])],
		})
	}
	return out
}

func containsStr(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

func toInt64(v interface{}) int64 {
	switch n := v.(type) {
	case int64:
		return n
	case int:
		return int64(n)
	case float64:
		return int64(n)
	case string:
		var x int64
		fmt.Sscanf(n, "%d", &x)
		return x
	}
	return 0
}

// ---------------------------------------------------------------------------
// 分页结构（前端窗口化：全量下发 pages=1；日志页服务端分页）
// ---------------------------------------------------------------------------
type PageResult struct {
	Rows    []Row
	Page    int
	Total   int
	Pages   int
	HasPrev bool
	HasNext bool
	PerPage int
}

// pageMap 转为模板可用 map（属性名与 Python 版一致）
func (p PageResult) pageMap() Row {
	rows := make([]interface{}, len(p.Rows))
	for i, r := range p.Rows {
		rows[i] = r
	}
	return Row{
		"rows": rows, "page": p.Page, "total": p.Total, "pages": p.Pages,
		"has_prev": p.HasPrev, "has_next": p.HasNext, "per_page": p.PerPage,
	}
}

func listAll(query string, args ...interface{}) PageResult {
	rows, _ := queryMaps(query, args...)
	total := len(rows)
	per := total
	if per == 0 {
		per = 1
	}
	return PageResult{Rows: rows, Page: 1, Total: total, Pages: 1, PerPage: per}
}

func paginate(query string, args []interface{}, page, perPage int) PageResult {
	total := int(countQuery("SELECT COUNT(*) FROM ("+query+") AS _cnt", args...))
	pages := (total + perPage - 1) / perPage
	if pages < 1 {
		pages = 1
	}
	if page < 1 {
		page = 1
	}
	if page > pages {
		page = pages
	}
	offset := (page - 1) * perPage
	rows, _ := queryMaps(fmt.Sprintf("%s LIMIT %d OFFSET %d", query, perPage, offset), args...)
	return PageResult{
		Rows: rows, Page: page, Total: total, Pages: pages,
		HasPrev: page > 1, HasNext: page < pages, PerPage: perPage,
	}
}

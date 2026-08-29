// 历史回填的证件种类：三级推断、存量订正、待核实呈现、人工更正。
//
// 原先回填一律把 cert_types 写成 '01'（普通护照）——往来港澳通行证、大陆居民往来
// 台湾通行证全被标成护照。领用凭证是要归档的，错的种类比空着更糟。
//
// 五版共用同一个 data.db，本版必须与 Python 版同口径：改对回填还不够，
// 回填带幂等守卫，已经回填过的库要靠独立的订正迁移才能纠正。
package main

import (
	"net/url"
	"strings"
	"testing"
)

// 每个人的持证情况与出行记录，以及应当被推断出的种类。
var certTypeCases = []struct {
	name    string
	slot    string // certificates 表里填哪一列
	certNo  string
	travNo  string // 出行表填的证件号（空表示没填）
	dest    string // 「地点、证照」
	want    string
}{
	{"张三", "passport_no", "E12345678", "E12345678", "美国-护照", "01"},
	{"李四", "hm_pass_no", "C87654321", "C87654321", "香港", "02"},
	{"王五", "tw_pass_no", "T11112222", "T11112222", "台湾", "03"},
	{"赵六", "hm_pass_no", "C40000001", "", "澳门/港澳通行证", "02"},
	{"孙七", "passport_no", "E55556666", "", "泰国", "01"},
}

// seedLegacy 造一个「升级前」的库：出行表已有领用日期。
// withIssuance=true 时先把错标的领用记录塞进去，模拟已被老版本回填过的存量库。
func seedLegacy(t *testing.T, withIssuance bool) {
	t.Helper()
	for i, c := range certTypeCases {
		id := i + 1
		mustExecT(t, "INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"+
			"id_number,residence,political_status,work_unit,position_or_title,supervisor_unit,"+
			"operator) VALUES (?,?,'','男','19900101',?,'北京','群众','总部','科长','人事处','admin')",
			id, c.name, testID)
		mustExecT(t, "INSERT INTO certificates (personnel_filing_id,unit,department,name,"+
			c.slot+",operator) VALUES (?,'总部','技术部',?,?,'admin')", id, c.name, c.certNo)
		mustExecT(t, "INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"+
			"position,id_number,destination_passport,category,travel_dates,need_new_passport,"+
			"passport_no,passport_collect_date,operator) VALUES "+
			"(?,?,'总部','技术部',?,'科长',?,?,'旅游','2026/03/01-2026/03/10','否',?,'20260225','admin')",
			id, id, c.name, testID, c.dest, c.travNo)
		if withIssuance {
			mustExecT(t, "INSERT INTO cert_issuance (id,travel_id,personnel_filing_id,holder_name,"+
				"id_number,cert_types,cert_nos,issue_date,issuer,status,remarks,operator) "+
				"VALUES (?,?,?,?,?,'01',?,'20260225','admin','issued',?,'admin')",
				id, id, id, c.name, testID, c.travNo, backfillRemarkLegacy)
		}
	}
}

func mustExecT(t *testing.T, q string, args ...interface{}) {
	t.Helper()
	if _, err := db.Exec(q, args...); err != nil {
		t.Fatalf("造数失败: %v\n%s", err, q)
	}
}

// storedTypes 取每个人当前的 cert_types。
func storedTypes(t *testing.T) map[string]string {
	t.Helper()
	out := map[string]string{}
	rows, err := queryMaps("SELECT holder_name, cert_types FROM cert_issuance")
	if err != nil {
		t.Fatalf("查询失败: %v", err)
	}
	for _, r := range rows {
		out[rowStr(r, "holder_name")] = rowStr(r, "cert_types")
	}
	return out
}

func wantTypes() map[string]string {
	m := map[string]string{}
	for _, c := range certTypeCases {
		m[c.name] = c.want
	}
	return m
}

func assertTypes(t *testing.T, got, want map[string]string) {
	t.Helper()
	for name, w := range want {
		if got[name] != w {
			t.Errorf("%s 的证件种类：得到 %q，应为 %q", name, got[name], w)
		}
	}
}

// ---------------------------------------------------------------------------
// 回填本身（从没回填过的库）
// ---------------------------------------------------------------------------
func TestBackfillInfersRealCertType(t *testing.T) {
	newTestApp(t)
	seedLegacy(t, false)
	backfillLegacyIssuance()
	assertTypes(t, storedTypes(t), wantTypes())
}

func TestBackfillMarksUndeterminableAsPending(t *testing.T) {
	newTestApp(t)
	seedLegacy(t, false)
	// 三本证都有、出行表没填号码、文字里也没写证件名——数据里确实没有信息
	mustExecT(t, "INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"+
		"id_number,residence,political_status,work_unit,position_or_title,supervisor_unit,operator) "+
		"VALUES (9,'周','八','男','19900101',?,'北京','群众','总部','科长','人事处','admin')", testID)
	mustExecT(t, "INSERT INTO certificates (personnel_filing_id,unit,department,name,"+
		"passport_no,hm_pass_no,tw_pass_no,operator) VALUES (9,'总部','技术部','周八','E9','C9','T9','admin')")
	mustExecT(t, "INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"+
		"id_number,destination_passport,category,travel_dates,need_new_passport,"+
		"passport_collect_date,operator) VALUES "+
		"(9,9,'总部','技术部','周八','科长',?,'新加坡','旅游','2026/03/01-2026/03/10','否','20260225','admin')",
		testID)
	backfillLegacyIssuance()

	got := storedTypes(t)
	if got["周八"] != "" {
		t.Errorf("判不出的应留空，得到 %q", got["周八"])
	}
	rm := rowStr(queryOne("SELECT remarks FROM cert_issuance WHERE holder_name='周八'"), "remarks")
	if rm != backfillRemarkPending {
		t.Errorf("备注应为待核实，得到 %q", rm)
	}
	rm = rowStr(queryOne("SELECT remarks FROM cert_issuance WHERE holder_name='李四'"), "remarks")
	if rm != backfillRemarkInferred {
		t.Errorf("判出来的备注应为据证照登记推定，得到 %q", rm)
	}
}

// ---------------------------------------------------------------------------
// 存量订正（已经被老版本回填过的库）
// ---------------------------------------------------------------------------
func TestCorrectionFixesExistingRows(t *testing.T) {
	newTestApp(t)
	seedLegacy(t, true)
	// 前置条件：全是错的
	for name, ct := range storedTypes(t) {
		if ct != "01" {
			t.Fatalf("前置条件不成立，%s 的种类是 %q", name, ct)
		}
	}
	// 光改回填没用——回填有幂等守卫，存量错标行不会被重算。必须有独立的订正。
	backfillLegacyIssuance()
	assertTypes(t, storedTypes(t), wantTypes())
}

func TestCorrectionIsIdempotent(t *testing.T) {
	newTestApp(t)
	seedLegacy(t, true)
	backfillLegacyIssuance()
	first := storedTypes(t)

	backfillLegacyIssuance()
	backfillLegacyIssuance()
	assertTypes(t, storedTypes(t), first)

	// 只比对结果不够：备注若没换掉，每次启动都会重跑、重复备份、重复写日志，
	// 而结果恰好相同，比对不出来。直接数日志条数。
	n := countQuery("SELECT COUNT(*) FROM operation_logs WHERE action='migrate' " +
		"AND target_type='cert_issuance'")
	if n != 1 {
		t.Errorf("订正跑了 3 次，日志攒了 %d 条——幂等守卫没生效", n)
	}
}

func TestCorrectionNeverTouchesSignedRecords(t *testing.T) {
	newTestApp(t)
	seedLegacy(t, true)
	// 把李四那条伪装成「有签名但备注恰好也是旧串」的极端情形
	mustExecT(t, "UPDATE cert_issuance SET sign_image = ? WHERE holder_name = '李四'",
		[]byte("\x89PNG"))
	backfillLegacyIssuance()

	got := storedTypes(t)
	if got["李四"] != "01" {
		t.Errorf("有签名的记录不该被订正改动，得到 %q", got["李四"])
	}
	if got["王五"] != "03" {
		t.Errorf("无签名的记录应照常订正，得到 %q", got["王五"])
	}
}

func TestCorrectionLogsSummary(t *testing.T) {
	newTestApp(t)
	seedLegacy(t, true)
	backfillLegacyIssuance()
	detail := rowStr(queryOne("SELECT detail FROM operation_logs WHERE action='migrate' "+
		"AND target_type='cert_issuance'"), "detail")
	if !strings.Contains(detail, "共 5 条") || !strings.Contains(detail, "推定 5 条") {
		t.Errorf("订正日志内容不对：%q", detail)
	}
}

// ---------------------------------------------------------------------------
// 待核实呈现与人工更正 —— 没有更正入口，「待核实」就是永远填不上的死数据
// ---------------------------------------------------------------------------

// seedPending 造一条判不出种类的回填记录，返回其 id。
func seedPending(t *testing.T, c *client) string {
	t.Helper()
	mustExecT(t, "INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"+
		"id_number,residence,political_status,work_unit,position_or_title,supervisor_unit,operator) "+
		"VALUES (9,'周','八','男','19900101',?,'北京','群众','总部','科长','人事处','admin')", testID)
	mustExecT(t, "INSERT INTO certificates (personnel_filing_id,unit,department,name,"+
		"passport_no,hm_pass_no,tw_pass_no,operator) VALUES (9,'总部','技术部','周八','E9','C9','T9','admin')")
	mustExecT(t, "INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"+
		"id_number,destination_passport,category,travel_dates,need_new_passport,"+
		"passport_collect_date,operator) VALUES "+
		"(9,9,'总部','技术部','周八','科长',?,'新加坡','旅游','2026/03/01-2026/03/10','否','20260225','admin')",
		testID)
	backfillLegacyIssuance()
	return rowStr(queryOne("SELECT id FROM cert_issuance WHERE holder_name='周八'"), "id")
}

func TestPendingShownAndFilterable(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedPending(t, c)

	_, body := c.get("/issuance/?cert_type=pending")
	if !strings.Contains(body, "周八") {
		t.Error("待核实筛选没有筛出该记录")
	}
	if !strings.Contains(body, "待核实") {
		t.Error("列表上没有「待核实」徽章")
	}
	// 现有筛选是 (','||cert_types||',') LIKE '%,01,%'，对空值恒不匹配；
	// 筛不出来这批待办就没法收口。
	_, body = c.get("/issuance/?cert_type=01")
	if strings.Contains(body, "周八") {
		t.Error("按 01 筛选不该出现待核实的记录")
	}
}

func TestPendingRowCanBeCorrected(t *testing.T) {
	c := newTestApp(t)
	c.login()
	id := seedPending(t, c)

	resp, body := c.post("/issuance/"+id+"/cert-types", url.Values{
		"csrf_token": {c.csrf("/issuance/" + id)}, "cert_types": {"02"},
	})
	if resp.StatusCode != 302 {
		t.Fatalf("更正失败: %d %s", resp.StatusCode, snippet(body))
	}
	got := rowStr(queryOne("SELECT cert_types FROM cert_issuance WHERE id=?", id), "cert_types")
	if got != "02" {
		t.Errorf("更正后应为 02，得到 %q", got)
	}
	rm := rowStr(queryOne("SELECT remarks FROM cert_issuance WHERE id=?", id), "remarks")
	if !strings.Contains(rm, "人工核定") {
		t.Errorf("备注应改为人工核定，得到 %q", rm)
	}
}

func TestCorrectionRejectedOnSignedRecord(t *testing.T) {
	c := newTestApp(t)
	c.login()
	id := seedPending(t, c)
	mustExecT(t, "UPDATE cert_issuance SET sign_image=? WHERE id=?", []byte("\x89PNG"), id)

	c.post("/issuance/"+id+"/cert-types", url.Values{
		"csrf_token": {c.csrf("/issuance/" + id)}, "cert_types": {"02"},
	})
	got := rowStr(queryOne("SELECT cert_types FROM cert_issuance WHERE id=?", id), "cert_types")
	if got != "" {
		t.Errorf("有签名的记录不该被改动，得到 %q", got)
	}
}

func TestCorrectionRejectsInvalidAndMulti(t *testing.T) {
	c := newTestApp(t)
	c.login()
	id := seedPending(t, c)

	for _, tc := range []struct{ label string; v url.Values }{
		{"非法代码", url.Values{"cert_types": {"99"}}},
		{"空选", url.Values{}},
		{"多选", url.Values{"cert_types": {"01", "02"}}},
	} {
		form := url.Values{"csrf_token": {c.csrf("/issuance/" + id)}}
		for k, vs := range tc.v {
			form[k] = vs
		}
		c.post("/issuance/"+id+"/cert-types", form)
		if got := rowStr(queryOne("SELECT cert_types FROM cert_issuance WHERE id=?", id),
			"cert_types"); got != "" {
			t.Errorf("%s 应被挡回，但记录被改成了 %q", tc.label, got)
		}
	}
}

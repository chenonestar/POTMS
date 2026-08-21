// 证件领用 REQ-012 的端到端用例：领用 → 归还 → 作废，以及签名的三条口径。
//
// 模板是从 Python 版原样拷过来的，gonja 与 Jinja2 的差异（`or` 在 nil 上的行为、
// 过滤器可用性、url_for 端点是否登记）只有真渲染一遍才会暴露，所以这里全部走 HTTP。
package main

import (
	"net/url"
	"strings"
	"testing"
)

// 1×1 白色 PNG 的 dataURL；签名校验只看魔数与大小
const pngDataURL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ" +
	"AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

// newIssuance 造一条领用记录，返回其 id。
func newIssuance(t *testing.T, c *client, sign string) string {
	t.Helper()
	form := url.Values{
		"csrf_token": {c.csrf("/issuance/new")}, "personnel_filing_id": {"1"},
		"holder_name": {"张三"}, "id_number": {testID}, "cert_types": {"01"},
		"cert_nos": {"E12345678"}, "issue_date": {"20260801"}, "sign_png": {sign},
	}
	resp, body := c.post("/issuance/new", form)
	if resp.StatusCode != 302 {
		t.Fatalf("领用登记失败: %d %s", resp.StatusCode, snippet(body))
	}
	loc := resp.Header.Get("Location")
	return loc[strings.LastIndex(loc, "/")+1:]
}

func TestIssuancePagesRender(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	id := newIssuance(t, c, pngDataURL)

	for _, path := range []string{
		"/issuance/", "/issuance/?status=issued", "/issuance/?cert_type=01",
		"/issuance/?search=" + url.QueryEscape("张三"),
		"/issuance/new", "/issuance/new?travel_id=1",
		"/issuance/" + id, "/issuance/" + id + "/return",
		"/print/issuance/" + id,
	} {
		resp, body := c.get(path)
		if resp.StatusCode >= 500 {
			t.Errorf("GET %s → %d\n%s", path, resp.StatusCode, snippet(body))
		}
	}
}

func TestIssuanceCreateStoresSignature(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	id := newIssuance(t, c, pngDataURL)

	var status, types string
	var blob []byte
	db.QueryRow("SELECT status, cert_types, sign_image FROM cert_issuance WHERE id = ?", id).
		Scan(&status, &types, &blob)
	if status != "issued" || types != "01" {
		t.Errorf("状态/证件种类不对: %q %q", status, types)
	}
	if len(blob) < 8 || string(blob[1:4]) != "PNG" {
		t.Errorf("签名未按 PNG 存入：%d 字节", len(blob))
	}

	// 领用日期要回写到出行表（本模块是唯一写入方）
	_, body := c.get("/issuance/" + id)
	if !strings.Contains(body, "signature.png") {
		t.Error("详情页未呈现签名图")
	}
}

func TestIssuanceRejectsBadSignature(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)

	for _, tc := range []struct{ sign, want string }{
		{"", "请手写签名后再提交"},
		{"data:image/jpeg;base64,AAAA", "签名数据格式不正确"},
		{"data:image/png;base64,!!!", "签名数据解析失败"},
		{"data:image/png;base64,QUJDRA==", "不是有效的 PNG 图像"},
	} {
		resp, body := c.post("/issuance/new", url.Values{
			"csrf_token": {c.csrf("/issuance/new")}, "personnel_filing_id": {"1"},
			"holder_name": {"张三"}, "cert_types": {"01"},
			"issue_date": {"20260801"}, "sign_png": {tc.sign},
		})
		if resp.StatusCode == 302 {
			t.Errorf("签名 %q 不该被放行", tc.sign)
			continue
		}
		if !strings.Contains(body, tc.want) {
			t.Errorf("签名 %q 应报「%s」，实际：%s", tc.sign, tc.want, snippet(body))
		}
	}
}

func TestIssuanceReturnAndVoid(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	id := newIssuance(t, c, pngDataURL)

	// 归还日期不得早于领用日期
	resp, body := c.post("/issuance/"+id+"/return", url.Values{
		"csrf_token": {c.csrf("/issuance/" + id + "/return")},
		"return_date": {"20260701"}, "sign_png": {pngDataURL}})
	if resp.StatusCode == 302 || !strings.Contains(body, "不应早于领用日期") {
		t.Errorf("早于领用日期的归还应被拒：%d %s", resp.StatusCode, snippet(body))
	}

	// 正常归还
	resp, body = c.post("/issuance/"+id+"/return", url.Values{
		"csrf_token": {c.csrf("/issuance/" + id + "/return")},
		"return_date": {"20260810"}, "sign_png": {pngDataURL}})
	if resp.StatusCode != 302 {
		t.Fatalf("归还登记失败: %d %s", resp.StatusCode, snippet(body))
	}
	var status, retDate string
	db.QueryRow("SELECT status, return_date FROM cert_issuance WHERE id = ?", id).Scan(&status, &retDate)
	if status != "returned" || retDate != "20260810" {
		t.Errorf("归还后状态/日期不对: %q %q", status, retDate)
	}

	// 已归还的记录不能再办归还
	resp, _ = c.post("/issuance/"+id+"/return", url.Values{
		"csrf_token": {c.csrf("/issuance/" + id)}, "return_date": {"20260811"},
		"sign_png": {pngDataURL}})
	if resp.StatusCode != 302 {
		t.Error("重复归还应被挡下并重定向")
	}

	// 作废必须给原因
	c.post("/issuance/"+id+"/void", url.Values{"csrf_token": {c.csrf("/issuance/" + id)}})
	db.QueryRow("SELECT status FROM cert_issuance WHERE id = ?", id).Scan(&status)
	if status == "voided" {
		t.Error("没填原因就作废了")
	}

	c.post("/issuance/"+id+"/void", url.Values{
		"csrf_token": {c.csrf("/issuance/" + id)}, "void_reason": {"登记有误"}})
	var reason string
	db.QueryRow("SELECT status, void_reason FROM cert_issuance WHERE id = ?", id).Scan(&status, &reason)
	if status != "voided" || reason != "登记有误" {
		t.Errorf("作废未生效: %q %q", status, reason)
	}
}

// 本模块是「证件领用/归还日期」的唯一写入方，出行表上那两个字段是派生的。
// 作废之后必须跟着清空，否则逾期告警会按一条已经不算数的记录继续报警。
func TestIssuanceSyncsTravelDates(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)

	resp, body := c.post("/issuance/new", url.Values{
		"csrf_token": {c.csrf("/issuance/new")}, "travel_id": {"1"},
		"personnel_filing_id": {"1"}, "holder_name": {"张三"}, "cert_types": {"01"},
		"issue_date": {"20260801"}, "sign_png": {pngDataURL}})
	if resp.StatusCode != 302 {
		t.Fatalf("领用登记失败: %d %s", resp.StatusCode, snippet(body))
	}
	id := resp.Header.Get("Location")[len("/issuance/"):]

	var collect string
	db.QueryRow("SELECT COALESCE(passport_collect_date,'') FROM travel_details WHERE id = 1").Scan(&collect)
	if collect != "20260801" {
		t.Errorf("领用日期未回写出行表: %q", collect)
	}

	c.post("/issuance/"+id+"/void", url.Values{
		"csrf_token": {c.csrf("/issuance/" + id)}, "void_reason": {"重复登记"}})
	db.QueryRow("SELECT COALESCE(passport_collect_date,'') FROM travel_details WHERE id = 1").Scan(&collect)
	if collect != "" {
		t.Errorf("作废后领用日期应清空，实际 %q", collect)
	}
}

// 同一出行下不允许两条未归还的领用记录——否则证件在谁手里就说不清了。
func TestIssuanceRejectsDuplicateOpenRecord(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)

	form := func() url.Values {
		return url.Values{
			"csrf_token": {c.csrf("/issuance/new")}, "travel_id": {"1"},
			"personnel_filing_id": {"1"}, "holder_name": {"张三"}, "cert_types": {"01"},
			"issue_date": {"20260801"}, "sign_png": {pngDataURL}}
	}
	if resp, body := c.post("/issuance/new", form()); resp.StatusCode != 302 {
		t.Fatalf("首条领用应成功: %d %s", resp.StatusCode, snippet(body))
	}
	resp, body := c.post("/issuance/new", form())
	if resp.StatusCode == 302 || !strings.Contains(body, "已有未归还的领用记录") {
		t.Errorf("重复的未归还领用应被拒：%d %s", resp.StatusCode, snippet(body))
	}
}

func TestIssuanceSignatureImage(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	id := newIssuance(t, c, pngDataURL)

	resp, body := c.get("/issuance/" + id + "/signature.png")
	if resp.StatusCode != 200 || resp.Header.Get("Content-Type") != "image/png" {
		t.Fatalf("签名图应以 image/png 返回: %d %s", resp.StatusCode, resp.Header.Get("Content-Type"))
	}
	if len(body) < 8 || body[1:4] != "PNG" {
		t.Errorf("返回的不是 PNG：%d 字节", len(body))
	}
	// 还没归还，归还签名不存在
	if resp, _ := c.get("/issuance/" + id + "/signature.png?kind=return"); resp.StatusCode != 404 {
		t.Errorf("尚未归还时归还签名应 404，实际 %d", resp.StatusCode)
	}
}

func TestIssuanceExportProducesXlsx(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	newIssuance(t, c, pngDataURL)

	resp, body := c.get("/export/issuance")
	if resp.StatusCode != 200 {
		t.Fatalf("导出失败: %d %s", resp.StatusCode, snippet(body))
	}
	// xlsx 是 zip，魔数 PK
	if !strings.HasPrefix(body, "PK") {
		t.Errorf("导出的不是 xlsx：前 8 字节 %q", body[:min(8, len(body))])
	}
}

// 迁移要能把「出行表上已有领用日期、却没有领用记录」的老数据补成一条记录。
func TestLegacyIssuanceBackfill(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)

	// 造一条老形态：出行表带领用日期，但没有对应的领用记录
	db.Exec("UPDATE travel_details SET passport_collect_date = '20260101' WHERE id = 1")
	db.Exec("DELETE FROM cert_issuance WHERE travel_id = 1")
	runMigrations()

	var n int
	var issueDate, remarks string
	db.QueryRow("SELECT COUNT(*) FROM cert_issuance WHERE travel_id = 1").Scan(&n)
	if n != 1 {
		t.Fatalf("应回填出 1 条领用记录，实际 %d 条", n)
	}
	db.QueryRow("SELECT issue_date, remarks FROM cert_issuance WHERE travel_id = 1").
		Scan(&issueDate, &remarks)
	if issueDate != "20260101" || !strings.Contains(remarks, "历史数据回填") {
		t.Errorf("回填内容不对: %q %q", issueDate, remarks)
	}

	// 幂等：再跑一次不该多出记录
	runMigrations()
	db.QueryRow("SELECT COUNT(*) FROM cert_issuance WHERE travel_id = 1").Scan(&n)
	if n != 1 {
		t.Errorf("迁移不幂等：第二次跑之后有 %d 条", n)
	}
}

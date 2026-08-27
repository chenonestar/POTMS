// 领用必须挂在出国申请上、路径B（做证）的逾期告警、证件号码派生、做证校验。
//
// 四条规则同源：证件是为某一次已批准的出行借出/办理的。
//   - 挂不上申请的领用记录是无主的，还会掉出逾期告警（告警按出行记录算）；
//   - 路径B 压根没有领用记录（证是本人凭函去公安办的，从没进过保管处），
//     原来的告警判据「passport_collect_date 非空」对它恒不成立，整类人不受监管；
//   - 明细表上的证件号码原先手填，与领用记录各写各的，打印件上两个格子可能来自
//     不同的证件；
//   - 一本可用的证都没有却说不做证，这条申请本身就是错的。
package main

import (
	"net/url"
	"strings"
	"testing"
)

// seedTwoPaths 造两条都已回国 90 天、证都没交回的申请，区别只在是否做证。
// 路径A 用种子数据里的备案人 1（名下有在有效期内的护照），路径B 另建一人。
func seedTwoPaths(t *testing.T) {
	t.Helper()
	ago := ymdDaysAgo(90)
	if _, err := db.Exec(
		"INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,"+
			"residence,political_status,work_unit,position_or_title,supervisor_unit,operator) "+
			"VALUES (2,'李','四','男','19900101',?,'浙江杭州市西湖区','群众','总部','科长',"+
			"'人事处','admin')", testID); err != nil {
		t.Fatalf("造备案人员失败: %v", err)
	}
	for _, row := range []struct {
		id, pfid int
		name, mk string
	}{
		{801, 1, "路径A张三", "否"},
		{802, 2, "路径B李四", "是"},
	} {
		if _, err := db.Exec(
			"INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"+
				"id_number,destination_passport,category,travel_dates,travel_start,travel_end,"+
				"need_new_passport,actual_return_date,operator) "+
				"VALUES (?,?,'总部','技术部',?,'科长',?,'美国/护照','旅游',?,?,?,?,?,'admin')",
			row.id, row.pfid, row.name, testID, ago+"-"+ago, ago, ago, row.mk, ago); err != nil {
			t.Fatalf("造出行记录失败: %v", err)
		}
	}
}

func countIssuance(t *testing.T) int {
	t.Helper()
	var n int
	db.QueryRow("SELECT COUNT(*) FROM cert_issuance").Scan(&n)
	return n
}

// postIssue 提交一条领用登记，over 覆盖默认字段。
func postIssue(t *testing.T, c *client, over url.Values) (int, string) {
	t.Helper()
	form := url.Values{
		"csrf_token": {c.csrf("/issuance/new?travel_id=801")}, "travel_id": {"801"},
		"personnel_filing_id": {"1"}, "holder_name": {"路径A张三"}, "id_number": {testID},
		"cert_types": {"01"}, "cert_nos": {"E12345678"}, "issue_date": {ymdDaysAgo(90)},
		"sign_png": {pngDataURL},
	}
	for k, v := range over {
		form[k] = v
	}
	resp, body := c.post("/issuance/new", form)
	return resp.StatusCode, body
}

// ---------------------------------------------------------------------------
// A1 领用必须挂出国申请
// ---------------------------------------------------------------------------
func TestIssueWithoutTravelIsRejected(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	_, body := postIssue(t, c, url.Values{"travel_id": {""}})
	if !strings.Contains(body, "关联出国申请") {
		t.Errorf("未提示必须关联出国申请:\n%s", snippet(body))
	}
	if n := countIssuance(t); n != 0 {
		t.Errorf("无主的领用记录被写进库了，共 %d 条", n)
	}
}

func TestIssueWithUnknownTravelIsRejected(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	_, body := postIssue(t, c, url.Values{"travel_id": {"999"}})
	if !strings.Contains(body, "关联的出国申请不存在") {
		t.Errorf("未校验申请是否存在:\n%s", snippet(body))
	}
	if n := countIssuance(t); n != 0 {
		t.Errorf("挂空申请的领用记录被写进库了，共 %d 条", n)
	}
}

func TestHolderMustMatchApplicant(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	// 证是为这条申请借的，不能借给别人
	_, body := postIssue(t, c, url.Values{
		"personnel_filing_id": {"2"}, "holder_name": {"路径B李四"}})
	if !strings.Contains(body, "与该出国申请的申请人不一致") {
		t.Errorf("领用人与申请人不一致未被拦下:\n%s", snippet(body))
	}
	if n := countIssuance(t); n != 0 {
		t.Errorf("借给别人的领用记录被写进库了，共 %d 条", n)
	}
}

func TestCancelledTripCannotIssue(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)
	db.Exec("UPDATE travel_details SET trip_status='cancelled' WHERE id=801")

	_, body := postIssue(t, c, nil)
	if !strings.Contains(body, "已取消行程") {
		t.Errorf("已取消的行程仍能领用:\n%s", snippet(body))
	}
	if n := countIssuance(t); n != 0 {
		t.Errorf("已取消行程的领用记录被写进库了，共 %d 条", n)
	}
}

func TestOneCertPerApplication(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	_, body := postIssue(t, c, url.Values{"cert_types": {"01", "02"}})
	if !strings.Contains(body, "只能领用一本证件") {
		t.Errorf("一次申请领多本未被拦下:\n%s", snippet(body))
	}
	if n := countIssuance(t); n != 0 {
		t.Errorf("多本证的领用记录被写进库了，共 %d 条", n)
	}
}

func TestNewWithoutTravelIDShowsPicker(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	// 直接进新建页时先选申请，而不是给一个能不填的表单
	resp, body := c.get("/issuance/new")
	if resp.StatusCode != 200 {
		t.Fatalf("GET /issuance/new → %d", resp.StatusCode)
	}
	for _, want := range []string{"选择出国申请", "登记领用", "路径A张三"} {
		if !strings.Contains(body, want) {
			t.Errorf("选择页缺少 %q:\n%s", want, snippet(body))
		}
	}
}

func TestPickerExcludesCancelledAndActiveIssuance(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	if code, body := postIssue(t, c, nil); code != 302 {
		t.Fatalf("领用登记失败: %d %s", code, snippet(body))
	}
	db.Exec("UPDATE travel_details SET trip_status='cancelled' WHERE id=802")

	_, body := c.get("/issuance/new")
	if strings.Contains(body, "路径A张三") {
		t.Error("已有未归还领用的申请仍出现在可选列表里")
	}
	if strings.Contains(body, "路径B李四") {
		t.Error("已取消的行程仍出现在可选列表里")
	}
	// 种子数据里的出行 1 已经被 seedBusinessData 建出来且可选，所以这里只断言
	// 上面两条被排除；把它也排除掉才能看到空表提示
	db.Exec("UPDATE travel_details SET trip_status='cancelled' WHERE id=1")
	if _, body = c.get("/issuance/new"); !strings.Contains(body, "没有可办理领用的出国申请") {
		t.Errorf("全部排除后未显示空表提示:\n%s", snippet(body))
	}
}

// ---------------------------------------------------------------------------
// A2 路径B 的逾期告警
// ---------------------------------------------------------------------------
func TestPathBWithoutRegisteredCertIsOverdue(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	// 路径A 也造一条未归还的领用，作对照
	if code, body := postIssue(t, c, nil); code != 302 {
		t.Fatalf("领用登记失败: %d %s", code, snippet(body))
	}
	ids := travelOverdueIDs()
	if !ids[801] {
		t.Error("路径A 已领未还且逾期，却没被抓到")
	}
	if !ids[802] {
		t.Error("路径B 回国 90 天、证没交回，却没被抓到——这类人整个掉出了告警")
	}
}

func TestPathBClearedOnceCertRegistered(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	// 证交回入库、登记进台账之后就不该再告警
	db.Exec("UPDATE travel_details SET passport_no='E99999999' WHERE id=802")
	db.Exec("INSERT INTO certificates (personnel_filing_id,unit,department,name," +
		"passport_no,passport_expiry,passport_submit_date,operator) " +
		"VALUES (2,'总部','技术部','路径B李四','E99999999','20360101','20260101','admin')")
	if travelOverdueIDs()[802] {
		t.Error("证已进台账仍在告警")
	}
}

func TestPathBNumberRecordedButNotRegisteredStillOverdue(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	// 只在明细表补录了号码、没进台账，仍然算没交回
	db.Exec("UPDATE travel_details SET passport_no='E99999999' WHERE id=802")
	if !travelOverdueIDs()[802] {
		t.Error("只补录号码未入台账，应仍算逾期")
	}
}

func TestPathBNotOverdueBeforeDeadline(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	today := ymdDaysAgo(0)
	db.Exec("UPDATE travel_details SET actual_return_date=?, travel_end=? WHERE id=802", today, today)
	if travelOverdueIDs()[802] {
		t.Error("还没到期就报了逾期")
	}
}

func TestPathBShowsOnTravelList(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	resp, body := c.get("/travel/?passport_status=overdue")
	if resp.StatusCode != 200 {
		t.Fatalf("GET /travel/?passport_status=overdue → %d\n%s", resp.StatusCode, snippet(body))
	}
	if !strings.Contains(body, "路径B李四") {
		t.Errorf("逾期筛选没带上路径B:\n%s", snippet(body))
	}
}

func TestPathBCountsOnDashboard(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	// 不能只断言姓名出现在页面上——「近期出行」板块本来就会列出这个人，
	// 那样即使逾期统计完全失灵也照样通过。这里查逾期清单那一条本身：
	// 姓名后面必须跟着「应还: 日期」。
	resp, body := c.get("/")
	if resp.StatusCode != 200 {
		t.Fatalf("GET / → %d", resp.StatusCode)
	}
	i := strings.Index(body, "路径B李四")
	if i < 0 {
		t.Fatalf("仪表盘上找不到路径B:\n%s", snippet(body))
	}
	rest := body[i:]
	j := strings.Index(rest, "应还:")
	if j < 0 || j > 200 {
		t.Errorf("仪表盘逾期清单里没有路径B（姓名后面没跟着应还日期）:\n%s", snippet(rest))
	}
}

// ---------------------------------------------------------------------------
// C 证件号码派生
// ---------------------------------------------------------------------------
func TestCertNoDerivedFromIssuance(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	if code, body := postIssue(t, c, url.Values{"cert_nos": {"E77778888"}}); code != 302 {
		t.Fatalf("领用登记失败: %d %s", code, snippet(body))
	}
	var no string
	db.QueryRow("SELECT COALESCE(passport_no,'') FROM travel_details WHERE id=801").Scan(&no)
	if no != "E77778888" {
		t.Errorf("证件号码未从领用记录派生到出行表，实际 %q", no)
	}

	// 表单上那一栏应变成只读。不能只查页面上有没有 readonly——领用日期、
	// 归还日期两栏本来就是只读的，那样查恒为真。只看 passport_no 这个 input。
	_, body := c.get("/travel/801/edit")
	tag := passportNoInput(t, body)
	if !strings.Contains(tag, "readonly") {
		t.Errorf("有领用记录时证件号码栏未置为只读:\n%s", tag)
	}

	// 就算绕过只读直接提交，也不能覆盖派生值
	c.post("/travel/801/edit", url.Values{
		"csrf_token": {c.csrf("/travel/801/edit")}, "personnel_filing_id": {"1"},
		"unit": {"总部"}, "department": {"技术部"}, "name": {"路径A张三"}, "position": {"科长"},
		"id_number": {testID}, "destination_passport": {"美国-护照"}, "category": {"旅游"},
		"travel_dates": {"2026/09/01-2026/09/11"}, "need_new_passport": {"否"},
		"passport_no": {"BOGUS999"}})
	db.QueryRow("SELECT COALESCE(passport_no,'') FROM travel_details WHERE id=801").Scan(&no)
	if no != "E77778888" {
		t.Errorf("绕过只读的提交覆盖了派生的证件号码，实际 %q", no)
	}
}

// passportNoInput 从页面里切出 name="passport_no" 那个 input 标签。
func passportNoInput(t *testing.T, body string) string {
	t.Helper()
	i := strings.Index(body, `name="passport_no"`)
	if i < 0 {
		t.Fatalf("页面上找不到证件号码输入框:\n%s", snippet(body))
	}
	start := strings.LastIndex(body[:i], "<input")
	end := strings.Index(body[i:], ">")
	return body[start : i+end+1]
}

// ---------------------------------------------------------------------------
// D 做证校验
// ---------------------------------------------------------------------------

// postTravel 提交一条出国申请（不带附件，只看校验是否放行到附件那一步）。
func postTravel(t *testing.T, c *client, over url.Values) string {
	t.Helper()
	form := url.Values{
		"csrf_token": {c.csrf("/travel/new")}, "personnel_filing_id": {"2"},
		"unit": {"总部"}, "department": {"技术部"}, "name": {"李四"}, "position": {"科长"},
		"id_number": {testID}, "destination_passport": {"美国-护照"}, "category": {"旅游"},
		"travel_dates": {"2026/09/01-2026/09/11"}, "need_new_passport": {"否"},
	}
	for k, v := range over {
		form[k] = v
	}
	_, body := c.post("/travel/new", form)
	return body
}

func TestNoUsableCertMustMakeNew(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t) // 备案人 2 名下一本证都没有

	body := postTravel(t, c, nil)
	if !strings.Contains(body, "没有在有效期内的出入境证件") {
		t.Errorf("一本证都没有却填「不做证」，未被拦下:\n%s", snippet(body))
	}
}

func TestExpiredCertCountsAsNone(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	// 一本过期护照等于没有——只看有没有号码是不够的
	db.Exec("INSERT INTO certificates (personnel_filing_id,unit,department,name," +
		"passport_no,passport_expiry,passport_submit_date,operator) " +
		"VALUES (2,'总部','技术部','李四','E11112222','20200101','20190101','admin')")
	body := postTravel(t, c, nil)
	if !strings.Contains(body, "没有在有效期内的出入境证件") {
		t.Errorf("过期证件被当成可用:\n%s", snippet(body))
	}
}

func TestValidCertPassesPathA(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	db.Exec("INSERT INTO certificates (personnel_filing_id,unit,department,name," +
		"hm_pass_no,hm_pass_expiry,hm_pass_submit_date,operator) " +
		"VALUES (2,'总部','技术部','李四','C11112222','20360101','20260101','admin')")
	body := postTravel(t, c, nil)
	if strings.Contains(body, "没有在有效期内的出入境证件") {
		t.Errorf("名下有在有效期内的证件，却被判为必须做证:\n%s", snippet(body))
	}
}

func TestNeedNewPassportSkipsCertCheck(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedTwoPaths(t)

	// 做证=是 时本来就没证，不该报这条
	body := postTravel(t, c, url.Values{"need_new_passport": {"是"}})
	if strings.Contains(body, "没有在有效期内的出入境证件") {
		t.Errorf("做证=是 时不该校验名下证件:\n%s", snippet(body))
	}
}

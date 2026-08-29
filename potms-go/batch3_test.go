// 第 3 批：领用列表批量打印、附件总览按批次排序、证件种类单选、证照一人一行 + 换发提醒。
//
// 四条都是「界面与语义」层面的：功能都在，但呈现或口径与 Python 版不一致，
// 用起来会出错——批量打印缺一整个入口；附件按上传时间排，同一个人同一批次的
// 附件被别人的插在中间；证件种类是复选框，而业务上一次申请只能领一本；证照
// 允许同一个人建多条，于是两个编辑入口、预警报两遍。
package main

import (
	"net/url"
	"strings"
	"testing"
)

// ---------------------------------------------------------------------------
// 1 批量打印
// ---------------------------------------------------------------------------
func TestIssuanceListHasBatchPrint(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)

	_, body := c.get("/issuance/")
	if !strings.Contains(body, "批量打印") {
		t.Errorf("领用列表缺少批量打印入口:\n%s", snippet(body))
	}
	if !strings.Contains(body, "batchPrint('issuance')") {
		t.Errorf("批量打印按钮没接上 issuance 类型:\n%s", snippet(body))
	}
}

func TestBatchPrintIssuanceRendersRows(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	id := newIssuance(t, c, pngDataURL)

	resp, body := c.get("/print/batch/issuance?ids=" + id)
	if resp.StatusCode != 200 {
		t.Fatalf("GET /print/batch/issuance → %d\n%s", resp.StatusCode, snippet(body))
	}
	for _, want := range []string{
		"因私出国（境）证件领用登记表",
		"张三",       // 领用人
		"总部",       // 单位（JOIN 备案表取的）
		"普通护照",     // 证件种类：代码要换成中文，不能印出 01
		"E12345678", // 证件号码
		"共 1 条记录",
	} {
		if !strings.Contains(body, want) {
			t.Errorf("批量打印页缺少「%s」:\n%s", want, snippet(body))
		}
	}
	// 签名按行取图，不能把 BLOB 塞进页面
	if !strings.Contains(body, "/issuance/"+id+"/signature.png") {
		t.Errorf("批量打印页没有按行引用签名图:\n%s", snippet(body))
	}
	if strings.Contains(body, "\x89PNG") {
		t.Error("页面里直接塞了 PNG 字节")
	}
}

func TestBatchPrintWithoutIdsIsRejected(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)

	resp, _ := c.get("/print/batch/issuance")
	if resp.StatusCode != 302 {
		t.Errorf("没选记录时应重定向，实际 %d", resp.StatusCode)
	}
}

// ---------------------------------------------------------------------------
// 2 附件总览排序
// ---------------------------------------------------------------------------

// seedAttachments 造两条申请，各带两个附件，且刻意让上传时间交叉：
// 申请 901 的附件一早一晚，申请 902 的夹在中间。
// 按上传时间排会把 902 插进 901 中间；按批次排则两组各自聚拢。
func seedAttachments(t *testing.T) {
	t.Helper()
	for _, tid := range []int{901, 902} {
		if _, err := db.Exec(
			"INSERT INTO travel_details (id, personnel_filing_id, unit, department, name, position, "+
				"id_number, destination_passport, category, travel_dates, need_new_passport, operator) "+
				"VALUES (?, 1, '总部', '技术部', ?, '科长', ?, '美国/护照', '旅游', "+
				"'2026/03/01-2026/03/10', '否', 'admin')",
			tid, "批次"+itoa(int64(tid)), testID); err != nil {
			t.Fatalf("造出行记录失败: %v", err)
		}
	}
	// (附件 id, 出行 id, 类型, 上传时间)
	for _, a := range []struct {
		id, travelID int
		fileType, up string
	}{
		{9011, 901, "审批表", "2026-03-05 10:00:00"},     // 901 的第二件，先传
		{9021, 902, "个人申请报告", "2026-03-06 10:00:00"},  // 902 的，夹在中间
		{9012, 901, "个人申请报告", "2026-03-07 10:00:00"},  // 901 的第一件，后补传
		{9022, 902, "审批表", "2026-03-08 10:00:00"},
	} {
		if _, err := db.Exec(
			"INSERT INTO attachments (id, travel_id, file_name, file_path, file_type, file_size, uploaded_at) "+
				"VALUES (?, ?, ?, 'x.pdf', ?, 1024, ?)",
			a.id, a.travelID, "f"+itoa(int64(a.id))+".pdf", a.fileType, a.up); err != nil {
			t.Fatalf("造附件失败: %v", err)
		}
	}
}

// orderOf 返回几个片段在页面上出现的先后次序。
func orderOf(body string, keys ...string) []int {
	out := make([]int, len(keys))
	for i, k := range keys {
		out[i] = strings.Index(body, k)
	}
	return out
}

func TestAttachmentsGroupedByBatchByDefault(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedAttachments(t)

	resp, body := c.get("/travel/attachments")
	if resp.StatusCode != 200 {
		t.Fatalf("GET /travel/attachments → %d\n%s", resp.StatusCode, snippet(body))
	}
	// 默认按批次：902 那组（created_at 更晚）整组在前，组内按办件顺序
	// （个人申请报告 → 审批表），901 那组随后，同样按办件顺序。
	pos := orderOf(body, "f9021.pdf", "f9022.pdf", "f9012.pdf", "f9011.pdf")
	for i, p := range pos {
		if p < 0 {
			t.Fatalf("第 %d 个附件没出现在页面上", i)
		}
	}
	for i := 1; i < len(pos); i++ {
		if pos[i-1] > pos[i] {
			t.Fatalf("默认排序不是「按批次聚组 + 组内办件顺序」，实际位置 %v", pos)
		}
	}
}

func TestAttachmentsSortByUploadedTime(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedAttachments(t)

	_, body := c.get("/travel/attachments?sort=uploaded")
	// 按上传时间倒序：9022 → 9012 → 9021 → 9011
	pos := orderOf(body, "f9022.pdf", "f9012.pdf", "f9021.pdf", "f9011.pdf")
	for i := 1; i < len(pos); i++ {
		if pos[i-1] > pos[i] {
			t.Fatalf("sort=uploaded 没有按上传时间倒序，实际位置 %v", pos)
		}
	}
	// 选择器要回显当前选项
	if !strings.Contains(body, `value="uploaded" selected`) &&
		!strings.Contains(body, `selected value="uploaded"`) {
		t.Errorf("排序选择器没有回显 uploaded:\n%s", snippet(body))
	}
}

func TestAttachmentsSortFallsBackOnGarbage(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedAttachments(t)

	// 白名单之外的取值不能拼进 SQL，退回默认排序而不是报错
	resp, body := c.get("/travel/attachments?sort=" + url.QueryEscape("a.id; DROP TABLE attachments"))
	if resp.StatusCode != 200 {
		t.Fatalf("非法排序参数把页面打挂了：%d", resp.StatusCode)
	}
	if !strings.Contains(body, "f9021.pdf") {
		t.Error("非法排序参数下附件列表为空")
	}
	var n int
	db.QueryRow("SELECT COUNT(*) FROM attachments").Scan(&n)
	if n == 0 {
		t.Fatal("attachments 表没了——排序参数被拼进了 SQL")
	}
}

// ---------------------------------------------------------------------------
// 3 证件种类单选
// ---------------------------------------------------------------------------
func TestIssuanceFormUsesRadioForCertType(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)

	_, body := c.get("/issuance/new?travel_id=1")
	i := strings.Index(body, `name="cert_types"`)
	if i < 0 {
		t.Fatalf("表单上找不到证件种类控件:\n%s", snippet(body))
	}
	start := strings.LastIndex(body[:i], "<input")
	tag := body[start : i+len(`name="cert_types"`)]
	if !strings.Contains(tag, `type="radio"`) {
		t.Errorf("证件种类仍是复选框——业务上一次申请只能领一本证：%s", tag)
	}
}

// ---------------------------------------------------------------------------
// 4 证照一人一行 + 换发提醒
// ---------------------------------------------------------------------------
func postCert(c *client, over url.Values) (int, string) {
	form := url.Values{
		"csrf_token": {c.csrf("/certificate/new")}, "personnel_filing_id": {"1"},
		"unit": {"总部"}, "department": {"技术部"}, "name": {"张三"},
		"passport_no": {"E20000001"}, "passport_expiry": {"20360101"},
		"passport_submit_date": {"20260101"},
	}
	for k, v := range over {
		form[k] = v
	}
	resp, body := c.post("/certificate/new", form)
	return resp.StatusCode, body
}

func TestCertificateOnePerPerson(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)   // 已给备案人 1 建了一条证照

	code, body := postCert(c, nil)
	if code == 302 {
		t.Fatal("同一备案人员被允许建第二条证照记录")
	}
	if !strings.Contains(body, "已有证照记录") {
		t.Errorf("未提示「一人一行」:\n%s", snippet(body))
	}
	var n int
	db.QueryRow("SELECT COUNT(*) FROM certificates WHERE personnel_filing_id = 1").Scan(&n)
	if n != 1 {
		t.Errorf("库里应仍只有 1 条证照记录，实际 %d 条", n)
	}
}

func TestCertificateFirstRecordStillAllowed(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	db.Exec("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number," +
		"residence,political_status,work_unit,position_or_title,supervisor_unit,operator) " +
		"VALUES (2,'李','四','男','19900101','" + testID + "','浙江杭州市西湖区','群众'," +
		"'总部','科长','人事处','admin')")

	// 换一个还没有证照的人，首次登记必须放行
	if code, body := postCert(c, url.Values{
		"personnel_filing_id": {"2"}, "name": {"李四"},
		"passport_no": {"E20000002"}}); code != 302 {
		t.Errorf("首次登记被误拦：%d %s", code, snippet(body))
	}
}

func TestCertificateRenewalWarnsAboutDates(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)   // 备案人 1 的护照是 E12345678

	var certID string
	db.QueryRow("SELECT id FROM certificates WHERE personnel_filing_id = 1").Scan(&certID)

	// 换发：只改号码，日期没跟着改
	form := url.Values{
		"csrf_token": {c.csrf("/certificate/" + certID + "/edit")},
		"personnel_filing_id": {"1"}, "unit": {"总部"}, "department": {"技术部"},
		"name": {"张三"}, "passport_no": {"E99999999"},
		"passport_expiry": {"20300101"}, "passport_submit_date": {"20250101"},
	}
	resp, _ := c.post("/certificate/"+certID+"/edit", form)
	if resp.StatusCode != 302 {
		t.Fatalf("换发提交失败：%d", resp.StatusCode)
	}
	_, body := c.get("/certificate/")
	if !strings.Contains(body, "号码已变更") {
		t.Errorf("换发后没有提醒同步日期:\n%s", snippet(body))
	}
	if !strings.Contains(body, "普通护照") {
		t.Errorf("提醒里没有说明是哪一类证件:\n%s", snippet(body))
	}
}

func TestCertificateEditWithoutNumberChangeIsQuiet(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)

	var certID string
	db.QueryRow("SELECT id FROM certificates WHERE personnel_filing_id = 1").Scan(&certID)

	// 号码没动，只改了部门——不是换发，不该提醒
	resp, _ := c.post("/certificate/"+certID+"/edit", url.Values{
		"csrf_token": {c.csrf("/certificate/" + certID + "/edit")},
		"personnel_filing_id": {"1"}, "unit": {"总部"}, "department": {"办公室"},
		"name": {"张三"}, "passport_no": {"E12345678"},
		"passport_expiry": {"20300101"}, "passport_submit_date": {"20250101"},
	})
	if resp.StatusCode != 302 {
		t.Fatalf("编辑提交失败：%d", resp.StatusCode)
	}
	_, body := c.get("/certificate/")
	if strings.Contains(body, "号码已变更") {
		t.Error("号码没变也提醒了换发——这条提醒会被当成噪音，很快没人看")
	}
}

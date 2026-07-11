// 端到端冒烟测试：登录 → 全部页面 → 关键业务流（与 Python 版行为对齐）
package main

import (
	"bytes"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"net/url"
	"os"
	"regexp"
	"strings"
	"testing"
)

var csrfRe = regexp.MustCompile(`name="csrf-token" content="([^"]+)"`)

type client struct {
	t      *testing.T
	http   *http.Client
	server *httptest.Server
}

func newTestApp(t *testing.T) *client {
	tmp := t.TempDir()
	os.Setenv("POTMS_BASE", tmp)
	initConfig()
	openDB()
	initSchema()
	seedData()
	runMigrations()
	loadTemplates()

	mux := http.NewServeMux()
	registerRoutes(mux)
	server := httptest.NewServer(protect(mux))
	t.Cleanup(func() { server.Close(); db.Close() })

	jar, _ := cookiejar.New(nil)
	return &client{t: t, server: server,
		http: &http.Client{Jar: jar, CheckRedirect: func(req *http.Request, via []*http.Request) error {
			return http.ErrUseLastResponse
		}}}
}

func (c *client) get(path string) (*http.Response, string) {
	resp, err := c.http.Get(c.server.URL + path)
	if err != nil {
		c.t.Fatalf("GET %s: %v", path, err)
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	return resp, string(body)
}

func (c *client) csrf(path string) string {
	_, body := c.get(path)
	m := csrfRe.FindStringSubmatch(body)
	if m == nil {
		c.t.Fatalf("页面 %s 无 csrf-token", path)
	}
	return m[1]
}

func (c *client) post(path string, form url.Values) (*http.Response, string) {
	resp, err := c.http.PostForm(c.server.URL+path, form)
	if err != nil {
		c.t.Fatalf("POST %s: %v", path, err)
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	return resp, string(body)
}

func (c *client) login() {
	tok := c.csrf("/login")
	resp, _ := c.post("/login", url.Values{
		"username": {"admin"}, "password": {"admin123"}, "csrf_token": {tok}})
	if resp.StatusCode != 302 {
		c.t.Fatalf("登录失败: %d", resp.StatusCode)
	}
}

const testID = "110101199001012133" // 合法男性身份证（生日19900101）

func seedBusinessData(t *testing.T, c *client) {
	tok := c.csrf("/")
	// 信息登记表
	resp, body := c.post("/personnel/info/new", url.Values{
		"csrf_token": {tok}, "unit": {"总部"}, "department": {"人事处"},
		"name": {"张三"}, "gender": {"男"}, "birth_date": {"19900101"},
		"id_number": {testID}, "work_start_date": {"20100701"},
		"education": {"03"}, "degree": {"03"}, "title": {"02"}, "rank": {"03"},
		"political_status": {"群众"}, "position": {"科长"},
	})
	if resp.StatusCode != 302 || !strings.Contains(resp.Header.Get("Location"), "filing/new") {
		t.Fatalf("信息表创建失败: %d %s", resp.StatusCode, snippet(body))
	}
	// 登记备案表
	resp, body = c.post("/personnel/filing/new?info_id=1", url.Values{
		"csrf_token": {c.csrf("/")}, "surname": {"张"}, "given_name": {"三"},
		"gender": {"男"}, "birth_date": {"19900101"}, "id_number": {testID},
		"residence": {"浙江杭州市西湖区"}, "political_status": {"群众"},
		"work_unit": {"总部"}, "position_or_title": {"正科"},
		"supervisor_unit": {"人事处"}, "tag": {"新增"}, "informed": {"是"},
	})
	if resp.StatusCode != 302 {
		t.Fatalf("备案表创建失败: %d %s", resp.StatusCode, snippet(body))
	}
	// 证照
	resp, _ = c.post("/certificate/new", url.Values{
		"csrf_token": {c.csrf("/")}, "personnel_filing_id": {"1"},
		"unit": {"总部"}, "department": {"人事处"}, "name": {"张三"},
		"passport_no": {"E12345678"}, "passport_expiry": {"20300101"}, "passport_submit_date": {"20250101"},
	})
	if resp.StatusCode != 302 {
		t.Fatal("证照创建失败")
	}
	// 出国申请（含 PDF 附件）
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	fields := map[string]string{
		"csrf_token": c.csrf("/"), "personnel_filing_id": "1",
		"unit": "总部", "department": "人事处", "name": "张三", "position": "正科",
		"title": "副高", "id_number": testID, "destination_passport": "美国-护照",
		"category": "旅游", "travel_dates": "2026/08/01-2026/08/11",
		"need_new_passport": "否", "passport_collect_date": "20260725",
	}
	for k, v := range fields {
		mw.WriteField(k, v)
	}
	for _, f := range []string{"att_application", "att_approval"} {
		fw, _ := mw.CreateFormFile(f, "doc.pdf")
		fw.Write([]byte("%PDF-1.4 test content"))
	}
	mw.Close()
	req, _ := http.NewRequest("POST", c.server.URL+"/travel/new", &buf)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	resp2, err := c.http.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	b, _ := io.ReadAll(resp2.Body)
	resp2.Body.Close()
	if resp2.StatusCode != 302 {
		t.Fatalf("出国申请创建失败: %d %s", resp2.StatusCode, snippet(string(b)))
	}
}

func snippet(s string) string {
	if i := strings.Index(s, "alert-danger"); i > 0 {
		end := i + 300
		if end > len(s) {
			end = len(s)
		}
		return s[i:end]
	}
	if len(s) > 200 {
		return s[:200]
	}
	return s
}

// ---------------------------------------------------------------------------
func TestFullSystem(t *testing.T) {
	c := newTestApp(t)

	// 未登录访问 → 跳登录
	resp, _ := c.get("/personnel/")
	if resp.StatusCode != 302 {
		t.Fatal("未登录应跳转登录页")
	}
	// 无 CSRF 的 POST → 拒绝
	resp, _ = c.post("/login", url.Values{"username": {"admin"}, "password": {"admin123"}})
	if resp.StatusCode != 302 || !strings.Contains(resp.Header.Get("Location"), "/login") {
		t.Fatal("无 CSRF 令牌的 POST 应被拒绝")
	}

	c.login()
	seedBusinessData(t, c)

	// 全部页面 200 且无渲染错误
	pages := []string{
		"/", "/personnel/", "/personnel/info/new", "/personnel/filing/new",
		"/personnel/1", "/personnel/info/1/edit", "/personnel/filing/1/edit",
		"/certificate/", "/certificate/new", "/certificate/1/edit",
		"/travel/", "/travel/new", "/travel/1", "/travel/1/edit", "/travel/attachments",
		"/decontrol/", "/logs/", "/account", "/dict/", "/org/", "/submit-unit/",
		"/import/", "/search", "/search?q=张三",
		"/print/info/1", "/print/filing/1", "/print/certificate/1", "/print/travel/1",
		"/print/batch/travel?ids=1",
	}
	for _, p := range pages {
		resp, body := c.get(p)
		if resp.StatusCode != 200 {
			t.Errorf("%s → %d", p, resp.StatusCode)
		}
		if strings.Contains(body, "Unable to") || strings.Contains(body, "unable to execute") {
			t.Errorf("%s 模板渲染错误: %s", p, snippet(body))
		}
		// gonja 的 or/and 是纯布尔运算（不同于 Jinja2 返回操作数），
		// 模板须用 default(x, true) 兜底，页面不得出现布尔值泄漏
		if strings.Contains(body, ">True<") || strings.Contains(body, ">False<") {
			t.Errorf("%s 页面出现 True/False 布尔泄漏，应使用 default 过滤器", p)
		}
	}

	// 有值字段显示实际内容而非 True
	if _, body := c.get("/certificate/"); !strings.Contains(body, "E12345678") {
		t.Error("证照列表应显示护照号 E12345678")
	}

	// 校验拦截：假 PDF
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	mw.WriteField("csrf_token", c.csrf("/"))
	for k, v := range map[string]string{
		"personnel_filing_id": "1", "unit": "总部", "department": "人事处",
		"name": "张三", "position": "正科", "id_number": testID,
		"destination_passport": "日本-护照", "category": "旅游",
		"travel_dates": "2026/09/01-2026/09/05", "need_new_passport": "否",
		"passport_collect_date": "20260828",
	} {
		mw.WriteField(k, v)
	}
	fw, _ := mw.CreateFormFile("att_application", "fake.pdf")
	fw.Write([]byte("NOT A PDF"))
	fw2, _ := mw.CreateFormFile("att_approval", "ok.pdf")
	fw2.Write([]byte("%PDF-1.4"))
	mw.Close()
	req, _ := http.NewRequest("POST", c.server.URL+"/travel/new", &buf)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	resp2, _ := c.http.Do(req)
	b, _ := io.ReadAll(resp2.Body)
	resp2.Body.Close()
	if !strings.Contains(string(b), "不是有效的 PDF") {
		t.Error("假 PDF 未被拦截")
	}

	// 行程取消 / 恢复
	resp, _ = c.post("/travel/1/cancel", url.Values{"csrf_token": {c.csrf("/")}, "cancel_date": {"20260805"}})
	if resp.StatusCode != 302 {
		t.Error("取消行程失败")
	}
	if rowStr(queryOne("SELECT trip_status FROM travel_details WHERE id=1"), "trip_status") != "cancelled" {
		t.Error("取消状态未写入")
	}
	c.post("/travel/1/restore", url.Values{"csrf_token": {c.csrf("/")}})
	if rowStr(queryOne("SELECT trip_status FROM travel_details WHERE id=1"), "trip_status") != "normal" {
		t.Error("恢复状态未写入")
	}

	// Excel 导出（5 类 + 日志归档 + 导入模板）
	for _, p := range []string{
		"/export/info", "/export/filing", "/export/certificate",
		"/export/travel", "/export/decontrol", "/import/template",
	} {
		resp, body := c.get(p)
		if resp.StatusCode != 200 || !strings.HasPrefix(body, "PK") {
			t.Errorf("%s 导出失败: %d", p, resp.StatusCode)
		}
	}

	// 附件下载 / 预览
	resp, body := c.get("/travel/attachment/1/preview")
	if resp.StatusCode != 200 || !strings.HasPrefix(body, "%PDF") {
		t.Error("附件预览失败")
	}

	// 撤控流程
	resp, _ = c.post("/decontrol/new/1", url.Values{
		"csrf_token": {c.csrf("/")}, "surname": {"张"}, "given_name": {"三"},
		"gender": {"男"}, "birth_date": {"19900101"}, "id_number": {testID},
		"residence": {"浙江杭州市西湖区"}, "political_status": {"群众"},
		"work_unit": {"总部"}, "supervisor_unit": {"人事处"},
		"submit_unit_name": {"市公安局"}, "submit_unit_type": {"党政机关"},
		"submit_contact": {"李四"}, "submit_phone": {"0571-12345678"},
		"batch_no": {"2026-001"}, "reason": {"工作调动"},
	})
	if resp.StatusCode != 302 {
		t.Error("撤控提交失败")
	}
	if rowStr(queryOne("SELECT status FROM personnel_filing WHERE id=1"), "status") != "decontrolled" {
		t.Error("撤控后状态未变更")
	}
	_, body = c.get("/decontrol/")
	if !strings.Contains(body, "张三") {
		t.Error("撤控列表缺记录")
	}
	_, body = c.get("/print/decontrol/1")
	if !strings.Contains(body, "撤控备案表") {
		t.Error("撤控打印页异常")
	}

	// 撤控重报关联：重新备案同身份证 → tag=更新
	resp, _ = c.post("/personnel/filing/new", url.Values{
		"csrf_token": {c.csrf("/")}, "surname": {"张"}, "given_name": {"三"},
		"gender": {"男"}, "birth_date": {"19900101"}, "id_number": {testID},
		"residence": {"浙江杭州市西湖区"}, "political_status": {"群众"},
		"work_unit": {"总部"}, "position_or_title": {"正科"},
		"supervisor_unit": {"人事处"}, "tag": {"新增"}, "informed": {"是"},
	})
	if resp.StatusCode != 302 {
		t.Error("重报失败")
	}
	if rowStr(queryOne("SELECT tag FROM personnel_filing WHERE id=2"), "tag") != "更新" {
		t.Error("重报未自动标记为更新")
	}
	if toInt64(queryOne("SELECT replaced_by_id FROM personnel_filing WHERE id=1")["replaced_by_id"]) != 2 {
		t.Error("新旧关联未建立")
	}

	// 数据字典 / 组织 / 报送单位增删
	c.post("/dict/add", url.Values{"csrf_token": {c.csrf("/")},
		"category": {"education"}, "code": {"88"}, "value": {"测试学历"}, "sort_order": {"9"}})
	if queryOne("SELECT id FROM sys_dict WHERE category='education' AND code='88'") == nil {
		t.Error("字典新增失败")
	}
	c.post("/org/add", url.Values{"csrf_token": {c.csrf("/")}, "name": {"测试单位"}, "parent_id": {"0"}})
	c.post("/submit-unit/add", url.Values{"csrf_token": {c.csrf("/")},
		"name": {"测试报送单位"}, "contact": {"王五"}, "phone": {"123"}})

	// 全局搜索
	_, body = c.get("/search?q=张三")
	if !strings.Contains(body, "人员备案") {
		t.Error("全局搜索无结果分组")
	}

	// 操作日志与年度归档
	_, body = c.get("/logs/")
	if !strings.Contains(body, "归档导出") {
		t.Error("日志归档按钮缺失")
	}
	resp, body = c.get("/logs/export?year=" + nowLocalYMD()[:4])
	if resp.StatusCode != 200 || !strings.HasPrefix(body, "PK") {
		t.Error("日志归档导出失败")
	}

	// 手动备份
	resp, _ = c.post("/backup/now", url.Values{"csrf_token": {c.csrf("/")}})
	if resp.StatusCode != 302 {
		t.Error("手动备份失败")
	}
	if name, _ := latestBackup(); name == "" {
		t.Error("备份文件未生成")
	}

	// 404 中文页
	resp, body = c.get("/no-such-page")
	if resp.StatusCode != 404 || !strings.Contains(body, "页面不存在") {
		t.Error("404 中文页异常")
	}
}

func TestLoginLockout(t *testing.T) {
	c := newTestApp(t)
	for i := 0; i < 5; i++ {
		c.post("/login", url.Values{"username": {"admin"}, "password": {"wrong"},
			"csrf_token": {c.csrf("/login")}})
	}
	_, body := c.post("/login", url.Values{"username": {"admin"}, "password": {"admin123"},
		"csrf_token": {c.csrf("/login")}})
	if !strings.Contains(body, "锁定") {
		t.Error("连续失败后未锁定")
	}
	if queryOne("SELECT id FROM operation_logs WHERE action='lock'") == nil {
		t.Error("锁定事件未写日志")
	}
	resetLoginFails("127.0.0.1")
}

func TestValidators(t *testing.T) {
	if ok, _ := validateIDNumber(testID); !ok {
		t.Error("合法身份证被拒")
	}
	if ok, _ := validateIDNumber("110101199001012134"); ok {
		t.Error("错误校验位未拦截")
	}
	if ok, _ := validateGenderMatch(testID, "女"); ok {
		t.Error("性别不一致未拦截")
	}
	if ok, _ := validateDateFormat("20260230"); ok {
		t.Error("不存在的日期未拦截")
	}
	if got := addWorkingDays("20260811", 10); got != "20260825" {
		t.Errorf("工作日推算错误: %s", got)
	}
	if got := addWorkingDays("20260703", 5); got != "20260710" {
		t.Errorf("取消5工作日推算错误: %s", got)
	}
	r := Row{"passport_collect_date": "20260101", "passport_return_date": "",
		"actual_return_date": "", "travel_end": "20260811", "trip_status": "normal", "cancel_date": ""}
	if !isCertOverdue(r, "20260826") {
		t.Error("应判逾期")
	}
	if isCertOverdue(r, "20260825") {
		t.Error("到期日当天不应逾期")
	}
	if got := formatTravelRange("20260801", "20260811"); got != "2026/08/01-2026/08/11" {
		t.Errorf("区间格式化错误: %s", got)
	}
	if got := toLocalTime("2026-07-05 10:00:00", "%Y-%m-%d %H:%M:%S"); got != "2026-07-05 18:00:00" {
		t.Errorf("UTC→本地转换错误: %s", got)
	}
	if s, g := detectSurnameSplit("欧阳修文"); s != "欧阳" || g != "修文" {
		t.Error("复姓拆分错误")
	}
	if normalizeResidence("浙江省宁波市江东区") != "浙江宁波市鄞州区" {
		t.Error("户口规范化错误")
	}
	fmt.Println("validators OK")
}

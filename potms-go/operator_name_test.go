// 经办人身份的分层：业务单据记真实姓名，操作日志记登录账号。
//
// 这不是显示细节，是两类字段的不同口径。账号是身份标识、姓名可以随时改，
// 所以审计痕迹只能挂在账号上；而打印出来的单据上一个 admin 没法拿去归档，
// 必须是真人名字。改回任何一边都会被下面的用例抓住。
package main

import (
	"net/url"
	"strings"
	"testing"
)

// setFullName 走账户设置页把姓名存进 users.full_name，并让会话带上它。
func setFullName(t *testing.T, c *client, name string) {
	t.Helper()
	resp, body := c.post("/account", url.Values{
		"csrf_token":       {c.csrf("/account")},
		"current_password": {"admin123"},
		"new_username":     {"admin"},
		"new_full_name":    {name},
	})
	if resp.StatusCode != 302 {
		t.Fatalf("保存姓名失败: %d %s", resp.StatusCode, snippet(body))
	}
}

func TestFullNameColumnExists(t *testing.T) {
	newTestApp(t)
	// 五版共用一个 data.db，users.full_name 必须由本版的建表 DDL 带出来
	rows, err := queryMaps("PRAGMA table_info(users)")
	if err != nil {
		t.Fatalf("读取表结构失败: %v", err)
	}
	for _, r := range rows {
		if rowStr(r, "name") == "full_name" {
			return
		}
	}
	t.Fatalf("users 表缺少 full_name 列: %v", rows)
}

func TestAddColumnIsIdempotent(t *testing.T) {
	newTestApp(t)
	// 迁移在每次启动时都会跑，重复执行不能报错、也不能把列加两遍
	runMigrations()
	runMigrations()
	rows, _ := queryMaps("PRAGMA table_info(users)")
	n := 0
	for _, r := range rows {
		if rowStr(r, "name") == "full_name" {
			n++
		}
	}
	if n != 1 {
		t.Fatalf("full_name 列出现 %d 次，应恰好 1 次", n)
	}
}

func TestBusinessRecordsUseRealName(t *testing.T) {
	c := newTestApp(t)
	c.login()
	setFullName(t, c, "张建国")
	seedBusinessData(t, c)

	for _, table := range []string{
		"personnel_info", "personnel_filing", "certificates", "travel_details",
	} {
		var op string
		if err := db.QueryRow("SELECT operator FROM " + table + " LIMIT 1").Scan(&op); err != nil {
			t.Fatalf("读取 %s.operator 失败: %v", table, err)
		}
		if op != "张建国" {
			t.Errorf("%s.operator = %q，业务单据应记真实姓名", table, op)
		}
	}
}

func TestOperationLogsKeepAccount(t *testing.T) {
	c := newTestApp(t)
	c.login()
	setFullName(t, c, "张建国")
	seedBusinessData(t, c)

	// 姓名可以改，账号不能——日志只记姓名的话，改名后历史记录就对不上人了
	var n int
	db.QueryRow("SELECT COUNT(*) FROM operation_logs WHERE operator = '张建国'").Scan(&n)
	if n != 0 {
		t.Errorf("操作日志里出现了 %d 条以姓名为操作人的记录，应全部记登录账号", n)
	}
	db.QueryRow("SELECT COUNT(*) FROM operation_logs WHERE operator = 'admin'").Scan(&n)
	if n == 0 {
		t.Error("操作日志里没有以 admin 为操作人的记录")
	}
}

func TestOperatorFallsBackToAccount(t *testing.T) {
	c := newTestApp(t)
	c.login() // 不设姓名
	seedBusinessData(t, c)

	var op string
	db.QueryRow("SELECT operator FROM personnel_info LIMIT 1").Scan(&op)
	if op != "admin" {
		t.Errorf("未填姓名时 operator = %q，应回退到登录账号 admin", op)
	}
}

func TestLogsPageShowsNameWithAccount(t *testing.T) {
	c := newTestApp(t)
	c.login()
	setFullName(t, c, "张建国")
	seedBusinessData(t, c)

	_, body := c.get("/logs/")
	if !strings.Contains(body, "张建国") || !strings.Contains(body, "（admin）") {
		t.Errorf("日志页应把操作人渲染成「张建国（admin）」，实际：%s", snippet(body))
	}
}

func TestDashboardPromptsForMissingName(t *testing.T) {
	c := newTestApp(t)
	c.login()

	_, body := c.get("/")
	if !strings.Contains(body, "尚未填写") {
		t.Error("未填姓名时仪表盘应提示一次")
	}

	setFullName(t, c, "张建国")
	_, body = c.get("/")
	if strings.Contains(body, "尚未填写") {
		t.Error("填了姓名之后不该再提示")
	}
}

func TestBackfillRewritesLegacyRecords(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c) // 先造出一批以 admin 为经办人的历史数据
	setFullName(t, c, "张建国")

	// 账户设置页应报出待回填条数
	_, body := c.get("/account")
	if !strings.Contains(body, "历史经办人回填") {
		t.Fatalf("账户设置页未出现回填面板：%s", snippet(body))
	}

	resp, body := c.post("/account/backfill-operator",
		url.Values{"csrf_token": {c.csrf("/account")}})
	if resp.StatusCode != 302 {
		t.Fatalf("回填失败: %d %s", resp.StatusCode, snippet(body))
	}

	var n int
	db.QueryRow("SELECT COUNT(*) FROM personnel_info WHERE operator = 'admin'").Scan(&n)
	if n != 0 {
		t.Errorf("回填后仍有 %d 条业务记录以 admin 为经办人", n)
	}
	db.QueryRow("SELECT COUNT(*) FROM personnel_info WHERE operator = '张建国'").Scan(&n)
	if n == 0 {
		t.Error("回填后没有以真实姓名为经办人的业务记录")
	}
	// 审计痕迹不能被回填改掉
	db.QueryRow("SELECT COUNT(*) FROM operation_logs WHERE operator = '张建国'").Scan(&n)
	if n != 0 {
		t.Errorf("回填动了操作日志：%d 条 operator 变成了姓名", n)
	}
}

func TestBackfillRefusedWithoutName(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)

	resp, _ := c.post("/account/backfill-operator",
		url.Values{"csrf_token": {c.csrf("/account")}})
	if resp.StatusCode != 302 {
		t.Fatalf("应重定向回账户页: %d", resp.StatusCode)
	}
	var n int
	db.QueryRow("SELECT COUNT(*) FROM personnel_info WHERE operator = 'admin'").Scan(&n)
	if n == 0 {
		t.Error("没填姓名就把历史数据改了")
	}
}

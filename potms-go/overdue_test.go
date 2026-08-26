// 出国明细列表的「证件逾期未还」分支。
//
// 这个分支此前从未被执行过：gonja 不支持用整数键索引 map，而模板里写的是
// deadlines[row.id]（row.id 是 int64，下发的 map 键却是字符串），一旦真有人逾期
// 就渲染失败、整页 500。没暴露只是因为测试种的出行记录当时还没跨过应还日期。
//
// 所以这里刻意用**相对今天**的日期造数据，让它永远处于逾期状态，
// 不再依赖运行的是哪一天。
package main

import (
	"strings"
	"testing"
	"time"
)

// ymdDaysAgo 返回 n 天前的 YYYYMMDD。
func ymdDaysAgo(n int) string {
	return time.Now().AddDate(0, 0, -n).Format("20060102")
}

// seedOverdueTravel 造一条「早就该交回却没交回」的出行记录。
// 回国 90 天远超 10 个工作日的时限，无论今天是哪天都必然逾期。
func seedOverdueTravel(t *testing.T) {
	t.Helper()
	ago := ymdDaysAgo(90)
	if _, err := db.Exec(
		"INSERT INTO travel_details (id, personnel_filing_id, unit, department, name, position, "+
			"id_number, destination_passport, category, travel_dates, travel_start, travel_end, "+
			"need_new_passport, actual_return_date, passport_collect_date, operator) "+
			"VALUES (900, 1, '总部', '技术部', '逾期某', '科长', ?, '美国/护照', '旅游', ?, ?, ?, "+
			"'否', ?, ?, 'admin')",
		testID, ago+"-"+ago, ago, ago, ago, ymdDaysAgo(120)); err != nil {
		t.Fatalf("造逾期出行记录失败: %v", err)
	}
}

func TestTravelListRendersOverdueBranch(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedOverdueTravel(t)

	resp, body := c.get("/travel/")
	if resp.StatusCode != 200 {
		t.Fatalf("/travel/ → %d：%s", resp.StatusCode, snippet(body))
	}
	if strings.Contains(body, "Unable to") || strings.Contains(body, "unable to execute") {
		t.Fatalf("逾期分支渲染失败：%s", snippet(body))
	}
	if !strings.Contains(body, "逾期未还") {
		t.Error("页面上没有逾期提示块")
	}
	if !strings.Contains(body, "逾期某") {
		t.Error("逾期提示块里没有列出该人员")
	}
	// 应还到期日要真的印出来，不能是空的——那正是 deadlines[row.id] 取不到值的症状
	if !strings.Contains(body, "应还") {
		t.Error("没有显示应还到期日")
	}
	if strings.Contains(body, "应还: )") || strings.Contains(body, "应还 ）") {
		t.Error("应还到期日为空")
	}
}

func TestTravelListOverdueFilter(t *testing.T) {
	c := newTestApp(t)
	c.login()
	seedBusinessData(t, c)
	seedOverdueTravel(t)

	resp, body := c.get("/travel/?passport_status=overdue")
	if resp.StatusCode != 200 {
		t.Fatalf("逾期筛选 → %d：%s", resp.StatusCode, snippet(body))
	}
	if !strings.Contains(body, "逾期某") {
		t.Error("按逾期筛选没有筛出逾期记录")
	}
}

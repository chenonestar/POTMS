// 校验工具 — 对应 Python 版 utils/validators.py
package main

import (
	"fmt"
	"regexp"
	"strings"
	"time"
)

var idWeights = []int{7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2}

const idCheck = "10X98765432"

var digitsOnly = regexp.MustCompile(`^\d+$`)

// validateIDNumber 校验 18 位身份证号，返回 (是否通过, 错误信息)
func validateIDNumber(id string) (bool, string) {
	if len(id) != 18 {
		return false, "身份证号须为18位。"
	}
	if !digitsOnly.MatchString(id[:17]) {
		return false, "身份证号前17位须为数字。"
	}
	total := 0
	for i := 0; i < 17; i++ {
		total += int(id[i]-'0') * idWeights[i]
	}
	expected := string(idCheck[total%11])
	if strings.ToUpper(id[17:]) != expected {
		return false, fmt.Sprintf("身份证校验位不正确，应为 %s。", expected)
	}
	if _, err := time.Parse("20060102", id[6:14]); err != nil {
		return false, "身份证号中出生日期不合法。"
	}
	return true, ""
}

func validateBirthDateMatch(id, birthDate string) (bool, string) {
	if id[6:14] != birthDate {
		return false, fmt.Sprintf("出生日期与身份证号不一致（身份证中为 %s）。", id[6:14])
	}
	return true, ""
}

// validateGenderMatch 性别须与身份证第 17 位顺序码奇偶一致（奇→男，偶→女）
func validateGenderMatch(id, gender string) (bool, string) {
	if len(id) != 18 || id[16] < '0' || id[16] > '9' {
		return true, "" // 号码不合规交由 validateIDNumber 报错
	}
	expected := "女"
	if int(id[16]-'0')%2 == 1 {
		expected = "男"
	}
	if gender != "" && gender != expected {
		return false, fmt.Sprintf("性别与身份证号不一致（身份证中为 %s）。", expected)
	}
	return true, ""
}

// validateDateFormat 校验 YYYYMMDD（拒绝不存在的日期）
func validateDateFormat(s string) (bool, string) {
	if len(s) != 8 {
		return false, "日期格式须为 YYYYMMDD（8位数字）。"
	}
	if !digitsOnly.MatchString(s) {
		return false, "日期须为纯数字。"
	}
	if _, err := time.Parse("20060102", s); err != nil {
		return false, "日期不合法。"
	}
	return true, ""
}

// parseDateInput 清洗日期输入：2023-06-20 / 2023/06/20 / 20230620 → YYYYMMDD
func parseDateInput(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ""
	}
	if digitsOnly.MatchString(raw) && len(raw) == 8 {
		return raw
	}
	for _, sep := range []string{"-", "/", "."} {
		if strings.Contains(raw, sep) {
			parts := strings.Split(raw, sep)
			if len(parts) == 3 {
				return parts[0] + pad2(parts[1]) + pad2(parts[2])
			}
		}
	}
	return raw
}

func pad2(s string) string {
	if len(s) == 1 {
		return "0" + s
	}
	return s
}

func isPartyMember(status string) bool {
	return status == "中共党员" || status == "中共预备党员"
}

var travelRangeRe = regexp.MustCompile(`(\d{4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})`)

// parseTravelRange 从出行日期文本解析 (start, end) YYYYMMDD
func parseTravelRange(text string) (string, string) {
	if text == "" {
		return "", ""
	}
	m := travelRangeRe.FindAllStringSubmatch(text, -1)
	if len(m) == 0 {
		return "", ""
	}
	norm := func(g []string) string { return g[1] + pad2(g[2]) + pad2(g[3]) }
	return norm(m[0]), norm(m[len(m)-1])
}

// formatTravelRange 统一存储格式 YYYY/MM/DD-YYYY/MM/DD（同日折叠为单个）
func formatTravelRange(start, end string) string {
	f := func(s string) string {
		if len(s) != 8 {
			return ""
		}
		return s[:4] + "/" + s[4:6] + "/" + s[6:]
	}
	fs, fe := f(start), f(end)
	if fs != "" && fe != "" && fs != fe {
		return fs + "-" + fe
	}
	if fs != "" {
		return fs
	}
	return fe
}

// validateTravelRange 起止须为真实日期且起始不晚于结束
func validateTravelRange(text string) (bool, string) {
	if strings.TrimSpace(text) == "" {
		return false, "计划出行日期不能为空。"
	}
	start, end := parseTravelRange(text)
	if start == "" || end == "" {
		return false, "计划出行日期格式无法识别，请填「起始-结束」，如 2026-8-1-2026-8-11。"
	}
	if ok, msg := validateDateFormat(start); !ok {
		return false, fmt.Sprintf("起始日期不合法（解析为 %s）：%s", start, msg)
	}
	if ok, msg := validateDateFormat(end); !ok {
		return false, fmt.Sprintf("结束日期不合法（解析为 %s）：%s", end, msg)
	}
	if start > end {
		return false, fmt.Sprintf("起始日期（%s）不应晚于结束日期（%s）。", start, end)
	}
	return true, ""
}

// addWorkingDays 顺延 n 个工作日（仅跳过周六/周日），返回到期日 YYYYMMDD
func addWorkingDays(startYMD string, n int) string {
	if len(startYMD) != 8 || !digitsOnly.MatchString(startYMD) {
		return ""
	}
	d, err := time.Parse("20060102", startYMD)
	if err != nil {
		return ""
	}
	counted := 0
	for counted < n {
		d = d.AddDate(0, 0, 1)
		if wd := d.Weekday(); wd != time.Saturday && wd != time.Sunday {
			counted++
		}
	}
	return d.Format("20060102")
}

func rowStr(r Row, key string) string {
	if v, ok := r[key]; ok && v != nil {
		if s, ok := v.(string); ok {
			return s
		}
		return fmt.Sprintf("%v", v)
	}
	return ""
}

// certOverdueDeadline 证件归还到期日：正常=实际回国日(否则计划结束日)+10工作日；取消=取消日+5工作日
func certOverdueDeadline(r Row) string {
	if rowStr(r, "trip_status") == "cancelled" {
		return addWorkingDays(rowStr(r, "cancel_date"), 5)
	}
	base := rowStr(r, "actual_return_date")
	if base == "" {
		base = rowStr(r, "travel_end")
	}
	return addWorkingDays(base, 10)
}

// isCertOverdue 逾期 = 已领用 + 未归还 + today 严格大于到期日
func isCertOverdue(r Row, today string) bool {
	if rowStr(r, "passport_collect_date") == "" || rowStr(r, "passport_return_date") != "" {
		return false
	}
	deadline := certOverdueDeadline(r)
	return deadline != "" && today > deadline
}

// ---- 公共校验器（对应 check_required / check_dates / check_identity）----
type fieldLabel struct{ Field, Label string }

func checkRequired(data map[string]string, fields []fieldLabel) []string {
	var errs []string
	for _, f := range fields {
		if data[f.Field] == "" {
			errs = append(errs, f.Label+" 为必填项。")
		}
	}
	return errs
}

func checkDates(data map[string]string, fields []fieldLabel) []string {
	var errs []string
	for _, f := range fields {
		if v := data[f.Field]; v != "" {
			if ok, msg := validateDateFormat(v); !ok {
				errs = append(errs, f.Label+": "+msg)
			}
		}
	}
	return errs
}

// checkIdentity 身份证校验位 + 出生/性别一致性（birthField/genderField 传空跳过）
func checkIdentity(data map[string]string, birthField, genderField string) []string {
	var errs []string
	id := data["id_number"]
	if id == "" {
		return errs
	}
	if ok, msg := validateIDNumber(id); !ok {
		return append(errs, "身份证号: "+msg)
	}
	if birthField != "" && data[birthField] != "" {
		if ok, msg := validateBirthDateMatch(id, data[birthField]); !ok {
			errs = append(errs, msg)
		}
	}
	if genderField != "" && data[genderField] != "" {
		if ok, msg := validateGenderMatch(id, data[genderField]); !ok {
			errs = append(errs, msg)
		}
	}
	return errs
}

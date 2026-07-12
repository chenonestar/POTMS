// 校验工具 — 对应 Go validators.go / Python utils/validators.py
use std::collections::HashMap;
use time::{Date, Month, Weekday};

pub type Form = HashMap<String, String>;

const ID_WEIGHTS: [i32; 17] = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2];
const ID_CHECK: &[u8] = b"10X98765432";

fn is_digits(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit())
}

/// 解析 YYYYMMDD → Date（不存在的日期返回 None）
pub fn parse_ymd(s: &str) -> Option<Date> {
    if s.len() != 8 || !is_digits(s) {
        return None;
    }
    let y: i32 = s[0..4].parse().ok()?;
    let m: u8 = s[4..6].parse().ok()?;
    let d: u8 = s[6..8].parse().ok()?;
    let month = Month::try_from(m).ok()?;
    Date::from_calendar_date(y, month, d).ok()
}

pub fn fmt_ymd(d: Date) -> String {
    format!("{:04}{:02}{:02}", d.year(), d.month() as u8, d.day())
}

pub fn validate_id_number(id: &str) -> (bool, String) {
    if id.len() != 18 {
        return (false, "身份证号须为18位。".into());
    }
    if !is_digits(&id[..17]) {
        return (false, "身份证号前17位须为数字。".into());
    }
    let bytes = id.as_bytes();
    let mut total = 0i32;
    for i in 0..17 {
        total += (bytes[i] - b'0') as i32 * ID_WEIGHTS[i];
    }
    let expected = ID_CHECK[(total % 11) as usize] as char;
    if id[17..].to_uppercase() != expected.to_string() {
        return (false, format!("身份证校验位不正确，应为 {expected}。"));
    }
    if parse_ymd(&id[6..14]).is_none() {
        return (false, "身份证号中出生日期不合法。".into());
    }
    (true, String::new())
}

pub fn validate_birth_match(id: &str, birth: &str) -> (bool, String) {
    if &id[6..14] != birth {
        return (false, format!("出生日期与身份证号不一致（身份证中为 {}）。", &id[6..14]));
    }
    (true, String::new())
}

pub fn validate_gender_match(id: &str, gender: &str) -> (bool, String) {
    let bytes = id.as_bytes();
    if id.len() != 18 || !bytes[16].is_ascii_digit() {
        return (true, String::new());
    }
    let expected = if (bytes[16] - b'0') % 2 == 1 { "男" } else { "女" };
    if !gender.is_empty() && gender != expected {
        return (false, format!("性别与身份证号不一致（身份证中为 {expected}）。"));
    }
    (true, String::new())
}

pub fn validate_date_format(s: &str) -> (bool, String) {
    if s.len() != 8 {
        return (false, "日期格式须为 YYYYMMDD（8位数字）。".into());
    }
    if !is_digits(s) {
        return (false, "日期须为纯数字。".into());
    }
    if parse_ymd(s).is_none() {
        return (false, "日期不合法。".into());
    }
    (true, String::new())
}

fn pad2(s: &str) -> String {
    if s.len() == 1 {
        format!("0{s}")
    } else {
        s.to_string()
    }
}

/// 2023-06-20 / 2023/06/20 / 20230620 → YYYYMMDD
pub fn parse_date_input(raw: &str) -> String {
    let raw = raw.trim();
    if raw.is_empty() {
        return String::new();
    }
    if is_digits(raw) && raw.len() == 8 {
        return raw.to_string();
    }
    for sep in ['-', '/', '.'] {
        if raw.contains(sep) {
            let parts: Vec<&str> = raw.split(sep).collect();
            if parts.len() == 3 {
                return format!("{}{}{}", parts[0], pad2(parts[1]), pad2(parts[2]));
            }
        }
    }
    raw.to_string()
}

pub fn is_party_member(status: &str) -> bool {
    status == "中共党员" || status == "中共预备党员"
}

/// 从出行日期文本解析 (start, end) YYYYMMDD（取第一处与最后一处日期）
pub fn parse_travel_range(text: &str) -> (String, String) {
    let matches = scan_dates(text);
    if matches.is_empty() {
        return (String::new(), String::new());
    }
    (matches[0].clone(), matches[matches.len() - 1].clone())
}

// 扫描形如 YYYY[-/.]?M[-/.]?D 的日期片段
fn scan_dates(text: &str) -> Vec<String> {
    let b = text.as_bytes();
    let mut out = vec![];
    let mut i = 0;
    while i + 4 <= b.len() {
        if b[i].is_ascii_digit()
            && b[i + 1].is_ascii_digit()
            && b[i + 2].is_ascii_digit()
            && b[i + 3].is_ascii_digit()
        {
            let year = &text[i..i + 4];
            let mut j = i + 4;
            let sep = |c: u8| c == b'-' || c == b'/' || c == b'.';
            if j < b.len() && sep(b[j]) {
                j += 1;
            }
            let ms = j;
            while j < b.len() && b[j].is_ascii_digit() && j - ms < 2 {
                j += 1;
            }
            let month = &text[ms..j];
            if j < b.len() && sep(b[j]) {
                j += 1;
            }
            let ds = j;
            while j < b.len() && b[j].is_ascii_digit() && j - ds < 2 {
                j += 1;
            }
            let day = &text[ds..j];
            if !month.is_empty() && !day.is_empty() {
                out.push(format!("{year}{}{}", pad2(month), pad2(day)));
                i = j;
                continue;
            }
        }
        i += 1;
    }
    out
}

/// 统一存储格式 YYYY/MM/DD-YYYY/MM/DD（同日折叠）
pub fn format_travel_range(start: &str, end: &str) -> String {
    let f = |s: &str| -> String {
        if s.len() != 8 {
            String::new()
        } else {
            format!("{}/{}/{}", &s[..4], &s[4..6], &s[6..])
        }
    };
    let (fs, fe) = (f(start), f(end));
    if !fs.is_empty() && !fe.is_empty() && fs != fe {
        format!("{fs}-{fe}")
    } else if !fs.is_empty() {
        fs
    } else {
        fe
    }
}

pub fn validate_travel_range(text: &str) -> (bool, String) {
    if text.trim().is_empty() {
        return (false, "计划出行日期不能为空。".into());
    }
    let (start, end) = parse_travel_range(text);
    if start.is_empty() || end.is_empty() {
        return (false, "计划出行日期格式无法识别，请填「起始-结束」，如 2026-8-1-2026-8-11。".into());
    }
    let (ok, msg) = validate_date_format(&start);
    if !ok {
        return (false, format!("起始日期不合法（解析为 {start}）：{msg}"));
    }
    let (ok, msg) = validate_date_format(&end);
    if !ok {
        return (false, format!("结束日期不合法（解析为 {end}）：{msg}"));
    }
    if start > end {
        return (false, format!("起始日期（{start}）不应晚于结束日期（{end}）。"));
    }
    (true, String::new())
}

/// 顺延 n 个工作日（仅跳过周六/周日）
pub fn add_working_days(start_ymd: &str, n: i32) -> String {
    let mut d = match parse_ymd(start_ymd) {
        Some(d) => d,
        None => return String::new(),
    };
    let mut counted = 0;
    while counted < n {
        d = d.next_day().unwrap();
        if d.weekday() != Weekday::Saturday && d.weekday() != Weekday::Sunday {
            counted += 1;
        }
    }
    fmt_ymd(d)
}

// ---- 公共校验器 ----
pub fn check_required(data: &Form, fields: &[(&str, &str)]) -> Vec<String> {
    let mut errs = vec![];
    for (field, label) in fields {
        if data.get(*field).map(|s| s.is_empty()).unwrap_or(true) {
            errs.push(format!("{label} 为必填项。"));
        }
    }
    errs
}

pub fn check_dates(data: &Form, fields: &[(&str, &str)]) -> Vec<String> {
    let mut errs = vec![];
    for (field, label) in fields {
        if let Some(v) = data.get(*field) {
            if !v.is_empty() {
                let (ok, msg) = validate_date_format(v);
                if !ok {
                    errs.push(format!("{label}: {msg}"));
                }
            }
        }
    }
    errs
}

pub fn check_identity(data: &Form, birth_field: &str, gender_field: &str) -> Vec<String> {
    let mut errs = vec![];
    let id = data.get("id_number").cloned().unwrap_or_default();
    if id.is_empty() {
        return errs;
    }
    let (ok, msg) = validate_id_number(&id);
    if !ok {
        errs.push(format!("身份证号: {msg}"));
        return errs;
    }
    if !birth_field.is_empty() {
        if let Some(b) = data.get(birth_field) {
            if !b.is_empty() {
                let (ok, msg) = validate_birth_match(&id, b);
                if !ok {
                    errs.push(msg);
                }
            }
        }
    }
    if !gender_field.is_empty() {
        if let Some(g) = data.get(gender_field) {
            if !g.is_empty() {
                let (ok, msg) = validate_gender_match(&id, g);
                if !ok {
                    errs.push(msg);
                }
            }
        }
    }
    errs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_id_number() {
        assert!(validate_id_number("110101199001012133").0);
        assert!(!validate_id_number("11010119900101213X").0); // 错误校验位
        assert!(!validate_id_number("123").0);
    }

    #[test]
    fn test_gender_match() {
        // 第17位 3 为奇数 → 男
        assert!(validate_gender_match("110101199001012133", "男").0);
        assert!(!validate_gender_match("110101199001012133", "女").0);
    }

    #[test]
    fn test_date_format() {
        assert!(validate_date_format("20260101").0);
        assert!(!validate_date_format("20260230").0); // 2月30日不存在
        assert!(!validate_date_format("2026131").0);
    }

    #[test]
    fn test_working_days() {
        // 2026-08-11(周二) + 10 工作日 → 2026-08-25(周二)
        assert_eq!(add_working_days("20260811", 10), "20260825");
    }

    #[test]
    fn test_travel_range() {
        assert!(validate_travel_range("2026/08/01-2026/08/11").0);
        assert!(!validate_travel_range("2026/08/11-2026/08/01").0); // 起晚于止
        assert_eq!(format_travel_range("20260801", "20260811"), "2026/08/01-2026/08/11");
    }

    #[test]
    fn test_parse_travel_range() {
        let (s, e) = parse_travel_range("2026-8-1-2026-8-11");
        assert_eq!(s, "20260801");
        assert_eq!(e, "20260811");
    }
}

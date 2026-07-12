// 辅助函数 — 时间、令牌、快照、字典/组织/人员数据源、分页
use crate::db::{self, Row};
use rusqlite::types::Value as SqlValue;
use rusqlite::Connection;
use serde_json::{json, Value};

pub fn now_unix() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

pub fn random_token() -> String {
    use rand::RngCore;
    let mut buf = [0u8; 24];
    rand::thread_rng().fill_bytes(&mut buf);
    buf.iter().map(|b| format!("{:02x}", b)).collect()
}

pub fn now_utc_sql() -> String {
    // UTC 时间戳字符串，写入 created_at（store UTC）
    let now = time::OffsetDateTime::now_utc();
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
        now.year(), now.month() as u8, now.day(), now.hour(), now.minute(), now.second()
    )
}

pub fn now_local_ymd(offset_hours: i64) -> String {
    let now = time::OffsetDateTime::now_utc() + time::Duration::hours(offset_hours);
    format!("{:04}{:02}{:02}", now.year(), now.month() as u8, now.day())
}

/// UTC 时间字符串 → 本地（固定偏移），并按 Python strftime 风格格式化
pub fn to_local_time(value: &str, format: &str, offset_hours: i64) -> String {
    let s = value.trim();
    if s.is_empty() {
        return String::new();
    }
    let s = s.replace('T', " ");
    let s = s.split('.').next().unwrap_or(&s);
    let s = if s.len() > 19 { &s[..19] } else { s };
    // 解析 YYYY-MM-DD HH:MM:SS
    let bytes: Vec<&str> = s.splitn(2, ' ').collect();
    if bytes.len() != 2 {
        return value.to_string();
    }
    let date_parts: Vec<&str> = bytes[0].split('-').collect();
    let time_parts: Vec<&str> = bytes[1].split(':').collect();
    if date_parts.len() != 3 || time_parts.len() < 3 {
        return value.to_string();
    }
    let parse = |x: &str| x.parse::<i64>().ok();
    let (y, mo, d, h, mi, se) = match (
        parse(date_parts[0]), parse(date_parts[1]), parse(date_parts[2]),
        parse(time_parts[0]), parse(time_parts[1]), parse(time_parts[2]),
    ) {
        (Some(y), Some(mo), Some(d), Some(h), Some(mi), Some(se)) => (y, mo, d, h, mi, se),
        _ => return value.to_string(),
    };
    let month = match time::Month::try_from(mo as u8) {
        Ok(m) => m,
        Err(_) => return value.to_string(),
    };
    let date = match time::Date::from_calendar_date(y as i32, month, d as u8) {
        Ok(dd) => dd,
        Err(_) => return value.to_string(),
    };
    let dt = date.with_hms(h as u8, mi as u8, se as u8).unwrap().assume_utc()
        + time::Duration::hours(offset_hours);
    let repl = format
        .replace("%Y", &format!("{:04}", dt.year()))
        .replace("%m", &format!("{:02}", dt.month() as u8))
        .replace("%d", &format!("{:02}", dt.day()))
        .replace("%H", &format!("{:02}", dt.hour()))
        .replace("%M", &format!("{:02}", dt.minute()))
        .replace("%S", &format!("{:02}", dt.second()));
    repl
}

pub fn row_str(r: &Row, key: &str) -> String {
    match r.get(key) {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Number(n)) => n.to_string(),
        Some(Value::Bool(b)) => b.to_string(),
        _ => String::new(),
    }
}

pub fn row_i64(r: &Row, key: &str) -> i64 {
    match r.get(key) {
        Some(Value::Number(n)) => n.as_i64().unwrap_or(0),
        Some(Value::String(s)) => s.parse().unwrap_or(0),
        _ => 0,
    }
}

// ---------------------------------------------------------------------------
// 操作日志（含变更前后快照，白名单防注入）
// ---------------------------------------------------------------------------
const SNAPSHOT_TABLES: &[&str] = &[
    "personnel_info", "personnel_filing", "certificates", "travel_details",
    "decontrol_filing", "sys_dict", "sys_org", "sys_submit_unit",
];

pub fn row_snapshot(conn: &Connection, table: &str, id: i64) -> Option<Row> {
    if !SNAPSHOT_TABLES.contains(&table) {
        panic!("row_snapshot: 不允许的表名 {table}");
    }
    db::query_one(conn, &format!("SELECT * FROM {table} WHERE id = ?"), &[SqlValue::Integer(id)])
}

fn clean_snapshot(r: &Option<Row>) -> Value {
    match r {
        None => Value::Null,
        Some(Value::Object(m)) => {
            let mut out = serde_json::Map::new();
            for (k, v) in m {
                if k != "created_at" && k != "updated_at" {
                    out.insert(k.clone(), v.clone());
                }
            }
            Value::Object(out)
        }
        Some(v) => v.clone(),
    }
}

#[allow(clippy::too_many_arguments)]
pub fn log_action(
    conn: &Connection, operator: &str, ip: &str, action: &str, target_type: &str,
    target_id: Option<i64>, detail: &str, before: Option<Row>, after: Option<Row>,
) {
    let snapshot: SqlValue = if before.is_some() || after.is_some() {
        let obj = json!({"before": clean_snapshot(&before), "after": clean_snapshot(&after)});
        SqlValue::Text(obj.to_string())
    } else {
        SqlValue::Null
    };
    let tid = target_id.map(SqlValue::Integer).unwrap_or(SqlValue::Null);
    let det = if detail.is_empty() { SqlValue::Null } else { SqlValue::Text(detail.to_string()) };
    let _ = db::exec(
        conn,
        "INSERT INTO operation_logs (operator, action, target_type, target_id, detail, ip_address, snapshot, created_at) \
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        &[
            SqlValue::Text(operator.to_string()), SqlValue::Text(action.to_string()),
            SqlValue::Text(target_type.to_string()), tid, det, SqlValue::Text(ip.to_string()),
            snapshot, SqlValue::Text(now_utc_sql()),
        ],
    );
}

// ---------------------------------------------------------------------------
// 字典 / 组织 / 报送单位 / 人员选项（模板数据源）
// ---------------------------------------------------------------------------
pub fn get_dict_options(conn: &Connection, category: &str) -> Vec<Row> {
    db::query_maps(
        conn,
        "SELECT code, value FROM sys_dict WHERE category = ? ORDER BY sort_order",
        &[SqlValue::Text(category.to_string())],
    )
}

pub fn get_dict_value(conn: &Connection, category: &str, code: &str) -> String {
    if code.is_empty() {
        return code.to_string();
    }
    match db::query_one(
        conn,
        "SELECT value FROM sys_dict WHERE category = ? AND code = ?",
        &[SqlValue::Text(category.to_string()), SqlValue::Text(code.to_string())],
    ) {
        Some(r) => {
            let v = row_str(&r, "value");
            if v.is_empty() { code.to_string() } else { v }
        }
        None => code.to_string(),
    }
}

pub fn get_org_flat(conn: &Connection) -> Vec<Row> {
    let rows = db::query_maps(conn, "SELECT id, name, parent_id FROM sys_org ORDER BY sort_order, id", &[]);
    let mut children: std::collections::HashMap<i64, Vec<Row>> = std::collections::HashMap::new();
    for r in &rows {
        children.entry(row_i64(r, "parent_id")).or_default().push(r.clone());
    }
    let mut out = vec![];
    fn dfs(children: &std::collections::HashMap<i64, Vec<Row>>, parent: i64, depth: i64, root: i64, out: &mut Vec<Row>) {
        if let Some(list) = children.get(&parent) {
            for r in list {
                let rid = row_i64(r, "id");
                let this_root = if depth == 0 { rid } else { root };
                let indent = if depth >= 1 {
                    "　".repeat((depth - 1) as usize) + "└ "
                } else {
                    String::new()
                };
                out.push(json!({
                    "id": rid, "name": row_str(r, "name"), "parent_id": row_i64(r, "parent_id"),
                    "depth": depth, "root_id": this_root, "indent": indent,
                }));
                dfs(children, rid, depth + 1, this_root, out);
            }
        }
    }
    dfs(&children, 0, 0, 0, &mut out);
    out
}

pub fn get_org_tree_options(conn: &Connection) -> Vec<Row> {
    let rows = db::query_maps(conn, "SELECT id, name, parent_id FROM sys_org ORDER BY parent_id, sort_order", &[]);
    let mut out = vec![];
    fn build(rows: &[Row], parent: i64, depth: usize, out: &mut Vec<Row>) {
        for o in rows {
            if row_i64(o, "parent_id") == parent {
                let prefix = if depth > 0 { "　".repeat(depth) + "└ " } else { String::new() };
                out.push(json!({"id": row_i64(o, "id"), "name": format!("{prefix}{}", row_str(o, "name"))}));
                build(rows, row_i64(o, "id"), depth + 1, out);
            }
        }
    }
    build(&rows, 0, 0, &mut out);
    out
}

pub fn get_submit_units(conn: &Connection) -> Vec<Row> {
    let mut rows = db::query_maps(conn, "SELECT id, name, contact, phone FROM sys_submit_unit ORDER BY sort_order, name", &[]);
    for r in &mut rows {
        if let Value::Object(m) = r {
            m.entry("contact").or_insert(json!(""));
            if m.get("contact") == Some(&Value::Null) { m.insert("contact".into(), json!("")); }
            if m.get("phone") == Some(&Value::Null) { m.insert("phone".into(), json!("")); }
        }
    }
    rows
}

pub fn get_personnel_options(conn: &Connection) -> Vec<Row> {
    let rows = db::query_maps(
        conn,
        "SELECT pf.id, pf.surname, pf.given_name, pf.work_unit, pf.id_number, pf.position_or_title, \
         COALESCE(pi.department, '') AS department, \
         (SELECT value FROM sys_dict WHERE category = 'title' AND code = pi.title) AS title_val \
         FROM personnel_filing pf LEFT JOIN personnel_info pi ON pf.personnel_info_id = pi.id \
         WHERE pf.status = 'active' ORDER BY pf.surname, pf.given_name",
        &[],
    );
    let certs = db::query_maps(conn, "SELECT personnel_filing_id, passport_no, hm_pass_no, tw_pass_no FROM certificates", &[]);
    let mut cert_map: std::collections::HashMap<i64, Vec<String>> = std::collections::HashMap::new();
    for c in &certs {
        let pid = row_i64(c, "personnel_filing_id");
        for k in ["passport_no", "hm_pass_no", "tw_pass_no"] {
            let v = row_str(c, k);
            if !v.is_empty() {
                let e = cert_map.entry(pid).or_default();
                if !e.contains(&v) {
                    e.push(v);
                }
            }
        }
    }
    rows.iter().map(|r| {
        let name = format!("{}{}", row_str(r, "surname"), row_str(r, "given_name"));
        json!({
            "id": row_i64(r, "id"), "name": name,
            "full_name": format!("{name} ({})", row_str(r, "work_unit")),
            "unit": row_str(r, "work_unit"), "department": row_str(r, "department"),
            "id_number": row_str(r, "id_number"), "position": row_str(r, "position_or_title"),
            "title": row_str(r, "title_val"),
            "cert_nos": cert_map.get(&row_i64(r, "id")).cloned().unwrap_or_default(),
        })
    }).collect()
}

// ---------------------------------------------------------------------------
// 分页（前端窗口化：全量下发 pages=1；日志页服务端分页）
// ---------------------------------------------------------------------------
pub fn page_map(rows: Vec<Row>, page: i64, total: i64, pages: i64, per_page: i64) -> Value {
    json!({
        "rows": rows, "page": page, "total": total, "pages": pages,
        "has_prev": page > 1, "has_next": page < pages, "per_page": per_page,
    })
}

pub fn list_all(conn: &Connection, sql: &str, params: &[SqlValue]) -> Value {
    let rows = db::query_maps(conn, sql, params);
    let total = rows.len() as i64;
    let per = if total == 0 { 1 } else { total };
    page_map(rows, 1, total, 1, per)
}

pub fn paginate(conn: &Connection, base: &str, params: &[SqlValue], page: i64, per_page: i64) -> Value {
    let total = db::count(conn, &format!("SELECT COUNT(*) FROM ({base}) AS _cnt"), params);
    let mut pages = (total + per_page - 1) / per_page;
    if pages < 1 {
        pages = 1;
    }
    let page = page.clamp(1, pages);
    let offset = (page - 1) * per_page;
    let rows = db::query_maps(conn, &format!("{base} LIMIT {per_page} OFFSET {offset}"), params);
    page_map(rows, page, total, pages, per_page)
}

pub fn detect_surname_split(full: &str) -> (String, String) {
    const COMPOUND: &[&str] = &[
        "欧阳","司马","上官","诸葛","令狐","慕容","独孤","拓跋","尉迟","呼延","端木","皇甫",
        "东方","南宫","夏侯","宇文","长孙","公孙","闾丘","亓官","司寇","巫马","公西","壤驷",
        "乐正","公良","季孙","仲孙","宰父","谷梁","段干","百里","东郭","南门","羊舌","微生",
        "梁丘","左丘","西门","第五",
    ];
    let chars: Vec<char> = full.chars().collect();
    if chars.len() < 2 {
        return (full.to_string(), String::new());
    }
    let head: String = chars[..2].iter().collect();
    if COMPOUND.contains(&head.as_str()) {
        return (head, chars[2..].iter().collect());
    }
    (chars[0..1].iter().collect(), chars[1..].iter().collect())
}

// 证件归还到期日：正常=实际回国日(否则计划结束日)+10工作日；取消=取消日+5工作日
pub fn cert_overdue_deadline(r: &Row) -> String {
    if row_str(r, "trip_status") == "cancelled" {
        return crate::validators::add_working_days(&row_str(r, "cancel_date"), 5);
    }
    let mut base = row_str(r, "actual_return_date");
    if base.is_empty() {
        base = row_str(r, "travel_end");
    }
    crate::validators::add_working_days(&base, 10)
}

// 逾期 = 已领用 + 未归还 + today 严格大于到期日
pub fn is_cert_overdue(r: &Row, today: &str) -> bool {
    if row_str(r, "passport_collect_date").is_empty() || !row_str(r, "passport_return_date").is_empty() {
        return false;
    }
    let deadline = cert_overdue_deadline(r);
    !deadline.is_empty() && today > deadline.as_str()
}

pub fn normalize_residence(raw: &str) -> String {
    raw.trim()
        .replace('省', "")
        .replace("江东区", "鄞州区")
        .replace("鄞县", "鄞州区")
}

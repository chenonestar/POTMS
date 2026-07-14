// 操作日志 / 组织架构 / 数据字典 / 报送单位 / 全局搜索
use crate::{csrf_check, db, ff, flash, helpers, opt_list, page, query_args, redirect, require_login, Req, St};
use axum::extract::{Path, State};
use axum::http::{header, HeaderMap, StatusCode, Uri};
use axum::response::{IntoResponse, Response};
use axum::Form;
use rusqlite::types::Value::{Integer as I, Text as T};
use rusqlite::types::Value as SqlValue;
use serde_json::{json, Value};
use std::collections::HashMap;

type F = HashMap<String, String>;

fn field_label(k: &str) -> String {
    let m: &[(&str, &str)] = &[
        ("unit", "单位"), ("department", "部门"), ("name", "姓名"), ("gender", "性别"),
        ("birth_date", "出生日期"), ("id_number", "身份证号"), ("work_start_date", "参加工作日期"),
        ("education", "学历"), ("degree", "学位"), ("title", "职称"), ("rank", "职级"),
        ("political_status", "政治面貌"), ("party_join_date", "入党日期"), ("position", "职务"),
        ("surname", "中文姓"), ("given_name", "中文名"), ("residence", "户口所在地"),
        ("work_unit", "工作单位"), ("position_or_title", "职务/职称"), ("supervisor_unit", "人事主管单位"),
        ("tag", "标记"), ("informed", "已告知本人"), ("status", "状态"), ("remarks", "备注"),
        ("passport_no", "护照号"), ("passport_expiry", "护照有效期"), ("passport_submit_date", "护照上交日期"),
        ("hm_pass_no", "港澳通行证号"), ("hm_pass_expiry", "港澳有效期"), ("hm_pass_submit_date", "港澳上交日期"),
        ("tw_pass_no", "台湾通行证号"), ("tw_pass_expiry", "台湾有效期"), ("tw_pass_submit_date", "台湾上交日期"),
        ("destination_passport", "地点、证照"), ("category", "类别"), ("travel_dates", "计划出行日期"),
        ("travel_start", "出行起"), ("travel_end", "出行止"), ("approval_date", "批准日期"),
        ("need_new_passport", "是否做证"), ("passport_collect_date", "领用日期"), ("passport_return_date", "归还日期"),
        ("actual_return_date", "实际回国日期"), ("trip_status", "行程状态"), ("cancel_date", "取消日期"),
        ("submit_unit_name", "报送单位"), ("submit_unit_type", "报送类别"), ("submit_contact", "联系人"),
        ("submit_phone", "联系电话"), ("batch_no", "入库批号"), ("reason", "撤控原因"), ("operator", "操作人"),
    ];
    m.iter().find(|(kk, _)| *kk == k).map(|(_, v)| v.to_string()).unwrap_or_else(|| k.to_string())
}

fn vstr(v: &Value) -> String {
    match v {
        Value::Null => String::new(),
        Value::String(s) => s.clone(),
        _ => v.to_string(),
    }
}

fn compute_changes(snapshot: &str) -> Value {
    if snapshot.is_empty() { return Value::Null; }
    let parsed: Value = match serde_json::from_str(snapshot) { Ok(v) => v, Err(_) => return Value::Null };
    let before = parsed.get("before");
    let after = parsed.get("after");
    let obj = |v: Option<&Value>| v.and_then(|x| x.as_object()).cloned();
    let (b, a) = (obj(before), obj(after));
    if let (Some(b), Some(a)) = (&b, &a) {
        let mut diffs = vec![];
        for (k, av) in a {
            let bv = b.get(k).cloned().unwrap_or(Value::Null);
            if vstr(&bv) != vstr(av) {
                diffs.push(json!({"field": field_label(k), "before": bv, "after": av}));
            }
        }
        if diffs.is_empty() { return Value::Null; }
        return json!({"type": "update", "diffs": diffs});
    }
    let collect = |m: &serde_json::Map<String, Value>| -> Vec<Value> {
        m.iter().filter(|(_, v)| !v.is_null() && !vstr(v).is_empty())
            .map(|(k, v)| json!({"field": field_label(k), "value": v})).collect()
    };
    if let Some(a) = &a { return json!({"type": "create", "data": collect(a)}); }
    if let Some(b) = &b { return json!({"type": "delete", "data": collect(b)}); }
    Value::Null
}

pub async fn logs_index(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let q = query_args(&req.query);
    let page_n: i64 = q.get("page").and_then(|s| s.parse().ok()).filter(|n| *n >= 1).unwrap_or(1);
    let mut base = "SELECT * FROM operation_logs WHERE 1=1".to_string();
    let mut p: Vec<SqlValue> = vec![];
    for (key, col) in [("action", "action"), ("target_type", "target_type")] {
        if let Some(v) = q.get(key).map(|x| x.trim()).filter(|x| !x.is_empty()) { base.push_str(&format!(" AND {col} = ?")); p.push(T(v.to_string())); }
    }
    if let Some(d) = q.get("date_from").map(|x| x.trim()).filter(|x| !x.is_empty()) { base.push_str(" AND date(created_at) >= ?"); p.push(T(d.to_string())); }
    if let Some(d) = q.get("date_to").map(|x| x.trim()).filter(|x| !x.is_empty()) { base.push_str(" AND date(created_at) <= ?"); p.push(T(d.to_string())); }
    base.push_str(" ORDER BY created_at DESC");

    let (mut items, log_years) = {
        let conn = st.db.lock().unwrap();
        let items = helpers::paginate(&conn, &base, &p, page_n, crate::config::LOGS_PAGE_SIZE as i64);
        let tz = format!("+{} hours", st.cfg.tz_offset_hours);
        let yrows = db::query_maps(&conn, "SELECT DISTINCT strftime('%Y', datetime(created_at, ?)) AS y FROM operation_logs WHERE created_at IS NOT NULL ORDER BY y DESC", &[T(tz)]);
        let years: Vec<Value> = yrows.iter().map(|r| json!(helpers::row_str(r, "y"))).filter(|v| !v.as_str().unwrap_or("").is_empty()).collect();
        (items, years)
    };
    // 注入 changes
    if let Some(rows) = items.get_mut("rows").and_then(|v| v.as_array_mut()) {
        for row in rows {
            let snap = helpers::row_str(row, "snapshot");
            if let Value::Object(m) = row { m.insert("changes".into(), compute_changes(&snap)); }
        }
    }
    let data = json!({
        "items": items, "action_filter": q.get("action").cloned().unwrap_or_default(),
        "target_filter": q.get("target_type").cloned().unwrap_or_default(),
        "date_from": q.get("date_from").cloned().unwrap_or_default(), "date_to": q.get("date_to").cloned().unwrap_or_default(),
        "action_types": opt_list(&[("create","新建"),("update","修改"),("delete","删除"),("cancel","取消行程"),("restore","恢复行程"),("lock","登录锁定"),("export","导出"),("import","导入"),("backup","备份")]),
        "target_types": opt_list(&[("personnel_info","人员信息表"),("personnel_filing","登记备案表"),("certificates","证照登记表"),("travel_details","出国明细表"),("decontrol_filing","撤控备案表"),("sys_dict","数据字典"),("sys_submit_unit","报送单位"),("users","账户"),("batch","批量导入")]),
        "log_years": log_years,
        "action_badges": {"create":"success","update":"warning","delete":"danger","backup":"secondary"},
        "action_labels": {"create":"新建","update":"修改","delete":"删除","cancel":"取消行程","restore":"恢复行程","lock":"登录锁定","export":"导出","import":"导入","backup":"备份"},
        "target_labels": {"personnel_info":"信息表","personnel_filing":"备案表","certificates":"证照表","travel_details":"明细表","decontrol_filing":"撤控表","batch":"批量导入"},
    });
    page(&st, &mut req, "logs/view.html", data)
}

pub async fn logs_export(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let year = query_args(&req.query).get("year").map(|s| s.trim().to_string()).unwrap_or_default();
    if year.len() != 4 || !year.bytes().all(|b| b.is_ascii_digit()) {
        flash(&mut req, "请选择要归档导出的年份。", "warning");
        return redirect(&st, &req, "logs.index", &[]);
    }
    let (path, filename) = { let conn = st.db.lock().unwrap(); crate::excel::export_logs(&conn, &st.cfg, &req.sess.username(), &year) };
    match path {
        Some(p) => {
            { let conn = st.db.lock().unwrap(); helpers::log_action(&conn, &req.sess.username(), &req.ip, "export", "operation_logs", None, &format!("归档导出 {year} 年操作日志：{filename}"), None, None); }
            send_xlsx(&p, &filename)
        }
        None => { flash(&mut req, "日志归档导出失败。", "danger"); redirect(&st, &req, "logs.index", &[]) }
    }
}

pub fn send_xlsx(path: &std::path::Path, filename: &str) -> Response {
    match std::fs::read(path) {
        Ok(bytes) => {
            let mut resp = (StatusCode::OK, bytes).into_response();
            resp.headers_mut().insert(header::CONTENT_TYPE, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet".parse().unwrap());
            resp.headers_mut().insert(header::CONTENT_DISPOSITION, format!("attachment; filename*=UTF-8''{}", crate::url_escape(filename)).parse().unwrap());
            resp
        }
        Err(_) => (StatusCode::INTERNAL_SERVER_ERROR, "导出文件读取失败").into_response(),
    }
}

// ---- 组织架构 ----
pub async fn org_index(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let (orgs, child_counts) = {
        let conn = st.db.lock().unwrap();
        let orgs = db::query_maps(&conn, "SELECT * FROM sys_org ORDER BY parent_id, sort_order", &[]);
        let mut cc = serde_json::Map::new();
        for o in &orgs { let k = helpers::row_i64(o, "parent_id").to_string(); let n = cc.get(&k).and_then(|v| v.as_i64()).unwrap_or(0); cc.insert(k, json!(n + 1)); }
        (orgs, cc)
    };
    page(&st, &mut req, "organization/tree.html", json!({"orgs": orgs, "child_counts": child_counts}))
}

pub async fn org_add(State(st): State<St>, headers: HeaderMap, uri: Uri, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期。", "danger"); return redirect(&st, &req, "organization.index", &[]); }
    let name = ff(&form, "name");
    let parent: i64 = ff(&form, "parent_id").parse().unwrap_or(0);
    if name.is_empty() { flash(&mut req, "请输入单位/部门名称。", "danger"); return redirect(&st, &req, "organization.index", &[]); }
    { let conn = st.db.lock().unwrap(); db::exec(&conn, "INSERT INTO sys_org (name, parent_id, sort_order) VALUES (?, ?, 0)", &[T(name.clone()), I(parent)]).ok(); helpers::log_action(&conn, &req.sess.username(), &req.ip, "create", "sys_org", None, &name, None, None); }
    flash(&mut req, &format!("已添加：{name}"), "success");
    redirect(&st, &req, "organization.index", &[])
}

pub async fn org_edit(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(org_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期。", "danger"); return redirect(&st, &req, "organization.index", &[]); }
    let name = ff(&form, "name");
    let parent: i64 = ff(&form, "parent_id").parse().unwrap_or(0);
    if name.is_empty() { flash(&mut req, "名称不能为空。", "danger"); return redirect(&st, &req, "organization.index", &[]); }
    { let conn = st.db.lock().unwrap(); db::exec(&conn, "UPDATE sys_org SET name = ?, parent_id = ? WHERE id = ?", &[T(name.clone()), I(parent), I(org_id)]).ok(); helpers::log_action(&conn, &req.sess.username(), &req.ip, "update", "sys_org", Some(org_id), &name, None, None); }
    flash(&mut req, &format!("已更新：{name}"), "success");
    redirect(&st, &req, "organization.index", &[])
}

pub async fn org_delete(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(org_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期。", "danger"); return redirect(&st, &req, "organization.index", &[]); }
    let conn = st.db.lock().unwrap();
    if db::count(&conn, "SELECT COUNT(*) FROM sys_org WHERE parent_id = ?", &[I(org_id)]) > 0 {
        drop(conn); flash(&mut req, "该节点下还有子部门，请先删除子部门。", "danger"); return redirect(&st, &req, "organization.index", &[]);
    }
    db::exec(&conn, "DELETE FROM sys_org WHERE id = ?", &[I(org_id)]).ok();
    helpers::log_action(&conn, &req.sess.username(), &req.ip, "delete", "sys_org", Some(org_id), "", None, None);
    drop(conn);
    flash(&mut req, "已删除。", "info");
    redirect(&st, &req, "organization.index", &[])
}

// ---- 数据字典 ----
const DICT_CATS: &[(&str, &str, &[(&str, &str)])] = &[
    ("education", "学历", &[("personnel_info", "education")]),
    ("degree", "学位", &[("personnel_info", "degree")]),
    ("title", "职称", &[("personnel_info", "title"), ("travel_details", "title")]),
    ("rank", "职级", &[("personnel_info", "rank")]),
    ("political_status", "政治面貌", &[("personnel_info", "political_status"), ("personnel_filing", "political_status"), ("decontrol_filing", "political_status")]),
    ("travel_category", "出国（境）类别", &[("travel_details", "category")]),
    ("submit_unit_type", "报送单位类别", &[("decontrol_filing", "submit_unit_type")]),
    ("supervisor_unit", "人事主管单位", &[("personnel_filing", "supervisor_unit"), ("decontrol_filing", "supervisor_unit")]),
];

fn dict_cat(key: &str) -> Option<&'static (&'static str, &'static str, &'static [(&'static str, &'static str)])> {
    DICT_CATS.iter().find(|(k, _, _)| *k == key)
}

fn dict_usage(conn: &rusqlite::Connection, category: &str, code: &str, value: &str) -> i64 {
    match dict_cat(category) {
        None => 0,
        Some((_, _, refs)) => refs.iter().map(|(tbl, col)| db::count(conn, &format!("SELECT COUNT(*) FROM {tbl} WHERE {col} = ? OR {col} = ?"), &[T(code.to_string()), T(value.to_string())])).sum(),
    }
}

pub async fn dict_index(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let groups = {
        let conn = st.db.lock().unwrap();
        DICT_CATS.iter().map(|(key, label, _)| {
            let items = db::query_maps(&conn, "SELECT * FROM sys_dict WHERE category = ? ORDER BY sort_order, code", &[T(key.to_string())]);
            json!({"key": key, "label": label, "rows": items})
        }).collect::<Vec<_>>()
    };
    page(&st, &mut req, "dict/list.html", json!({"groups": groups}))
}

pub async fn dict_add(State(st): State<St>, headers: HeaderMap, uri: Uri, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期。", "danger"); return redirect(&st, &req, "dict_admin.index", &[]); }
    let category = ff(&form, "category"); let code = ff(&form, "code"); let value = ff(&form, "value");
    let sort: i64 = ff(&form, "sort_order").parse().unwrap_or(0);
    let cat = match dict_cat(&category) { Some(c) => c, None => { flash(&mut req, "无效的字典类别。", "danger"); return redirect(&st, &req, "dict_admin.index", &[]); } };
    if code.is_empty() || value.is_empty() { flash(&mut req, "编码与显示值均为必填。", "danger"); return redirect(&st, &req, "dict_admin.index", &[]); }
    {
        let conn = st.db.lock().unwrap();
        if db::query_one(&conn, "SELECT id FROM sys_dict WHERE category = ? AND code = ?", &[T(category.clone()), T(code.clone())]).is_some() {
            drop(conn); flash(&mut req, &format!("「{}」下编码 {code} 已存在。", cat.1), "warning"); return redirect(&st, &req, "dict_admin.index", &[]);
        }
        db::exec(&conn, "INSERT INTO sys_dict (category, code, value, sort_order) VALUES (?, ?, ?, ?)", &[T(category), T(code.clone()), T(value.clone()), I(sort)]).ok();
        let id = conn.last_insert_rowid();
        let after = helpers::row_snapshot(&conn, "sys_dict", id);
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "create", "sys_dict", Some(id), &format!("{}: {code}={value}", cat.1), None, after);
    }
    flash(&mut req, "字典项已添加。", "success");
    redirect(&st, &req, "dict_admin.index", &[])
}

pub async fn dict_edit(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(dict_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期。", "danger"); return redirect(&st, &req, "dict_admin.index", &[]); }
    let value = ff(&form, "value"); let sort: i64 = ff(&form, "sort_order").parse().unwrap_or(0);
    let conn = st.db.lock().unwrap();
    let before = db::query_one(&conn, "SELECT * FROM sys_dict WHERE id = ?", &[I(dict_id)]);
    if before.is_none() { drop(conn); flash(&mut req, "字典项不存在。", "danger"); return redirect(&st, &req, "dict_admin.index", &[]); }
    if value.is_empty() { drop(conn); flash(&mut req, "显示值为必填。", "danger"); return redirect(&st, &req, "dict_admin.index", &[]); }
    db::exec(&conn, "UPDATE sys_dict SET value = ?, sort_order = ? WHERE id = ?", &[T(value), I(sort), I(dict_id)]).ok();
    let after = helpers::row_snapshot(&conn, "sys_dict", dict_id);
    helpers::log_action(&conn, &req.sess.username(), &req.ip, "update", "sys_dict", Some(dict_id), "", before, after);
    drop(conn);
    flash(&mut req, "字典项已更新。", "success");
    redirect(&st, &req, "dict_admin.index", &[])
}

pub async fn dict_delete(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(dict_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期。", "danger"); return redirect(&st, &req, "dict_admin.index", &[]); }
    let conn = st.db.lock().unwrap();
    let row = db::query_one(&conn, "SELECT * FROM sys_dict WHERE id = ?", &[I(dict_id)]);
    let row = match row { Some(r) => r, None => { drop(conn); flash(&mut req, "字典项不存在。", "danger"); return redirect(&st, &req, "dict_admin.index", &[]); } };
    let used = dict_usage(&conn, &helpers::row_str(&row, "category"), &helpers::row_str(&row, "code"), &helpers::row_str(&row, "value"));
    if used > 0 {
        drop(conn); flash(&mut req, &format!("「{}」已被 {used} 条记录使用，不能删除（可改用编辑或保留）。", helpers::row_str(&row, "value")), "warning"); return redirect(&st, &req, "dict_admin.index", &[]);
    }
    db::exec(&conn, "DELETE FROM sys_dict WHERE id = ?", &[I(dict_id)]).ok();
    helpers::log_action(&conn, &req.sess.username(), &req.ip, "delete", "sys_dict", Some(dict_id), "", Some(row), None);
    drop(conn);
    flash(&mut req, "字典项已删除。", "info");
    redirect(&st, &req, "dict_admin.index", &[])
}

// ---- 报送单位 ----
pub async fn su_index(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let rows = { let conn = st.db.lock().unwrap(); db::query_maps(&conn, "SELECT * FROM sys_submit_unit ORDER BY sort_order, name", &[]) };
    page(&st, &mut req, "submit_unit/list.html", json!({"rows": rows}))
}

pub async fn su_add(State(st): State<St>, headers: HeaderMap, uri: Uri, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期。", "danger"); return redirect(&st, &req, "submit_unit.index", &[]); }
    let name = ff(&form, "name");
    if name.is_empty() { flash(&mut req, "单位名称为必填。", "danger"); return redirect(&st, &req, "submit_unit.index", &[]); }
    {
        let conn = st.db.lock().unwrap();
        if db::query_one(&conn, "SELECT id FROM sys_submit_unit WHERE name = ?", &[T(name.clone())]).is_some() {
            drop(conn); flash(&mut req, "该报送单位已存在。", "warning"); return redirect(&st, &req, "submit_unit.index", &[]);
        }
        db::exec(&conn, "INSERT INTO sys_submit_unit (name, contact, phone, sort_order) VALUES (?, ?, ?, ?)", &[T(name.clone()), db::sv_opt(&ff(&form, "contact")), db::sv_opt(&ff(&form, "phone")), I(ff(&form, "sort_order").parse().unwrap_or(0))]).ok();
        let id = conn.last_insert_rowid();
        let after = helpers::row_snapshot(&conn, "sys_submit_unit", id);
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "create", "sys_submit_unit", Some(id), &name, None, after);
    }
    flash(&mut req, "报送单位已添加。", "success");
    redirect(&st, &req, "submit_unit.index", &[])
}

pub async fn su_edit(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(uid): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期。", "danger"); return redirect(&st, &req, "submit_unit.index", &[]); }
    let name = ff(&form, "name");
    let conn = st.db.lock().unwrap();
    let before = db::query_one(&conn, "SELECT * FROM sys_submit_unit WHERE id = ?", &[I(uid)]);
    if before.is_none() { drop(conn); flash(&mut req, "记录不存在。", "danger"); return redirect(&st, &req, "submit_unit.index", &[]); }
    if name.is_empty() { drop(conn); flash(&mut req, "单位名称为必填。", "danger"); return redirect(&st, &req, "submit_unit.index", &[]); }
    db::exec(&conn, "UPDATE sys_submit_unit SET name = ?, contact = ?, phone = ?, sort_order = ? WHERE id = ?", &[T(name), db::sv_opt(&ff(&form, "contact")), db::sv_opt(&ff(&form, "phone")), I(ff(&form, "sort_order").parse().unwrap_or(0)), I(uid)]).ok();
    let after = helpers::row_snapshot(&conn, "sys_submit_unit", uid);
    helpers::log_action(&conn, &req.sess.username(), &req.ip, "update", "sys_submit_unit", Some(uid), "", before, after);
    drop(conn);
    flash(&mut req, "报送单位已更新。", "success");
    redirect(&st, &req, "submit_unit.index", &[])
}

pub async fn su_delete(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(uid): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期。", "danger"); return redirect(&st, &req, "submit_unit.index", &[]); }
    let conn = st.db.lock().unwrap();
    let row = db::query_one(&conn, "SELECT * FROM sys_submit_unit WHERE id = ?", &[I(uid)]);
    let row = match row { Some(r) => r, None => { drop(conn); flash(&mut req, "记录不存在。", "danger"); return redirect(&st, &req, "submit_unit.index", &[]); } };
    let name = helpers::row_str(&row, "name");
    let used = db::count(&conn, "SELECT COUNT(*) FROM decontrol_filing WHERE submit_unit_name = ?", &[T(name.clone())]);
    if used > 0 { drop(conn); flash(&mut req, &format!("「{name}」已被 {used} 条撤控记录使用，不能删除。"), "warning"); return redirect(&st, &req, "submit_unit.index", &[]); }
    db::exec(&conn, "DELETE FROM sys_submit_unit WHERE id = ?", &[I(uid)]).ok();
    helpers::log_action(&conn, &req.sess.username(), &req.ip, "delete", "sys_submit_unit", Some(uid), "", Some(row), None);
    drop(conn);
    flash(&mut req, "报送单位已删除。", "info");
    redirect(&st, &req, "submit_unit.index", &[])
}

// ---- 全局搜索 ----
pub async fn search(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let q = query_args(&req.query).get("q").map(|s| s.trim().to_string()).unwrap_or_default();
    let mut results = json!({"personnel": [], "certificate": [], "travel": [], "decontrol": []});
    let mut total = 0i64;
    if !q.is_empty() {
        let like = format!("%{q}%");
        let conn = st.db.lock().unwrap();
        let l = |n: usize| -> Vec<SqlValue> { let mut v = vec![]; for _ in 0..n { v.push(T(like.clone())); } v.push(I(50)); v };
        let p = db::query_maps(&conn, "SELECT id, surname, given_name, id_number, work_unit, status FROM personnel_filing WHERE surname||given_name LIKE ? OR id_number LIKE ? ORDER BY created_at DESC LIMIT ?", &l(2));
        let c = db::query_maps(&conn, "SELECT id, name, unit, passport_no, hm_pass_no, tw_pass_no FROM certificates WHERE name LIKE ? OR passport_no LIKE ? OR hm_pass_no LIKE ? OR tw_pass_no LIKE ? ORDER BY created_at DESC LIMIT ?", &l(4));
        let t = db::query_maps(&conn, "SELECT id, name, destination_passport, travel_dates, trip_status FROM travel_details WHERE name LIKE ? OR destination_passport LIKE ? OR passport_no LIKE ? ORDER BY created_at DESC LIMIT ?", &l(3));
        let d = db::query_maps(&conn, "SELECT id, surname, given_name, work_unit, reason, decontrol_date FROM decontrol_filing WHERE surname||given_name LIKE ? OR id_number LIKE ? OR reason LIKE ? ORDER BY created_at DESC LIMIT ?", &l(3));
        total = (p.len() + c.len() + t.len() + d.len()) as i64;
        results = json!({"personnel": p, "certificate": c, "travel": t, "decontrol": d});
    }
    page(&st, &mut req, "search/results.html", json!({"q": q, "results": results, "total": total}))
}

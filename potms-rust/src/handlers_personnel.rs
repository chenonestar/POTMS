// 人员备案：信息登记表 + 登记备案表（含 #2-#5 数据完整性）
use crate::validators::{self as v, Form as VForm};
use crate::{csrf_check, db, ff, flash, helpers, opt_list, page, query_args, redirect, require_login, Req, St};
use axum::extract::{Path, State};
use axum::http::{HeaderMap, Uri};
use axum::response::Response;
use axum::Form;
use rusqlite::types::Value::{Integer as I, Text as T};
use rusqlite::types::Value as SqlValue;
use serde_json::json;
use std::collections::HashMap;

type F = HashMap<String, String>;

pub fn personnel_filters(q: &F, ids: &[i64]) -> (String, Vec<SqlValue>) {
    let mut where_ = String::new();
    let mut params: Vec<SqlValue> = vec![];
    let s = q.get("search").map(|x| x.trim()).unwrap_or("");
    if !s.is_empty() {
        where_.push_str(" AND (pf.surname||pf.given_name LIKE ? OR pf.id_number LIKE ? OR pf.work_unit LIKE ?)");
        let like = format!("%{s}%");
        params.push(T(like.clone())); params.push(T(like.clone())); params.push(T(like));
    }
    for (key, col) in [("status", "pf.status"), ("political_status", "pf.political_status"), ("rank", "pi.rank"), ("gender", "pf.gender"), ("tag", "pf.tag")] {
        let val = q.get(key).map(|x| x.trim()).unwrap_or("");
        if !val.is_empty() {
            where_.push_str(&format!(" AND {col} = ?"));
            params.push(T(val.to_string()));
        }
    }
    let res = q.get("residence").map(|x| x.trim()).unwrap_or("");
    if !res.is_empty() {
        where_.push_str(" AND pf.residence LIKE ?");
        params.push(T(format!("%{res}%")));
    }
    if !ids.is_empty() {
        let ph = vec!["?"; ids.len()].join(",");
        where_.push_str(&format!(" AND pf.id IN ({ph})"));
        for id in ids { params.push(I(*id)); }
    }
    (where_, params)
}

pub async fn list(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    let q = query_args(&req.query);
    let (where_, params) = personnel_filters(&q, &[]);
    let base = format!(
        "SELECT pf.id, pf.surname, pf.given_name, pf.gender, pf.birth_date, \
         pf.id_number, pf.work_unit, pf.position_or_title, pf.tag, pf.status, \
         pf.created_at, pi.id AS info_id \
         FROM personnel_filing pf LEFT JOIN personnel_info pi ON pf.personnel_info_id = pi.id \
         WHERE 1=1{where_}"
    );
    let sort_by = {
        let s = q.get("sort").map(|x| x.trim().to_string()).unwrap_or_default();
        if s.is_empty() { "created_at_desc".to_string() } else { s }
    };
    let order = match sort_by.as_str() {
        "created_at_asc" => "pf.created_at ASC",
        "name_asc" => "pf.surname||pf.given_name ASC",
        "birth_date_asc" => "pf.birth_date ASC",
        _ => "pf.created_at DESC",
    };
    let (items, political_opts, rank_opts) = {
        let conn = st.db.lock().unwrap();
        let items = helpers::list_all(&conn, &format!("{base} ORDER BY {order}"), &params);
        (items, helpers::get_dict_options(&conn, "political_status"), helpers::get_dict_options(&conn, "rank"))
    };
    let data = json!({
        "items": items, "search": q.get("search").cloned().unwrap_or_default(),
        "status_filter": q.get("status").cloned().unwrap_or_default(),
        "political_filter": q.get("political_status").cloned().unwrap_or_default(),
        "rank_filter": q.get("rank").cloned().unwrap_or_default(),
        "gender_filter": q.get("gender").cloned().unwrap_or_default(),
        "tag_filter": q.get("tag").cloned().unwrap_or_default(),
        "residence_filter": q.get("residence").cloned().unwrap_or_default(),
        "sort_by": sort_by,
        "statuses": opt_list(&[("active", "有效"), ("decontrolled", "已撤控")]),
        "political_opts": political_opts, "rank_opts": rank_opts,
        "tags": opt_list(&[("新增", "新增"), ("更新", "更新")]),
        "genders": opt_list(&[("男", "男"), ("女", "女")]),
        "sorts": json!([
            {"code": "created_at_desc", "value": "录入时间（新→旧）"},
            {"code": "created_at_asc", "value": "录入时间（旧→新）"},
            {"code": "name_asc", "value": "姓名排序"},
            {"code": "birth_date_asc", "value": "出生日期"},
        ]),
    });
    page(&st, &mut req, "personnel/list.html", data)
}

// ---- 信息登记表 ----
fn extract_info(form: &F, operator: &str) -> VForm {
    let mut m = VForm::new();
    for k in ["unit", "department", "name", "gender", "education", "degree", "title", "rank", "political_status", "position"] {
        m.insert(k.into(), ff(form, k));
    }
    m.insert("birth_date".into(), v::parse_date_input(&ff(form, "birth_date")));
    m.insert("id_number".into(), ff(form, "id_number").to_uppercase());
    m.insert("work_start_date".into(), v::parse_date_input(&ff(form, "work_start_date")));
    m.insert("party_join_date".into(), v::parse_date_input(&ff(form, "party_join_date")));
    m.insert("operator".into(), operator.to_string());
    m
}

fn validate_info(data: &VForm) -> Vec<String> {
    let mut errs = v::check_required(data, &[
        ("unit", "单位"), ("department", "部门"), ("name", "姓名"), ("gender", "性别"),
        ("birth_date", "出生日期"), ("id_number", "身份证号"), ("work_start_date", "参加工作日期"),
        ("education", "学历"), ("degree", "学位"), ("title", "职称"), ("rank", "职级"),
        ("political_status", "政治面貌"), ("position", "职务（岗位名称）"),
    ]);
    errs.extend(v::check_dates(data, &[("birth_date", "出生日期"), ("work_start_date", "参加工作日期"), ("party_join_date", "入党日期")]));
    errs.extend(v::check_identity(data, "birth_date", "gender"));
    if v::is_party_member(data.get("political_status").map(|s| s.as_str()).unwrap_or("")) && data.get("party_join_date").map(|s| s.is_empty()).unwrap_or(true) {
        errs.push("中共党员/预备党员须填写入党日期。".into());
    }
    errs
}

fn info_params(d: &VForm) -> Vec<SqlValue> {
    ["unit", "department", "name", "gender", "birth_date", "id_number", "work_start_date",
     "education", "degree", "title", "rank", "political_status", "party_join_date", "position", "operator"]
        .iter().map(|k| db::sv_opt(d.get(*k).map(|s| s.as_str()).unwrap_or(""))).collect()
}

pub async fn info_new_get(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    page(&st, &mut req, "personnel/info_form.html", json!({"data": {}, "editing": false}))
}

pub async fn info_new_post(State(st): State<St>, headers: HeaderMap, uri: Uri, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "personnel.list", &[]); }
    let data = extract_info(&form, &req.sess.username());
    let mut errs = validate_info(&data);
    let id_number = data.get("id_number").cloned().unwrap_or_default();
    if errs.is_empty() && !id_number.is_empty() {
        let conn = st.db.lock().unwrap();
        if let Some(dup) = db::query_one(&conn, "SELECT id FROM personnel_info WHERE id_number = ? LIMIT 1", &[T(id_number.clone())]) {
            errs.push(format!("该身份证号已存在信息登记表（编号 {}），如需修改请直接编辑该记录，请勿重复录入。", helpers::row_i64(&dup, "id")));
        }
    }
    if !errs.is_empty() {
        for e in &errs { flash(&mut req, e, "danger"); }
        return page(&st, &mut req, "personnel/info_form.html", json!({"data": vform_json(&data), "editing": false}));
    }
    let info_id = {
        let conn = st.db.lock().unwrap();
        db::exec(&conn, "INSERT INTO personnel_info (unit, department, name, gender, birth_date, id_number, work_start_date, education, degree, title, rank, political_status, party_join_date, position, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", &info_params(&data)).ok();
        let id = conn.last_insert_rowid();
        let after = helpers::row_snapshot(&conn, "personnel_info", id);
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "create", "personnel_info", Some(id), "", None, after);
        id
    };
    flash(&mut req, "备案人员信息登记表已保存。请继续填写登记备案表。", "success");
    redirect(&st, &req, "personnel.filing_new", &[("info_id".into(), info_id.to_string())])
}

pub async fn info_edit_get(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(info_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    let row = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT * FROM personnel_info WHERE id = ?", &[I(info_id)]) };
    match row {
        None => { flash(&mut req, "记录不存在。", "danger"); redirect(&st, &req, "personnel.list", &[]) }
        Some(r) => page(&st, &mut req, "personnel/info_form.html", json!({"data": r, "editing": true, "info_id": info_id})),
    }
}

pub async fn info_edit_post(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(info_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "personnel.list", &[]); }
    let exists = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT id FROM personnel_info WHERE id = ?", &[I(info_id)]).is_some() };
    if !exists { flash(&mut req, "记录不存在。", "danger"); return redirect(&st, &req, "personnel.list", &[]); }
    let data = extract_info(&form, &req.sess.username());
    let errs = validate_info(&data);
    if !errs.is_empty() {
        for e in &errs { flash(&mut req, e, "danger"); }
        return page(&st, &mut req, "personnel/info_form.html", json!({"data": vform_json(&data), "editing": true, "info_id": info_id}));
    }
    {
        let conn = st.db.lock().unwrap();
        let before = helpers::row_snapshot(&conn, "personnel_info", info_id);
        let mut p = info_params(&data);
        p.push(I(info_id));
        db::exec(&conn, "UPDATE personnel_info SET unit=?, department=?, name=?, gender=?, birth_date=?, id_number=?, work_start_date=?, education=?, degree=?, title=?, rank=?, political_status=?, party_join_date=?, position=?, operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", &p).ok();
        let after = helpers::row_snapshot(&conn, "personnel_info", info_id);
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "update", "personnel_info", Some(info_id), "", before, after);
    }
    flash(&mut req, "信息登记表已更新。", "success");
    redirect(&st, &req, "personnel.list", &[])
}

// ---- 登记备案表 ----
fn extract_filing(form: &F, operator: &str) -> VForm {
    let mut m = VForm::new();
    for k in ["surname", "given_name", "gender", "political_status", "work_unit", "position_or_title", "supervisor_unit", "remarks"] {
        m.insert(k.into(), ff(form, k));
    }
    m.insert("birth_date".into(), v::parse_date_input(&ff(form, "birth_date")));
    m.insert("id_number".into(), ff(form, "id_number").to_uppercase());
    m.insert("residence".into(), helpers::normalize_residence(&ff(form, "residence")));
    let tag = { let t = ff(form, "tag"); if t.is_empty() { "新增".into() } else { t } };
    let informed = { let t = ff(form, "informed"); if t.is_empty() { "否".into() } else { t } };
    m.insert("tag".into(), tag);
    m.insert("informed".into(), informed);
    m.insert("operator".into(), operator.to_string());
    m
}

fn validate_filing(data: &VForm, skip_dup: bool, conn: &rusqlite::Connection) -> Vec<String> {
    let mut errs = v::check_required(data, &[
        ("surname", "中文姓"), ("given_name", "中文名"), ("gender", "性别"), ("birth_date", "出生日期"),
        ("id_number", "身份证号"), ("residence", "户口所在地"), ("political_status", "政治面貌"),
        ("work_unit", "工作单位"), ("position_or_title", "职务（级）或职称"), ("supervisor_unit", "人事主管单位"),
        ("tag", "标记"), ("informed", "已告知本人"),
    ]);
    errs.extend(v::check_dates(data, &[("birth_date", "出生日期")]));
    errs.extend(v::check_identity(data, "birth_date", "gender"));
    let id = data.get("id_number").cloned().unwrap_or_default();
    if !id.is_empty() && !skip_dup {
        if db::query_one(conn, "SELECT id FROM personnel_filing WHERE id_number = ? AND status = 'active'", &[T(id)]).is_some() {
            errs.push("该身份证号已存在有效备案记录，请勿重复登记。".into());
        }
    }
    errs
}

fn filing_params(d: &VForm) -> Vec<SqlValue> {
    ["surname", "given_name", "gender", "birth_date", "id_number", "residence", "political_status",
     "work_unit", "position_or_title", "supervisor_unit", "tag", "informed", "remarks", "operator"]
        .iter().map(|k| db::sv_opt(d.get(*k).map(|s| s.as_str()).unwrap_or(""))).collect()
}

pub async fn filing_new_get(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    let info_id: i64 = query_args(&req.query).get("info_id").and_then(|s| s.parse().ok()).unwrap_or(0);
    let prefill = if info_id > 0 {
        let conn = st.db.lock().unwrap();
        match db::query_one(&conn, "SELECT * FROM personnel_info WHERE id = ?", &[I(info_id)]) {
            Some(info) => {
                let (surname, given) = helpers::detect_surname_split(&helpers::row_str(&info, "name"));
                let mut pos = helpers::row_str(&info, "position");
                if pos.is_empty() { pos = helpers::row_str(&info, "rank"); }
                json!({
                    "surname": surname, "given_name": given,
                    "gender": helpers::row_str(&info, "gender"), "birth_date": helpers::row_str(&info, "birth_date"),
                    "id_number": helpers::row_str(&info, "id_number"), "political_status": helpers::row_str(&info, "political_status"),
                    "work_unit": helpers::row_str(&info, "unit"), "position_or_title": pos,
                })
            }
            None => json!({}),
        }
    } else { json!({}) };
    page(&st, &mut req, "personnel/filing_form.html", json!({"data": prefill, "editing": false, "info_id": info_id}))
}

pub async fn filing_new_post(State(st): State<St>, headers: HeaderMap, uri: Uri, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "personnel.list", &[]); }
    let info_id: i64 = query_args(&req.query).get("info_id").and_then(|s| s.parse().ok()).unwrap_or(0);
    let data = extract_filing(&form, &req.sess.username());
    let errs = { let conn = st.db.lock().unwrap(); validate_filing(&data, false, &conn) };
    if !errs.is_empty() {
        for e in &errs { flash(&mut req, e, "danger"); }
        return page(&st, &mut req, "personnel/filing_form.html", json!({"data": vform_json(&data), "editing": false, "info_id": info_id}));
    }
    let id_number = data.get("id_number").cloned().unwrap_or_default();
    let mut relinked: Option<i64> = None;
    {
        let conn = st.db.lock().unwrap();
        let mut p = filing_params(&data);
        p.insert(0, if info_id > 0 { I(info_id) } else { SqlValue::Null });
        db::exec(&conn, "INSERT INTO personnel_filing (personnel_info_id, surname, given_name, gender, birth_date, id_number, residence, political_status, work_unit, position_or_title, supervisor_unit, tag, informed, remarks, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", &p).ok();
        let filing_id = conn.last_insert_rowid();
        if let Some(prior) = db::query_one(&conn, "SELECT id FROM personnel_filing WHERE id_number = ? AND status = 'decontrolled' AND replaced_by_id IS NULL AND id != ? ORDER BY id DESC LIMIT 1", &[T(id_number), I(filing_id)]) {
            let pid = helpers::row_i64(&prior, "id");
            db::exec(&conn, "UPDATE personnel_filing SET replaced_by_id = ? WHERE id = ?", &[I(filing_id), I(pid)]).ok();
            db::exec(&conn, "UPDATE personnel_filing SET tag = '更新' WHERE id = ?", &[I(filing_id)]).ok();
            relinked = Some(pid);
        }
        let after = helpers::row_snapshot(&conn, "personnel_filing", filing_id);
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "create", "personnel_filing", Some(filing_id), "", None, after);
    }
    if let Some(pid) = relinked {
        flash(&mut req, &format!("已与原撤控记录（#{pid}）建立关联，本记录标记为\u{201c}更新\u{201d}。"), "info");
    }
    flash(&mut req, "登记备案表已保存。", "success");
    redirect(&st, &req, "personnel.list", &[])
}

pub async fn filing_edit_get(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(filing_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    let row = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT * FROM personnel_filing WHERE id = ?", &[I(filing_id)]) };
    match row {
        None => { flash(&mut req, "记录不存在。", "danger"); redirect(&st, &req, "personnel.list", &[]) }
        Some(r) => page(&st, &mut req, "personnel/filing_form.html", json!({"data": r, "editing": true, "filing_id": filing_id})),
    }
}

pub async fn filing_edit_post(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(filing_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "personnel.list", &[]); }
    let exists = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT id FROM personnel_filing WHERE id = ?", &[I(filing_id)]).is_some() };
    if !exists { flash(&mut req, "记录不存在。", "danger"); return redirect(&st, &req, "personnel.list", &[]); }
    let data = extract_filing(&form, &req.sess.username());
    let errs = { let conn = st.db.lock().unwrap(); validate_filing(&data, true, &conn) };
    if !errs.is_empty() {
        for e in &errs { flash(&mut req, e, "danger"); }
        return page(&st, &mut req, "personnel/filing_form.html", json!({"data": vform_json(&data), "editing": true, "filing_id": filing_id}));
    }
    {
        let conn = st.db.lock().unwrap();
        let before = helpers::row_snapshot(&conn, "personnel_filing", filing_id);
        let mut p = filing_params(&data);
        p.push(I(filing_id));
        db::exec(&conn, "UPDATE personnel_filing SET surname=?, given_name=?, gender=?, birth_date=?, id_number=?, residence=?, political_status=?, work_unit=?, position_or_title=?, supervisor_unit=?, tag=?, informed=?, remarks=?, operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", &p).ok();
        let after = helpers::row_snapshot(&conn, "personnel_filing", filing_id);
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "update", "personnel_filing", Some(filing_id), "", before, after);
    }
    flash(&mut req, "登记备案表已更新。", "success");
    redirect(&st, &req, "personnel.list", &[])
}

pub async fn view(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(filing_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    let data = {
        let conn = st.db.lock().unwrap();
        let filing = match db::query_one(&conn, "SELECT * FROM personnel_filing WHERE id = ?", &[I(filing_id)]) {
            Some(f) => f,
            None => { drop(conn); flash(&mut req, "记录不存在。", "danger"); return redirect(&st, &req, "personnel.list", &[]); }
        };
        let info = if filing.get("personnel_info_id").map(|v| !v.is_null()).unwrap_or(false) {
            db::query_one(&conn, "SELECT * FROM personnel_info WHERE id = ?", &[I(helpers::row_i64(&filing, "personnel_info_id"))])
        } else { None };
        let successor = if filing.get("replaced_by_id").map(|v| !v.is_null()).unwrap_or(false) {
            db::query_one(&conn, "SELECT id, surname, given_name, created_at FROM personnel_filing WHERE id = ?", &[I(helpers::row_i64(&filing, "replaced_by_id"))])
        } else { None };
        let predecessor = db::query_one(&conn, "SELECT id, surname, given_name, created_at FROM personnel_filing WHERE replaced_by_id = ?", &[I(filing_id)]);
        json!({"filing": filing, "info": info, "successor": successor, "predecessor": predecessor})
    };
    page(&st, &mut req, "personnel/view.html", data)
}

pub async fn delete(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(filing_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "personnel.list", &[]); }
    let conn = st.db.lock().unwrap();
    if db::query_one(&conn, "SELECT id FROM personnel_filing WHERE id = ?", &[I(filing_id)]).is_none() {
        drop(conn); flash(&mut req, "记录不存在。", "danger"); return redirect(&st, &req, "personnel.list", &[]);
    }
    let cert = db::count(&conn, "SELECT COUNT(*) FROM certificates WHERE personnel_filing_id = ?", &[I(filing_id)]);
    let travel = db::count(&conn, "SELECT COUNT(*) FROM travel_details WHERE personnel_filing_id = ?", &[I(filing_id)]);
    let dec = db::count(&conn, "SELECT COUNT(*) FROM decontrol_filing WHERE personnel_filing_id = ?", &[I(filing_id)]);
    if cert > 0 || travel > 0 || dec > 0 {
        drop(conn);
        flash(&mut req, &format!("该人员名下尚有证照 {cert} 条、出国明细 {travel} 条、撤控记录 {dec} 条，请先删除或处理这些关联记录后再删除备案。"), "danger");
        return redirect(&st, &req, "personnel.list", &[]);
    }
    let before = helpers::row_snapshot(&conn, "personnel_filing", filing_id);
    db::exec(&conn, "DELETE FROM personnel_filing WHERE id = ?", &[I(filing_id)]).ok();
    helpers::log_action(&conn, &req.sess.username(), &req.ip, "delete", "personnel_filing", Some(filing_id), "", before, None);
    drop(conn);
    flash(&mut req, "备案记录已删除。", "info");
    redirect(&st, &req, "personnel.list", &[])
}

// ---- 信息登记表管理（#2）----
pub async fn info_list(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    let q = query_args(&req.query);
    let mut where_ = String::new();
    let mut params: Vec<SqlValue> = vec![];
    let s = q.get("search").map(|x| x.trim()).unwrap_or("");
    if !s.is_empty() {
        where_.push_str(" AND (pi.name LIKE ? OR pi.id_number LIKE ? OR pi.unit LIKE ? OR pi.department LIKE ?)");
        let like = format!("%{s}%");
        for _ in 0..4 { params.push(T(like.clone())); }
    }
    let ref_count = "(SELECT COUNT(*) FROM personnel_filing pf WHERE pf.personnel_info_id = pi.id)";
    match q.get("ref").map(|x| x.trim()).unwrap_or("") {
        "orphan" => where_.push_str(&format!(" AND {ref_count} = 0")),
        "linked" => where_.push_str(&format!(" AND {ref_count} > 0")),
        _ => {}
    }
    let items = {
        let conn = st.db.lock().unwrap();
        helpers::list_all(&conn, &format!("SELECT pi.*, {ref_count} AS filing_count FROM personnel_info pi WHERE 1=1{where_} ORDER BY pi.id"), &params)
    };
    page(&st, &mut req, "personnel/info_list.html", json!({"items": items, "search": q.get("search").cloned().unwrap_or_default(), "ref": q.get("ref").cloned().unwrap_or_default()}))
}

pub async fn info_delete(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(info_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "personnel.info_list", &[]); }
    let conn = st.db.lock().unwrap();
    if db::query_one(&conn, "SELECT id FROM personnel_info WHERE id = ?", &[I(info_id)]).is_none() {
        drop(conn); flash(&mut req, "记录不存在。", "danger"); return redirect(&st, &req, "personnel.info_list", &[]);
    }
    let refs = db::count(&conn, "SELECT COUNT(*) FROM personnel_filing WHERE personnel_info_id = ?", &[I(info_id)]);
    if refs > 0 {
        drop(conn);
        flash(&mut req, &format!("该信息登记表已被 {refs} 条备案记录引用，不能删除。请先删除相关备案记录。"), "danger");
        return redirect(&st, &req, "personnel.info_list", &[]);
    }
    let before = helpers::row_snapshot(&conn, "personnel_info", info_id);
    db::exec(&conn, "DELETE FROM personnel_info WHERE id = ?", &[I(info_id)]).ok();
    helpers::log_action(&conn, &req.sess.username(), &req.ip, "delete", "personnel_info", Some(info_id), "", before, None);
    drop(conn);
    flash(&mut req, "信息登记表已删除。", "info");
    redirect(&st, &req, "personnel.info_list", &[])
}

fn vform_json(d: &VForm) -> serde_json::Value {
    serde_json::to_value(d).unwrap_or(json!({}))
}

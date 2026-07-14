// 撤控备案
use crate::validators::{self as v, Form as VForm};
use crate::{csrf_check, db, ff, flash, helpers, page, query_args, redirect, require_login, Req, St};
use axum::extract::{Path, State};
use axum::http::{HeaderMap, Uri};
use axum::response::Response;
use axum::Form;
use rusqlite::types::Value::{Integer as I, Text as T};
use rusqlite::types::Value as SqlValue;
use serde_json::json;
use std::collections::HashMap;

type F = HashMap<String, String>;

pub fn decontrol_filters(q: &F, ids: &[i64]) -> (String, Vec<SqlValue>) {
    let mut w = String::new();
    let mut p: Vec<SqlValue> = vec![];
    let s = q.get("search").map(|x| x.trim()).unwrap_or("");
    if !s.is_empty() {
        w.push_str(" AND (surname||given_name LIKE ? OR id_number LIKE ? OR reason LIKE ?)");
        let like = format!("%{s}%"); p.push(T(like.clone())); p.push(T(like.clone())); p.push(T(like));
    }
    if let Some(t) = q.get("submit_unit_type").map(|x| x.trim()).filter(|x| !x.is_empty()) {
        w.push_str(" AND submit_unit_type = ?"); p.push(T(t.to_string()));
    }
    if !ids.is_empty() {
        w.push_str(&format!(" AND id IN ({})", vec!["?"; ids.len()].join(",")));
        for id in ids { p.push(I(*id)); }
    }
    (w, p)
}

pub async fn list(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let q = query_args(&req.query);
    let (w, p) = decontrol_filters(&q, &[]);
    let (items, opts) = {
        let conn = st.db.lock().unwrap();
        (helpers::list_all(&conn, &format!("SELECT * FROM decontrol_filing WHERE 1=1{w} ORDER BY created_at DESC"), &p),
         helpers::get_dict_options(&conn, "submit_unit_type"))
    };
    page(&st, &mut req, "decontrol/list.html", json!({
        "items": items, "search": q.get("search").cloned().unwrap_or_default(),
        "unit_type_filter": q.get("submit_unit_type").cloned().unwrap_or_default(), "unit_type_opts": opts,
    }))
}

fn extract(form: &F, operator: &str, tz: i64) -> VForm {
    let mut m = VForm::new();
    for k in ["surname", "given_name", "gender", "political_status", "work_unit", "supervisor_unit",
              "submit_unit_name", "submit_unit_type", "submit_contact", "submit_phone", "batch_no", "reason"] {
        m.insert(k.into(), ff(form, k));
    }
    m.insert("birth_date".into(), v::parse_date_input(&ff(form, "birth_date")));
    m.insert("id_number".into(), ff(form, "id_number").to_uppercase());
    m.insert("residence".into(), helpers::normalize_residence(&ff(form, "residence")));
    let dec = { let d = v::parse_date_input(&ff(form, "decontrol_date")); if d.is_empty() { helpers::now_local_ymd(tz) } else { d } };
    m.insert("decontrol_date".into(), dec);
    m.insert("cert_handover_date".into(), v::parse_date_input(&ff(form, "cert_handover_date")));
    m.insert("operator".into(), operator.to_string());
    m
}

fn validate(data: &VForm) -> Vec<String> {
    let mut errs = v::check_required(data, &[
        ("surname", "中文姓"), ("given_name", "中文名"), ("gender", "性别"), ("birth_date", "出生日期"),
        ("id_number", "身份证号"), ("residence", "户口所在地"), ("political_status", "政治面貌"),
        ("work_unit", "工作单位"), ("supervisor_unit", "人事主管单位"), ("submit_unit_name", "报送单位名称"),
        ("submit_unit_type", "报送单位类别"), ("submit_contact", "报送单位联系人"), ("submit_phone", "报送单位联系电话"),
        ("batch_no", "入库批号"), ("reason", "撤控原因"),
    ]);
    errs.extend(v::check_dates(data, &[("birth_date", "出生日期"), ("cert_handover_date", "证件移交日期"), ("decontrol_date", "撤控日期")]));
    errs.extend(v::check_identity(data, "birth_date", "gender"));
    errs
}

pub async fn new_get(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(filing_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let filing = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT * FROM personnel_filing WHERE id = ?", &[I(filing_id)]) };
    let filing = match filing { Some(f) => f, None => { flash(&mut req, "备案人员不存在。", "danger"); return redirect(&st, &req, "decontrol.list", &[]); } };
    if helpers::row_str(&filing, "status") == "decontrolled" {
        flash(&mut req, "该人员已被撤控。", "warning");
        return redirect(&st, &req, "personnel.view", &[("filing_id".into(), filing_id.to_string())]);
    }
    let prefill = json!({
        "surname": helpers::row_str(&filing, "surname"), "given_name": helpers::row_str(&filing, "given_name"),
        "gender": helpers::row_str(&filing, "gender"), "birth_date": helpers::row_str(&filing, "birth_date"),
        "id_number": helpers::row_str(&filing, "id_number"), "residence": helpers::row_str(&filing, "residence"),
        "political_status": helpers::row_str(&filing, "political_status"), "work_unit": helpers::row_str(&filing, "work_unit"),
        "supervisor_unit": helpers::row_str(&filing, "supervisor_unit"), "decontrol_date": helpers::now_local_ymd(st.cfg.tz_offset_hours),
    });
    page(&st, &mut req, "decontrol/form.html", json!({"data": prefill, "filing": filing, "filing_id": filing_id}))
}

pub async fn new_post(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(filing_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "decontrol.list", &[]); }
    let filing = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT * FROM personnel_filing WHERE id = ?", &[I(filing_id)]) };
    let filing = match filing { Some(f) => f, None => { flash(&mut req, "备案人员不存在。", "danger"); return redirect(&st, &req, "decontrol.list", &[]); } };
    if helpers::row_str(&filing, "status") == "decontrolled" {
        flash(&mut req, "该人员已被撤控。", "warning");
        return redirect(&st, &req, "personnel.view", &[("filing_id".into(), filing_id.to_string())]);
    }
    let data = extract(&form, &req.sess.username(), st.cfg.tz_offset_hours);
    let errs = validate(&data);
    if !errs.is_empty() {
        for e in &errs { flash(&mut req, e, "danger"); }
        return page(&st, &mut req, "decontrol/form.html", json!({"data": vform_json(&data), "filing": filing, "filing_id": filing_id}));
    }
    let params: Vec<SqlValue> = {
        let mut p = vec![I(filing_id)];
        for k in ["surname", "given_name", "gender", "birth_date", "id_number", "residence", "political_status",
                  "work_unit", "supervisor_unit", "submit_unit_name", "submit_unit_type", "submit_contact",
                  "submit_phone", "batch_no", "reason", "decontrol_date", "cert_handover_date", "operator"] {
            p.push(db::sv_opt(data.get(k).map(|s| s.as_str()).unwrap_or("")));
        }
        p
    };
    {
        let conn = st.db.lock().unwrap();
        db::exec(&conn, "INSERT INTO decontrol_filing (personnel_filing_id, surname, given_name, gender, birth_date, id_number, residence, political_status, work_unit, supervisor_unit, submit_unit_name, submit_unit_type, submit_contact, submit_phone, batch_no, reason, decontrol_date, cert_handover_date, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", &params).ok();
        let dec_id = conn.last_insert_rowid();
        db::exec(&conn, "UPDATE personnel_filing SET status = 'decontrolled', updated_at = CURRENT_TIMESTAMP WHERE id = ?", &[I(filing_id)]).ok();
        let after = helpers::row_snapshot(&conn, "decontrol_filing", dec_id);
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "create", "decontrol_filing", Some(dec_id), "", None, after);
    }
    flash(&mut req, "撤控备案已提交。该人员备案状态已标记为'已撤控'。", "success");
    redirect(&st, &req, "personnel.list", &[])
}

pub async fn view(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(dec_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let row = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT * FROM decontrol_filing WHERE id = ?", &[I(dec_id)]) };
    match row {
        None => { flash(&mut req, "记录不存在。", "danger"); redirect(&st, &req, "decontrol.list", &[]) }
        Some(r) => page(&st, &mut req, "decontrol/view.html", json!({"dec": r})),
    }
}

fn vform_json(d: &VForm) -> serde_json::Value {
    serde_json::to_value(d).unwrap_or(json!({}))
}

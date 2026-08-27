// 证照登记：护照 / 港澳通行证 / 台湾通行证
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

pub fn cert_filters(q: &F, ids: &[i64]) -> (String, Vec<SqlValue>) {
    let mut where_ = String::new();
    let mut params: Vec<SqlValue> = vec![];
    let s = q.get("search").map(|x| x.trim()).unwrap_or("");
    if !s.is_empty() {
        where_.push_str(" AND (name LIKE ? OR unit LIKE ?)");
        let like = format!("%{s}%");
        params.push(T(like.clone())); params.push(T(like));
    }
    for (key, col) in [("has_passport", "passport_no"), ("has_hm", "hm_pass_no"), ("has_tw", "tw_pass_no")] {
        match q.get(key).map(|x| x.trim()).unwrap_or("") {
            "1" => where_.push_str(&format!(" AND {col} IS NOT NULL AND {col} != ''")),
            "0" => where_.push_str(&format!(" AND ({col} IS NULL OR {col} = '')")),
            _ => {}
        }
    }
    if !ids.is_empty() {
        let ph = vec!["?"; ids.len()].join(",");
        where_.push_str(&format!(" AND id IN ({ph})"));
        for id in ids { params.push(I(*id)); }
    }
    (where_, params)
}

pub async fn list(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let q = query_args(&req.query);
    let (where_, params) = cert_filters(&q, &[]);
    let items = { let conn = st.db.lock().unwrap(); helpers::list_all(&conn, &format!("SELECT * FROM certificates WHERE 1=1{where_} ORDER BY updated_at DESC"), &params) };

    let today = helpers::now_local_ymd(st.cfg.tz_offset_hours);
    let warn_date = {
        let d = time::OffsetDateTime::now_utc() + time::Duration::days(crate::config::CERT_WARN_DAYS);
        format!("{:04}{:02}{:02}", d.year(), d.month() as u8, d.day())
    };
    let mut warn_set = serde_json::Map::new();
    let mut warn_map = serde_json::Map::new();
    let mut warn_ids: Vec<serde_json::Value> = vec![];
    if let Some(rows) = items.get("rows").and_then(|v| v.as_array()) {
        for row in rows {
            let id = helpers::row_i64(row, "id");
            for (field, label) in [("passport_expiry", "普通护照"), ("hm_pass_expiry", "往来港澳通行证"), ("tw_pass_expiry", "大陆居民往来台湾通行证")] {
                let expiry = helpers::row_str(row, field);
                if !expiry.is_empty() && today <= expiry && expiry <= warn_date {
                    warn_set.insert(format!("{id}:{label}"), json!(true));
                    if !warn_map.contains_key(&id.to_string()) {
                        warn_map.insert(id.to_string(), json!([label, expiry]));
                        warn_ids.push(json!(id));
                    }
                }
            }
        }
    }
    let data = json!({
        "items": items, "search": q.get("search").cloned().unwrap_or_default(),
        "has_passport": q.get("has_passport").cloned().unwrap_or_default(),
        "has_hm": q.get("has_hm").cloned().unwrap_or_default(),
        "has_tw": q.get("has_tw").cloned().unwrap_or_default(),
        "warn_ids": warn_ids, "_warn_set": warn_set, "_warn_map": warn_map,
    });
    page(&st, &mut req, "certificate/list.html", data)
}

fn extract(form: &F, operator: &str) -> VForm {
    let mut m = VForm::new();
    for k in ["personnel_filing_id", "unit", "department", "name", "passport_no", "hm_pass_no", "tw_pass_no"] {
        m.insert(k.into(), ff(form, k));
    }
    for k in ["passport_expiry", "passport_submit_date", "hm_pass_expiry", "hm_pass_submit_date", "tw_pass_expiry", "tw_pass_submit_date"] {
        m.insert(k.into(), v::parse_date_input(&ff(form, k)));
    }
    m.insert("operator".into(), operator.to_string());
    m
}

fn validate(data: &VForm) -> Vec<String> {
    let mut errs = v::check_required(data, &[("personnel_filing_id", "备案人员"), ("unit", "单位"), ("department", "部门"), ("name", "姓名")]);
    errs.extend(v::check_dates(data, &[
        ("passport_expiry", "护照有效日期"), ("passport_submit_date", "护照上交日期"),
        ("hm_pass_expiry", "港澳通行证有效日期"), ("hm_pass_submit_date", "港澳通行证上交日期"),
        ("tw_pass_expiry", "台湾通行证有效日期"), ("tw_pass_submit_date", "台湾通行证上交日期"),
    ]));
    for (no, exp, sub, label) in [
        ("passport_no", "passport_expiry", "passport_submit_date", "护照"),
        ("hm_pass_no", "hm_pass_expiry", "hm_pass_submit_date", "港澳通行证"),
        ("tw_pass_no", "tw_pass_expiry", "tw_pass_submit_date", "台湾通行证"),
    ] {
        if !data.get(no).map(|s| s.is_empty()).unwrap_or(true) {
            if data.get(exp).map(|s| s.is_empty()).unwrap_or(true) { errs.push(format!("填写{label}证件号时，有效日期为必填。")); }
            if data.get(sub).map(|s| s.is_empty()).unwrap_or(true) { errs.push(format!("填写{label}证件号时，上交日期为必填。")); }
        }
    }
    errs
}

/// 三类证件的（展示名, 号码列, 有效期列, 上交日期列）。
const CERT_SLOTS: &[(&str, &str, &str, &str)] = &[
    ("普通护照", "passport_no", "passport_expiry", "passport_submit_date"),
    ("往来港澳通行证", "hm_pass_no", "hm_pass_expiry", "hm_pass_submit_date"),
    ("大陆居民往来台湾通行证", "tw_pass_no", "tw_pass_expiry", "tw_pass_submit_date"),
];

/// 该备案人员是否已有证照记录；有则返回其 id。
fn existing_cert_id(conn: &rusqlite::Connection, personnel_filing_id: &str) -> Option<i64> {
    if personnel_filing_id.trim().is_empty() {
        return None;
    }
    db::query_one(conn,
        "SELECT id FROM certificates WHERE personnel_filing_id = ? ORDER BY id LIMIT 1",
        &[db::sv_opt(personnel_filing_id)])
        .map(|r| helpers::row_i64(&r, "id"))
}

/// 哪几类证件的号码发生了变化（旧号码非空且与新号码不同）。
///
/// 只认「换发」：从空到有是首次登记，不提醒；改回空是注销，也不提醒。
fn renewed_labels(before: &Option<serde_json::Value>, after: &VForm) -> Vec<String> {
    let Some(b) = before else { return vec![] };
    CERT_SLOTS.iter()
        .filter(|(_, no, _, _)| {
            let old = helpers::row_str(b, no);
            let new = after.get(*no).map(|s| s.trim()).unwrap_or("");
            !old.trim().is_empty() && !new.is_empty() && old.trim() != new
        })
        .map(|(label, _, _, _)| label.to_string())
        .collect()
}

fn cert_params(d: &VForm) -> Vec<SqlValue> {
    ["personnel_filing_id", "unit", "department", "name", "passport_no", "passport_expiry", "passport_submit_date",
     "hm_pass_no", "hm_pass_expiry", "hm_pass_submit_date", "tw_pass_no", "tw_pass_expiry", "tw_pass_submit_date", "operator"]
        .iter().map(|k| db::sv_opt(d.get(*k).map(|s| s.as_str()).unwrap_or(""))).collect()
}

pub async fn new_get(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let mut prefill = json!({});
    if let Some(fid) = query_args(&req.query).get("filing_id").and_then(|s| s.parse::<i64>().ok()) {
        let conn = st.db.lock().unwrap();
        if let Some(f) = db::query_one(&conn, "SELECT id, work_unit, surname||given_name AS name, COALESCE((SELECT unit FROM personnel_info WHERE id = personnel_filing.personnel_info_id), work_unit) AS unit_val FROM personnel_filing WHERE id = ?", &[I(fid)]) {
            let mut unit = helpers::row_str(&f, "unit_val");
            if unit.is_empty() { unit = helpers::row_str(&f, "work_unit"); }
            prefill = json!({"personnel_filing_id": fid, "unit": unit, "department": "", "name": helpers::row_str(&f, "name")});
        }
    }
    page(&st, &mut req, "certificate/form.html", json!({"data": prefill, "editing": false}))
}

pub async fn new_post(State(st): State<St>, headers: HeaderMap, uri: Uri, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "certificate.list", &[]); }
    let data = extract(&form, &req.sess.operator_name());
    let mut errs = validate(&data);
    // 一人一行：三种证件是同一行上的三组列，本来就装得下一个人的全部证件。
    // 需求文档写明「一行为一人」，但此前代码从未拦过，现实里很容易变成「没找到原
    // 记录就又建一条」——于是同一个人两个编辑入口，到期预警报两遍，想改护照有效期
    // 还得先点进去看哪条里有护照。
    {
        let conn = st.db.lock().unwrap();
        if let Some(dup) = existing_cert_id(&conn,
                data.get("personnel_filing_id").map(|s| s.as_str()).unwrap_or("")) {
            errs.push(format!(
                "该备案人员已有证照记录（#{dup}）。三类证件登记在同一条记录上，请直接编辑那一条，不要新建。"));
        }
    }
    if !errs.is_empty() {
        for e in &errs { flash(&mut req, e, "danger"); }
        return page(&st, &mut req, "certificate/form.html", json!({"data": vform_json(&data), "editing": false}));
    }
    {
        let conn = st.db.lock().unwrap();
        db::exec(&conn, "INSERT INTO certificates (personnel_filing_id, unit, department, name, passport_no, passport_expiry, passport_submit_date, hm_pass_no, hm_pass_expiry, hm_pass_submit_date, tw_pass_no, tw_pass_expiry, tw_pass_submit_date, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", &cert_params(&data)).ok();
        let id = conn.last_insert_rowid();
        let after = helpers::row_snapshot(&conn, "certificates", id);
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "create", "certificate", Some(id), "", None, after);
    }
    flash(&mut req, "证照登记已保存。", "success");
    redirect(&st, &req, "certificate.list", &[])
}

pub async fn edit_get(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(cert_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let row = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT * FROM certificates WHERE id = ?", &[I(cert_id)]) };
    match row {
        None => { flash(&mut req, "记录不存在。", "danger"); redirect(&st, &req, "certificate.list", &[]) }
        Some(r) => page(&st, &mut req, "certificate/form.html", json!({"data": r, "editing": true, "cert_id": cert_id})),
    }
}

pub async fn edit_post(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(cert_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "certificate.list", &[]); }
    let exists = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT id FROM certificates WHERE id = ?", &[I(cert_id)]).is_some() };
    if !exists { flash(&mut req, "记录不存在。", "danger"); return redirect(&st, &req, "certificate.list", &[]); }
    let data = extract(&form, &req.sess.operator_name());
    let errs = validate(&data);
    if !errs.is_empty() {
        for e in &errs { flash(&mut req, e, "danger"); }
        return page(&st, &mut req, "certificate/form.html", json!({"data": vform_json(&data), "editing": true, "cert_id": cert_id}));
    }
    let renewed = {
        let conn = st.db.lock().unwrap();
        let before = helpers::row_snapshot(&conn, "certificates", cert_id);
        let renewed = renewed_labels(&before, &data);
        let mut p = cert_params(&data);
        p.push(I(cert_id));
        db::exec(&conn, "UPDATE certificates SET personnel_filing_id=?, unit=?, department=?, name=?, passport_no=?, passport_expiry=?, passport_submit_date=?, hm_pass_no=?, hm_pass_expiry=?, hm_pass_submit_date=?, tw_pass_no=?, tw_pass_expiry=?, tw_pass_submit_date=?, operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", &p).ok();
        let after = helpers::row_snapshot(&conn, "certificates", cert_id);
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "update", "certificate", Some(cert_id), "", before, after);
        renewed
    };
    flash(&mut req, "证照信息已更新。", "success");
    // 换发新证时最容易漏的一步：号码换了，有效期或上交日期还留着旧证的。
    // 台账是到期预警与「有没有可用证件」校验的唯一依据，日期不准这两样都会失灵。
    // 号码变化是换发的确切信号，此时提醒一次，成本为零。
    for label in &renewed {
        flash(&mut req, &format!("{label}号码已变更：请确认有效日期与上交日期同步更新为新证的。"), "warning");
    }
    redirect(&st, &req, "certificate.list", &[])
}

pub async fn delete(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(cert_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "certificate.list", &[]); }
    {
        let conn = st.db.lock().unwrap();
        let before = helpers::row_snapshot(&conn, "certificates", cert_id);
        db::exec(&conn, "DELETE FROM certificates WHERE id = ?", &[I(cert_id)]).ok();
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "delete", "certificate", Some(cert_id), "", before, None);
    }
    flash(&mut req, "证照记录已删除。", "info");
    redirect(&st, &req, "certificate.list", &[])
}

fn vform_json(d: &VForm) -> serde_json::Value {
    serde_json::to_value(d).unwrap_or(json!({}))
}

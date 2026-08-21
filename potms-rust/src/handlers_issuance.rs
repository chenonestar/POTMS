//! 证件领用管理（REQ-012）—— 领用登记 / 归还登记 / 作废，含手写签名。
//! 与 Python 版 blueprints/issuance.py 逐条对应。
//!
//! 设计约束（已与业务方审定，五版一致）：
//! 1. 本模块是「证件领用/归还日期」的**唯一写入方**；travel_details 上的
//!    passport_collect_date / passport_return_date 降级为派生只读字段，
//!    由本模块回写，避免双数据源。
//! 2. 签名一经保存**不可编辑**，登记有误只能作废（voided）后重新登记，
//!    以保证签名凭证的证据效力。
//! 3. 签名以 PNG 位图 + 笔迹矢量双存于数据库，随每日备份一起落盘；
//!    不落文件系统（uploads 目录不在备份范围内）。

use crate::validators as v;
use crate::{
    csrf_check, db, ff, flash, helpers, page, query_args, redirect, require_login, signature, Req, St,
};
use axum::extract::{Path, State};
use axum::http::{HeaderMap, StatusCode, Uri};
use axum::response::{IntoResponse, Response};
use axum::Form;
use rusqlite::types::Value as SqlValue;
use rusqlite::types::Value::{Integer as I, Text as T};
use serde_json::json;
use std::collections::HashMap;

type F = HashMap<String, String>;

/// 证件种类代码 → certificates 表中对应的号码字段
const CERT_NO_FIELD: &[(&str, &str)] = &[
    ("01", "passport_no"),
    ("02", "hm_pass_no"),
    ("03", "tw_pass_no"),
];

/// 列表/导出共用：JOIN 备案表以排除孤儿行（延续既有数据完整性口径）
const BASE_SELECT: &str = "SELECT i.*, pf.work_unit AS work_unit \
     FROM cert_issuance i \
     JOIN personnel_filing pf ON i.personnel_filing_id = pf.id \
     WHERE 1=1";

/// 构建领用列表 WHERE 子句，供列表与导出复用。
pub fn issuance_filters(q: &F, ids: &[i64]) -> (String, Vec<SqlValue>) {
    let mut where_ = String::new();
    let mut params: Vec<SqlValue> = vec![];
    let s = q.get("search").map(|x| x.trim()).unwrap_or("");
    if !s.is_empty() {
        where_.push_str(" AND (i.holder_name LIKE ? OR i.id_number LIKE ? OR i.cert_nos LIKE ?)");
        let like = format!("%{s}%");
        params.push(T(like.clone()));
        params.push(T(like.clone()));
        params.push(T(like));
    }
    let status = q.get("status").map(|x| x.trim()).unwrap_or("");
    if matches!(status, "issued" | "returned" | "voided") {
        where_.push_str(" AND i.status = ?");
        params.push(T(status.into()));
    }
    let ct = q.get("cert_type").map(|x| x.trim()).unwrap_or("");
    if !ct.is_empty() {
        where_.push_str(" AND (',' || i.cert_types || ',') LIKE ?");
        params.push(T(format!("%,{ct},%")));
    }
    for (key, op) in [("date_from", ">="), ("date_to", "<=")] {
        let d = q.get(key).map(|x| x.trim()).unwrap_or("");
        if !d.is_empty() {
            where_.push_str(&format!(" AND i.issue_date {op} ?"));
            params.push(T(v::parse_date_input(d)));
        }
    }
    if !ids.is_empty() {
        let ph = vec!["?"; ids.len()].join(",");
        where_.push_str(&format!(" AND i.id IN ({ph})"));
        for id in ids {
            params.push(I(*id));
        }
    }
    (where_, params)
}

pub async fn list(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) {
        return r;
    }
    let q = query_args(&req.query);
    let (where_, params) = issuance_filters(&q, &[]);
    let mut items = {
        let conn = st.db.lock().unwrap();
        helpers::list_all(
            &conn,
            &format!("{BASE_SELECT}{where_} ORDER BY i.issue_date DESC, i.id DESC"),
            &params,
        )
    };
    // 证件种类代码 → 中文标签，在这里算好再下发。模板里 split 字符串在三种
    // Jinja 实现（Jinja2 / gonja / minijinja）上写法不一（minijinja 干脆没有），
    // 而五版模板要逐字一致。
    {
        let conn = st.db.lock().unwrap();
        if let Some(rows) = items.get_mut("rows").and_then(|v| v.as_array_mut()) {
            for row in rows {
                let labels: Vec<String> = helpers::row_str(row, "cert_types")
                    .split(',')
                    .map(str::trim)
                    .filter(|c| !c.is_empty())
                    .map(|c| {
                        let v = helpers::get_dict_value(&conn, "cert_type", c);
                        if v.is_empty() { c.to_string() } else { v }
                    })
                    .collect();
                if let serde_json::Value::Object(m) = row {
                    m.insert("cert_type_labels".into(), json!(labels));
                }
            }
        }
    }
    let g = |k: &str| q.get(k).map(|x| x.trim().to_string()).unwrap_or_default();
    page(&st, &mut req, "issuance/list.html", json!({
        "items": items,
        "search": g("search"),
        "status_filter": g("status"),
        "cert_type_filter": g("cert_type"),
        "date_from": g("date_from"),
        "date_to": g("date_to"),
    }))
}

pub async fn new_get(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) {
        return r;
    }
    // 支持从出行记录跳转带入
    let travel_id = query_args(&req.query)
        .get("travel_id")
        .and_then(|s| s.parse::<i64>().ok());
    let mut prefill = json!({"issue_date": helpers::now_local_ymd(st.cfg.tz_offset_hours)});
    let travel = {
        let conn = st.db.lock().unwrap();
        travel_brief(&conn, travel_id)
    };
    if let Some(t) = &travel {
        let m = prefill.as_object_mut().unwrap();
        m.insert("travel_id".into(), json!(travel_id));
        m.insert("personnel_filing_id".into(), json!(helpers::row_i64(t, "personnel_filing_id")));
        m.insert("holder_name".into(), json!(helpers::row_str(t, "name")));
        m.insert("id_number".into(), json!(helpers::row_str(t, "id_number")));
    }
    page(&st, &mut req, "issuance/form.html", json!({"data": prefill, "travel": travel}))
}

pub async fn new_post(
    State(st): State<St>,
    headers: HeaderMap,
    uri: Uri,
    // 用 Vec 而不是 HashMap：证件种类是一组同名 checkbox，HashMap 只会留下最后一个
    Form(pairs): Form<Vec<(String, String)>>,
) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) {
        return r;
    }
    let form = flatten(&pairs);
    if !csrf_check(&req, &form) {
        flash(&mut req, "表单已过期，请重试。", "danger");
        return redirect(&st, &req, "issuance.list", &[]);
    }

    let data = extract(&pairs, &req.sess.operator_name(), st.cfg.tz_offset_hours);
    let mut errs = {
        let conn = st.db.lock().unwrap();
        validate(&conn, &data)
    };
    let blob = match signature::decode(form.get("sign_png").map(|s| s.as_str()).unwrap_or(""),
                                       st.cfg.require_signature) {
        Ok(b) => b,
        Err(e) => {
            errs.push(e);
            None
        }
    };
    if !errs.is_empty() {
        for e in &errs {
            flash(&mut req, e, "danger");
        }
        let travel = {
            let conn = st.db.lock().unwrap();
            travel_brief(&conn, data.travel_id)
        };
        return page(&st, &mut req, "issuance/form.html",
                    json!({"data": data.to_json(), "travel": travel}));
    }

    let meta = signature::clean_meta(form.get("sign_meta").map(|s| s.as_str()).unwrap_or(""));
    let iss_id = {
        let conn = st.db.lock().unwrap();
        let r = conn.execute(
            "INSERT INTO cert_issuance (travel_id, personnel_filing_id, holder_name, id_number, \
             cert_types, cert_nos, issue_date, issuer, sign_image, sign_meta, status, remarks, operator) \
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'issued', ?, ?)",
            rusqlite::params![
                data.travel_id, data.personnel_filing_id, data.holder_name, data.id_number,
                data.cert_types, data.cert_nos, data.issue_date, data.issuer,
                blob, meta, data.remarks, data.operator,
            ],
        );
        if r.is_err() {
            drop(conn);
            flash(&mut req, "保存失败，请检查填写内容。", "danger");
            return redirect(&st, &req, "issuance.list", &[]);
        }
        let id = conn.last_insert_rowid();
        sync_travel_dates(&conn, data.travel_id);
        let after = helpers::row_snapshot(&conn, "cert_issuance", id);
        let detail = format!("证件领用登记：{}，{}",
                             data.holder_name, types_label(&conn, &data.cert_types));
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "create", "cert_issuance",
                            Some(id), &detail, None, after);
        id
    };
    flash(&mut req, "证件领用登记已保存。", "success");
    redirect(&st, &req, "issuance.view", &[("iss_id".to_string(), iss_id.to_string())])
}

pub async fn view(State(st): State<St>, headers: HeaderMap, uri: Uri,
                  Path(iss_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) {
        return r;
    }
    let (row, travel, labels) = {
        let conn = st.db.lock().unwrap();
        match get_issuance(&conn, iss_id) {
            None => (None, None, String::new()),
            Some(r) => {
                let tid = helpers::row_i64(&r, "travel_id");
                let t = travel_brief(&conn, if tid > 0 { Some(tid) } else { None });
                let l = types_label(&conn, &helpers::row_str(&r, "cert_types"));
                (Some(r), t, l)
            }
        }
    };
    match row {
        None => not_found(&st, req),
        Some(r) => page(&st, &mut req, "issuance/view.html",
                        json!({"item": r, "travel": travel, "type_labels": labels})),
    }
}

pub async fn return_get(State(st): State<St>, headers: HeaderMap, uri: Uri,
                        Path(iss_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) {
        return r;
    }
    let (row, labels) = {
        let conn = st.db.lock().unwrap();
        match get_issuance(&conn, iss_id) {
            None => (None, String::new()),
            Some(r) => {
                let l = types_label(&conn, &helpers::row_str(&r, "cert_types"));
                (Some(r), l)
            }
        }
    };
    let Some(row) = row else { return not_found(&st, req) };
    if helpers::row_str(&row, "status") != "issued" {
        flash(&mut req, "该记录不是「已领用」状态，无法办理归还。", "warning");
        return redirect(&st, &req, "issuance.view", &[("iss_id".to_string(), iss_id.to_string())]);
    }
    let today = helpers::now_local_ymd(st.cfg.tz_offset_hours);
    page(&st, &mut req, "issuance/return.html",
         json!({"item": row, "return_date": today, "type_labels": labels}))
}

pub async fn return_post(State(st): State<St>, headers: HeaderMap, uri: Uri,
                         Path(iss_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) {
        return r;
    }
    if !csrf_check(&req, &form) {
        flash(&mut req, "表单已过期，请重试。", "danger");
        return redirect(&st, &req, "issuance.view", &[("iss_id".to_string(), iss_id.to_string())]);
    }
    let (row, labels) = {
        let conn = st.db.lock().unwrap();
        match get_issuance(&conn, iss_id) {
            None => (None, String::new()),
            Some(r) => {
                let l = types_label(&conn, &helpers::row_str(&r, "cert_types"));
                (Some(r), l)
            }
        }
    };
    let Some(row) = row else { return not_found(&st, req) };
    if helpers::row_str(&row, "status") != "issued" {
        flash(&mut req, "该记录不是「已领用」状态，无法办理归还。", "warning");
        return redirect(&st, &req, "issuance.view", &[("iss_id".to_string(), iss_id.to_string())]);
    }

    let return_date = v::parse_date_input(&ff(&form, "return_date"));
    let issue_date = helpers::row_str(&row, "issue_date");
    let mut errs: Vec<String> = vec![];
    if return_date.is_empty() {
        errs.push("归还日期为必填项。".into());
    } else {
        let mut d = v::Form::new();
        d.insert("return_date".into(), return_date.clone());
        errs.extend(v::check_dates(&d, &[("return_date", "归还日期")]));
        if return_date < issue_date {
            errs.push(format!("归还日期不应早于领用日期（{issue_date}）。"));
        }
    }
    let blob = match signature::decode(&ff(&form, "sign_png"), st.cfg.require_signature) {
        Ok(b) => b,
        Err(e) => {
            errs.push(e);
            None
        }
    };
    if !errs.is_empty() {
        for e in &errs {
            flash(&mut req, e, "danger");
        }
        return page(&st, &mut req, "issuance/return.html",
                    json!({"item": row, "return_date": return_date, "type_labels": labels}));
    }

    {
        let conn = st.db.lock().unwrap();
        let before = helpers::row_snapshot(&conn, "cert_issuance", iss_id);
        let _ = conn.execute(
            "UPDATE cert_issuance SET return_date=?, return_sign_image=?, return_sign_meta=?, \
             return_operator=?, status='returned', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            rusqlite::params![
                return_date, blob, signature::clean_meta(&ff(&form, "sign_meta")),
                req.sess.operator_name(), iss_id,
            ],
        );
        let tid = helpers::row_i64(&row, "travel_id");
        sync_travel_dates(&conn, if tid > 0 { Some(tid) } else { None });
        let after = helpers::row_snapshot(&conn, "cert_issuance", iss_id);
        let detail = format!("证件归还登记：{}，归还日期 {return_date}",
                             helpers::row_str(&row, "holder_name"));
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "update", "cert_issuance",
                            Some(iss_id), &detail, before, after);
    }
    flash(&mut req, "证件归还登记已保存。", "success");
    redirect(&st, &req, "issuance.view", &[("iss_id".to_string(), iss_id.to_string())])
}

/// 作废。签名不可编辑，登记有误走这条路径。
pub async fn void(State(st): State<St>, headers: HeaderMap, uri: Uri,
                  Path(iss_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) {
        return r;
    }
    if !csrf_check(&req, &form) {
        flash(&mut req, "表单已过期，请重试。", "danger");
        return redirect(&st, &req, "issuance.view", &[("iss_id".to_string(), iss_id.to_string())]);
    }
    let row = {
        let conn = st.db.lock().unwrap();
        get_issuance(&conn, iss_id)
    };
    let Some(row) = row else { return not_found(&st, req) };
    if helpers::row_str(&row, "status") == "voided" {
        flash(&mut req, "该记录已是作废状态。", "info");
        return redirect(&st, &req, "issuance.view", &[("iss_id".to_string(), iss_id.to_string())]);
    }
    let reason = ff(&form, "void_reason");
    if reason.is_empty() {
        flash(&mut req, "作废原因为必填项。", "danger");
        return redirect(&st, &req, "issuance.view", &[("iss_id".to_string(), iss_id.to_string())]);
    }

    {
        let conn = st.db.lock().unwrap();
        let before = helpers::row_snapshot(&conn, "cert_issuance", iss_id);
        let _ = conn.execute(
            "UPDATE cert_issuance SET status='voided', void_reason=?, \
             updated_at=CURRENT_TIMESTAMP WHERE id=?",
            rusqlite::params![reason, iss_id],
        );
        let tid = helpers::row_i64(&row, "travel_id");
        sync_travel_dates(&conn, if tid > 0 { Some(tid) } else { None });
        let after = helpers::row_snapshot(&conn, "cert_issuance", iss_id);
        let detail = format!("领用记录作废：{}，原因：{reason}",
                             helpers::row_str(&row, "holder_name"));
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "void", "cert_issuance",
                            Some(iss_id), &detail, before, after);
    }
    flash(&mut req, "领用记录已作废，如需更正请重新登记。", "info");
    redirect(&st, &req, "issuance.view", &[("iss_id".to_string(), iss_id.to_string())])
}

/// 输出签名位图。kind=return 取归还签名，否则取领用签名。
pub async fn signature_png(State(st): State<St>, headers: HeaderMap, uri: Uri,
                           Path(iss_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) {
        return r;
    }
    let col = if query_args(&req.query).get("kind").map(|s| s.as_str()) == Some("return") {
        "return_sign_image"
    } else {
        "sign_image"
    };
    let blob: Option<Vec<u8>> = {
        let conn = st.db.lock().unwrap();
        conn.query_row(&format!("SELECT {col} FROM cert_issuance WHERE id = ?"), [iss_id],
                       |r| r.get::<_, Option<Vec<u8>>>(0))
            .ok()
            .flatten()
    };
    match blob {
        Some(b) if !b.is_empty() => (
            [
                (axum::http::header::CONTENT_TYPE, "image/png"),
                // 签名一经保存不可变，可长期缓存
                (axum::http::header::CACHE_CONTROL, "private, max-age=86400"),
            ],
            b,
        ).into_response(),
        _ => not_found(&st, req),
    }
}

// ---------------------------------------------------------------------------
// 内部工具
// ---------------------------------------------------------------------------

fn not_found(st: &St, mut req: Req) -> Response {
    let ctx = req.base();
    crate::render::render_status(&st.env, &mut { ctx }, &req.sess, &st.cfg,
                                 "errors/404.html", json!({}), StatusCode::NOT_FOUND)
}

fn get_issuance(conn: &rusqlite::Connection, iss_id: i64) -> Option<db::Row> {
    db::query_one(conn,
        "SELECT i.*, pf.work_unit FROM cert_issuance i \
         JOIN personnel_filing pf ON i.personnel_filing_id = pf.id WHERE i.id = ?",
        &[I(iss_id)])
}

/// 取出行记录摘要（用于带入与展示）。
fn travel_brief(conn: &rusqlite::Connection, travel_id: Option<i64>) -> Option<db::Row> {
    let id = travel_id?;
    db::query_one(conn,
        "SELECT id, personnel_filing_id, name, id_number, unit, department, \
         destination_passport, travel_dates, approval_date, passport_no \
         FROM travel_details WHERE id = ?", &[I(id)])
}

/// 把 "01,02" 转成 "因私护照、往来港澳通行证"。
pub fn types_label(conn: &rusqlite::Connection, codes: &str) -> String {
    codes.split(',')
        .map(str::trim)
        .filter(|c| !c.is_empty())
        .map(|c| {
            let v = helpers::get_dict_value(conn, "cert_type", c);
            if v.is_empty() { c.to_string() } else { v }
        })
        .collect::<Vec<_>>()
        .join("、")
}

/// 把领用/归还日期回写到出行表（派生字段，本模块为唯一写入方）。
///
/// 取该出行下**未作废**记录中最早的领用日期与最晚的归还日期；若全部作废或无记录，
/// 则清空，使逾期告警口径与领用记录始终一致。
fn sync_travel_dates(conn: &rusqlite::Connection, travel_id: Option<i64>) {
    let Some(tid) = travel_id else { return };
    let agg = db::query_one(conn,
        "SELECT MIN(issue_date) AS c, \
                CASE WHEN COUNT(*) = SUM(CASE WHEN return_date IS NOT NULL AND return_date != '' \
                                              THEN 1 ELSE 0 END) \
                     THEN MAX(return_date) ELSE NULL END AS r \
         FROM cert_issuance WHERE travel_id = ? AND status != 'voided'", &[I(tid)]);
    let none_if_empty = |s: String| if s.is_empty() { None } else { Some(s) };
    let (collect, ret) = match &agg {
        Some(a) => (none_if_empty(helpers::row_str(a, "c")), none_if_empty(helpers::row_str(a, "r"))),
        None => (None, None),
    };
    let _ = conn.execute(
        "UPDATE travel_details SET passport_collect_date=?, passport_return_date=? WHERE id=?",
        rusqlite::params![collect, ret, tid]);
}

/// 领用表单的字段集合。cert_types 是一组同名 checkbox，只能从原始 pairs 里取。
struct IssuanceForm {
    travel_id: Option<i64>,
    personnel_filing_id: String,
    holder_name: String,
    id_number: String,
    cert_types: String,
    cert_nos: String,
    issue_date: String,
    issuer: String,
    remarks: String,
    operator: String,
}

impl IssuanceForm {
    fn to_json(&self) -> serde_json::Value {
        json!({
            "travel_id": self.travel_id,
            "personnel_filing_id": self.personnel_filing_id,
            "holder_name": self.holder_name,
            "id_number": self.id_number,
            "cert_types": self.cert_types,
            "cert_nos": self.cert_nos,
            "issue_date": self.issue_date,
            "issuer": self.issuer,
            "remarks": self.remarks,
        })
    }
}

/// 同名键只留最后一个——CSRF 令牌之类的单值字段用这个视图就够了。
fn flatten(pairs: &[(String, String)]) -> F {
    pairs.iter().cloned().collect()
}

fn extract(pairs: &[(String, String)], operator: &str, _tz: i64) -> IssuanceForm {
    let form = flatten(pairs);
    let types: Vec<String> = pairs.iter()
        .filter(|(k, _)| k == "cert_types")
        .map(|(_, val)| val.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();
    IssuanceForm {
        travel_id: form.get("travel_id").and_then(|s| s.trim().parse::<i64>().ok()),
        personnel_filing_id: ff(&form, "personnel_filing_id"),
        holder_name: ff(&form, "holder_name"),
        id_number: ff(&form, "id_number"),
        cert_types: types.join(","),
        cert_nos: ff(&form, "cert_nos"),
        issue_date: v::parse_date_input(&ff(&form, "issue_date")),
        issuer: operator.to_string(),
        remarks: ff(&form, "remarks"),
        operator: operator.to_string(),
    }
}

fn validate(conn: &rusqlite::Connection, d: &IssuanceForm) -> Vec<String> {
    let mut data = v::Form::new();
    data.insert("personnel_filing_id".into(), d.personnel_filing_id.clone());
    data.insert("holder_name".into(), d.holder_name.clone());
    data.insert("cert_types".into(), d.cert_types.clone());
    data.insert("issue_date".into(), d.issue_date.clone());

    let mut errs = v::check_required(&data, &[
        ("personnel_filing_id", "领用人（备案人员）"),
        ("holder_name", "领用人姓名"),
        ("cert_types", "领用证件种类"),
        ("issue_date", "领用日期"),
    ]);
    errs.extend(v::check_dates(&data, &[("issue_date", "领用日期")]));

    // 证件种类必须是字典内的合法代码
    for c in d.cert_types.split(',').filter(|c| !c.is_empty()) {
        if !CERT_NO_FIELD.iter().any(|(code, _)| *code == c) {
            errs.push(format!("无效的证件种类代码：{c}。"));
        }
    }

    // 同一出行下不允许重复的未归还领用记录
    if let Some(tid) = d.travel_id {
        if let Some(dup) = db::query_one(conn,
            "SELECT id FROM cert_issuance WHERE travel_id = ? AND status = 'issued'", &[I(tid)]) {
            errs.push(format!("该出行记录已有未归还的领用记录（#{}），请先办理归还或作废。",
                              helpers::row_i64(&dup, "id")));
        }
    }
    errs
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    /// 1×1 白色 PNG 的 dataURL；签名校验只看魔数与大小
    const PNG_DATA_URL: &str = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ\
AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

    /// 起一个内存库 + 完整路由的测试实例，并直接把会话置成已登录。
    ///
    /// 走 build_app 而不是另抄一份 Router：测试要驱动真正跑起来的那套路由。
    /// 模板是从 Python 版原样拷来的，minijinja 与 Jinja2 的差异只有真渲染一遍
    /// 才会暴露，所以这些用例全部发真请求。
    struct App {
        router: axum::Router,
        cookie: String,
        db: crate::render::Db,
        _tmp: std::path::PathBuf,
    }

    impl App {
        fn new() -> App {
            let tmp = std::env::temp_dir()
                .join(format!("potms-iss-{}-{:?}", std::process::id(), std::thread::current().id()));
            let _ = std::fs::remove_dir_all(&tmp);
            std::fs::create_dir_all(&tmp).unwrap();
            unsafe { std::env::set_var("POTMS_BASE", &tmp) };
            let cfg = crate::config::Config::load();

            let conn = rusqlite::Connection::open_in_memory().unwrap();
            crate::db::init_schema(&conn);
            crate::db::run_migrations(&conn);
            crate::db::seed_data(&conn);
            seed_business(&conn);

            let db: crate::render::Db = std::sync::Arc::new(std::sync::Mutex::new(conn));
            let env = crate::render::build_env(db.clone(), cfg.clone());
            let state: St = std::sync::Arc::new(crate::AppState {
                db: db.clone(), env, cfg: cfg.clone(),
                lockout: crate::session::Lockout::default(),
            });

            // 直接造一个已登录会话，省掉走登录表单那一趟
            let mut sess = crate::session::Session::default();
            sess.login("admin", "");
            let csrf = sess.csrf_token();
            let cookie = sess.to_cookie(&cfg.secret_key);
            let cookie = cookie.split(';').next().unwrap().to_string();

            App { router: crate::build_app(state), cookie: format!("{cookie}|{csrf}"), db, _tmp: tmp }
        }

        fn csrf(&self) -> String {
            self.cookie.split('|').nth(1).unwrap().to_string()
        }
        fn cookie_header(&self) -> String {
            self.cookie.split('|').next().unwrap().to_string()
        }

        async fn get(&self, path: &str) -> (StatusCode, String) {
            let req = Request::builder().uri(path)
                .header("Cookie", self.cookie_header())
                .body(Body::empty()).unwrap();
            let res = self.router.clone().oneshot(req).await.unwrap();
            let status = res.status();
            let bytes = axum::body::to_bytes(res.into_body(), usize::MAX).await.unwrap();
            (status, String::from_utf8_lossy(&bytes).into_owned())
        }

        async fn get_bytes(&self, path: &str) -> (StatusCode, Option<String>, Vec<u8>) {
            let req = Request::builder().uri(path)
                .header("Cookie", self.cookie_header())
                .body(Body::empty()).unwrap();
            let res = self.router.clone().oneshot(req).await.unwrap();
            let status = res.status();
            let ct = res.headers().get(axum::http::header::CONTENT_TYPE)
                .and_then(|v| v.to_str().ok()).map(|s| s.to_string());
            let bytes = axum::body::to_bytes(res.into_body(), usize::MAX).await.unwrap();
            (status, ct, bytes.to_vec())
        }

        async fn post(&self, path: &str, fields: &[(&str, &str)]) -> (StatusCode, String) {
            let mut body = format!("csrf_token={}", urlencoding::encode(&self.csrf()));
            for (k, v) in fields {
                body.push('&');
                body.push_str(&format!("{}={}", urlencoding::encode(k), urlencoding::encode(v)));
            }
            let req = Request::builder().method("POST").uri(path)
                .header("Cookie", self.cookie_header())
                .header("Content-Type", "application/x-www-form-urlencoded")
                .body(Body::from(body)).unwrap();
            let res = self.router.clone().oneshot(req).await.unwrap();
            let status = res.status();
            let bytes = axum::body::to_bytes(res.into_body(), usize::MAX).await.unwrap();
            (status, String::from_utf8_lossy(&bytes).into_owned())
        }

        fn scalar(&self, sql: &str) -> String {
            let conn = self.db.lock().unwrap();
            conn.query_row(sql, [], |r| r.get::<_, Option<String>>(0))
                .ok().flatten().unwrap_or_default()
        }
        fn count(&self, sql: &str) -> i64 {
            let conn = self.db.lock().unwrap();
            conn.query_row(sql, [], |r| r.get(0)).unwrap_or(-1)
        }
        fn exec(&self, sql: &str) {
            let conn = self.db.lock().unwrap();
            conn.execute_batch(sql).unwrap();
        }

        async fn new_issuance(&self, sign: &str) -> StatusCode {
            self.post("/issuance/new", &[
                ("personnel_filing_id", "1"), ("holder_name", "史迪威"),
                ("id_number", "110101199001012133"), ("cert_types", "01"),
                ("cert_nos", "E1234567"), ("issue_date", "20260801"),
                ("travel_id", "1"), ("sign_png", sign),
            ]).await.0
        }
    }

    fn seed_business(conn: &rusqlite::Connection) {
        conn.execute_batch(
            "INSERT INTO personnel_info (id,unit,department,name,gender,birth_date,rank,\
                political_status,position,operator) \
             VALUES (1,'总部','办公室','史迪威','男','19900101','01','群众','工程师','admin');\
             INSERT INTO personnel_filing (id,personnel_info_id,surname,given_name,gender,\
                birth_date,id_number,residence,political_status,work_unit,position_or_title,\
                supervisor_unit,operator) \
             VALUES (1,1,'史','迪威','男','19900101','110101199001012133','浙江杭州市西湖区',\
                '群众','总部','处级','人事处','admin');\
             INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,\
                id_number,destination_passport,category,travel_dates,operator) \
             VALUES (1,1,'总部','办公室','史迪威','处级','110101199001012133','德国','因私',\
                '2026/09/01-2026/09/10','admin');",
        ).unwrap();
    }

    #[tokio::test]
    async fn pages_render() {
        let app = App::new();
        assert_eq!(app.new_issuance(PNG_DATA_URL).await, StatusCode::SEE_OTHER);
        for path in ["/issuance/", "/issuance/?status=issued", "/issuance/?cert_type=01",
                     "/issuance/new", "/issuance/new?travel_id=1",
                     "/issuance/1", "/issuance/1/return", "/print/issuance/1"] {
            let (status, body) = app.get(path).await;
            assert_eq!(status, StatusCode::OK, "GET {path} → {status}\n{}",
                       &body[..body.len().min(400)]);
        }
    }

    #[tokio::test]
    async fn create_stores_signature_and_syncs_travel() {
        let app = App::new();
        assert_eq!(app.new_issuance(PNG_DATA_URL).await, StatusCode::SEE_OTHER);
        assert_eq!(app.scalar("SELECT status FROM cert_issuance WHERE id = 1"), "issued");
        assert!(app.count("SELECT length(sign_image) FROM cert_issuance WHERE id = 1") > 8,
                "签名未入库");
        // 本模块是派生日期的唯一写入方
        assert_eq!(app.scalar("SELECT passport_collect_date FROM travel_details WHERE id = 1"),
                   "20260801");
    }

    #[tokio::test]
    async fn rejects_bad_signature() {
        let app = App::new();
        for (sign, want) in [
            ("", "请手写签名后再提交"),
            ("data:image/jpeg;base64,AAAA", "签名数据格式不正确"),
            ("data:image/png;base64,!!!", "签名数据解析失败"),
            ("data:image/png;base64,QUJDRA==", "不是有效的 PNG 图像"),
        ] {
            let (status, body) = app.post("/issuance/new", &[
                ("personnel_filing_id", "1"), ("holder_name", "史迪威"),
                ("cert_types", "01"), ("issue_date", "20260801"), ("sign_png", sign),
            ]).await;
            assert_ne!(status, StatusCode::SEE_OTHER, "签名 {sign:?} 不该被放行");
            assert!(body.contains(want), "签名 {sign:?} 应报「{want}」");
        }
        assert_eq!(app.count("SELECT COUNT(*) FROM cert_issuance"), 0);
    }

    #[tokio::test]
    async fn return_then_void() {
        let app = App::new();
        app.new_issuance(PNG_DATA_URL).await;

        // 归还日期不得早于领用日期
        let (status, body) = app.post("/issuance/1/return", &[
            ("return_date", "20260701"), ("sign_png", PNG_DATA_URL)]).await;
        assert_ne!(status, StatusCode::SEE_OTHER);
        assert!(body.contains("不应早于领用日期"));

        let (status, _) = app.post("/issuance/1/return", &[
            ("return_date", "20260810"), ("sign_png", PNG_DATA_URL)]).await;
        assert_eq!(status, StatusCode::SEE_OTHER);
        assert_eq!(app.scalar("SELECT status FROM cert_issuance WHERE id = 1"), "returned");
        assert_eq!(app.scalar("SELECT return_date FROM cert_issuance WHERE id = 1"), "20260810");
        assert_eq!(app.scalar("SELECT passport_return_date FROM travel_details WHERE id = 1"),
                   "20260810");

        // 作废必须给原因
        app.post("/issuance/1/void", &[]).await;
        assert_eq!(app.scalar("SELECT status FROM cert_issuance WHERE id = 1"), "returned");

        app.post("/issuance/1/void", &[("void_reason", "登记有误")]).await;
        assert_eq!(app.scalar("SELECT status FROM cert_issuance WHERE id = 1"), "voided");
        // 作废后派生日期要跟着清空，否则逾期告警会按一条不算数的记录继续报警
        assert_eq!(app.scalar("SELECT passport_collect_date FROM travel_details WHERE id = 1"), "");
    }

    /// 同一出行下不允许两条未归还的领用记录——否则证件在谁手里就说不清了。
    #[tokio::test]
    async fn rejects_duplicate_open_record() {
        let app = App::new();
        assert_eq!(app.new_issuance(PNG_DATA_URL).await, StatusCode::SEE_OTHER);
        let (status, body) = app.post("/issuance/new", &[
            ("personnel_filing_id", "1"), ("holder_name", "史迪威"), ("cert_types", "01"),
            ("issue_date", "20260801"), ("travel_id", "1"), ("sign_png", PNG_DATA_URL),
        ]).await;
        assert_ne!(status, StatusCode::SEE_OTHER);
        assert!(body.contains("已有未归还的领用记录"));
    }

    #[tokio::test]
    async fn signature_image_served_as_png() {
        let app = App::new();
        app.new_issuance(PNG_DATA_URL).await;

        let (status, ct, bytes) = app.get_bytes("/issuance/1/signature.png").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(ct.as_deref(), Some("image/png"));
        assert_eq!(&bytes[1..4], b"PNG");

        // 还没归还，归还签名不存在
        let (status, _, _) = app.get_bytes("/issuance/1/signature.png?kind=return").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn export_produces_xlsx() {
        let app = App::new();
        app.new_issuance(PNG_DATA_URL).await;
        let (status, _, bytes) = app.get_bytes("/export/issuance").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(&bytes[..2], b"PK", "导出的不是 xlsx（zip 魔数 PK）");
    }

    /// 操作日志记的是登录账号；签名位图不得进快照，否则 snapshot 会被 base64 撑爆。
    #[tokio::test]
    async fn logs_record_account_and_skip_signature_blobs() {
        let app = App::new();
        app.new_issuance(PNG_DATA_URL).await;
        assert!(app.count(
            "SELECT COUNT(*) FROM operation_logs WHERE target_type='cert_issuance' \
             AND operator='admin'") > 0);
        assert_eq!(app.count(
            "SELECT COUNT(*) FROM operation_logs WHERE snapshot LIKE '%sign_image%'"), 0,
            "签名位图混进了操作日志快照");
    }

    /// 迁移要能把「出行表上已有领用日期、却没有领用记录」的老数据补成一条记录。
    #[tokio::test]
    async fn legacy_backfill_is_idempotent() {
        let app = App::new();
        app.exec("UPDATE travel_details SET passport_collect_date = '20260101' WHERE id = 1");
        {
            let conn = app.db.lock().unwrap();
            crate::db::run_migrations(&conn);
        }
        assert_eq!(app.count("SELECT COUNT(*) FROM cert_issuance WHERE travel_id = 1"), 1);
        assert_eq!(app.scalar("SELECT issue_date FROM cert_issuance WHERE travel_id = 1"),
                   "20260101");
        assert!(app.scalar("SELECT remarks FROM cert_issuance WHERE travel_id = 1")
                   .contains("历史数据回填"));

        {
            let conn = app.db.lock().unwrap();
            crate::db::run_migrations(&conn);
        }
        assert_eq!(app.count("SELECT COUNT(*) FROM cert_issuance WHERE travel_id = 1"), 1,
                   "迁移不幂等");
    }

    #[test]
    fn filters_build_expected_sql() {
        let mut q = F::new();
        q.insert("search".into(), "史".into());
        q.insert("status".into(), "issued".into());
        q.insert("cert_type".into(), "01".into());
        let (where_, params) = issuance_filters(&q, &[7]);
        assert!(where_.contains("i.holder_name LIKE ?"));
        assert!(where_.contains("i.status = ?"));
        assert!(where_.contains("(',' || i.cert_types || ',') LIKE ?"));
        assert!(where_.contains("i.id IN (?)"));
        assert_eq!(params.len(), 6); // 3 个 like + 状态 + 种类 + id

        // 非法状态值不该拼进 SQL
        let mut bad = F::new();
        bad.insert("status".into(), "'; DROP TABLE".into());
        assert!(!issuance_filters(&bad, &[]).0.contains("status"));
    }
}

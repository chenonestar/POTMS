// 出国（境）申请：明细表 + 附件上传（PDF 魔数校验）+ 取消/恢复 + 附件总览
use crate::validators::{self as v, Form as VForm};
use crate::{csrf_check, db, ff, flash, helpers, page, query_args, redirect, require_login, Req, St};
use axum::extract::{Multipart, Path, State};
use axum::http::{header, HeaderMap, StatusCode, Uri};
use axum::response::{IntoResponse, Response};
use axum::Form;
use rusqlite::types::Value::{Integer as I, Text as T};
use rusqlite::types::Value as SqlValue;
use serde_json::json;
use std::collections::HashMap;

type F = HashMap<String, String>;

const ATT_CATEGORIES: &[(&str, &str)] = &[
    ("att_application", "个人申请报告"),
    ("att_approval", "审批表"),
    ("att_consent", "同意申办函"),
];

async fn parse_multipart(mut mp: Multipart) -> (F, Vec<(String, String, Vec<u8>)>) {
    let mut form = HashMap::new();
    let mut files = vec![];
    while let Ok(Some(field)) = mp.next_field().await {
        let name = field.name().unwrap_or("").to_string();
        let filename = field.file_name().map(|s| s.to_string());
        let data = field.bytes().await.map(|b| b.to_vec()).unwrap_or_default();
        match filename {
            Some(fname) if !fname.is_empty() => files.push((name, fname, data)),
            _ => { form.insert(name, String::from_utf8_lossy(&data).into_owned()); }
        }
    }
    (form, files)
}

fn is_pdf(bytes: &[u8]) -> bool {
    bytes.len() >= 5 && &bytes[..5] == b"%PDF-"
}

fn travel_overdue_ids(conn: &rusqlite::Connection, today: &str) -> Vec<i64> {
    let rows = db::query_maps(conn, "SELECT id, passport_collect_date, passport_return_date, actual_return_date, travel_end, trip_status, cancel_date FROM travel_details WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' AND (passport_return_date IS NULL OR passport_return_date = '')", &[]);
    rows.iter().filter(|r| helpers::is_cert_overdue(r, today)).map(|r| helpers::row_i64(r, "id")).collect()
}

pub fn travel_filters(conn: &rusqlite::Connection, q: &F, ids: &[i64], today: &str) -> (String, Vec<SqlValue>) {
    let mut w = String::new();
    let mut p: Vec<SqlValue> = vec![];
    let s = q.get("search").map(|x| x.trim()).unwrap_or("");
    if !s.is_empty() {
        w.push_str(" AND (name LIKE ? OR destination_passport LIKE ?)");
        let like = format!("%{s}%"); p.push(T(like.clone())); p.push(T(like));
    }
    if let Some(c) = q.get("category").map(|x| x.trim()).filter(|x| !x.is_empty()) {
        w.push_str(" AND category = ?"); p.push(T(c.to_string()));
    }
    if let Some(n) = q.get("need_new_passport").map(|x| x.trim()).filter(|x| !x.is_empty()) {
        w.push_str(" AND need_new_passport = ?"); p.push(T(n.to_string()));
    }
    match q.get("passport_status").map(|x| x.trim()).unwrap_or("") {
        "storage" => w.push_str(" AND (passport_collect_date IS NULL OR passport_collect_date = '')"),
        "inuse" => w.push_str(" AND passport_collect_date IS NOT NULL AND passport_collect_date != '' AND (passport_return_date IS NULL OR passport_return_date = '')"),
        "overdue" => {
            let ids = travel_overdue_ids(conn, today);
            if ids.is_empty() { w.push_str(" AND 1=0"); }
            else { w.push_str(&format!(" AND id IN ({})", ids.iter().map(|i| i.to_string()).collect::<Vec<_>>().join(","))); }
        }
        _ => {}
    }
    let df = v::parse_date_input(q.get("date_from").map(|s| s.as_str()).unwrap_or(""));
    if !df.is_empty() { w.push_str(" AND travel_end >= ? AND travel_end != ''"); p.push(T(df)); }
    let dt = v::parse_date_input(q.get("date_to").map(|s| s.as_str()).unwrap_or(""));
    if !dt.is_empty() { w.push_str(" AND travel_start <= ? AND travel_start != ''"); p.push(T(dt)); }
    if !ids.is_empty() {
        w.push_str(&format!(" AND id IN ({})", vec!["?"; ids.len()].join(",")));
        for id in ids { p.push(I(*id)); }
    }
    (w, p)
}

pub async fn list(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    let q = query_args(&req.query);
    let today = helpers::now_local_ymd(st.cfg.tz_offset_hours);
    let (items, mut overdue_ids, mut deadlines) = {
        let conn = st.db.lock().unwrap();
        let (w, p) = travel_filters(&conn, &q, &[], &today);
        let items = helpers::list_all(&conn, &format!("SELECT * FROM travel_details WHERE 1=1{w} ORDER BY created_at DESC"), &p);
        (items, vec![], serde_json::Map::new())
    };
    if let Some(rows) = items.get("rows").and_then(|v| v.as_array()) {
        for row in rows {
            if helpers::is_cert_overdue(row, &today) {
                let id = helpers::row_i64(row, "id");
                overdue_ids.push(json!(id));
                deadlines.insert(id.to_string(), json!(helpers::cert_overdue_deadline(row)));
            }
        }
    }
    let category_opts = { let conn = st.db.lock().unwrap(); helpers::get_dict_options(&conn, "travel_category") };
    let data = json!({
        "items": items, "search": q.get("search").cloned().unwrap_or_default(),
        "category_filter": q.get("category").cloned().unwrap_or_default(),
        "need_passport_filter": q.get("need_new_passport").cloned().unwrap_or_default(),
        "passport_status": q.get("passport_status").cloned().unwrap_or_default(),
        "date_from": q.get("date_from").cloned().unwrap_or_default(),
        "date_to": q.get("date_to").cloned().unwrap_or_default(),
        "overdue_ids": overdue_ids, "deadlines": deadlines,
        "category_opts": category_opts,
    });
    page(&st, &mut req, "travel/list.html", data)
}

pub async fn attachments(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    let q = query_args(&req.query);
    let data = {
        let conn = st.db.lock().unwrap();
        let mut base = "SELECT a.id, a.file_name, a.file_type, a.file_size, a.uploaded_at, t.id AS travel_id, t.name, t.unit, t.destination_passport, t.travel_dates FROM attachments a JOIN travel_details t ON a.travel_id = t.id WHERE 1=1".to_string();
        let mut p: Vec<SqlValue> = vec![];
        let s = q.get("search").map(|x| x.trim()).unwrap_or("");
        if !s.is_empty() { base.push_str(" AND (t.name LIKE ? OR a.file_name LIKE ?)"); let like = format!("%{s}%"); p.push(T(like.clone())); p.push(T(like)); }
        if let Some(ft) = q.get("file_type").map(|x| x.trim()).filter(|x| !x.is_empty()) { base.push_str(" AND a.file_type = ?"); p.push(T(ft.to_string())); }
        if let Some(d) = q.get("date_from").map(|x| x.trim()).filter(|x| !x.is_empty()) { base.push_str(" AND date(a.uploaded_at) >= ?"); p.push(T(d.to_string())); }
        if let Some(d) = q.get("date_to").map(|x| x.trim()).filter(|x| !x.is_empty()) { base.push_str(" AND date(a.uploaded_at) <= ?"); p.push(T(d.to_string())); }
        let items = helpers::list_all(&conn, &format!("{base} ORDER BY a.uploaded_at DESC"), &p);

        // 缺件检查
        let travels = db::query_maps(&conn, "SELECT id, name, unit, need_new_passport FROM travel_details ORDER BY created_at DESC", &[]);
        let mut missing = vec![];
        for tv in &travels {
            let have_rows = db::query_maps(&conn, "SELECT DISTINCT file_type FROM attachments WHERE travel_id = ?", &[I(helpers::row_i64(tv, "id"))]);
            let have: std::collections::HashSet<String> = have_rows.iter().map(|h| helpers::row_str(h, "file_type")).collect();
            let (required, path): (&[&str], &str) = if helpers::row_str(tv, "need_new_passport") == "是" {
                (&["个人申请报告", "审批表", "同意申办函"], "B")
            } else {
                (&["个人申请报告", "审批表"], "A")
            };
            let lack: Vec<&str> = required.iter().filter(|r| !have.contains(**r)).copied().collect();
            if !lack.is_empty() {
                missing.push(json!({"id": helpers::row_i64(tv, "id"), "name": helpers::row_str(tv, "name"), "unit": helpers::row_str(tv, "unit"), "path": path, "lack": lack}));
            }
        }
        let tc = db::query_maps(&conn, "SELECT file_type, COUNT(*) AS cnt FROM attachments GROUP BY file_type", &[]);
        let mut type_counts = serde_json::Map::new();
        for k in ["个人申请报告", "审批表", "同意申办函"] { type_counts.insert(k.into(), json!(0)); }
        for tr in &tc { type_counts.insert(helpers::row_str(&tr, "file_type"), json!(helpers::row_i64(&tr, "cnt"))); }
        let total = db::count(&conn, "SELECT COUNT(*) FROM attachments", &[]);
        json!({
            "items": items, "search": q.get("search").cloned().unwrap_or_default(),
            "type_filter": q.get("file_type").cloned().unwrap_or_default(),
            "date_from": q.get("date_from").cloned().unwrap_or_default(),
            "date_to": q.get("date_to").cloned().unwrap_or_default(),
            "missing": missing, "type_counts": type_counts, "total_att": total,
            "types": ["个人申请报告", "审批表", "同意申办函"],
        })
    };
    page(&st, &mut req, "travel/attachments.html", data)
}

fn extract(form: &F, operator: &str) -> VForm {
    let mut m = VForm::new();
    for k in ["personnel_filing_id", "unit", "department", "name", "position", "title", "destination_passport", "category", "travel_dates", "passport_no"] {
        m.insert(k.into(), ff(form, k));
    }
    m.insert("id_number".into(), ff(form, "id_number").to_uppercase());
    let np = { let n = ff(form, "need_new_passport"); if n.is_empty() { "否".into() } else { n } };
    m.insert("need_new_passport".into(), np);
    for k in ["approval_date", "passport_collect_date", "passport_return_date", "actual_return_date"] {
        m.insert(k.into(), v::parse_date_input(&ff(form, k)));
    }
    m.insert("operator".into(), operator.to_string());
    m
}

fn validate(data: &VForm) -> Vec<String> {
    let mut errs = v::check_required(data, &[
        ("personnel_filing_id", "备案人员"), ("unit", "单位"), ("department", "部门"), ("name", "姓名"),
        ("position", "职务"), ("id_number", "身份证号"), ("destination_passport", "地点、证照"),
        ("category", "类别"), ("travel_dates", "计划出行日期"), ("need_new_passport", "是否做证"),
    ]);
    errs.extend(v::check_identity(data, "", ""));
    let td = data.get("travel_dates").cloned().unwrap_or_default();
    if !td.is_empty() {
        let (ok, msg) = v::validate_travel_range(&td);
        if !ok { errs.push(format!("计划出行日期: {msg}")); }
    }
    errs.extend(v::check_dates(data, &[("approval_date", "批准日期"), ("passport_collect_date", "证件领用日期"), ("passport_return_date", "证件归还日期"), ("actual_return_date", "实际回国日期")]));
    if data.get("need_new_passport").map(|s| s.as_str()) == Some("否") && data.get("passport_collect_date").map(|s| s.is_empty()).unwrap_or(true) {
        errs.push("路径A（已有证件）时，证件领用日期为必填。".into());
    }
    errs
}

fn missing_att_errors(files: &[(String, String, Vec<u8>)], need_new: &str) -> Vec<String> {
    let mut errs = vec![];
    let has = |field: &str| files.iter().any(|(n, fname, _)| n == field && !fname.is_empty());
    if !has("att_application") { errs.push("附件《个人申请报告》为必传项（PDF）。".into()); }
    if !has("att_approval") { errs.push("附件《审批表》为必传项（PDF）。".into()); }
    if need_new == "是" && !has("att_consent") { errs.push("需新办证件（路径B）时，《同意申办函》为必传项（PDF）。".into()); }
    for (name, fname, data) in files {
        if ATT_CATEGORIES.iter().any(|(f, _)| f == name) && !fname.is_empty() && !is_pdf(data) {
            errs.push(format!("文件 {fname} 内容不是有效的 PDF，请上传真实的 PDF 扫描件。"));
        }
    }
    errs
}

fn save_attachments(st: &St, files: &[(String, String, Vec<u8>)], travel_id: i64, warnings: &mut Vec<String>) {
    for (field, label) in ATT_CATEGORIES {
        for (name, fname, data) in files {
            if name != field || fname.is_empty() { continue; }
            if !fname.to_lowercase().ends_with(".pdf") { warnings.push(format!("文件 {fname} 格式不支持（仅允许 PDF）。")); continue; }
            if !is_pdf(data) { warnings.push(format!("文件 {fname} 内容不是有效的 PDF（已拒绝）。")); continue; }
            let saved = format!("{}.pdf", helpers::random_token());
            let path = st.cfg.upload_folder.join(&saved);
            if std::fs::write(&path, data).is_ok() {
                let conn = st.db.lock().unwrap();
                db::exec(&conn, "INSERT INTO attachments (travel_id, file_name, file_path, file_type, file_size) VALUES (?,?,?,?,?)",
                    &[I(travel_id), T(fname.clone()), T(saved), T(label.to_string()), I(data.len() as i64)]).ok();
            }
        }
    }
}

fn travel_params(d: &VForm, t_start: &str, t_end: &str) -> Vec<SqlValue> {
    vec![
        db::sv_opt(d.get("personnel_filing_id").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("unit").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("department").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("name").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("position").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("title").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("id_number").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("destination_passport").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("category").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("travel_dates").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(t_start), db::sv_opt(t_end),
        db::sv_opt(d.get("approval_date").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("need_new_passport").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("passport_no").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("passport_collect_date").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("passport_return_date").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("actual_return_date").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("operator").map(|s| s.as_str()).unwrap_or("")),
    ]
}

pub async fn new_get(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    let mut prefill = json!({});
    if let Some(fid) = query_args(&req.query).get("filing_id").and_then(|s| s.parse::<i64>().ok()) {
        let conn = st.db.lock().unwrap();
        if let Some(f) = db::query_one(&conn, "SELECT pf.*, COALESCE((SELECT unit FROM personnel_info WHERE id = pf.personnel_info_id), pf.work_unit) AS info_unit, COALESCE((SELECT department FROM personnel_info WHERE id = pf.personnel_info_id), '') AS info_dept FROM personnel_filing pf WHERE pf.id = ?", &[I(fid)]) {
            prefill = json!({
                "personnel_filing_id": fid, "unit": helpers::row_str(&f, "info_unit"), "department": helpers::row_str(&f, "info_dept"),
                "name": format!("{}{}", helpers::row_str(&f, "surname"), helpers::row_str(&f, "given_name")),
                "position": helpers::row_str(&f, "position_or_title"), "id_number": helpers::row_str(&f, "id_number"),
            });
        }
    }
    page(&st, &mut req, "travel/form.html", json!({"data": prefill, "editing": false}))
}

pub async fn new_post(State(st): State<St>, headers: HeaderMap, uri: Uri, mp: Multipart) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    let (form, files) = parse_multipart(mp).await;
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "travel.list", &[]); }
    let mut data = extract(&form, &req.sess.username());
    let mut errs = validate(&data);
    errs.extend(missing_att_errors(&files, data.get("need_new_passport").map(|s| s.as_str()).unwrap_or("否")));
    if !errs.is_empty() {
        for e in &errs { flash(&mut req, e, "danger"); }
        return page(&st, &mut req, "travel/form.html", json!({"data": vform_json(&data), "editing": false}));
    }
    let (ts, te) = v::parse_travel_range(data.get("travel_dates").map(|s| s.as_str()).unwrap_or(""));
    let canon = v::format_travel_range(&ts, &te);
    if !canon.is_empty() { data.insert("travel_dates".into(), canon); }
    let travel_id = {
        let conn = st.db.lock().unwrap();
        db::exec(&conn, "INSERT INTO travel_details (personnel_filing_id, unit, department, name, position, title, id_number, destination_passport, category, travel_dates, travel_start, travel_end, approval_date, need_new_passport, passport_no, passport_collect_date, passport_return_date, actual_return_date, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", &travel_params(&data, &ts, &te)).ok();
        conn.last_insert_rowid()
    };
    let mut warnings = vec![];
    save_attachments(&st, &files, travel_id, &mut warnings);
    for wmsg in &warnings { flash(&mut req, wmsg, "warning"); }
    { let conn = st.db.lock().unwrap(); let after = helpers::row_snapshot(&conn, "travel_details", travel_id); helpers::log_action(&conn, &req.sess.username(), &req.ip, "create", "travel_details", Some(travel_id), "", None, after); }
    flash(&mut req, "出国（境）明细表已保存。", "success");
    redirect(&st, &req, "travel.list", &[])
}

pub async fn edit_get(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(travel_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    let (row, atts) = {
        let conn = st.db.lock().unwrap();
        (db::query_one(&conn, "SELECT * FROM travel_details WHERE id = ?", &[I(travel_id)]),
         db::query_maps(&conn, "SELECT * FROM attachments WHERE travel_id = ? ORDER BY uploaded_at", &[I(travel_id)]))
    };
    match row {
        None => { flash(&mut req, "记录不存在。", "danger"); redirect(&st, &req, "travel.list", &[]) }
        Some(r) => page(&st, &mut req, "travel/form.html", json!({"data": r, "editing": true, "travel_id": travel_id, "attachments": atts})),
    }
}

pub async fn edit_post(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(travel_id): Path<i64>, mp: Multipart) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    let (form, files) = parse_multipart(mp).await;
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "travel.list", &[]); }
    let exists = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT id FROM travel_details WHERE id = ?", &[I(travel_id)]).is_some() };
    if !exists { flash(&mut req, "记录不存在。", "danger"); return redirect(&st, &req, "travel.list", &[]); }
    let mut data = extract(&form, &req.sess.username());
    let errs = validate(&data);
    if !errs.is_empty() {
        for e in &errs { flash(&mut req, e, "danger"); }
        return page(&st, &mut req, "travel/form.html", json!({"data": vform_json(&data), "editing": true, "travel_id": travel_id}));
    }
    let (ts, te) = v::parse_travel_range(data.get("travel_dates").map(|s| s.as_str()).unwrap_or(""));
    let canon = v::format_travel_range(&ts, &te);
    if !canon.is_empty() { data.insert("travel_dates".into(), canon); }
    {
        let conn = st.db.lock().unwrap();
        let before = helpers::row_snapshot(&conn, "travel_details", travel_id);
        let mut p = travel_params(&data, &ts, &te);
        p.push(I(travel_id));
        db::exec(&conn, "UPDATE travel_details SET personnel_filing_id=?, unit=?, department=?, name=?, position=?, title=?, id_number=?, destination_passport=?, category=?, travel_dates=?, travel_start=?, travel_end=?, approval_date=?, need_new_passport=?, passport_no=?, passport_collect_date=?, passport_return_date=?, actual_return_date=?, operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", &p).ok();
        let after = helpers::row_snapshot(&conn, "travel_details", travel_id);
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "update", "travel_details", Some(travel_id), "", before, after);
    }
    let mut warnings = vec![];
    save_attachments(&st, &files, travel_id, &mut warnings);
    for wmsg in &warnings { flash(&mut req, wmsg, "warning"); }
    flash(&mut req, "明细表已更新。", "success");
    redirect(&st, &req, "travel.list", &[])
}

pub async fn view(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(travel_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    let (row, atts) = {
        let conn = st.db.lock().unwrap();
        (db::query_one(&conn, "SELECT * FROM travel_details WHERE id = ?", &[I(travel_id)]),
         db::query_maps(&conn, "SELECT * FROM attachments WHERE travel_id = ? ORDER BY uploaded_at", &[I(travel_id)]))
    };
    match row {
        None => { flash(&mut req, "记录不存在。", "danger"); redirect(&st, &req, "travel.list", &[]) }
        Some(r) => page(&st, &mut req, "travel/view.html", json!({"travel": r, "attachments": atts})),
    }
}

pub async fn delete(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(travel_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "travel.list", &[]); }
    {
        let conn = st.db.lock().unwrap();
        let atts = db::query_maps(&conn, "SELECT file_path FROM attachments WHERE travel_id = ?", &[I(travel_id)]);
        for a in &atts { let _ = std::fs::remove_file(st.cfg.upload_folder.join(basename(&helpers::row_str(a, "file_path")))); }
        let before = helpers::row_snapshot(&conn, "travel_details", travel_id);
        db::exec(&conn, "DELETE FROM attachments WHERE travel_id = ?", &[I(travel_id)]).ok();
        db::exec(&conn, "DELETE FROM travel_details WHERE id = ?", &[I(travel_id)]).ok();
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "delete", "travel_details", Some(travel_id), "", before, None);
    }
    flash(&mut req, "出国申请记录已删除。", "info");
    redirect(&st, &req, "travel.list", &[])
}

pub async fn cancel(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(travel_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "travel.list", &[]); }
    let row = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT * FROM travel_details WHERE id = ?", &[I(travel_id)]) };
    let row = match row { Some(r) => r, None => { flash(&mut req, "记录不存在。", "danger"); return redirect(&st, &req, "travel.list", &[]); } };
    if helpers::row_str(&row, "trip_status") == "cancelled" {
        flash(&mut req, "该行程已处于取消状态。", "info");
        return redirect(&st, &req, "travel.view", &[("travel_id".into(), travel_id.to_string())]);
    }
    let mut cancel_date = v::parse_date_input(&ff(&form, "cancel_date"));
    if cancel_date.is_empty() { cancel_date = helpers::now_local_ymd(st.cfg.tz_offset_hours); }
    let (ok, msg) = v::validate_date_format(&cancel_date);
    if !ok { flash(&mut req, &format!("取消日期: {msg}"), "danger"); return redirect(&st, &req, "travel.view", &[("travel_id".into(), travel_id.to_string())]); }
    {
        let conn = st.db.lock().unwrap();
        let before = helpers::row_snapshot(&conn, "travel_details", travel_id);
        db::exec(&conn, "UPDATE travel_details SET trip_status='cancelled', cancel_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", &[T(cancel_date.clone()), I(travel_id)]).ok();
        let after = helpers::row_snapshot(&conn, "travel_details", travel_id);
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "cancel", "travel_details", Some(travel_id), &format!("取消行程（{cancel_date}）"), before, after);
    }
    flash(&mut req, &format!("行程已取消（{cancel_date}）。已申领证件请于 5 个工作日内送回保管。"), "warning");
    redirect(&st, &req, "travel.view", &[("travel_id".into(), travel_id.to_string())])
}

pub async fn restore(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(travel_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "travel.list", &[]); }
    let exists = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT id FROM travel_details WHERE id = ?", &[I(travel_id)]).is_some() };
    if !exists { flash(&mut req, "记录不存在。", "danger"); return redirect(&st, &req, "travel.list", &[]); }
    {
        let conn = st.db.lock().unwrap();
        let before = helpers::row_snapshot(&conn, "travel_details", travel_id);
        db::exec(&conn, "UPDATE travel_details SET trip_status='normal', cancel_date=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?", &[I(travel_id)]).ok();
        let after = helpers::row_snapshot(&conn, "travel_details", travel_id);
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "restore", "travel_details", Some(travel_id), "恢复行程为正常", before, after);
    }
    flash(&mut req, "行程已恢复为正常状态。", "success");
    redirect(&st, &req, "travel.view", &[("travel_id".into(), travel_id.to_string())])
}

fn basename(p: &str) -> String {
    p.rsplit(['/', '\\']).next().unwrap_or(p).to_string()
}

async fn serve_att(st: &St, req: &mut Req, att_id: i64, inline: bool) -> Response {
    let att = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT * FROM attachments WHERE id = ?", &[I(att_id)]) };
    let att = match att { Some(a) => a, None => { flash(req, "附件不存在。", "danger"); return redirect(&st, req, "travel.list", &[]); } };
    let full = st.cfg.upload_folder.join(basename(&helpers::row_str(&att, "file_path")));
    let bytes = match std::fs::read(&full) { Ok(b) => b, Err(_) => { flash(req, "附件文件缺失。", "danger"); return redirect(&st, req, "travel.list", &[]); } };
    let disp = if inline { "inline" } else { "attachment" };
    let fname = url_escape(&helpers::row_str(&att, "file_name"));
    let mut resp = (StatusCode::OK, bytes).into_response();
    resp.headers_mut().insert(header::CONTENT_TYPE, "application/pdf".parse().unwrap());
    resp.headers_mut().insert(header::CONTENT_DISPOSITION, format!("{disp}; filename*=UTF-8''{fname}").parse().unwrap());
    resp
}

fn url_escape(s: &str) -> String {
    const HEX: &[u8] = b"0123456789ABCDEF";
    let mut out = String::new();
    for &c in s.as_bytes() {
        if c.is_ascii_alphanumeric() || c == b'.' || c == b'-' || c == b'_' {
            out.push(c as char);
        } else {
            out.push('%');
            out.push(HEX[(c >> 4) as usize] as char);
            out.push(HEX[(c & 15) as usize] as char);
        }
    }
    out
}

pub async fn att_download(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(att_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    serve_att(&st, &mut req, att_id, false).await
}

pub async fn att_preview(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(att_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    serve_att(&st, &mut req, att_id, true).await
}

pub async fn att_delete(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(att_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) { return r; }
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "travel.list", &[]); }
    let travel_id = {
        let conn = st.db.lock().unwrap();
        match db::query_one(&conn, "SELECT * FROM attachments WHERE id = ?", &[I(att_id)]) {
            None => { drop(conn); flash(&mut req, "附件不存在。", "danger"); return redirect(&st, &req, "travel.list", &[]); }
            Some(att) => {
                let _ = std::fs::remove_file(st.cfg.upload_folder.join(basename(&helpers::row_str(&att, "file_path"))));
                let tid = helpers::row_i64(&att, "travel_id");
                db::exec(&conn, "DELETE FROM attachments WHERE id = ?", &[I(att_id)]).ok();
                tid
            }
        }
    };
    flash(&mut req, "附件已删除。", "info");
    redirect(&st, &req, "travel.edit", &[("travel_id".into(), travel_id.to_string())])
}

fn vform_json(d: &VForm) -> serde_json::Value {
    serde_json::to_value(d).unwrap_or(json!({}))
}

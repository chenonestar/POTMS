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

/// 全量计算「证件逾期未交回」记录的 id 集合。
///
/// 两类合并：
/// - 路径A：已领用 + 未归还 + 超工作日时限（判据在领用记录上）；
/// - 路径B：做证 + 新证尚未进入台账 + 超工作日时限（路径B 没有领用记录，
///   用老判据一条都抓不到，见 `helpers::is_new_cert_overdue` 的说明）。
fn travel_overdue_ids(conn: &rusqlite::Connection, today: &str) -> Vec<i64> {
    let rows = db::query_maps(conn, "SELECT id, passport_collect_date, passport_return_date, actual_return_date, travel_end, trip_status, cancel_date FROM travel_details WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' AND (passport_return_date IS NULL OR passport_return_date = '')", &[]);
    let mut ids: Vec<i64> = rows.iter().filter(|r| helpers::is_cert_overdue(r, today)).map(|r| helpers::row_i64(r, "id")).collect();

    let registered = helpers::registered_cert_travel_ids(conn);
    let new_rows = db::query_maps(conn, "SELECT id, need_new_passport, actual_return_date, travel_end, trip_status, cancel_date, passport_collect_date FROM travel_details WHERE need_new_passport = '是'", &[]);
    for r in &new_rows {
        // 已经走过领用流程的，归上面那套判据管，避免同一条记录被两边重复判定
        if !helpers::row_str(r, "passport_collect_date").is_empty() {
            continue;
        }
        if helpers::is_new_cert_overdue(r, today, &registered) {
            ids.push(helpers::row_i64(r, "id"));
        }
    }
    ids
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
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let q = query_args(&req.query);
    let today = helpers::now_local_ymd(st.cfg.tz_offset_hours);
    let (mut items, mut overdue_ids) = {
        let conn = st.db.lock().unwrap();
        let (w, p) = travel_filters(&conn, &q, &[], &today);
        let items = helpers::list_all(&conn, &format!("SELECT * FROM travel_details WHERE 1=1{w} ORDER BY created_at DESC"), &p);
        (items, vec![])
    };
    // 到期日直接挂在行上，而不是另下发一个 id → 到期日的 map。
    //
    // 原先下发的 map 键是 id.to_string()，模板里却写 deadlines[row.id]——row.id
    // 是整数，minijinja 查不到这个键，返回 undefined 并**静默渲染成空**，
    // 页面上就成了「应还: )」。Go 版同一处更直接，gonja 索引不了整数键，直接 500。
    // 两边都是同一个毛病：键的类型对不上。挂在行上就没有查表这一步了。
    // 路径A 看领用记录，路径B（做证、无领用记录）看新证是否已进入证照台账。
    let registered = { let conn = st.db.lock().unwrap(); helpers::registered_cert_travel_ids(&conn) };
    if let Some(rows) = items.get_mut("rows").and_then(|v| v.as_array_mut()) {
        for row in rows.iter_mut() {
            let late = helpers::is_cert_overdue(row, &today)
                || (helpers::row_str(row, "passport_collect_date").is_empty()
                    && helpers::is_new_cert_overdue(row, &today, &registered));
            if late {
                overdue_ids.push(json!(helpers::row_i64(row, "id")));
                let dl = helpers::cert_overdue_deadline(row);
                if let Some(obj) = row.as_object_mut() {
                    obj.insert("overdue_deadline".into(), json!(dl));
                }
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
        "overdue_ids": overdue_ids,
        "category_opts": category_opts,
    });
    page(&st, &mut req, "travel/list.html", data)
}

/// 把附件类型排成办件顺序（个人申请报告 → 审批表 → 同意申办函）的 CASE 表达式。
///
/// 这三个中文词按任何排序规则（拼音、笔画、UTF-8 码位）都排不出办件顺序，只能显式
/// 指定。次序直接取自 `ATT_CATEGORIES`——那里已经按办件顺序定义了三类附件，再手抄
/// 一份迟早两边漂移。表里出现的其它类型统一排在最后。
fn file_type_order_sql(col: &str) -> String {
    let mut out = format!("CASE {col}");
    for (i, (_, label)) in ATT_CATEGORIES.iter().enumerate() {
        out.push_str(&format!(" WHEN '{label}' THEN {}", i + 1));
    }
    out.push_str(&format!(" ELSE {} END", ATT_CATEGORIES.len() + 1));
    out
}

/// 附件总览的排序方式，白名单取值。
///
/// batch（默认）：先把同一条出行申请的附件聚成一组，组间与「出国明细」列表同序
/// （created_at DESC），组内按办件顺序。此前只按 uploaded_at 排，一旦有过补传，
/// 那条申请的附件就会被别人的插在中间，翻起来对不上人。
///
/// uploaded：保留原来的按上传时间倒序，找「最近传了什么」时更顺手。
///
/// 两种都以 a.id 收尾：uploaded_at 是 CURRENT_TIMESTAMP，只精确到秒，同一次提交
/// 上传的多个文件时间戳完全相同，没有兜底列的话它们之间的先后在 SQL 层面是未定义的。
fn att_order_by(sort: &str) -> String {
    match sort {
        "uploaded" => "ORDER BY a.uploaded_at DESC, a.id".to_string(),
        _ => format!("ORDER BY t.created_at DESC, t.id DESC, {}, a.id",
                     file_type_order_sql("a.file_type")),
    }
}

const ATT_SORT_DEFAULT: &str = "batch";

pub async fn attachments(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
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
        let sort = match q.get("sort").map(|x| x.trim()).unwrap_or("") {
            "uploaded" => "uploaded",
            _ => ATT_SORT_DEFAULT,
        };
        let items = helpers::list_all(&conn, &format!("{base} {}", att_order_by(sort)), &p);

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
            "sort": sort,
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
    // 证件领用 / 归还日期不再由本表单收集：它们是领用模块的派生字段，
    // 两处都能写就会出现「签了字的领用凭证」和「明细表上的日期」对不上。
    for k in ["approval_date", "actual_return_date"] {
        m.insert(k.into(), v::parse_date_input(&ff(form, k)));
    }
    m.insert("operator".into(), operator.to_string());
    m
}

fn validate(conn: &rusqlite::Connection, data: &VForm, today: &str) -> Vec<String> {
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
    errs.extend(v::check_dates(data, &[("approval_date", "批准日期"), ("actual_return_date", "实际回国日期")]));
    // 证件领用日期原在此校验必填，现已迁移至证件领用模块（须手写签名后登记），
    // 出行表单不再收集该字段。

    // 一本可用的证都没有，却说不做证——这条记录本身就是错的。
    //
    // 「够不够用」判不了：系统不知道这趟要用哪种证（明细表只有「地点、证照」
    // 那段自由文本），有港澳通行证但要去美国这类情形只能靠经办人自己看。
    // 但「一本都没有」是可判的，而且无论去哪都不可能有证用，属于硬错误。
    //
    // 「有证」要算有效期：一本过期护照等于没有。证照登记里填了号码就必须填
    // 有效日期，所以这个判断的数据一定在。
    let pfid = data.get("personnel_filing_id").cloned().unwrap_or_default();
    if data.get("need_new_passport").map(|s| s.as_str()) == Some("否") && !pfid.is_empty() {
        // 一个人可能有多条证照记录（历史遗留），任意一条里有在有效期内的证就算数
        let usable = db::query_one(conn,
            "SELECT 1 FROM certificates WHERE personnel_filing_id = ? AND ( \
               (passport_no IS NOT NULL AND passport_no != '' AND passport_expiry >= ?) OR \
               (hm_pass_no  IS NOT NULL AND hm_pass_no  != '' AND hm_pass_expiry  >= ?) OR \
               (tw_pass_no  IS NOT NULL AND tw_pass_no  != '' AND tw_pass_expiry  >= ?)) LIMIT 1",
            &[db::sv_opt(&pfid), T(today.to_string()), T(today.to_string()), T(today.to_string())]);
        if usable.is_none() {
            errs.push("该备案人员名下没有在有效期内的出入境证件，「是否做证」应为「是」。".into());
        }
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
        db::sv_opt(d.get("actual_return_date").map(|s| s.as_str()).unwrap_or("")),
        db::sv_opt(d.get("operator").map(|s| s.as_str()).unwrap_or("")),
    ]
}

pub async fn new_get(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
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
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let (form, files) = parse_multipart(mp).await;
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "travel.list", &[]); }
    let mut data = extract(&form, &req.sess.operator_name());
    let today = helpers::now_local_ymd(st.cfg.tz_offset_hours);
    let mut errs = { let conn = st.db.lock().unwrap(); validate(&conn, &data, &today) };
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
        db::exec(&conn, "INSERT INTO travel_details (personnel_filing_id, unit, department, name, position, title, id_number, destination_passport, category, travel_dates, travel_start, travel_end, approval_date, need_new_passport, passport_no, actual_return_date, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", &travel_params(&data, &ts, &te)).ok();
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
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let (row, atts) = {
        let conn = st.db.lock().unwrap();
        (db::query_one(&conn, "SELECT * FROM travel_details WHERE id = ?", &[I(travel_id)]),
         db::query_maps(&conn, "SELECT * FROM attachments WHERE travel_id = ? ORDER BY uploaded_at", &[I(travel_id)]))
    };
    match row {
        None => { flash(&mut req, "记录不存在。", "danger"); redirect(&st, &req, "travel.list", &[]) }
        Some(r) => {
            let derived = { let conn = st.db.lock().unwrap(); crate::handlers_issuance::travel_has_issuance(&conn, travel_id) };
            page(&st, &mut req, "travel/form.html", json!({"data": r, "editing": true, "travel_id": travel_id, "attachments": atts, "cert_no_derived": derived}))
        }
    }
}

pub async fn edit_post(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(travel_id): Path<i64>, mp: Multipart) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let (form, files) = parse_multipart(mp).await;
    if !csrf_check(&req, &form) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "travel.list", &[]); }
    let exists = { let conn = st.db.lock().unwrap(); db::query_one(&conn, "SELECT id FROM travel_details WHERE id = ?", &[I(travel_id)]).is_some() };
    if !exists { flash(&mut req, "记录不存在。", "danger"); return redirect(&st, &req, "travel.list", &[]); }
    let mut data = extract(&form, &req.sess.operator_name());
    let today = helpers::now_local_ymd(st.cfg.tz_offset_hours);
    let errs = { let conn = st.db.lock().unwrap(); validate(&conn, &data, &today) };
    if !errs.is_empty() {
        for e in &errs { flash(&mut req, e, "danger"); }
        let derived = { let conn = st.db.lock().unwrap(); crate::handlers_issuance::travel_has_issuance(&conn, travel_id) };
        return page(&st, &mut req, "travel/form.html", json!({"data": vform_json(&data), "editing": true, "travel_id": travel_id, "cert_no_derived": derived}));
    }
    let (ts, te) = v::parse_travel_range(data.get("travel_dates").map(|s| s.as_str()).unwrap_or(""));
    let canon = v::format_travel_range(&ts, &te);
    if !canon.is_empty() { data.insert("travel_dates".into(), canon); }
    {
        let conn = st.db.lock().unwrap();
        let before = helpers::row_snapshot(&conn, "travel_details", travel_id);
        // 有领用记录时证件号码由领用记录派生，表单上是只读的，提交上来的值不能覆盖它
        if crate::handlers_issuance::travel_has_issuance(&conn, travel_id) {
            let cur = db::query_one(&conn, "SELECT passport_no FROM travel_details WHERE id = ?", &[I(travel_id)])
                .map(|r| helpers::row_str(&r, "passport_no")).unwrap_or_default();
            data.insert("passport_no".into(), cur);
        }
        let mut p = travel_params(&data, &ts, &te);
        p.push(I(travel_id));
        db::exec(&conn, "UPDATE travel_details SET personnel_filing_id=?, unit=?, department=?, name=?, position=?, title=?, id_number=?, destination_passport=?, category=?, travel_dates=?, travel_start=?, travel_end=?, approval_date=?, need_new_passport=?, passport_no=?, actual_return_date=?, operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", &p).ok();
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
    if let Some(r) = require_login(&st, &mut req) { return r; }
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
    if let Some(r) = require_login(&st, &mut req) { return r; }
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
    if let Some(r) = require_login(&st, &mut req) { return r; }
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
    if let Some(r) = require_login(&st, &mut req) { return r; }
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
    if let Some(r) = require_login(&st, &mut req) { return r; }
    serve_att(&st, &mut req, att_id, false).await
}

pub async fn att_preview(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(att_id): Path<i64>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    serve_att(&st, &mut req, att_id, true).await
}

pub async fn att_delete(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(att_id): Path<i64>, Form(form): Form<F>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
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

// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    /// 「证件逾期未还」分支此前从未被渲染过。用相对今天的日期造数据，
    /// 让它永远处于逾期状态，不依赖运行的是哪一天。
    fn ymd_days_ago(n: i64) -> String {
        let t = time::OffsetDateTime::now_utc() - time::Duration::days(n);
        format!("{:04}{:02}{:02}", t.year(), t.month() as u8, t.day())
    }

    struct App {
        router: axum::Router,
        cookie: String,
        csrf: String,
        db: crate::render::Db,
    }

    impl App {
        fn new() -> App {
            let tmp = std::env::temp_dir().join(format!(
                "potms-travel-{}-{:?}", std::process::id(), std::thread::current().id()));
            let _ = std::fs::remove_dir_all(&tmp);
            std::fs::create_dir_all(&tmp).unwrap();
            unsafe { std::env::set_var("POTMS_BASE", &tmp) };
            let cfg = crate::config::Config::load();

            let conn = rusqlite::Connection::open_in_memory().unwrap();
            crate::db::init_schema(&conn);
            crate::db::run_migrations(&conn);
            crate::db::seed_data(&conn);
            let ago = ymd_days_ago(90);
            conn.execute(
                "INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,\
                    residence,political_status,work_unit,position_or_title,supervisor_unit,operator) \
                 VALUES (1,'逾','期某','男','19900101','110101199001012133','浙江杭州市西湖区',\
                    '群众','总部','处级','人事处','admin')", []).unwrap();
            conn.execute(
                "INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,\
                    id_number,destination_passport,category,travel_dates,travel_start,travel_end,\
                    need_new_passport,actual_return_date,passport_collect_date,operator) \
                 VALUES (1,1,'总部','办公室','逾期某','处级','110101199001012133','德国','因私',\
                    ?1,?2,?3,'否',?4,?5,'admin')",
                rusqlite::params![format!("{ago}-{ago}"), &ago, &ago, &ago, ymd_days_ago(120)],
            ).unwrap();

            let db: crate::render::Db = std::sync::Arc::new(std::sync::Mutex::new(conn));
            let env = crate::render::build_env(db.clone(), cfg.clone());
            let state: crate::St = std::sync::Arc::new(crate::AppState {
                db, env, cfg: cfg.clone(), lockout: crate::session::Lockout::default(),
            });
            let mut sess = crate::session::Session::default();
            sess.login("admin", "");
            let csrf = sess.csrf_token();
            let cookie = sess.to_cookie(&cfg.secret_key);
            let cookie = cookie.split(';').next().unwrap().to_string();
            App { router: crate::build_app(state.clone()), cookie, csrf, db: state.db.clone() }
        }

        /// 提交后跟随重定向再取落地页——flash 存在会话 cookie 里，本夹具的 cookie
        /// 是固定的，不跟着响应更新，所以必须把响应里的 Set-Cookie 带到下一跳，
        /// 否则提示信息永远看不到。
        async fn post_then(&self, path: &str, fields: &[(&str, &str)], next: &str) -> String {
            let mut body = format!("csrf_token={}", urlencoding::encode(&self.csrf));
            for (k, val) in fields {
                body.push('&');
                body.push_str(&format!("{}={}", urlencoding::encode(k), urlencoding::encode(val)));
            }
            let req = Request::builder().method("POST").uri(path)
                .header("Cookie", &self.cookie)
                .header("Content-Type", "application/x-www-form-urlencoded")
                .body(Body::from(body)).unwrap();
            let res = self.router.clone().oneshot(req).await.unwrap();
            let cookie = res.headers().get(axum::http::header::SET_COOKIE)
                .and_then(|v| v.to_str().ok())
                .map(|v| v.split(';').next().unwrap_or("").to_string())
                .unwrap_or_else(|| self.cookie.clone());
            let req = Request::builder().uri(next)
                .header("Cookie", cookie)
                .body(Body::empty()).unwrap();
            let res = self.router.clone().oneshot(req).await.unwrap();
            let bytes = axum::body::to_bytes(res.into_body(), usize::MAX).await.unwrap();
            String::from_utf8_lossy(&bytes).into_owned()
        }

        async fn post(&self, path: &str, fields: &[(&str, &str)]) -> (StatusCode, String) {
            let mut body = format!("csrf_token={}", urlencoding::encode(&self.csrf));
            for (k, val) in fields {
                body.push('&');
                body.push_str(&format!("{}={}", urlencoding::encode(k), urlencoding::encode(val)));
            }
            let req = Request::builder().method("POST").uri(path)
                .header("Cookie", &self.cookie)
                .header("Content-Type", "application/x-www-form-urlencoded")
                .body(Body::from(body)).unwrap();
            let res = self.router.clone().oneshot(req).await.unwrap();
            let status = res.status();
            let bytes = axum::body::to_bytes(res.into_body(), usize::MAX).await.unwrap();
            (status, String::from_utf8_lossy(&bytes).into_owned())
        }

        /// 出国明细表单走 multipart（要收附件），这里手搓一个最小请求体。
        async fn post_multipart(&self, path: &str, fields: &[(&str, &str)]) -> (StatusCode, String) {
            const B: &str = "----potmstestboundary";
            let mut body = String::new();
            let mut push = |k: &str, v: &str| {
                body.push_str(&format!(
                    "--{B}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"));
            };
            push("csrf_token", &self.csrf);
            for (k, v) in fields { push(k, v); }
            body.push_str(&format!("--{B}--\r\n"));
            let req = Request::builder().method("POST").uri(path)
                .header("Cookie", &self.cookie)
                .header("Content-Type", format!("multipart/form-data; boundary={B}"))
                .body(Body::from(body)).unwrap();
            let res = self.router.clone().oneshot(req).await.unwrap();
            let status = res.status();
            let bytes = axum::body::to_bytes(res.into_body(), usize::MAX).await.unwrap();
            (status, String::from_utf8_lossy(&bytes).into_owned())
        }

        fn exec(&self, sql: &str) {
            self.db.lock().unwrap().execute_batch(sql).unwrap();
        }
        fn scalar(&self, sql: &str) -> String {
            self.db.lock().unwrap()
                .query_row(sql, [], |r| r.get::<_, Option<String>>(0))
                .ok().flatten().unwrap_or_default()
        }
        fn count(&self, sql: &str) -> i64 {
            self.db.lock().unwrap().query_row(sql, [], |r| r.get(0)).unwrap_or(-1)
        }
        fn overdue_ids(&self, today: &str) -> Vec<i64> {
            super::travel_overdue_ids(&self.db.lock().unwrap(), today)
        }

        async fn get(&self, path: &str) -> (StatusCode, String) {
            let req = Request::builder().uri(path)
                .header("Cookie", &self.cookie)
                .body(Body::empty()).unwrap();
            let res = self.router.clone().oneshot(req).await.unwrap();
            let status = res.status();
            let bytes = axum::body::to_bytes(res.into_body(), usize::MAX).await.unwrap();
            (status, String::from_utf8_lossy(&bytes).into_owned())
        }
    }

    #[tokio::test]
    async fn travel_list_renders_overdue_branch() {
        let app = App::new();
        let (status, body) = app.get("/travel/").await;
        assert_eq!(status, StatusCode::OK, "/travel/ → {status}\n{}",
                   &body[..body.len().min(600)]);
        assert!(body.contains("逾期未还"), "页面上没有逾期提示块");
        assert!(body.contains("逾期某"), "逾期提示块里没有列出该人员");
        // 只查「应还」这两个字不够——deadlines 取不到值时它照样在，后面跟的是空。
        // 必须确认真印出了一个 8 位日期。为一条断言引依赖不值当，用标准库切。
        let after: String = body
            .split("应还")
            .skip(1)
            .map(|seg| seg.trim_start_matches([':', ' ']).chars().take(8).collect::<String>())
            .find(|d: &String| d.len() == 8 && d.chars().all(|c| c.is_ascii_digit()))
            .unwrap_or_default();
        let ctx: String = body.split("应还").nth(1).unwrap_or("").chars().take(60).collect();
        assert!(!after.is_empty(), "应还到期日为空，实际渲染：「应还{ctx}」");
    }

    // -----------------------------------------------------------------------
    // 第 2 批：领用挂申请 / 路径B 逾期 / 号码派生 / 做证校验
    // -----------------------------------------------------------------------

    const PNG_DATA_URL: &str = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ\
AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

    /// 再造两条都已回国 90 天、证都没交回的申请，区别只在是否做证。
    /// 备案人 1 名下有在有效期内的护照（路径A），备案人 2 一本证都没有（路径B）。
    fn seed_two_paths(app: &App) {
        let ago = ymd_days_ago(90);
        app.exec(&format!(
            "INSERT INTO certificates (personnel_filing_id,unit,department,name,\
                passport_no,passport_expiry,passport_submit_date,operator) \
             VALUES (1,'总部','技术部','逾期某','E12345678','20360101','20250101','admin');\
             INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,\
                residence,political_status,work_unit,position_or_title,supervisor_unit,operator) \
             VALUES (2,'李','四','男','19900101','110101199001012133','浙江杭州市西湖区',\
                '群众','总部','科长','人事处','admin');\
             INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,\
                id_number,destination_passport,category,travel_dates,travel_start,travel_end,\
                need_new_passport,actual_return_date,operator) \
             VALUES (801,1,'总部','技术部','路径A张三','科长','110101199001012133','美国/护照',\
                '因私','{ago}-{ago}','{ago}','{ago}','否','{ago}','admin');\
             INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,\
                id_number,destination_passport,category,travel_dates,travel_start,travel_end,\
                need_new_passport,actual_return_date,operator) \
             VALUES (802,2,'总部','技术部','路径B李四','科长','110101199001012133','美国/护照',\
                '因私','{ago}-{ago}','{ago}','{ago}','是','{ago}','admin');"));
    }

    /// 提交一条挂在申请 801 上的领用登记。
    async fn post_issue(app: &App, over: &[(&str, &str)]) -> (StatusCode, String) {
        let ago = ymd_days_ago(90);
        let mut fields: Vec<(&str, &str)> = vec![
            ("travel_id", "801"), ("personnel_filing_id", "1"), ("holder_name", "路径A张三"),
            ("id_number", "110101199001012133"), ("cert_types", "01"),
            ("cert_nos", "E12345678"), ("issue_date", &ago), ("sign_png", PNG_DATA_URL),
        ];
        // 同名键后出现的覆盖先出现的：cert_types 需要能追加成多个，其余替换
        for (k, v) in over {
            if *k == "cert_types" { fields.push((k, v)); continue; }
            match fields.iter_mut().find(|(fk, _)| fk == k) {
                Some(slot) => slot.1 = v,
                None => fields.push((k, v)),
            }
        }
        app.post("/issuance/new", &fields).await
    }

    // ---- A1 领用必须挂出国申请 ----

    #[tokio::test]
    async fn issue_without_travel_is_rejected() {
        let app = App::new();
        seed_two_paths(&app);
        let (_, body) = post_issue(&app, &[("travel_id", "")]).await;
        assert!(body.contains("关联出国申请"), "未提示必须关联出国申请");
        assert_eq!(app.count("SELECT COUNT(*) FROM cert_issuance"), 0, "无主的领用记录被写进库了");
    }

    #[tokio::test]
    async fn issue_with_unknown_travel_is_rejected() {
        let app = App::new();
        seed_two_paths(&app);
        let (_, body) = post_issue(&app, &[("travel_id", "999")]).await;
        assert!(body.contains("关联的出国申请不存在"), "未校验申请是否存在");
        assert_eq!(app.count("SELECT COUNT(*) FROM cert_issuance"), 0);
    }

    #[tokio::test]
    async fn holder_must_match_applicant() {
        let app = App::new();
        seed_two_paths(&app);
        // 证是为这条申请借的，不能借给别人
        let (_, body) = post_issue(&app,
            &[("personnel_filing_id", "2"), ("holder_name", "路径B李四")]).await;
        assert!(body.contains("与该出国申请的申请人不一致"), "领用人与申请人不一致未被拦下");
        assert_eq!(app.count("SELECT COUNT(*) FROM cert_issuance"), 0);
    }

    #[tokio::test]
    async fn cancelled_trip_cannot_issue() {
        let app = App::new();
        seed_two_paths(&app);
        app.exec("UPDATE travel_details SET trip_status='cancelled' WHERE id=801");
        let (_, body) = post_issue(&app, &[]).await;
        assert!(body.contains("已取消行程"), "已取消的行程仍能领用");
        assert_eq!(app.count("SELECT COUNT(*) FROM cert_issuance"), 0);
    }

    #[tokio::test]
    async fn one_cert_per_application() {
        let app = App::new();
        seed_two_paths(&app);
        let (_, body) = post_issue(&app, &[("cert_types", "02")]).await;
        assert!(body.contains("只能领用一本证件"), "一次申请领多本未被拦下");
        assert_eq!(app.count("SELECT COUNT(*) FROM cert_issuance"), 0);
    }

    #[tokio::test]
    async fn new_without_travel_id_shows_picker() {
        let app = App::new();
        seed_two_paths(&app);
        let (status, body) = app.get("/issuance/new").await;
        assert_eq!(status, StatusCode::OK, "/issuance/new → {status}");
        for want in ["选择出国申请", "登记领用", "路径A张三"] {
            assert!(body.contains(want), "选择页缺少「{want}」");
        }
    }

    #[tokio::test]
    async fn picker_excludes_cancelled_and_active_issuance() {
        let app = App::new();
        seed_two_paths(&app);
        assert_eq!(post_issue(&app, &[]).await.0, StatusCode::SEE_OTHER, "领用登记失败");
        app.exec("UPDATE travel_details SET trip_status='cancelled' WHERE id=802");
        let (_, body) = app.get("/issuance/new").await;
        assert!(!body.contains("路径A张三"), "已有未归还领用的申请仍出现在可选列表里");
        assert!(!body.contains("路径B李四"), "已取消的行程仍出现在可选列表里");
    }

    // ---- A2 路径B 的逾期告警 ----

    #[tokio::test]
    async fn path_b_without_registered_cert_is_overdue() {
        let app = App::new();
        seed_two_paths(&app);
        assert_eq!(post_issue(&app, &[]).await.0, StatusCode::SEE_OTHER, "领用登记失败");
        let ids = app.overdue_ids(&ymd_days_ago(0));
        assert!(ids.contains(&801), "路径A 已领未还且逾期，却没被抓到");
        assert!(ids.contains(&802), "路径B 回国 90 天、证没交回，却没被抓到");
    }

    #[tokio::test]
    async fn path_b_cleared_once_cert_registered() {
        let app = App::new();
        seed_two_paths(&app);
        app.exec("UPDATE travel_details SET passport_no='E99999999' WHERE id=802;\
                  INSERT INTO certificates (personnel_filing_id,unit,department,name,\
                     passport_no,passport_expiry,passport_submit_date,operator) \
                  VALUES (2,'总部','技术部','路径B李四','E99999999','20360101','20260101','admin');");
        assert!(!app.overdue_ids(&ymd_days_ago(0)).contains(&802), "证已进台账仍在告警");
    }

    #[tokio::test]
    async fn path_b_number_recorded_but_not_registered_still_overdue() {
        let app = App::new();
        seed_two_paths(&app);
        app.exec("UPDATE travel_details SET passport_no='E99999999' WHERE id=802");
        assert!(app.overdue_ids(&ymd_days_ago(0)).contains(&802),
                "只补录号码未入台账，应仍算逾期");
    }

    #[tokio::test]
    async fn path_b_not_overdue_before_deadline() {
        let app = App::new();
        seed_two_paths(&app);
        let today = ymd_days_ago(0);
        app.exec(&format!(
            "UPDATE travel_details SET actual_return_date='{today}', travel_end='{today}' WHERE id=802"));
        assert!(!app.overdue_ids(&today).contains(&802), "还没到期就报了逾期");
    }

    #[tokio::test]
    async fn path_b_shows_on_travel_list() {
        let app = App::new();
        seed_two_paths(&app);
        let (status, body) = app.get("/travel/?passport_status=overdue").await;
        assert_eq!(status, StatusCode::OK);
        assert!(body.contains("路径B李四"), "逾期筛选没带上路径B");
    }

    #[tokio::test]
    async fn path_b_counts_on_dashboard() {
        let app = App::new();
        seed_two_paths(&app);
        let (status, body) = app.get("/").await;
        assert_eq!(status, StatusCode::OK);
        // 不能只断言姓名出现在页面上——「近期出行」板块本来就会列出这个人，
        // 那样即使逾期统计完全失灵也照样通过。查姓名后面是否跟着「应还」。
        let seg: String = body.split("路径B李四").nth(1).unwrap_or("").chars().take(200).collect();
        assert!(seg.contains("应还"), "仪表盘逾期清单里没有路径B，实际：{seg}");
    }

    // ---- C 证件号码派生 ----

    #[tokio::test]
    async fn cert_no_derived_from_issuance() {
        let app = App::new();
        seed_two_paths(&app);
        assert_eq!(post_issue(&app, &[("cert_nos", "E77778888")]).await.0, StatusCode::SEE_OTHER);
        assert_eq!(app.scalar("SELECT passport_no FROM travel_details WHERE id=801"), "E77778888",
                   "证件号码未从领用记录派生到出行表");

        // 表单上那一栏应变成只读。不能只查页面上有没有 readonly——领用日期、
        // 归还日期两栏本来就是只读的，那样查恒为真。只看 passport_no 这个 input。
        let (_, body) = app.get("/travel/801/edit").await;
        let i = body.find("name=\"passport_no\"").expect("页面上找不到证件号码输入框");
        let start = body[..i].rfind("<input").unwrap();
        let end = i + body[i..].find('>').unwrap();
        let tag = &body[start..=end];
        assert!(tag.contains("readonly"), "有领用记录时证件号码栏未置为只读：{tag}");

        // 就算绕过只读直接提交，也不能覆盖派生值
        app.post_multipart("/travel/801/edit", &[
            ("personnel_filing_id", "1"), ("unit", "总部"), ("department", "技术部"),
            ("name", "路径A张三"), ("position", "科长"), ("id_number", "110101199001012133"),
            ("destination_passport", "美国-护照"), ("category", "旅游"),
            ("travel_dates", "2026/09/01-2026/09/11"), ("need_new_passport", "否"),
            ("passport_no", "BOGUS999"),
        ]).await;
        assert_eq!(app.scalar("SELECT passport_no FROM travel_details WHERE id=801"), "E77778888",
                   "绕过只读的提交覆盖了派生的证件号码");
    }

    // ---- D 做证校验 ----

    async fn post_travel(app: &App, over: &[(&str, &str)]) -> String {
        let mut fields: Vec<(&str, &str)> = vec![
            ("personnel_filing_id", "2"), ("unit", "总部"), ("department", "技术部"),
            ("name", "李四"), ("position", "科长"), ("id_number", "110101199001012133"),
            ("destination_passport", "美国-护照"), ("category", "旅游"),
            ("travel_dates", "2026/09/01-2026/09/11"), ("need_new_passport", "否"),
        ];
        for (k, v) in over {
            match fields.iter_mut().find(|(fk, _)| fk == k) {
                Some(slot) => slot.1 = v,
                None => fields.push((k, v)),
            }
        }
        app.post_multipart("/travel/new", &fields).await.1
    }

    #[tokio::test]
    async fn no_usable_cert_must_make_new() {
        let app = App::new();
        seed_two_paths(&app);   // 备案人 2 名下一本证都没有
        let body = post_travel(&app, &[]).await;
        assert!(body.contains("没有在有效期内的出入境证件"),
                "一本证都没有却填「不做证」，未被拦下");
    }

    #[tokio::test]
    async fn expired_cert_counts_as_none() {
        let app = App::new();
        seed_two_paths(&app);
        // 一本过期护照等于没有——只看有没有号码是不够的
        app.exec("INSERT INTO certificates (personnel_filing_id,unit,department,name,\
                     passport_no,passport_expiry,passport_submit_date,operator) \
                  VALUES (2,'总部','技术部','李四','E11112222','20200101','20190101','admin')");
        let body = post_travel(&app, &[]).await;
        assert!(body.contains("没有在有效期内的出入境证件"), "过期证件被当成可用");
    }

    #[tokio::test]
    async fn valid_cert_passes_path_a() {
        let app = App::new();
        seed_two_paths(&app);
        app.exec("INSERT INTO certificates (personnel_filing_id,unit,department,name,\
                     hm_pass_no,hm_pass_expiry,hm_pass_submit_date,operator) \
                  VALUES (2,'总部','技术部','李四','C11112222','20360101','20260101','admin')");
        let body = post_travel(&app, &[]).await;
        assert!(!body.contains("没有在有效期内的出入境证件"),
                "名下有在有效期内的证件，却被判为必须做证");
    }

    #[tokio::test]
    async fn need_new_passport_skips_cert_check() {
        let app = App::new();
        seed_two_paths(&app);
        // 做证=是 时本来就没证，不该报这条
        let body = post_travel(&app, &[("need_new_passport", "是")]).await;
        assert!(!body.contains("没有在有效期内的出入境证件"), "做证=是 时不该校验名下证件");
    }

    // -----------------------------------------------------------------------
    // 第 3 批：附件总览排序、证照一人一行 + 换发提醒
    // -----------------------------------------------------------------------

    /// 造两条申请各带两个附件，且刻意让上传时间交叉：申请 901 的附件一早一晚，
    /// 申请 902 的夹在中间。按上传时间排会把 902 插进 901 中间；按批次排则各自聚拢。
    fn seed_attachments(app: &App) {
        for tid in [901, 902] {
            app.exec(&format!(
                "INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,\
                    id_number,destination_passport,category,travel_dates,need_new_passport,operator) \
                 VALUES ({tid},1,'总部','技术部','批次{tid}','科长','110101199001012133',\
                    '美国/护照','因私','2026/03/01-2026/03/10','否','admin')"));
        }
        for (id, tid, ftype, up) in [
            (9011, 901, "审批表", "2026-03-05 10:00:00"),        // 901 的第二件，先传
            (9021, 902, "个人申请报告", "2026-03-06 10:00:00"),   // 902 的，夹在中间
            (9012, 901, "个人申请报告", "2026-03-07 10:00:00"),   // 901 的第一件，后补传
            (9022, 902, "审批表", "2026-03-08 10:00:00"),
        ] {
            app.exec(&format!(
                "INSERT INTO attachments (id,travel_id,file_name,file_path,file_type,file_size,uploaded_at) \
                 VALUES ({id},{tid},'f{id}.pdf','x.pdf','{ftype}',1024,'{up}')"));
        }
    }

    /// 断言几个片段在页面上按给定顺序出现。
    fn assert_order(body: &str, keys: &[&str], what: &str) {
        let mut last = 0usize;
        for k in keys {
            let pos = body.find(k).unwrap_or_else(|| panic!("{what}：页面上没有 {k}"));
            assert!(pos >= last, "{what}：{k} 出现得太早（{pos} < {last}）");
            last = pos;
        }
    }

    #[tokio::test]
    async fn attachments_grouped_by_batch_by_default() {
        let app = App::new();
        seed_attachments(&app);
        let (status, body) = app.get("/travel/attachments").await;
        assert_eq!(status, StatusCode::OK, "/travel/attachments → {status}");
        // 默认按批次：902 那组（created_at 更晚）整组在前，组内按办件顺序
        assert_order(&body, &["f9021.pdf", "f9022.pdf", "f9012.pdf", "f9011.pdf"],
                     "默认排序不是「按批次聚组 + 组内办件顺序」");
    }

    #[tokio::test]
    async fn attachments_sort_by_uploaded_time() {
        let app = App::new();
        seed_attachments(&app);
        let (_, body) = app.get("/travel/attachments?sort=uploaded").await;
        assert_order(&body, &["f9022.pdf", "f9012.pdf", "f9021.pdf", "f9011.pdf"],
                     "sort=uploaded 没有按上传时间倒序");
        assert!(body.contains("value=\"uploaded\" selected"), "排序选择器没有回显 uploaded");
    }

    #[tokio::test]
    async fn attachments_sort_falls_back_on_garbage() {
        let app = App::new();
        seed_attachments(&app);
        // 白名单之外的取值不能拼进 SQL，退回默认排序而不是报错
        let (status, body) = app.get("/travel/attachments?sort=a.id%3B%20DROP%20TABLE%20attachments").await;
        assert_eq!(status, StatusCode::OK, "非法排序参数把页面打挂了");
        assert!(body.contains("f9021.pdf"), "非法排序参数下附件列表为空");
        assert!(app.count("SELECT COUNT(*) FROM attachments") > 0,
                "attachments 表没了——排序参数被拼进了 SQL");
    }

    // ---- 证照一人一行 + 换发提醒 ----

    /// 提交一条证照登记，over 覆盖默认字段。
    async fn post_cert(app: &App, over: &[(&str, &str)]) -> (StatusCode, String) {
        let mut fields: Vec<(&str, &str)> = vec![
            ("personnel_filing_id", "1"), ("unit", "总部"), ("department", "技术部"),
            ("name", "逾期某"), ("passport_no", "E20000001"),
            ("passport_expiry", "20360101"), ("passport_submit_date", "20260101"),
        ];
        for (k, v) in over {
            match fields.iter_mut().find(|(fk, _)| fk == k) {
                Some(slot) => slot.1 = v,
                None => fields.push((k, v)),
            }
        }
        app.post("/certificate/new", &fields).await
    }

    #[tokio::test]
    async fn certificate_one_row_per_person() {
        let app = App::new();
        // 备案人 1 先有一条证照
        assert_eq!(post_cert(&app, &[]).await.0, StatusCode::SEE_OTHER, "首次登记应放行");
        let (_, body) = post_cert(&app, &[("passport_no", "E30000003")]).await;
        assert!(body.contains("已有证照记录"), "同一备案人员被允许建第二条证照记录");
        assert_eq!(app.count("SELECT COUNT(*) FROM certificates WHERE personnel_filing_id = 1"), 1,
                   "库里应仍只有 1 条证照记录");
    }

    #[tokio::test]
    async fn certificate_renewal_warns_about_dates() {
        let app = App::new();
        assert_eq!(post_cert(&app, &[]).await.0, StatusCode::SEE_OTHER);
        // 换发：只改号码，日期没跟着改
        let body = app.post_then("/certificate/1/edit", &[
            ("personnel_filing_id", "1"), ("unit", "总部"), ("department", "技术部"),
            ("name", "逾期某"), ("passport_no", "E99999999"),
            ("passport_expiry", "20360101"), ("passport_submit_date", "20260101"),
        ], "/certificate/").await;
        assert!(body.contains("号码已变更"), "换发后没有提醒同步日期");
        assert!(body.contains("普通护照"), "提醒里没有说明是哪一类证件");
    }

    #[tokio::test]
    async fn certificate_edit_without_number_change_is_quiet() {
        let app = App::new();
        assert_eq!(post_cert(&app, &[]).await.0, StatusCode::SEE_OTHER);
        // 号码没动，只改了部门——不是换发，不该提醒
        let body = app.post_then("/certificate/1/edit", &[
            ("personnel_filing_id", "1"), ("unit", "总部"), ("department", "办公室"),
            ("name", "逾期某"), ("passport_no", "E20000001"),
            ("passport_expiry", "20360101"), ("passport_submit_date", "20260101"),
        ], "/certificate/").await;
        assert!(!body.contains("号码已变更"),
                "号码没变也提醒了换发——这条提醒会被当成噪音，很快没人看");
    }
}

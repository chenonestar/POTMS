// 导出 / 在线打印 / 批量打印
use crate::handlers_misc::send_xlsx;
use crate::{db, flash, helpers, page, query_args, redirect, require_login, selected_ids, Req, St};
use axum::extract::{Path, State};
use axum::http::{HeaderMap, Uri};
use axum::response::Response;
use rusqlite::types::Value::Integer as I;
use serde_json::json;

fn scope_note(where_sql: &str, ids: &[i64]) -> String {
    if !ids.is_empty() { format!("选中{}行", ids.len()) }
    else if !where_sql.is_empty() { "按筛选条件".into() }
    else { "全量".into() }
}

macro_rules! export_handler {
    ($name:ident, $target:expr, $back:expr, $build:expr) => {
        pub async fn $name(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
            let mut req = Req::new(&st, &headers, &uri);
            if let Some(r) = require_login(&st, &mut req) { return r; }
            let q = query_args(&req.query);
            let ids = selected_ids(&req.query);
            let (path, filename, where_) = {
                let conn = st.db.lock().unwrap();
                let (path, filename, where_) = $build(&conn, &st.cfg, &req.sess.username(), &q, &ids);
                (path, filename, where_)
            };
            match path {
                Some(p) => {
                    { let conn = st.db.lock().unwrap();
                      helpers::log_action(&conn, &req.sess.username(), &req.ip, "export", $target, None, &format!("{}（{}）", filename, scope_note(&where_, &ids)), None, None); }
                    send_xlsx(&p, &filename)
                }
                None => { flash(&mut req, "导出失败。", "danger"); redirect(&st, &req, $back, &[]) }
            }
        }
    };
}

export_handler!(info_export, "personnel_info", "personnel.list", |conn, cfg, op, q: &std::collections::HashMap<String,String>, ids: &[i64]| {
    let (w, p) = crate::handlers_personnel::personnel_filters(q, ids);
    let (path, fname) = crate::excel::export_personnel_info(conn, cfg, op, &w, &p);
    (path, fname, w)
});
export_handler!(filing_export, "personnel_filing", "personnel.list", |conn, cfg, op, q: &std::collections::HashMap<String,String>, ids: &[i64]| {
    let (w, p) = crate::handlers_personnel::personnel_filters(q, ids);
    let (path, fname) = crate::excel::export_personnel_filing(conn, cfg, op, &w, &p);
    (path, fname, w)
});
export_handler!(certificate_export, "certificates", "certificate.list", |conn, cfg, op, q: &std::collections::HashMap<String,String>, ids: &[i64]| {
    let (w, p) = crate::handlers_certificate::cert_filters(q, ids);
    let (path, fname) = crate::excel::export_certificates(conn, cfg, op, &w, &p);
    (path, fname, w)
});
export_handler!(travel_export, "travel_details", "travel.list", |conn, cfg: &crate::config::Config, op, q: &std::collections::HashMap<String,String>, ids: &[i64]| {
    let today = helpers::now_local_ymd(cfg.tz_offset_hours);
    let (w, p) = crate::handlers_travel::travel_filters(conn, q, ids, &today);
    let (path, fname) = crate::excel::export_travel(conn, cfg, op, &w, &p);
    (path, fname, w)
});
export_handler!(decontrol_export, "decontrol_filing", "decontrol.list", |conn, cfg, op, q: &std::collections::HashMap<String,String>, ids: &[i64]| {
    let (w, p) = crate::handlers_decontrol::decontrol_filters(q, ids);
    let (path, fname) = crate::excel::export_decontrol(conn, cfg, op, &w, &p);
    (path, fname, w)
});

// ---- 在线打印 ----
fn print_spec(t: &str) -> Option<(&'static str, &'static str, &'static str)> {
    Some(match t {
        "info" => ("personnel_info", "备案人员信息登记表", "personnel.list"),
        "filing" => ("personnel_filing", "因私事出国（境）人员登记备案表", "personnel.list"),
        "certificate" => ("certificates", "因私出国（境）备案人员证照登记表", "certificate.list"),
        "travel" => ("travel_details", "因私出国（境）人员明细表", "travel.list"),
        "decontrol" => ("decontrol_filing", "因私事出国（境）人员撤控备案表", "decontrol.list"),
        _ => return None,
    })
}

pub async fn print_view(State(st): State<St>, headers: HeaderMap, uri: Uri, Path((print_type, id)): Path<(String, i64)>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let spec = match print_spec(&print_type) { Some(s) => s, None => { flash(&mut req, "不支持的打印类型。", "danger"); return redirect(&st, &req, "dashboard.index", &[]); } };
    let data = {
        let conn = st.db.lock().unwrap();
        let row = db::query_one(&conn, &format!("SELECT * FROM {} WHERE id = ?", spec.0), &[I(id)]);
        match row {
            None => { drop(conn); flash(&mut req, "记录不存在。", "danger"); return redirect(&st, &req, spec.2, &[]); }
            Some(row) => {
                let mut d = json!({"title": spec.1, "row": row, "mode": print_type});
                if print_type == "filing" {
                    if let Some(iid) = d["row"].get("personnel_info_id").and_then(|v| v.as_i64()) {
                        d["info"] = json!(db::query_one(&conn, "SELECT * FROM personnel_info WHERE id = ?", &[I(iid)]));
                    }
                }
                d
            }
        }
    };
    page(&st, &mut req, "export/print.html", data)
}

pub async fn batch_print(State(st): State<St>, headers: HeaderMap, uri: Uri, Path(print_type): Path<String>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let ids = selected_ids(&req.query);
    if ids.is_empty() { flash(&mut req, "请选择要打印的记录。", "warning"); return redirect(&st, &req, "dashboard.index", &[]); }
    let spec = match print_spec(&print_type) { Some(s) => s, None => { flash(&mut req, "不支持的打印类型。", "danger"); return redirect(&st, &req, "dashboard.index", &[]); } };
    let rows = {
        let conn = st.db.lock().unwrap();
        let ph = vec!["?"; ids.len()].join(",");
        let params: Vec<rusqlite::types::Value> = ids.iter().map(|i| I(*i)).collect();
        db::query_maps(&conn, &format!("SELECT * FROM {} WHERE id IN ({ph}) ORDER BY id", spec.0), &params)
    };
    let total = rows.len();
    page(&st, &mut req, "export/batch_print.html", json!({"title": spec.1, "rows": rows, "mode": print_type, "total": total}))
}

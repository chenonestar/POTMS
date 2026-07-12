// 首页仪表盘 + 手动备份（备份逻辑将于 backup 模块补全）
use crate::{db, flash, helpers, page, redirect, require_login, Req, St};
use axum::extract::State;
use axum::http::{HeaderMap, Uri};
use axum::response::Response;
use serde_json::json;

pub async fn backup_now(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) {
        return r;
    }
    let mut req = req;
    flash(&mut req, "备份功能移植中。", "info");
    redirect(&st, &req, "dashboard.index", &[])
}

pub async fn index(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) {
        return r;
    }
    let today = helpers::now_local_ymd(st.cfg.tz_offset_hours);
    let warn_date = {
        let d = time::OffsetDateTime::now_utc() + time::Duration::days(crate::config::CERT_WARN_DAYS);
        format!("{:04}{:02}{:02}", d.year(), d.month() as u8, d.day())
    };

    let data = {
        let conn = st.db.lock().unwrap();
        let c = |sql: &str| db::count(&conn, sql, &[]);
        let total_active = c("SELECT COUNT(*) FROM personnel_filing WHERE status = 'active'");
        let total_decontrolled = c("SELECT COUNT(*) FROM personnel_filing WHERE status = 'decontrolled'");
        let total_certificates = c("SELECT COUNT(*) FROM certificates");
        let total_travel = c("SELECT COUNT(*) FROM travel_details");

        let by_unit = db::query_maps(&conn, "SELECT work_unit AS label, COUNT(*) AS cnt FROM personnel_filing WHERE status = 'active' GROUP BY work_unit ORDER BY cnt DESC LIMIT 8", &[]);
        let by_political = db::query_maps(&conn, "SELECT political_status AS label, COUNT(*) AS cnt FROM personnel_filing WHERE status = 'active' GROUP BY political_status ORDER BY cnt DESC", &[]);
        let by_rank = db::query_maps(&conn, "SELECT pi.rank AS label, COUNT(*) AS cnt FROM personnel_filing pf JOIN personnel_info pi ON pf.personnel_info_id = pi.id WHERE pf.status = 'active' GROUP BY pi.rank ORDER BY cnt DESC", &[]);

        let cert_in_storage = c("SELECT COUNT(*) FROM travel_details WHERE passport_collect_date IS NULL OR passport_collect_date = ''");
        let in_use = db::query_maps(&conn, "SELECT id, name, passport_collect_date, passport_return_date, actual_return_date, travel_end, trip_status, cancel_date FROM travel_details WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' AND (passport_return_date IS NULL OR passport_return_date = '')", &[]);
        let cert_in_use = in_use.len() as i64;

        let mut overdue: Vec<serde_json::Value> = vec![];
        for row in &in_use {
            if helpers::is_cert_overdue(row, &today) {
                let mut ts = helpers::row_str(row, "trip_status");
                if ts.is_empty() { ts = "normal".into(); }
                overdue.push(json!({"name": helpers::row_str(row, "name"), "deadline": helpers::cert_overdue_deadline(row), "trip_status": ts}));
            }
        }
        overdue.sort_by(|a, b| helpers::row_str(a, "deadline").cmp(&helpers::row_str(b, "deadline")));

        let cert_rows = db::query_maps(&conn, "SELECT name, passport_expiry, hm_pass_expiry, tw_pass_expiry FROM certificates", &[]);
        let mut expiring: Vec<serde_json::Value> = vec![];
        for row in &cert_rows {
            for (field, label) in [("passport_expiry", "普通护照"), ("hm_pass_expiry", "往来港澳通行证"), ("tw_pass_expiry", "大陆居民往来台湾通行证")] {
                let expiry = helpers::row_str(row, field);
                if !expiry.is_empty() && today <= expiry && expiry <= warn_date {
                    expiring.push(json!({"name": helpers::row_str(row, "name"), "type": label, "expiry": expiry}));
                }
            }
        }

        let recent_travel = db::query_maps(&conn, "SELECT name, destination_passport, travel_dates, created_at FROM travel_details ORDER BY CASE WHEN travel_start IS NULL OR travel_start = '' THEN 1 ELSE 0 END, travel_start DESC, created_at DESC LIMIT 5", &[]);

        json!({
            "total_active": total_active, "total_decontrolled": total_decontrolled,
            "total_certificates": total_certificates, "total_travel": total_travel,
            "by_unit": by_unit, "by_political": by_political, "by_rank": by_rank,
            "cert_in_storage": cert_in_storage, "cert_in_use": cert_in_use, "cert_overdue": overdue.len(),
            "expiring": expiring, "overdue": overdue,
            "recent_travel": recent_travel, "backup_date": "",
        })
    };
    page(&st, &mut req, "dashboard.html", data)
}

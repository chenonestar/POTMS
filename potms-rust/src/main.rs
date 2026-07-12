// POTMS 纯 Rust 版 — axum + minijinja + rusqlite（单文件 exe，rust-embed 嵌入资源）
mod config;
mod db;
mod helpers;
mod render;
mod security;
mod session;
mod validators;
mod handlers_auth;
mod handlers_dashboard;
mod handlers_personnel;
mod handlers_certificate;
mod handlers_travel;
mod handlers_decontrol;
mod handlers_misc;
mod handlers_export;
mod handlers_import;
mod excel;
mod backup;

use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode, Uri},
    response::{IntoResponse, Response},
    routing::{get, post},
    Router,
};
use render::{Db, StaticAssets};
use std::sync::{Arc, Mutex};

pub struct AppState {
    pub db: Db,
    pub env: minijinja::Environment<'static>,
    pub cfg: config::Config,
    pub lockout: session::Lockout,
}

pub type St = Arc<AppState>;

// 请求上下文：会话 + 路径 + 查询串 + 客户端 IP
pub struct Req {
    pub sess: session::Session,
    pub path: String,
    pub query: String,
    pub ip: String,
}

impl Req {
    pub fn new(st: &AppState, headers: &HeaderMap, uri: &Uri) -> Req {
        Req {
            sess: session::Session::from_headers(headers, &st.cfg.secret_key),
            path: uri.path().to_string(),
            query: uri.query().unwrap_or("").to_string(),
            ip: client_ip(headers),
        }
    }
    pub fn base<'a>(&mut self) -> render::Ctx {
        render::base_context(&mut self.sess, &self.path.clone(), &self.query.clone())
    }
}

fn client_ip(headers: &HeaderMap) -> String {
    headers
        .get("x-forwarded-for")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.split(',').next())
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| "127.0.0.1".to_string())
}

// 便捷渲染
pub fn page(st: &AppState, req: &mut Req, name: &str, data: serde_json::Value) -> Response {
    let ctx = req.base();
    render::render(&st.env, ctx, &req.sess, &st.cfg, name, data)
}

pub fn redirect(st: &AppState, req: &Req, endpoint: &str, kwargs: &[(String, String)]) -> Response {
    render::redirect(&req.sess, &st.cfg, endpoint, kwargs)
}

pub fn flash(req: &mut Req, msg: &str, cat: &str) {
    req.sess.flash(msg, cat);
}

// 登录校验：未登录跳转登录页
pub fn require_login(st: &AppState, req: &Req) -> Option<Response> {
    if !req.sess.logged_in() {
        return Some(render::redirect(&req.sess, &st.cfg, "auth.login", &[]));
    }
    None
}

// CSRF 校验（POST）：失败则跳回登录/来源
pub fn csrf_check(req: &Req, form: &std::collections::HashMap<String, String>) -> bool {
    req.sess.csrf_ok(form.get("csrf_token").map(|s| s.as_str()).unwrap_or(""))
}

// 解析查询串为 map
pub fn query_args(query: &str) -> std::collections::HashMap<String, String> {
    let mut out = std::collections::HashMap::new();
    for pair in query.split('&').filter(|s| !s.is_empty()) {
        if let Some((k, v)) = pair.split_once('=') {
            let val = urlencoding::decode(v).map(|c| c.into_owned()).unwrap_or_else(|_| v.to_string());
            out.entry(k.to_string()).or_insert(val);
        }
    }
    out
}

// 表单字段（去空白）
pub fn ff(form: &std::collections::HashMap<String, String>, k: &str) -> String {
    form.get(k).map(|s| s.trim().to_string()).unwrap_or_default()
}

// 选项列表 [(code,value),...] → JSON
pub fn opt_list(pairs: &[(&str, &str)]) -> serde_json::Value {
    serde_json::Value::Array(
        pairs.iter().map(|(c, v)| serde_json::json!({"code": c, "value": v})).collect(),
    )
}

// RFC5987 文件名转义（附件/导出下载名）
pub fn url_escape(s: &str) -> String {
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

// selectedIDs：读取 ids 查询参数（逗号分隔）
pub fn selected_ids(query: &str) -> Vec<i64> {
    query_args(query)
        .get("ids")
        .map(|s| s.split(',').filter_map(|x| x.trim().parse::<i64>().ok()).collect())
        .unwrap_or_default()
}

// ---------------------------------------------------------------------------
// 静态资源（rust-embed）
// ---------------------------------------------------------------------------
async fn static_handler(Path(path): Path<String>) -> Response {
    match StaticAssets::get(&path) {
        Some(content) => {
            let mime = mime_of(&path);
            ([(axum::http::header::CONTENT_TYPE, mime)], content.data.into_owned()).into_response()
        }
        None => (StatusCode::NOT_FOUND, "not found").into_response(),
    }
}

fn mime_of(path: &str) -> &'static str {
    if path.ends_with(".css") {
        "text/css; charset=utf-8"
    } else if path.ends_with(".js") {
        "application/javascript; charset=utf-8"
    } else if path.ends_with(".woff2") {
        "font/woff2"
    } else if path.ends_with(".woff") {
        "font/woff"
    } else if path.ends_with(".png") {
        "image/png"
    } else if path.ends_with(".svg") {
        "image/svg+xml"
    } else {
        "application/octet-stream"
    }
}

async fn not_found(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    let ctx = req.base();
    render::render_status(
        &st.env, &mut { ctx }, &req.sess, &st.cfg, "errors/404.html",
        serde_json::json!({}), StatusCode::NOT_FOUND,
    )
}

#[tokio::main]
async fn main() {
    let cfg = config::Config::load();
    let conn = db::open(&cfg.database);
    db::init_schema(&conn);
    db::run_migrations(&conn);
    let first_run = db::seed_data(&conn);
    if first_run {
        println!("首次运行：已创建默认账户 admin / admin123（请尽快修改）");
    }
    let db: Db = Arc::new(Mutex::new(conn));
    let env = render::build_env(db.clone(), cfg.clone());

    let state: St = Arc::new(AppState {
        db,
        env,
        cfg: cfg.clone(),
        lockout: session::Lockout::default(),
    });

    let app = Router::new()
        .route("/login", get(handlers_auth::login_get).post(handlers_auth::login_post))
        .route("/logout", get(handlers_auth::logout))
        .route("/account", get(handlers_auth::account_get).post(handlers_auth::account_post))
        .route("/", get(handlers_dashboard::index))
        .route("/backup/now", post(handlers_dashboard::backup_now))
        // 人员备案
        .route("/personnel/", get(handlers_personnel::list))
        .route("/personnel/info/", get(handlers_personnel::info_list))
        .route("/personnel/info/new", get(handlers_personnel::info_new_get).post(handlers_personnel::info_new_post))
        .route("/personnel/info/:info_id/edit", get(handlers_personnel::info_edit_get).post(handlers_personnel::info_edit_post))
        .route("/personnel/info/:info_id/delete", post(handlers_personnel::info_delete))
        .route("/personnel/filing/new", get(handlers_personnel::filing_new_get).post(handlers_personnel::filing_new_post))
        .route("/personnel/filing/:filing_id/edit", get(handlers_personnel::filing_edit_get).post(handlers_personnel::filing_edit_post))
        .route("/personnel/:filing_id", get(handlers_personnel::view))
        .route("/personnel/:filing_id/delete", post(handlers_personnel::delete))
        // 证照
        .route("/certificate/", get(handlers_certificate::list))
        .route("/certificate/new", get(handlers_certificate::new_get).post(handlers_certificate::new_post))
        .route("/certificate/:cert_id/edit", get(handlers_certificate::edit_get).post(handlers_certificate::edit_post))
        .route("/certificate/:cert_id/delete", post(handlers_certificate::delete))
        // 出国明细 + 附件
        .route("/travel/", get(handlers_travel::list))
        .route("/travel/attachments", get(handlers_travel::attachments))
        .route("/travel/new", get(handlers_travel::new_get).post(handlers_travel::new_post))
        .route("/travel/:travel_id/edit", get(handlers_travel::edit_get).post(handlers_travel::edit_post))
        .route("/travel/:travel_id", get(handlers_travel::view))
        .route("/travel/:travel_id/delete", post(handlers_travel::delete))
        .route("/travel/:travel_id/cancel", post(handlers_travel::cancel))
        .route("/travel/:travel_id/restore", post(handlers_travel::restore))
        .route("/travel/attachment/:att_id/download", get(handlers_travel::att_download))
        .route("/travel/attachment/:att_id/preview", get(handlers_travel::att_preview))
        .route("/travel/attachment/:att_id/delete", post(handlers_travel::att_delete))
        // 撤控
        .route("/decontrol/", get(handlers_decontrol::list))
        .route("/decontrol/new/:filing_id", get(handlers_decontrol::new_get).post(handlers_decontrol::new_post))
        .route("/decontrol/:dec_id", get(handlers_decontrol::view))
        // 日志
        .route("/logs/", get(handlers_misc::logs_index))
        .route("/logs/export", get(handlers_misc::logs_export))
        // 组织架构
        .route("/org/", get(handlers_misc::org_index))
        .route("/org/add", post(handlers_misc::org_add))
        .route("/org/:org_id/edit", post(handlers_misc::org_edit))
        .route("/org/:org_id/delete", post(handlers_misc::org_delete))
        // 数据字典
        .route("/dict/", get(handlers_misc::dict_index))
        .route("/dict/add", post(handlers_misc::dict_add))
        .route("/dict/:dict_id/edit", post(handlers_misc::dict_edit))
        .route("/dict/:dict_id/delete", post(handlers_misc::dict_delete))
        // 报送单位
        .route("/submit-unit/", get(handlers_misc::su_index))
        .route("/submit-unit/add", post(handlers_misc::su_add))
        .route("/submit-unit/:uid/edit", post(handlers_misc::su_edit))
        .route("/submit-unit/:uid/delete", post(handlers_misc::su_delete))
        // 全局搜索
        .route("/search", get(handlers_misc::search))
        // 导出
        .route("/export/info", get(handlers_export::info_export))
        .route("/export/filing", get(handlers_export::filing_export))
        .route("/export/certificate", get(handlers_export::certificate_export))
        .route("/export/travel", get(handlers_export::travel_export))
        .route("/export/decontrol", get(handlers_export::decontrol_export))
        // 打印
        .route("/print/batch/:print_type", get(handlers_export::batch_print))
        .route("/print/:print_type/:id", get(handlers_export::print_view))
        // 导入
        .route("/import/", get(handlers_import::index_get).post(handlers_import::index_post))
        .route("/import/template", get(handlers_import::download_template))
        .route("/static/*path", get(static_handler))
        .layer(axum::extract::DefaultBodyLimit::max(config::MAX_CONTENT_LENGTH))
        .fallback(not_found)
        .with_state(state);

    let addr = "127.0.0.1:5000";
    println!("POTMS (Rust) 启动：http://{addr}");
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}


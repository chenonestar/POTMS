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

// 未移植路由的临时占位（逐步替换为真实处理器）
async fn todo_page(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &req) {
        return r;
    }
    flash(&mut req, "该功能正在移植中……", "info");
    page(&st, &mut req, "errors/500.html", serde_json::json!({"message": "开发中"}))
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
        // 以下为占位路由（逐步替换）
        .route("/personnel/", get(todo_page))
        .route("/certificate/", get(todo_page))
        .route("/travel/", get(todo_page))
        .route("/decontrol/", get(todo_page))
        .route("/logs/", get(todo_page))
        .route("/org/", get(todo_page))
        .route("/dict/", get(todo_page))
        .route("/submit-unit/", get(todo_page))
        .route("/import/", get(todo_page))
        .route("/search", get(todo_page))
        .route("/static/*path", get(static_handler))
        .fallback(not_found)
        .with_state(state);

    let addr = "127.0.0.1:5000";
    println!("POTMS (Rust) 启动：http://{addr}");
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}


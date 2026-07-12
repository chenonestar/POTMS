// 渲染层 — minijinja(Jinja2 兼容) + Flask 风格全局函数
use crate::config::Config;
use crate::helpers;
use axum::response::{Html, IntoResponse, Response};
use minijinja::value::{Kwargs, Rest};
use minijinja::{Environment, State, Value};
use rusqlite::Connection;
use serde_json::json;
use std::sync::{Arc, Mutex};

pub type Db = Arc<Mutex<Connection>>;

#[derive(rust_embed::RustEmbed)]
#[folder = "templates/"]
pub struct Templates;

#[derive(rust_embed::RustEmbed)]
#[folder = "static/"]
pub struct StaticAssets;

// Flask endpoint → 路径模板（{param} 占位；多余 kwargs 变查询串）
pub fn endpoint_path(endpoint: &str) -> Option<&'static str> {
    Some(match endpoint {
        "auth.login" => "/login", "auth.logout" => "/logout", "auth.account" => "/account",
        "dashboard.index" => "/", "dashboard.backup_now" => "/backup/now",
        "personnel.list" => "/personnel/", "personnel.info_new" => "/personnel/info/new",
        "personnel.info_list" => "/personnel/info/",
        "personnel.info_delete" => "/personnel/info/{info_id}/delete",
        "personnel.info_edit" => "/personnel/info/{info_id}/edit",
        "personnel.filing_new" => "/personnel/filing/new",
        "personnel.filing_edit" => "/personnel/filing/{filing_id}/edit",
        "personnel.view" => "/personnel/{filing_id}",
        "personnel.delete" => "/personnel/{filing_id}/delete",
        "certificate.list" => "/certificate/", "certificate.new" => "/certificate/new",
        "certificate.edit" => "/certificate/{cert_id}/edit",
        "certificate.delete" => "/certificate/{cert_id}/delete",
        "travel.list" => "/travel/", "travel.attachments" => "/travel/attachments",
        "travel.new" => "/travel/new", "travel.edit" => "/travel/{travel_id}/edit",
        "travel.view" => "/travel/{travel_id}", "travel.delete" => "/travel/{travel_id}/delete",
        "travel.cancel" => "/travel/{travel_id}/cancel", "travel.restore" => "/travel/{travel_id}/restore",
        "travel.attachment_download" => "/travel/attachment/{att_id}/download",
        "travel.attachment_preview" => "/travel/attachment/{att_id}/preview",
        "travel.attachment_delete" => "/travel/attachment/{att_id}/delete",
        "decontrol.list" => "/decontrol/", "decontrol.new" => "/decontrol/new/{filing_id}",
        "decontrol.view" => "/decontrol/{dec_id}",
        "export.info_export" => "/export/info", "export.filing_export" => "/export/filing",
        "export.certificate_export" => "/export/certificate", "export.travel_export" => "/export/travel",
        "export.decontrol_export" => "/export/decontrol",
        "export.print_view" => "/print/{print_type}/{id}", "export.batch_print" => "/print/batch/{print_type}",
        "import_data.index" => "/import/", "import_data.download_template" => "/import/template",
        "logs.index" => "/logs/", "logs.export" => "/logs/export",
        "organization.index" => "/org/", "organization.add" => "/org/add",
        "organization.edit" => "/org/{org_id}/edit", "organization.delete" => "/org/{org_id}/delete",
        "dict_admin.index" => "/dict/", "dict_admin.add" => "/dict/add",
        "dict_admin.edit" => "/dict/{dict_id}/edit", "dict_admin.delete" => "/dict/{dict_id}/delete",
        "submit_unit.index" => "/submit-unit/", "submit_unit.add" => "/submit-unit/add",
        "submit_unit.edit" => "/submit-unit/{uid}/edit", "submit_unit.delete" => "/submit-unit/{uid}/delete",
        "search.index" => "/search",
        _ => return None,
    })
}

pub fn url_for(endpoint: &str, kwargs: &[(String, String)]) -> String {
    if endpoint == "static" {
        let filename = kwargs.iter().find(|(k, _)| k == "filename").map(|(_, v)| v.clone()).unwrap_or_default();
        return format!("/static/{filename}");
    }
    let mut path = match endpoint_path(endpoint) {
        Some(p) => p.to_string(),
        None => return "#".into(),
    };
    let mut query: Vec<String> = vec![];
    for (k, v) in kwargs {
        let ph = format!("{{{k}}}");
        if path.contains(&ph) {
            path = path.replace(&ph, v);
        } else {
            query.push(format!("{}={}", urlencoding::encode(k), urlencoding::encode(v)));
        }
    }
    if !query.is_empty() {
        path.push('?');
        path.push_str(&query.join("&"));
    }
    path
}

pub fn build_env(db: Db, cfg: Config) -> Environment<'static> {
    let mut env = Environment::new();
    env.set_auto_escape_callback(|name| {
        if name.ends_with(".html") {
            minijinja::AutoEscape::Html
        } else {
            minijinja::AutoEscape::None
        }
    });
    for name in Templates::iter() {
        let file = Templates::get(&name).unwrap();
        let body = String::from_utf8_lossy(&file.data).into_owned();
        env.add_template_owned(name.to_string(), body).expect("模板解析失败");
    }

    // localtime 过滤器
    let off = cfg.tz_offset_hours;
    env.add_filter("localtime", move |v: Value, args: Rest<Value>| -> Value {
        let s = v.as_str().map(|x| x.to_string()).unwrap_or_else(|| v.to_string());
        let fmt = args.first().and_then(|x| x.as_str()).unwrap_or("%Y-%m-%d %H:%M:%S");
        Value::from(helpers::to_local_time(&s, fmt, off))
    });

    // url_for
    env.add_function("url_for", |endpoint: &str, kwargs: Kwargs| -> Result<Value, minijinja::Error> {
        let mut pairs = vec![];
        for k in kwargs.args() {
            let val: Value = kwargs.get(k)?;
            let sv = val.as_str().map(|x| x.to_string()).unwrap_or_else(|| val.to_string());
            pairs.push((k.to_string(), sv));
        }
        Ok(Value::from(url_for(endpoint, &pairs)))
    });

    // csrf_token()：读取 State 中的 _csrf
    env.add_function("csrf_token", |state: &State| -> Value {
        state.lookup("_csrf").unwrap_or_else(|| Value::from(""))
    });

    // get_flashed_messages()：读取 State 中的 _flashes
    env.add_function("get_flashed_messages", |state: &State, _kwargs: Kwargs| -> Value {
        state.lookup("_flashes").unwrap_or_else(|| Value::from(Vec::<Value>::new()))
    });

    // page_url(endpoint, page)：保留当前查询串、替换 page
    env.add_function("page_url", |state: &State, endpoint: &str, page: i64| -> Value {
        let q = state.lookup("_query").and_then(|v| v.as_str().map(|s| s.to_string())).unwrap_or_default();
        let mut params: Vec<(String, String)> = vec![];
        for pair in q.split('&').filter(|s| !s.is_empty()) {
            if let Some((k, v)) = pair.split_once('=') {
                if k != "page" {
                    params.push((k.to_string(), v.to_string()));
                }
            }
        }
        let base = url_for(endpoint, &[]);
        let mut qs = params.iter().map(|(k, v)| format!("{k}={v}")).collect::<Vec<_>>();
        qs.push(format!("page={page}"));
        Value::from(format!("{base}?{}", qs.join("&")))
    });

    // DB 数据源全局（捕获 db）
    let d = db.clone();
    env.add_function("dict_opts", move |cat: &str| -> Value {
        let conn = d.lock().unwrap();
        to_val(helpers::get_dict_options(&conn, cat))
    });
    let d = db.clone();
    env.add_function("dict_value", move |cat: &str, code: &str| -> Value {
        let conn = d.lock().unwrap();
        Value::from(helpers::get_dict_value(&conn, cat, code))
    });
    let d = db.clone();
    env.add_function("org_flat", move || -> Value {
        let conn = d.lock().unwrap();
        to_val(helpers::get_org_flat(&conn))
    });
    let d = db.clone();
    env.add_function("org_tree_opts", move || -> Value {
        let conn = d.lock().unwrap();
        to_val(helpers::get_org_tree_options(&conn))
    });
    let d = db.clone();
    env.add_function("org_children", move |pid: i64| -> Value {
        let conn = d.lock().unwrap();
        to_val(crate::db::query_maps(&conn, "SELECT id, name FROM sys_org WHERE parent_id = ? ORDER BY sort_order", &[rusqlite::types::Value::Integer(pid)]))
    });
    let d = db.clone();
    env.add_function("personnel_opts", move || -> Value {
        let conn = d.lock().unwrap();
        to_val(helpers::get_personnel_options(&conn))
    });
    let d = db.clone();
    env.add_function("submit_units", move || -> Value {
        let conn = d.lock().unwrap();
        to_val(helpers::get_submit_units(&conn))
    });

    env
}

fn to_val(rows: Vec<serde_json::Value>) -> Value {
    Value::from_serialize(&rows)
}

// 每请求基础上下文（session/request/flashes/csrf/query），与 handler 数据合并
pub struct Ctx {
    pub base: serde_json::Map<String, serde_json::Value>,
}

pub fn base_context(sess: &mut crate::session::Session, path: &str, query: &str) -> Ctx {
    let mut args = serde_json::Map::new();
    for pair in query.split('&').filter(|s| !s.is_empty()) {
        if let Some((k, v)) = pair.split_once('=') {
            args.insert(k.to_string(), json!(urlencoding::decode(v).unwrap_or_default().into_owned()));
        }
    }
    let csrf = sess.csrf_token();
    let flashes: Vec<serde_json::Value> = sess
        .pop_flashes()
        .into_iter()
        .map(|(c, m)| json!([c, m]))
        .collect();
    let nav_q = if path == "/search" {
        args.get("q").and_then(|v| v.as_str()).unwrap_or("").to_string()
    } else {
        String::new()
    };
    let mut base = serde_json::Map::new();
    base.insert("session".into(), json!({"logged_in": sess.logged_in(), "username": sess.username()}));
    base.insert("request".into(), json!({"args": args, "path": path, "endpoint": ""}));
    base.insert("_csrf".into(), json!(csrf));
    base.insert("_flashes".into(), json!(flashes));
    base.insert("_query".into(), json!(query));
    base.insert("nav_q".into(), json!(nav_q));
    Ctx { base }
}

pub fn render(env: &Environment, mut ctx: Ctx, sess: &crate::session::Session, cfg: &Config, name: &str, data: serde_json::Value) -> Response {
    render_status(env, &mut ctx, sess, cfg, name, data, axum::http::StatusCode::OK)
}

pub fn render_status(env: &Environment, ctx: &mut Ctx, sess: &crate::session::Session, cfg: &Config, name: &str, data: serde_json::Value, status: axum::http::StatusCode) -> Response {
    if let serde_json::Value::Object(m) = data {
        for (k, v) in m {
            ctx.base.insert(k, v);
        }
    }
    let tmpl = match env.get_template(name) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("模板不存在 {name}: {e}");
            return (axum::http::StatusCode::INTERNAL_SERVER_ERROR, "模板不存在").into_response();
        }
    };
    let out = match tmpl.render(serde_json::Value::Object(ctx.base.clone())) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("模板渲染失败 {name}: {e:#}");
            return (axum::http::StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response();
        }
    };
    let mut resp = (status, Html(out)).into_response();
    attach_session(&mut resp, sess, cfg);
    resp
}

pub fn attach_session(resp: &mut Response, sess: &crate::session::Session, cfg: &Config) {
    if sess.dirty {
        if let Ok(hv) = axum::http::HeaderValue::from_str(&sess.to_cookie(&cfg.secret_key)) {
            resp.headers_mut().append(axum::http::header::SET_COOKIE, hv);
        }
    }
}

pub fn redirect(sess: &crate::session::Session, cfg: &Config, endpoint: &str, kwargs: &[(String, String)]) -> Response {
    let loc = url_for(endpoint, kwargs);
    let mut resp = axum::response::Redirect::to(&loc).into_response();
    attach_session(&mut resp, sess, cfg);
    resp
}

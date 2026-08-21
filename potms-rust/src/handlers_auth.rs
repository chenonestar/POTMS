// 认证：登录（防爆破）/ 登出 / 账户设置
use crate::config::{LOCK_SECS, LOCK_THRESHOLD};
use crate::{db, flash, helpers, page, redirect, require_login, security, Req, St};
use axum::extract::State;
use axum::http::{HeaderMap, Uri};
use axum::response::Response;
use axum::Form;
use rusqlite::types::Value as SqlValue;
use std::collections::HashMap;

pub async fn login_get(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    page(&st, &mut req, "login.html", serde_json::json!({}))
}

pub async fn login_post(
    State(st): State<St>,
    headers: HeaderMap,
    uri: Uri,
    Form(form): Form<HashMap<String, String>>,
) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    // CSRF
    if !req.sess.csrf_ok(form.get("csrf_token").map(|s| s.as_str()).unwrap_or("")) {
        flash(&mut req, "表单已过期，请重试。", "danger");
        return page(&st, &mut req, "login.html", serde_json::json!({}));
    }
    let username = form.get("username").map(|s| s.trim().to_string()).unwrap_or_default();
    let password = form.get("password").cloned().unwrap_or_default();
    let ip = req.ip.clone();

    let remain = st.lockout.remaining(&ip);
    if remain > 0 {
        let mins = remain / 60 + 1;
        flash(&mut req, &format!("登录失败次数过多，已临时锁定，请 {mins} 分钟后再试。"), "danger");
        return page(&st, &mut req, "login.html", serde_json::json!({}));
    }
    if username.is_empty() || password.is_empty() {
        flash(&mut req, "请输入用户名和密码。", "danger");
        return page(&st, &mut req, "login.html", serde_json::json!({}));
    }

    let (ok, needs_rehash, uid, full_name) = {
        let conn = st.db.lock().unwrap();
        match db::query_one(&conn, "SELECT * FROM users WHERE username = ?", &[SqlValue::Text(username.clone())]) {
            Some(u) => {
                let (ok, rehash) = security::verify_password(&password, &helpers::row_str(&u, "password_hash"));
                (ok, rehash, helpers::row_i64(&u, "id"), helpers::row_str(&u, "full_name"))
            }
            None => (false, false, 0, String::new()),
        }
    };

    if ok {
        st.lockout.reset(&ip);
        if needs_rehash {
            let h = security::hash_password(&password);
            let conn = st.db.lock().unwrap();
            let _ = db::exec(&conn, "UPDATE users SET password_hash = ? WHERE id = ?", &[SqlValue::Text(h), SqlValue::Integer(uid)]);
        }
        req.sess.login(&username, &full_name);
        flash(&mut req, "登录成功。", "success");
        return redirect(&st, &req, "dashboard.index", &[]);
    }

    st.lockout.record_failure(&ip);
    {
        let conn = st.db.lock().unwrap();
        helpers::log_action(&conn, &username, &ip, "login_fail", "auth", None, "登录失败", None, None);
        if st.lockout.just_locked(&ip) {
            helpers::log_action(&conn, &username, &ip, "lock", "auth", None, &format!("账户锁定 {} 分钟", LOCK_SECS / 60), None, None);
        }
    }
    let fails_left = LOCK_THRESHOLD as i64 - failure_count(&st, &ip);
    if fails_left > 0 {
        flash(&mut req, &format!("用户名或密码错误（再失败 {fails_left} 次将锁定 {} 分钟）。", LOCK_SECS / 60), "danger");
    } else {
        flash(&mut req, &format!("登录失败次数过多，已锁定 {} 分钟。", LOCK_SECS / 60), "danger");
    }
    page(&st, &mut req, "login.html", serde_json::json!({}))
}

// 借助 remaining 推断失败次数不便，这里用锁定状态近似（just_locked 已覆盖阈值提示）
fn failure_count(st: &St, ip: &str) -> i64 {
    if st.lockout.remaining(ip) > 0 {
        LOCK_THRESHOLD as i64
    } else {
        0
    }
}

pub async fn logout(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    req.sess.logout();
    flash(&mut req, "已退出登录。", "info");
    redirect(&st, &req, "auth.login", &[])
}

pub async fn account_get(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) {
        return r;
    }
    let ctx = {
        let conn = st.db.lock().unwrap();
        account_view(&conn, &req.sess.username())
    };
    page(&st, &mut req, "account.html", ctx)
}

/// 账户设置页的上下文：账号 + 姓名 + 还有多少条历史记录把账号当经办人。
fn account_view(conn: &rusqlite::Connection, username: &str) -> serde_json::Value {
    let full_name = db::query_one(conn, "SELECT full_name FROM users WHERE username = ?",
                                  &[SqlValue::Text(username.to_string())])
        .map(|u| helpers::row_str(&u, "full_name"))
        .unwrap_or_default();
    serde_json::json!({
        "username": username,
        "full_name": full_name,
        "legacy": {"username": username, "total": legacy_operator_count(conn, username)},
    })
}

pub async fn account_post(
    State(st): State<St>,
    headers: HeaderMap,
    uri: Uri,
    Form(form): Form<HashMap<String, String>>,
) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) {
        return r;
    }
    if !req.sess.csrf_ok(form.get("csrf_token").map(|s| s.as_str()).unwrap_or("")) {
        flash(&mut req, "表单已过期，请重试。", "danger");
        return redirect(&st, &req, "auth.account", &[]);
    }
    let g = |k: &str| form.get(k).cloned().unwrap_or_default();
    let current_pw = g("current_password");
    let new_username = g("new_username").trim().to_string();
    let new_full_name = g("new_full_name").trim().to_string();
    let new_pw = g("new_password");
    let confirm_pw = g("confirm_password");

    let (uid, cur_username, cur_full_name, stored) = {
        let conn = st.db.lock().unwrap();
        match db::query_one(&conn, "SELECT * FROM users WHERE username = ?", &[SqlValue::Text(req.sess.username())]) {
            Some(u) => (helpers::row_i64(&u, "id"), helpers::row_str(&u, "username"),
                        helpers::row_str(&u, "full_name"), helpers::row_str(&u, "password_hash")),
            None => {
                req.sess.logout();
                return redirect(&st, &req, "auth.login", &[]);
            }
        }
    };

    let mut errs: Vec<String> = vec![];
    if !security::verify_password(&current_pw, &stored).0 {
        errs.push("当前密码不正确。".into());
    }
    let change_username = !new_username.is_empty() && new_username != cur_username;
    let change_password = !new_pw.is_empty();
    let change_full_name = new_full_name != cur_full_name;
    if !change_username && !change_password && !change_full_name {
        errs.push("未检测到任何修改。".into());
    }
    if new_full_name.chars().count() > 30 {
        errs.push("姓名过长（最多 30 个字符）。".into());
    }
    if new_username.is_empty() {
        errs.push("用户名不能为空。".into());
    } else if change_username {
        if new_username.chars().count() < 3 {
            errs.push("用户名至少 3 个字符。".into());
        } else {
            let conn = st.db.lock().unwrap();
            if db::query_one(&conn, "SELECT id FROM users WHERE username = ? AND id != ?", &[SqlValue::Text(new_username.clone()), SqlValue::Integer(uid)]).is_some() {
                errs.push("该用户名已被占用。".into());
            }
        }
    }
    if change_password {
        if new_pw.chars().count() < 6 {
            errs.push("新密码至少 6 个字符。".into());
        } else if new_pw != confirm_pw {
            errs.push("两次输入的新密码不一致。".into());
        }
    }
    if !errs.is_empty() {
        for e in &errs {
            flash(&mut req, e, "danger");
        }
        let ctx = { let conn = st.db.lock().unwrap(); account_view(&conn, &cur_username) };
        return page(&st, &mut req, "account.html", ctx);
    }
    {
        let conn = st.db.lock().unwrap();
        if change_username {
            let _ = db::exec(&conn, "UPDATE users SET username = ? WHERE id = ?", &[SqlValue::Text(new_username.clone()), SqlValue::Integer(uid)]);
        }
        if change_password {
            let h = security::hash_password(&new_pw);
            let _ = db::exec(&conn, "UPDATE users SET password_hash = ? WHERE id = ?", &[SqlValue::Text(h), SqlValue::Integer(uid)]);
        }
        if change_full_name {
            let v = if new_full_name.is_empty() { SqlValue::Null } else { SqlValue::Text(new_full_name.clone()) };
            let _ = db::exec(&conn, "UPDATE users SET full_name = ? WHERE id = ?", &[v, SqlValue::Integer(uid)]);
        }
        let mut parts = vec![];
        if change_username { parts.push(format!("用户名→{new_username}")); }
        if change_full_name {
            let shown = if new_full_name.is_empty() { "（清空）" } else { &new_full_name };
            parts.push(format!("姓名→{shown}"));
        }
        if change_password { parts.push("密码".to_string()); }
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "update", "users", Some(uid), &format!("账户变更：{}", parts.join("、")), None, None);
    }
    if change_password {
        req.sess.logout();
        flash(&mut req, "密码已修改，请使用新密码重新登录。", "success");
        return redirect(&st, &req, "auth.login", &[]);
    }
    req.sess.set_identity(&new_username, &new_full_name);
    flash(&mut req, "账户信息已更新。", "success");
    redirect(&st, &req, "auth.account", &[])
}

// ---------------------------------------------------------------------------
// 历史经办人回填
//
// 升级那一刻系统还不知道真实姓名——得先去账户设置填。所以「加列」和「改历史
// 数据」不能是同一步，回填只能等姓名填好之后由用户显式触发。
//
// 刻意做成按钮而不是升级时静默 UPDATE：批量改历史数据不可逆，得让人看清影响
// 条数再点。执行前自动备一次库，整件事也记进操作日志。
// ---------------------------------------------------------------------------

/// 业务表的经办人字段。operation_logs 不在其列——那是审计痕迹，记的是账号。
const OPERATOR_COLUMNS: &[(&str, &str)] = &[
    ("personnel_info", "operator"),
    ("personnel_filing", "operator"),
    ("certificates", "operator"),
    ("travel_details", "operator"),
    ("decontrol_filing", "operator"),
];

/// 统计业务表里还有多少条记录把登录账号当经办人。
fn legacy_operator_count(conn: &rusqlite::Connection, username: &str) -> i64 {
    let mut total = 0i64;
    for (table, col) in OPERATOR_COLUMNS {
        // 老库可能缺表，查不到就跳过
        if let Ok(n) = conn.query_row(
            &format!("SELECT COUNT(*) FROM {table} WHERE {col} = ?"),
            [username], |r| r.get::<_, i64>(0)) {
            total += n;
        }
    }
    total
}

pub async fn backfill_operator(State(st): State<St>, headers: HeaderMap, uri: Uri,
                               Form(form): Form<HashMap<String, String>>) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) {
        return r;
    }
    if !req.sess.csrf_ok(form.get("csrf_token").map(|s| s.as_str()).unwrap_or("")) {
        flash(&mut req, "表单已过期，请重试。", "danger");
        return redirect(&st, &req, "auth.account", &[]);
    }

    let (uid, username, full_name) = {
        let conn = st.db.lock().unwrap();
        match db::query_one(&conn, "SELECT * FROM users WHERE username = ?",
                            &[SqlValue::Text(req.sess.username())]) {
            Some(u) => (helpers::row_i64(&u, "id"), helpers::row_str(&u, "username"),
                        helpers::row_str(&u, "full_name").trim().to_string()),
            None => {
                req.sess.logout();
                return redirect(&st, &req, "auth.login", &[]);
            }
        }
    };
    if full_name.is_empty() {
        flash(&mut req, "请先填写并保存姓名，再回填历史记录。", "warning");
        return redirect(&st, &req, "auth.account", &[]);
    }
    if full_name == username {
        flash(&mut req, "姓名与登录账号相同，无需回填。", "info");
        return redirect(&st, &req, "auth.account", &[]);
    }

    // 不可逆的批量写入，先留一份退路。force：当天已备过也要再备，因为马上要改数据。
    // run_daily_backup 吞掉了 VACUUM INTO 的错误，所以按产物判断成败。
    {
        let conn = st.db.lock().unwrap();
        let (ymd, _) = crate::backup::run_daily_backup(&conn, &st.cfg, true);
        if !st.cfg.backup_folder.join(format!("data_{ymd}.db")).exists() {
            drop(conn);
            flash(&mut req, "自动备份失败，已中止回填。请手动备份 data.db 后重试。", "danger");
            return redirect(&st, &req, "auth.account", &[]);
        }
    }

    let changed = {
        let conn = st.db.lock().unwrap();
        let mut changed = 0i64;
        for (table, col) in OPERATOR_COLUMNS {
            if let Ok(n) = conn.execute(
                &format!("UPDATE {table} SET {col} = ? WHERE {col} = ?"),
                [&full_name, &username]) {
                changed += n as i64;
            }
        }
        helpers::log_action(&conn, &req.sess.username(), &req.ip, "update", "users", Some(uid),
                            &format!("历史经办人回填：{username} → {full_name}，共 {changed} 条"),
                            None, None);
        changed
    };
    flash(&mut req, &format!(
        "已把 {changed} 条历史记录的经办人由「{username}」更新为「{full_name}」。\
         操作日志保持原样（审计需要登录账号）。"), "success");
    redirect(&st, &req, "auth.account", &[])
}

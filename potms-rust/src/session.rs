// 会话（HMAC 签名 Cookie）+ flash + CSRF + 超时 + 登录锁定
use crate::config::{Config, LOCK_SECS, LOCK_THRESHOLD, SESSION_TIMEOUT_SECS};
use axum::http::HeaderMap;
use base64::{engine::general_purpose::URL_SAFE_NO_PAD as B64, Engine};
use hmac::{Hmac, Mac};
use serde_json::{json, Map, Value};
use sha2::Sha256;
use std::collections::HashMap;
use std::sync::Mutex;

const COOKIE_NAME: &str = "potms_session";

#[derive(Default)]
pub struct Session {
    pub map: Map<String, Value>,
    pub dirty: bool,
}

impl Session {
    pub fn from_headers(headers: &HeaderMap, secret: &[u8]) -> Session {
        let mut s = Session::default();
        if let Some(raw) = cookie_value(headers, COOKIE_NAME) {
            if let Some(map) = verify_and_decode(&raw, secret) {
                s.map = map;
            }
        }
        // 超时校验：logged_in 且 ts 过期 → 视为登出
        if s.logged_in() {
            let now = crate::helpers::now_unix();
            let ts = s.map.get("ts").and_then(|v| v.as_i64()).unwrap_or(0);
            if now - ts > SESSION_TIMEOUT_SECS {
                s.map.clear();
                s.dirty = true;
            } else {
                s.map.insert("ts".into(), json!(now)); // 滑动续期
                s.dirty = true;
            }
        }
        s
    }

    pub fn logged_in(&self) -> bool {
        self.map.get("logged_in").and_then(|v| v.as_bool()).unwrap_or(false)
    }
    pub fn username(&self) -> String {
        self.map.get("username").and_then(|v| v.as_str()).unwrap_or("").to_string()
    }
    pub fn login(&mut self, username: &str) {
        self.map.insert("logged_in".into(), json!(true));
        self.map.insert("username".into(), json!(username));
        self.map.insert("ts".into(), json!(crate::helpers::now_unix()));
        self.dirty = true;
    }
    pub fn logout(&mut self) {
        self.map.clear();
        self.dirty = true;
    }

    // CSRF：确保存在令牌
    pub fn csrf_token(&mut self) -> String {
        if let Some(t) = self.map.get("csrf").and_then(|v| v.as_str()) {
            return t.to_string();
        }
        let t = crate::helpers::random_token();
        self.map.insert("csrf".into(), json!(t));
        self.dirty = true;
        t
    }
    pub fn csrf_ok(&self, token: &str) -> bool {
        match self.map.get("csrf").and_then(|v| v.as_str()) {
            Some(t) => !token.is_empty() && crate::security::constant_time_eq(t.as_bytes(), token.as_bytes()),
            None => false,
        }
    }

    // flash：追加消息
    pub fn flash(&mut self, msg: &str, category: &str) {
        let arr = self.map.entry("_flashes").or_insert_with(|| json!([]));
        if let Value::Array(a) = arr {
            a.push(json!([category, msg]));
        }
        self.dirty = true;
    }
    // 取出并清空 flash（供渲染）
    pub fn pop_flashes(&mut self) -> Vec<(String, String)> {
        let mut out = vec![];
        if let Some(Value::Array(a)) = self.map.remove("_flashes") {
            for item in a {
                if let Value::Array(pair) = item {
                    let cat = pair.get(0).and_then(|v| v.as_str()).unwrap_or("info").to_string();
                    let msg = pair.get(1).and_then(|v| v.as_str()).unwrap_or("").to_string();
                    out.push((cat, msg));
                }
            }
            self.dirty = true;
        }
        out
    }

    pub fn to_cookie(&self, secret: &[u8]) -> String {
        let body = serde_json::to_vec(&Value::Object(self.map.clone())).unwrap_or_default();
        let payload = B64.encode(&body);
        let sig = sign(payload.as_bytes(), secret);
        let value = format!("{payload}.{sig}");
        format!(
            "{COOKIE_NAME}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={}",
            SESSION_TIMEOUT_SECS
        )
    }
}

fn sign(data: &[u8], secret: &[u8]) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(secret).unwrap();
    mac.update(data);
    B64.encode(mac.finalize().into_bytes())
}

fn verify_and_decode(raw: &str, secret: &[u8]) -> Option<Map<String, Value>> {
    let (payload, sig) = raw.rsplit_once('.')?;
    let expect = sign(payload.as_bytes(), secret);
    if !crate::security::constant_time_eq(expect.as_bytes(), sig.as_bytes()) {
        return None;
    }
    let body = B64.decode(payload).ok()?;
    match serde_json::from_slice::<Value>(&body).ok()? {
        Value::Object(m) => Some(m),
        _ => None,
    }
}

pub fn cookie_value(headers: &HeaderMap, name: &str) -> Option<String> {
    let raw = headers.get(axum::http::header::COOKIE)?.to_str().ok()?;
    for part in raw.split(';') {
        let part = part.trim();
        if let Some(v) = part.strip_prefix(&format!("{name}=")) {
            return Some(v.to_string());
        }
    }
    None
}

// ---------------------------------------------------------------------------
// 登录防爆破：每 IP 失败计数（进程内）
// ---------------------------------------------------------------------------
#[derive(Default)]
pub struct Lockout {
    inner: Mutex<HashMap<String, (u32, i64)>>, // ip -> (fails, lock_until)
}

impl Lockout {
    pub fn remaining(&self, ip: &str) -> i64 {
        let m = self.inner.lock().unwrap();
        if let Some((_, until)) = m.get(ip) {
            let now = crate::helpers::now_unix();
            if *until > now {
                return until - now;
            }
        }
        0
    }
    pub fn record_failure(&self, ip: &str) {
        let mut m = self.inner.lock().unwrap();
        let now = crate::helpers::now_unix();
        let e = m.entry(ip.to_string()).or_insert((0, 0));
        e.0 += 1;
        if e.0 >= LOCK_THRESHOLD {
            e.1 = now + LOCK_SECS;
        }
    }
    pub fn reset(&self, ip: &str) {
        self.inner.lock().unwrap().remove(ip);
    }
    // 达到阈值那次是否刚触发锁定
    pub fn just_locked(&self, ip: &str) -> bool {
        let m = self.inner.lock().unwrap();
        m.get(ip).map(|(f, _)| *f == LOCK_THRESHOLD).unwrap_or(false)
    }
}

pub fn _touch(_: &Config) {}

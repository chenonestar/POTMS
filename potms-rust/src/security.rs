// 密码哈希 — bcrypt（兼容旧 werkzeug pbkdf2 哈希，登录透明升级）
use pbkdf2::pbkdf2_hmac;
use sha2::Sha256;

pub fn hash_password(password: &str) -> String {
    bcrypt::hash(password, bcrypt::DEFAULT_COST).expect("bcrypt 失败")
}

/// 返回 (是否匹配, 是否需升级为 bcrypt)
pub fn verify_password(password: &str, stored: &str) -> (bool, bool) {
    if stored.is_empty() {
        return (false, false);
    }
    if stored.starts_with("$2") {
        return (bcrypt::verify(password, stored).unwrap_or(false), false);
    }
    if stored.starts_with("pbkdf2:sha256") {
        let ok = verify_werkzeug_pbkdf2(password, stored);
        return (ok, ok);
    }
    (false, false)
}

// werkzeug 格式: pbkdf2:sha256:iterations$salt$hexhash
fn verify_werkzeug_pbkdf2(password: &str, stored: &str) -> bool {
    let parts: Vec<&str> = stored.splitn(3, '$').collect();
    if parts.len() != 3 {
        return false;
    }
    let (method, salt, hex_hash) = (parts[0], parts[1], parts[2]);
    let mut iterations: u32 = 260000;
    let mp: Vec<&str> = method.splitn(3, ':').collect();
    if mp.len() == 3 {
        if let Ok(n) = mp[2].parse::<u32>() {
            iterations = n;
        }
    }
    let mut derived = [0u8; 32];
    pbkdf2_hmac::<Sha256>(password.as_bytes(), salt.as_bytes(), iterations, &mut derived);
    let derived_hex = hex_lower(&derived);
    constant_time_eq(derived_hex.as_bytes(), hex_hash.as_bytes())
}

fn hex_lower(b: &[u8]) -> String {
    b.iter().map(|x| format!("{:02x}", x)).collect()
}

pub fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for i in 0..a.len() {
        diff |= a[i] ^ b[i];
    }
    diff == 0
}

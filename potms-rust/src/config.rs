// 应用配置 — 对应 Go 版 config.go / Python 版 config.py
use std::path::{Path, PathBuf};

pub const PAGE_SIZE: usize = 12; // 数据列表每页（前端窗口化时作为兜底）
pub const LOGS_PAGE_SIZE: usize = 10; // 日志页服务端分页
pub const CERT_WARN_DAYS: i64 = 30; // 证照到期预警天数
pub const MAX_CONTENT_LENGTH: usize = 20 * 1024 * 1024; // 20MB 上传上限
pub const SESSION_TIMEOUT_SECS: i64 = 30 * 60; // 会话超时 30 分钟
pub const LOCK_THRESHOLD: u32 = 5; // 登录失败锁定阈值
pub const LOCK_SECS: i64 = 10 * 60; // 锁定时长

#[derive(Clone)]
pub struct Config {
    pub base_dir: PathBuf,
    pub database: PathBuf,
    pub upload_folder: PathBuf,
    pub export_folder: PathBuf,
    pub backup_folder: PathBuf,
    pub secret_key: Vec<u8>,
    pub tz_offset_hours: i64,
}

impl Config {
    pub fn load() -> Config {
        let base_dir = base_dir();
        let _ = std::fs::create_dir_all(&base_dir);
        let cfg = Config {
            database: base_dir.join("data.db"),
            upload_folder: base_dir.join("uploads"),
            export_folder: base_dir.join("exports"),
            backup_folder: base_dir.join("backup"),
            secret_key: load_or_create_secret(&base_dir),
            tz_offset_hours: std::env::var("POTMS_TZ")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(8),
            base_dir,
        };
        for d in [&cfg.upload_folder, &cfg.export_folder, &cfg.backup_folder] {
            let _ = std::fs::create_dir_all(d);
        }
        cfg
    }
}

// 数据目录：优先 POTMS_BASE 环境变量；否则 exe 所在目录；开发态回退当前目录
fn base_dir() -> PathBuf {
    if let Ok(p) = std::env::var("POTMS_BASE") {
        return PathBuf::from(p);
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            // 避免开发态 target/debug 目录：若在 target 下则回退 cwd
            if !dir.components().any(|c| c.as_os_str() == "target") {
                return dir.to_path_buf();
            }
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

// 持久化 SECRET_KEY，避免重启导致会话失效
fn load_or_create_secret(base: &Path) -> Vec<u8> {
    if let Ok(env) = std::env::var("SECRET_KEY") {
        if !env.is_empty() {
            return env.into_bytes();
        }
    }
    let key_file = base.join(".secret_key");
    if let Ok(val) = std::fs::read_to_string(&key_file) {
        let v = val.trim();
        if !v.is_empty() {
            return v.as_bytes().to_vec();
        }
    }
    use rand::RngCore;
    let mut buf = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut buf);
    let hexed = hex_encode(&buf);
    let _ = std::fs::write(&key_file, &hexed);
    hexed.into_bytes()
}

fn hex_encode(b: &[u8]) -> String {
    b.iter().map(|x| format!("{:02x}", x)).collect()
}

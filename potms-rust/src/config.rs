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
    /// 证件领用 / 归还是否强制手写签名（POTMS_REQUIRE_SIGNATURE，默认强制）。
    ///
    /// 默认强制：签名就是「本人确实领了/还了」的凭证，一旦允许留空，这条记录就只剩
    /// 经办人的一面之词。放宽必须是明确的选择，不能是默认值。
    pub require_signature: bool,
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
            // 变量名与另外四版统一为 POTMS_TZ_OFFSET；本版原先叫 POTMS_TZ，
            // 同一台机器上换个版本跑，时区就悄悄退回 +8，而页面上只是时间差了
            // 几个小时，不报错，很难被发现。旧名继续认，免得已经写进批处理 /
            // 服务配置的部署失效。
            tz_offset_hours: std::env::var("POTMS_TZ_OFFSET")
                .or_else(|_| std::env::var("POTMS_TZ"))
                .ok()
                .and_then(|s| s.trim().parse().ok())
                .unwrap_or(8),
            require_signature: !matches!(
                std::env::var("POTMS_REQUIRE_SIGNATURE")
                    .unwrap_or_else(|_| "1".into())
                    .trim()
                    .to_ascii_lowercase()
                    .as_str(),
                "0" | "false" | "no" | "off"
            ),
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

#[cfg(test)]
mod tests {
    use super::*;

    /// 时区变量名与另外四版统一为 POTMS_TZ_OFFSET，同时继续认旧名 POTMS_TZ。
    ///
    /// 本版原先只认 POTMS_TZ：同一台机器上换个版本跑，时区就悄悄退回 +8，
    /// 而页面上只是时间差了几个小时，不会报错，很难被发现。
    ///
    /// 走真的 Config::load() 而不是抄一份读取逻辑——抄一份只能证明副本对。
    /// 环境变量是进程级的，所以整段串行放在一个 #[test] 里，并借 POTMS_BASE
    /// 把数据目录引到临时目录，免得在仓库里落下 .secret_key。
    #[test]
    fn tz_offset_env_names() {
        let tmp = std::env::temp_dir().join(format!("potms-cfg-{}", std::process::id()));
        let load = || {
            unsafe { std::env::set_var("POTMS_BASE", &tmp) };
            Config::load().tz_offset_hours
        };
        unsafe {
            std::env::remove_var("POTMS_TZ_OFFSET");
            std::env::remove_var("POTMS_TZ");
        }
        assert_eq!(load(), 8, "都不设时应为东八区");

        unsafe { std::env::set_var("POTMS_TZ", "9") };
        assert_eq!(load(), 9, "旧名 POTMS_TZ 仍要认，免得已有部署失效");

        unsafe { std::env::set_var("POTMS_TZ_OFFSET", " 0 ") };
        assert_eq!(load(), 0, "新名优先，且要容忍两边的空白");

        unsafe { std::env::set_var("POTMS_TZ_OFFSET", "不是数字") };
        assert_eq!(load(), 8, "非法值退回默认，不因配置笔误拒绝启动");

        unsafe {
            std::env::remove_var("POTMS_TZ_OFFSET");
            std::env::remove_var("POTMS_TZ");
            std::env::remove_var("POTMS_BASE");
        }
        let _ = std::fs::remove_dir_all(&tmp);
    }
}

// 数据库每日备份 + 保留 30 天
use crate::config::Config;
use crate::helpers;
use rusqlite::Connection;

const RETENTION_DAYS: i64 = 30;

// 每日备份：同日已备份则跳过（force 时强制重做）；返回 (日期 YYYYMMDD, 清理数量)
pub fn run_daily_backup(conn: &Connection, cfg: &Config, force: bool) -> (String, i64) {
    let ymd = helpers::now_local_ymd(cfg.tz_offset_hours);
    let _ = std::fs::create_dir_all(&cfg.backup_folder);
    let target = cfg.backup_folder.join(format!("data_{ymd}.db"));
    if force && target.exists() {
        let _ = std::fs::remove_file(&target);
    }
    if force || !target.exists() {
        // VACUUM INTO 生成一致性快照（含已合并的 WAL）
        let path = target.to_string_lossy().replace('\'', "''");
        let _ = conn.execute_batch(&format!("VACUUM INTO '{path}'"));
    }
    let pruned = prune_old_backups(cfg);
    (ymd, pruned)
}

fn prune_old_backups(cfg: &Config) -> i64 {
    let cutoff = {
        let d = time::OffsetDateTime::now_utc() - time::Duration::days(RETENTION_DAYS);
        format!("{:04}{:02}{:02}", d.year(), d.month() as u8, d.day())
    };
    let mut pruned = 0;
    if let Ok(entries) = std::fs::read_dir(&cfg.backup_folder) {
        for e in entries.flatten() {
            let name = e.file_name().to_string_lossy().into_owned();
            if let Some(date) = name.strip_prefix("data_").and_then(|s| s.strip_suffix(".db")) {
                if date.len() == 8 && date.bytes().all(|b| b.is_ascii_digit()) && date < cutoff.as_str() {
                    if std::fs::remove_file(e.path()).is_ok() {
                        pruned += 1;
                    }
                }
            }
        }
    }
    pruned
}

// 最新备份日期（YYYY-MM-DD），无则空串
pub fn latest_backup(cfg: &Config) -> String {
    let mut latest = String::new();
    if let Ok(entries) = std::fs::read_dir(&cfg.backup_folder) {
        for e in entries.flatten() {
            let name = e.file_name().to_string_lossy().into_owned();
            if let Some(date) = name.strip_prefix("data_").and_then(|s| s.strip_suffix(".db")) {
                if date.len() == 8 && date.bytes().all(|b| b.is_ascii_digit()) && date > latest.as_str() {
                    latest = date.to_string();
                }
            }
        }
    }
    if latest.len() == 8 {
        format!("{}-{}-{}", &latest[..4], &latest[4..6], &latest[6..])
    } else {
        String::new()
    }
}

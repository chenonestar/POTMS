"""数据库每日自动备份 + 保留 30 天"""
import os
import shutil
from datetime import datetime, timedelta

from config import Config

RETAIN_DAYS = 30
_PREFIX = "data_"
_SUFFIX = ".db"


def _backup_path(date_str: str) -> str:
    return os.path.join(Config.BACKUP_FOLDER, f"{_PREFIX}{date_str}{_SUFFIX}")


def latest_backup() -> tuple[str, str] | tuple[None, None]:
    """返回 (文件名, 日期YYYYMMDD)，无备份则 (None, None)"""
    if not os.path.isdir(Config.BACKUP_FOLDER):
        return (None, None)
    files = [f for f in os.listdir(Config.BACKUP_FOLDER)
             if f.startswith(_PREFIX) and f.endswith(_SUFFIX)]
    if not files:
        return (None, None)
    files.sort(reverse=True)
    latest = files[0]
    date_str = latest[len(_PREFIX):-len(_SUFFIX)]
    return (latest, date_str)


def prune_old_backups(retain_days: int = RETAIN_DAYS) -> int:
    """删除超过保留期的备份，返回删除数量"""
    if not os.path.isdir(Config.BACKUP_FOLDER):
        return 0
    cutoff = (datetime.now() - timedelta(days=retain_days)).strftime("%Y%m%d")
    removed = 0
    for f in os.listdir(Config.BACKUP_FOLDER):
        if f.startswith(_PREFIX) and f.endswith(_SUFFIX):
            date_str = f[len(_PREFIX):-len(_SUFFIX)]
            if date_str.isdigit() and date_str < cutoff:
                try:
                    os.remove(os.path.join(Config.BACKUP_FOLDER, f))
                    removed += 1
                except OSError:
                    pass
    return removed


def run_daily_backup(force: bool = False) -> dict:
    """
    执行每日备份（幂等）：当天已有备份则跳过（force=True 时强制覆盖）。
    完成后清理超过保留期的旧备份。
    返回 {created: bool, path: str|None, pruned: int, date: str}
    """
    os.makedirs(Config.BACKUP_FOLDER, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    dest = _backup_path(today)

    created = False
    if os.path.exists(Config.DATABASE) and (force or not os.path.exists(dest)):
        shutil.copy2(Config.DATABASE, dest)
        created = True

    pruned = prune_old_backups()
    return {"created": created, "path": dest if created else None,
            "pruned": pruned, "date": today}

"""数据库备份：每日自动备份 + 批量改数据前的独立快照，都保留 30 天。

两种备份的用途不一样，所以文件也分开放：

- **每日备份** `data_YYYYMMDD.db`：一天一份，当天重复触发就覆盖。它回答的是
  「昨天/上周的数据长什么样」。
- **改前快照** `before_<做什么>_YYYYMMDD_HHMMSS.db`：每次批量重写历史之前存一份，
  精确到秒且**从不覆盖**。它回答的是「这次改动之前长什么样」。

分开是必需的。改前快照若沿用每日备份那个文件名，同一天做两次批量改动，第二次
的备份会盖掉第一次改之前的那一份——第一次改错了就再也退不回去了，而这恰恰是
留这份备份要防的事。
"""
import os
import re
import shutil
from datetime import datetime, timedelta

from config import Config

RETAIN_DAYS = 30
_PREFIX = "data_"
_SNAP_PREFIX = "before_"
_SUFFIX = ".db"
# before_<tag>_YYYYMMDD_HHMMSS[_n].db —— 取出中间那段日期用于按保留期清理
_SNAP_RE = re.compile(r"^before_.+_(\d{8})_\d{6}(?:_\d+)?\.db$")

# 进程内"今日已检查"标记：首页每次访问都会触发备份检查，
# 同一天第二次起直接跳过文件系统检查与清理扫描
_checked_date: str | None = None


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


def _backup_date(fname: str) -> str | None:
    """从备份文件名里取出它代表的日期，取不出返回 None（不是我们放的文件，别碰）。"""
    if fname.startswith(_PREFIX) and fname.endswith(_SUFFIX):
        date_str = fname[len(_PREFIX):-len(_SUFFIX)]
        return date_str if date_str.isdigit() else None
    m = _SNAP_RE.match(fname)
    return m.group(1) if m else None


def prune_old_backups(retain_days: int = RETAIN_DAYS) -> int:
    """删除超过保留期的备份（每日备份与改前快照一视同仁），返回删除数量"""
    if not os.path.isdir(Config.BACKUP_FOLDER):
        return 0
    cutoff = (datetime.now() - timedelta(days=retain_days)).strftime("%Y%m%d")
    removed = 0
    for f in os.listdir(Config.BACKUP_FOLDER):
        date_str = _backup_date(f)
        if date_str and date_str < cutoff:
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
    global _checked_date
    today = datetime.now().strftime("%Y%m%d")
    if not force and _checked_date == today:
        return {"created": False, "path": None, "pruned": 0, "date": today}

    os.makedirs(Config.BACKUP_FOLDER, exist_ok=True)
    dest = _backup_path(today)

    created = False
    if os.path.exists(Config.DATABASE) and (force or not os.path.exists(dest)):
        shutil.copy2(Config.DATABASE, dest)
        created = True

    pruned = prune_old_backups()
    _checked_date = today
    return {"created": created, "path": dest if created else None,
            "pruned": pruned, "date": today}


def snapshot_before_change(tag: str) -> str:
    """批量重写历史之前存一份独立快照，返回文件名。失败抛异常，由调用方决定是否继续。

    与每日备份分开、且带到秒的时间戳，就是为了**永不覆盖**：同一天做两次批量改动，
    两份改前快照都要留得住，否则第一次改错了就退不回去了。tag 说明这次要改什么
    （org_rename / dict_rename / …），出事时不用逐个打开文件猜哪份是哪份。
    """
    os.makedirs(Config.BACKUP_FOLDER, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", tag) or "change"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"{_SNAP_PREFIX}{safe}_{stamp}{_SUFFIX}"
    # 同一秒内连着改两次会撞名。宁可加后缀也不覆盖——这份文件的全部价值就在于
    # 它是那一次改动之前的样子。
    n = 1
    while os.path.exists(os.path.join(Config.BACKUP_FOLDER, name)):
        name = f"{_SNAP_PREFIX}{safe}_{stamp}_{n}{_SUFFIX}"
        n += 1
    shutil.copy2(Config.DATABASE, os.path.join(Config.BACKUP_FOLDER, name))
    return name

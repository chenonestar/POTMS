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
import sqlite3
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


def copy_database(dest: str) -> None:
    """把当前数据库完整复制到 dest。

    **不能用 shutil.copy2。** 库开的是 WAL（见 database.get_db 的
    `PRAGMA journal_mode=WAL`）：一次 commit 之后数据先落在 `data.db-wal`，
    要等一次 checkpoint 才搬进 `data.db`，而 checkpoint 只在没有连接正在读时
    才做得成。只拷主库文件，就会把还留在 -wal 里的那部分**整段丢掉**。

    实测（主库已 checkpoint 含 50 条，随后在有连接开着的情况下又提交 300 条）：

        shutil.copy2(data.db)  → 备份里 50 条，静默丢失 300 条
        Connection.backup()    → 备份里 350 条

    丢了也不会报错：拷出来的是一个完全合法、能打开的数据库，只是停在过去。
    只有真去恢复那天才发现当天的活儿一条都没有。

    单机单人时每个请求结束就 close_db()，最后一个连接关闭会自动 checkpoint，
    所以这个坑平时不发作。**但断电、进程被杀、以及多人在线（8 个 waitress
    线程里总有连接活着）这三种情况下都会发作。**

    Connection.backup() 走 SQLite 官方的在线备份 API：它复制的是数据库的
    **逻辑内容**（自然包含 -wal 里已提交的部分），且在正确的锁下进行，
    写入方同时在写也能得到一个一致的快照。
    """
    src = sqlite3.connect(Config.DATABASE)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


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
        # force=True 会覆盖当天已有的那份：backup() 写进一个已存在的文件时会
        # 整体替换它的内容，不会与旧内容混在一起。
        copy_database(dest)
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
    copy_database(os.path.join(Config.BACKUP_FOLDER, name))
    return name

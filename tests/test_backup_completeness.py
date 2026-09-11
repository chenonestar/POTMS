"""第 12 批：备份必须拷得全。

`utils/backup.py` 原先用 `shutil.copy2(Config.DATABASE, dest)`——只拷主库
那一个文件。而库开的是 WAL（`database.get_db` 里的 `PRAGMA journal_mode=WAL`）：
一次 commit 之后数据先落在 `data.db-wal`，要等一次 checkpoint 才搬进
`data.db`，而 checkpoint 只在**没有连接正在读**时才做得成。

所以只拷主库文件，会把还留在 -wal 里的那部分整段丢掉。实测：

    主库已 checkpoint 含 50 条，随后在有连接开着的情况下又提交 300 条
    shutil.copy2   → 备份里 50 条，静默丢失 300 条
    backup() API   → 备份里 350 条

**丢了不会报错**：拷出来的是一个完全合法、能打开的数据库，只是停在过去。
只有真去恢复那天才发现当天的活儿一条都没有。

这个坑与「上不上网」无关。单机单人时每个请求结束就 close_db()，最后一个
连接关闭会自动 checkpoint，所以平时不发作；但断电、进程被杀、以及多人在线
（8 个 waitress 线程里总有连接活着）这三种情况下都会发作。

**这些用例的关键在于必须真的造出「有未 checkpoint 的 WAL」这个条件。**
不造这个条件，`shutil.copy2` 也能全绿——那样的用例撤掉修复不会变红，
等于没测（见 15.2 第 2 条：造的数据能分辨出对错吗）。
"""
import os
import sqlite3

import pytest

from config import Config


@pytest.fixture()
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    bak = tmp_path / "bak"
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(bak))
    # run_daily_backup 的「今日已检查」标记是**模块级全局**，跨用例会残留：
    # 前一条用例跑过之后，后一条直接短路返回 created=False / path=None。
    # 这不是用例的毛病，是那个全局本身在多线程下也不严谨（两个请求可能同时
    # 通过检查）——只是备份幂等，撞上了也只是多拷一次，不改数据。
    import utils.backup
    monkeypatch.setattr(utils.backup, "_checked_date", None)
    return tmp_path


def _seed_checkpointed(n: int) -> None:
    """建库、写 n 条、全部关闭——最后一个连接关闭时 SQLite 自动 checkpoint，
    此刻主库文件是完整的。这是「昨天」的状态。"""
    c = sqlite3.connect(Config.DATABASE)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
    for i in range(n):
        c.execute("INSERT INTO t(v) VALUES (?)", (f"老数据{i}",))
    c.commit()
    c.close()


def _write_with_reader_open(n: int):
    """在**有连接开着**的情况下再提交 n 条，checkpoint 因此被推迟。

    返回那个还开着的读连接，调用方负责关掉——它必须在备份期间保持打开，
    否则条件就不成立了（这正是第一版用例会假绿的地方）。
    """
    reader = sqlite3.connect(Config.DATABASE)
    reader.execute("PRAGMA journal_mode=WAL")
    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM t").fetchone()   # 持有读快照

    w = sqlite3.connect(Config.DATABASE)
    w.execute("PRAGMA journal_mode=WAL")
    for i in range(n):
        w.execute("INSERT INTO t(v) VALUES (?)", (f"今天办的{i}",))
        w.commit()
    w.close()
    return reader


def _count(path: str) -> int:
    c = sqlite3.connect(path)
    try:
        return c.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        c.close()


def _wal_size() -> int:
    wal = Config.DATABASE + "-wal"
    return os.path.getsize(wal) if os.path.exists(wal) else 0


# ===========================================================================
# 一、条件本身要成立
# ===========================================================================
def test_the_scenario_really_leaves_data_in_the_wal(paths):
    """先证明这批用例造出来的条件是真的：WAL 里确实压着没进主库的数据。

    这一条是给下面两条兜底的。WAL 若是空的，`shutil.copy2` 也能拷全，
    那么「备份完整」就成了一句永远为真的断言——撤掉修复也不会红。
    """
    _seed_checkpointed(50)
    assert _wal_size() == 0, "基线不对：主库应已 checkpoint"

    reader = _write_with_reader_open(300)
    try:
        assert _wal_size() > 0, "没造出未 checkpoint 的 WAL，后面两条会假绿"
        # 主库文件本身仍停在 50 条——这就是 shutil.copy2 会拷到的东西
        raw = sqlite3.connect(f"file:{Config.DATABASE}?immutable=1", uri=True)
        try:
            assert raw.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 50
        finally:
            raw.close()
    finally:
        reader.rollback(); reader.close()


# ===========================================================================
# 二、两个备份入口都要拷全
# ===========================================================================
def test_daily_backup_includes_data_still_in_the_wal(paths):
    """每日备份：350 条就该备出 350 条，不是主库文件里那 50 条。"""
    from utils.backup import run_daily_backup

    _seed_checkpointed(50)
    reader = _write_with_reader_open(300)
    try:
        res = run_daily_backup()
        assert res["created"], "没生成备份"
        assert _count(res["path"]) == 350
    finally:
        reader.rollback(); reader.close()


def test_snapshot_before_change_includes_data_still_in_the_wal(paths):
    """改前快照同理——而且它更要紧。

    它是批量重写历史（如经办人回填）之前的唯一退路。那份备份要是残的，
    等于没有退路，而调用方还会以为备份成功了。
    """
    from utils.backup import snapshot_before_change

    _seed_checkpointed(50)
    reader = _write_with_reader_open(300)
    try:
        name = snapshot_before_change("operator_backfill")
        assert _count(os.path.join(Config.BACKUP_FOLDER, name)) == 350
    finally:
        reader.rollback(); reader.close()


# ===========================================================================
# 三、别把原来能用的行为改坏了
# ===========================================================================
def test_a_plain_backup_still_works(paths):
    """反向对照：没有 WAL 残留时照样备得出来，别把改动写成只在特殊情形下work。"""
    from utils.backup import run_daily_backup

    _seed_checkpointed(20)
    res = run_daily_backup()
    assert res["created"] and _count(res["path"]) == 20


def test_force_overwrites_the_same_day_file_cleanly(paths):
    """同一天再备一次（force）要整体替换，不能与旧内容混在一起。

    backup() 写进一个已存在的文件与 copy2 覆盖不是一回事，这条专门守它：
    第一次备 20 条，删掉 15 条后强制再备，必须是 5 条，不是 20 或 25。
    """
    from utils.backup import run_daily_backup

    _seed_checkpointed(20)
    first = run_daily_backup()["path"]
    assert _count(first) == 20

    c = sqlite3.connect(Config.DATABASE)
    c.execute("DELETE FROM t WHERE id > 5")
    c.commit(); c.close()

    second = run_daily_backup(force=True)
    assert second["path"] == first, "force 应覆盖当天那一份，而不是另建一个"
    assert _count(first) == 5


def test_snapshot_never_overwrites_an_earlier_one(paths):
    """同一秒连做两次改前快照，两份都要留住——这是改前快照存在的全部理由。"""
    from utils.backup import snapshot_before_change

    _seed_checkpointed(10)
    a = snapshot_before_change("org_rename")
    b = snapshot_before_change("org_rename")
    assert a != b
    assert _count(os.path.join(Config.BACKUP_FOLDER, a)) == 10
    assert _count(os.path.join(Config.BACKUP_FOLDER, b)) == 10


def test_backup_does_not_disturb_the_live_database(paths):
    """备份期间库还能正常读写，备完数据也没被动过。"""
    from utils.backup import copy_database

    _seed_checkpointed(30)
    live = sqlite3.connect(Config.DATABASE)
    live.execute("PRAGMA journal_mode=WAL")
    try:
        dest = os.path.join(str(paths), "probe.db")
        copy_database(dest)
        assert _count(dest) == 30
        live.execute("INSERT INTO t(v) VALUES ('备份之后还能写')")
        live.commit()
        assert live.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 31
    finally:
        live.close()

"""经办人姓名 —— 单据上写真人名字，日志里记登录账号

背景：系统原先把登录账号（admin）直接当经办人写进业务表，打印出来的证件领用
凭证上「经办人（发放）：admin」，没法拿去归档。现在 users 表加了 full_name，
业务字段写姓名、日志字段仍记账号。

「老库连 users 表都没有」这条路径由 tests/test_migrations.py 覆盖——迁移里的
存在性守卫正是被那个用例逼出来的，这里不重复造一套残缺 schema。
"""
import re
import sqlite3

import pytest

from config import Config

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = "110101199001012133"

_INFO_FORM = {
    "unit": "总部", "department": "办公室", "name": "李四", "gender": "男",
    "birth_date": "19900101", "id_number": _VALID_ID, "work_start_date": "20120701",
    "education": "01", "degree": "01", "title": "01", "rank": "01",
    "political_status": "群众", "position": "科员",
}


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    for attr, sub in (("UPLOAD_FOLDER", "up"), ("EXPORT_FOLDER", "exp"), ("BACKUP_FOLDER", "bak")):
        d = tmp_path / sub
        d.mkdir()
        monkeypatch.setattr(Config, attr, str(d))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()
    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,"
               "residence,political_status,work_unit,position_or_title,supervisor_unit,operator) "
               "VALUES (1,'张','三','男','19900101',?,'北京','群众','总部','科长','人事处','admin')",
               (_VALID_ID,))
    db.commit(); db.close()
    from app import create_app
    client = create_app().test_client()
    tok = _CSRF.search(client.get("/login").get_data(as_text=True)).group(1)
    client.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return client


def _tok(client):
    return _CSRF.search(client.get("/").get_data(as_text=True)).group(1)


def _set_name(client, name):
    return client.post("/account", data={
        "csrf_token": _tok(client), "current_password": "admin123",
        "new_username": "admin", "new_full_name": name}, follow_redirects=True)


def _q(sql, *args):
    db = sqlite3.connect(Config.DATABASE)
    row = db.execute(sql, args).fetchone()
    db.close()
    return row


# ---------------------------------------------------------------------------
# 新库结构与迁移
# ---------------------------------------------------------------------------
def test_new_database_has_full_name(c):
    cols = {r[1] for r in sqlite3.connect(Config.DATABASE).execute("PRAGMA table_info(users)")}
    assert "full_name" in cols


def test_migration_adds_full_name_to_legacy_db(tmp_path, monkeypatch):
    """老库升级后应自动补列，且原有数据一条不动。

    造老库的办法是「建完整新库，再把 full_name 列删掉」——比手搓一批残缺假表
    更贴近真实场景：用户就是拿老 data.db 覆盖到新程序旁边直接启动。
    """
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "legacy.db"))
    for attr, sub in (("UPLOAD_FOLDER", "up"), ("EXPORT_FOLDER", "exp"), ("BACKUP_FOLDER", "bak")):
        d = tmp_path / sub; d.mkdir(); monkeypatch.setattr(Config, attr, str(d))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()

    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,"
               "residence,political_status,work_unit,position_or_title,supervisor_unit,operator) "
               "VALUES (9,'王','五','男','19880101','110101198801010019','沪','群众','总部',"
               "'科长','人事处','admin')")
    db.execute("ALTER TABLE users DROP COLUMN full_name")          # 退回老库形态
    db.commit()
    assert "full_name" not in {r[1] for r in db.execute("PRAGMA table_info(users)")}
    db.close()

    database.run_migrations()                                       # 相当于新程序启动

    db = sqlite3.connect(Config.DATABASE)
    assert "full_name" in {r[1] for r in db.execute("PRAGMA table_info(users)")}
    assert db.execute("SELECT username FROM users").fetchone()[0] == "admin"
    assert db.execute("SELECT surname FROM personnel_filing WHERE id=9").fetchone()[0] == "王"
    db.close()


# ---------------------------------------------------------------------------
# 姓名没填时回退到账号
# ---------------------------------------------------------------------------
def test_falls_back_to_username_when_name_empty(c):
    c.post("/personnel/info/new", data={
        "csrf_token": _tok(c), **_INFO_FORM}, follow_redirects=True)
    assert _q("SELECT operator FROM personnel_info ORDER BY id DESC LIMIT 1")[0] == "admin"


# ---------------------------------------------------------------------------
# 填了姓名之后：业务表写姓名，日志写账号
# ---------------------------------------------------------------------------
def test_business_records_use_real_name(c):
    _set_name(c, "张建国")
    c.post("/personnel/info/new", data={
        "csrf_token": _tok(c), **_INFO_FORM}, follow_redirects=True)
    assert _q("SELECT operator FROM personnel_info ORDER BY id DESC LIMIT 1")[0] == "张建国"


def test_operation_log_keeps_account_not_name(c):
    """日志记账号：账号是身份标识，姓名可改，只记姓名的话改名后就对不上人。"""
    _set_name(c, "张建国")
    c.post("/personnel/info/new", data={
        "csrf_token": _tok(c), **_INFO_FORM}, follow_redirects=True)
    assert _q("SELECT operator FROM operation_logs WHERE target_type='personnel_info' "
              "ORDER BY id DESC LIMIT 1")[0] == "admin"


def test_log_page_shows_name_with_account(c):
    _set_name(c, "张建国")
    html = c.get("/logs/").get_data(as_text=True)
    assert "张建国" in html and "（admin）" in html


# ---------------------------------------------------------------------------
# 历史回填
# ---------------------------------------------------------------------------
def test_backfill_requires_name_first(c):
    res = c.post("/account/backfill-operator", data={"csrf_token": _tok(c)},
                 follow_redirects=True)
    assert "请先填写并保存姓名" in res.get_data(as_text=True)
    assert _q("SELECT operator FROM personnel_filing WHERE id=1")[0] == "admin"


def test_backfill_updates_business_tables_only(c):
    _set_name(c, "张建国")
    before_log = _q("SELECT operator FROM operation_logs ORDER BY id LIMIT 1")[0]

    res = c.post("/account/backfill-operator", data={"csrf_token": _tok(c)},
                 follow_redirects=True)
    assert "更新为「张建国」" in res.get_data(as_text=True)

    # 业务表改了
    assert _q("SELECT operator FROM personnel_filing WHERE id=1")[0] == "张建国"
    # 日志没动
    assert _q("SELECT operator FROM operation_logs ORDER BY id LIMIT 1")[0] == before_log == "admin"


def test_backfill_makes_a_backup_first(c, tmp_path):
    """不可逆的批量写入，执行前必须留一份退路。"""
    import os
    _set_name(c, "张建国")
    assert not os.listdir(Config.BACKUP_FOLDER)
    c.post("/account/backfill-operator", data={"csrf_token": _tok(c)}, follow_redirects=True)
    assert os.listdir(Config.BACKUP_FOLDER), "回填前应自动备份 data.db"


def test_backfill_is_logged(c):
    _set_name(c, "张建国")
    c.post("/account/backfill-operator", data={"csrf_token": _tok(c)}, follow_redirects=True)
    detail = _q("SELECT detail FROM operation_logs WHERE detail LIKE '%历史经办人回填%' "
                "ORDER BY id DESC LIMIT 1")
    assert detail and "admin → 张建国" in detail[0]


def test_account_page_shows_pending_count(c):
    _set_name(c, "张建国")
    html = c.get("/account").get_data(as_text=True)
    assert "历史经办人回填" in html and "回填这" in html


# ---------------------------------------------------------------------------
# 收尾一致性：POTMS_BASE 与 /favicon.ico
# ---------------------------------------------------------------------------

def test_favicon_returns_no_content(c):
    """浏览器每开一个标签页都要 /favicon.ico；明确应答 204，未登录也要能拿到。"""
    resp = c.get("/favicon.ico")
    assert resp.status_code == 204
    assert resp.data == b""


def test_potms_base_overrides_data_dir(tmp_path, monkeypatch):
    """POTMS_BASE 指定数据目录——另外四版早就支持，本版此前只认 exe 所在目录。

    重新导入 config 才能看到新的环境变量：BASE_DIR 是模块级常量，导入即固化。
    """
    import importlib
    import config as config_module

    target = tmp_path / "潜在的共享盘"
    monkeypatch.setenv("POTMS_BASE", str(target))
    try:
        reloaded = importlib.reload(config_module)
        assert reloaded.BASE_DIR == str(target)
        assert target.is_dir(), "POTMS_BASE 指向的目录应被自动建出来"
        assert reloaded.Config.DATABASE == str(target / "data.db")
    finally:
        # 还原，免得污染同一进程里后面的用例
        monkeypatch.delenv("POTMS_BASE", raising=False)
        importlib.reload(config_module)

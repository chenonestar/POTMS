"""P1+P2 安全与健壮性加固测试：登录防爆破 / PDF 魔数 / 索引 / 错误页。"""
import io
import re
import sqlite3

import pytest

from config import Config

CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"
    up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    import database
    database.init_db()
    database.run_migrations()
    database.seed_data()
    import auth
    auth._login_fails.clear()  # 防爆破计数为进程级，测试间必须清零
    from app import create_app
    app = create_app()
    return app.test_client()


def _tok(c, path="/login"):
    return CSRF.search(c.get(path).get_data(as_text=True)).group(1)


def _login(c, pw, username="admin"):
    return c.post("/login", data={"username": username, "password": pw,
                                  "csrf_token": _tok(c)})


# ------------------------- S1 登录防爆破 -------------------------
def test_lockout_after_5_failures(app_client):
    c = app_client
    for _ in range(5):
        r = _login(c, "wrong-password")
        assert r.status_code == 200
    # 已锁定：即使密码正确也拒绝
    r = _login(c, "admin123")
    html = r.get_data(as_text=True)
    assert "锁定" in html
    assert r.status_code == 200  # 未跳转仪表盘
    # 确认未登录
    assert c.get("/").status_code == 302


def test_success_resets_counter(app_client):
    c = app_client
    for _ in range(3):
        _login(c, "wrong-password")
    r = _login(c, "admin123")
    assert r.status_code == 302  # 成功跳转
    # 登出后失败计数应已清零：再错 4 次仍未锁
    c.get("/logout")
    for _ in range(4):
        _login(c, "wrong-password")
    r = _login(c, "admin123")
    # 第 5 次失败才锁；上面只错了 4 次，本次正确应成功
    assert r.status_code == 302


def test_lock_event_logged(app_client):
    c = app_client
    for _ in range(5):
        _login(c, "wrong-password")
    db = sqlite3.connect(Config.DATABASE)
    row = db.execute("SELECT action, detail FROM operation_logs WHERE action='lock'").fetchone()
    assert row is not None and "锁定" in row[1]


# ------------------------- S2 PDF 魔数校验 -------------------------
def _travel_form(csrf, fake=False):
    pdf = b"NOT A PDF!" if fake else b"%PDF-1.4 fake body"
    return dict(
        csrf_token=csrf, personnel_filing_id="1", unit="局", department="科",
        name="张三", position="科员", title="工程师", id_number="110101199001012133",
        destination_passport="美国-护照", category="出国",
        travel_dates="2026/08/01-2026/08/11", need_new_passport="否",
        passport_collect_date="20260725",
        att_application=(io.BytesIO(pdf), "a.pdf"),
        att_approval=(io.BytesIO(b"%PDF-1.4"), "b.pdf"),
    )


@pytest.fixture()
def logged_in(app_client):
    c = app_client
    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,"
               "residence,political_status,work_unit,position_or_title,supervisor_unit,tag,informed,"
               "status,operator) VALUES (1,'张','三','男','19900101','110101199001012133','X','群众',"
               "'局','科员','主管','新增','否','active','admin')")
    db.commit()
    db.close()
    r = _login(c, "admin123")
    assert r.status_code == 302
    return c

def test_fake_pdf_rejected(logged_in):
    c = logged_in
    r = c.post("/travel/new", data=_travel_form(_tok(c, "/"), fake=True),
               content_type="multipart/form-data", follow_redirects=True)
    assert "不是有效的 PDF" in r.get_data(as_text=True)
    db = sqlite3.connect(Config.DATABASE)
    assert db.execute("SELECT COUNT(*) FROM travel_details").fetchone()[0] == 0  # 记录未入库


def test_real_pdf_accepted(logged_in):
    c = logged_in
    r = c.post("/travel/new", data=_travel_form(_tok(c, "/")),
               content_type="multipart/form-data", follow_redirects=True)
    assert "已保存" in r.get_data(as_text=True)
    db = sqlite3.connect(Config.DATABASE)
    assert db.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 2


# ------------------------- F1 数据库索引 -------------------------
def test_indexes_created(app_client):
    db = sqlite3.connect(Config.DATABASE)
    names = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'").fetchall()}
    assert {"idx_pf_id_number", "idx_pf_status", "idx_td_pf_id",
            "idx_cert_pf_id", "idx_dec_pf_id", "idx_att_travel_id",
            "idx_logs_created_at"} <= names


# ------------------------- R1 中文错误页 -------------------------
def test_404_chinese_page(app_client):
    r = app_client.get("/no-such-page-xyz")
    assert r.status_code == 404
    assert "页面不存在" in r.get_data(as_text=True)

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
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
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


# ------------------------- P3: 配置 / 备份标记 / 日志归档 / 全局搜索 -------------------------
def test_session_cookie_flags():
    assert Config.SESSION_COOKIE_HTTPONLY is True
    assert Config.SESSION_COOKIE_SAMESITE == "Lax"


def test_backup_daily_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "d.db"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bk"))
    (tmp_path / "d.db").write_bytes(b"x")
    import utils.backup as bk
    bk._checked_date = None
    r1 = bk.run_daily_backup()
    assert r1["created"] is True
    assert bk._checked_date == r1["date"]          # 当日标记已置
    r2 = bk.run_daily_backup()                     # 同日第二次：直接跳过
    assert r2["created"] is False and r2["path"] is None
    r3 = bk.run_daily_backup(force=True)           # force 不受标记影响
    assert r3["created"] is True


def test_logs_export_by_year(logged_in):
    c = logged_in
    # 上面 fixture 的登录/建档已产生日志；取当前本地年份导出
    from datetime import datetime
    year = datetime.now().strftime("%Y")
    r = c.get(f"/logs/export?year={year}")
    assert r.status_code == 200
    assert r.data[:2] == b"PK"                     # xlsx 是 zip 容器
    # 无效年份回列表页
    assert c.get("/logs/export?year=abc").status_code == 302


def test_global_search(logged_in):
    c = logged_in
    r = c.get("/search?q=张三")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "人员备案" in html and "张三" in html
    # 空关键词提示页
    assert "一次搜遍" in c.get("/search").get_data(as_text=True)
    # 无结果
    assert "未找到" in c.get("/search?q=不存在的名字XYZ").get_data(as_text=True)


# ------------------------- 导入模板去除“操作人”列 + 自动写入 -------------------------
def test_import_template_no_operator_column(app_client):
    from app import create_app  # 确保应用上下文可用
    import utils.excel_import as ei
    from openpyxl import load_workbook
    buf = ei.generate_import_template()
    hdr = [c.value for c in load_workbook(buf).active[1]]
    assert "操作人" not in hdr
    assert len(hdr) == 20 and hdr[-1] == "备注"


def test_import_operator_from_session(app_client):
    import utils.excel_import as ei
    from openpyxl import load_workbook
    from app import create_app
    buf = io.BytesIO()
    load_workbook(ei.generate_import_template()).save(buf)  # 含自带示例行
    buf.seek(0)
    with create_app().app_context():                        # 解析需应用上下文（get_db）
        res = ei.parse_import_file(buf, operator="wangwu")
    assert res["success"] == 1
    row = sqlite3.connect(Config.DATABASE).execute(
        "SELECT operator FROM personnel_filing").fetchone()
    assert row[0] == "wangwu"      # 操作人来自会话，而非表格

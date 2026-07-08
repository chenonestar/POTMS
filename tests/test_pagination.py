"""分页回归测试：翻页链接不得因 request.args 中已含 page 而崩溃。"""
import os
import re
import sqlite3

import pytest

from config import Config

CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"
    up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    import database
    database.init_db()
    database.run_migrations()
    database.seed_data()
    # 造 25 条备案记录，确保 > 每页条数、产生多页
    db = sqlite3.connect(Config.DATABASE)
    for i in range(25):
        db.execute(
            "INSERT INTO personnel_filing (surname, given_name, gender, birth_date, id_number, "
            "residence, political_status, work_unit, position_or_title, supervisor_unit, tag, "
            "informed, status, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("张", f"三{i}", "男", "19900101", f"1101011990010100{i:02d}", "X", "群众",
             "某局", "科员", "主管", "新增", "否", "active", "admin"),
        )
    db.commit()
    db.close()
    from app import create_app
    app = create_app()
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "admin123",
                           "csrf_token": CSRF.search(c.get("/login").get_data(as_text=True)).group(1)})
    return c


def test_server_returns_all_rows(client):
    # 纯前端窗口化：服务端一次性下发全部 25 行（分页交给浏览器）
    html = client.get("/personnel/").get_data(as_text=True)
    assert html.count('class="row-check"') == 25


def test_page_param_ignored_gracefully(client):
    # 分页由前端处理，URL 带 page 不再影响服务端，也不得报错
    r = client.get("/personnel/?page=2")
    assert r.status_code == 200
    assert r.get_data(as_text=True).count('class="row-check"') == 25


def test_filter_still_server_side(client):
    # 筛选仍在服务端：active 状态返回全部匹配行，无 500
    r = client.get("/personnel/?status=active")
    assert r.status_code == 200
    assert r.get_data(as_text=True).count('class="row-check"') == 25

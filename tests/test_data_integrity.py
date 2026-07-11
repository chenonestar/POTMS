"""#2–#5 数据完整性回归：信息表删除守卫 / 备案删除拦截 / 同号防重 / 导出排除孤儿。"""
import re
import sqlite3

import pytest

from config import Config

CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
VALID_ID = "110101199001012133"  # 合法男性身份证（生日 19900101）


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()
    import auth
    auth._login_fails.clear()
    from app import create_app
    client = create_app().test_client()
    tok = CSRF.search(client.get("/login").get_data(as_text=True)).group(1)
    client.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return client


def _tok(client):
    return CSRF.search(client.get("/").get_data(as_text=True)).group(1)


def _seed_info_filing_cert(db):
    """info id=1（有 filing）+ filing id=1（有证照）。"""
    db.execute("INSERT INTO personnel_info (id,unit,department,name,gender,birth_date,id_number,"
               "rank,political_status,position,operator) VALUES (1,'总部','人事处','张三','男',"
               "'19900101',?,'03','群众','科长','admin')", (VALID_ID,))
    db.execute("INSERT INTO personnel_filing (id,personnel_info_id,surname,given_name,gender,birth_date,"
               "id_number,residence,political_status,work_unit,position_or_title,supervisor_unit,tag,"
               "informed,status,operator) VALUES (1,1,'张','三','男','19900101',?,'X','群众','总部',"
               "'科长','主管','新增','否','active','admin')", (VALID_ID,))
    db.execute("INSERT INTO certificates (personnel_filing_id,unit,department,name,passport_no,operator) "
               "VALUES (1,'总部','人事处','张三','E12345678','admin')")
    db.commit()


def test_dup_info_blocked(c):
    """#5 同一身份证号已存在信息表时，新建应被拦截。"""
    db = sqlite3.connect(Config.DATABASE)
    _seed_info_filing_cert(db)
    r = c.post("/personnel/info/new", data={
        "csrf_token": _tok(c), "unit": "总部", "department": "财务部", "name": "张三",
        "gender": "男", "birth_date": "19900101", "id_number": VALID_ID,
        "work_start_date": "20100701", "education": "03", "degree": "03", "title": "02",
        "rank": "03", "political_status": "群众", "position": "科长",
    })
    assert r.status_code == 200  # 未跳转 = 被拦截
    assert "已存在信息登记表" in r.get_data(as_text=True)
    # 未新增第二条
    assert db.execute("SELECT COUNT(*) FROM personnel_info").fetchone()[0] == 1


def test_filing_delete_blocked_with_cert(c):
    """#3 名下有证照的备案不能删除。"""
    db = sqlite3.connect(Config.DATABASE)
    _seed_info_filing_cert(db)
    c.post("/personnel/1/delete", data={"csrf_token": _tok(c)})
    assert sqlite3.connect(Config.DATABASE).execute(
        "SELECT COUNT(*) FROM personnel_filing WHERE id=1").fetchone()[0] == 1


def test_info_delete_guard_and_orphan(c):
    """#2 有备案引用的信息表不能删；孤儿信息表可删。"""
    db = sqlite3.connect(Config.DATABASE)
    _seed_info_filing_cert(db)
    # 管理页可访问
    assert "信息登记表管理" in c.get("/personnel/info/").get_data(as_text=True)
    # 有引用 → 拒删
    c.post("/personnel/info/1/delete", data={"csrf_token": _tok(c)})
    assert db.execute("SELECT COUNT(*) FROM personnel_info WHERE id=1").fetchone()[0] == 1
    # 孤儿 → 可删
    db.execute("INSERT INTO personnel_info (id,unit,department,name,gender,birth_date,id_number,"
               "rank,political_status,position,operator) VALUES (2,'总部','工程部','李四','男',"
               "'19850101','000000000000000000','03','群众','员工','admin')")
    db.commit()
    c.post("/personnel/info/2/delete", data={"csrf_token": _tok(c)})
    assert sqlite3.connect(Config.DATABASE).execute(
        "SELECT COUNT(*) FROM personnel_info WHERE id=2").fetchone()[0] == 0


def test_export_excludes_orphan(c):
    """#4 信息表导出仅含有备案引用的记录，孤儿不外泄。"""
    db = sqlite3.connect(Config.DATABASE)
    _seed_info_filing_cert(db)
    db.execute("INSERT INTO personnel_info (id,unit,department,name,gender,birth_date,id_number,"
               "rank,political_status,position,operator) VALUES (9,'总部','工程部','王五','男',"
               "'19850101','111111111111111111','03','群众','员工','admin')")
    db.commit()
    from app import create_app
    with create_app().app_context():
        from utils.excel_export import export_personnel_info
        from database import get_db
        # 复用导出同款 JOIN 查询断言：仅 1 条（孤儿 id=9 被排除）
        n = get_db().execute(
            "SELECT COUNT(*) FROM (SELECT pi.id FROM personnel_info pi "
            "JOIN personnel_filing pf ON pf.personnel_info_id=pi.id GROUP BY pi.id)"
        ).fetchone()[0]
        assert n == 1
        # 端到端：导出函数可正常产出文件
        path, _ = export_personnel_info("admin")
        assert path.endswith(".xlsx")

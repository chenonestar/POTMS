"""证照台账的三条约束：跨行合并推断 / 一人一行 / 换发提醒。

certificates 是「当前持有什么证」的台账（一行为一人，三证横向排列），
不是持证流水账。历史由两条链承担：用过的证留在出行与领用记录里（各存号码
快照），换发动作留在操作日志的前后快照里。
"""
import re
import sqlite3

import pytest

from config import Config

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = "110101199001012133"


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()
    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
               "id_number,residence,political_status,work_unit,position_or_title,"
               "supervisor_unit,operator) VALUES (1,'王','某','男','19900101',?,'北京',"
               "'群众','总部','科长','人事处','admin')", (_VALID_ID,))
    db.commit(); db.close()
    from app import create_app
    cl = create_app().test_client()
    tok = _CSRF.search(cl.get("/login").get_data(as_text=True)).group(1)
    cl.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return cl


def _tok(cl):
    return _CSRF.search(cl.get("/").get_data(as_text=True)).group(1)


def _cert_form(cl, **over):
    data = {"csrf_token": _tok(cl), "personnel_filing_id": "1", "unit": "总部",
            "department": "技术部", "name": "王某"}
    data.update(over)
    return data


def _rows():
    db = sqlite3.connect(Config.DATABASE)
    n = db.execute("SELECT COUNT(*) FROM certificates WHERE personnel_filing_id=1").fetchone()[0]
    db.close()
    return n


# ---------------------------------------------------------------------------
# C1 推断要跨行合并——只取一条会给出自信的错误答案
# ---------------------------------------------------------------------------
def test_infer_merges_across_multiple_cert_rows(c):
    """一人两条证照记录时，推断必须看全，不能只看第一条。

    现实成因：先登记了护照，过一阵办了港澳通行证时没找到原记录，又建了一条。
    只取第一条会连踩三级判据——第①级拿不到港澳号码所以对不上，第③级又因为
    「那条里只有护照」而答出 01。给出错误答案比判不出更糟。
    """
    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO certificates (id,personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (1,1,'总部','技术部','王某','E11111111','20351231','20250101','admin')")
    db.execute("INSERT INTO certificates (id,personnel_filing_id,unit,department,name,"
               "hm_pass_no,hm_pass_expiry,hm_pass_submit_date,operator) "
               "VALUES (2,1,'总部','技术部','王某','C22222222','20351231','20250201','admin')")
    db.commit()
    from database import infer_cert_type
    # 「香港」是地名不是证件名，第②级刻意不认，只能靠第①级的号码匹配
    assert infer_cert_type(db, 1, "C22222222", "香港") == "02"
    assert infer_cert_type(db, 1, "E11111111", "美国") == "01"
    db.close()


def test_infer_single_row_still_works(c):
    """单条记录（一人一行的正常形态）行为不变。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO certificates (personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,"
               "tw_pass_no,tw_pass_expiry,tw_pass_submit_date,operator) "
               "VALUES (1,'总部','技术部','王某','E1','20351231','20250101',"
               "'T9','20351231','20250101','admin')")
    db.commit()
    from database import infer_cert_type
    assert infer_cert_type(db, 1, "T9", "台湾") == "03"
    db.close()


# ---------------------------------------------------------------------------
# C2 一人一行
# ---------------------------------------------------------------------------
def test_second_cert_row_for_same_person_rejected(c):
    """三类证件登记在同一行的三组列上，一个人不该有第二条记录。"""
    r = c.post("/certificate/new", data=_cert_form(
        c, passport_no="E11111111", passport_expiry="20351231",
        passport_submit_date="20250101"), follow_redirects=True)
    assert _rows() == 1

    r = c.post("/certificate/new", data=_cert_form(
        c, hm_pass_no="C22222222", hm_pass_expiry="20351231",
        hm_pass_submit_date="20250201"), follow_redirects=True)
    assert "已有证照记录" in r.get_data(as_text=True)
    assert _rows() == 1, "同一个人不该出现第二条证照记录"


def test_editing_the_single_row_adds_other_cert_types(c):
    """正确做法是编辑那一条，把第二类证件加进同一行。"""
    c.post("/certificate/new", data=_cert_form(
        c, passport_no="E11111111", passport_expiry="20351231",
        passport_submit_date="20250101"), follow_redirects=True)
    c.post("/certificate/1/edit", data=_cert_form(
        c, passport_no="E11111111", passport_expiry="20351231",
        passport_submit_date="20250101",
        hm_pass_no="C22222222", hm_pass_expiry="20351231",
        hm_pass_submit_date="20250201"), follow_redirects=True)
    db = sqlite3.connect(Config.DATABASE)
    got = db.execute("SELECT passport_no, hm_pass_no FROM certificates WHERE id=1").fetchone()
    db.close()
    assert got == ("E11111111", "C22222222")
    assert _rows() == 1


# ---------------------------------------------------------------------------
# C3 换发提醒
# ---------------------------------------------------------------------------
def _renew(cl, **over):
    base = {"passport_no": "E11111111", "passport_expiry": "20260601",
            "passport_submit_date": "20200101"}
    base.update(over)
    return cl.post("/certificate/1/edit", data=_cert_form(cl, **base), follow_redirects=True)


@pytest.fixture()
def with_passport(c):
    c.post("/certificate/new", data=_cert_form(
        c, passport_no="E11111111", passport_expiry="20260601",
        passport_submit_date="20200101"), follow_redirects=True)
    return c


def test_renewal_warns_to_update_dates(with_passport):
    """号码换了，有效期或上交日期还留着旧证的——台账不准，到期预警随之失灵。"""
    r = _renew(with_passport, passport_no="E99999999")
    body = r.get_data(as_text=True)
    assert "普通护照号码已变更" in body
    assert "有效日期与上交日期同步更新" in body


def test_no_warning_when_number_unchanged(with_passport):
    """只改有效期不算换发，不该唠叨。"""
    r = _renew(with_passport, passport_expiry="20360601")
    assert "号码已变更" not in r.get_data(as_text=True)


def test_no_warning_on_first_registration(with_passport):
    """从空到有是首次登记，不是换发。"""
    r = _renew(with_passport, hm_pass_no="C22222222", hm_pass_expiry="20351231",
               hm_pass_submit_date="20250201")
    body = r.get_data(as_text=True)
    assert "往来港澳通行证号码已变更" not in body


def test_renewal_keeps_one_row_and_logs_old_number(with_passport):
    """换发走覆盖，不新增行；旧号码留在操作日志的前后快照里。

    没有任何东西外键引用 certificates——出行与领用记录各存号码文本快照——
    所以覆盖不会打断历史单据。
    """
    import json
    _renew(with_passport, passport_no="E99999999", passport_expiry="20360601",
           passport_submit_date="20260701")
    db = sqlite3.connect(Config.DATABASE)
    assert db.execute("SELECT COUNT(*) FROM certificates").fetchone()[0] == 1
    assert db.execute("SELECT passport_no FROM certificates").fetchone()[0] == "E99999999"
    snap = json.loads(db.execute(
        "SELECT snapshot FROM operation_logs WHERE target_type='certificates' "
        "AND action='update' ORDER BY id DESC LIMIT 1").fetchone()[0])
    db.close()
    assert snap["before"]["passport_no"] == "E11111111"
    assert snap["after"]["passport_no"] == "E99999999"

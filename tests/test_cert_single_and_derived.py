"""一次申请一本证 / 证件号码派生 / 「是否做证」与实际持证一致。

三条共同收紧「一次出行 ↔ 一本证件」这条线。此前：
- 证件种类是复选框，一条领用记录能勾三种；
- 明细表的证件号码手填，与领用记录各写各的，打印件上「证件号码」和
  「证件领用日期」两个格子可能来自不同的证件；
- 「是否做证」纯自由选择，一本证都没有的人也能填「否」。
"""
import io
import re
import sqlite3

import pytest

from config import Config
from conftest import seed_required_attachments, valid_id
from tests.test_issuance import _PNG_DATA_URL as _PNG

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = valid_id(1)   # 1 号人物；其余人各用 valid_id(pid)


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
    # 1 号有一本在有效期内的护照；2 号名下什么证都没有
    for pid, nm in ((1, "有证张三"), (2, "无证李四")):
        db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
                   "id_number,residence,political_status,work_unit,position_or_title,"
                   "supervisor_unit,operator) VALUES (?,?,'','男','19900101',?,'北京','群众',"
                   "'总部','科长','人事处','admin')", (pid, nm, valid_id(pid)))
    db.execute("INSERT INTO certificates (personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (1,'总部','技术部','有证张三','E12345678','20351231','20250101','admin')")
    db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
               "id_number,destination_passport,category,travel_dates,need_new_passport,"
               "passport_no,operator) VALUES (1,1,'总部','技术部','有证张三','科长',?,"
               "'美国/护照','01','2026/08/01-2026/08/11','否','手填的旧号码','admin')",
               (_VALID_ID,))
    seed_required_attachments(db, 1, "否")
    db.commit(); db.close()
    from app import create_app
    cl = create_app().test_client()
    tok = _CSRF.search(cl.get("/login").get_data(as_text=True)).group(1)
    cl.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return cl


def _tok(cl):
    return _CSRF.search(cl.get("/").get_data(as_text=True)).group(1)


def _travel_passport_no(tid=1):
    db = sqlite3.connect(Config.DATABASE)
    v = db.execute("SELECT passport_no FROM travel_details WHERE id=?", (tid,)).fetchone()[0]
    db.close()
    return v


def _issue(cl, **over):
    data = {"csrf_token": _tok(cl), "travel_id": "1", "personnel_filing_id": "1",
            "holder_name": "有证张三", "id_number": _VALID_ID, "cert_types": "01",
            "cert_nos": "E12345678", "issue_date": "20260720", "sign_png": _PNG}
    data.update(over)
    return cl.post("/issuance/new", data=data, follow_redirects=True)


# ---------------------------------------------------------------------------
# B1 一次申请一本证
# ---------------------------------------------------------------------------
def test_cert_type_input_is_radio(c):
    """界面上是单选而不是复选框——服务端拦得住，但不该让人先勾了再被拒。"""
    html = c.get("/issuance/new?travel_id=1").get_data(as_text=True)
    assert 'type="radio" name="cert_types"' in html
    assert 'type="checkbox" name="cert_types"' not in html
    assert "可多选" not in html


# ---------------------------------------------------------------------------
# B2 明细表证件号码派生
# ---------------------------------------------------------------------------
def test_issuance_overwrites_travel_passport_no(c):
    """登记领用后，明细表的证件号码以领用记录为准。

    两个格子此前各写各的：号码手填、领用日期由领用记录派生，打印件上并排
    放着却可能来自不同的证件。
    """
    assert _travel_passport_no() == "手填的旧号码"
    _issue(c)
    assert _travel_passport_no() == "E12345678"


def test_travel_form_locks_derived_passport_no(c):
    """有领用记录时那一栏只读，并写明是派生的。"""
    _issue(c)
    html = c.get("/travel/1/edit").get_data(as_text=True)
    field = re.search(r'name="passport_no".*?</div>', html, re.S).group(0)
    assert "readonly" in field
    assert "派生" in html


def test_travel_edit_cannot_override_derived_passport_no(c):
    """只读字段照样会提交，伪造 POST 更是想填什么填什么——服务端不采信。"""
    _issue(c)
    c.post("/travel/1/edit", data={
        "csrf_token": _tok(c), "personnel_filing_id": "1", "unit": "总部",
        "department": "技术部", "name": "有证张三", "position": "科长",
        "id_number": _VALID_ID, "destination_passport": "美国/护照", "category": "01",
        "travel_dates": "2026/08/01-2026/08/11", "need_new_passport": "否",
        "approval_date": "20260701", "intended_cert_type": "01",
        "passport_no": "伪造的号码",
    }, follow_redirects=True)
    assert _travel_passport_no() == "E12345678"


def test_path_b_passport_no_still_hand_entered(c):
    """路径B 没有领用记录，那一栏是系统里唯一的来源，必须仍可手填。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
               "id_number,destination_passport,category,travel_dates,need_new_passport,operator) "
               "VALUES (2,2,'总部','技术部','无证李四','科长',?,'美国/护照','01',"
               "'2026/09/01-2026/09/11','是','admin')", (_VALID_ID,))
    seed_required_attachments(db, 2, "是")
    db.commit(); db.close()

    html = c.get("/travel/2/edit").get_data(as_text=True)
    field = re.search(r'name="passport_no".*?</div>', html, re.S).group(0)
    assert "readonly" not in field

    c.post("/travel/2/edit", data={
        "csrf_token": _tok(c), "personnel_filing_id": "2", "unit": "总部",
        "department": "技术部", "name": "无证李四", "position": "科长",
        "id_number": _VALID_ID, "destination_passport": "美国/护照", "category": "01",
        "travel_dates": "2026/09/01-2026/09/11", "need_new_passport": "是",
        "approval_date": "20260701", "intended_cert_type": "01",
        "passport_no": "E99999999",
    }, follow_redirects=True)
    assert _travel_passport_no(2) == "E99999999"


def test_voided_issuance_keeps_last_number(c):
    """领用记录全部作废时不清空号码——那仍是当时用的号码，清掉就什么都不剩了。"""
    _issue(c)
    c.post("/issuance/1/void", data={"csrf_token": _tok(c), "void_reason": "登记错误"},
           follow_redirects=True)
    assert _travel_passport_no() == "E12345678"


# ---------------------------------------------------------------------------
# B3 「是否做证」与实际持证一致
# ---------------------------------------------------------------------------
def _new_travel(cl, pfid, name, need, cert_type="01"):
    """路径A 须传《个人申请报告》《审批表》，路径B 另须《同意申办函》。"""
    data = {
        "csrf_token": _tok(cl), "personnel_filing_id": str(pfid), "unit": "总部",
        "department": "技术部", "name": name, "position": "科长",
        "id_number": _VALID_ID, "destination_passport": "美国/护照", "category": "01",
        "travel_dates": "2026/10/01-2026/10/11", "need_new_passport": need,
        "approval_date": "20260701", "intended_cert_type": cert_type,
        "att_application": (io.BytesIO(b"%PDF-1.4 x"), "a.pdf"),
        "att_approval": (io.BytesIO(b"%PDF-1.4 x"), "b.pdf"),
    }
    if need == "是":
        data["att_consent"] = (io.BytesIO(b"%PDF-1.4 x"), "c.pdf")
    return cl.post("/travel/new", data=data,
                   content_type="multipart/form-data", follow_redirects=True)


def test_no_cert_must_make_one(c):
    """一本可用的证都没有却说不做证——这条记录本身就是错的。"""
    r = _new_travel(c, 2, "无证李四", "否")
    assert "没有在有效期内的普通护照" in r.get_data(as_text=True)


def test_no_cert_with_make_one_is_ok(c):
    r = _new_travel(c, 2, "无证李四", "是")
    assert "已保存" in r.get_data(as_text=True)


def test_expired_cert_counts_as_none(c):
    """过期护照等于没有——「有证」必须算有效期。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE certificates SET passport_expiry='20200101' WHERE personnel_filing_id=1")
    db.commit(); db.close()
    r = _new_travel(c, 1, "有证张三", "否")
    assert "没有在有效期内的普通护照" in r.get_data(as_text=True)


def test_valid_cert_allows_no_new_passport(c):
    r = _new_travel(c, 1, "有证张三", "否")
    assert "已保存" in r.get_data(as_text=True)


def _only_hm_pass():
    """把 1 号人改成「只有港澳通行证，没有护照」。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE certificates SET passport_no=NULL, passport_expiry=NULL, "
               "hm_pass_no='C87654321', hm_pass_expiry='20351231', "
               "hm_pass_submit_date='20250101' WHERE personnel_filing_id=1")
    db.commit(); db.close()


def test_holding_the_wrong_kind_is_now_caught(c):
    """只有港澳通行证，却说这趟用护照且不做证——现在判得出来了。

    这条用例原来钉的是相反的结论：「系统判不了够不够用，只判一本都没有」，
    理由是明细表上没有证件种类栏。第 7 批加了「拟用证件种类」这个结构化字段，
    那个理由随之消失，判据可以精确到**那一本**。
    """
    _only_hm_pass()
    r = _new_travel(c, 1, "有证张三", "否", cert_type="01")
    body = r.get_data(as_text=True)
    assert "没有在有效期内的普通护照" in body, body[:400]
    assert "已保存" not in body


def test_holding_the_right_kind_still_passes(c):
    """同一个人，改说这趟用港澳通行证——他确实有，放行。

    没有这条对照，上面那条用「一律拦死」也能变绿。
    """
    _only_hm_pass()
    r = _new_travel(c, 1, "有证张三", "否", cert_type="02")
    assert "已保存" in r.get_data(as_text=True)

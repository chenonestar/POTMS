"""跨表引用守卫（第 4 批）：撤控前置清障、证照删除守卫、申请人锁定。

三条都在防同一件事：**改/删一张表，悄悄改变了另一张表的含义**。

- 撤控：撤控表上「证件移交日期」这一栏本身就说明业务上要先收缴证件，但代码不查，
  于是可以「带证走人」——人撤控了，逾期告警还挂在首页，而这个人已经不在管理范围内，
  那条告警谁也处理不掉。
- 删证照：号码一旦从台账消失，路径B 那条出行**当场变回「逾期未交回」**（判据就是
  「号码在不在台账里」）；已签字的领用凭证上印着这个号，台账里却查无此证。
- 改申请人：领用记录上有本人手写签名，签的是「我为这次申请领了这本证」。事后把申请
  改挂到别人名下，那张凭证就指向了另一个人——这正是这套签名要防的事。
"""
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
    """一个人（#1）有护照、有一条已批准的出行；另一个人（#2）做证出去了还没交回。"""
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()

    db = sqlite3.connect(Config.DATABASE)
    for pid, nm in ((1, "路径A张三"), (2, "路径B李四")):
        db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
                   "id_number,residence,political_status,work_unit,position_or_title,"
                   "supervisor_unit,operator) VALUES (?,?,'','男','19900101',?,"
                   "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')",
                   (pid, nm, valid_id(pid)))
    db.execute("INSERT INTO certificates (id,personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (1,1,'总部','技术部','路径A张三','E12345678','20351231','20250101','admin')")
    # 出行 1：路径A，已批准，尚未领用
    db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
               "position,id_number,destination_passport,category,travel_dates,travel_start,"
               "travel_end,need_new_passport,operator) VALUES "
               "(1,1,'总部','技术部','路径A张三','科长',?,'美国/护照','01',"
               "'2026/03/01-2026/03/10','20260301','20260310','否','admin')", (_VALID_ID,))
    # 出行 2：路径B，做证出去了，号码还没补录（＝还没交回入库）
    db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
               "position,id_number,destination_passport,category,travel_dates,travel_start,"
               "travel_end,need_new_passport,operator) VALUES "
               "(2,2,'总部','技术部','路径B李四','科长',?,'美国/护照','01',"
               "'2026/03/01-2026/03/10','20260301','20260310','是','admin')", (_VALID_ID,))
    # 出行 1 按路径B 备齐三件。它本身是路径A，多一件《同意申办函》无害；
    # 而下面「换申请人」的用例必须同时把「是否做证」改成是（2 号名下没有证，
    # 选否会被「没有可用证件」那条校验挡下），换路径之后这一件就成了必传项。
    seed_required_attachments(db, 1, "是")
    seed_required_attachments(db, 2, "是")
    db.commit(); db.close()

    from app import create_app
    cl = create_app().test_client()
    tok = _CSRF.search(cl.get("/login").get_data(as_text=True)).group(1)
    cl.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return cl


def _tok(cl):
    return _CSRF.search(cl.get("/").get_data(as_text=True)).group(1)


def _scalar(sql, args=()):
    db = sqlite3.connect(Config.DATABASE)
    v = db.execute(sql, args).fetchone()
    db.close()
    return v[0] if v else None


def _issue(cl, travel_id=1, pfid=1, name="路径A张三"):
    """给某条出行登记一条带签名的领用记录。"""
    r = cl.post("/issuance/new", data={
        "csrf_token": _tok(cl), "travel_id": str(travel_id),
        "personnel_filing_id": str(pfid), "holder_name": name, "id_number": _VALID_ID,
        "cert_types": "01", "cert_nos": "E12345678", "issue_date": "20260225",
        "sign_png": _PNG}, follow_redirects=True)
    assert _scalar("SELECT COUNT(*) FROM cert_issuance WHERE travel_id=?", (travel_id,)) == 1, \
        f"领用登记没成功：{r.get_data(as_text=True)[:400]}"


# ---------------------------------------------------------------------------
# A1 撤控前置清障
# ---------------------------------------------------------------------------
def _decontrol_form(cl, filing_id=1, **over):
    data = {
        "csrf_token": _tok(cl), "surname": "路径A", "given_name": "张三", "gender": "男",
        "birth_date": "19900101", "id_number": _VALID_ID, "residence": "浙江宁波市鄞州区",
        "political_status": "群众", "work_unit": "总部", "supervisor_unit": "人事处",
        "submit_unit_name": "某某国资委", "submit_unit_type": "01",
        "submit_contact": "王五", "submit_phone": "13800000000",
        "batch_no": "2026-01", "reason": "调离本单位",
        "decontrol_date": "20260301", "cert_handover_date": "20260301",
    }
    data.update(over)
    return cl.post(f"/decontrol/new/{filing_id}", data=data, follow_redirects=True)


def test_cannot_decontrol_with_unreturned_issuance(c):
    """路径A：证还在本人手上（已领未还），不许撤控。

    撤控完了那条逾期告警还挂在首页，而这个人已经不在管理范围内，谁也处理不掉。
    """
    _issue(c)
    html = _decontrol_form(c).get_data(as_text=True)
    assert "未归还的证件领用记录" in html
    assert _scalar("SELECT COUNT(*) FROM decontrol_filing") == 0
    assert _scalar("SELECT status FROM personnel_filing WHERE id=1") == "active"


def test_cannot_decontrol_with_uncollected_new_cert(c):
    """路径B：做证出去了，新证还没进台账，同样不许撤控。"""
    html = _decontrol_form(c, filing_id=2, surname="路径B", given_name="李四"
                           ).get_data(as_text=True)
    assert "尚未交回入库的证件" in html
    assert _scalar("SELECT COUNT(*) FROM decontrol_filing") == 0


def test_decontrol_allowed_once_certs_settled(c):
    """证清干净了就该放行——守卫不能把正常的撤控也挡住。"""
    assert _decontrol_form(c).status_code == 200
    assert _scalar("SELECT COUNT(*) FROM decontrol_filing") == 1
    assert _scalar("SELECT status FROM personnel_filing WHERE id=1") == "decontrolled"


def test_decontrol_blocked_before_filling_the_form(c):
    """拦截要发生在进表单之前——让人填完一整张表再说不行，是最没必要的为难。"""
    _issue(c)
    html = c.get("/decontrol/new/1", follow_redirects=True).get_data(as_text=True)
    assert "未归还的证件领用记录" in html
    assert "撤控原因" not in html, "被拦下了却还是把表单渲染了出来"


def test_handover_date_is_required(c):
    """撤控以证件收缴完毕为前提，移交日期是这件事发生过的凭据。"""
    html = _decontrol_form(c, cert_handover_date="").get_data(as_text=True)
    assert "证件移交日期" in html and "必填" in html
    assert _scalar("SELECT COUNT(*) FROM decontrol_filing") == 0


# ---------------------------------------------------------------------------
# A2 证照删除守卫
# ---------------------------------------------------------------------------
def test_cannot_delete_cert_referenced_by_issuance(c):
    """已签字的领用凭证上印着这个号码，台账里不能查无此证。"""
    _issue(c)
    html = c.post("/certificate/1/delete", data={"csrf_token": _tok(c)},
                  follow_redirects=True).get_data(as_text=True)
    assert "证件领用记录引用" in html
    assert _scalar("SELECT COUNT(*) FROM certificates WHERE id=1") == 1


def test_cannot_delete_cert_referenced_by_travel(c):
    """出行表上补录的做证号码一旦在台账里找不到，那条出行当场变回「逾期未交回」。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE travel_details SET passport_no='E12345678' WHERE id=2")
    db.commit(); db.close()

    html = c.post("/certificate/1/delete", data={"csrf_token": _tok(c)},
                  follow_redirects=True).get_data(as_text=True)
    assert "出国申请引用" in html
    assert _scalar("SELECT COUNT(*) FROM certificates WHERE id=1") == 1


def test_unreferenced_cert_can_still_be_deleted(c):
    """录错了、重复录的证照仍要能删——守卫不能把这条路也堵死。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO certificates (id,personnel_filing_id,unit,department,name,"
               "hm_pass_no,hm_pass_expiry,hm_pass_submit_date,operator) "
               "VALUES (9,2,'总部','技术部','路径B李四','C00000009','20351231','20250101','admin')")
    db.commit(); db.close()

    c.post("/certificate/9/delete", data={"csrf_token": _tok(c)}, follow_redirects=True)
    assert _scalar("SELECT COUNT(*) FROM certificates WHERE id=9") == 0


# ---------------------------------------------------------------------------
# A3 申请人锁定
# ---------------------------------------------------------------------------
def _edit_travel(cl, travel_id=1, **over):
    data = {
        "csrf_token": _tok(cl), "personnel_filing_id": "1", "unit": "总部",
        "department": "技术部", "name": "路径A张三", "position": "科长",
        "id_number": _VALID_ID, "destination_passport": "美国/护照", "category": "01",
        "travel_dates": "2026/03/01-2026/03/10", "need_new_passport": "否",
        "approval_date": "20260201", "intended_cert_type": "01",
    }
    data.update(over)
    return cl.post(f"/travel/{travel_id}/edit", data=data, follow_redirects=True)


def test_applicant_locked_once_issued(c):
    """有领用记录时，表单上不再给可改的申请人控件。"""
    _issue(c)
    html = c.get("/travel/1/edit").get_data(as_text=True)
    assert 'name="personnel_filing_id"' not in html, "已有领用记录，申请人仍可改"
    assert "已锁定" in html


# 换到 2 号名下时必须同时把「是否做证」改成「是」：2 号名下一本证都没有，
# 否则会先被第 2 批的做证校验挡下，这条用例就测不到锁定本身了。
_SWAP_TO_2 = {"personnel_filing_id": "2", "name": "路径B李四", "need_new_passport": "是"}


def test_applicant_cannot_be_swapped_by_forged_post(c):
    """绕过界面直接提交也换不掉人——只读字段照样会随表单提交，伪造的 POST 更是想填什么填什么。"""
    _issue(c)
    _edit_travel(c, **_SWAP_TO_2)
    assert _scalar("SELECT personnel_filing_id FROM travel_details WHERE id=1") == 1, \
        "签了字的领用凭证被改挂到了另一个人名下"


def test_applicant_still_editable_without_issuance(c):
    """没有领用记录的申请仍可改人——锁定只在有凭证时生效。"""
    html = c.get("/travel/1/edit").get_data(as_text=True)
    assert 'name="personnel_filing_id"' in html
    r = _edit_travel(c, **_SWAP_TO_2)
    assert _scalar("SELECT personnel_filing_id FROM travel_details WHERE id=1") == 2, \
        f"没有领用记录却改不动申请人：{r.get_data(as_text=True)[:400]}"

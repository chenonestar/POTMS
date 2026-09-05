"""第 9 批：领用登记的证件号码不能留空。

手工点系统时报出来的：「是否做证=否、证件号码没填，领用登记也没填号码，
居然领证成功了」。实测复现，而且后果比「少了一格信息」严重得多——

    在库 = 1 | 借出未还 = 0 | 孤儿号码 = []

那本证已经在人手上，系统仍把它算作「在库」。certificate.lent_out_numbers()
是按号码收集借出集合的，空号码直接被滤掉；stock_split() 的文档字符串写着
「在库这个数能真的拿去和柜子里的实体证核对」——这条记录让那句话不成立。
而且是**无声的**：四档恒等式「在库 + 借出未还 = 台账总本数」依然平，
orphan_numbers 也是空的，一处都不喊。同时失效的还有号码级跨申请查重
（同一本证可以被两个人同时领走）和 _sync_travel_derived 的号码回写。

**根因是前端。** 号码框写着「按所选种类自动带入」，syncCertNos() 也确实能
拿到号码（人员下拉上挂着 data-cert01="E1"），可它只挂在 change 事件上；
而证件种类是第 7 批加的服务端预选——经办人没有理由再去点一下那个已经
选中的单选钮，于是号码框一直空着，**看上去却像填好了**。第 7 批那个
「按申请预选种类」的改进，恰恰把唯一会触发自动带入的动作给省掉了。

所以三层一起补，缺一层都不算修好：

    服务端预填   GET 时就把号码带出来，不只靠 JS
    前端         DOMContentLoaded 也带一次（已有值不覆盖）
    后端校验     cert_nos 加进必填 —— 前两层都是入口，伪造 POST 照样绕过去

第三层不能省，而绕过去的代价是柜子里的账错了却没人知道。
"""
import io
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

from config import Config
from conftest import valid_id

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_PNG = __import__("tests.test_issuance", fromlist=["_PNG_DATA_URL"])._PNG_DATA_URL
_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\ntrailer\n<<>>\n%%EOF\n"


def _today():
    return datetime.now().strftime("%Y%m%d")


def _shift(n):
    return (datetime.now() + timedelta(days=n)).strftime("%Y%m%d")


def _range(a, b):
    def f(n):
        s = _shift(n)
        return f"{s[:4]}/{s[4:6]}/{s[6:]}"
    return f"{f(a)}-{f(b)}"


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()
    return sqlite3.connect(Config.DATABASE)


def _client():
    from app import create_app
    cl = create_app().test_client()
    tok = _CSRF.search(cl.get("/login").get_data(as_text=True)).group(1)
    cl.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return cl


def _tok(cl):
    return _CSRF.search(cl.get("/").get_data(as_text=True)).group(1)


def _one(sql, *params):
    db = sqlite3.connect(Config.DATABASE)
    row = db.execute(sql, params).fetchone()
    db.close()
    return row[0] if row else None


@pytest.fixture()
def cl(tmp_path, monkeypatch):
    """一个在控人员，台账上一本长期有效的护照 E1，一条已批准的出国申请。"""
    db = _fresh(tmp_path, monkeypatch)
    db.execute(
        "INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,"
        "residence,political_status,work_unit,position_or_title,supervisor_unit,status,operator) "
        "VALUES (1,'甲','一','男','19900101',?,'浙江宁波市鄞州区','群众','总部','科长','人事处',"
        "'active','admin')", (valid_id(1),))
    db.execute(
        "INSERT INTO certificates (personnel_filing_id,unit,department,name,passport_no,"
        "passport_expiry,passport_submit_date,operator) "
        "VALUES (1,'总部','技术部','甲一','E1','20351231','20250101','admin')")
    db.execute(
        "INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
        "id_number,destination_passport,intended_cert_type,category,travel_dates,travel_start,"
        "travel_end,approval_date,need_new_passport,operator) "
        "VALUES (1,1,'总部','技术部','甲一','科长',?,'美国','01','01',?,?,?,?,'否','admin')",
        (valid_id(1), _range(60, 70), _shift(60), _shift(70), _shift(-30)))
    from conftest import seed_required_attachments
    seed_required_attachments(db, 1, "否")
    db.commit(); db.close()
    return _client()


def _issue(cl, **over):
    d = {"csrf_token": _tok(cl), "travel_id": "1", "personnel_filing_id": "1",
         "holder_name": "甲一", "id_number": valid_id(1), "cert_types": "01",
         "cert_nos": "E1", "issue_date": _today(), "sign_png": _PNG, "sign_meta": "{}"}
    d.update(over)
    return cl.post("/issuance/new", data=d, follow_redirects=True)


# ===========================================================================
# 一、后端：空号码办不成领用
# ===========================================================================
def test_an_issuance_without_a_number_is_refused(cl):
    """空号码直接挡回。这是三层里唯一伪造 POST 也绕不过去的一层。"""
    r = _issue(cl, cert_nos="")
    assert "证件号码" in r.get_data(as_text=True)
    assert _one("SELECT COUNT(*) FROM cert_issuance") == 0


def test_a_whitespace_only_number_is_refused(cl):
    """只敲了几个空格也不算填了——_extract_form 会 strip，剩下空串。"""
    r = _issue(cl, cert_nos="   ")
    assert "证件号码" in r.get_data(as_text=True)
    assert _one("SELECT COUNT(*) FROM cert_issuance") == 0


def test_a_normal_issuance_still_goes_through(cl):
    """反向对照：号码填了就正常登记，别把必填改成了谁也过不去。"""
    _issue(cl)
    assert _one("SELECT cert_nos FROM cert_issuance") == "E1"
    assert _one("SELECT status FROM cert_issuance") == "issued"


# ===========================================================================
# 二、这条必填到底在保护什么：账要对得上柜子
# ===========================================================================
def _stock():
    """(在库本数, 借出未还本数, 孤儿号码)。"""
    from app import create_app
    with create_app().app_context():
        from blueprints.certificate import stock_split
        ins, lent, orphan = stock_split()
        return len(ins), len(lent), orphan


def test_a_lent_out_certificate_is_no_longer_counted_as_in_stock(cl):
    """办完领用，那本证从「在库」转到「借出未还」。

    这条用例才是上面那条必填的理由。空号码时实测是「在库 1 / 借出 0」——
    证在人手上，账上却还在柜子里，而且四档恒等式照样平、孤儿号码也是空的，
    没有任何一处会喊。
    """
    assert _stock() == (1, 0, [])          # 领用之前：一本在库
    _issue(cl)
    assert _stock() == (0, 1, [])          # 领用之后：转到借出未还


def test_the_number_is_written_back_to_the_travel_record(cl):
    """号码回写到出行记录上——_sync_travel_derived 的 cert_nos != '' 过滤
    会把空号码整条跳过，那一栏就一直空着。"""
    _issue(cl)
    assert _one("SELECT passport_no FROM travel_details WHERE id=1") == "E1"


def test_the_same_certificate_cannot_be_lent_to_two_people(cl):
    """号码级跨申请查重要真的生效。

    空号码时 `if no:` 直接跳过这段，同一本实体证可以同时挂在两张都签了字的
    未归还领用单上——归还时该销哪一张都说不清。
    """
    db = sqlite3.connect(Config.DATABASE)
    db.execute(
        "INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,"
        "residence,political_status,work_unit,position_or_title,supervisor_unit,status,operator) "
        "VALUES (2,'乙','二','男','19900101',?,'浙江宁波市鄞州区','群众','总部','科长','人事处',"
        "'active','admin')", (valid_id(2),))
    db.execute(
        "INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
        "id_number,destination_passport,intended_cert_type,category,travel_dates,travel_start,"
        "travel_end,approval_date,need_new_passport,operator) "
        "VALUES (2,2,'总部','技术部','乙二','科长',?,'日本','01','01',?,?,?,?,'否','admin')",
        (valid_id(2), _range(60, 70), _shift(60), _shift(70), _shift(-30)))
    db.commit(); db.close()

    _issue(cl)                                     # 甲一先领走 E1
    r = _issue(cl, travel_id="2", personnel_filing_id="2",
               holder_name="乙二", id_number=valid_id(2), cert_nos="E1")
    body = r.get_data(as_text=True)
    assert "已由" in body and "尚未归还" in body
    assert _one("SELECT COUNT(*) FROM cert_issuance") == 1


# ===========================================================================
# 三、入口：号码要自己出现在框里，不能等人去点
# ===========================================================================
def test_the_server_prefills_the_number_from_the_ledger(cl):
    """页面刚打开时号码框里就有值——这是根因所在。

    此前这里是 value=""：种类由服务端预选，change 事件永远不触发，
    syncCertNos() 一次都不跑。号码就在人员下拉的 data-cert01 里躺着，
    却没有任何东西把它搬进框子。
    """
    html = cl.get("/issuance/new?travel_id=1").get_data(as_text=True)
    box = re.search(r'<input[^>]*name="cert_nos"[^>]*>', html)
    assert box, "找不到证件号码输入框"
    assert 'value="E1"' in box.group(0), f"号码没有预填：{box.group(0)}"
    assert "required" in box.group(0), "号码输入框没有 required"


def test_the_form_marks_the_number_as_required(cl):
    """表单上要有那个星号——校验拦得住，但让人填完整张表再打回是白为难。"""
    html = cl.get("/issuance/new?travel_id=1").get_data(as_text=True)
    label = re.search(r'<label[^>]*>证件号码[^<]*(?:<span[^>]*>[^<]*</span>)?\s*</label>', html)
    assert label, "表单上找不到「证件号码」这一栏"
    assert "required" in label.group(0), f"证件号码没有标 *：{label.group(0)}"


def test_the_client_side_fill_does_not_clobber_a_server_prefill(cl):
    """页面加载时的那次自动带入必须让位给服务端已经填好的值。

    路径B 的新证还没进台账，data-cert0X 里查不到，服务端是从出行记录上的
    passport_no 带出来的。加载时无条件调 syncCertNos() 会把它清成空串——
    修一个 bug 顺手造一个。所以那一行是 `if (!nosEl.value) syncCertNos();`。
    """
    js = cl.get("/issuance/new?travel_id=1").get_data(as_text=True)
    assert "if (!nosEl.value) syncCertNos();" in js, \
        "加载时的自动带入没有守住「已有值不覆盖」"


def test_path_b_number_comes_from_the_travel_record(cl):
    """路径B：新证不在台账里，号码从出行记录上带出来。

    台账优先、出行记录兜底——这两个来源缺一不可：路径A 的权威来源是台账
    （出行记录上那一栏是派生的），路径B 台账里压根没有那本证。
    """
    db = sqlite3.connect(Config.DATABASE)
    db.execute(
        "INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
        "id_number,destination_passport,intended_cert_type,category,travel_dates,travel_start,"
        "travel_end,approval_date,need_new_passport,passport_no,operator) "
        "VALUES (3,1,'总部','技术部','甲一','科长',?,'德国','02','01',?,?,?,?,'是','C-NEW','admin')",
        (valid_id(1), _range(60, 70), _shift(60), _shift(70), _shift(-30)))
    db.commit(); db.close()
    html = cl.get("/issuance/new?travel_id=3").get_data(as_text=True)
    box = re.search(r'<input[^>]*name="cert_nos"[^>]*>', html)
    assert 'value="C-NEW"' in box.group(0), f"路径B 的号码没带出来：{box.group(0)}"


def test_the_ledger_wins_over_the_travel_record(cl):
    """两个来源都有值时以台账为准。

    出行记录上那一栏是派生字段（由领用记录回写），台账才是证照的权威登记。
    顺序写反了就会拿一个陈旧的派生值去覆盖权威值。
    """
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE travel_details SET passport_no='STALE' WHERE id=1")
    db.commit(); db.close()
    html = cl.get("/issuance/new?travel_id=1").get_data(as_text=True)
    box = re.search(r'<input[^>]*name="cert_nos"[^>]*>', html)
    assert 'value="E1"' in box.group(0), f"没有以台账为准：{box.group(0)}"

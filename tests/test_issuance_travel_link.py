"""领用必须挂在出国申请上，以及路径B（做证）的逾期告警。

两条规则同源：证件是为某一次已批准的出行借出/办理的。
- 挂不上申请的领用记录是无主的，还会掉出逾期告警（告警按出行记录算）；
- 路径B 压根没有领用记录（证是本人凭函去公安办的，从没进过保管处），
  原来的告警判据「passport_collect_date 非空」对它恒不成立，整类人不受监管。
"""
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

from config import Config

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = "110101199001012133"
_PNG = __import__("tests.test_issuance", fromlist=["_PNG_DATA_URL"])._PNG_DATA_URL


def _long_ago(days=90):
    return (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")


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
    for pid, nm in ((1, "路径A张三"), (2, "路径B李四")):
        db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
                   "id_number,residence,political_status,work_unit,position_or_title,"
                   "supervisor_unit,operator) VALUES (?,?,'','男','19900101',?,'北京','群众',"
                   "'总部','科长','人事处','admin')", (pid, nm, _VALID_ID))
    db.execute("INSERT INTO certificates (personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (1,'总部','技术部','路径A张三','E12345678','20301231','20250101','admin')")
    ago = _long_ago()
    # 两条出行申请：都回国 90 天，证都没交回。区别只在是否做证。
    for tid, pid, nm, mk in ((1, 1, "路径A张三", "否"), (2, 2, "路径B李四", "是")):
        db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
                   "position,id_number,destination_passport,category,travel_dates,travel_end,"
                   "need_new_passport,actual_return_date,operator) VALUES "
                   "(?,?,'总部','技术部',?,'科长',?,'美国/护照','01',?,?,?,?,'admin')",
                   (tid, pid, nm, _VALID_ID, f"{ago}-{ago}", ago, mk, ago))
    db.commit(); db.close()
    from app import create_app
    cl = create_app().test_client()
    tok = _CSRF.search(cl.get("/login").get_data(as_text=True)).group(1)
    cl.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return cl


def _tok(cl):
    return _CSRF.search(cl.get("/").get_data(as_text=True)).group(1)


def _post_issue(cl, **over):
    data = {"csrf_token": _tok(cl), "travel_id": "1", "personnel_filing_id": "1",
            "holder_name": "路径A张三", "id_number": _VALID_ID, "cert_types": "01",
            "cert_nos": "E12345678", "issue_date": _long_ago(), "sign_png": _PNG}
    data.update(over)
    return cl.post("/issuance/new", data=data, follow_redirects=True)


def _count_issuance():
    db = sqlite3.connect(Config.DATABASE)
    n = db.execute("SELECT COUNT(*) FROM cert_issuance").fetchone()[0]
    db.close()
    return n


# ---------------------------------------------------------------------------
# A1 领用必须挂出国申请
# ---------------------------------------------------------------------------
def test_issue_without_travel_is_rejected(c):
    """不挂申请的领用记录是无主的，还会掉出逾期告警——必须挡回。"""
    r = _post_issue(c, travel_id="")
    assert "关联出国申请" in r.get_data(as_text=True)
    assert _count_issuance() == 0


def test_issue_with_unknown_travel_is_rejected(c):
    r = _post_issue(c, travel_id="999")
    assert "关联的出国申请不存在" in r.get_data(as_text=True)
    assert _count_issuance() == 0


def test_holder_must_match_applicant(c):
    """证是为这条申请借的，不能借给别人。"""
    r = _post_issue(c, personnel_filing_id="2", holder_name="路径B李四")
    assert "与该出国申请的申请人不一致" in r.get_data(as_text=True)
    assert _count_issuance() == 0


def test_cancelled_trip_cannot_issue(c):
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE travel_details SET trip_status='cancelled' WHERE id=1")
    db.commit(); db.close()
    r = _post_issue(c)
    assert "已取消行程" in r.get_data(as_text=True)
    assert _count_issuance() == 0


def test_new_without_travel_id_shows_picker(c):
    """直接进新建页时先选申请，而不是给一个能不填的表单。"""
    html = c.get("/issuance/new").get_data(as_text=True)
    assert "选择出国申请" in html
    assert "登记领用" in html
    assert "路径A张三" in html


def test_picker_excludes_cancelled_and_active_issuance(c):
    """已取消的行程、以及已有未归还领用的申请，不该出现在可选列表里。"""
    _post_issue(c)                       # 申请 1 现在有一条未归还记录
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE travel_details SET trip_status='cancelled' WHERE id=2")
    db.commit(); db.close()
    html = c.get("/issuance/new").get_data(as_text=True)
    assert "路径A张三" not in html       # 有未归还记录
    assert "路径B李四" not in html       # 已取消
    assert "没有可办理领用的出国申请" in html


def test_one_cert_per_application(c):
    """一次申请一本证；要多本就分多条申请。"""
    r = _post_issue(c, cert_types=["01", "02"])
    assert "只能领用一本证件" in r.get_data(as_text=True)
    assert _count_issuance() == 0


# ---------------------------------------------------------------------------
# A2 路径B 的逾期告警
# ---------------------------------------------------------------------------
def _overdue():
    from app import create_app
    app = create_app()
    with app.app_context(), app.test_request_context():
        from blueprints.travel import _overdue_ids
        return _overdue_ids()


def test_path_b_without_registered_cert_is_overdue(c):
    """路径B 回国 90 天、证没交回，必须被抓到。

    原实现判据是 passport_collect_date 非空，而它由领用记录派生；
    路径B 没有领用记录，这一整类人一条都抓不到。
    """
    _post_issue(c)                       # 路径A 也造一条未归还的，作对照
    assert _overdue() == {1, 2}


def test_path_b_cleared_once_cert_registered(c):
    """证交回入库、登记进台账之后就不该再告警。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE travel_details SET passport_no='E99999999' WHERE id=2")
    db.execute("INSERT INTO certificates (personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (2,'总部','技术部','路径B李四','E99999999','20360101',?,'admin')",
               (_long_ago(1),))
    db.commit(); db.close()
    assert 2 not in _overdue()


def test_path_b_number_recorded_but_not_registered_still_overdue(c):
    """只在明细表补录了号码、没进台账，仍然算没交回。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE travel_details SET passport_no='E99999999' WHERE id=2")
    db.commit(); db.close()
    assert 2 in _overdue()


def test_path_b_not_overdue_before_deadline(c):
    """还没到期的不报——10 个工作日的口径沿用原算法。"""
    db = sqlite3.connect(Config.DATABASE)
    today = datetime.now().strftime("%Y%m%d")
    db.execute("UPDATE travel_details SET actual_return_date=?, travel_end=? WHERE id=2",
               (today, today))
    db.commit(); db.close()
    assert 2 not in _overdue()


def test_path_b_shows_on_dashboard(c):
    """仪表盘的逾期清单也要带上路径B，否则首页看不到这类漏管。

    不能只断言姓名出现在页面上——「近期出行」板块本来就会列出这个人，
    那样即使逾期统计完全失灵也照样通过。这里查逾期计数本身。
    """
    from app import create_app
    app = create_app()
    with app.app_context(), app.test_request_context():
        from blueprints.dashboard import index
        index()   # 触发一次，确认不抛异常
    html = c.get("/").get_data(as_text=True)
    # 逾期卡片上的数字：路径A 未领用，所以此刻只有路径B 一条
    assert re.search(r'text-danger">\s*1\s*</div>', html), "仪表盘逾期计数没算上路径B"


# ---------------------------------------------------------------------------
# 逾期分支的页面渲染
# ---------------------------------------------------------------------------
def test_travel_list_renders_overdue_branch(c):
    """出国明细列表的「逾期未还」提示块要真能渲染，且应还到期日不为空。

    五版里这个分支此前只有函数级覆盖（_overdue_ids），没有一条走到页面渲染。
    代价是 Go 版带着一个到 2026-08-26 才引爆的故障——gonja 索引不了整数键的 map，
    模板里 deadlines[row.id] 一旦真有人逾期就渲染失败、整页 500；Rust 版同一处
    静默渲染成空，页面上是「应还: )」。本版的 deadlines 是真字典、键是 int，
    Jinja2 取得到，但同样得有用例钉住。
    """
    _post_issue(c)                                     # 路径A：已领未还且已逾期
    html = c.get("/travel/").get_data(as_text=True)
    assert "逾期" in html
    assert "路径A张三" in html

    # 「应还」两个字在模板里是死的，光查它不够——必须确认后面真跟着日期
    i = html.index("应还")
    after = html[i + 2:].lstrip(" :：")
    assert after[:8].isdigit(), f"应还到期日为空，实际渲染：「应还{after[:40]}」"


def test_travel_list_overdue_filter_renders(c):
    """按逾期筛选也要能筛出来并正常渲染。"""
    _post_issue(c)
    html = c.get("/travel/?passport_status=overdue").get_data(as_text=True)
    assert "路径A张三" in html
    assert "路径B李四" in html          # 做证未交回，同样应计入

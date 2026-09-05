"""第 8 批：日期之间的先后关系。

这套系统里有七八个日期，此前的校验只管每个日期**自己**合不合法（是不是
YYYYMMDD、是不是真实存在的日子），跨字段的先后关系是零散补上的——补过
「计划出行起 ≤ 止」、「归还 ≥ 领用」、「领用 ≤ 实际回国」、「移交 ≤ 撤控 ≤ 今天」，
每一条都是被具体问题逼出来的，从没有人把整条链摆出来看一遍。

摆出来之后，剩下五个缺口一次补齐：

    批准日期 ≤ 今天             《审批表》是必传附件，那张签好字的纸此刻就在手上
    批准日期 ≤ 计划出行开始日     先批准后出行
    实际回国日期 ≥ 计划出行开始日  人不可能在出发之前就回国
    领用日期 ≤ 今天              领用单上有本人手写签名，签字那一刻已经发生
    领用日期 ≥ 该申请的批准日期    证是为已批准的出行借出的

前三条是纸面事实，第四条是签名凭证的性质，只有第五条是程序规则——它现实中
做得出来，只是不该做。管住这个程序正是这套系统存在的理由，所以同样硬拦
（与「领用日期 ≤ 实际回国日期」那条物理不可能的区别，见 issuance 里的注释）。

**「不合法的日期不参与比较」单独测一条。** YYYYMMDD 定长，字符串比较等于
日期比较——前提是两边都真是 YYYYMMDD。`'2026131' > '20261101'` 在 Python 里
是 False，比出来的结果毫无意义却会被当成通过。这就是 comparable_ymd 存在的
理由，也是它为什么只决定「要不要比」、不重复报格式错。
"""
import io
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

from config import Config
from conftest import seed_required_attachments, valid_id

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_PNG = __import__("tests.test_issuance", fromlist=["_PNG_DATA_URL"])._PNG_DATA_URL
_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\ntrailer\n<<>>\n%%EOF\n"


def _today():
    return datetime.now().strftime("%Y%m%d")


def _shift(n):
    return (datetime.now() + timedelta(days=n)).strftime("%Y%m%d")


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
    """一个在控人员，名下有一本长期有效的护照（「是否做证=否」的前提）。"""
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
    db.commit(); db.close()
    return _client()


def _travel_form(cl, **over):
    """一份各项都填对的明细表；出行在两个月后，批准日期是一个月前。"""
    start, end = _shift(60), _shift(70)
    d = {"csrf_token": _tok(cl), "personnel_filing_id": "1", "unit": "总部",
         "department": "技术部", "name": "甲一", "position": "科长",
         "id_number": valid_id(1), "destination_passport": "美国", "category": "01",
         "travel_dates": f"{start[:4]}/{start[4:6]}/{start[6:]}-{end[:4]}/{end[4:6]}/{end[6:]}",
         "need_new_passport": "否", "approval_date": _shift(-30), "intended_cert_type": "01",
         "att_application": (io.BytesIO(_PDF), "a.pdf"),
         "att_approval": (io.BytesIO(_PDF), "b.pdf")}
    d.update(over)
    return d


def _new_travel(cl, **over):
    return cl.post("/travel/new", data=_travel_form(cl, **over),
                   content_type="multipart/form-data", follow_redirects=True)


# ===========================================================================
# 一、明细表上的三条
# ===========================================================================
def test_a_correct_form_still_goes_through(cl):
    """反向对照：日期全填对时照常保存。

    每条拦截都得配一条放行用例，否则「一律拦死」也能让上面几条全绿。
    """
    _new_travel(cl)
    assert _one("SELECT COUNT(*) FROM travel_details") == 1
    assert _one("SELECT approval_date FROM travel_details") == _shift(-30)


def test_approval_date_cannot_be_in_the_future(cl):
    """批准日期填成将来 —— 《审批表》必须已经签好字上传，纸就在手上。"""
    r = _new_travel(cl, approval_date=_shift(400))
    body = r.get_data(as_text=True)
    assert "批准日期" in body and "将来" in body
    assert _one("SELECT COUNT(*) FROM travel_details") == 0


def test_approval_date_cannot_be_after_departure(cl):
    """批准日期晚于计划出行开始日 —— 先批准后出行。"""
    r = _new_travel(cl, approval_date=_shift(65))   # 出行 60~70 天后，批准落在中间
    body = r.get_data(as_text=True)
    assert "晚于计划出行开始日" in body
    assert _one("SELECT COUNT(*) FROM travel_details") == 0


def test_approval_on_the_departure_day_itself_is_allowed(cl):
    """边界：批准日期正好等于出行开始日，放行。

    判据是「晚于」不是「不早于」——当天批下来当天走，紧是紧了点，
    但它确实发生过，不能拿边界去误伤。

    出行日期得改成从今天起：另一条规则要求批准日期不能在将来，
    所以「批准日 = 出行开始日」这个边界只在出行开始日不晚于今天时才存在。
    第一版把出行留在 60 天后、批准日也写成 60 天后，两条规则互相打架，
    这条用例自己就是错的——被它自己红出来的。
    """
    start, end = _today(), _shift(10)
    _new_travel(cl, approval_date=start,
                travel_dates=f"{start[:4]}/{start[4:6]}/{start[6:]}-"
                             f"{end[:4]}/{end[4:6]}/{end[6:]}")
    assert _one("SELECT COUNT(*) FROM travel_details") == 1
    assert _one("SELECT approval_date FROM travel_details") == start


def test_return_date_cannot_precede_departure(cl):
    """实际回国日期早于计划出行开始日 —— 人不可能在出发之前就回国。"""
    r = _new_travel(cl, actual_return_date=_shift(10))   # 出行 60 天后
    body = r.get_data(as_text=True)
    assert "早于计划出行开始日" in body
    assert _one("SELECT COUNT(*) FROM travel_details") == 0


def test_a_malformed_date_does_not_add_a_second_confusing_error(cl):
    """格式非法的日期只报「格式」那一条，不再多报一条先后关系。

    这条是 comparable_ymd 的存在理由。没有它，'20261' 会一路走到字符串
    比较里去——比出来的真假毫无意义，而页面上会同时弹出「日期格式须为
    YYYYMMDD」和「批准日期晚于计划出行开始日」两条互不相干的提示，
    第二条纯属噪音，还会把人往错的方向引。
    """
    r = _new_travel(cl, approval_date="20261")
    body = r.get_data(as_text=True)
    assert "批准日期" in body                      # 格式那条要报
    assert "晚于计划出行开始日" not in body        # 先后那条不该报
    assert "将来的日期" not in body
    assert _one("SELECT COUNT(*) FROM travel_details") == 0


def test_the_edit_path_is_guarded_too(cl):
    """编辑保存同样拦得住。

    「新增守得住、编辑守不住」是本项目复盘出来的头号根因（出现四次）。
    _validate_form 是两条路径共用的，但共用这件事本身要有用例钉住——
    此前正是因为编辑路径另起一套校验才漏的。
    """
    _new_travel(cl)
    tid = _one("SELECT id FROM travel_details")
    d = _travel_form(cl, approval_date=_shift(400))
    d.pop("att_application"); d.pop("att_approval")     # 库里已有，不必重传
    r = cl.post(f"/travel/{tid}/edit", data=d,
                content_type="multipart/form-data", follow_redirects=True)
    assert "将来" in r.get_data(as_text=True)
    assert _one("SELECT approval_date FROM travel_details WHERE id=?", tid) == _shift(-30)


# ===========================================================================
# 二、领用登记上的两条
# ===========================================================================
def _issue(cl, travel_id=1, **over):
    d = {"csrf_token": _tok(cl), "travel_id": str(travel_id), "personnel_filing_id": "1",
         "holder_name": "甲一", "id_number": valid_id(1), "cert_types": "01",
         "cert_nos": "E1", "issue_date": _today(), "sign_png": _PNG, "sign_meta": "{}"}
    d.update(over)
    return cl.post("/issuance/new", data=d, follow_redirects=True)


@pytest.fixture()
def issued(cl):
    """一条已建好的出国申请（批准于 30 天前，出行在 60 天后）。"""
    _new_travel(cl)
    return cl


def test_a_normal_issuance_still_goes_through(issued):
    """反向对照：领用日期在批准之后、不晚于今天，照常登记。"""
    _issue(issued)
    assert _one("SELECT COUNT(*) FROM cert_issuance") == 1
    assert _one("SELECT issue_date FROM cert_issuance") == _today()


def test_issue_date_cannot_be_in_the_future(issued):
    """领用日期填成将来 —— 领用单上有本人手写签名，签字那一刻已经发生。"""
    r = _issue(issued, issue_date=_shift(400))
    assert "将来的日期" in r.get_data(as_text=True)
    assert _one("SELECT COUNT(*) FROM cert_issuance") == 0


def test_issue_date_cannot_precede_the_approval(issued):
    """领用日期早于该申请的批准日期 —— 审批没下来就把证发出去了。"""
    r = _issue(issued, issue_date=_shift(-90))     # 批准是 30 天前
    body = r.get_data(as_text=True)
    assert "早于该出国申请的批准日期" in body
    assert _one("SELECT COUNT(*) FROM cert_issuance") == 0


def test_issuing_on_the_approval_day_itself_is_allowed(issued):
    """边界：领用日期正好等于批准日期，放行——批下来当天就来领证是常态。"""
    _issue(issued, issue_date=_shift(-30))
    assert _one("SELECT COUNT(*) FROM cert_issuance") == 1


def test_back_dated_entry_between_approval_and_today_still_works(issued):
    """补录仍然办得成：领用日期落在「批准之后、今天之前」这段区间里。

    第 7 批刚把「行程已结束就不许再办领用」放宽成只挡物理不可能的那一种，
    理由是补录属于正当业务。新加的两条不能把那个口子又缩回去。
    """
    _issue(issued, issue_date=_shift(-10))
    assert _one("SELECT issue_date FROM cert_issuance") == _shift(-10)


def test_an_old_record_without_an_approval_date_is_not_blocked(cl):
    """存量申请批准日期为空时不比对——不能拿系统自己都没有的值去挡人。

    批准日期是第 4 批才改必填的，之前建的记录这一栏可能是空的。
    """
    db = sqlite3.connect(Config.DATABASE)
    start = _shift(60)
    db.execute(
        "INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
        "id_number,destination_passport,intended_cert_type,category,travel_dates,travel_start,"
        "travel_end,approval_date,need_new_passport,operator) "
        "VALUES (1,1,'总部','技术部','甲一','科长',?,'美国','01','01',?,?,?,'','否','admin')",
        (valid_id(1), f"{start}-{_shift(70)}", start, _shift(70)))
    from conftest import seed_required_attachments as _seed
    _seed(db, 1, "否")
    db.commit(); db.close()
    _issue(cl, issue_date=_shift(-500))
    assert _one("SELECT COUNT(*) FROM cert_issuance") == 1

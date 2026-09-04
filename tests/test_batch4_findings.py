"""第 4 批：必填与准入。

六条，两个主题。

**一、必填该不该必填，是有答案的，不能拍脑袋**

批准日期原为选填。需求文档 613 行说「审批通过后回填」——先建记录、批下来再补，
这个理由自洽；可同一份文档 634 行写的是相反的流程：「管理员根据《个人申请报告》
《审批表》等**线下已签批材料**填写明细表」。而代码实现的正是后者——《审批表》
一直在必传附件里，没有它连记录都建不出来。于是现状是：必须先有那张签好字的
审批表扫描件才能建记录，可它上面的日期却是选填的。两条规则不可能同时讲得通。

入库批号则相反：它是必填的，但**系统里根本没有这个字段的来源**——personnel_filing
上从没存过任何批号。一个必填、却既给不出来源也校不了对错的格子，只会逼人随便
敲一个数字进去，那比留空更糟：留空至少诚实地表示「不知道」。

**二、「办不了的事不给入口」这条，判据漏了两项**

领用准入此前只排除「行程已取消」和「同一申请已有未归还记录」。漏掉的两项：
行程已经结束、申请人已撤控。实测：一条 3 月走完、证也已归还的申请，9 月还能
凭它领出一本护照；一个已撤控的人，他的申请照样列在「可办理领用」里。

而「已完成的行程还能取消」这一条最险：cert_overdue_deadline() 的基准日会随
行程状态整个切换（正常＝实际回国+10 工作日，取消＝取消日+5 工作日）。对一条
早该还证、已在逾期告警里的记录点一下取消，应还日期会从几个月前跳到今天之后
——实测 20260403 → 20260911，**首页那条告警当场消失**。一次误点就够了。
"""
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

from config import Config
from conftest import seed_required_attachments, valid_id

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_PNG = __import__("tests.test_issuance", fromlist=["_PNG_DATA_URL"])._PNG_DATA_URL


def _today():
    return datetime.now().strftime("%Y%m%d")


def _days_ago(n):
    return (datetime.now() - timedelta(days=n)).strftime("%Y%m%d")


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


def _person(db, pid=1, nm="甲", gn="一", status="active"):
    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,"
               "residence,political_status,work_unit,position_or_title,supervisor_unit,status,operator) "
               "VALUES (?,?,?,'男','19900101',?,'浙江宁波市鄞州区','群众','总部','科长','人事处',?,'admin')",
               (pid, nm, gn, valid_id(pid), status))


def _passport(db, pid=1, nm="甲一", no="E1"):
    db.execute("INSERT INTO certificates (personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (?,'总部','技术部',?,?,'20351231','20250101','admin')", (pid, nm, no))


# ===========================================================================
# 一、批准日期必填
# ===========================================================================
@pytest.fixture()
def t(tmp_path, monkeypatch):
    db = _fresh(tmp_path, monkeypatch)
    _person(db); _passport(db)
    db.commit(); db.close()
    return _client()


_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\ntrailer\n<<>>\n%%EOF\n"


def _new_travel(cl, **over):
    import io
    d = {"csrf_token": _tok(cl), "personnel_filing_id": "1", "unit": "总部",
         "department": "技术部", "name": "甲一", "position": "科长",
         "id_number": valid_id(1), "destination_passport": "美国/护照", "category": "01",
         "travel_dates": "2026/11/01-2026/11/11", "need_new_passport": "否",
         "approval_date": "20261001",
         "att_application": (io.BytesIO(_PDF), "a.pdf"),
         "att_approval": (io.BytesIO(_PDF), "b.pdf")}
    d.update(over)
    return cl.post("/travel/new", data=d, content_type="multipart/form-data",
                   follow_redirects=True)


def test_approval_date_is_required_now(t):
    """不填批准日期建不出记录。

    《审批表》一直是必传附件——没有那张签好字的扫描件连记录都建不出来。
    既然纸质件必然存在，它上面的日期就没有理由是选填的。
    """
    r = _new_travel(t, approval_date="")
    assert "批准日期" in r.get_data(as_text=True) and "必填" in r.get_data(as_text=True)
    assert _one("SELECT COUNT(*) FROM travel_details") == 0


def test_the_form_marks_it_as_required(t):
    """表单上要有那个星号——校验拦得住，但让人填完一整张表才被打回是最没必要的为难。"""
    html = t.get("/travel/new").get_data(as_text=True)
    # 按标签文字精确定位，不用「输入框前后若干字符」那种窗口：窗口一宽就会
    # 框进邻格的 form-label required，这条断言随即变成永远绿的假通过
    # （撤掉星号验证时就是这么发现的）。
    label = re.search(r'<label[^>]*>批准日期</label>', html)
    assert label, "表单上找不到「批准日期」这一栏"
    assert "required" in label.group(0), f"批准日期没有标 *：{label.group(0)}"

    i = html.find('name="approval_date"')
    assert "required" in html[i:i + 200], "输入框上没有 required"


def test_a_normal_submission_still_goes_through(t):
    """填了就正常保存——别把必填改成了谁也过不去。"""
    _new_travel(t)
    assert _one("SELECT approval_date FROM travel_details") == "20261001"


# ===========================================================================
# 二、入库批号改为选填
# ===========================================================================
@pytest.fixture()
def d(tmp_path, monkeypatch):
    """一个待撤控的人，名下没有未清证件（否则撤控前置校验会先把人挡回去）。"""
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    db.commit(); db.close()
    return _client()


def _decontrol(cl, **over):
    d_ = {"csrf_token": _tok(cl), "surname": "甲", "given_name": "一", "gender": "男",
          "birth_date": "19900101", "id_number": valid_id(1),
          "residence": "浙江宁波市鄞州区", "political_status": "群众",
          "work_unit": "总部", "supervisor_unit": "人事处",
          "submit_unit_name": "市公安局出入境管理局", "submit_unit_type": "公安",
          "submit_contact": "李四", "submit_phone": "0574-88888888",
          "batch_no": "", "reason": "调离本单位",
          "decontrol_date": _days_ago(1), "cert_handover_date": _days_ago(3)}
    d_.update(over)
    return cl.post("/decontrol/new/1", data=d_, follow_redirects=True)


def test_batch_no_can_be_left_blank(d):
    """入库批号留空也能提交。

    它指的是当初备案时报给公安的那批纸质材料的批号，系统从没生成也从没存过
    ——personnel_filing 上根本没有这个字段。必填只会逼人随便敲一个数字进去，
    那比留空更糟：留空至少诚实地表示「不知道」。
    """
    _decontrol(d)
    assert _one("SELECT COUNT(*) FROM decontrol_filing") == 1
    assert (_one("SELECT batch_no FROM decontrol_filing") or "") == ""


def test_batch_no_is_still_saved_when_given(d):
    """知道批号的照样填，照样存。"""
    _decontrol(d, batch_no="2026-001")
    assert _one("SELECT batch_no FROM decontrol_filing") == "2026-001"


def test_the_form_no_longer_stars_it_and_says_where_it_comes_from(d):
    """表单上去掉星号，并写明它从哪来——不然下一个人还是会以为系统该给。"""
    html = d.get("/decontrol/new/1").get_data(as_text=True)
    # 只取「入库批号」自己那个 <label> 元素。往前后多截一点就会把邻格的
    # 「政治面貌 *」框进来，断言随即变成一条永远红的假警报——第 1 批栽过
    # 一次同类的（拿整页去找短字符串），这里按标签文字精确定位。
    label = re.search(r'<label[^>]*>入库批号</label>', html)
    assert label, "表单上找不到「入库批号」这一栏"
    assert "required" not in label.group(0), f"入库批号还标着 *：{label.group(0)}"

    i = html.find('name="batch_no"')
    assert "required" not in html[i:i + 200], "输入框上还留着 required"
    assert "系统不产生也不保存备案批号" in html[i:i + 400], "没说清这个批号从哪来"


# ===========================================================================
# 三、撤控日期与证件移交日期的先后
# ===========================================================================
def test_handover_may_precede_decontrol(d):
    """先把证收上来、隔几天再报撤控——正常节奏，放行。"""
    _decontrol(d, cert_handover_date=_days_ago(5), decontrol_date=_days_ago(1))
    assert _one("SELECT COUNT(*) FROM decontrol_filing") == 1


def test_same_day_is_fine_too(d):
    """同一天办结也放行——不要求两者相同，也不要求必须错开。"""
    _decontrol(d, cert_handover_date=_days_ago(2), decontrol_date=_days_ago(2))
    assert _one("SELECT COUNT(*) FROM decontrol_filing") == 1


def test_handover_after_decontrol_is_refused(d):
    """移交晚于撤控——挡下。撤控以证件收缴完毕为前提，证要先交回来。"""
    r = _decontrol(d, cert_handover_date=_days_ago(1), decontrol_date=_days_ago(5))
    assert "不能晚于撤控日期" in r.get_data(as_text=True)
    assert _one("SELECT COUNT(*) FROM decontrol_filing") == 0


def test_neither_date_may_be_in_the_future(d):
    """两个日期都不得晚于今天——它们记的都是已经发生过的事。"""
    later = (datetime.now() + timedelta(days=3)).strftime("%Y%m%d")
    r = _decontrol(d, decontrol_date=later)
    assert "不能晚于今天" in r.get_data(as_text=True)
    assert _one("SELECT COUNT(*) FROM decontrol_filing") == 0

    r = _decontrol(d, cert_handover_date=later, decontrol_date=later)
    assert "不能晚于今天" in r.get_data(as_text=True)
    assert _one("SELECT COUNT(*) FROM decontrol_filing") == 0


def test_today_itself_is_allowed(d):
    """今天不算「晚于今天」——边界写成 > 而不是 >=，撤控当天就得能办。"""
    _decontrol(d, cert_handover_date=_today(), decontrol_date=_today())
    assert _one("SELECT COUNT(*) FROM decontrol_filing") == 1


# ===========================================================================
# 四、领用准入：行程已结束 / 申请人已撤控
# ===========================================================================
@pytest.fixture()
def e(tmp_path, monkeypatch):
    """四条申请，覆盖准入判据的四个分支 + 一条正常的。

    1 正常在办（可领）
    2 行程已结束（实际回国日期已填）
    3 申请人已撤控
    4 已取消行程
    """
    db = _fresh(tmp_path, monkeypatch)
    _person(db, 1, "甲", "一"); _passport(db, 1, "甲一", "E1")
    _person(db, 2, "乙", "二", status="decontrolled")
    ago = _days_ago(120)

    def travel(tid, pid, nm, ret="", cancelled=False):
        db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
                   "position,id_number,destination_passport,category,travel_dates,travel_start,"
                   "travel_end,need_new_passport,actual_return_date,trip_status,approval_date,operator) "
                   "VALUES (?,?,'总部','技术部',?,'科长',?,'美国/护照','01','历史',?,?,'否',?,?,?,'admin')",
                   (tid, pid, nm, valid_id(pid), ago, ago, ret,
                    "cancelled" if cancelled else "normal", ago))
        seed_required_attachments(db, tid, "否")

    travel(1, 1, "甲一")
    travel(2, 1, "甲一", ret=_days_ago(100))
    travel(3, 2, "乙二")
    travel(4, 1, "甲一", cancelled=True)
    db.commit(); db.close()
    return _client()


def _issue(cl, travel_id, pid="1", nm="甲一"):
    return cl.post("/issuance/new", data={
        "csrf_token": _tok(cl), "travel_id": str(travel_id), "personnel_filing_id": pid,
        "holder_name": nm, "id_number": valid_id(int(pid)), "cert_types": "01",
        "cert_nos": "E1", "issue_date": _days_ago(110), "sign_png": _PNG,
    }, follow_redirects=True)


def _reasons():
    from app import create_app
    with create_app().app_context():
        from blueprints.issuance import issuance_block_reasons
        return issuance_block_reasons()


def test_the_four_reasons_are_each_spelled_out(e):
    """四个分支各给一句能看懂的原因，正常那条不在字典里。"""
    r = _reasons()
    assert 1 not in r, "正常在办的申请被挡了"
    assert "行程已结束" in r[2]
    assert "申请人已撤控" in r[3]
    assert "行程已取消" in r[4]


def test_a_finished_trip_cannot_be_issued_again(e):
    """行程已结束——不能再领。

    这正是报出来的那条：3 月走完、证也已归还的申请，9 月还能凭它再领一本
    护照出去。「领用 → 归还 → 再领用」的设计本意是同一趟行程中途的反复，
    不是行程结束之后。
    """
    body = _issue(e, 2).get_data(as_text=True)
    assert "行程已结束" in body
    assert _one("SELECT COUNT(*) FROM cert_issuance") == 0


def test_a_decontrolled_applicant_cannot_be_issued(e):
    """申请人已撤控——不能再领。撤控以证件收缴移交完毕为前提，人已不在管理范围内。"""
    body = _issue(e, 3, pid="2", nm="乙二").get_data(as_text=True)
    assert "申请人已撤控" in body
    assert _one("SELECT COUNT(*) FROM cert_issuance") == 0


def test_the_button_is_grey_for_all_three_and_says_why(e):
    """列表上这三行的按钮都点不了，且 title 就是后端给的那句原因。

    「能不能办」与「为什么办不了」必须是同一份判断的两个输出：模板自己拼提示语，
    判据一扩就会出现「提示说行程已取消、其实是因为别的」这种更难查的错。
    """
    html = e.get("/travel/").get_data(as_text=True)
    body = html[html.find("<tbody"):html.find("</tbody>")]
    assert "/issuance/new?travel_id=1" in body, "正常那条反而没了入口"
    for tid in (2, 3, 4):
        assert f"/issuance/new?travel_id={tid}" not in body, f"申请 {tid} 办不了却仍给了入口"
    for phrase in ("行程已结束", "申请人已撤控", "行程已取消"):
        assert phrase in body, f"按钮灰了却没说「{phrase}」"


def test_the_picker_lists_only_the_one_that_can_be_issued(e):
    """挑单页与按钮同源：只列那条真能办的。"""
    from app import create_app
    with create_app().app_context():
        from blueprints.issuance import _eligible_travels
        assert [r["id"] for r in _eligible_travels()] == [1]


def test_a_normal_application_still_works(e):
    """正常那条照样能领——判据收紧不能把正路也堵死。"""
    _issue(e, 1)
    assert _one("SELECT COUNT(*) FROM cert_issuance WHERE travel_id=1") == 1


# ===========================================================================
# 五、已结束的行程不能取消（否则会抹掉逾期告警）
# ===========================================================================
def test_a_finished_trip_cannot_be_cancelled(e):
    """已填实际回国日期的行程不能再取消。"""
    body = e.post("/travel/2/cancel", data={"csrf_token": _tok(e), "cancel_date": _today()},
                  follow_redirects=True).get_data(as_text=True)
    assert "行程已结束" in body and "不能再取消" in body
    assert _one("SELECT trip_status FROM travel_details WHERE id=2") == "normal"
    assert _one("SELECT cancel_date FROM travel_details WHERE id=2") is None


def test_cancelling_would_have_pushed_the_overdue_deadline_forward(e):
    """这条守的是「为什么必须拦」：取消会把应还到期日推到今天之后。

    cert_overdue_deadline 的基准日随行程状态整个切换——正常是「实际回国+10
    工作日」，取消是「取消日+5 工作日」。对一条早就该还证的记录点一下取消，
    到期日会从几个月前跳到今天之后，首页那条逾期告警当场消失 5 个工作日。
    这里不调路由（已经拦住了），直接拿判据函数把这个后果摆出来。
    """
    from utils.validators import cert_overdue_deadline
    db = sqlite3.connect(Config.DATABASE); db.row_factory = sqlite3.Row
    row = dict(db.execute("SELECT * FROM travel_details WHERE id=2").fetchone())
    db.close()

    now = cert_overdue_deadline(row)
    would_be = cert_overdue_deadline({**row, "trip_status": "cancelled",
                                      "cancel_date": _today()})
    assert now < _today() <= would_be, \
        f"本用例的前提不成立：现到期日 {now}，取消后 {would_be}"


def test_an_unfinished_trip_can_still_be_cancelled(e):
    """还没回来的行程当然可以取消——这才是取消行程的本来用途。"""
    e.post("/travel/1/cancel", data={"csrf_token": _tok(e), "cancel_date": _today()},
           follow_redirects=True)
    assert _one("SELECT trip_status FROM travel_details WHERE id=1") == "cancelled"


def test_the_button_is_disabled_on_the_detail_page(e):
    """详情页上那个按钮也要灰掉，并说明原因——后端拦住了，入口就不该还亮着。"""
    html = e.get("/travel/2").get_data(as_text=True)
    assert "行程已结束" in html and "不能再取消" in html
    assert "cancelModal" not in html, "已结束的行程还挂着取消行程的弹窗入口"
    assert "cancelModal" in e.get("/travel/1").get_data(as_text=True), \
        "正常行程的取消入口被一并去掉了"


# ===========================================================================
# 六、取消 / 恢复的操作日志要点名
# ===========================================================================
def test_cancel_log_names_the_record(e):
    """日志里要看得出取消的是谁、哪一趟。

    此前写的是「取消行程（20260904）」——翻一整页都不知道动的是谁，而同一批
    日志里别的动作都是「证件领用登记：甲一，普通护照」这个样子。
    """
    e.post("/travel/1/cancel", data={"csrf_token": _tok(e), "cancel_date": _today()},
           follow_redirects=True)
    detail = _one("SELECT detail FROM operation_logs WHERE action='cancel' ORDER BY id DESC LIMIT 1")
    assert "甲一" in detail, f"没点名是谁：{detail!r}"
    assert "美国/护照" in detail, f"没说是哪一趟：{detail!r}"
    assert _today() in detail, f"没记取消日期：{detail!r}"


def test_restore_log_names_the_record_and_the_date_it_undoes(e):
    """恢复同理，并带上它撤掉的那个取消日期。"""
    e.post("/travel/1/cancel", data={"csrf_token": _tok(e), "cancel_date": _today()},
           follow_redirects=True)
    e.post("/travel/1/restore", data={"csrf_token": _tok(e)}, follow_redirects=True)
    detail = _one("SELECT detail FROM operation_logs WHERE action='restore' ORDER BY id DESC LIMIT 1")
    assert "甲一" in detail, f"没点名是谁：{detail!r}"
    assert _today() in detail, f"没说撤掉的是哪一次取消：{detail!r}"

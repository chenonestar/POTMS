"""第 6 批：台账跟人走、删除提示说准话、办不了的事不给入口、字典分页。

四条都不改判据，改的是「系统有没有把话说对、把路指对」：

- C1 备案人员改了名，证照台账还挂在旧名下。台账不是单据——它记的是「这个人现在
  手上有哪几本证」，就该跟着人走。不跟，这本证在旧名下消失、也不在新名下，
  按姓名搜、按单位筛，两边都找不着。
- C2 删出国申请被挡时，提示说「请先作废相关领用记录」。照做没有用：判据不看
  status，作废的照样算数。
- C3 「证件领用登记」按钮对每一行都亮着，点进去才被挡回来。
- C4 八个字典类别的卡片全铺在一页，找一项要翻半天。
"""
import re
import sqlite3

import pytest

from config import Config
from tests.test_issuance import _PNG_DATA_URL as _PNG

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = "110101199001012133"


@pytest.fixture()
def c(tmp_path, monkeypatch):
    """一个人（#1）有信息表 + 备案表 + 证照台账 + 两条出行。"""
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()

    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO personnel_info (id,unit,department,name,gender,birth_date,"
               "id_number,position,education,degree,title,rank,political_status,operator) "
               "VALUES (1,'总部','技术部','张三','男','19900101',?,'科长','01','01','01','01',"
               "'群众','admin')", (_VALID_ID,))
    db.execute("INSERT INTO personnel_filing (id,personnel_info_id,surname,given_name,gender,"
               "birth_date,id_number,residence,political_status,work_unit,position_or_title,"
               "supervisor_unit,operator) VALUES (1,1,'张','三','男','19900101',?,"
               "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')", (_VALID_ID,))
    db.execute("INSERT INTO certificates (id,personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (1,1,'总部','技术部','张三','E12345678','20351231','20250101','admin')")
    for tid in (1, 2):
        db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
                   "position,id_number,destination_passport,category,travel_dates,travel_start,"
                   "travel_end,need_new_passport,operator) VALUES "
                   "(?,1,'总部','技术部','张三','科长',?,'美国/护照','01',"
                   "'2026/03/01-2026/03/10','20260301','20260310','否','admin')",
                   (tid, _VALID_ID))
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


def _issue(cl, travel_id=1):
    """给某条出行登记一条带签名的领用记录。"""
    cl.post("/issuance/new", data={
        "csrf_token": _tok(cl), "travel_id": str(travel_id), "personnel_filing_id": "1",
        "holder_name": "张三", "id_number": _VALID_ID, "cert_types": "01",
        "cert_nos": "E12345678", "issue_date": "20260225", "sign_png": _PNG},
        follow_redirects=True)
    assert _scalar("SELECT COUNT(*) FROM cert_issuance WHERE travel_id=?", (travel_id,)) == 1


# ---------------------------------------------------------------------------
# C1 证照台账跟着人走
# ---------------------------------------------------------------------------
def _edit_filing(cl, **over):
    data = {
        "csrf_token": _tok(cl), "surname": "张", "given_name": "三", "gender": "男",
        "birth_date": "19900101", "id_number": _VALID_ID, "residence": "浙江宁波市鄞州区",
        "political_status": "群众", "work_unit": "总部", "position_or_title": "科长",
        "supervisor_unit": "人事处",
    }
    data.update(over)
    return cl.post("/personnel/filing/1/edit", data=data, follow_redirects=True)


def test_rename_follows_into_certificate_ledger(c):
    """改了名，台账上那本证也得改过来——否则新旧两个名字下都找不着它。"""
    _edit_filing(c, surname="李", given_name="四")
    assert _scalar("SELECT name FROM certificates WHERE id=1") == "李四"


def test_unit_change_follows_into_certificate_ledger(c):
    """调了单位同理：台账按单位筛，人走了证还挂在原单位下就筛错了。"""
    _edit_filing(c, work_unit="分公司")
    assert _scalar("SELECT unit FROM certificates WHERE id=1") == "分公司"


def test_department_change_follows_from_info_table(c):
    """部门只存在于信息表（备案表没有这一栏），那条路径也要联动。"""
    c.post("/personnel/info/1/edit", data={
        "csrf_token": _tok(c), "unit": "总部", "department": "工程技术部", "name": "张三",
        "gender": "男", "birth_date": "19900101", "id_number": _VALID_ID, "position": "科长",
        "work_start_date": "20120701", "education": "01", "degree": "01", "title": "01",
        "rank": "01", "political_status": "群众"}, follow_redirects=True)
    assert _scalar("SELECT department FROM certificates WHERE id=1") == "工程技术部"


def test_issued_vouchers_keep_the_old_name(c):
    """已开出的领用单不跟着改——单据上印的是开单那天的信息，本来就该定格。

    这是台账与单据的分界：改人不能改单，否则那张签了字的凭证就被事后改写了。
    """
    _issue(c)
    _edit_filing(c, surname="李", given_name="四")
    assert _scalar("SELECT holder_name FROM cert_issuance WHERE travel_id=1") == "张三", \
        "签了字的领用凭证被改名改掉了"
    assert _scalar("SELECT name FROM travel_details WHERE id=1") == "张三", \
        "已提交的出国申请被改名改掉了"


def test_ledger_sync_is_logged(c):
    """联动改了别人的表，日志里要留得下这件事。"""
    _edit_filing(c, surname="李", given_name="四")
    db = sqlite3.connect(Config.DATABASE)
    details = [r[0] or "" for r in db.execute(
        "SELECT detail FROM operation_logs WHERE target_type='certificates' ORDER BY id DESC")]
    db.close()
    assert any("张三" in d and "李四" in d for d in details), f"日志里没有这次联动：{details[:3]}"


def test_editing_without_renaming_touches_nothing(c):
    """没改名没调单位就别去动台账。

    无谓的 UPDATE 会白刷一次 updated_at（台账列表按它排序，无关的编辑会把这行
    顶到最前），还会在日志里堆出一条什么也没变的「同步」记录。

    断言看的是提示与日志，不是 updated_at：那一栏只精确到秒，同一秒内的改动
    看不出差别，拿它做判据这条用例会永远绿。
    """
    html = _edit_filing(c, position_or_title="处长").get_data(as_text=True)
    assert "已同步更新证照台账" not in html, "什么都没改，却报了一次同步"
    assert _scalar("SELECT COUNT(*) FROM operation_logs WHERE target_type='certificates'") == 0, \
        "什么都没改，却写了一条证照台账的联动日志"


# ---------------------------------------------------------------------------
# C2 删除提示说准话
# ---------------------------------------------------------------------------
def test_delete_guard_does_not_suggest_voiding(c):
    """别再说「请先作废相关领用记录」——照做没有用，作废的照样挡。"""
    _issue(c)
    c.post("/issuance/1/void", data={"csrf_token": _tok(c), "void_reason": "登记错误"},
           follow_redirects=True)
    assert _scalar("SELECT status FROM cert_issuance WHERE id=1") == "voided", \
        "前提不成立：这条领用没作废成"

    html = c.post("/travel/1/delete", data={"csrf_token": _tok(c)},
                  follow_redirects=True).get_data(as_text=True)
    assert _scalar("SELECT COUNT(*) FROM travel_details WHERE id=1") == 1, "作废后居然删掉了"
    assert "请先作废相关领用记录" not in html, "仍在指一条走不通的路"
    assert "取消行程" in html, "没告诉操作员真正该做什么"
    assert "1 条已作废" in html, f"没说清是被什么挡住的：{html[:600]}"


def test_delete_guard_breaks_down_by_status(c):
    """说清楚挡在这里的是几条、什么状态，才知道下一步找谁。"""
    _issue(c)
    html = c.post("/travel/1/delete", data={"csrf_token": _tok(c)},
                  follow_redirects=True).get_data(as_text=True)
    assert "1 条已领用未归还" in html


def test_travel_without_issuance_can_still_be_deleted(c):
    """没开过领用单的申请仍要能删——守卫不能把这条路也堵死。"""
    c.post("/travel/2/delete", data={"csrf_token": _tok(c)}, follow_redirects=True)
    assert _scalar("SELECT COUNT(*) FROM travel_details WHERE id=2") == 0


def test_deleting_missing_travel_is_harmless(c):
    """删一条不存在的记录不能谎报成功——后退再提交就会走到这里。"""
    html = c.post("/travel/999/delete", data={"csrf_token": _tok(c)},
                  follow_redirects=True).get_data(as_text=True)
    assert "记录不存在" in html
    assert "已删除" not in html


# ---------------------------------------------------------------------------
# C3 办不了的事不给入口
# ---------------------------------------------------------------------------
def _row_actions(cl, travel_id):
    """截出列表里某一行的操作按钮区。"""
    html = cl.get("/travel/").get_data(as_text=True)
    key = f"/travel/{travel_id}/edit"
    assert key in html, f"列表里没有出行 {travel_id}"
    seg = html.rsplit(key, 1)[0]
    return seg[seg.rindex("<td><div class=\"btn-group"):]


def test_issuance_button_shown_when_eligible(c):
    """可以办的时候按钮照常给。"""
    assert "/issuance/new?travel_id=1" in _row_actions(c, 1)


def test_issuance_button_disabled_when_already_issued(c):
    """已有未归还的领用记录时不给入口——一次申请一本证，点进去也是被挡回来。"""
    _issue(c)
    actions = _row_actions(c, 1)
    assert "/issuance/new?travel_id=1" not in actions, "办不了却仍给了入口"
    assert "已有一条未归还的领用记录" in actions, "按钮灰了却没说为什么"


def test_issuance_button_returns_after_the_cert_comes_back(c):
    """归还之后又能再领——灰掉的按钮要能亮回来，不能变成一扇单向门。"""
    _issue(c)
    c.post("/issuance/1/return", data={"csrf_token": _tok(c), "return_date": "20260310",
                                       "sign_png": _PNG}, follow_redirects=True)
    assert _scalar("SELECT status FROM cert_issuance WHERE id=1") == "returned", \
        "前提不成立：这条领用没归还成"
    assert "/issuance/new?travel_id=1" in _row_actions(c, 1)


def test_issuance_button_disabled_for_cancelled_trip(c):
    """行程都取消了就不会再出行，没有领用的理由。"""
    c.post("/travel/1/cancel", data={"csrf_token": _tok(c), "cancel_date": "20260220"},
           follow_redirects=True)
    actions = _row_actions(c, 1)
    assert "/issuance/new?travel_id=1" not in actions
    assert "行程已取消" in actions


def test_list_button_and_picker_agree(c):
    """列表按钮与领用模块的选择页必须同口径——两套判据迟早对不上。"""
    _issue(c, travel_id=1)
    picker = c.get("/issuance/new").get_data(as_text=True)
    assert "选择出国申请" in picker or "出国申请" in picker
    # 1 号被排除、2 号仍可选，与列表上按钮的亮灭一致
    assert "travel_id=1" not in picker
    assert "travel_id=2" in picker
    assert "/issuance/new?travel_id=1" not in _row_actions(c, 1)
    assert "/issuance/new?travel_id=2" in _row_actions(c, 2)


# ---------------------------------------------------------------------------
# C4 字典改标签页
# ---------------------------------------------------------------------------
def test_dict_page_uses_tabs(c):
    """八个类别改成标签页，一屏只看一类。"""
    html = c.get("/dict/").get_data(as_text=True)
    assert 'data-bs-toggle="tab"' in html, "还是把八块内容全铺在一页"
    for label in ("学历", "职称", "政治面貌", "人事主管单位"):
        assert label in html, f"少了「{label}」这一类"


def test_dict_tab_can_be_selected_by_url(c):
    """?cat= 决定打开哪一页——后端跳回来、刷新、收藏都靠它。"""
    html = c.get("/dict/?cat=political_status").get_data(as_text=True)
    active = html.split('id="tab-political_status"', 1)[0].rsplit("<div", 1)[1]
    assert "show active" in active, "?cat= 指定的标签页没有被打开"


def test_dict_bad_cat_falls_back_to_first_tab(c):
    """乱填的 cat 退回第一页，不能什么都不选（那样一片空白）。"""
    html = c.get("/dict/?cat=不存在的类别").get_data(as_text=True)
    assert html.count("show active") == 1, "没有恰好一个标签页处于打开状态"


def test_dict_edits_come_back_to_the_same_tab(c):
    """在「职称」下加一项，保存完还得在「职称」——不能弹回第一页让人重新找。"""
    r = c.post("/dict/add", data={"csrf_token": _tok(c), "category": "title",
                                  "code": "99", "value": "特级技师", "sort_order": "9"})
    assert r.status_code == 302
    assert "cat=title" in r.headers["Location"], \
        f"保存后没有回到原来那一页：{r.headers['Location']}"


def test_dict_delete_comes_back_to_the_same_tab(c):
    did = _scalar("SELECT id FROM sys_dict WHERE category='travel_category' LIMIT 1")
    r = c.post(f"/dict/{did}/delete", data={"csrf_token": _tok(c)})
    assert "cat=travel_category" in r.headers["Location"]

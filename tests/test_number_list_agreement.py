"""数字与列表必须对得上：首页卡片的数、筛选出来的行、实体证件的本数，三者同源。

本批修的三处是同一个毛病的三种长相——**同一个概念在两个地方各写了一套判据**：

1. 首页「新办未入库（本）」的数取自 `travel.new_making_travel_ids()`（排除已交回
   入库、已取消行程、已撤控三类），可那张卡的链接指向 `?need_new_passport=是`
   ——纯列匹配，一类都不排除。实测卡上 1 本、点进去 4 行。用户看到的是
   「系统自己跟自己对不上」，而这一行卡片存在的全部意义就是拿去对账。

2. 出国明细列表的「证件状态」下拉里还留着「在库 / 领用中」两档，判据是
   `passport_collect_date` 有没有值——四档改造之前的老定义。现在的「在库」是
   **按证件本数**算的（以证照台账为准，见 certificate.stock_split），这里却按
   出行记录行数算。同一个词在两个页面指两件事，比没有这个筛选更糟。

3. 领用登记的重复校验只查同一条出行（`travel_id = ?`），拦不住同一本证被另一条
   申请再借一次。实体证只有一本，两张签了字的未归还领用单同时指向它。

第 3 条要说清楚它**不是**什么：恒等式「在库 + 借出未还 = 台账总本数」并没有被
打破——`lent_out_numbers()` 返回的是号码集合，天然去重。破的是领用单与实体证件
的一一对应，以及「领用列表两行 / 首页一本」这个对不上的数。
"""
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

from config import Config
from conftest import valid_id

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = valid_id(1)   # 1 号人物；其余人各用 valid_id(pid)
_PNG = __import__("tests.test_issuance", fromlist=["_PNG_DATA_URL"])._PNG_DATA_URL


def _ago(days=120):
    return (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")


def _login(tmp_path, monkeypatch):
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


def _person(db, pid, nm, status="active"):
    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
               "id_number,residence,political_status,work_unit,position_or_title,"
               "supervisor_unit,status,operator) VALUES (?,?,'','男','19900101',?,"
               "'浙江宁波市鄞州区','群众','总部','科长','人事处',?,'admin')",
               (pid, nm, valid_id(pid), status))


# ===========================================================================
# 一、首页「新办未入库」的数与它点开的列表
# ===========================================================================
@pytest.fixture()
def c(tmp_path, monkeypatch):
    """五个人，四条路径B 申请，只有一条该算「新办未入库」。

    甲 做证、号码还没进台账、在控、行程没取消  ← 唯一该算的一条
    乙 做证、新证号码**已经进了证照台账**       ← 已交回入库，不算
    丙 做证、**行程已取消**                     ← 压根不会去办，不算
    丁 做证、人**已撤控**                       ← 不在管理范围，不算
    戊 路径A，证在库                            ← 与本档无关

    乙丙丁三条正是旧链接（?need_new_passport=是）会多列出来的行。
    """
    db = _login(tmp_path, monkeypatch)
    ago = _ago()

    def travel(tid, pid, nm, no="", cancelled=False):
        db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
                   "position,id_number,destination_passport,category,travel_dates,travel_start,"
                   "travel_end,need_new_passport,passport_no,trip_status,operator) VALUES "
                   "(?,?,'总部','技术部',?,'科长',?,'美国/护照','01','历史',?,?,'是',?,?,'admin')",
                   (tid, pid, nm, _VALID_ID, ago, ago, no,
                    "cancelled" if cancelled else "normal"))

    _person(db, 1, "甲"); travel(1, 1, "甲", "E_NEW_1")
    _person(db, 2, "乙"); travel(2, 2, "乙", "E_BACK_2")
    # 乙那本新证已经录进台账 —— 台账登记时上交日期必填，所以「在台账里」就等于
    # 「已交回收缴」，这正是 _registered_cert_travel_ids 的判据
    db.execute("INSERT INTO certificates (personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (2,'总部','技术部','乙','E_BACK_2','20351231','20250101','admin')")
    _person(db, 3, "丙"); travel(3, 3, "丙", "E_CANCEL_3", cancelled=True)
    _person(db, 4, "丁", "decontrolled"); travel(4, 4, "丁", "E_GONE_4")
    _person(db, 5, "戊")
    db.execute("INSERT INTO certificates (personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (5,'总部','技术部','戊','E_STOCK_5','20351231','20250101','admin')")
    db.commit(); db.close()
    return _client()


def _card(html, label):
    """取某张数字卡上的数。数字紧挨在标签前，一起匹配才不会取到别的卡。"""
    m = re.search(r'>(\d+)</div>\s*<small class="text-muted">' + re.escape(label), html)
    assert m, f"首页上找不到「{label}」这张卡"
    return int(m.group(1))


def _listed_names(html):
    """列表 <tbody> 里出现的人名。断言范围收窄到表体——整页里侧边栏、
    告警条、筛选框都可能带上同样的字，拿整页去 in 一定会误判。"""
    body = html[html.find("<tbody"):html.find("</tbody>")]
    return {nm for nm in ("甲", "乙", "丙", "丁", "戊") if f">{nm}<" in body}


def test_card_number_equals_the_rows_its_link_shows(c):
    """卡上的数 == 点开那个链接列出来的行数。这是这张卡唯一的用途。"""
    home = c.get("/").get_data(as_text=True)
    n = _card(home, "新办未入库（本）")
    assert n == 1, "该算的只有甲：乙已入库、丙已取消、丁已撤控"

    # 链接就从首页 HTML 里取，不在测试里另拼一个——拼错了这条断言反而会绿
    m = re.search(r'href="(/travel/\?[^"]*passport_status=pending_new[^"]*)"', home)
    assert m, "首页「新办未入库」卡没有指向 ?passport_status=pending_new 的链接"

    rows = c.get(m.group(1).replace("&amp;", "&")).get_data(as_text=True)
    assert _listed_names(rows) == {"甲"}, "列表里的人和卡上的数对不上"


def test_the_three_kinds_the_old_link_wrongly_listed(c):
    """乙丙丁逐个点名：旧链接把这三类都列了进来，这条把它们钉死。

    分三条断言而不是合成一条，是为了让哪一类漏了排除一眼可见。
    """
    names = _listed_names(c.get("/travel/?passport_status=pending_new").get_data(as_text=True))
    assert "乙" not in names, "新证号码已进证照台账 = 已交回入库，不该还算未入库"
    assert "丙" not in names, "行程已取消的不会去办证，不该算未入库"
    assert "丁" not in names, "已撤控人员不在管理范围，不该出现在告警类筛选里"


def test_the_plain_column_match_is_not_what_the_card_means(c):
    """留一条对照：按 ?need_new_passport=是 筛，确实会多出那三行。

    这条锁的是「两种筛法结果本来就不同」这个事实——将来谁把卡片链接改回
    纯列匹配，上面那条会红，而这条说明为什么它必须红。
    """
    plain = _listed_names(c.get("/travel/?need_new_passport=是").get_data(as_text=True))
    assert plain == {"甲", "乙", "丙", "丁"}, "「是否做证=是」是一个纯粹的列匹配，不做任何排除"


def test_retired_stock_and_inuse_options_are_gone(c):
    """下拉里不再有「在库 / 领用中」两档。

    它们的判据是 passport_collect_date（四档改造前的老定义），按出行记录行算；
    而现在的「在库」按证件本数算。同一个词在两个页面指两件事，撤掉整档，
    不重新对口径——出国明细本来就不是盘库的地方。
    """
    bar = c.get("/travel/").get_data(as_text=True)
    sel = bar[bar.find('name="passport_status"'):]
    sel = sel[:sel.find("</select>")]
    assert 'value="storage"' not in sel and 'value="inuse"' not in sel, \
        "老口径的「在库 / 领用中」还留在下拉里"
    assert 'value="pending_new"' in sel and 'value="overdue"' in sel, \
        "下拉里应当只剩与首页同源的两档"


def test_both_remaining_filters_share_the_dashboard_functions(c):
    """剩下两档都直接调首页那两张卡背后的函数，不另写判据。

    直接比集合：筛出来的 id 必须与函数返回的 id 集合完全相同。
    """
    from blueprints.travel import _overdue_ids, new_making_travel_ids
    from app import create_app
    with create_app().app_context():
        expect_new = new_making_travel_ids()
        expect_od = _overdue_ids()

    def listed_ids(url):
        html = c.get(url).get_data(as_text=True)
        body = html[html.find("<tbody"):html.find("</tbody>")]
        return {int(i) for i in re.findall(r'/travel/(\d+)\b', body)}

    assert listed_ids("/travel/?passport_status=pending_new") == expect_new
    assert listed_ids("/travel/?passport_status=overdue") == expect_od


# ===========================================================================
# 二、一本证同时只能在一个人手上（跨申请的号码级查重）
# ===========================================================================
@pytest.fixture()
def d(tmp_path, monkeypatch):
    """一个人、一本护照 E1、两条出国申请。

    两条申请是现实里最常见的形态：这次去美国，下次去日本，用的是同一本护照。
    正确流程是还回来再借；错误流程是第一次没还就又开一张领用单。
    """
    db = _login(tmp_path, monkeypatch)
    _person(db, 1, "甲")
    db.execute("INSERT INTO certificates (personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (1,'总部','技术部','甲','E1','20351231','20250101','admin')")
    _person(db, 2, "乙")
    for tid, pid, nm in ((1, 1, "甲"), (2, 1, "甲"), (3, 2, "乙")):
        db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
                   "position,id_number,destination_passport,category,travel_dates,travel_end,"
                   "need_new_passport,operator) VALUES "
                   "(?,?,'总部','技术部',?,'科长',?,'美国/护照','01','历史',?,'否','admin')",
                   (tid, pid, nm, _VALID_ID, _ago()))
    db.commit(); db.close()
    return _client()


def _tok(cl):
    return _CSRF.search(cl.get("/").get_data(as_text=True)).group(1)


def _issue(cl, travel_id, pid="1", nm="甲", no="E1"):
    return cl.post("/issuance/new", data={
        "csrf_token": _tok(cl), "travel_id": str(travel_id), "personnel_filing_id": pid,
        "holder_name": nm, "id_number": _VALID_ID, "cert_types": "01",
        "cert_nos": no, "issue_date": _ago(30), "sign_png": _PNG,
    }, follow_redirects=True)


def _open_count(no="E1"):
    db = sqlite3.connect(Config.DATABASE)
    n = db.execute("SELECT COUNT(*) FROM cert_issuance WHERE cert_nos = ? AND status = 'issued'",
                   (no,)).fetchone()[0]
    db.close()
    return n


def test_same_certificate_cannot_be_issued_twice_at_once(d):
    """第二张未归还的领用单被拦下，且提示要说清是谁、哪条记录。

    「挡下要给明细」：只说「该证件已被领用」，经办人还得自己去翻是哪一张。
    """
    _issue(d, 1)
    assert _open_count() == 1

    html = _issue(d, 2).get_data(as_text=True)
    assert _open_count() == 1, "同一本证同时开出了两张未归还的领用单"
    assert "E1" in html and "甲" in html, "提示里没说清是哪本证、在谁手上"
    assert "#1" in html, "提示里没给出前一张领用记录的编号"


def test_a_different_persons_application_cannot_take_it_either(d):
    """换个人拿同一个号码去领，同样拦——号码错录成别人的证是真会发生的。"""
    _issue(d, 1)
    _issue(d, 3, pid="2", nm="乙")
    assert _open_count() == 1


def test_returning_it_frees_the_number(d):
    """还回来之后再借，必须放行。

    这条守的是修复的边界：判据只看 status='issued'，把它写成「历史上领过就不许
    再领」会把最普通的业务（同一本护照下次出差再借）一起拦死。
    """
    _issue(d, 1)
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE cert_issuance SET status='returned', return_date=? WHERE id=1",
               (_ago(10),))
    db.commit(); db.close()

    _issue(d, 2)
    assert _open_count() == 1, "归还之后再领应当放行"


def test_a_voided_record_does_not_hold_the_number(d):
    """作废的那张不占用号码——作废是「这次领用作废」，证根本没出过柜子。"""
    _issue(d, 1)
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE cert_issuance SET status='voided', void_reason='登记有误' WHERE id=1")
    db.commit(); db.close()

    _issue(d, 2)
    assert _open_count() == 1, "作废之后再领应当放行"


def test_an_empty_number_is_not_a_collision(d):
    """号码为空时不参与查重——空不是一个号码，两条都空不代表撞了同一本证。"""
    from blueprints.issuance import _validate_form
    from app import create_app
    with create_app().app_context():
        errs = _validate_form({"travel_id": "1", "personnel_filing_id": "1",
                               "holder_name": "甲", "cert_types": "01",
                               "issue_date": _ago(30), "cert_nos": ""})
    assert not [e for e in errs if "已由" in e], "空号码不该被判为重复"


def test_the_count_and_the_list_agree_after_the_guard(d):
    """回到这批的主题：首页「借出未还（本）」与领用列表的行数必须一致。

    这正是 H2 真正破坏的东西——恒等式没破（号码集合天然去重），破的是
    「一本 vs 两行」。拦住第二张之后两边才对得上。
    """
    _issue(d, 1)
    _issue(d, 2)  # 被拦下

    home = d.get("/").get_data(as_text=True)
    lent = _card(home, "借出未还（本）")
    listed = d.get("/issuance/?status=issued").get_data(as_text=True)
    body = listed[listed.find("<tbody"):listed.find("</tbody>")]
    # 按记录 id 去重再数：一行里「查看」「归还」两个链接都指向同一条记录
    assert lent == len(set(re.findall(r'/issuance/(\d+)"', body))) == 1

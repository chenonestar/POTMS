"""首页仪表盘：一件事只报一次，不算没人看的数。

首页原来七张卡，里面藏着两对重复：

- 「证照逾期未还」数字卡与「证件逾期未还」名单卡，同一份 overdue 数据，一个取长度
  一个列名单，措辞还不一样（证照 / 证件）。
- 「证照在库 / 领用中 / 逾期未还」这三个讲的是**证件借出归还的流转**，数据来自出国
  申请上由领用记录回写的派生字段，业务上该叫「证件」；「证照」在本系统里特指证照
  台账（这个人有哪几本证）。三处都用错了词。

另有一张「证照到期预警」卡，按业务本身就不需要：证件只有凭出国申请才领得出去，
没有申请，证到期了也不会被领出去换证，只能在库里放着。算了不看的数，删掉。

现在的口径：**首页只报数字，名单与应还日期在出国明细列表上**（点数字卡过去）。
"""
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

from config import Config

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = "110101199001012133"


def _day(n):
    return (datetime.now() + timedelta(days=n)).strftime("%Y%m%d")


@pytest.fixture()
def c(tmp_path, monkeypatch):
    """三个人：两个已领用且逾期未还（一个在控、一个已撤控），一个证在库没领。"""
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()

    long_ago = _day(-120)
    db = sqlite3.connect(Config.DATABASE)
    people = [(1, "逾期甲", "active"), (2, "撤控乙", "decontrolled"), (3, "在库丙", "active")]
    for pid, nm, status in people:
        db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
                   "id_number,residence,political_status,work_unit,position_or_title,"
                   "supervisor_unit,status,operator) VALUES (?,?,'','男','19900101',?,"
                   "'浙江宁波市鄞州区','群众','总部','科长','人事处',?,'admin')",
                   (pid, nm, _VALID_ID, status))
        db.execute("INSERT INTO certificates (id,personnel_filing_id,unit,department,name,"
                   "passport_no,passport_expiry,passport_submit_date,operator) "
                   "VALUES (?,?,'总部','技术部',?,?,?,'20250101','admin')",
                   (pid, pid, nm, f"E900000{pid}", _day(10)))   # 都是 10 天后到期
    # 1、2 号：领用后逾期未还；3 号：没领，证在库
    for pid, nm in ((1, "逾期甲"), (2, "撤控乙")):
        db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
                   "position,id_number,destination_passport,category,travel_dates,travel_start,"
                   "travel_end,need_new_passport,passport_collect_date,operator) VALUES "
                   "(?,?,'总部','技术部',?,'科长',?,'美国/护照','01','历史批次',?,?,'否',?,'admin')",
                   (pid, pid, nm, _VALID_ID, long_ago, long_ago, long_ago))
    db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
               "position,id_number,destination_passport,category,travel_dates,"
               "need_new_passport,operator) VALUES (3,3,'总部','技术部','在库丙','科长',?,"
               "'美国/护照','01','2026/09/01-2026/09/10','否','admin')", (_VALID_ID,))
    db.commit(); db.close()

    from app import create_app
    cl = create_app().test_client()
    tok = _CSRF.search(cl.get("/login").get_data(as_text=True)).group(1)
    cl.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return cl


def _stat(html, label):
    """取出某张数字卡上的数。数字在标签前面一行，一起匹配才不会取错卡。"""
    m = re.search(r'>(\d+)</div>\s*<small class="text-muted">' + label, html)
    assert m, f"首页上找不到「{label}」这张卡"
    return int(m.group(1))


# ---------------------------------------------------------------------------
# 一件事只报一次
# ---------------------------------------------------------------------------
def test_overdue_is_reported_in_exactly_one_place(c):
    """逾期只有一个入口。原来数字卡与名单卡各报一次，同一份数据说两遍。"""
    html = c.get("/").get_data(as_text=True)
    assert html.count("逾期未还") == 1, \
        f"首页上「逾期未还」出现了 {html.count('逾期未还')} 次，同一件事报了不止一遍"


def test_overdue_card_counts_and_links_to_the_list(c):
    """数字卡要能点过去看名单——名单不在首页了，这条路就不能断。"""
    html = c.get("/").get_data(as_text=True)
    assert _stat(html, "证件逾期未还") == 1, "逾期数只该算在控的那一个"
    assert "passport_status=overdue" in html, "逾期卡没有指向出国明细的逾期筛选"


def test_in_use_excludes_decontrolled(c):
    """「领用中」不把已撤控人员算进去。

    撤控的前提就是证件已收缴移交；这种状态只可能是守卫上线前的历史数据，
    算进在办数字里只会让人去找一个找不到的人。
    """
    assert _stat(c.get("/").get_data(as_text=True), "证件领用中") == 1


def test_cards_say_certificate_not_ledger(c):
    """在库 / 领用中 / 逾期未还讲的是证件的借出归还，不是证照台账。

    「证照」在本系统里特指证照台账（这个人有哪几本证），「证件」才是流转中的那本。
    """
    html = c.get("/").get_data(as_text=True)
    for wrong in ("证照在库", "证照领用中", "证照逾期未还"):
        assert wrong not in html, f"首页仍在用「{wrong}」——这三张卡讲的是证件流转"
    for right in ("证件在库", "证件领用中", "证件逾期未还"):
        assert right in html, f"首页缺少「{right}」"


# ---------------------------------------------------------------------------
# 不算没人看的数
# ---------------------------------------------------------------------------
def test_expiry_warning_is_gone_from_dashboard(c):
    """到期预警不该在首页：证件只有凭出国申请才领得出去，没有申请，证到期了
    也不会被领出去换证，只能在库放着——这条预警在首页上没有可采取的行动。"""
    assert "到期预警" not in c.get("/").get_data(as_text=True)


def test_dashboard_computes_nothing_it_does_not_render(c):
    """算了不渲染的数，等于每进一次首页白跑一次查询。

    断言的是模板上下文而不是页面文字：这些变量本来就不渲染，只看页面永远是绿的，
    测不出「查询还在不在」。
    """
    from flask import template_rendered
    from app import create_app

    app = create_app()
    seen = {}
    def record(sender, template, context, **extra):
        if template.name == "dashboard.html":
            seen.update(context)
    template_rendered.connect(record, app)
    try:
        cl = app.test_client()
        tok = _CSRF.search(cl.get("/login").get_data(as_text=True)).group(1)
        cl.post("/login", data={"username": "admin", "password": "admin123",
                                "csrf_token": tok})
        cl.get("/")
    finally:
        template_rendered.disconnect(record, app)

    assert seen, "没抓到首页的模板上下文，这条用例什么也没验证"
    for dead in ("expiring", "warn_days", "overdue", "by_unit", "by_political", "by_rank"):
        assert dead not in seen, f"{dead} 仍在算并传给模板，而模板不用它"
    assert "cert_overdue" in seen, "逾期数没传给模板"


def test_certificate_ledger_keeps_its_own_expiry_banner(c):
    """删的只是首页那张卡，证照台账页自己的到期提示不动。

    台账页是「管证」的地方，在那里看到期是有意义的（换发要提前安排）；
    首页是「今天要办什么」，两者不是一回事。
    """
    assert "即将到期" in c.get("/certificate/").get_data(as_text=True)

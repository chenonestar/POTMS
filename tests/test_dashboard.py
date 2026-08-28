"""首页告警：证照到期预警卡，以及不再白算没人用的统计。

首页原来只报「证件逾期未还」——逾期是已经出事了。**还来得及办**的那件事（证照快到
期，该提醒本人去换发）只在证照台账页有，得点进去才看得到，首页上一个字都没有。
更别扭的是：`expiring` 这份数据首页一直在算，算完直接扔掉，从第一版起就没渲染过。

同时扔掉的还有 by_unit / by_political / by_rank 三项分布统计——同样从没渲染过，
每进一次首页白跑三个查询。500 人、单用户的规模上分布统计更像报表需求，
.NET 与 Java 两版早已不查也不显示，这里与它们对齐。
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
    """三个人：护照 5 天后到期、25 天后到期、以及一个已撤控的 5 天后到期。"""
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()

    db = sqlite3.connect(Config.DATABASE)
    people = [
        (1, "急张三", _day(5), "active"),
        (2, "缓李四", _day(25), "active"),
        (3, "撤控王五", _day(5), "decontrolled"),
    ]
    for pid, nm, expiry, status in people:
        db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
                   "id_number,residence,political_status,work_unit,position_or_title,"
                   "supervisor_unit,status,operator) VALUES (?,?,'','男','19900101',?,"
                   "'浙江宁波市鄞州区','群众','总部','科长','人事处',?,'admin')",
                   (pid, nm, _VALID_ID, status))
        db.execute("INSERT INTO certificates (id,personnel_filing_id,unit,department,name,"
                   "passport_no,passport_expiry,passport_submit_date,operator) "
                   "VALUES (?,?,'总部','技术部',?,?,?,'20250101','admin')",
                   (pid, pid, nm, f"E1000000{pid}", expiry))
    db.commit(); db.close()

    from app import create_app
    cl = create_app().test_client()
    tok = _CSRF.search(cl.get("/login").get_data(as_text=True)).group(1)
    cl.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return cl


def _card(cl):
    """截出「证照到期预警」那张卡。整页断言会被别处的姓名糊弄。"""
    html = cl.get("/").get_data(as_text=True)
    assert "证照到期预警" in html, "首页没有到期预警卡"
    return html.split("证照到期预警", 1)[1].split("近期出行计划", 1)[0]


def test_expiry_card_lists_people_by_urgency(c):
    """最先到期的排最前——这张卡是「接下来要办什么」，不是一份名册。"""
    card = _card(c)
    assert "急张三" in card and "缓李四" in card
    assert card.index("急张三") < card.index("缓李四"), "没有按到期先后排"
    assert "普通护照" in card, "没说明是哪一类证件"


def test_expiry_card_shows_days_left(c):
    """光给一个日期还得心算，而这张卡要回答的就是「有多急」。"""
    card = _card(c)
    assert "剩 5 天" in card, f"没标出剩余天数：{card[:500]}"
    # 一周之内的要显眼，否则和还有三周的混在一起就失去了排序的意义
    urgent = card.split("急张三", 1)[1].split("</li>", 1)[0]
    assert "text-danger" in urgent, "七天内到期的没有标红"


def test_expiry_card_respects_configured_threshold(c, monkeypatch):
    """阈值取 Config.CERT_EXPIRY_WARN_DAYS，不是首页自己写死的 30。

    首页与证照台账报的必须是同一批证。两处各写一个天数，调了配置就只有一处
    跟着变，用的人无从判断哪个才算数。
    """
    monkeypatch.setattr(Config, "CERT_EXPIRY_WARN_DAYS", 10)
    card = _card(c)
    assert "急张三" in card, "5 天后到期的在 10 天阈值内，却没报出来"
    assert "缓李四" not in card, "25 天后到期的超出了 10 天阈值，仍被报出来"
    assert "10 天内无到期证照" not in card, "有该报的却显示成了空"


def test_decontrolled_person_is_not_warned_about(c):
    """人都撤控了，他那本证到不到期与本单位无关（第 5 批 B1 的口径）。

    撤控意味着证已收缴移交，这条预警没人处理得掉，报出来只会把真正要办的事淹掉。
    """
    assert "撤控王五" not in _card(c)


def test_empty_state_names_the_threshold(c):
    """没有要办的事时也要说清楚「多少天内没有」，否则不知道这卡到底看的什么。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE certificates SET passport_expiry = ?", (_day(3650),))
    db.commit(); db.close()
    assert "30 天内无到期证照" in _card(c)


def test_dashboard_does_not_compute_unused_statistics(c):
    """没人渲染的统计就不该算——每进一次首页白跑三个查询，其中一个还带 JOIN。

    断言的是模板上下文而不是页面文字：这三项本来就没渲染过，只看页面永远是绿的，
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
    for dead in ("by_unit", "by_political", "by_rank"):
        assert dead not in seen, f"{dead} 仍在算并传给模板，而模板从没用过它"
    assert "expiring" in seen, "到期预警的数据没传给模板"

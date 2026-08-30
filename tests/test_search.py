"""全局搜索：五个模块一次搜遍，其中领用单是补进来的第五个。

补它的理由不是「凑齐」。按证件号码搜，原来搜得到证照台账（这本证登记在谁名下）、
搜得到出国申请（哪次出行用了它），唯独搜不到**「这本证现在在谁手上」的那张领用单**
——而领用单才是这件事的权威来源：首页「借出未还」那一档就是按它算的
（certificate.lent_out_numbers 只看 cert_issuance.status='issued'）。

保管处最常问的一句话是「这本证呢」，以前在全局搜索里恰恰答不上来。
"""
import re
import sqlite3

import pytest

from config import Config

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = "110101199001012133"


@pytest.fixture()
def c(tmp_path, monkeypatch):
    """一个人、一本证、一条出行、三张领用单（在借 / 已归还 / 已作废）。

    三种状态都造出来：搜索是「找东西」，不是「找在办的东西」——作废的那张
    单子上有本人签名、仍要留档，查历史时同样得搜得到。
    """
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()

    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
               "id_number,residence,political_status,work_unit,position_or_title,"
               "supervisor_unit,operator) VALUES (1,'史','迪威','男','19900101',?,"
               "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')", (_VALID_ID,))
    db.execute("INSERT INTO certificates (id,personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (1,1,'总部','技术部','史迪威','E12345678','20351231','20250101','admin')")
    db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
               "id_number,destination_passport,category,travel_dates,need_new_passport,"
               "passport_no,operator) VALUES (1,1,'总部','技术部','史迪威','科长',?,"
               "'美国/护照','旅游','2026-05','否','E12345678','admin')", (_VALID_ID,))
    for iid, no, st, ret in ((1, "E12345678", "issued", None),
                             (2, "C87654321", "returned", "20260401"),
                             (3, "T55556666", "voided", None)):
        db.execute("INSERT INTO cert_issuance (id,travel_id,personnel_filing_id,holder_name,"
                   "id_number,cert_types,cert_nos,issue_date,issuer,status,return_date,operator) "
                   "VALUES (?,1,1,'史迪威',?,'01',?,'20260301','保管处',?,?,'admin')",
                   (iid, _VALID_ID, no, st, ret))
    db.commit(); db.close()

    from app import create_app
    cl = create_app().test_client()
    tok = _CSRF.search(cl.get("/login").get_data(as_text=True)).group(1)
    cl.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return cl


def _block(html, group):
    """截出某个结果分组那张卡（按 data-group 定位），避免拿整页断言。

    不能按「证件领用」这几个字去找：**侧边栏导航里也有同样四个字**，
    第一次命中的是导航项，截出来的是一段与搜索结果无关的 HTML。
    模板上给五张结果卡各加了 data-group，就是为了有一个只指向结果卡的锚点。
    """
    marker = f'data-group="{group}"'
    i = html.find(marker)
    assert i != -1, f"结果页里没有 {group} 这一组"
    end = html.find('<div class="card mb-3"', i + len(marker))
    return html[i:end] if end != -1 else html[i:]


def _has_group(html, group):
    return f'data-group="{group}"' in html


def _search(cl, q):
    from urllib.parse import quote
    return cl.get(f"/search?q={quote(q)}").get_data(as_text=True)


def test_certificate_number_finds_the_issuance_record(c):
    """按证件号码搜，要搜得到那张领用单——「这本证现在在谁手上」的权威来源。

    这一条是本次改动的全部理由：原来同一个号码搜得到台账、搜得到出国申请，
    唯独领用单搜不到。
    """
    html = _search(c, "E12345678")
    blk = _block(html, "issuance")
    assert "E12345678" in blk, "领用分组里没有这个号码"
    assert "已领用（未归还）" in blk, "没显示这本证还没还回来"
    assert "/issuance/1" in blk, "没给查看领用记录的入口"


def test_holder_name_finds_issuance(c):
    """按领用人姓名搜。"""
    assert _has_group(_search(c, "史迪威"), "issuance")


def test_id_number_finds_issuance(c):
    """按身份证号搜。领用单上存了身份证号，签字凭证认的就是这个。"""
    assert _has_group(_search(c, _VALID_ID), "issuance")


def test_returned_and_voided_records_are_searchable_too(c):
    """已归还与已作废的也要搜得到。

    搜索是「找东西」，不是「找在办的东西」。作废那张单上有本人手写签名、
    仍要留档（作废是「这次领用作废」，不是「这次领用没发生过」），
    查历史时必须找得到。
    """
    ret = _block(_search(c, "C87654321"), "issuance")
    assert "已归还" in ret and "20260401" in ret

    void = _block(_search(c, "T55556666"), "issuance")
    assert "已作废" in void


def test_cert_type_code_is_rendered_as_chinese(c):
    """证件种类要显示中文，不能印出裸的 01。"""
    assert "普通护照" in _block(_search(c, "E12345678"), "issuance")


def test_search_shares_the_predicate_with_the_issuance_list(c):
    """「什么算命中」与领用列表的搜索框同源，不另写一套。

    各写一套的话，同一个号码在两处搜出不同结果，而用户没有任何办法知道
    哪一处是对的。这里直接断言两边命中的是同一批 id。
    """
    from blueprints.issuance import build_filters
    where, params = build_filters({"search": "E12345678"})
    assert "i.holder_name" in where and "i.cert_nos" in where, \
        "领用模块的搜索判据变了，全局搜索借的就是它"

    # 领用列表页与全局搜索，同一个关键词应当指向同一条记录
    listed = c.get("/issuance/?search=E12345678").get_data(as_text=True)
    assert "/issuance/1" in listed
    assert "/issuance/1" in _block(_search(c, "E12345678"), "issuance")


def test_number_search_now_covers_all_three_places_it_appears(c):
    """同一个号码，三处都要搜得到：台账（登记在谁名下）、出行（哪次用了它）、
    领用单（现在在谁手上）。少任何一处，答案就是残的。"""
    html = _search(c, "E12345678")
    for group, label in (("certificate", "证照台账"), ("travel", "出国申请"),
                         ("issuance", "证件领用")):
        assert _has_group(html, group), f"号码搜索漏了「{label}」"


def test_no_match_says_so(c):
    """搜不到就明说，不要给一张空页面。"""
    html = _search(c, "E00000000")
    assert "未找到与" in html
    assert not _has_group(html, "issuance")


def test_empty_query_lists_all_five_modules_in_the_hint(c):
    """空查询时的提示要把五个模块都点到——它是用户唯一能看到「能搜什么」的地方。"""
    html = c.get("/search").get_data(as_text=True)
    for group in ("人员备案", "证照台账", "出国申请", "证件领用", "撤控记录"):
        assert group in html, f"提示语里没提「{group}」"

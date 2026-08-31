"""第 3 批：时区筛选 / 换发二次确认 / 撤销撤控提醒 / 未关联信息表。

四条看似不相干，共同点是**系统知道的比它说出来的多**：

M2 日志与附件的日期筛选直接 date(created_at)，而库里存的是 UTC、页面显示的是
   本地。同一个模块里 _log_years 与 export_logs 明明转过时区，就这两处没转。
   后果不是报错，是本地当天 00:00–08:00 那一段静静地筛不出来——**筛不到的东西
   没有声音**，操作员只会以为那天没人操作。

M3 换发时号码换了、日期还留着旧证的，系统只 flash 一句提醒。而它其实分得清
   两种情形——只要问一句。见 stale_renewal_errors。

M4 撤销撤控把人放回在控，他名下的台账证件立刻重新计入「在库」，可实体证在
   撤控那天已经移交出去了。系统清楚这次变动，却什么都没说。

M5 备案可以不关联信息登记表（这是设计，不是缺陷）。但职级只存在于信息表，
   按职级筛选时这批人永远不出现——SQL 没错，错在用户不知道自己看的是子集。
"""
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

from config import Config
from conftest import valid_id

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')


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


# ===========================================================================
# M2 按本地日期筛选（库里存 UTC）
# ===========================================================================
# 挑 UTC 18:00：+8 之后落到本地的次日 02:00，正好是「本地当天 00:00–08:00」
# 那一段——此前整段都筛不出来。
_UTC_EVENING = "2026-08-29 18:00:00"
_LOCAL_DAY = "2026-08-30"      # 它在页面上显示成这一天
_UTC_DAY = "2026-08-29"        # 而库里的 date() 是这一天


@pytest.fixture()
def c(tmp_path, monkeypatch):
    """一条落在时区分界另一侧的日志，和一个同样时刻上传的附件。"""
    db = _fresh(tmp_path, monkeypatch)
    db.execute("INSERT INTO operation_logs (operator, action, target_type, target_id, "
               "detail, created_at) VALUES ('admin','update','certificates',1,"
               "'跨时区那条日志',?)", (_UTC_EVENING,))
    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
               "id_number,residence,political_status,work_unit,position_or_title,"
               "supervisor_unit,operator) VALUES (1,'甲','一','男','19900101',?,"
               "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')", (valid_id(1),))
    db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
               "id_number,destination_passport,category,travel_dates,need_new_passport,operator) "
               "VALUES (1,1,'总部','技术部','甲一','科长',?,'美国/护照','01',"
               "'2026/09/01-2026/09/11','否','admin')", (valid_id(1),))
    db.execute("INSERT INTO attachments (travel_id,file_name,file_path,file_type,file_size,"
               "uploaded_at) VALUES (1,'跨时区那份附件.pdf','x.pdf','个人申请报告',1024,?)",
               (_UTC_EVENING,))
    db.commit(); db.close()
    return _client()


def test_the_page_shows_the_local_day(c):
    """先确认前提：这条日志在页面上显示的是本地日期，不是 UTC 日期。

    筛选口径要对齐的正是「用户看到的那个日期」。
    """
    html = c.get("/logs/").get_data(as_text=True)
    assert f"{_LOCAL_DAY} 02:00:00" in html, "展示没走本地时区，本用例的前提不成立"


def test_filtering_logs_by_the_local_day_finds_it(c):
    """按页面上显示的那个日期筛——必须筛得到。

    此前 date(created_at) 拿的是 UTC 的 08-29，按 08-30 筛就整条漏掉。
    """
    html = c.get(f"/logs/?date_from={_LOCAL_DAY}&date_to={_LOCAL_DAY}").get_data(as_text=True)
    assert "跨时区那条日志" in html


def test_filtering_logs_by_the_utc_day_does_not_find_it(c):
    """按 UTC 那一天筛，反而不该筛到——否则等于口径又倒回去了。

    只断言「本地日期筛得到」是不够的：把判据写成「两天都命中」也能让上一条变绿。
    """
    html = c.get(f"/logs/?date_from={_UTC_DAY}&date_to={_UTC_DAY}").get_data(as_text=True)
    assert "跨时区那条日志" not in html


def test_attachment_overview_filters_by_the_local_day_too(c):
    """附件总览的上传日期筛选同病同治。"""
    hit = c.get(f"/travel/attachments?date_from={_LOCAL_DAY}&date_to={_LOCAL_DAY}")
    assert "跨时区那份附件" in hit.get_data(as_text=True)
    miss = c.get(f"/travel/attachments?date_from={_UTC_DAY}&date_to={_UTC_DAY}")
    assert "跨时区那份附件" not in miss.get_data(as_text=True)


def test_the_offset_is_spelled_once_and_survives_a_negative_value(c, monkeypatch):
    """偏移量只在 tz_modifier 里成形一次，且负偏移也拼得出合法修饰符。

    手写 '+' 的话，POTMS_TZ_OFFSET=-5 会拼出 '+-5 hours'——SQLite 不报错，
    只是悄悄忽略这个修饰符，筛选无声地退回 UTC 口径。
    """
    from utils.helpers import tz_modifier
    assert tz_modifier() == "+8 hours"
    monkeypatch.setattr(Config, "DISPLAY_TZ_OFFSET_HOURS", -5)
    assert tz_modifier() == "-5 hours"

    db = sqlite3.connect(Config.DATABASE)
    got = db.execute("SELECT date(?, ?)", (_UTC_EVENING, tz_modifier())).fetchone()[0]
    db.close()
    assert got == "2026-08-29", "负偏移没被 SQLite 认出来"


def test_the_year_dropdown_and_the_filter_agree(c):
    """年份下拉与日期筛选走同一个偏移量——它们本来就该说同一种时间。"""
    html = c.get("/logs/").get_data(as_text=True)
    assert "2026" in html


# ===========================================================================
# M3 换发 vs 订正：号码换了、两个日期都没动时停下来问一句
# ===========================================================================
@pytest.fixture()
def d(tmp_path, monkeypatch):
    """一个人、一条证照台账，护照 E1 有效期到 2035、上交日期 2025-01-01。"""
    db = _fresh(tmp_path, monkeypatch)
    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
               "id_number,residence,political_status,work_unit,position_or_title,"
               "supervisor_unit,operator) VALUES (1,'甲','一','男','19900101',?,"
               "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')", (valid_id(1),))
    db.execute("INSERT INTO certificates (id,personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (1,1,'总部','技术部','甲一','E1','20351231','20250101','admin')")
    db.commit(); db.close()
    return _client()


def _save(cl, **over):
    d_ = {"csrf_token": _tok(cl), "personnel_filing_id": "1", "unit": "总部",
          "department": "技术部", "name": "甲一",
          "passport_no": "E1", "passport_expiry": "20351231",
          "passport_submit_date": "20250101"}
    d_.update(over)
    return cl.post("/certificate/1/edit", data=d_, follow_redirects=True)


def test_changing_only_the_number_is_stopped_and_asked(d):
    """号码换了、两个日期都没动——挡下，并把两种情形都摆出来让人选。

    此前这里只 flash 一句提醒就放过去了，台账留着上一本证的有效期，
    到期预警与「有没有可用证件」校验双双失灵。
    """
    body = _save(d, passport_no="E99999999").get_data(as_text=True)
    assert "有效日期与上交日期都没有变动" in body
    assert "仅订正号码录入错误" in body, "只说错了、没告诉人另一种情形怎么办"
    assert 'data-block="correction-only"' in body, "没给出勾选框，人被卡死在这里"
    assert _one("SELECT passport_no FROM certificates WHERE id=1") == "E1", "挡下了却还是写进去了"


def test_a_renewal_with_new_dates_goes_through(d):
    """换发时把两个日期一并改成新证的——直接通过，不问。"""
    body = _save(d, passport_no="E99999999", passport_expiry="20360601",
                 passport_submit_date="20260701").get_data(as_text=True)
    assert "有效日期与上交日期都没有变动" not in body
    assert _one("SELECT passport_no FROM certificates WHERE id=1") == "E99999999"
    assert _one("SELECT passport_expiry FROM certificates WHERE id=1") == "20360601"


def test_ticking_correction_only_lets_a_typo_fix_through(d):
    """勾了「仅订正号码录入错误」——放行，日期原封不动。

    这是不能硬拦的那个理由：号码变化这个信号覆盖的不止换发。订正原先录错的
    号码时，它还是同一本证，日期本来就不该变。硬拦只会逼人去编一个假日期。
    """
    _save(d, passport_no="E00000001", correction_only="1")
    assert _one("SELECT passport_no FROM certificates WHERE id=1") == "E00000001"
    assert _one("SELECT passport_expiry FROM certificates WHERE id=1") == "20351231"
    assert _one("SELECT passport_submit_date FROM certificates WHERE id=1") == "20250101"


def test_the_log_records_which_of_the_two_it_was(d):
    """日志要分得出这次是换发还是订正——两件事在库里的痕迹本来一模一样。"""
    _save(d, passport_no="E00000001", correction_only="1")
    assert "仅订正号码录入错误" in (_one(
        "SELECT detail FROM operation_logs WHERE target_type='certificates' "
        "ORDER BY id DESC LIMIT 1") or "")

    _save(d, passport_no="E77777777", passport_expiry="20360601",
          passport_submit_date="20260701")
    assert "证件换发" in (_one(
        "SELECT detail FROM operation_logs WHERE target_type='certificates' "
        "ORDER BY id DESC LIMIT 1") or "")


def test_first_registration_is_not_a_renewal(d):
    """从空到有是首次登记，不问也不提醒——问了就是噪音。"""
    body = _save(d, hm_pass_no="C22222222", hm_pass_expiry="20351231",
                 hm_pass_submit_date="20250201").get_data(as_text=True)
    assert "都没有变动" not in body
    assert _one("SELECT hm_pass_no FROM certificates WHERE id=1") == "C22222222"


def test_the_checkbox_is_not_shown_when_nothing_is_wrong(d):
    """平时打开编辑页不出现这个勾选框——常驻的确认框会被人闭眼勾掉。"""
    assert 'data-block="correction-only"' not in c_get(d, "/certificate/1/edit")


def c_get(cl, url):
    return cl.get(url).get_data(as_text=True)


# ===========================================================================
# M4 撤销撤控：账面回到在库，实体证在哪儿没人知道
# ===========================================================================
@pytest.fixture()
def e(tmp_path, monkeypatch):
    """一个已撤控的人，名下台账还留着两本证，撤控时填了移交日期。"""
    db = _fresh(tmp_path, monkeypatch)
    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
               "id_number,residence,political_status,work_unit,position_or_title,"
               "supervisor_unit,status,operator) VALUES (1,'甲','一','男','19900101',?,"
               "'浙江宁波市鄞州区','群众','总部','科长','人事处','decontrolled','admin')",
               (valid_id(1),))
    db.execute("INSERT INTO certificates (personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,"
               "hm_pass_no,hm_pass_expiry,hm_pass_submit_date,operator) "
               "VALUES (1,'总部','技术部','甲一','E1','20351231','20250101',"
               "'C1','20351231','20250101','admin')")
    db.execute("INSERT INTO decontrol_filing (id,personnel_filing_id,surname,given_name,gender,"
               "birth_date,id_number,residence,political_status,work_unit,supervisor_unit,"
               "submit_unit_name,submit_unit_type,submit_contact,submit_phone,batch_no,"
               "reason,decontrol_date,cert_handover_date,operator) VALUES "
               "(1,1,'甲','一','男','19900101',?,'浙江宁波市鄞州区','群众','总部','人事处',"
               "'市公安局出入境管理局','公安','李四','0574-88888888','2026-001',"
               "'调离本单位','20260301','20260228','admin')", (valid_id(1),))
    db.commit(); db.close()
    return _client()


def test_revoking_says_the_documents_are_back_in_stock(e):
    """撤销撤控要说清：台账上那几本证此刻重新计入「在库」，请确认实体已收回。

    「挡下/提醒都要给数量明细」——只说「请注意证件」，操作员还得自己去数几本。
    """
    body = e.post("/decontrol/1/revoke", data={"csrf_token": _tok(e)},
                  follow_redirects=True).get_data(as_text=True)
    assert "2 本证件已重新计入「在库」" in body, "没给出本数"
    assert "20260228" in body, "没带上撤控时那个移交日期，人无从核对"
    assert "确认实体证件确已收回" in body


def test_the_stock_count_really_does_jump(e):
    """提醒说的是真的：撤销之前这两本不算在库，之后就算了。

    提醒的内容必须与系统实际做的事一致，否则它就是一句吓唬人的空话。
    """
    home = e.get("/").get_data(as_text=True)
    before = int(re.search(r'>(\d+)</div>\s*<small class="text-muted">在库（本）', home).group(1))
    assert before == 0, "已撤控人员的证不该算在库"

    e.post("/decontrol/1/revoke", data={"csrf_token": _tok(e)}, follow_redirects=True)
    home = e.get("/").get_data(as_text=True)
    after = int(re.search(r'>(\d+)</div>\s*<small class="text-muted">在库（本）', home).group(1))
    assert after == 2


def test_no_certificate_no_noise(e):
    """名下没有台账证件时不出这条提醒——没有错位就不该有告警。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("DELETE FROM certificates")
    db.commit(); db.close()
    body = e.post("/decontrol/1/revoke", data={"csrf_token": _tok(e)},
                  follow_redirects=True).get_data(as_text=True)
    assert "重新计入「在库」" not in body


# ===========================================================================
# M5 备案未关联信息登记表
# ===========================================================================
@pytest.fixture()
def f(tmp_path, monkeypatch):
    """两条备案：甲关联了信息表（有职级），乙没有（职级为空）。"""
    db = _fresh(tmp_path, monkeypatch)
    db.execute("INSERT INTO personnel_info (id,unit,department,name,gender,birth_date,"
               "id_number,rank,political_status,position,operator) VALUES "
               "(1,'总部','技术部','甲一','男','19900101',?,'四级主任科员','群众','科长','admin')",
               (valid_id(1),))
    db.execute("INSERT INTO personnel_filing (id,personnel_info_id,surname,given_name,gender,"
               "birth_date,id_number,residence,political_status,work_unit,position_or_title,"
               "supervisor_unit,operator) VALUES (1,1,'甲','一','男','19900101',?,"
               "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')", (valid_id(1),))
    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,"
               "birth_date,id_number,residence,political_status,work_unit,position_or_title,"
               "supervisor_unit,operator) VALUES (2,'乙','二','男','19900101',?,"
               "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')", (valid_id(2),))
    db.commit(); db.close()
    return _client()


def _names(html):
    body = html[html.find("<tbody"):html.find("</tbody>")]
    return {nm for nm in ("甲一", "乙二") if nm in body}


def test_unlinked_filings_can_be_listed_on_their_own(f):
    """新增筛选项：单独筛出未关联信息登记表的备案。"""
    assert _names(f.get("/personnel/?info_link=none").get_data(as_text=True)) == {"乙二"}
    assert _names(f.get("/personnel/?info_link=linked").get_data(as_text=True)) == {"甲一"}
    assert _names(f.get("/personnel/").get_data(as_text=True)) == {"甲一", "乙二"}


def test_rank_filter_still_behaves_as_sql_says(f):
    """按职级筛，未关联信息表的那条筛不出来——这不是 bug，那个人确实没登记职级。

    改的不是 SQL，是让用户知道自己看到的是子集。
    """
    assert _names(f.get("/personnel/?rank=四级主任科员").get_data(as_text=True)) == {"甲一"}


def test_rank_filter_says_how_many_it_cannot_reach(f):
    """用职级筛选时出现提示：另有几条备案没有职级，怎么筛都不会出现。"""
    html = f.get("/personnel/?rank=四级主任科员").get_data(as_text=True)
    i = html.find('data-block="unlinked-info-hint"')
    assert i != -1, "按职级筛选时没有提示存在筛不到的那批人"
    hint = html[i:i + 600]
    assert "1" in hint, "没给出条数"
    assert "info_link=none" in hint, "没给出直接查看那批人的链接"


def test_the_hint_stays_out_of_the_way_when_not_filtering_by_rank(f):
    """不按职级筛时不出现——常驻提示会变成常驻噪音，然后没人看。"""
    assert 'data-block="unlinked-info-hint"' not in f.get("/personnel/").get_data(as_text=True)


def test_no_hint_when_every_filing_is_linked(f):
    """所有备案都关联了信息表时也不出现。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("DELETE FROM personnel_filing WHERE id=2")
    db.commit(); db.close()
    html = f.get("/personnel/?rank=四级主任科员").get_data(as_text=True)
    assert 'data-block="unlinked-info-hint"' not in html

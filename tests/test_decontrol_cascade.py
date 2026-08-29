"""撤控的下游影响（第 5 批 B1/B2）：告警口径、台账标注、以及撤销撤控。

撤控此前只做了一件事——把 personnel_filing.status 改成 decontrolled——然后就不管了。
可这个状态是**在办范围**的定义：撤控意味着这个人不归本单位管了。于是两头都出问题：

- B1 告警与台账没跟上：首页与出行列表照旧把他的逾期证件报出来，而这条告警**谁也
  处理不掉**（人已经不在管理范围内，归还入口也不给他开）；证照台账里他那本证还
  混在「在库」里参与到期预警，实际早就随撤控移交出去了。
- B2 撤控是一扇单向门：撤错了一个人，界面上没有任何回头路——他从发起撤控的下拉、
  出行申请的选人、首页统计里同时消失，业务彻底办不了，只能去改库。

两条合起来才闭环：撤控要「干净地摘出去」，也要「摘错了能放回来」。
"""
import re
import sqlite3

import pytest

from config import Config

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = "110101199001012133"


@pytest.fixture()
def c(tmp_path, monkeypatch):
    """两个人：#1 撤控在即，#2 全程保持在控，用来证明守卫没有误伤在控人员。

    #1 名下：一条领用后逾期未还的出行 + 一本 15 天后到期的护照。
    #2 名下：同样的一条逾期出行 + 同样快到期的护照。
    """
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()

    from datetime import datetime, timedelta
    soon = (datetime.now() + timedelta(days=15)).strftime("%Y%m%d")
    long_ago = (datetime.now() - timedelta(days=120)).strftime("%Y%m%d")

    db = sqlite3.connect(Config.DATABASE)
    for pid, nm in ((1, "撤控张三"), (2, "在控李四")):
        db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
                   "id_number,residence,political_status,work_unit,position_or_title,"
                   "supervisor_unit,operator) VALUES (?,?,'','男','19900101',?,"
                   "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')",
                   (pid, nm, _VALID_ID))
        db.execute("INSERT INTO certificates (id,personnel_filing_id,unit,department,name,"
                   "passport_no,passport_expiry,passport_submit_date,operator) "
                   "VALUES (?,?,'总部','技术部',?,?,?,'20250101','admin')",
                   (pid, pid, nm, f"E1000000{pid}", soon))
        # 领用后逾期未还：行程早已结束，证还没回来
        db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
                   "position,id_number,destination_passport,category,travel_dates,travel_start,"
                   "travel_end,need_new_passport,passport_collect_date,operator) VALUES "
                   "(?,?,'总部','技术部',?,'科长',?,'美国/护照','01','历史批次',?,?,'否',?,'admin')",
                   (pid, pid, nm, _VALID_ID, long_ago, long_ago, long_ago))
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


def _overdue_count(cl):
    """首页逾期那张卡上的数（单位：本）。

    首页原来还有一张列名单的卡，可以按姓名断言；那张卡与数字卡是同一份数据，
    重复了，已删。现在名单在出国明细列表上，首页只留这个数。
    """
    html = cl.get("/").get_data(as_text=True)
    m = re.search(r'>(\d+)</div>\s*<small class="text-muted">其中逾期（本）', html)
    assert m, "首页上找不到逾期那张卡"
    return int(m.group(1))


def _between(html, start, end):
    """截出页面上某一块，避免拿整页做「不包含某人」的断言。

    页面上到处都是姓名（近期出行、台账行本身），整页断言既会误报也会漏报——
    要看的是**告警块里点没点这个人的名**。
    """
    assert start in html, f"页面上找不到「{start}」这一块"
    tail = html.split(start, 1)[1]
    return tail.split(end, 1)[0] if end in tail else tail


def _decontrol_1(handover="20260301"):
    """把 1 号办成已撤控。

    直接写库而不是走 /decontrol/new：第 4 批的前置校验（证没清完不许撤控）会把
    这条挡下——而 B1 要守的恰恰是**校验上线之前**就已经这样躺在库里的历史数据，
    以及任何绕过界面产生的同类状态。用界面造不出来的状态，就直接造。
    """
    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO decontrol_filing (id,personnel_filing_id,surname,given_name,"
               "gender,birth_date,id_number,residence,political_status,work_unit,"
               "supervisor_unit,submit_unit_name,submit_unit_type,submit_contact,"
               "submit_phone,batch_no,reason,decontrol_date,cert_handover_date,operator) "
               "VALUES (7,1,'撤控','张三','男','19900101',?,'浙江宁波市鄞州区','群众',"
               "'总部','人事处','某某国资委','01','王五','13800000000','2026-01',"
               "'调离本单位','20260301',?,'admin')", (_VALID_ID, handover))
    db.execute("UPDATE personnel_filing SET status='decontrolled' WHERE id=1")
    db.commit(); db.close()


# ---------------------------------------------------------------------------
# B1 撤控后的告警与台账
# ---------------------------------------------------------------------------
def test_dashboard_overdue_drops_decontrolled_person(c):
    """首页「证件逾期未还」不再把已撤控的人算进去——这条告警没人处理得掉。"""
    assert _overdue_count(c) == 2, "前提不成立：撤控前首页本就没把两个人都算上"
    _decontrol_1()
    assert _overdue_count(c) == 1, "已撤控人员仍被算进首页逾期数（或把在控的也一并抹掉了）"


def test_travel_list_drops_decontrolled_overdue(c):
    """出行列表的逾期红条与「逾期未还」筛选，同样只认在控人员。"""
    _decontrol_1()
    banner = _between(c.get("/travel/").get_data(as_text=True), "证件逾期未还：", "</div>")
    assert "撤控张三" not in banner, "已撤控人员仍在逾期红条里被点名"
    assert "在控李四" in banner

    filtered = c.get("/travel/?passport_status=overdue").get_data(as_text=True)
    assert "撤控张三" not in filtered, "「逾期未还」筛选仍捞出已撤控人员"
    assert "在控李四" in filtered


def test_certificate_ledger_marks_handover(c):
    """台账要一眼看出这本证已随撤控移交，且不再参与到期预警。"""
    warn = lambda h: _between(h, "证照即将到期（30天内）：", "</div>")
    assert "撤控张三" in warn(c.get("/certificate/").get_data(as_text=True)), \
        "前提不成立：撤控前本就没有这个人的到期预警"

    _decontrol_1(handover="20260315")
    html = c.get("/certificate/").get_data(as_text=True)
    assert "已撤控" in html and "20260315" in html, "台账上没标出已撤控与移交日期"
    assert "撤控张三" not in warn(html), "已撤控人员的证照仍在到期预警里"
    assert "在控李四" in warn(html), "在控人员的到期预警被一起抹掉了"


# ---------------------------------------------------------------------------
# B2 撤销撤控
# ---------------------------------------------------------------------------
def test_revoke_restores_person_and_deletes_record(c):
    """撤销撤控：人回到「有效」，那条撤控记录物理删除。"""
    _decontrol_1()
    r = c.post("/decontrol/7/revoke", data={"csrf_token": _tok(c)}, follow_redirects=True)
    assert r.status_code == 200
    assert _scalar("SELECT status FROM personnel_filing WHERE id=1") == "active"
    assert _scalar("SELECT COUNT(*) FROM decontrol_filing WHERE id=7") == 0


def test_revoke_logs_full_snapshot(c):
    """物理删除的前提是日志留得住——快照里要能查回撤控原因这类只此一份的信息。"""
    _decontrol_1()
    c.post("/decontrol/7/revoke", data={"csrf_token": _tok(c)}, follow_redirects=True)
    snap = _scalar("SELECT snapshot FROM operation_logs WHERE target_type='decontrol_filing' "
                   "AND action='delete' ORDER BY id DESC LIMIT 1")
    assert snap, "撤销撤控没有写操作日志——记录删了就再也查不回来了"
    for want in ("调离本单位", "某某国资委", "2026-01"):
        assert want in snap, f"日志快照里缺少「{want}」，这条信息只此一份：{snap}"


def test_revoked_person_is_back_in_business(c):
    """撤销之后这个人要真的能重新办事——状态回滚不是改个字段就完了。

    撤控把人从所有在办入口里摘掉了（发起撤控的下拉只列 active，告警口径也只认
    active）。撤销如果只把字段改回去而没让这些地方重新认他，等于没撤销。
    """
    _decontrol_1()
    assert _overdue_count(c) == 1

    c.post("/decontrol/7/revoke", data={"csrf_token": _tok(c)}, follow_redirects=True)
    assert _overdue_count(c) == 2, "撤销后逾期告警没有回来"
    # 撤控列表页的「发起撤控」下拉只列 active 人员
    picker = _between(c.get("/decontrol/").get_data(as_text=True),
                      'id="decPersonSelect"', "</select>")
    assert "撤控张三" in picker, "撤销后这个人没有回到「发起撤控」的可选名单里"


def test_revoke_entry_points_exist(c):
    """列表与详情页都要有入口——只在详情页给，等于要求先知道去哪找。"""
    _decontrol_1()
    assert "/decontrol/7/revoke" in c.get("/decontrol/").get_data(as_text=True)
    assert "/decontrol/7/revoke" in c.get("/decontrol/7").get_data(as_text=True)


def test_revoke_missing_record_is_harmless(c):
    """撤销一条不存在的记录不能 500——重复点确认、后退再提交都会走到这里。"""
    r = c.post("/decontrol/999/revoke", data={"csrf_token": _tok(c)}, follow_redirects=True)
    assert r.status_code == 200
    assert "记录不存在" in r.get_data(as_text=True)

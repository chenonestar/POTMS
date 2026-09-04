"""编辑路径的校验必须与新增一样严。

这批修的两条是同一个毛病：**新增守得住、编辑守不住**。写新增校验时人在想
「不能让脏数据进来」，写编辑时想的是「别把用户已经填好的东西判成错」，于是
一路放宽，宽到把关也放掉了。

H1 身份证号唯一性
  - info_edit 根本不查重，可以把甲的身份证改成乙的，造出两张同号信息登记表；
  - filing_edit 以 skip_id_dup_check=True 调用校验，整条跳过。那个参数的本意是
    「别把自己判成重复」，代价却是「改成别人的号码」也一并放行。
    **排除自身**（id != ?）与**放弃检查**，差的就是这一条。
  这条不变量下游一大片东西在依赖：撤控重报关联按 id_number 找旧记录、批量导入
  查重、全局搜索、按人汇总的告警。同号一出现，这些地方全会指错人。

M1 必传附件
  travel.new 校验必传附件，travel.edit 不校验。而编辑页上就有逐个删除附件的
  按钮——删光后保存，返回 200，附件仍为 0，一条缺《个人申请报告》《审批表》
  的办件就这么留在库里。附件总览的「缺件检查」明明报了它，编辑页却不拦。

两条都还各带一个「顺带」：
  - 唯一性同时落到库层（部分唯一索引），并对存量同号数据出常驻告警；
  - 「是否做证」从否改成是时，路径B 才要求的《同意申办函》现在也会被要求。
"""
import io
import re
import sqlite3

import pytest

from config import Config
from conftest import seed_required_attachments, valid_id

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    return database


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
# H1 身份证号唯一性
# ===========================================================================
@pytest.fixture()
def c(tmp_path, monkeypatch):
    """两个人，各有一张信息登记表和一条有效备案，身份证号不同。"""
    database = _fresh(tmp_path, monkeypatch)
    database.init_db(); database.run_migrations(); database.seed_data()
    db = sqlite3.connect(Config.DATABASE)
    for pid, nm, gn in ((1, "甲", "一"), (2, "乙", "二")):
        db.execute("INSERT INTO personnel_info (id,unit,department,name,gender,birth_date,"
                   "id_number,rank,political_status,position,operator) VALUES "
                   "(?,'总部','技术部',?,'男','19900101',?,'四级主任科员','群众','科长','admin')",
                   (pid, nm + gn, valid_id(pid)))
        db.execute("INSERT INTO personnel_filing (id,personnel_info_id,surname,given_name,gender,"
                   "birth_date,id_number,residence,political_status,work_unit,position_or_title,"
                   "supervisor_unit,tag,informed,operator) VALUES (?,?,?,?,'男','19900101',?,"
                   "'浙江宁波市鄞州区','群众','总部','科长','人事处','新增','是','admin')",
                   (pid, pid, nm, gn, valid_id(pid)))
    db.commit(); db.close()
    return _client()


def _info_payload(cl, name, id_number):
    return {"csrf_token": _tok(cl), "unit": "总部", "department": "技术部", "name": name,
            "gender": "男", "birth_date": "19900101", "id_number": id_number,
            "work_start_date": "20120701", "education": "本科", "degree": "学士",
            "title": "工程师", "rank": "四级主任科员",
            "political_status": "群众", "position": "科长"}


def _filing_payload(cl, surname, id_number, given_name="一", **over):
    d = {"csrf_token": _tok(cl), "surname": surname, "given_name": given_name, "gender": "男",
         "birth_date": "19900101", "id_number": id_number, "residence": "浙江宁波市鄞州区",
         "political_status": "群众", "work_unit": "总部", "position_or_title": "科长",
         "supervisor_unit": "人事处", "tag": "新增", "informed": "是"}
    d.update(over)
    return d


def test_info_edit_cannot_steal_another_persons_id_number(c):
    """把甲的信息登记表改成乙的身份证号——拦下。

    此前 info_edit 只调 _validate_info_form，一个字的查重都没有。
    """
    r = c.post("/personnel/info/1/edit", data=_info_payload(c, "甲", valid_id(2)),
               follow_redirects=True)
    assert "已属于另一张信息登记表" in r.get_data(as_text=True)
    assert _one("SELECT id_number FROM personnel_info WHERE id=1") == valid_id(1), \
        "被拦下了却还是写进去了"
    assert _one("SELECT COUNT(*) FROM personnel_info WHERE id_number=?", valid_id(2)) == 1


def test_info_edit_can_still_save_its_own_number(c):
    """改别的字段、身份证号不动——必须放行。

    这条守的是「排除自身」而不是「放弃检查」：少了 id != ?，
    每个人一打开自己的表就被判成重复，编辑功能等于废掉。
    """
    r = c.post("/personnel/info/1/edit",
               data=_info_payload(c, "甲改名", valid_id(1)), follow_redirects=True)
    assert "已属于另一张" not in r.get_data(as_text=True)
    assert _one("SELECT name FROM personnel_info WHERE id=1") == "甲改名"


def test_filing_edit_cannot_steal_another_persons_id_number(c):
    """把甲的备案改成乙的身份证号——拦下。

    此前这里传 skip_id_dup_check=True，整条跳过，实测能造出两条同号有效备案。
    """
    r = c.post("/personnel/filing/1/edit", data=_filing_payload(c, "甲", valid_id(2)),
               follow_redirects=True)
    assert "已存在有效备案记录" in r.get_data(as_text=True)
    assert _one("SELECT id_number FROM personnel_filing WHERE id=1") == valid_id(1)
    assert _one("SELECT COUNT(*) FROM personnel_filing WHERE id_number=? AND status='active'",
                valid_id(2)) == 1


def test_filing_edit_can_still_save_its_own_number(c):
    """备案编辑不动号码时照样能改别的字段。"""
    c.post("/personnel/filing/1/edit",
           data=_filing_payload(c, "甲", valid_id(1), work_unit="分部"), follow_redirects=True)
    assert _one("SELECT work_unit FROM personnel_filing WHERE id=1") == "分部"


def test_a_decontrolled_record_does_not_hold_the_number(c):
    """撤控之后拿同一个号码重新报备——必须放行。

    备案表的唯一性只在 status='active' 范围内成立：撤控后重报是正常业务，
    filing_new 还会主动去找那条已撤控的旧记录建立新旧关联。写成全量唯一，
    这条路就断了。
    """
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE personnel_filing SET status='decontrolled' WHERE id=1")
    db.commit(); db.close()

    c.post("/personnel/filing/new", data=_filing_payload(c, "甲", valid_id(1)),
           follow_redirects=True)
    assert _one("SELECT COUNT(*) FROM personnel_filing WHERE id_number=? AND status='active'",
                valid_id(1)) == 1, "撤控后重新报备被误拦"


def test_the_invariant_is_also_enforced_by_the_database(c):
    """两条唯一索引确实建上了——应用层校验挡不住并发，也挡不住直接改库。"""
    db = sqlite3.connect(Config.DATABASE)
    idx = {r[1]: r[2] for r in db.execute("PRAGMA index_list(personnel_filing)")}
    assert idx.get("ux_pf_active_id_number") == 1, "备案表的部分唯一索引没建上"
    idx2 = {r[1]: r[2] for r in db.execute("PRAGMA index_list(personnel_info)")}
    assert idx2.get("ux_info_id_number") == 1, "信息表的唯一索引没建上"

    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO personnel_filing (surname,given_name,gender,birth_date,"
                   "id_number,residence,political_status,work_unit,position_or_title,"
                   "supervisor_unit,operator) VALUES ('丙','三','男','19900101',?,"
                   "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')", (valid_id(1),))
    db.close()


def test_empty_id_numbers_do_not_collide(c):
    """空号码不参与唯一性——空不是一个号码，多条空值不代表撞了同一个人。

    索引的 WHERE 子句里写了这一条，漏掉的话第二条空号码记录就插不进去。
    """
    db = sqlite3.connect(Config.DATABASE)
    for nm in ("丙", "丁"):
        db.execute("INSERT INTO personnel_info (unit,department,name,gender,birth_date,"
                   "id_number,rank,political_status,position,operator) VALUES "
                   "('总部','技术部',?,'男','19900101','','四级主任科员','群众','科长','admin')",
                   (nm,))
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM personnel_info WHERE id_number=''").fetchone()[0] == 2
    db.close()

    from blueprints.personnel import duplicate_id_numbers
    from app import create_app
    with create_app().app_context():
        assert duplicate_id_numbers()["info"] == [], "体检把空号码当成了重复"


# ---------------------------------------------------------------------------
# 存量体检：库里已经有同号数据时
# ---------------------------------------------------------------------------
@pytest.fixture()
def dirty(tmp_path, monkeypatch):
    """先造出两条同号的有效备案，再跑迁移——模拟「校验补上之前就已经脏了的库」。"""
    database = _fresh(tmp_path, monkeypatch)
    database.init_db()
    db = sqlite3.connect(Config.DATABASE)
    for pid, nm, gn in ((1, "甲", "一"), (2, "甲", "分身")):
        db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
                   "id_number,residence,political_status,work_unit,position_or_title,"
                   "supervisor_unit,operator) VALUES (?,?,?,'男','19900101',?,"
                   "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')",
                   (pid, nm, gn, valid_id(1)))
    db.commit(); db.close()
    database.run_migrations(); database.seed_data()   # 不能因为脏数据就起不来
    return _client()


def test_dirty_data_does_not_block_startup(dirty):
    """存量同号时，迁移不报错、系统照常起得来。

    数据是真实的，不能为了建一个索引把人挡在系统外面。索引建不上就先不建。
    """
    db = sqlite3.connect(Config.DATABASE)
    names = {r[1] for r in db.execute("PRAGMA index_list(personnel_filing)")}
    db.close()
    assert "ux_pf_active_id_number" not in names, "有重复数据却把唯一索引建上了？"
    assert dirty.get("/personnel/").status_code == 200


def test_dirty_data_is_reported_where_someone_will_act_on_it(dirty):
    """人员备案列表顶部常驻告警，点名是哪个号码、几条，并给出筛出它们的链接。

    「挡下/提醒都要给数量明细」——只说「存在重复数据」，操作员还得自己去翻。
    常驻而不是 flash 一次：这是一笔待办，订正干净之前它就该一直在。
    """
    html = dirty.get("/personnel/").get_data(as_text=True)
    i = html.find('data-block="dup-id-numbers"')
    assert i != -1, "列表页没有存量同号告警"
    block = html[i:html.find("</div>", html.find("</div>", i) + 1) + 6]
    block = html[i:i + 1200]
    assert valid_id(1) in block, "告警没点名是哪个号码"
    assert "共 2 条" in block, "告警没给条数"
    assert f"search={valid_id(1)}" in block, "告警没给能筛出这几条的链接"


def test_the_banner_is_absent_when_the_data_is_clean(c):
    """数据干净时不出现这条告警——常驻告警一旦变成常驻噪音就没人看了。"""
    assert 'data-block="dup-id-numbers"' not in c.get("/personnel/").get_data(as_text=True)


# ===========================================================================
# M1 编辑出国申请时的必传附件
# ===========================================================================
@pytest.fixture()
def t(tmp_path, monkeypatch):
    """一个人、一本在有效期内的护照、一条路径A 的出行申请，附件齐全。"""
    database = _fresh(tmp_path, monkeypatch)
    database.init_db(); database.run_migrations(); database.seed_data()
    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
               "id_number,residence,political_status,work_unit,position_or_title,"
               "supervisor_unit,operator) VALUES (1,'甲','','男','19900101',?,"
               "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')", (valid_id(1),))
    db.execute("INSERT INTO certificates (personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (1,'总部','技术部','甲','E1','20351231','20250101','admin')")
    db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
               "id_number,destination_passport,category,travel_dates,need_new_passport,operator) "
               "VALUES (1,1,'总部','技术部','甲','科长',?,'美国/护照','01',"
               "'2026/09/01-2026/09/11','否','admin')", (valid_id(1),))
    seed_required_attachments(db, 1, "否")
    db.commit(); db.close()
    return _client()


def _edit(cl, **over):
    d = {"csrf_token": _tok(cl), "personnel_filing_id": "1", "unit": "总部",
         "department": "技术部", "name": "甲", "position": "科长",
         "id_number": valid_id(1), "destination_passport": "美国/护照", "category": "01",
         "travel_dates": "2026/09/01-2026/09/11", "need_new_passport": "否",
         "approval_date": "20260801", "intended_cert_type": "01"}
    d.update(over)
    return cl.post("/travel/1/edit", data=d, follow_redirects=True)


def _att_ids():
    db = sqlite3.connect(Config.DATABASE)
    ids = [r[0] for r in db.execute("SELECT id FROM attachments WHERE travel_id=1 ORDER BY id")]
    db.close()
    return ids


def test_editing_without_touching_attachments_is_fine(t):
    """只改个日期，不重传附件——必须放行。

    这是本条修复最容易做错的方向：直接把新增那套「看 request.files」的校验
    搬过来，编辑一次就得把附件全部重传一遍。库里已有的必须算数。
    """
    r = _edit(t, travel_dates="2026/10/01-2026/10/11")
    assert "为必传项" not in r.get_data(as_text=True)
    assert _one("SELECT travel_dates FROM travel_details WHERE id=1") == "2026/10/01-2026/10/11"


def test_saving_after_deleting_every_attachment_is_refused(t):
    """把附件删光再保存——挡下，记录一个字都没改。

    这正是报出来的那个洞：此前返回 200、附件仍为 0，办件完整性没了。
    """
    for aid in _att_ids():
        t.post(f"/travel/attachment/{aid}/delete", data={"csrf_token": _tok(t)},
               follow_redirects=True)
    assert _att_ids() == []

    r = _edit(t, travel_dates="2026/10/01-2026/10/11")
    body = r.get_data(as_text=True)
    assert "《个人申请报告》为必传项" in body and "《审批表》为必传项" in body
    assert _one("SELECT travel_dates FROM travel_details WHERE id=1") == "2026/09/01-2026/09/11", \
        "被拦下了，记录却还是改了"


def test_deleting_an_attachment_says_what_is_now_missing(t):
    """删除当场就点名缺了什么，不等到保存被拒才说。

    删除本身不拦——换一份传错的扫描件本来就得先删再传。但人删完可能就走开了，
    缺了什么必须当场讲清楚。
    """
    r = t.post(f"/travel/attachment/{_att_ids()[0]}/delete",
               data={"csrf_token": _tok(t)}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "现缺少必备附件" in body and "《个人申请报告》" in body
    assert "保存会被拒绝" in body, "没告诉人后果，提醒就只是句废话"


def test_switching_to_path_b_now_requires_the_consent_letter(t):
    """把「是否做证」从否改成是——《同意申办函》当场成为必传项。

    这个口子报告里没提：路径由**表单提交上来的值**决定，不是库里的旧值。
    照着旧值判，改路径就能绕过路径B 专有的那一件。
    """
    r = _edit(t, need_new_passport="是")
    assert "《同意申办函》为必传项" in r.get_data(as_text=True)
    assert _one("SELECT need_new_passport FROM travel_details WHERE id=1") == "否"


def test_uploading_the_missing_one_in_the_same_save_works(t):
    """本次一并补传的也算数——库里已有的 ＋ 这次传的，合起来判。"""
    r = _edit(t, need_new_passport="是",
              att_consent=(io.BytesIO(_PDF), "同意申办函.pdf"))
    assert "为必传项" not in r.get_data(as_text=True)
    assert _one("SELECT need_new_passport FROM travel_details WHERE id=1") == "是"
    assert _one("SELECT COUNT(*) FROM attachments WHERE travel_id=1 AND file_type='同意申办函'") == 1


def test_the_overview_check_and_the_save_check_are_the_same_function(t):
    """附件总览的「缺件检查」与保存校验同源。

    此前一个报缺件、另一个放行，正是各写一套（准确说是编辑那处压根没有）
    造成的。这里直接断言两边说的是同一件事。
    """
    for aid in _att_ids():
        t.post(f"/travel/attachment/{aid}/delete", data={"csrf_token": _tok(t)},
               follow_redirects=True)

    from blueprints.travel import lacking_attachment_types
    from app import create_app
    with create_app().app_context():
        lack = lacking_attachment_types(1, "否")
    assert lack == ["个人申请报告", "审批表"]

    overview = t.get("/travel/attachments").get_data(as_text=True)
    assert "个人申请报告" in overview and "审批表" in overview

    saved = _edit(t).get_data(as_text=True)
    for item in lack:
        assert f"《{item}》为必传项" in saved, f"总览说缺 {item}，保存却不提"


def test_creating_still_requires_them_all(t):
    """新增那一侧的绝对判据没被改松——重构时最容易顺手弄丢的就是它。"""
    r = t.post("/travel/new", data={
        "csrf_token": _tok(t), "personnel_filing_id": "1", "unit": "总部",
        "department": "技术部", "name": "甲", "position": "科长",
        "id_number": valid_id(1), "destination_passport": "日本/护照", "category": "01",
        "travel_dates": "2026/11/01-2026/11/11", "need_new_passport": "否",
        "approval_date": "20260801", "intended_cert_type": "01",
    }, follow_redirects=True)
    assert "《个人申请报告》为必传项" in r.get_data(as_text=True)
    assert _one("SELECT COUNT(*) FROM travel_details") == 1, "缺件却建出了新申请"

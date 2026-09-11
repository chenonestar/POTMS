"""第 13 批：一本证同时只能在一个人手上——落到库层。

这条规则从第 1 批就有，但一直只是应用层的**先查后插**：先 SELECT 有没有人
占着，没有就 INSERT。两个请求同时进来时，两句 SELECT 都在对方 INSERT 之前
跑完，于是两个都「查到没人占用」。

实测（起真的 waitress，6 个独立会话卡在同一瞬间提交）：

    6 张领用单全部写进库，全是 issued
    在库 0 + 借出未还 1 = 1（恒等式照样平）
    领用列表 issued 6 行，首页「借出未还（本）」1 → 对不上

**而且这跟「上不上网」无关。** 领用表单原先没有 disable-on-submit，
一次双击「保存」就是两个 POST，实测同样复现——单人、单机、一个浏览器。
签名板画完字点保存，页面要编码 PNG、写 BLOB、跑一堆校验，慢半拍很正常，
人下意识就会再点一下。

更要紧的是另外四版：Go / Rust / .NET / Java 的领用校验里**一条号码查重
都没有**（已逐个核过源码），`cert_nos` 连必填都不是。五版共享同一个
data.db，从那边录进来的账，Python 版下次启动照单全收。

所以修在库层——索引是库的属性，不是某一版的代码，五版一视同仁：

    CREATE UNIQUE INDEX ux_issuance_active_cert_no ON cert_issuance(cert_nos)
        WHERE status = 'issued' AND cert_nos IS NOT NULL AND cert_nos != ''

「部分」那个 WHERE 是要点：**只在「已领用未归还」这一档内唯一**。
还了再借、作废后重录都是正常业务，全表唯一会把它们一起误拦。
"""
import re
import sqlite3

import pytest

from config import Config
from conftest import valid_id

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_PNG = __import__("tests.test_issuance", fromlist=["_PNG_DATA_URL"])._PNG_DATA_URL


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()
    return sqlite3.connect(Config.DATABASE)


def _seed(db, n=2):
    """n 个人，各一本护照 E000i，各一条已批准的出国申请。"""
    for i in range(1, n + 1):
        db.execute(
            "INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,"
            "residence,political_status,work_unit,position_or_title,supervisor_unit,status,operator) "
            "VALUES (?,?,'一','男','19900101',?,'浙江宁波市鄞州区','群众','总部','科长','人事处',"
            "'active','admin')", (i, f"人{i}", valid_id(i)))
        db.execute(
            "INSERT INTO certificates (personnel_filing_id,unit,department,name,passport_no,"
            "passport_expiry,passport_submit_date,operator) "
            "VALUES (?,'总部','技术部',?,?,'20351231','20250101','admin')",
            (i, f"人{i}一", f"E{i:04d}"))
        db.execute(
            "INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
            "id_number,destination_passport,intended_cert_type,category,travel_dates,travel_start,"
            "travel_end,approval_date,need_new_passport,operator) "
            "VALUES (?,?,'总部','技术部',?,'科长',?,'美国','01','01',"
            "'2026/12/01-2026/12/11','20261201','20261211','20260101','否','admin')",
            (i, i, f"人{i}一", valid_id(i)))
        from conftest import seed_required_attachments
        seed_required_attachments(db, i, "否")


def _client():
    from app import create_app
    cl = create_app().test_client()
    tok = _CSRF.search(cl.get("/login").get_data(as_text=True)).group(1)
    cl.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return cl


def _tok(cl):
    return _CSRF.search(cl.get("/").get_data(as_text=True)).group(1)


def _one(sql, *p):
    d = sqlite3.connect(Config.DATABASE)
    try:
        r = d.execute(sql, p).fetchone()
        return r[0] if r else None
    finally:
        d.close()


@pytest.fixture()
def cl(tmp_path, monkeypatch):
    db = _fresh(tmp_path, monkeypatch)
    _seed(db, 2)
    db.commit(); db.close()
    return _client()


def _issue(cl, travel_id=1, cert_nos="E0001", **over):
    d = {"csrf_token": _tok(cl), "travel_id": str(travel_id),
         "personnel_filing_id": str(travel_id), "holder_name": f"人{travel_id}一",
         "id_number": valid_id(travel_id), "cert_types": "01", "cert_nos": cert_nos,
         "issue_date": "20260901", "sign_png": _PNG, "sign_meta": "{}"}
    d.update(over)
    return cl.post("/issuance/new", data=d, follow_redirects=True)


# ===========================================================================
# 一、索引本身
# ===========================================================================
def test_the_index_exists(cl):
    """迁移把索引建上了。"""
    sql = _one("SELECT sql FROM sqlite_master WHERE type='index' "
               "AND name='ux_issuance_active_cert_no'")
    assert sql, "索引没建上"
    assert "status = 'issued'" in sql, "不是部分索引——全表唯一会误拦「还了再借」"


def test_the_database_itself_refuses_a_second_active_row(cl):
    """绕开整个应用层，直接往库里插第二张同号未归还单——库必须拒绝。

    这一条是整批的地基：它证明保护不在 Python 代码里，而在库里。
    另外四版没有任何号码查重，能管住它们的只有这个。
    """
    _issue(cl)
    assert _one("SELECT COUNT(*) FROM cert_issuance") == 1
    d = sqlite3.connect(Config.DATABASE)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            d.execute(
                "INSERT INTO cert_issuance (travel_id,personnel_filing_id,holder_name,id_number,"
                "cert_types,cert_nos,issue_date,issuer,status,operator) "
                "VALUES (2,2,'人2一',?,'01','E0001','20260901','admin','issued','admin')",
                (valid_id(2),))
            d.commit()
    finally:
        d.close()


# ===========================================================================
# 二、正常业务不能被误拦（部分索引的 WHERE 就是为它们写的）
# ===========================================================================
def test_borrowing_again_after_returning_is_allowed(cl):
    """还了之后再借同一本证——放行。全表唯一会把这条最普通的流程拦死。"""
    _issue(cl)
    iss_id = _one("SELECT id FROM cert_issuance")
    r = cl.post(f"/issuance/{iss_id}/return",
                data={"csrf_token": _tok(cl), "return_date": "20260910",
                      "sign_png": _PNG, "sign_meta": "{}"}, follow_redirects=True)
    assert _one("SELECT status FROM cert_issuance WHERE id=?", iss_id) == "returned", \
        r.get_data(as_text=True)[:300]
    _issue(cl, travel_id=2, cert_nos="E0001",
           personnel_filing_id="2", holder_name="人2一", id_number=valid_id(2))
    assert _one("SELECT COUNT(*) FROM cert_issuance") == 2


def test_reissuing_after_voiding_is_allowed(cl):
    """作废之后重新登记——放行。"""
    _issue(cl)
    iss_id = _one("SELECT id FROM cert_issuance")
    cl.post(f"/issuance/{iss_id}/void",
            data={"csrf_token": _tok(cl), "void_reason": "登记有误"}, follow_redirects=True)
    assert _one("SELECT status FROM cert_issuance WHERE id=?", iss_id) == "voided"
    _issue(cl)
    assert _one("SELECT COUNT(*) FROM cert_issuance WHERE status='issued'") == 1


def test_two_different_certificates_are_fine(cl):
    """反向对照：不同号码各借各的，别把索引写成谁也过不去。"""
    _issue(cl, travel_id=1, cert_nos="E0001")
    _issue(cl, travel_id=2, cert_nos="E0002",
           personnel_filing_id="2", holder_name="人2一", id_number=valid_id(2))
    assert _one("SELECT COUNT(*) FROM cert_issuance WHERE status='issued'") == 2


# ===========================================================================
# 三、撞上索引时要说人话，不能 500
# ===========================================================================
def _occupy(cert_nos="E0001"):
    """直接往库里塞一张同号未归还单（不走 HTTP）。"""
    d = sqlite3.connect(Config.DATABASE)
    d.execute(
        "INSERT INTO cert_issuance (travel_id,personnel_filing_id,holder_name,id_number,"
        "cert_types,cert_nos,issue_date,issuer,status,operator) "
        "VALUES (2,2,'人2一',?,'01',?,'20260901','admin','issued','admin')",
        (valid_id(2), cert_nos))
    d.commit(); d.close()


def _simulate_race(monkeypatch):
    """模拟并发窗口：应用层查重跑的那一刻还没人占用，等它 INSERT 时已经被占了。

    真实的竞态是两个请求交错，单线程用例里没法自然复现。这里把应用层那条
    「已由 X 领用且尚未归还」的错误摘掉——等价于「SELECT 那一刻确实查到没人
    占用」，随后 INSERT 撞上唯一索引。测的正是库层兜底这条路径。

    **不这么做，下面两条就是假绿。** 第一版直接塞一张冲突记录再提交，走的是
    应用层那道查重、压根到不了 IntegrityError 处理器；而两条消息都含「一本
    证件同时只能在一个人手上」，断言照样通过。是撤销验证时才发现的。
    所以下面断的是「已被登记为领用中」——那句话只出现在库层兜底那条路径上。
    """
    import blueprints.issuance as iss
    orig = iss._validate_form
    monkeypatch.setattr(iss, "_validate_form",
                        lambda data: [e for e in orig(data) if "尚未归还" not in e])


def test_hitting_the_index_gives_a_readable_message_not_a_500(cl, monkeypatch):
    """并发窗口里撞上唯一索引，用户看到的必须是人话。

    不接住 IntegrityError 就是 500——他会以为系统坏了，然后**再点一次**。
    """
    _occupy()
    _simulate_race(monkeypatch)

    r = _issue(cl, travel_id=1, cert_nos="E0001")
    assert r.status_code == 200, "撞索引变成了 500"
    body = r.get_data(as_text=True)
    assert "已被登记为领用中" in body, "走的不是库层兜底那条路径，这条断言是假绿"
    assert "一本证件同时只能在一个人手上" in body
    assert "IntegrityError" not in body and "Traceback" not in body
    assert _one("SELECT COUNT(*) FROM cert_issuance") == 1, "重复的那张还是写进去了"


def test_the_message_tells_the_operator_a_double_click_already_succeeded(cl, monkeypatch):
    """提示里要点明「刚才那次已经成功了，别再提交」。

    双击是这条最常见的触发方式。只说「号码被占用」，人会以为自己填错了号码，
    然后去改号码——那才是真的把账搞乱。
    """
    _occupy()
    _simulate_race(monkeypatch)
    body = _issue(cl, travel_id=1, cert_nos="E0001").get_data(as_text=True)
    assert "连点了两次" in body and "不必重复提交" in body


def test_correcting_cert_types_into_a_conflict_does_not_500(cl):
    """更正证件种类那个入口也能写 cert_nos，同样要接住。"""
    _issue(cl, travel_id=1, cert_nos="E0001")
    d = sqlite3.connect(Config.DATABASE)
    d.execute(
        "INSERT INTO cert_issuance (id,travel_id,personnel_filing_id,holder_name,id_number,"
        "cert_types,cert_nos,issue_date,issuer,status,operator) "
        "VALUES (99,2,2,'人2一',?,'01','E0002','20260901','admin','issued','admin')",
        (valid_id(2),))
    d.commit(); d.close()
    r = cl.post("/issuance/99/cert-types",
                data={"csrf_token": _tok(cl), "cert_types": "01", "cert_nos": "E0001"},
                follow_redirects=True)
    assert r.status_code == 200
    assert _one("SELECT cert_nos FROM cert_issuance WHERE id=99") == "E0002", "冲突的改动被写进去了"


# ===========================================================================
# 四、存量违规数据：不中断启动，但要报出来
# ===========================================================================
def _seed_conflicting(tmp_path, monkeypatch):
    """造一个「升级前」的库：两张同号未归还单已经躺在里面。

    做法是先把库建全（init_db + run_migrations），再把索引 DROP 掉、插入
    冲突数据——这才是真实形态：老库的表结构是全的，缺的只是这条新索引。
    第一版直接只跑 init_db()，结果连 travel_start 这些迁移加的列都没有，
    fixture 自己先炸了。
    """
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()
    db = sqlite3.connect(Config.DATABASE)
    db.execute("DROP INDEX IF EXISTS ux_issuance_active_cert_no")
    _seed(db, 2)
    for i in (1, 2):
        db.execute(
            "INSERT INTO cert_issuance (travel_id,personnel_filing_id,holder_name,id_number,"
            "cert_types,cert_nos,issue_date,issuer,status,operator) "
            "VALUES (?,?,?,?,'01','E-DUP','20260901','admin','issued','admin')",
            (i, i, f"人{i}一", valid_id(i)))
    db.commit(); db.close()
    return database


def test_existing_conflicts_do_not_block_startup(tmp_path, monkeypatch):
    """存量里已有同号未归还单时，迁移不许抛异常、不许把人挡在系统外面。

    数据是真实的，不能为了建一个索引让系统起不来。索引建不上就先不建，
    等人订正干净，下次启动自然就建上了。
    """
    database = _seed_conflicting(tmp_path, monkeypatch)
    database.run_migrations()        # 不抛异常就是通过
    database.seed_data()
    assert _one("SELECT COUNT(*) FROM cert_issuance WHERE cert_nos='E-DUP'") == 2
    assert _one("SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='ux_issuance_active_cert_no'") is None, \
        "有冲突数据时索引不该建上"


def test_existing_conflicts_are_reported_on_the_list_page(tmp_path, monkeypatch):
    """列表页顶部常驻告警点名是哪个号码、几张，并给出能筛到它们的链接。

    不报出来有两个后果：索引静默建不上，而经办人永远不知道账上有一本证
    同时记在两个人名下。
    """
    database = _seed_conflicting(tmp_path, monkeypatch)
    database.run_migrations(); database.seed_data()
    html = _client().get("/issuance/").get_data(as_text=True)
    assert 'data-block="dup-cert-nos"' in html, "没有那条常驻告警"
    assert "E-DUP" in html and "共 2 张未归还" in html


def test_the_warning_disappears_once_corrected(tmp_path, monkeypatch):
    """订正之后告警要消失——常驻告警若撤不掉，它就变成了常驻噪音。"""
    database = _seed_conflicting(tmp_path, monkeypatch)
    database.run_migrations(); database.seed_data()
    d = sqlite3.connect(Config.DATABASE)
    d.execute("UPDATE cert_issuance SET status='voided' WHERE travel_id=2")
    d.commit(); d.close()
    html = _client().get("/issuance/").get_data(as_text=True)
    assert 'data-block="dup-cert-nos"' not in html


def test_the_check_and_the_index_use_the_same_condition(tmp_path, monkeypatch):
    """体检的口径必须与索引的 WHERE 一致。

    对不上的话会出现最难查的一种情形：告警说没问题，索引却建不上。
    这里用「已归还的同号记录」验证——它不违反索引，也不该被报成冲突。
    """
    db = _fresh(tmp_path, monkeypatch)
    _seed(db, 2)
    for i, st in ((1, "issued"), (2, "returned")):
        db.execute(
            "INSERT INTO cert_issuance (travel_id,personnel_filing_id,holder_name,id_number,"
            "cert_types,cert_nos,issue_date,issuer,status,operator) "
            f"VALUES (?,?,?,?,'01','E-SAME','20260901','admin','{st}','admin')",
            (i, i, f"人{i}一", valid_id(i)))
    db.commit(); db.close()
    from app import create_app
    with create_app().app_context():
        from blueprints.issuance import duplicate_issued_cert_nos
        assert duplicate_issued_cert_nos() == [], "把「已归还」也算成了冲突，与索引口径不一致"


# ===========================================================================
# 五、入口那一层：防重复提交
# ===========================================================================
def test_the_key_forms_are_wired_to_the_double_submit_guard(cl):
    """写业务记录的表单都要标上 data-no-double-submit。

    这一层是**入口**，防的是手滑；伪造 POST、JS 被禁、另外四版都绕得过去，
    真正的保证是上面那个索引。两者都要有——这是第 15.6.6 条「入口、预填、
    后端校验三层缺一层都不算修好」的同一个道理。
    """
    for url in ("/issuance/new?travel_id=1", "/travel/new", "/certificate/new",
                "/personnel/info/new", "/import/"):
        r = cl.get(url)
        assert r.status_code == 200, f"{url} 没取到（{r.status_code}），断言会假绿"
        assert "data-no-double-submit" in r.get_data(as_text=True), f"{url} 的表单没接上"


def test_the_guard_lets_the_button_recover_when_validation_blocks(cl):
    """校验拦下提交时，按钮必须还能再点。

    签名忘了画、附件超了总量——那时提交被 preventDefault 拦住，若还把按钮
    禁掉，人就再也提交不了，只能刷新重填整张表。**修一个 bug 顺手造一个。**
    所以那段 JS 里有 `if (ev.defaultPrevented) return;`。
    """
    js = open("static/js/main.js", encoding="utf-8").read()
    assert "function preventDoubleSubmit" in js
    body = js[js.index("function preventDoubleSubmit"):]
    assert "ev.defaultPrevented" in body, "没有守住「被校验拦下时不禁用按钮」"
    assert "pageshow" in body, "没有处理浏览器后退（bfcache 会把按钮留在禁用态）"

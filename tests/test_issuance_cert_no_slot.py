"""第 15 批：领用的号码，必须就是「所选那个种类」那一本的号码。

业务方在 rc2 验收时点出来的（33 条验收单全过，这条不在单子上）：一个人同时
有护照和往来港澳通行证，出国申请的拟用证件种类已经选了港澳通行证、是否做证
为「否」，而领用页的号码框里**还会冒出护照号**。

那个「下拉」其实不是系统给的——号码框是文本输入（`form.html` 的
`<input type="text" name="cert_nos">`），浏览器按输入框名字做历史填充，把以前
敲过的号码（包括给**别人**登记时敲的）弹成候选。所以修法不是「把下拉收窄」，
收窄一个不存在的下拉等于没修。

**真正的缺口：号码和种类从来没比对过。** 原有判据链是：

    说不做证就得真有那本证、且在有效期内（精确到槽位）   travel.py      ✅
    领用的种类必须等于申请的拟用种类                     issuance.py    ✅ 硬拦
    号码必填                                             issuance.py    ✅
    同一号码不能同时未归还                               应用层 + 库层索引 ✅
    号码必须属于所选的那个种类                                          ❌ 没有

实测复现（新建与更正两个入口都没拦），后果比空号码更难发现——空号码让那本证
从借出账上消失、总数少一本；填错槽位是两本证的状态**互相调换**：

    在库     = C7654321（往来港澳通行证，实际在人手上）
    借出未还 = E1234567（普通护照，实际在柜子里）

而「在库 + 借出未还 = 在控人员台账登记总本数」照样平，孤儿号码为空，一处都
不喊。盘库的人去柜子里找不到那本港澳通行证，却多出一本系统说已借出的护照——
两个差错在总数上互相抵消。

判据三条（见 issuance.cert_no_slot_error）：

    号码 = 所选种类那个槽的值      放行
    号码 = 该人**其它**槽的值      硬拦（两条路径都拦）
    号码在该人台账查不到          路径A 拦，路径B 放行

第二条不看路径，这不是偷懒：路径B 新办港澳通行证时 02 槽本来就是空的，
「查不到就放行」那条规则对护照号压根不适用（它查得到），只有第二条拦得住。
test_path_b_still_blocks_a_number_from_another_slot 就是钉这个的。
"""
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

from config import Config
from conftest import valid_id, seed_required_attachments

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_PNG = __import__("tests.test_issuance", fromlist=["_PNG_DATA_URL"])._PNG_DATA_URL

# 两条提示各自独有的尾句。
#
# 不能拿「是该人员台账上登记的」去断言：「丙」那条写的是「**不**是该人员台账上
# 登记的……」，前者是后者的子串，两条路径都会匹配上——自检清单第 23 条那个坑
# 的又一个形态。所以各挑一句只出现在自己那一支上的话。
MSG_WRONG_SLOT = "两者不是同一本证"      # 乙：号码坐在别的槽里
MSG_NOT_IN_LEDGER = "号码应与台账一致"   # 丙：台账里查不到（仅路径A）
MSG_TYPE_MISMATCH = "两者不一致"         # 既有判据：种类与申请不符


def _d(days: int) -> str:
    """相对今天算日期。写死日期的 fixture 栽过：一到那天前后，
    「不能是将来的日期」「领用日期不早于批准日」这些判据就反过来咬测试。"""
    return (datetime.now() + timedelta(days=days)).strftime("%Y%m%d")


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()
    return sqlite3.connect(Config.DATABASE)


def _person(db, pid=1):
    db.execute(
        "INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,"
        "residence,political_status,work_unit,position_or_title,supervisor_unit,status,operator) "
        "VALUES (?,'张','三','男','19900101',?,'浙江宁波市鄞州区','群众','总部','科长',"
        "'人事处','active','admin')", (pid, valid_id(pid)))


def _certs(db, pid=1, **slots):
    """给某人加一条证照台账行。slots 例：passport_no='E1', hm_pass_no='C1'。

    有效期一律给未来——「说不做证就得有在有效期内的证」那条判据要用。
    """
    cols, vals = [], []
    for col, no in slots.items():
        base = col[:-2]            # passport_no → passport_（只去掉 'no'，留下划线）
        cols += [col, base + "expiry", base + "submit_date"]
        vals += [no, _d(3000), _d(-300)]
    db.execute(
        "INSERT INTO certificates (personnel_filing_id,unit,department,name," +
        ",".join(cols) + ",operator) VALUES (?,'总部','技术部','张三'," +
        ",".join("?" * len(cols)) + ",'admin')", (pid, *vals))


def _travel(db, tid=1, pid=1, intended="02", need_new="否", dest="中国香港",
            passport_no=None):
    db.execute(
        "INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
        "id_number,destination_passport,intended_cert_type,category,travel_dates,travel_start,"
        "travel_end,approval_date,need_new_passport,passport_no,operator) "
        "VALUES (?,?,'总部','技术部','张三','科长',?,?,?,'01',?,?,?,?,?,?,'admin')",
        (tid, pid, valid_id(pid), dest, intended,
         f"{_d(5)}-{_d(15)}", _d(5), _d(15), _d(-30), need_new, passport_no))
    seed_required_attachments(db, tid, need_new)


def _client(app_db):
    from app import create_app
    c = create_app().test_client()
    tok = _CSRF.search(c.get("/login").get_data(as_text=True)).group(1)
    c.post("/login", data={"username": "admin", "password": "admin123",
                           "csrf_token": tok})
    return c


def _tok(c):
    return _CSRF.search(c.get("/").get_data(as_text=True)).group(1)


def _post(c, types, nos, travel_id=1, pid=1):
    return c.post("/issuance/new", data={
        "csrf_token": _tok(c), "travel_id": str(travel_id),
        "personnel_filing_id": str(pid), "holder_name": "张三",
        "id_number": valid_id(pid), "cert_types": types, "cert_nos": nos,
        "issue_date": _d(0), "sign_png": _PNG,
    })


def _issued(db, nos):
    return db.execute(
        "SELECT id FROM cert_issuance WHERE cert_nos=? AND status='issued'",
        (nos,)).fetchone()


# ===========================================================================
# 一、路径 A（是否做证=否）：号码必须就是台账里那一本的
# ===========================================================================
@pytest.fixture()
def both(tmp_path, monkeypatch):
    """一个人两本证都有，申请拟用港澳通行证、是否做证=否。就是业务方报的那个局面。"""
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _certs(db, passport_no="E1234567", hm_pass_no="C7654321")
    _travel(db, intended="02", need_new="否")
    db.commit()
    return db, _client(db)


def test_the_other_slots_number_is_blocked(both):
    """核心：种类=往来港澳通行证、号码填成同一个人的护照号 → 硬拦。

    这就是业务方点出来的那条路。修之前这里是 302 + 写库，一句话都不说。
    """
    db, c = both
    r = _post(c, "02", "E1234567")
    assert r.status_code == 200, "应当留在表单页回显错误，不是重定向"
    assert MSG_WRONG_SLOT in r.get_data(as_text=True)
    assert _issued(db, "E1234567") is None, "被拦下了却还是写进了库"


def test_the_matching_number_passes(both):
    """反向对照：种类与号码配对 → 放行。

    没有这条，判据写成「一律拦死」也能让上面那条变绿（第 16 条）。
    """
    db, c = both
    r = _post(c, "02", "C7654321")
    assert r.status_code == 302
    row = db.execute("SELECT cert_types,cert_nos FROM cert_issuance "
                     "WHERE id=(SELECT MAX(id) FROM cert_issuance)").fetchone()
    assert row == ("02", "C7654321")


def test_a_number_not_in_the_ledger_is_blocked_on_path_a(both):
    """路径 A 下台账里查不到的号码 → 硬拦。

    travel.py 的「说不做证就得真有那本证、且在有效期内」已经保证台账里有
    那本证，所以一个查不到的号码没有合法出处，只可能是敲错或填串了。
    """
    db, c = both
    r = _post(c, "02", "C0000000")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert MSG_NOT_IN_LEDGER in body
    # 提示要把台账上那个号码报出来，否则人不知道该填什么
    assert "C7654321" in body
    assert _issued(db, "C0000000") is None


def test_the_existing_type_check_still_fires(both):
    """既有判据没被这次改动顶掉：种类与申请不符仍然先拦。

    种类=护照（申请写的是港澳通行证）→ 报的应该是「种类不一致」那条，
    而不是号码那两条。
    """
    db, c = both
    r = _post(c, "01", "E1234567")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert MSG_TYPE_MISMATCH in body
    assert MSG_WRONG_SLOT not in body and MSG_NOT_IN_LEDGER not in body
    assert _issued(db, "E1234567") is None


# ===========================================================================
# 二、路径 B（是否做证=是）：新证还没入台账，「查不到」是正常的
# ===========================================================================
def test_path_b_allows_a_number_the_ledger_does_not_have(tmp_path, monkeypatch):
    """路径 B 下台账查不到的号码 → 放行。这是唯一的放行例外。

    新证刚办出来、还没进台账，travel_details.passport_no 是系统里唯一的号码
    来源。拦了这里，路径 B 就没法登记领用——「规则挡住坏情形时顺带挡住了
    什么」（第 18 条）。
    """
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    # 台账上只有护照，港澳通行证正在新办（02 槽是空的）
    _certs(db, passport_no="E1234567")
    _travel(db, intended="02", need_new="是", passport_no="C9999999")
    db.commit()
    c = _client(db)
    r = _post(c, "02", "C9999999")
    assert r.status_code == 302, \
        f"路径 B 被拦住了：{r.get_data(as_text=True)[:400]}"
    assert _issued(db, "C9999999") is not None


def test_path_b_still_blocks_a_number_from_another_slot(tmp_path, monkeypatch):
    """路径 B 下，号码是本人**另一本证**的号码 → 照样硬拦。

    这条是整批的要点，也是「第二条判据不看路径」的理由：
    02 槽此刻是空的（正在新办），所以「台账查不到就放行」那条规则对护照号
    **压根不适用**——它查得到，坐在 01 槽里。只有「号码坐在别的槽里」这条
    拦得住。把它写成跟着路径走，这个洞就留着。
    """
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _certs(db, passport_no="E1234567")
    _travel(db, intended="02", need_new="是", passport_no="C9999999")
    db.commit()
    c = _client(db)
    r = _post(c, "02", "E1234567")      # 浏览器历史填充就会这么填
    assert r.status_code == 200
    assert MSG_WRONG_SLOT in r.get_data(as_text=True)
    assert _issued(db, "E1234567") is None


# ===========================================================================
# 三、一人多条证照记录：不能把正当操作判成错误
# ===========================================================================
def test_a_second_pass_on_another_ledger_row_is_accepted(tmp_path, monkeypatch):
    """同一个人两条证照记录、两条都登记了港澳通行证，交出第二本 → 放行。

    这是历史遗留的真实形态（先登记了护照，办港澳通行证时没找到原记录，
    又新建了一条）。判据如果复用 cert_no_of()，它背后的 setdefault 只保留
    **先登记的那一个**，第二本就会被判成「不是台账上的号码」——一次正当
    操作被拦死。所以 certificate_slots_of() 看全部槽位值。

    撤掉那个函数、改回 cert_no_of()，这条就会红；而上面那些拦截用例照样全绿。
    """
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _certs(db, passport_no="E1234567", hm_pass_no="C1111111")   # 先登记的
    _certs(db, hm_pass_no="C2222222")                           # 后补的另一条
    _travel(db, intended="02", need_new="否")
    db.commit()
    c = _client(db)
    r = _post(c, "02", "C2222222")
    assert r.status_code == 302, \
        f"第二本被误判成错误：{r.get_data(as_text=True)[:400]}"
    assert _issued(db, "C2222222") is not None


def test_certificate_slots_of_merges_across_rows(tmp_path, monkeypatch):
    """certificate_slots_of 跨行合并，且不丢同槽位的第二个号码。"""
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _certs(db, passport_no="E1234567", hm_pass_no="C1111111")
    _certs(db, hm_pass_no="C2222222", tw_pass_no="W3333333")
    db.commit()
    from app import create_app
    from utils.helpers import certificate_slots_of, cert_no_of
    app = create_app()
    with app.test_request_context():
        slots = certificate_slots_of(1)
        # 第 16 批起返回 {号码: 有效期}，不再是号码集合——有效期要一起带出来，
        # 判「这本证在领用那天还有效吗」要用。成员判断写法不变。
        assert set(slots["01"]) == {"E1234567"}
        assert set(slots["02"]) == {"C1111111", "C2222222"}, "同槽位第二个号码丢了"
        assert set(slots["03"]) == {"W3333333"}
        assert slots["02"]["C1111111"] == _d(3000), "有效期没带出来"
        # 与 cert_no_of 的差别就在这里，顺手钉住，免得将来有人把两者合并
        assert cert_no_of(1, "02") in slots["02"]
        assert len(slots["02"]) == 2
    with app.test_request_context():
        assert certificate_slots_of(999) == {"01": {}, "02": {}, "03": {}}


# ===========================================================================
# 四、更正入口（第 12 条：新增路径加的校验，编辑路径也要有）
# ===========================================================================
def _no_sign_issuance(db, iid=1, tid=1, pid=1, types="02", nos="C7654321"):
    """无签名的领用记录——can_fix_cert_types 只放这种（历史回填行）。"""
    db.execute(
        "INSERT INTO cert_issuance (id,travel_id,personnel_filing_id,holder_name,"
        "id_number,cert_types,cert_nos,issue_date,issuer,status,operator) "
        "VALUES (?,?,?,'张三',?,?,?,?,'admin','issued','admin')",
        (iid, tid, pid, valid_id(pid), types, nos, _d(-10)))


def _fix(c, iid, types, nos):
    return c.post(f"/issuance/{iid}/cert-types", data={
        "csrf_token": _tok(c), "cert_types": types, "cert_nos": nos,
        "remarks": "",
    }, follow_redirects=True)


def test_fix_path_blocks_the_other_slots_number(tmp_path, monkeypatch):
    """更正入口同样拦下。

    修之前这里保存成功、还提示「证件种类已更正。」——实测复现。弹窗里每个
    种类后面括号中本来就显示着台账号码，模板注释也写明了这条规则，唯独
    没人执行它。
    """
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _certs(db, passport_no="E1234567", hm_pass_no="C7654321")
    _travel(db, intended="02", need_new="否")
    _no_sign_issuance(db)
    db.commit()
    c = _client(db)
    r = _fix(c, 1, "02", "E1234567")
    assert r.status_code == 200
    assert MSG_WRONG_SLOT in r.get_data(as_text=True)
    assert db.execute("SELECT cert_nos FROM cert_issuance WHERE id=1").fetchone()[0] \
        == "C7654321", "拦下了却还是改了库"


def test_fix_path_still_allows_a_real_correction(tmp_path, monkeypatch):
    """反向对照：更正入口的正当用途没被堵死。

    回填成「护照 E1234567」的记录，人工核定其实是港澳通行证——种类和号码
    一起改成那一本的，应当放行。这正是这个入口存在的理由（历史回填行
    没有签名可采，作废重录那条路走不通）。
    """
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _certs(db, passport_no="E1234567", hm_pass_no="C7654321")
    _travel(db, intended="02", need_new="否")
    _no_sign_issuance(db, types="01", nos="E1234567")
    db.commit()
    c = _client(db)
    r = _fix(c, 1, "02", "C7654321")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert MSG_WRONG_SLOT not in body and MSG_NOT_IN_LEDGER not in body
    assert db.execute("SELECT cert_types,cert_nos FROM cert_issuance WHERE id=1"
                      ).fetchone() == ("02", "C7654321")


def test_fix_path_without_a_travel_record_stays_lenient_on_unknown_numbers(
        tmp_path, monkeypatch):
    """更正入口遇上 travel_id 为空的回填行：判不出路径，「查不到」放行。

    但「号码坐在别的槽里」照样拦——后者不需要知道路径。两件事一起钉，
    免得将来把宽松那一支写得过宽。
    """
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _certs(db, passport_no="E1234567")
    db.execute(
        "INSERT INTO cert_issuance (id,travel_id,personnel_filing_id,holder_name,"
        "id_number,cert_types,cert_nos,issue_date,issuer,status,operator) "
        "VALUES (1,NULL,1,'张三',?,'02','C7654321',?,'admin','issued','admin')",
        (valid_id(1), _d(-10)))
    db.commit()
    c = _client(db)

    # 查不到的号码：放行（没有出行记录，判不出是不是路径A）
    r = _fix(c, 1, "02", "C5555555")
    assert r.status_code == 200
    assert MSG_NOT_IN_LEDGER not in r.get_data(as_text=True)
    assert db.execute("SELECT cert_nos FROM cert_issuance WHERE id=1").fetchone()[0] \
        == "C5555555"

    # 但本人护照号仍然拦
    r = _fix(c, 1, "02", "E1234567")
    assert r.status_code == 200
    assert MSG_WRONG_SLOT in r.get_data(as_text=True)
    assert db.execute("SELECT cert_nos FROM cert_issuance WHERE id=1").fetchone()[0] \
        == "C5555555"


# ===========================================================================
# 五、四档对账：拦下之后账是对的
# ===========================================================================
def test_the_swap_can_no_longer_happen(both):
    """被拦下之后，两本证的状态不会互相调换。

    这条钉的是后果而不是提示语。修之前：在库=港澳通行证（实际在人手上）、
    借出未还=护照（实际在柜子里），而恒等式照样平、孤儿号码为空，一处都不喊。
    """
    db, c = both
    from app import create_app
    from blueprints.certificate import stock_split
    app = create_app()

    _post(c, "02", "E1234567")          # 被拦下
    with app.test_request_context():
        in_stock, lent, orphan = stock_split()
    nos = {r["cert_no"] for r in in_stock}
    assert nos == {"E1234567", "C7654321"}, "拦下之后两本证都该还在库"
    assert lent == [] and orphan == []

    _post(c, "02", "C7654321")          # 正常登记
    with app.test_request_context():
        in_stock, lent, orphan = stock_split()
    assert {r["cert_no"] for r in in_stock} == {"E1234567"}
    assert {r["cert_no"] for r in lent} == {"C7654321"}, \
        "借出的必须是港澳通行证那一本，不是护照"
    assert orphan == []
    assert len(in_stock) + len(lent) == 2        # 恒等式①


# ===========================================================================
# 六、表单文案与代码执行的是同一条（第 22 条）
# ===========================================================================
def test_the_form_no_longer_lets_you_type_the_number_on_path_a(both):
    """路径 A 的号码不让人敲：渲染成服务端给选项的下拉，不是文本框。

    第 15 批这里只是把「可修改」那句文案改掉；第 16 批进一步——号码在路径A 上
    是**确定的**（人 + 种类 + 领用那天有效），系统给得出，就不该让人填
    （第 14 条）。顺带把浏览器历史填充这条路整个断掉。
    """
    db, c = both
    r = c.get("/issuance/new?travel_id=1")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # 断言整句，不是「可修改」三个字——后者在同一页的签名区还有一处
    # 「签名一经保存后不可修改」，整页找短字符串当场就假了（第 3 条）。
    assert "按所选种类自动带入，可修改" not in body
    # 控件必须是 select：取 id="certNos" 之前那一小段，别拿整页找 <select
    # （人员选择框也是 select，整页断言两条路径都会过）。
    head = body.split('id="certNos"')[0][-160:]
    assert "<select" in head, "路径A 的号码框还是文本输入"
    assert "取自证照台账" in body
    assert "号码由系统带出" in body, \
        "路径A 的提示没出来——很可能 _travel_brief 又没把 need_new_passport 取出来，" \
        "那个 {% if %} 会静默地永远走 else"
    # 台账里那一本应当已经选中，什么都不改就能提交
    assert '<option value="C7654321" selected' in body


def test_path_b_form_says_something_else(tmp_path, monkeypatch):
    """反向对照：路径 B 不该显示「须与台账一致」，它本来就允许台账外的号码。

    没有这条，那段文案写成无条件显示也能让上面那条变绿。
    """
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _certs(db, passport_no="E1234567")
    _travel(db, intended="02", need_new="是", passport_no="C9999999")
    db.commit()
    c = _client(db)
    r = c.get("/issuance/new?travel_id=1")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "号码须与台账一致" not in body
    assert "新办证件尚未入台账" in body

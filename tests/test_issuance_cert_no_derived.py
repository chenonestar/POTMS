"""第 16 批：路径 A 的号码由系统派生，且要派生出**对的那一本**。

业务方问的是一句很朴素的话：「他有港澳通行证又在有效期内，证件号码就是确定的，
还需要输入吗？」顺着这句话挖下去，挖出一个比「要不要输入」严重得多的缺陷。

**换发过的人，预填带出来的是过期那本。** 旧证到期后台账里常是**新建一条记录**
而不是改原记录（certificate_number_maps 的说明自己写着这种历史遗留），于是
02 槽里有两个号码。而预填用的 cert_no_of() 取的是「先登记的那一个」——恰好是
旧的、已过期的那本。实测：

    certificate_slots_of(1)['02'] = ['C_NEW_002', 'C_OLD_001']
    cert_no_of(1,'02')            = 'C_OLD_001'      ← 预填用这个
    表单预填带出来的号码           = 'C_OLD_001'
    提交过期号码                   → HTTP 302，已写入库

于是「**什么都不改直接提交**」就登记出一本过期证，一句话都不说——而那正是
CLAUDE.md 第 4 节工序三点名的动作，第 7 批已经为同一个动作栽过一次。

三件事一起改：

  预填  改用 usable_cert_nos()：该槽位在**领用日期那天**仍然有效的号码。
        只有一个时它就是确定的（第 14 条：系统给得出的值不该让人填）。
  控件  路径A 渲染成服务端给选项的 <select>，不让人敲；唯一时一个选项等于
        只读，多个时不替人选（系统知道「哪一种证」，不知道「交出去的是哪一
        本」）。顺带把浏览器历史填充这条路整个断掉。
  判据  cert_no_slot_error 的「号码在对的槽里」这一支，再问一句「在领用那天
        还有效吗」。

**基准日是领用日期，不是今天。** 补录两年前的领用单时，当时那本证有效、今天
早过期了，那是正当业务——按今天判会把补录整类堵死（第 18 条）。
**有效期为空不判**：历史回填的证照行根本没采集过有效期，拿一个系统自己都没有
的答案去挡人是错的（与 intended_cert_type 留空就不比对同一条原则）。
"""
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

from config import Config
from conftest import valid_id, seed_required_attachments

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_PNG = __import__("tests.test_issuance", fromlist=["_PNG_DATA_URL"])._PNG_DATA_URL

MSG_EXPIRED = "当天已经过期"          # 只出现在「号码在对的槽里但已过期」这一支
MSG_NOT_IN_LEDGER = "号码应与台账一致"  # 「台账里查不到」那一支
MSG_WRONG_SLOT = "两者不是同一本证"     # 「号码坐在别的槽里」那一支


def _d(n: int) -> str:
    return (datetime.now() + timedelta(days=n)).strftime("%Y%m%d")


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


def _hm(db, no, expiry, pid=1):
    """给某人**另加一条**证照记录，只填港澳通行证槽。

    换发的真实形态就是这样：不是改原来那行，而是新建一行。
    expiry 传 None 表示台账上没采集有效期（历史回填行）。
    """
    db.execute(
        "INSERT INTO certificates (personnel_filing_id,unit,department,name,"
        "hm_pass_no,hm_pass_expiry,hm_pass_submit_date,operator) "
        "VALUES (?,'总部','技术部','张三',?,?,?,'admin')", (pid, no, expiry, _d(-400)))


def _travel(db, tid=1, pid=1, need_new="否", start=10, end=20, approved=-30):
    db.execute(
        "INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
        "id_number,destination_passport,intended_cert_type,category,travel_dates,travel_start,"
        "travel_end,approval_date,need_new_passport,passport_no,operator) "
        "VALUES (?,?,'总部','技术部','张三','科长',?,'中国香港','02','01',?,?,?,?,?,NULL,'admin')",
        (tid, pid, valid_id(pid), f"{_d(start)}-{_d(end)}", _d(start), _d(end),
         _d(approved), need_new))
    seed_required_attachments(db, tid, need_new)


def _client():
    from app import create_app
    c = create_app().test_client()
    tok = _CSRF.search(c.get("/login").get_data(as_text=True)).group(1)
    c.post("/login", data={"username": "admin", "password": "admin123",
                           "csrf_token": tok})
    return c


def _tok(c):
    return _CSRF.search(c.get("/").get_data(as_text=True)).group(1)


def _get_form(c, travel_id=1):
    r = c.get(f"/issuance/new?travel_id={travel_id}")
    assert r.status_code == 200, "没取到表单页，下面的断言全都不成立"
    return r.get_data(as_text=True)


def _selected(body):
    m = re.search(r'<option value="([^"]*)" selected', body)
    return m.group(1) if m else None


def _options(body):
    """号码下拉里的选项文本。只取 certNos 那个 select，别把人员选择框框进来。"""
    seg = body.split('id="certNos"', 1)[1].split("</select>", 1)[0]
    return [t.strip() for _, t in
            re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', seg)]


def _post(c, nos, travel_id=1, pid=1, issue_date=None):
    return c.post("/issuance/new", data={
        "csrf_token": _tok(c), "travel_id": str(travel_id),
        "personnel_filing_id": str(pid), "holder_name": "张三",
        "id_number": valid_id(pid), "cert_types": "02", "cert_nos": nos,
        "issue_date": issue_date or _d(0), "sign_png": _PNG,
    })


def _issued(db, nos):
    return db.execute("SELECT id FROM cert_issuance WHERE cert_nos=? AND status='issued'",
                      (nos,)).fetchone()


# ===========================================================================
# 一、换发：预填必须是有效那本（本批的核心）
# ===========================================================================
@pytest.fixture()
def reissued(tmp_path, monkeypatch):
    """换发过的人：02 槽两个号码，先登记的那个已过期。"""
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _hm(db, "C_OLD_001", _d(-60))    # 先登记 → cert_no_of 会取这个
    _hm(db, "C_NEW_002", _d(1200))   # 换发后补的，有效
    _travel(db)
    db.commit()
    return db, _client()


def test_prefill_picks_the_valid_one_not_the_first_registered(reissued):
    """预填选中的是**有效**那本，不是先登记的过期那本。

    修之前这里预选的是 C_OLD_001——于是「什么都不改直接提交」登记出一本过期证。
    """
    db, c = reissued
    body = _get_form(c)
    assert _selected(body) == "C_NEW_002", \
        f"预选的是 {_selected(body)}，又取成「先登记的那一个」了"


def test_submitting_the_prefilled_value_unchanged_succeeds(reissued):
    """什么都不改直接提交 → 成功，且存下来的是有效那本。

    这条钉的是工序三那个动作本身：预填的值真的能用吗。
    """
    db, c = reissued
    assert _post(c, "C_NEW_002").status_code == 302
    assert db.execute("SELECT cert_nos FROM cert_issuance "
                      "WHERE id=(SELECT MAX(id) FROM cert_issuance)").fetchone()[0] \
        == "C_NEW_002"


def test_the_expired_number_is_blocked_with_the_alternative_named(reissued):
    """过期号码被拦下，提示要报出有效期和当天有效的那一本。

    只说「不能用」没用——人不知道该换成哪个。
    """
    db, c = reissued
    r = _post(c, "C_OLD_001")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert MSG_EXPIRED in body
    assert "C_NEW_002" in body, "没告诉他当天有效的是哪一本"
    assert _d(-60) in body, "没报出过期日期"
    assert _issued(db, "C_OLD_001") is None


def test_the_dropdown_lists_both_and_marks_the_expired_one(reissued):
    """下拉列出该槽位全部号码，并标出今天已过期的那个。

    不能只列今天有效的：补录旧单时要选的那本今天可能已经过期，而后端是按
    领用日期判的，选项先被「今天」筛掉就选不着了。
    """
    db, c = reissued
    opts = _options(_get_form(c))
    assert len(opts) == 2, opts
    assert any("C_NEW_002" in o and "今天已过期" not in o for o in opts)
    assert any("C_OLD_001" in o and "今天已过期" in o for o in opts)


# ===========================================================================
# 二、两本都有效：不替人选
# ===========================================================================
@pytest.fixture()
def two_valid(tmp_path, monkeypatch):
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _hm(db, "C_AAA_111", _d(900))
    _hm(db, "C_BBB_222", _d(1200))
    _travel(db)
    db.commit()
    return db, _client()


def test_two_usable_numbers_are_not_auto_picked(two_valid):
    """两本都有效 → 不预选，给一个「请选择」占位。

    系统知道「这趟要用哪一种证」，**不知道交出去的是哪一本实体证**——
    那一步只有站在柜台前的经办人能定。替他选等于替他签字。
    """
    db, c = two_valid
    body = _get_form(c)
    assert _selected(body) is None, f"替人选了 {_selected(body)}"
    assert "请选择本次交出的是哪一本" in body
    assert len(_options(body)) == 3      # 占位 + 两个号码


def test_either_of_the_two_is_accepted(two_valid):
    """反向对照：两本都有效时，任选一本都放行。

    没有这条，判据写成「只认第一个」也能让上面那条变绿。
    """
    db, c = two_valid
    assert _post(c, "C_BBB_222").status_code == 302
    assert _issued(db, "C_BBB_222") is not None


# ===========================================================================
# 三、基准日是领用日期，不是今天（补录）
# ===========================================================================
def test_a_backdated_issue_accepts_a_now_expired_number(tmp_path, monkeypatch):
    """补录：领用日期落在旧证有效期内 → 旧证放行，哪怕它今天已过期。

    这是 on_date 而不是 today 的全部理由。按今天判会把补录整类堵死
    （第 18 条：规则挡住坏情形时，顺带挡住了什么）。
    """
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _hm(db, "C_OLD_001", _d(-60))     # 今天已过期
    _hm(db, "C_NEW_002", _d(1200))
    # 一条早就批完、也早就走完的旧申请
    _travel(db, start=-200, end=-190, approved=-260)
    db.commit()
    c = _client()
    r = _post(c, "C_OLD_001", issue_date=_d(-205))   # 那时候 C_OLD 还有效
    assert r.status_code == 302, \
        f"补录被拦了：{r.get_data(as_text=True)[:400]}"
    assert _issued(db, "C_OLD_001") is not None


def test_a_backdated_issue_after_expiry_is_still_blocked(tmp_path, monkeypatch):
    """反向对照：领用日期落在旧证过期之后 → 照样拦。

    没有这条，判据写成「有 on_date 就一律放行」也能让上面那条变绿。
    """
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _hm(db, "C_OLD_001", _d(-60))
    _hm(db, "C_NEW_002", _d(1200))
    _travel(db, start=-40, end=-30, approved=-100)
    db.commit()
    c = _client()
    r = _post(c, "C_OLD_001", issue_date=_d(-35))    # 过期之后 5 天
    assert r.status_code == 200
    assert MSG_EXPIRED in r.get_data(as_text=True)
    assert _issued(db, "C_OLD_001") is None


def test_expiry_on_the_issue_date_itself_is_still_valid(tmp_path, monkeypatch):
    """边界：到期日**当天**算有效（`expiry >= on_date`）。

    证件到期日那天本身是有效的，不该把它判成过期。
    """
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _hm(db, "C_EDGE_01", _d(0))       # 今天到期
    _travel(db)
    db.commit()
    c = _client()
    r = _post(c, "C_EDGE_01", issue_date=_d(0))
    assert r.status_code == 302, \
        f"到期日当天被判成过期了：{r.get_data(as_text=True)[:300]}"


# ===========================================================================
# 四、有效期为空：不拿系统没有的答案挡人
# ===========================================================================
def test_a_number_without_a_recorded_expiry_is_not_judged(tmp_path, monkeypatch):
    """台账上没采集有效期的号码 → 不判，放行。

    历史回填的证照行根本没有有效期（见 test_cert_type_backfill 的 _seed_legacy）。
    与 intended_cert_type 留空就不比对、逾期判据基准日缺失就不算逾期同一条
    原则：宁可漏报，不可误报。
    """
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _hm(db, "C_NOEXP_1", None)
    _travel(db)
    db.commit()
    c = _client()
    body = _get_form(c)
    assert _selected(body) == "C_NOEXP_1", "没有有效期的号码应当照常预选"
    assert "有效期至" not in body
    assert _post(c, "C_NOEXP_1").status_code == 302


# ===========================================================================
# 五、路径 B 不受影响
# ===========================================================================
def test_path_b_still_takes_a_typed_number(tmp_path, monkeypatch):
    """路径 B：新证还没进台账，号码仍然要人填，控件仍是文本框。"""
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _hm(db, "C_OLD_001", _d(-60))
    _travel(db, need_new="是")
    db.commit()
    c = _client()
    body = _get_form(c)
    head = body.split('id="certNos"')[0][-160:]
    assert "<select" not in head, "路径B 的号码框不该是下拉——新证不在台账里"
    assert 'autocomplete="off"' in body
    r = _post(c, "C_BRAND_NEW")        # 台账里根本没有的新号码
    assert r.status_code == 302, \
        f"路径B 被拦了：{r.get_data(as_text=True)[:400]}"


# ===========================================================================
# 六、被拦下之后还改得了（入口与判据同源）
# ===========================================================================
def test_the_dropdown_survives_a_validation_error(reissued):
    """校验失败回显时下拉不能是空的，否则人被拦下之后反而改不了。

    三处渲染（GET 预填、校验失败回显、库层兜底回显）共用
    cert_no_options_for()；回显那两处忘了重算，选项就没了。
    """
    db, c = reissued
    r = c.post("/issuance/new", data={
        "csrf_token": _tok(c), "travel_id": "1", "personnel_filing_id": "1",
        "holder_name": "张三", "id_number": valid_id(1),
        "cert_types": "02", "cert_nos": "C_OLD_001",
        "issue_date": _d(0), "sign_png": _PNG,
    })
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    opts = _options(body)
    assert len(opts) == 2, f"回显时下拉空了，改不了：{opts}"
    assert any("C_NEW_002" in o for o in opts)


# ===========================================================================
# 七、前端那条隐式依赖（第 19 条）
# ===========================================================================
def test_the_js_guard_against_overwriting_the_select_is_present(reissued):
    """syncCertNos 必须对 <select> 直接返回。

    不加这个守卫，整批修复会被**悄悄抵消**：data-cert0X 的值来自 cert_no_of()，
    取「先登记的那一个」＝换发过的人那本已过期的旧号码；两本都有效时下拉故意
    不预选，于是页面加载时 `if (!nosEl.value) syncCertNos()` 会触发，把过期号码
    又塞回来。两处代码各自都对，断的是「号码框是个 input」这条没写在任何地方的
    隐式依赖（第 19 条）。

    这里只能断言守卫还在——pytest 不跑 JS。它挡不住「守卫写错」，但挡得住
    「守卫被删」，而后者是更可能发生的那一种。
    """
    db, c = reissued
    body = _get_form(c)
    assert "if (nosEl.tagName === 'SELECT') return;" in body


# ===========================================================================
# 八、usable_cert_nos 本身
# ===========================================================================
def test_usable_cert_nos_rules(tmp_path, monkeypatch):
    """逐条钉住：按基准日筛、空有效期算有效、空基准日不筛、留有效期最晚的那条。"""
    db = _fresh(tmp_path, monkeypatch)
    _person(db)
    _hm(db, "C_PAST", _d(-60))
    _hm(db, "C_FUTURE", _d(900))
    _hm(db, "C_NOEXP", None)
    db.commit()
    from app import create_app
    from utils.helpers import usable_cert_nos, certificate_slots_of
    app = create_app()
    with app.test_request_context():
        assert usable_cert_nos(1, "02", _d(0)) == ["C_FUTURE", "C_NOEXP"]
        assert usable_cert_nos(1, "02", _d(-100)) == ["C_FUTURE", "C_NOEXP", "C_PAST"]
        # 空基准日不筛（没有基准就比不了）
        assert usable_cert_nos(1, "02", "") == ["C_FUTURE", "C_NOEXP", "C_PAST"]
        # 别的槽位是空的
        assert usable_cert_nos(1, "01", _d(0)) == []
        assert usable_cert_nos(None, "02", _d(0)) == []

    # 同一号码在两行里重复登记（换发时把旧行也留着并更新了有效期）：
    # 要留**有效期最晚**的那条，取先登记的那条就会把它误判成过期。
    _hm(db, "C_DUP", _d(-60))
    _hm(db, "C_DUP", _d(900))
    db.commit()
    with app.test_request_context():
        assert certificate_slots_of(1)["02"]["C_DUP"] == _d(900)
        assert "C_DUP" in usable_cert_nos(1, "02", _d(0))

"""历史回填的证件种类：推断、存量订正、人工更正。

原先回填一律把 cert_types 写成 '01'（因私护照）——往来港澳通行证、大陆居民往来
台湾通行证全被标成护照。领用凭证是要归档的，错的种类比空着更糟。
"""
import re
import sqlite3

import pytest

from config import Config
from database import (BACKFILL_REMARK_INFERRED, BACKFILL_REMARK_LEGACY,
                      BACKFILL_REMARK_PENDING)

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = "110101199001012133"

# (姓名, 证照登记表里持有的 {种类: 号码}, 出行表填的证件号, 「地点、证照」, 应判出的种类)
_CASES = [
    ("张三", {"01": "E12345678"}, "E12345678", "美国-护照", "01"),
    ("李四", {"01": "E20000001", "02": "C87654321"}, "C87654321", "香港", "02"),
    ("王五", {"01": "E30000001", "03": "T11112222"}, "T11112222", "台湾", "03"),
    ("赵六", {"01": "E40000001", "02": "C40000001"}, "", "澳门/港澳通行证", "02"),
    ("孙七", {"01": "E55556666"}, "", "泰国", "01"),
    # 三本证都有、出行表没填号码、文字里也没写证件名——数据里确实没有信息
    ("周八", {"01": "E60000001", "02": "C60000001", "03": "T60000001"}, "", "新加坡", ""),
]
_COL = {"01": "passport_no", "02": "hm_pass_no", "03": "tw_pass_no"}


def _seed_legacy(tmp_path, monkeypatch, *, with_issuance_rows):
    """造一个「升级前」的库：出行表已有领用日期。

    with_issuance_rows=True 时先把错标的领用记录塞进去，模拟已经被老版本回填过
    的存量库——那正是订正迁移要处理的形态。
    """
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.seed_data()

    db = sqlite3.connect(Config.DATABASE)
    for i, (nm, held, tpno, dest, _) in enumerate(_CASES, start=1):
        db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
                   "id_number,residence,political_status,work_unit,position_or_title,"
                   "supervisor_unit,operator) VALUES (?,?,'','男','19900101',?,'北京','群众',"
                   "'总部','科长','人事处','admin')", (i, nm, _VALID_ID))
        cols = ",".join(_COL[c] for c in held)
        qs = ",".join("?" for _ in held)
        db.execute(f"INSERT INTO certificates (personnel_filing_id,unit,department,name,"
                   f"{cols},operator) VALUES (?,'总部','技术部',?,{qs},'admin')",
                   (i, nm, *held.values()))
        db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
                   "position,id_number,destination_passport,category,travel_dates,"
                   "need_new_passport,passport_no,passport_collect_date,operator) "
                   "VALUES (?,?,'总部','技术部',?,'科长',?,?,'01','2026/03/01-2026/03/10',"
                   "'否',?,'20260225','admin')", (i, i, nm, _VALID_ID, dest, tpno))
        if with_issuance_rows:
            db.execute("INSERT INTO cert_issuance (id,travel_id,personnel_filing_id,holder_name,"
                       "id_number,cert_types,cert_nos,issue_date,issuer,status,remarks,operator) "
                       "VALUES (?,?,?,?,?,'01',?,'20260225','admin','issued',?,'admin')",
                       (i, i, i, nm, _VALID_ID, tpno, BACKFILL_REMARK_LEGACY))
    db.commit(); db.close()


def _stored():
    db = sqlite3.connect(Config.DATABASE)
    rows = dict(db.execute("SELECT holder_name, cert_types FROM cert_issuance").fetchall())
    db.close()
    return rows


def _remarks():
    db = sqlite3.connect(Config.DATABASE)
    rows = dict(db.execute("SELECT holder_name, remarks FROM cert_issuance").fetchall())
    db.close()
    return rows


_EXPECTED = {nm: want for nm, _, _, _, want in _CASES}


# ---------------------------------------------------------------------------
# 回填本身（从没回填过的库）
# ---------------------------------------------------------------------------
def test_backfill_infers_real_cert_type(tmp_path, monkeypatch):
    """回填时就该判对种类，而不是一律记成护照。"""
    _seed_legacy(tmp_path, monkeypatch, with_issuance_rows=False)
    import database
    database.run_migrations()
    assert _stored() == _EXPECTED


def test_backfill_marks_undeterminable_as_pending(tmp_path, monkeypatch):
    """判不出的留空并在备注里写明待核实，不替他猜一个。"""
    _seed_legacy(tmp_path, monkeypatch, with_issuance_rows=False)
    import database
    database.run_migrations()
    rm = _remarks()
    assert rm["周八"] == BACKFILL_REMARK_PENDING
    assert rm["李四"] == BACKFILL_REMARK_INFERRED
    assert BACKFILL_REMARK_LEGACY not in rm.values()


# ---------------------------------------------------------------------------
# 存量订正（已经被老版本回填过的库）
# ---------------------------------------------------------------------------
def test_correction_fixes_existing_rows(tmp_path, monkeypatch):
    """光把回填改对没用——回填有幂等守卫，存量错标行不会被重算。

    这条正是那个盲区：库里已经躺着一堆 '01'，必须有独立的订正迁移。
    """
    _seed_legacy(tmp_path, monkeypatch, with_issuance_rows=True)
    assert set(_stored().values()) == {"01"}      # 前置条件：全是错的
    import database
    database.run_migrations()
    assert _stored() == _EXPECTED


def test_correction_is_idempotent(tmp_path, monkeypatch):
    """跑第二遍必须**什么都不做**——靠改备注失配实现，不需要版本表。

    只比对结果不够：备注若没换掉，每次启动都会重跑一遍、重复备份、重复写日志，
    而结果恰好相同，比对不出来。所以直接数日志条数——守卫没脱开就会攒出第二条。
    """
    _seed_legacy(tmp_path, monkeypatch, with_issuance_rows=True)
    import database
    database.run_migrations()
    first = (_stored(), _remarks())

    database.run_migrations()
    database.run_migrations()
    assert (_stored(), _remarks()) == first

    db = sqlite3.connect(Config.DATABASE)
    n = db.execute("SELECT COUNT(*) FROM operation_logs WHERE action='migrate' "
                   "AND target_type='cert_issuance'").fetchone()[0]
    db.close()
    assert n == 1, f"订正跑了 3 次，日志攒了 {n} 条——幂等守卫没生效"


def test_correction_never_touches_signed_records(tmp_path, monkeypatch):
    """手工登记的记录有签名，订正必须绕开——判据是「备注为旧串且无签名」。"""
    _seed_legacy(tmp_path, monkeypatch, with_issuance_rows=True)
    db = sqlite3.connect(Config.DATABASE)
    # 把李四那条伪装成「有签名但备注恰好也是旧串」的极端情形
    db.execute("UPDATE cert_issuance SET sign_image = ? WHERE holder_name = '李四'", (b"\x89PNG",))
    db.commit(); db.close()

    import database
    database.run_migrations()
    got = _stored()
    assert got["李四"] == "01", "有签名的记录不该被订正改动"
    assert got["王五"] == "03", "无签名的记录照常订正"


def test_correction_backs_up_and_logs(tmp_path, monkeypatch):
    """动业务记录之前先落一份备份，并留下操作日志。"""
    _seed_legacy(tmp_path, monkeypatch, with_issuance_rows=True)
    import database
    database.run_migrations()

    # 改前快照是独立的带时间戳文件，不是当天那份每日备份——每日备份会被后续
    # 备份覆盖掉，而这份要能一直指向「这次订正之前」的状态。
    assert list((tmp_path / "bak").glob("before_migrate_cert_types_*.db")), \
        f"订正前没留下改前快照，备份目录里只有：{[p.name for p in (tmp_path / 'bak').iterdir()]}"
    db = sqlite3.connect(Config.DATABASE)
    detail = db.execute(
        "SELECT detail FROM operation_logs WHERE action='migrate' "
        "AND target_type='cert_issuance'").fetchone()
    db.close()
    assert detail is not None
    assert "共 6 条" in detail[0] and "推定 5 条" in detail[0] and "待核实 1 条" in detail[0]


# ---------------------------------------------------------------------------
# 人工更正入口 —— 没有它，「待核实」就是永远填不上的死数据
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    _seed_legacy(tmp_path, monkeypatch, with_issuance_rows=True)
    import database
    database.run_migrations()
    from app import create_app
    cl = create_app().test_client()
    tok = _CSRF.search(cl.get("/login").get_data(as_text=True)).group(1)
    cl.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return cl


def _tok(cl):
    return _CSRF.search(cl.get("/").get_data(as_text=True)).group(1)


def _cert_types(iss_id):
    db = sqlite3.connect(Config.DATABASE)
    v = db.execute("SELECT cert_types FROM cert_issuance WHERE id=?", (iss_id,)).fetchone()[0]
    db.close()
    return v


def test_pending_row_can_be_corrected(client):
    """周八那条判不出，必须能人工补上，否则订正等于制造死数据。"""
    assert _cert_types(6) == ""
    r = client.post("/issuance/6/cert-types",
                    data={"csrf_token": _tok(client), "cert_types": "02"},
                    follow_redirects=True)
    assert "证件种类已更正" in r.get_data(as_text=True)
    assert _cert_types(6) == "02"


def test_correction_rejected_on_signed_record(client):
    """有签名的记录不许改——签名签的就是「我领了这几样」，改了就名不副实。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE cert_issuance SET sign_image=? WHERE id=1", (b"\x89PNG",))
    db.commit(); db.close()
    r = client.post("/issuance/1/cert-types",
                    data={"csrf_token": _tok(client), "cert_types": "02"},
                    follow_redirects=True)
    assert "不可更改" in r.get_data(as_text=True)
    assert _cert_types(1) == "01"       # 原值未动


def test_correction_rejects_invalid_and_empty(client):
    """非法代码、空选、多选都要挡回，不能把记录改成一个更烂的状态。"""
    for data, msg in (({"cert_types": "99"}, "无效的证件种类代码"),
                      ({}, "请选择证件种类"),
                      ({"cert_types": ["01", "02"]}, "只能领用一本证件")):
        r = client.post("/issuance/6/cert-types",
                        data={"csrf_token": _tok(client), **data}, follow_redirects=True)
        assert msg in r.get_data(as_text=True)
    assert _cert_types(6) == ""


def test_pending_filter_finds_them(client):
    """待核实必须能筛出来——筛不出来这批待办就没法收口。

    现有筛选是 (','||cert_types||',') LIKE '%,01,%'，对空值恒不匹配。
    """
    html = client.get("/issuance/?cert_type=pending").get_data(as_text=True)
    assert "周八" in html
    assert "张三" not in html and "李四" not in html


def test_pending_shown_as_badge_not_blank(client):
    """列表与详情都要写明「待核实」，空白格子会被当成漏渲染。"""
    assert "待核实" in client.get("/issuance/?cert_type=pending").get_data(as_text=True)
    assert "待核实" in client.get("/issuance/6").get_data(as_text=True)

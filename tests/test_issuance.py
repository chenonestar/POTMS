"""证件领用管理 — 单元测试

覆盖：签名解析与拦截、PNG 尺寸解析、openpyxl 嵌图契约、派生日期回写口径。
"""
import base64
import io
import zipfile

import pytest

from blueprints.issuance import _decode_signature, _clean_meta, CERT_NO_FIELD
from utils.excel_export import _png_size, _make_png_image


# 真实的 1x1 PNG
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
    "7753de0000000c4944415408d763f8ffff3f0005fe02fea735d2860000000049454e44ae426082"
)
_PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(_PNG_BYTES).decode()


# ---------------------------------------------------------------------------
# 签名解析
# ---------------------------------------------------------------------------
def test_decode_signature_ok():
    blob, err = _decode_signature(_PNG_DATA_URL)
    assert err == ""
    assert blob.startswith(b"\x89PNG")


@pytest.mark.parametrize("raw,frag", [
    ("", "请手写签名"),
    ("notadataurl", "格式不正确"),
    ("data:image/png;base64,!!!not-base64!!!", "解析失败"),
    ("data:image/png;base64," + base64.b64encode(b"plain text").decode(), "不是有效的 PNG"),
])
def test_decode_signature_rejects(raw, frag):
    blob, err = _decode_signature(raw)
    assert blob is None
    assert frag in err


def test_decode_signature_rejects_oversize():
    # 构造一个超过上限的「PNG」（魔数正确但体积过大）
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (600 * 1024)
    blob, err = _decode_signature("data:image/png;base64," + base64.b64encode(big).decode())
    assert blob is None and "过大" in err


def test_clean_meta():
    assert _clean_meta('{"a":1}') == '{"a":1}'
    assert _clean_meta("") is None
    assert _clean_meta("{not json") is None
    assert _clean_meta("x" * 500_000) is None      # 超长丢弃


# ---------------------------------------------------------------------------
# PNG 尺寸解析（替代 Pillow）
# ---------------------------------------------------------------------------
def test_png_size():
    assert _png_size(_PNG_BYTES) == (1, 1)


def test_png_size_rejects_non_png():
    with pytest.raises(ValueError):
        _png_size(b"not a png at all........")


def test_make_png_image_contract():
    """守护对 openpyxl 内部契约的依赖：升级 openpyxl 若改变该契约，此用例先失败。"""
    from openpyxl.drawing.image import Image as XLImage
    img = _make_png_image(_PNG_BYTES)
    # 必须是 openpyxl.Image 子类 —— 序列化时以 isinstance 判定图片
    assert isinstance(img, XLImage)
    assert (img.width, img.height) == (1, 1)
    assert img.format == "png"
    assert img._data() == _PNG_BYTES
    assert img.path.endswith(".png")


def test_openpyxl_embeds_image_without_pillow():
    """端到端验证：不装 Pillow 也能把 PNG 写进 xlsx 的 media 目录。"""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    img = _make_png_image(_PNG_BYTES)
    img.anchor = "B2"
    ws.add_image(img)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    names = zipfile.ZipFile(buf).namelist()
    assert any(n.startswith("xl/media/") for n in names), names


# ---------------------------------------------------------------------------
# 证件种类映射
# ---------------------------------------------------------------------------
def test_cert_type_codes_match_dict_seed():
    from database import SEED_DICT
    seeded = {code for cat, code, _v, _o in SEED_DICT if cat == "cert_type"}
    assert seeded == set(CERT_NO_FIELD), "字典种子与领用模块的证件种类代码不一致"


# ---------------------------------------------------------------------------
# 派生日期回写（单一数据源不变量）
# ---------------------------------------------------------------------------
import re
import sqlite3
from config import Config

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = "110101199001012133"


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()
    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,"
               "residence,political_status,work_unit,position_or_title,supervisor_unit,operator) "
               "VALUES (1,'张','三','男','19900101',?,'北京','群众','总部','科长','人事处','admin')",
               (_VALID_ID,))
    db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
               "id_number,destination_passport,category,travel_dates,need_new_passport,operator) "
               "VALUES (1,1,'总部','技术部','张三','科长',?,'美国/护照','01','2026/08/01-2026/08/11','否','admin')",
               (_VALID_ID,))
    db.commit(); db.close()
    from app import create_app
    client = create_app().test_client()
    tok = _CSRF.search(client.get("/login").get_data(as_text=True)).group(1)
    client.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return client


def _tok(client):
    return _CSRF.search(client.get("/").get_data(as_text=True)).group(1)


def _add_travel(tid: int):
    """再造一条出国申请。领用必须挂申请，而同一申请下不能有两条未归还记录，
    所以要造第二条领用就得先有第二条申请。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
               "id_number,destination_passport,category,travel_dates,need_new_passport,operator) "
               "VALUES (?,1,'总部','技术部','张三','科长',?,'香港/港澳通行证','01',"
               "'2026/09/01-2026/09/05','否','admin')", (tid, _VALID_ID))
    db.commit(); db.close()


def _issue(client, **over):
    data = {"csrf_token": _tok(client), "travel_id": "1", "personnel_filing_id": "1",
            "holder_name": "张三", "id_number": _VALID_ID, "cert_types": "01",
            "cert_nos": "E12345678", "issue_date": "20260720", "sign_png": _PNG_DATA_URL}
    data.update(over)
    return client.post("/issuance/new", data=data, follow_redirects=True)


def _travel_dates():
    db = sqlite3.connect(Config.DATABASE)
    row = db.execute("SELECT passport_collect_date, passport_return_date "
                     "FROM travel_details WHERE id=1").fetchone()
    db.close()
    return row


def test_issue_writes_derived_collect_date(c):
    assert "领用登记已保存" in _issue(c).get_data(as_text=True)
    assert _travel_dates() == ("20260720", None)


def test_return_writes_derived_return_date(c):
    _issue(c)
    r = c.post("/issuance/1/return",
               data={"csrf_token": _tok(c), "return_date": "20260810", "sign_png": _PNG_DATA_URL},
               follow_redirects=True)
    assert "归还登记已保存" in r.get_data(as_text=True)
    assert _travel_dates() == ("20260720", "20260810")


def test_void_clears_derived_dates(c):
    _issue(c)
    r = c.post("/issuance/1/void", data={"csrf_token": _tok(c), "void_reason": "登记错误"},
               follow_redirects=True)
    assert "已作废" in r.get_data(as_text=True)
    # 作废后不再计入在借，派生字段须清空，否则逾期告警会误报
    assert _travel_dates() == (None, None)


def test_signature_is_required(c):
    r = _issue(c, sign_png="")
    assert "请手写签名" in r.get_data(as_text=True)
    assert _travel_dates() == (None, None)   # 未落库


def test_duplicate_open_issue_blocked(c):
    _issue(c)
    r = _issue(c, issue_date="20260721")
    assert "已有未归还的领用记录" in r.get_data(as_text=True)


def test_travel_form_no_longer_writes_collect_date(c):
    """出行编辑表单即使被构造提交这两个字段，也不得覆盖派生值。"""
    _issue(c)
    c.post("/travel/1/edit", data={
        "csrf_token": _tok(c), "personnel_filing_id": "1", "unit": "总部",
        "department": "技术部", "name": "张三", "position": "科长", "id_number": _VALID_ID,
        "destination_passport": "美国/护照", "category": "01",
        "travel_dates": "2026/08/01-2026/08/11", "need_new_passport": "否",
        "passport_collect_date": "19990101",      # 伪造：应被忽略
        "passport_return_date": "19990202",       # 伪造：应被忽略
    }, follow_redirects=True)
    assert _travel_dates() == ("20260720", None)


def test_travel_delete_blocked_when_issued(c):
    _issue(c)
    r = c.post("/travel/1/delete", data={"csrf_token": _tok(c)}, follow_redirects=True)
    assert "不能删除" in r.get_data(as_text=True)
    db = sqlite3.connect(Config.DATABASE)
    assert db.execute("SELECT COUNT(*) FROM travel_details WHERE id=1").fetchone()[0] == 1
    db.close()


# ---------------------------------------------------------------------------
# 手写签名是否强制（POTMS_REQUIRE_SIGNATURE 开关）
#
# 默认强制。单位尚未配备手写板、或存在代领代还与历史回填记录时可临时放宽。
# 放宽只影响「留空」这一种情况——签了名照常入库，格式非法照常拒绝，
# 未签名的记录仍会在详情页与打印件上被标注「无签名」。
# ---------------------------------------------------------------------------
def test_signature_required_by_default(monkeypatch):
    """默认必须强制。放宽是明确的选择，不能是默认值。"""
    assert Config.REQUIRE_SIGNATURE is True
    blob, err = _decode_signature("")
    assert blob is None and "请手写签名" in err


def test_signature_optional_when_switched_off(monkeypatch):
    monkeypatch.setattr(Config, "REQUIRE_SIGNATURE", False)
    blob, err = _decode_signature("")
    assert blob is None and err == ""          # 留空放行，如实存 NULL


@pytest.mark.parametrize("raw,frag", [
    ("notadataurl", "格式不正确"),
    ("data:image/png;base64," + base64.b64encode(b"plain text").decode(), "不是有效的 PNG"),
])
def test_bad_signature_still_rejected_when_optional(monkeypatch, raw, frag):
    """放宽的是「可以不签」，不是「可以乱签」——格式校验一步不能少。"""
    monkeypatch.setattr(Config, "REQUIRE_SIGNATURE", False)
    blob, err = _decode_signature(raw)
    assert blob is None and frag in err


def test_return_blocked_without_signature(c):
    _issue(c)
    html = c.post("/issuance/1/return",
                  data={"csrf_token": _tok(c), "return_date": "20260810", "sign_png": ""},
                  follow_redirects=True).get_data(as_text=True)
    assert "请手写签名后再提交" in html
    db = sqlite3.connect(Config.DATABASE)
    assert db.execute("SELECT status FROM cert_issuance WHERE id=1").fetchone()[0] == "issued"
    db.close()
    assert _travel_dates() == ("20260720", None)   # 派生字段也不能被写脏


def test_return_allowed_without_signature_when_switched_off(c, monkeypatch):
    _issue(c)
    monkeypatch.setattr(Config, "REQUIRE_SIGNATURE", False)
    html = c.post("/issuance/1/return",
                  data={"csrf_token": _tok(c), "return_date": "20260810", "sign_png": ""},
                  follow_redirects=True).get_data(as_text=True)
    assert "归还登记已保存" in html

    db = sqlite3.connect(Config.DATABASE)
    status, rdate, sig = db.execute(
        "SELECT status, return_date, return_sign_image FROM cert_issuance WHERE id=1").fetchone()
    db.close()
    assert (status, rdate, sig) == ("returned", "20260810", None)
    assert _travel_dates() == ("20260720", "20260810")
    # 无签名必须看得出来，不能与已签名的混为一谈
    assert "无签名" in c.get("/issuance/1").get_data(as_text=True)


def test_signature_still_stored_when_switched_off(c, monkeypatch):
    """开关关掉只是不强制，签了就得存。"""
    _issue(c)
    monkeypatch.setattr(Config, "REQUIRE_SIGNATURE", False)
    c.post("/issuance/1/return",
           data={"csrf_token": _tok(c), "return_date": "20260810", "sign_png": _PNG_DATA_URL},
           follow_redirects=True)
    db = sqlite3.connect(Config.DATABASE)
    sig = db.execute("SELECT return_sign_image FROM cert_issuance WHERE id=1").fetchone()[0]
    db.close()
    assert sig and sig.startswith(b"\x89PNG")


# ---------------------------------------------------------------------------
# 批量打印（四个业务列表都有，此前独缺证件领用）
# ---------------------------------------------------------------------------
def test_batch_print_issuance(c):
    """批量打印要出真内容：单位来自 JOIN，证件种类要是中文，签名按行取图。

    单条打印早就支持 issuance，缺的只是批量那条路——export.py 的 table_map 里
    没有 issuance，命中的是「不支持的打印类型」分支。

    第二条另建一条出国申请：同一申请下不允许并存两条未归还的领用记录，
    而领用又必须挂在申请上（一次申请一本证，多本就分多条申请）。
    """
    _issue(c)
    _add_travel(2)
    _issue(c, travel_id="2", cert_types="02", cert_nos="C87654321", issue_date="20260721")
    html = c.get("/print/batch/issuance?ids=1,2").get_data(as_text=True)

    assert "因私出国（境）证件领用登记表" in html
    assert "共 2 条" in html
    assert "总部" in html                       # work_unit 来自 JOIN personnel_filing
    assert "因私护照" in html                    # 代码 → 中文，不是裸的 '01'
    assert "往来港澳通行证" in html
    assert "E12345678" in html and "C87654321" in html
    # 签名按行取图（<img src=".../signature.png">），不是把 BLOB 塞进页面
    assert "/issuance/1/signature.png" in html
    assert "/issuance/2/signature.png" in html


def test_batch_print_issuance_shows_return_and_void(c):
    """归还签名与作废状态都要出现在批量打印上——这是归档件，不能只印半截。"""
    _issue(c)
    c.post("/issuance/1/return",
           data={"csrf_token": _tok(c), "return_date": "20260810", "sign_png": _PNG_DATA_URL},
           follow_redirects=True)
    # 第一条已归还，同一条申请可以再领一次（领用→归还→再领用）
    _issue(c, issue_date="20260822")
    c.post("/issuance/2/void",
           data={"csrf_token": _tok(c), "void_reason": "登记错误"}, follow_redirects=True)

    html = c.get("/print/batch/issuance?ids=1,2").get_data(as_text=True)
    assert "kind=return" in html      # 归还签名图
    assert "20260810" in html
    assert "已归还" in html and "已作废" in html

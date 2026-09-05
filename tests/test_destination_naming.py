"""第 11 批：「地点、证照」收窄为「目的地」，展示口径统一。

手工点系统时问出来的：这一栏到底填证照，还是只填地点？

按原定义是两样都填——需求文档写的是「目的地国家/地区**及使用证照类型**」，
列名沿袭纸质表格。但第 7 批加了结构化的 intended_cert_type 之后，这个定义
就过期了：「证照」那一半成了同一件事的第二处录入。三个后果：

1. **两处可以互相矛盾，系统不管。** 自由文本写「香港/护照」、拟用证件种类
   选「往来港澳通行证」，校验和领用比对全走后者，可打印件上照样印着
   「香港/护照」——归档的凭证上留着一句错话。
2. **系统自己的叫法已经分裂**：表单「地点、证照」、列表「目的地」、
   筛选框「姓名 / 目的地」、导出「地点、证照」、附件总览「目的地/证照」。
   同一个格子五个名字，操作员当然不知道该填什么。
3. infer_cert_type 的第②级判据还在读这段文字，而那是**回填历史数据**用的。

所以收窄为只填地点，全部展示口径统一为「目的地」——含打印件与导出表头。

**库列名 destination_passport 不动。** 改列要动 schema 和其余四版，而这
自始至终是展示口径问题，不是数据结构问题。这条边界值得单独一个用例钉住，
免得日后有人「顺手」把列也改了。
"""
import re
import sqlite3

import pytest

from config import Config
from conftest import valid_id


_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')

# 出现过这一栏的全部展示位置。少数一处就会重新分裂——这套系统栽在
# 「同一件事写两遍」上已经不止一次了。
_PAGES = [
    ("/travel/new", "新增出国申请"),
    ("/travel/", "出国申请列表"),
    ("/travel/attachments", "附件总览"),
    ("/issuance/new", "领用挑单页"),
    ("/search?q=甲", "全局搜索"),
    ("/", "首页"),
]

_OLD_NAMES = ("地点、证照", "目的地/证照")


@pytest.fixture()
def cl(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()

    db = sqlite3.connect(Config.DATABASE)
    db.execute(
        "INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,"
        "residence,political_status,work_unit,position_or_title,supervisor_unit,status,operator) "
        "VALUES (1,'甲','一','男','19900101',?,'浙江宁波市鄞州区','群众','总部','科长','人事处',"
        "'active','admin')", (valid_id(1),))
    db.execute(
        "INSERT INTO certificates (personnel_filing_id,unit,department,name,passport_no,"
        "passport_expiry,passport_submit_date,operator) "
        "VALUES (1,'总部','技术部','甲一','E1','20351231','20250101','admin')")
    db.execute(
        "INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
        "id_number,destination_passport,intended_cert_type,category,travel_dates,travel_start,"
        "travel_end,approval_date,need_new_passport,operator) "
        "VALUES (1,1,'总部','技术部','甲一','科长',?,'美国','01','01',"
        "'2026/11/01-2026/11/11','20261101','20261111','20260101','否','admin')",
        (valid_id(1),))
    from conftest import seed_required_attachments
    seed_required_attachments(db, 1, "否")
    db.commit(); db.close()

    from app import create_app
    c = create_app().test_client()
    tok = _CSRF.search(c.get("/login").get_data(as_text=True)).group(1)
    c.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return c


# ===========================================================================
# 一、界面上不再有旧名字
# ===========================================================================
@pytest.mark.parametrize("url,label", _PAGES)
def test_no_page_still_says_the_old_name(cl, url, label):
    """六个展示位置一个都不能漏下旧名字。

    先断言真的取到了页面。「某个字符串不在页面上」这种断言在 404 页上
    永远成立——本批写第一版时 URL 就写错过两次，撤销验证时那两条纹丝不动，
    才发现它们一直在对着 404 页做断言。同类坑这已经是第四次。
    """
    r = cl.get(url)
    assert r.status_code == 200, f"{label}（{url}）没取到，下面的断言就是假绿"
    html = r.get_data(as_text=True)
    for old in _OLD_NAMES:
        assert old not in html, f"{label}（{url}）上还写着「{old}」"


def test_the_printable_sheet_uses_the_new_name(cl):
    """打印件也改。这是归档件，之前一直沿用纸质表格的列名。"""
    r = cl.get("/print/travel/1")
    # 先确认真取到了打印件。第一版这里的 URL 写错了，取回来的是 404 页——
    # 404 页上当然没有「地点、证照」，「旧名字不在」那半条断言照样绿。
    assert r.status_code == 200, "没取到打印件，下面的断言就是假绿"
    html = r.get_data(as_text=True)
    for old in _OLD_NAMES:
        assert old not in html
    assert "目的地" in html


def test_the_batch_print_sheet_uses_the_new_name(cl):
    """批量打印那张横表同理。"""
    r = cl.get("/print/batch/travel?ids=1")
    assert r.status_code == 200, "没取到批量打印件，下面的断言就是假绿"
    html = r.get_data(as_text=True)
    assert "地点、证照" not in html
    assert "目的地" in html


def test_the_excel_export_header_uses_the_new_name(cl):
    """导出件的表头也是展示口径的一部分——它是要发出去给人看的。"""
    from openpyxl import load_workbook
    from app import create_app
    with create_app().app_context():
        from utils.excel_export import export_travel_details
        path, _ = export_travel_details("admin", "", ())
    header = [c.value for c in load_workbook(path).active[2]]
    assert "目的地" in header
    assert "地点、证照" not in header


def test_the_field_name_in_operation_logs_uses_the_new_name():
    """操作日志的变更详情里也会打这个字段名。

    日志是给人看「改了什么」的，字段名对不上就只能靠猜。
    """
    from blueprints.logs import FIELD_LABELS
    assert FIELD_LABELS["destination_passport"] == "目的地"


def test_the_validation_message_uses_the_new_name(cl):
    """必填校验的报错话术也要跟着改。

    「地点、证照 为必填项。」——报错里说的是一个界面上已经不存在的栏目名，
    人得先在页面上找那一栏才能明白说的是谁。
    """
    r = cl.post("/travel/new", data={
        "csrf_token": _CSRF.search(cl.get("/").get_data(as_text=True)).group(1),
        "personnel_filing_id": "1", "unit": "总部", "department": "技术部",
        "name": "甲一", "position": "科长", "id_number": valid_id(1),
        "destination_passport": "", "category": "01",
        "travel_dates": "2026/11/01-2026/11/11", "need_new_passport": "否",
        "approval_date": "20260101", "intended_cert_type": "01",
    }, content_type="multipart/form-data", follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "目的地 为必填项" in body
    assert "地点、证照" not in body


# ===========================================================================
# 二、这一栏现在只填地点，表单要说清楚
# ===========================================================================
def test_the_form_tells_the_operator_to_put_only_the_place_there(cl):
    """把「只填地点、证件在另一栏选」写在明处。

    这条问题的起点就是「这个字段输入证照吗，还是只输入地点」——
    改完名字不说清楚，下一个人还会问同一句。
    """
    html = cl.get("/travel/new").get_data(as_text=True)
    i = html.find('name="destination_passport"')
    assert i > 0
    around = html[max(0, i - 400):i + 400]
    assert "只填地点" in around, "没告诉经办人这一栏只填地点"
    assert "拟用证件种类" in around, "没指出证件种类该到哪一栏选"


def test_the_placeholder_no_longer_asks_for_the_certificate_type(cl):
    """占位文字里那句「及使用的证照类型」是旧定义，必须去掉。

    它比标题更容易被照做——标题只是个名字，placeholder 是在教人怎么填。
    """
    html = cl.get("/travel/new").get_data(as_text=True)
    box = re.search(r'<input[^>]*name="destination_passport"[^>]*>', html)
    assert box, "找不到目的地输入框"
    assert "证照类型" not in box.group(0), f"占位文字还在要证照类型：{box.group(0)}"


# ===========================================================================
# 三、边界：改的是展示口径，不是数据结构
# ===========================================================================
def test_the_database_column_is_untouched(cl):
    """库列名仍是 destination_passport。

    改列要动 schema 和其余四版（五版共享同一个 data.db），而这自始至终
    是展示口径问题。这条用例是给日后「顺手把列也改了」的人看的。
    """
    db = sqlite3.connect(Config.DATABASE)
    cols = {r[1] for r in db.execute("PRAGMA table_info(travel_details)")}
    db.close()
    assert "destination_passport" in cols
    assert "destination" not in cols


def test_the_backfill_rule_still_reads_the_free_text(cl):
    """infer_cert_type 的第②级判据仍要认老数据里那半句证件名称。

    老库里「香港/港澳通行证」那半句话还在，回填时仍要靠它。这一栏收窄
    只约束**新录入**，不能顺手把存量判据一起拆了——那批数据的种类就再也
    判不出来了。
    """
    import database
    db = sqlite3.connect(Config.DATABASE)
    assert database.infer_cert_type(db, 1, "", "香港/往来港澳通行证") == "02"
    db.close()

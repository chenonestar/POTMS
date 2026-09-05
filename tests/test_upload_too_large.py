"""第 10 批：上传超限的提示。

手工点系统报出来的：传一个大附件，跳出一整屏英文

    413 Request Entity Too Large
    The data value transmitted exceeds the capacity limit.

没有导航、没有中文，而且是整页替换——填了半天的表单当场丢光。app.py 里
只注册了 404 和 500 两个 errorhandler，413 走的是 werkzeug 的默认页。

比页面难看更麻烦的是**表单上的提示本身是错的**。附件那三栏原先各写着
「PDF格式，≤10MB」，读起来像单文件上限；可 MAX_CONTENT_LENGTH 限的是
**整个请求体**——三个各 4MB 的附件每个都「≤10MB」，合计 12MB 照样被拒收，
回来的还是那屏英文。而请求体在 413 那一步根本没被解析过，服务端说不出
是哪个文件大，所以它只能说「合计」，不能说「某个文件」。

两半一起做，缺一半都不解决问题：

    前端  提交前用 file.size 累加预检 —— 请求根本不发出去，表单原样留着
    服务端 413 处理器 —— 兜底：JS 被禁、伪造的 POST

前端那一半才是真正的修复。这里能自动测的是服务端那一半和文案；前端那一半
只能钉住模板与 main.js 里的接线（没有真实浏览器可跑），这是这些用例的边界。
"""
import io
import re
import sqlite3

import pytest

from config import Config
from conftest import valid_id

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\ntrailer\n<<>>\n%%EOF\n"


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()
    return sqlite3.connect(Config.DATABASE)


@pytest.fixture()
def cl(tmp_path, monkeypatch):
    db = _fresh(tmp_path, monkeypatch)
    db.execute(
        "INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,"
        "residence,political_status,work_unit,position_or_title,supervisor_unit,status,operator) "
        "VALUES (1,'甲','一','男','19900101',?,'浙江宁波市鄞州区','群众','总部','科长','人事处',"
        "'active','admin')", (valid_id(1),))
    # 「是否做证=否」要求台账里真有那本在有效期内的证，否则会被另一条校验挡回，
    # 反向对照那条就测不到「413 处理器没有一律拒收」这件事。
    db.execute(
        "INSERT INTO certificates (personnel_filing_id,unit,department,name,passport_no,"
        "passport_expiry,passport_submit_date,operator) "
        "VALUES (1,'总部','技术部','甲一','E1','20351231','20250101','admin')")
    db.commit(); db.close()
    from app import create_app
    c = create_app().test_client()
    tok = _CSRF.search(c.get("/login").get_data(as_text=True)).group(1)
    c.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return c


def _tok(cl):
    return _CSRF.search(cl.get("/").get_data(as_text=True)).group(1)


def _oversize_post(cl, total_bytes):
    """提交一份附件合计 total_bytes 的出国申请。"""
    big = _PDF + b"0" * max(0, total_bytes - len(_PDF))
    return cl.post("/travel/new", data={
        "csrf_token": _tok(cl), "personnel_filing_id": "1", "unit": "总部",
        "department": "技术部", "name": "甲一", "position": "科长",
        "id_number": valid_id(1), "destination_passport": "美国", "category": "01",
        "travel_dates": "2026/11/01-2026/11/11", "need_new_passport": "否",
        "approval_date": "20260101", "intended_cert_type": "01",
        "att_application": (io.BytesIO(big), "big.pdf"),
        "att_approval": (io.BytesIO(_PDF), "b.pdf"),
    }, content_type="multipart/form-data")


# ===========================================================================
# 一、服务端兜底：413 得是本系统自己的页面
# ===========================================================================
def test_the_413_page_is_our_own_and_in_chinese(cl):
    """不再是 werkzeug 那屏英文裸页。"""
    r = _oversize_post(cl, Config.MAX_CONTENT_LENGTH + 1024 * 1024)
    assert r.status_code == 413
    body = r.get_data(as_text=True)
    assert "The data value transmitted exceeds" not in body, "还是 werkzeug 的默认页"
    assert "上传内容过大" in body
    assert "因私出国（境）人员审批管理系统" in body, "不是本系统的页面（没有站点标题）"


def test_it_says_the_limit_is_a_total_not_per_file(cl):
    """必须说「合计」。

    这是整条修复里最容易写错的一句：请求体在 413 那一步根本没被解析过，
    服务端不知道是哪个文件超的，也不知道有几个文件。说「单个文件不能超过
    10MB」既是错的，还会把人引向「我每个都没超啊」的死胡同。
    """
    body = _oversize_post(cl, Config.MAX_CONTENT_LENGTH + 1024 * 1024).get_data(as_text=True)
    assert "合计" in body
    assert "总量" in body
    assert "单个文件" not in body or "不是单个文件" in body


def test_it_tells_the_operator_the_form_is_still_recoverable(cl):
    """告诉人「点后退，填过的内容通常还在」——否则他会以为白填了。"""
    body = _oversize_post(cl, Config.MAX_CONTENT_LENGTH + 1024 * 1024).get_data(as_text=True)
    assert "后退" in body


def test_the_limit_number_comes_from_the_config(cl, monkeypatch):
    """页面上那个数字是从配置读的，不是写死的 10。

    写死的话，谁把 MAX_CONTENT_LENGTH 调了，提示就开始骗人——而这一页
    存在的全部意义就是把上限讲清楚。
    """
    monkeypatch.setattr(Config, "MAX_CONTENT_LENGTH", 2 * 1024 * 1024)
    from app import create_app
    c = create_app().test_client()
    tok = _CSRF.search(c.get("/login").get_data(as_text=True)).group(1)
    c.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    body = _oversize_post(c, 3 * 1024 * 1024).get_data(as_text=True)
    assert "2MB" in body, "页面上的上限数字没跟着配置走"
    assert "10MB" not in body


def test_a_normal_sized_upload_still_goes_through(cl):
    """反向对照：正常大小的附件照常保存，别把 413 处理器写成了一律拒收。"""
    r = _oversize_post(cl, 1024)
    assert r.status_code in (200, 302)
    db = sqlite3.connect(Config.DATABASE)
    n = db.execute("SELECT COUNT(*) FROM travel_details").fetchone()[0]
    db.close()
    assert n == 1


# ===========================================================================
# 二、表单上的文案：原来那句是错的
# ===========================================================================
def test_the_form_no_longer_claims_a_per_file_limit(cl):
    """三栏下面不能再各写一句「≤10MB」。

    那句话把整次提交的总量说成了单个文件的上限，是这条问题里真正误导人的
    部分——三个各 4MB 的附件按那句话读全都合规，提交却被拒。
    """
    html = cl.get("/travel/new").get_data(as_text=True)
    assert "PDF格式，≤10MB" not in html
    assert html.count("≤10MB") == 0


def test_the_form_states_the_total_limit_once(cl):
    """改成在附件区说一次总量上限，并写明「这是总量，不是每个文件的上限」。"""
    html = cl.get("/travel/new").get_data(as_text=True)
    assert "合计" in html and "10MB" in html
    assert "不是每个文件的上限" in html


def test_the_consent_letter_field_is_covered_too(cl):
    """《同意申办函》那一栏原先连格式提示都没有——三栏都要说清是 PDF。"""
    html = cl.get("/travel/new").get_data(as_text=True)
    i = html.find('name="att_consent"')
    assert i > 0
    assert "PDF" in html[i:i + 200]


def test_the_excel_import_page_states_the_limit(cl):
    """Excel 导入同样受这条限制，原先一句提示都没有。"""
    html = cl.get("/import/").get_data(as_text=True)
    assert "10MB" in html


# ===========================================================================
# 三、前端预检的接线
#
# 没有真实浏览器可跑，这两条钉的是「线接上了没有」，不是「JS 逻辑对不对」。
# 这是它们的边界，写在这里免得日后误以为前端那一半有真测试。
# ===========================================================================
def test_the_upload_forms_are_wired_to_the_client_side_guard(cl):
    """两个上传表单都调了 attachUploadSizeGuard，并把配置里的上限传了进去。"""
    limit = str(Config.MAX_CONTENT_LENGTH)
    for url, form_id in (("/travel/new", "travelForm"), ("/import/", "importForm")):
        html = cl.get(url).get_data(as_text=True)
        assert f"attachUploadSizeGuard('{form_id}', {limit})" in html, f"{url} 没接上预检"
        assert f'id="{form_id}"' in html, f"{url} 的表单没有那个 id，预检找不到它"


def test_the_guard_sums_every_file_input():
    """预检必须把表单里**所有** file 输入加起来，不能只看变化的那一个。

    只看单个文件正是那句错提示的翻版：三个各 4MB 每个都合规、合计超限。
    """
    js = open("static/js/main.js", encoding="utf-8").read()
    assert "function attachUploadSizeGuard" in js
    i = js.index("function attachUploadSizeGuard")
    body = js[i:]
    assert "querySelectorAll('input[type=\"file\"]')" in body, "没有遍历全部 file 输入"
    assert "sum += inp.files[i].size" in body, "没有把各文件大小累加起来"

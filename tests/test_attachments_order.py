"""附件总览排序：同一条出行申请的附件必须聚在一起。

原来只有 `ORDER BY a.uploaded_at DESC`：一旦某条申请补传过附件，它的附件就会被
别人的插在中间，翻起来对不上人。而且 uploaded_at 是 CURRENT_TIMESTAMP，只精确到
秒——同一次提交的几个文件时间戳完全相同，没有兜底列时先后在 SQL 层面是未定义的。
"""
import re
import sqlite3

import pytest

from config import Config

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = "110101199001012133"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"
    up.mkdir()
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
    # 两条出行申请。created_at 显式指定：默认值同秒会让「组间顺序」这项断言失去意义。
    for tid, nm, created in ((1, "张三", "2026-03-01 08:00:00"),
                             (2, "李四", "2026-03-02 08:00:00")):
        db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
                   "position,id_number,destination_passport,category,travel_dates,"
                   "need_new_passport,operator,created_at) "
                   "VALUES (?,1,'总部','技术部',?,'科长',?,'美国/护照','01',"
                   "'2026/08/01-2026/08/11','否','admin',?)",
                   (tid, nm, _VALID_ID, created))
    # 交错上传：张三先传两件 → 李四传两件 → 张三补传一件。
    # 前两件同秒，正是「并列无兜底」那种情形。
    for tid, ftype, ts in (
        (1, "审批表", "2026-03-01 09:00:00"),        # 故意先插审批表，验证组内会重排
        (1, "个人申请报告", "2026-03-01 09:00:00"),
        (2, "个人申请报告", "2026-03-01 10:00:00"),
        (2, "审批表", "2026-03-01 10:00:00"),
        (1, "同意申办函", "2026-03-01 11:00:00"),    # 补传，时间最晚
    ):
        db.execute("INSERT INTO attachments (travel_id,file_name,file_path,file_type,"
                   "file_size,uploaded_at) VALUES (?,?,?,?,1024,?)",
                   (tid, f"{ftype}.pdf", f"{tid}-{ftype}.pdf", ftype, ts))
    db.commit(); db.close()

    from app import create_app
    cl = create_app().test_client()
    tok = _CSRF.search(cl.get("/login").get_data(as_text=True)).group(1)
    cl.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return cl


def _rows(client, qs=""):
    """按页面上出现的先后，取出 (姓名, 附件类型) 序列。"""
    html = client.get("/travel/attachments" + qs).get_data(as_text=True)
    body = html.split('id="mainTable"', 1)[1]
    return re.findall(
        r'<td>(张三|李四)</td>.*?badge bg-info">(个人申请报告|审批表|同意申办函)</span>',
        body, re.S)


def test_default_groups_by_travel(client):
    """默认按批次：同一条申请的附件连成一段，中间不许插别人的。"""
    got = _rows(client)
    names = [n for n, _ in got]
    # 每个人只出现一段（相邻去重后不应有重复姓名）
    segments = [n for i, n in enumerate(names) if i == 0 or names[i - 1] != n]
    assert len(segments) == len(set(segments)), f"批次被劈开了：{names}"
    assert len(got) == 5


def test_group_order_follows_travel_list(client):
    """组间与「出国明细」列表同序（created_at DESC）：李四的申请更晚，排前面。"""
    assert [n for n, _ in _rows(client)][0] == "李四"


def test_within_group_ordered_by_workflow(client):
    """组内按办件顺序，而不是上传时间。

    张三的审批表先于个人申请报告上传、同意申办函最后补传；正确的呈现顺序是
    个人申请报告 → 审批表 → 同意申办函。
    """
    got = [t for n, t in _rows(client) if n == "张三"]
    assert got == ["个人申请报告", "审批表", "同意申办函"]


def test_uploaded_sort_still_available(client):
    """按上传时间是可选项，保留原来的行为（最新在前）。"""
    got = _rows(client, "?sort=uploaded")
    assert got[0] == ("张三", "同意申办函")     # 11:00，最晚
    assert len(got) == 5


def test_unknown_sort_falls_back_to_default(client):
    """排序参数是白名单取值：非法值退回默认，不拼进 SQL。"""
    assert _rows(client, "?sort=%27%3B+DROP+TABLE+attachments%3B--") == _rows(client)
    db = sqlite3.connect(Config.DATABASE)
    assert db.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 5
    db.close()


def test_sort_survives_filtering(client):
    """排序与筛选并存：按类型筛完，剩下的仍按批次成组。"""
    got = _rows(client, "?sort=batch&file_type=%E5%AE%A1%E6%89%B9%E8%A1%A8")
    assert got == [("李四", "审批表"), ("张三", "审批表")]

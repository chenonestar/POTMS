"""配置表改名与删除对历史数据的影响（第 5 批 B3/B4/B5）。

sys_org / sys_dict / sys_submit_unit 这三张配置表都**不是被外键引用的**。业务表里
存的是当时那个名字的文字本身——`certificates.unit = '总部'`、
`personnel_filing.political_status = '群众'`、`decontrol_filing.submit_unit_name =
'某某国资委'`。这是有意的：单据一旦开出，上面印的抬头就该定格在开单那天。

代价是配置表这一侧完全不知道自己被谁用着，于是两个洞：

- **删除**：把「技术部」从组织树上删掉，几百条历史记录里的「技术部」原地变成
  一个下拉里再也选不到的孤儿值——按部门筛选选不出来，导入校验也认不了。
- **改名**：新数据用新名、老数据用旧名，同一个部门在统计里裂成两个，两边都不全。

所以两件事都要问：删要先报使用量并拒绝，改名要问历史数据跟不跟着走。跟着走属于
批量重写历史，走强制备份 + 一条操作日志（同第 1 批经办人回填）。

字典还多一层：**存编码的类别（学历/学位/职称/职级）改显示值是安全的**，因为库里
存的是 01/02，渲染时才翻成文字，改名只是换个叫法。判据统一用「有多少条记录存着
这几个字」——存编码的列天然统计不到显示值，于是这四类自然不会被问，不需要另加
一层按类别的判断。
"""
import os
import re
import sqlite3

import pytest

from config import Config

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = "110101199001012133"


@pytest.fixture()
def c(tmp_path, monkeypatch):
    """一个「总部 / 技术部」组织树，外加一批引用了这两个名字的历史数据。"""
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()

    db = sqlite3.connect(Config.DATABASE)
    db.execute("DELETE FROM sys_org")
    db.execute("INSERT INTO sys_org (id,name,parent_id,sort_order) VALUES (1,'总部',0,0)")
    db.execute("INSERT INTO sys_org (id,name,parent_id,sort_order) VALUES (2,'技术部',1,0)")
    db.execute("INSERT INTO sys_org (id,name,parent_id,sort_order) VALUES (3,'空壳部',1,0)")

    db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
               "id_number,residence,political_status,work_unit,position_or_title,"
               "supervisor_unit,operator) VALUES (1,'张','三','男','19900101',?,"
               "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')", (_VALID_ID,))
    db.execute("INSERT INTO certificates (id,personnel_filing_id,unit,department,name,"
               "passport_no,passport_expiry,passport_submit_date,operator) "
               "VALUES (1,1,'总部','技术部','张三','E12345678','20351231','20250101','admin')")
    db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
               "position,id_number,destination_passport,category,travel_dates,"
               "need_new_passport,operator) VALUES (1,1,'总部','技术部','张三','科长',?,"
               "'美国/护照','因私','2026/03/01-2026/03/10','否','admin')", (_VALID_ID,))
    db.execute("INSERT INTO decontrol_filing (id,personnel_filing_id,surname,given_name,"
               "gender,birth_date,id_number,residence,political_status,work_unit,"
               "supervisor_unit,submit_unit_name,submit_unit_type,submit_contact,"
               "submit_phone,batch_no,reason,decontrol_date,cert_handover_date,operator) "
               "VALUES (1,1,'李','四','男','19900101',?,'浙江宁波市鄞州区','群众','总部',"
               "'人事处','某某国资委','01','王五','13800000000','2026-01','调离',"
               "'20260301','20260301','admin')", (_VALID_ID,))
    db.execute("INSERT OR REPLACE INTO sys_submit_unit (id,name,contact,phone,sort_order) "
               "VALUES (1,'某某国资委','王五','13800000000',0)")
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


def _dict_id(category, value):
    return _scalar("SELECT id FROM sys_dict WHERE category=? AND value=?", (category, value))


def _log_details():
    db = sqlite3.connect(Config.DATABASE)
    rows = [r[0] or "" for r in db.execute("SELECT detail FROM operation_logs ORDER BY id DESC")]
    db.close()
    return rows


def _backups():
    return sorted(os.listdir(Config.BACKUP_FOLDER)) if os.path.isdir(Config.BACKUP_FOLDER) else []


def _snapshots(tag=""):
    """改前快照：backup/before_<tag>_YYYYMMDD_HHMMSS.db。"""
    return [f for f in _backups() if f.startswith("before_" + tag)]


def _arm_backup_check(cl):
    """先取好 CSRF 令牌，再清空备份目录，返回令牌。

    首页每天会自己备份一次，而取令牌走的就是首页——不先把顺序排开，「同步前
    备份过了」这条断言就会被首页的日常备份糊弄过去，撤掉强制备份也照样绿。
    清空之后日常备份不会再触发（当天已检查过），所以此后出现的备份只可能来自
    改名同步里的强制备份。
    """
    tok = _tok(cl)
    for f in _backups():
        os.remove(os.path.join(Config.BACKUP_FOLDER, f))
    return tok


# ---------------------------------------------------------------------------
# B3 组织架构
# ---------------------------------------------------------------------------
def test_cannot_delete_org_in_use(c):
    """删掉在用的部门，历史数据里的「技术部」就成了下拉里选不到的孤儿值。"""
    html = c.post("/org/2/delete", data={"csrf_token": _tok(c)},
                  follow_redirects=True).get_data(as_text=True)
    assert "不能删除" in html
    assert "证照台账·部门" in html, f"没报清楚是被哪里引用的：{html[:600]}"
    assert _scalar("SELECT COUNT(*) FROM sys_org WHERE id=2") == 1


def test_unused_org_can_still_be_deleted(c):
    """没人用的节点仍要能删——守卫不能把清理空壳部门这条路也堵死。"""
    c.post("/org/3/delete", data={"csrf_token": _tok(c)}, follow_redirects=True)
    assert _scalar("SELECT COUNT(*) FROM sys_org WHERE id=3") == 0


def test_org_rename_without_choice_is_refused(c):
    """有历史数据在用时，改名必须先明确表态，不能默默改一半。"""
    html = c.post("/org/2/edit", data={"csrf_token": _tok(c), "name": "工程技术部",
                                       "parent_id": "1"},
                  follow_redirects=True).get_data(as_text=True)
    assert "历史数据是否一并更新" in html
    assert _scalar("SELECT name FROM sys_org WHERE id=2") == "技术部", "表态之前就把名字改了"


def test_org_rename_can_skip_history(c):
    """明确选择不同步：只改组织树，历史数据原样留在旧名下。"""
    c.post("/org/2/edit", data={"csrf_token": _tok(c), "name": "工程技术部",
                                "parent_id": "1", "sync_history": ""}, follow_redirects=True)
    assert _scalar("SELECT name FROM sys_org WHERE id=2") == "技术部", \
        "空字符串的 sync_history 被当成了「要同步」"


def test_org_rename_syncs_history_with_backup_and_log(c):
    """选择同步：三张表一起改，改前有备份，改后有一条说得清的日志。"""
    tok = _arm_backup_check(c)
    html = c.post("/org/2/edit", data={"csrf_token": tok, "name": "工程技术部",
                                       "parent_id": "1", "sync_history": "1"},
                  follow_redirects=True).get_data(as_text=True)
    assert "同步了" in html and "改动前的快照已存为" in html

    assert _scalar("SELECT name FROM sys_org WHERE id=2") == "工程技术部"
    assert _scalar("SELECT department FROM certificates WHERE id=1") == "工程技术部"
    assert _scalar("SELECT department FROM travel_details WHERE id=1") == "工程技术部"

    snaps = _snapshots("org_rename")
    assert len(snaps) == 1, f"批量重写历史之前没留下改前快照：{_backups()}"
    assert snaps[0] in html, "页面没告诉操作员这份快照叫什么，出事时不知道拿哪个文件回退"
    detail = _log_details()[0]
    assert "技术部" in detail and "工程技术部" in detail and "2 条" in detail, \
        f"日志说不清改了什么：{detail}"
    assert snaps[0] in detail, f"日志里没记下改前快照叫什么：{detail}"


def test_each_sync_keeps_its_own_snapshot(c):
    """同一天做两次同步，要留下两份快照——这正是不用每日备份的原因。

    每日备份一天一个文件名，第二次同步会把它覆盖掉，于是「第一次改之前」的样子
    就再也拿不回来了；而那恰恰是留这份备份要防的事。改前快照带到秒的时间戳且
    从不覆盖，两次改动各有各的退路。
    """
    tok = _arm_backup_check(c)
    c.post("/org/2/edit", data={"csrf_token": tok, "name": "工程技术部",
                                "parent_id": "1", "sync_history": "1"}, follow_redirects=True)
    c.post("/submit-unit/1/edit",
           data={"csrf_token": tok, "name": "某某市国资委", "contact": "王五",
                 "phone": "13800000000", "sort_order": "0", "sync_history": "1"},
           follow_redirects=True)

    snaps = _snapshots()
    assert len(snaps) == 2, f"两次同步只留下 {len(snaps)} 份快照：{_backups()}"
    assert len(set(snaps)) == 2, f"两份快照重名，后一份把前一份盖掉了：{snaps}"
    # 文件名要能看出各自是哪次改动，不然出事时得逐个打开猜
    assert any("org_rename" in f for f in snaps) and \
           any("submit_unit_rename" in f for f in snaps), f"快照名分不出是哪次改动：{snaps}"


def test_org_rename_refuses_sync_when_name_is_ambiguous(c):
    """组织树上有重名节点时，按文字分不出历史数据属于谁，宁可不同步。

    「技术部」在两个单位下各有一个，一条 UPDATE 会把两边都扫走，而这不是用户要的。
    """
    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO sys_org (id,name,parent_id,sort_order) VALUES (4,'技术部',0,0)")
    db.commit(); db.close()

    html = c.post("/org/2/edit", data={"csrf_token": _tok(c), "name": "工程技术部",
                                       "parent_id": "1", "sync_history": "1"},
                  follow_redirects=True).get_data(as_text=True)
    assert "同叫" in html and "已中止同步" in html
    assert _scalar("SELECT name FROM sys_org WHERE id=2") == "技术部", "中止了却还是改了名"
    assert _scalar("SELECT department FROM certificates WHERE id=1") == "技术部"


def test_org_tree_shows_usage(c):
    """使用量要在树上就看得见——不能等点了删除才被弹回来。"""
    assert "在用" in c.get("/org/").get_data(as_text=True)


# ---------------------------------------------------------------------------
# B4 数据字典：存编码 vs 存文字
# ---------------------------------------------------------------------------
def test_code_backed_dict_rename_passes_through(c):
    """存编码的类别（职称）改显示值不该拦着问同步，且历史记录自己就跟着改了。

    库里存的是 01/02，显示值只是这个编码的当前叫法——渲染时用 dict_value() 把
    编码翻成文字，所以改完名，那条老记录在详情页上显示的就是新名称。拿这四类
    去问一遍「历史数据要不要同步」，是在制造假的风险感。
    """
    did = _scalar("SELECT id FROM sys_dict WHERE category='title' ORDER BY id LIMIT 1")
    code, old = _scalar("SELECT code FROM sys_dict WHERE id=?", (did,)), \
        _scalar("SELECT value FROM sys_dict WHERE id=?", (did,))
    # 一条实实在在引用着这个职称的人员信息——存的是编码
    db = sqlite3.connect(Config.DATABASE)
    db.execute("INSERT INTO personnel_info (id,unit,department,name,gender,birth_date,"
               "id_number,position,education,degree,title,rank,political_status,operator) VALUES "
               "(1,'总部','技术部','张三','男','19900101',?,'科长','01','01',?,'01','群众','admin')",
               (_VALID_ID, code))
    db.execute("UPDATE personnel_filing SET personnel_info_id=1 WHERE id=1")
    db.commit(); db.close()

    r = c.post(f"/dict/{did}/edit", data={"csrf_token": _tok(c), "value": "特级" + old,
                                          "sort_order": "0"}, follow_redirects=True)
    assert "历史数据是否一并更新" not in r.get_data(as_text=True), \
        "存编码的类别改名被当成了危险操作"
    assert _scalar("SELECT title FROM personnel_info WHERE id=1") == code, \
        "存编码的列被同步逻辑动过了"
    assert "特级" + old in c.get("/personnel/1").get_data(as_text=True), \
        "改名后历史记录没有显示新名称——存编码的前提不成立"


def test_text_backed_dict_rename_without_choice_is_refused(c):
    """存文字的类别（政治面貌）在用时，改名必须先表态。"""
    did = _dict_id("political_status", "群众")
    html = c.post(f"/dict/{did}/edit", data={"csrf_token": _tok(c), "value": "普通群众",
                                             "sort_order": "0"},
                  follow_redirects=True).get_data(as_text=True)
    assert "历史数据是否一并更新" in html
    assert _scalar("SELECT value FROM sys_dict WHERE id=?", (did,)) == "群众"


def test_text_backed_dict_rename_syncs_all_referencing_tables(c):
    """选择同步：备案人员与撤控备案两张表一起改，且有备份与日志。"""
    did = _dict_id("political_status", "群众")
    tok = _arm_backup_check(c)
    c.post(f"/dict/{did}/edit", data={"csrf_token": tok, "value": "普通群众",
                                      "sort_order": "0", "sync_history": "1"},
           follow_redirects=True)
    assert _scalar("SELECT political_status FROM personnel_filing WHERE id=1") == "普通群众"
    assert _scalar("SELECT political_status FROM decontrol_filing WHERE id=1") == "普通群众"
    assert _snapshots("dict_rename"), f"批量重写历史之前没留下改前快照：{_backups()}"
    assert any("普通群众" in d and "政治面貌" in d for d in _log_details()), \
        f"日志里没有这次同步：{_log_details()[:3]}"


def test_unused_text_dict_rename_is_quiet(c):
    """没人用的字典项改名不问同步——没有历史数据可影响。"""
    did = _dict_id("political_status", "中共党员")
    r = c.post(f"/dict/{did}/edit", data={"csrf_token": _tok(c), "value": "党员",
                                          "sort_order": "0"}, follow_redirects=True)
    assert "历史数据是否一并更新" not in r.get_data(as_text=True)
    assert _scalar("SELECT value FROM sys_dict WHERE id=?", (did,)) == "党员"


def test_dict_page_explains_the_two_kinds(c):
    """页面要讲清两类的区别，并且不能再说「改显示值」可以当停用。"""
    html = c.get("/dict/").get_data(as_text=True)
    assert "存编码" in html and "存文字" in html
    assert "如需停用，可保留或修改显示值" not in html, \
        "旧提示还在——对存文字的类别，改显示值不是停用，是让历史数据失联"


# ---------------------------------------------------------------------------
# B5 报送单位
# ---------------------------------------------------------------------------
def test_submit_unit_rename_without_choice_is_refused(c):
    did = 1
    html = c.post(f"/submit-unit/{did}/edit",
                  data={"csrf_token": _tok(c), "name": "某某市国资委", "contact": "王五",
                        "phone": "13800000000", "sort_order": "0"},
                  follow_redirects=True).get_data(as_text=True)
    assert "历史数据是否一并更新" in html
    assert _scalar("SELECT name FROM sys_submit_unit WHERE id=1") == "某某国资委"


def test_submit_unit_rename_syncs_decontrol_records(c):
    tok = _arm_backup_check(c)
    c.post("/submit-unit/1/edit",
           data={"csrf_token": tok, "name": "某某市国资委", "contact": "王五",
                 "phone": "13800000000", "sort_order": "0", "sync_history": "1"},
           follow_redirects=True)
    assert _scalar("SELECT name FROM sys_submit_unit WHERE id=1") == "某某市国资委"
    assert _scalar("SELECT submit_unit_name FROM decontrol_filing WHERE id=1") == "某某市国资委"
    assert _snapshots("submit_unit_rename"), f"批量重写历史之前没留下改前快照：{_backups()}"
    assert any("某某市国资委" in d for d in _log_details()), "日志里没有这次同步"


def test_submit_unit_contact_edit_is_not_a_rename(c):
    """只改联系人电话不是改名，不该弹同步询问。"""
    r = c.post("/submit-unit/1/edit",
               data={"csrf_token": _tok(c), "name": "某某国资委", "contact": "赵六",
                     "phone": "13900000000", "sort_order": "0"}, follow_redirects=True)
    assert "历史数据是否一并更新" not in r.get_data(as_text=True)
    assert _scalar("SELECT contact FROM sys_submit_unit WHERE id=1") == "赵六"

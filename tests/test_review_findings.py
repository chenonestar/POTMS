"""写《系统需求与分析文档》时逐条把口径对着代码抄，撞出来的四个问题。

它们有个共同点：**一条断言也不会因此变红**。功能都「能用」，数据也没坏——
坏的是「界面上说的」与「代码里做的」对不上，而没有任何自动化手段在看这件事。
所以这四条各配一个用例钉住，免得下次又漂回去。

1. 操作日志的筛选下拉与实际写入的 target_type / action 对不齐；
2. 首页第一行的「证照登记（人）」不按在控过滤，与第二行四档不可比；
3. 证件种类 01 在字典里叫「因私护照」、在台账槽位里叫「普通护照」；
4. 删除出国申请的确认框没讲明附件会一并从磁盘删除。
"""
import re
import sqlite3

import pytest

from config import Config

_CSRF = re.compile(r'name="csrf-token" content="([^"]+)"')
_VALID_ID = "110101199001012133"


@pytest.fixture()
def c(tmp_path, monkeypatch):
    """两个人：#1 在控且持证、名下一条带附件的出国申请；#2 已撤控但台账行还在。"""
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "t.db"))
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(up))
    monkeypatch.setattr(Config, "EXPORT_FOLDER", str(tmp_path / "exp"))
    monkeypatch.setattr(Config, "BACKUP_FOLDER", str(tmp_path / "bak"))
    import database
    database.init_db(); database.run_migrations(); database.seed_data()

    db = sqlite3.connect(Config.DATABASE)
    for pid, nm, st in ((1, "在控甲", "active"), (2, "撤控乙", "decontrolled")):
        db.execute("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,"
                   "id_number,residence,political_status,work_unit,position_or_title,"
                   "supervisor_unit,status,operator) VALUES (?,?,'','男','19900101',?,"
                   "'浙江宁波市鄞州区','群众','总部','科长','人事处',?,'admin')",
                   (pid, nm, _VALID_ID, st))
        db.execute("INSERT INTO certificates (id,personnel_filing_id,unit,department,name,"
                   "passport_no,passport_expiry,passport_submit_date,operator) "
                   "VALUES (?,?,'总部','技术部',?,?,'20351231','20250101','admin')",
                   (pid, pid, nm, f"E{pid}"))
    db.execute("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
               "id_number,destination_passport,category,travel_dates,need_new_passport,operator) "
               "VALUES (1,1,'总部','技术部','在控甲','科长',?,'美国/护照','旅游','2026-05','否','admin')",
               (_VALID_ID,))
    for i in (1, 2, 3):
        db.execute("INSERT INTO attachments (travel_id,file_name,file_path,file_type,file_size) "
                   "VALUES (1,?,?,'个人申请报告',10)", (f"a{i}.pdf", f"a{i}.pdf"))
    db.commit(); db.close()

    from app import create_app
    cl = create_app().test_client()
    tok = _CSRF.search(cl.get("/login").get_data(as_text=True)).group(1)
    cl.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": tok})
    return cl


def _tok(cl):
    return _CSRF.search(cl.get("/").get_data(as_text=True)).group(1)


def _row(html, needle):
    """截出含 needle 的那一行 <tr>，避免拿整页做断言。"""
    i = html.find(needle)
    assert i != -1, f"页面上找不到「{needle}」"
    return html[html.rfind("<tr", 0, i):html.find("</tr>", i)]


# ---------------------------------------------------------------------------
# 1. 操作日志：筛选下拉必须覆盖代码实际写入的每一个取值
# ---------------------------------------------------------------------------
def _written_targets_and_actions():
    """把代码里所有 log_action() 的前两个参数枚举出来。

    这是本条问题的发现方式，也是唯一能防它复发的办法：靠人核对，下次照样漏。
    """
    import pathlib
    pat = re.compile(r'log_action\(\s*"([a-z_]+)"\s*,\s*"([a-z_]+)"')
    root = pathlib.Path(__file__).resolve().parent.parent
    actions, targets = set(), set()
    for d in ("blueprints", "utils"):
        for f in (root / d).glob("*.py"):
            for a, t in pat.findall(f.read_text(encoding="utf-8")):
                actions.add(a); targets.add(t)
    for a, t in pat.findall((root / "auth.py").read_text(encoding="utf-8")):
        actions.add(a); targets.add(t)
    return actions, targets


def test_log_filter_options_cover_everything_written(c):
    """代码写进日志的每一个 action / target_type，下拉里都要能选到。

    此前有 5 个取值写得进、筛不出：动作 void，目标 cert_issuance / sys_org /
    database / operation_logs。日志本身记全了，丢的是筛选能力——不翻页就看不到。
    """
    actions, targets = _written_targets_and_actions()
    from blueprints.logs import TARGET_ALIASES
    html = c.get("/logs/").get_data(as_text=True)

    def options(select_name):
        """只取这一个 <select> 里的选项——两个下拉都在页上，混着取就分不出谁缺了。"""
        block = html.split(f'name="{select_name}"', 1)[1].split("</select>", 1)[0]
        return {v for v in re.findall(r'<option value="([a-z_]*)"', block) if v}

    missing_a = actions - options("action")
    assert not missing_a, f"这些动作写得进日志却筛不出来：{sorted(missing_a)}"

    # 目标类型：一个选项可以覆盖它历史上出现过的多种写法（见 TARGET_ALIASES）
    covered = set()
    for code in options("target_type"):
        covered.update(TARGET_ALIASES.get(code, (code,)))
    missing_t = targets - covered
    assert not missing_t, f"这些目标类型写得进日志却筛不出来：{sorted(missing_t)}"


def test_certificate_crud_is_filterable_as_certificates(c):
    """按「证照登记表」筛，要筛得出证照的增删改。

    增删改一直写的是单数 target_type="certificate"，导出写的是复数
    "certificates"，而下拉里只有复数——按它筛只能筛出导出记录，
    一条增删改也筛不到，偏偏增删改才是查日志时最要看的。

    代码这一侧已统一为复数；库里的历史日志仍是单数，而日志是审计记录，
    不该为了好看去重写它，所以筛选按别名匹配。
    """
    db = sqlite3.connect(Config.DATABASE)
    # 一条「历史」日志（旧写法）+ 走界面产生一条新日志（新写法）
    db.execute("INSERT INTO operation_logs (operator,action,target_type,target_id,detail) "
               "VALUES ('admin','update','certificate',1,'历史单数写法')")
    db.commit(); db.close()
    c.post("/certificate/1/edit", data={
        "personnel_filing_id": "1", "unit": "总部", "department": "技术部", "name": "在控甲",
        "passport_no": "E1-NEW", "passport_expiry": "20351231",
        "passport_submit_date": "20250101", "csrf_token": _tok(c)}, follow_redirects=True)

    html = c.get("/logs/?target_type=certificates").get_data(as_text=True)
    assert "历史单数写法" in html, "旧的单数写法筛不出来了"
    assert "E1-NEW" in html or "证照" in html, "新写法也没筛出来"


# ---------------------------------------------------------------------------
# 2. 首页两行统计的口径要可比
# ---------------------------------------------------------------------------
def _stat_value(html, label):
    m = re.search(r'<div class="stat-label">' + re.escape(label) +
                  r'</div>\s*<div class="stat-value[^"]*">(\d+)</div>', html)
    assert m, f"首页上找不到「{label}」这张卡"
    return int(m.group(1))


def test_certificate_card_counts_active_holders_only(c):
    """「证照登记（人）」只数在控人员，与下面四档同口径。

    原来是 COUNT(*) FROM certificates，不按状态过滤：撤控一个人，他的台账行
    仍计进这张卡，他的证却已退出「在库」。两个数并排摆着，看的人无从知道口径不同。
    """
    html = c.get("/").get_data(as_text=True)
    assert _stat_value(html, "有效备案人员") == 1
    assert _stat_value(html, "证照登记（人）") == 1, \
        "已撤控人员的台账行被算进「证照登记」了——与下面四档不可比"


def test_certificate_card_links_to_a_list_that_shows_the_same_number(c):
    """数字与点开看到的列表必须一致，否则说明口径只改了一半。"""
    dash = c.get("/").get_data(as_text=True)
    assert "filing_status=active" in dash, "卡片链接没带上在控筛选"

    html = c.get("/certificate/?filing_status=active").get_data(as_text=True)
    assert "在控甲" in html and "撤控乙" not in html
    assert _stat_value(dash, "证照登记（人）") == html.count('class="row-check"')


def test_ledger_without_the_filter_still_shows_everyone(c):
    """不带参数时台账照旧显示全部——已撤控的行上有标注，本来就该看得到。"""
    html = c.get("/certificate/").get_data(as_text=True)
    assert "在控甲" in html and "撤控乙" in html


# ---------------------------------------------------------------------------
# 3. 证件种类：字典与台账槽位一个叫法
# ---------------------------------------------------------------------------
def test_cert_type_dictionary_matches_the_ledger_slot_label(c):
    """字典 cert_type 的显示值必须与 CERT_SLOTS 的槽位标签一字不差。

    原来 01 在字典里叫「因私护照」、在台账里叫「普通护照」。同一本证两个叫法，
    只要有人写一段按名称匹配的代码（导入校验、报表归类、跨版本对齐），
    立刻就是个真 bug。
    """
    from blueprints.certificate import CERT_SLOTS
    db = sqlite3.connect(Config.DATABASE)
    dict_values = [r[0] for r in db.execute(
        "SELECT value FROM sys_dict WHERE category='cert_type' ORDER BY sort_order")]
    db.close()
    assert dict_values == [label for label, *_ in CERT_SLOTS], \
        f"字典叫法 {dict_values} 与台账槽位标签对不上"


def test_migration_renames_the_legacy_dictionary_value(c):
    """老库里还叫「因私护照」的，迁移要跟着改过来（业务表存的是编码，不受影响）。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("UPDATE sys_dict SET value='因私护照' WHERE category='cert_type' AND code='01'")
    db.commit(); db.close()

    import database
    database.run_migrations()

    db = sqlite3.connect(Config.DATABASE)
    v = db.execute("SELECT value FROM sys_dict WHERE category='cert_type' AND code='01'").fetchone()[0]
    db.close()
    assert v == "普通护照", "迁移没有把旧叫法改过来"


# ---------------------------------------------------------------------------
# 4. 删除出国申请的确认框要讲明后果
# ---------------------------------------------------------------------------
def test_delete_confirm_names_the_attachments_that_go_with_it(c):
    """删除出国申请会连带删掉磁盘上的附件文件，且不可恢复——确认框得说出来。

    原来只有一句「确定要删除 X 的出国申请记录吗？」。按提示文案规约，
    不可逆的后果必须讲明，而且要给数量（本例 3 个附件）。
    """
    row = _row(c.get("/travel/").get_data(as_text=True), "/travel/1/delete")
    assert "3 个附件" in row, f"确认框没说清有几个附件会一起删：{row}"
    assert "无法恢复" in row


def test_delete_confirm_without_attachments_still_says_it_is_final(c):
    """没有附件时也要说清「删除后无法恢复」，并指出日志留了快照。"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("DELETE FROM attachments WHERE travel_id=1")
    db.commit(); db.close()

    row = _row(c.get("/travel/").get_data(as_text=True), "/travel/1/delete")
    assert "附件" not in row, "没有附件却还在吓唬人"
    assert "无法恢复" in row and "操作日志" in row


# ---------------------------------------------------------------------------
# 顺带：空状态样式不该套到数据单元格上
# ---------------------------------------------------------------------------
def test_empty_state_style_keys_on_colspan_not_text_muted():
    """「暂无记录」那条 32px 上下留白的规则，判据必须是 td[colspan]。

    原来写的是 .table tbody td.text-muted —— 而 text-muted 是 Bootstrap 的通用
    工具类，正常数据单元格也在用（盘库清单的行号列、日志变更表的旧值列），
    于是那几张表的行高被撑到近两倍（实测 88px vs 全站 39px）。
    """
    import pathlib
    css = (pathlib.Path(__file__).resolve().parent.parent
           / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert ".table tbody td[colspan]" in css
    assert ".table tbody td.text-muted" not in css, \
        "空状态样式又按 .text-muted 匹配了，会把普通数据行撑高"

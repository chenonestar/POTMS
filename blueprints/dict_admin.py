"""数据字典维护 — 学历/学位/职称/职级/政治面貌/出国类别/报送单位类别"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db
from utils.helpers import log_action, row_snapshot
from utils.textref import (TextRef, backup_before_bulk_edit, count_refs,
                           describe_refs, sync_refs)

dict_bp = Blueprint("dict_admin", __name__)

# 各字典类别及其被引用的列。
#
# stores 记的是**业务表里到底存的是编码还是显示值**。两种表单写法都存在，
# 而它们对「改显示值」的后果截然相反：
#
# - stores="code"（学历/学位/职称/职级）：表单 <option value="{{ o.code }}">，
#   库里存的是 01/02。显示值只是这个编码的当前叫法，改名后所有历史记录跟着
#   改过来显示——改名是安全的，什么也不用同步。
# - stores="text"（政治面貌/出国类别/报送单位类别/人事主管单位）：表单
#   <option value="{{ o.value }}">，库里存的就是「群众」这三个字。改名之后
#   历史数据仍是旧文字，而下拉里只剩新文字——按新值筛一条也搜不到，
#   同一项在统计里裂成两个。改名必须问清楚历史数据跟不跟着走。
#
# stores 只用来在界面上标注和解释这个区别；「要不要问同步」由实际统计说了算
# （见 edit()），因为存编码的列天然统计不到显示值，不需要再按标注拦一道。
#
# 删除保护对两者一视同仁：编码或显示值命中都算在用。
CATEGORIES = [
    {"key": "education", "label": "学历", "stores": "code",
     "refs": [TextRef("personnel_info", "education", "人员信息·学历")]},
    {"key": "degree", "label": "学位", "stores": "code",
     "refs": [TextRef("personnel_info", "degree", "人员信息·学位")]},
    {"key": "title", "label": "职称", "stores": "code",
     "refs": [TextRef("personnel_info", "title", "人员信息·职称"),
              TextRef("travel_details", "title", "出国申请·职称")]},
    {"key": "rank", "label": "职级", "stores": "code",
     "refs": [TextRef("personnel_info", "rank", "人员信息·职级")]},
    {"key": "political_status", "label": "政治面貌", "stores": "text",
     "refs": [TextRef("personnel_info", "political_status", "人员信息·政治面貌"),
              TextRef("personnel_filing", "political_status", "备案人员·政治面貌"),
              TextRef("decontrol_filing", "political_status", "撤控备案·政治面貌")]},
    {"key": "travel_category", "label": "出国（境）类别", "stores": "text",
     "refs": [TextRef("travel_details", "category", "出国申请·类别")]},
    {"key": "submit_unit_type", "label": "报送单位类别", "stores": "text",
     "refs": [TextRef("decontrol_filing", "submit_unit_type", "撤控备案·报送单位类别")]},
    {"key": "supervisor_unit", "label": "人事主管单位", "stores": "text",
     "refs": [TextRef("personnel_filing", "supervisor_unit", "备案人员·人事主管单位"),
              TextRef("decontrol_filing", "supervisor_unit", "撤控备案·人事主管单位")]},
]
_CAT_MAP = {c["key"]: c for c in CATEGORIES}


def _usage_count(db, category: str, code: str, value: str) -> int:
    """统计某字典项被业务记录引用的次数（编码或显示值命中）。"""
    cat = _CAT_MAP.get(category)
    if not cat:
        return 0
    total = 0
    for ref in cat["refs"]:
        row = db.execute(
            f"SELECT COUNT(*) FROM {ref.table} WHERE {ref.column} = ? OR {ref.column} = ?",
            (code, value),
        ).fetchone()
        total += row[0]
    return total


@dict_bp.route("/dict/")
@login_required
def index() -> ResponseReturnValue:
    db = get_db()
    groups = []
    usage = {}
    for cat in CATEGORIES:
        items = db.execute(
            "SELECT * FROM sys_dict WHERE category = ? ORDER BY sort_order, code", (cat["key"],)
        ).fetchall()
        # 统计的是「有多少条记录存着这几个字」。存编码的类别正常都是 0，
        # 于是编辑框里也就不会冒出那个同步勾选框——不用另加判断。
        for it in items:
            usage[it["id"]] = sum(n for _, n in count_refs(cat["refs"], it["value"]))
        groups.append({"key": cat["key"], "label": cat["label"],
                       "stores": cat["stores"], "rows": items})
    return render_template("dict/list.html", groups=groups, usage=usage)


@dict_bp.route("/dict/add", methods=["POST"])
@login_required
def add() -> ResponseReturnValue:
    category = request.form.get("category", "").strip()
    code = request.form.get("code", "").strip()
    value = request.form.get("value", "").strip()
    sort_raw = request.form.get("sort_order", "0").strip()
    sort_order = int(sort_raw) if sort_raw.lstrip("-").isdigit() else 0

    if category not in _CAT_MAP:
        flash("无效的字典类别。", "danger")
        return redirect(url_for("dict_admin.index"))
    if not code or not value:
        flash("编码与显示值均为必填。", "danger")
        return redirect(url_for("dict_admin.index"))

    db = get_db()
    dup = db.execute(
        "SELECT id FROM sys_dict WHERE category = ? AND code = ?", (category, code)
    ).fetchone()
    if dup:
        flash(f"「{_CAT_MAP[category]['label']}」下编码 {code} 已存在。", "warning")
        return redirect(url_for("dict_admin.index"))

    db.execute(
        "INSERT INTO sys_dict (category, code, value, sort_order) VALUES (?, ?, ?, ?)",
        (category, code, value, sort_order),
    )
    db.commit()
    new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    log_action("create", "sys_dict", new_id,
               detail=f"{_CAT_MAP[category]['label']}: {code}={value}",
               after=row_snapshot("sys_dict", new_id))
    flash("字典项已添加。", "success")
    return redirect(url_for("dict_admin.index"))


@dict_bp.route("/dict/<int:dict_id>/edit", methods=["POST"])
@login_required
def edit(dict_id) -> ResponseReturnValue:
    db = get_db()
    row = db.execute("SELECT * FROM sys_dict WHERE id = ?", (dict_id,)).fetchone()
    if not row:
        flash("字典项不存在。", "danger")
        return redirect(url_for("dict_admin.index"))

    value = request.form.get("value", "").strip()
    sort_raw = request.form.get("sort_order", "0").strip()
    sort_order = int(sort_raw) if sort_raw.lstrip("-").isdigit() else 0
    if not value:
        flash("显示值为必填。", "danger")
        return redirect(url_for("dict_admin.index"))

    cat = _CAT_MAP.get(row["category"], {})
    renamed = value != row["value"]
    # 判据是「有没有业务记录存着这几个字」，而不是类别的 stores 标注。
    # 存编码的类别正常情况下天然是 0（库里存的是 01/02，对不上显示值），不会被问；
    # 但历史导入偶尔会把文字直接写进这些列，那时它就该被问——按标注一刀切反而漏掉。
    counts = count_refs(cat["refs"], row["value"]) if renamed else []
    syncing = bool(counts) and bool(request.form.get("sync_history"))

    if counts and not request.form.get("sync_history"):
        flash(f"「{row['value']}」已被 {describe_refs(counts)} 引用，而这一项在业务表里"
              "存的是文字本身。请在编辑框里选择历史数据是否一并更新——不勾选就只改"
              "下拉选项，历史数据仍是旧文字，按新值筛选一条也搜不到。", "warning")
        return redirect(url_for("dict_admin.index"))
    snapshot = None
    if syncing:
        snapshot, err = backup_before_bulk_edit("dict_rename")
        if err:
            flash(err, "danger")
            return redirect(url_for("dict_admin.index"))

    before = dict(row)
    db.execute("UPDATE sys_dict SET value = ?, sort_order = ? WHERE id = ?", (value, sort_order, dict_id))
    db.commit()

    if syncing:
        changed = sync_refs(cat["refs"], row["value"], value)
        log_action("update", "sys_dict", dict_id, before=before,
                   after=row_snapshot("sys_dict", dict_id),
                   detail=f"{cat['label']}改名同步历史数据：{row['value']} → {value}，"
                          f"共 {changed} 条（{describe_refs(counts)}）；改前快照 {snapshot}")
        flash(f"字典项已更新；并同步了 {changed} 条历史数据。"
              f"改动前的快照已存为 backup/{snapshot}，需要回退时用它替换 data.db。", "success")
    else:
        log_action("update", "sys_dict", dict_id, before=before, after=row_snapshot("sys_dict", dict_id))
        flash("字典项已更新。", "success")
    return redirect(url_for("dict_admin.index"))


@dict_bp.route("/dict/<int:dict_id>/delete", methods=["POST"])
@login_required
def delete(dict_id) -> ResponseReturnValue:
    db = get_db()
    row = db.execute("SELECT * FROM sys_dict WHERE id = ?", (dict_id,)).fetchone()
    if not row:
        flash("字典项不存在。", "danger")
        return redirect(url_for("dict_admin.index"))

    used = _usage_count(db, row["category"], row["code"], row["value"])
    if used:
        flash(f"「{row['value']}」已被 {used} 条记录使用，不能删除（可改用编辑或保留）。", "warning")
        return redirect(url_for("dict_admin.index"))

    before = dict(row)
    db.execute("DELETE FROM sys_dict WHERE id = ?", (dict_id,))
    db.commit()
    log_action("delete", "sys_dict", dict_id, before=before)
    flash("字典项已删除。", "info")
    return redirect(url_for("dict_admin.index"))

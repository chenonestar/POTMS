"""数据字典维护 — 学历/学位/职称/职级/政治面貌/出国类别/报送单位类别"""
from flask import Blueprint, render_template, request, redirect, url_for, flash

from auth import login_required
from database import get_db
from utils.helpers import log_action, row_snapshot

dict_bp = Blueprint("dict_admin", __name__)

# 各字典类别及其被引用的列（用于删除保护，编码或显示值命中即视为在用）
CATEGORIES = [
    {"key": "education", "label": "学历", "refs": [("personnel_info", "education")]},
    {"key": "degree", "label": "学位", "refs": [("personnel_info", "degree")]},
    {"key": "title", "label": "职称", "refs": [("personnel_info", "title"), ("travel_details", "title")]},
    {"key": "rank", "label": "职级", "refs": [("personnel_info", "rank")]},
    {"key": "political_status", "label": "政治面貌",
     "refs": [("personnel_info", "political_status"), ("personnel_filing", "political_status"),
              ("decontrol_filing", "political_status")]},
    {"key": "travel_category", "label": "出国（境）类别", "refs": [("travel_details", "category")]},
    {"key": "submit_unit_type", "label": "报送单位类别", "refs": [("decontrol_filing", "submit_unit_type")]},
    {"key": "supervisor_unit", "label": "人事主管单位",
     "refs": [("personnel_filing", "supervisor_unit"), ("decontrol_filing", "supervisor_unit")]},
]
_CAT_MAP = {c["key"]: c for c in CATEGORIES}


def _usage_count(db, category: str, code: str, value: str) -> int:
    """统计某字典项被业务记录引用的次数（编码或显示值命中）。"""
    cat = _CAT_MAP.get(category)
    if not cat:
        return 0
    total = 0
    for table, col in cat["refs"]:
        row = db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col} = ? OR {col} = ?", (code, value)
        ).fetchone()
        total += row[0]
    return total


@dict_bp.route("/dict/")
@login_required
def index():
    db = get_db()
    groups = []
    for cat in CATEGORIES:
        items = db.execute(
            "SELECT * FROM sys_dict WHERE category = ? ORDER BY sort_order, code", (cat["key"],)
        ).fetchall()
        groups.append({"key": cat["key"], "label": cat["label"], "rows": items})
    return render_template("dict/list.html", groups=groups)


@dict_bp.route("/dict/add", methods=["POST"])
@login_required
def add():
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
def edit(dict_id):
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

    before = dict(row)
    db.execute("UPDATE sys_dict SET value = ?, sort_order = ? WHERE id = ?", (value, sort_order, dict_id))
    db.commit()
    log_action("update", "sys_dict", dict_id, before=before, after=row_snapshot("sys_dict", dict_id))
    flash("字典项已更新。", "success")
    return redirect(url_for("dict_admin.index"))


@dict_bp.route("/dict/<int:dict_id>/delete", methods=["POST"])
@login_required
def delete(dict_id):
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

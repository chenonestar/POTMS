"""报送单位维护 — 名称 / 联系人 / 电话（撤控表下拉联动）"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db
from utils.helpers import log_action, row_snapshot
from utils.textref import (TextRef, backup_before_bulk_edit, count_refs,
                           describe_refs, sync_refs)

submit_unit_bp = Blueprint("submit_unit", __name__)

# 撤控备案单上的报送单位存的是名字的文字（单据要定格在开单那天的抬头），
# 所以这张配置表改名之后，历史撤控记录仍挂在旧名下，按新名筛一条也搜不到。
SUBMIT_UNIT_REFS = (
    TextRef("decontrol_filing", "submit_unit_name", "撤控备案·报送单位"),
)


def _sort(raw: str) -> int:
    raw = (raw or "0").strip()
    return int(raw) if raw.lstrip("-").isdigit() else 0


@submit_unit_bp.route("/submit-unit/")
@login_required
def index() -> ResponseReturnValue:
    db = get_db()
    rows = db.execute("SELECT * FROM sys_submit_unit ORDER BY sort_order, name").fetchall()
    usage = {r["id"]: sum(n for _, n in count_refs(SUBMIT_UNIT_REFS, r["name"])) for r in rows}
    return render_template("submit_unit/list.html", rows=rows, usage=usage)


@submit_unit_bp.route("/submit-unit/add", methods=["POST"])
@login_required
def add() -> ResponseReturnValue:
    name = request.form.get("name", "").strip()
    contact = request.form.get("contact", "").strip()
    phone = request.form.get("phone", "").strip()
    if not name:
        flash("单位名称为必填。", "danger")
        return redirect(url_for("submit_unit.index"))
    db = get_db()
    if db.execute("SELECT id FROM sys_submit_unit WHERE name = ?", (name,)).fetchone():
        flash("该报送单位已存在。", "warning")
        return redirect(url_for("submit_unit.index"))
    db.execute("INSERT INTO sys_submit_unit (name, contact, phone, sort_order) VALUES (?, ?, ?, ?)",
               (name, contact, phone, _sort(request.form.get("sort_order"))))
    db.commit()
    nid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    log_action("create", "sys_submit_unit", nid, detail=name, after=row_snapshot("sys_submit_unit", nid))
    flash("报送单位已添加。", "success")
    return redirect(url_for("submit_unit.index"))


@submit_unit_bp.route("/submit-unit/<int:uid>/edit", methods=["POST"])
@login_required
def edit(uid) -> ResponseReturnValue:
    db = get_db()
    row = db.execute("SELECT * FROM sys_submit_unit WHERE id = ?", (uid,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("submit_unit.index"))
    name = request.form.get("name", "").strip()
    if not name:
        flash("单位名称为必填。", "danger")
        return redirect(url_for("submit_unit.index"))
    counts = count_refs(SUBMIT_UNIT_REFS, row["name"]) if name != row["name"] else []
    syncing = bool(counts) and bool(request.form.get("sync_history"))
    if counts and not request.form.get("sync_history"):
        flash(f"「{row['name']}」已被 {describe_refs(counts)} 引用。改名前请在编辑框里选择"
              "历史数据是否一并更新——不勾选就只改这张配置表，历史撤控记录仍挂在旧名下。",
              "warning")
        return redirect(url_for("submit_unit.index"))
    if syncing and (err := backup_before_bulk_edit()):
        flash(err, "danger")
        return redirect(url_for("submit_unit.index"))

    before = dict(row)
    db.execute("UPDATE sys_submit_unit SET name = ?, contact = ?, phone = ?, sort_order = ? WHERE id = ?",
               (name, request.form.get("contact", "").strip(), request.form.get("phone", "").strip(),
                _sort(request.form.get("sort_order")), uid))
    db.commit()

    if syncing:
        changed = sync_refs(SUBMIT_UNIT_REFS, row["name"], name)
        log_action("update", "sys_submit_unit", uid, before=before,
                   after=row_snapshot("sys_submit_unit", uid),
                   detail=f"报送单位改名同步历史数据：{row['name']} → {name}，共 {changed} 条")
        flash(f"报送单位已更新；并同步了 {changed} 条历史撤控记录。改动前已自动备份。", "success")
    else:
        log_action("update", "sys_submit_unit", uid, before=before, after=row_snapshot("sys_submit_unit", uid))
        flash("报送单位已更新。", "success")
    return redirect(url_for("submit_unit.index"))


@submit_unit_bp.route("/submit-unit/<int:uid>/delete", methods=["POST"])
@login_required
def delete(uid) -> ResponseReturnValue:
    db = get_db()
    row = db.execute("SELECT * FROM sys_submit_unit WHERE id = ?", (uid,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("submit_unit.index"))
    used = db.execute("SELECT COUNT(*) FROM decontrol_filing WHERE submit_unit_name = ?",
                      (row["name"],)).fetchone()[0]
    if used:
        flash(f"「{row['name']}」已被 {used} 条撤控记录使用，不能删除。", "warning")
        return redirect(url_for("submit_unit.index"))
    before = dict(row)
    db.execute("DELETE FROM sys_submit_unit WHERE id = ?", (uid,))
    db.commit()
    log_action("delete", "sys_submit_unit", uid, before=before)
    flash("报送单位已删除。", "info")
    return redirect(url_for("submit_unit.index"))

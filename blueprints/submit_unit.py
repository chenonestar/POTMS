"""报送单位维护 — 名称 / 联系人 / 电话（撤控表下拉联动）"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db
from utils.helpers import log_action, row_snapshot

submit_unit_bp = Blueprint("submit_unit", __name__)


def _sort(raw: str) -> int:
    raw = (raw or "0").strip()
    return int(raw) if raw.lstrip("-").isdigit() else 0


@submit_unit_bp.route("/submit-unit/")
@login_required
def index() -> ResponseReturnValue:
    db = get_db()
    rows = db.execute("SELECT * FROM sys_submit_unit ORDER BY sort_order, name").fetchall()
    return render_template("submit_unit/list.html", rows=rows)


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
    before = dict(row)
    db.execute("UPDATE sys_submit_unit SET name = ?, contact = ?, phone = ?, sort_order = ? WHERE id = ?",
               (name, request.form.get("contact", "").strip(), request.form.get("phone", "").strip(),
                _sort(request.form.get("sort_order")), uid))
    db.commit()
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

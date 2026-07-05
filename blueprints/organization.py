"""单位/部门树形组织结构维护"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db
from utils.helpers import log_action

org_bp = Blueprint("organization", __name__)


@org_bp.route("/org/")
@login_required
def index() -> ResponseReturnValue:
    db = get_db()
    orgs = db.execute("SELECT * FROM sys_org ORDER BY parent_id, sort_order").fetchall()
    return render_template("organization/tree.html", orgs=orgs)


@org_bp.route("/org/add", methods=["POST"])
@login_required
def add() -> ResponseReturnValue:
    name = request.form.get("name", "").strip()
    parent_id = request.form.get("parent_id", 0, type=int)
    if not name:
        flash("请输入单位/部门名称。", "danger")
        return redirect(url_for("organization.index"))

    db = get_db()
    db.execute("INSERT INTO sys_org (name, parent_id, sort_order) VALUES (?, ?, 0)", (name, parent_id))
    db.commit()
    log_action("create", "sys_org", detail=name)
    flash(f"已添加：{name}", "success")
    return redirect(url_for("organization.index"))


@org_bp.route("/org/<int:org_id>/edit", methods=["POST"])
@login_required
def edit(org_id) -> ResponseReturnValue:
    name = request.form.get("name", "").strip()
    parent_id = request.form.get("parent_id", 0, type=int)
    if not name:
        flash("名称不能为空。", "danger")
        return redirect(url_for("organization.index"))

    db = get_db()
    db.execute("UPDATE sys_org SET name = ?, parent_id = ? WHERE id = ?", (name, parent_id, org_id))
    db.commit()
    log_action("update", "sys_org", org_id, detail=name)
    flash(f"已更新：{name}", "success")
    return redirect(url_for("organization.index"))


@org_bp.route("/org/<int:org_id>/delete", methods=["POST"])
@login_required
def delete(org_id) -> ResponseReturnValue:
    db = get_db()
    # 检查是否有子节点
    children = db.execute("SELECT COUNT(*) FROM sys_org WHERE parent_id = ?", (org_id,)).fetchone()[0]
    if children > 0:
        flash("该节点下还有子部门，请先删除子部门。", "danger")
        return redirect(url_for("organization.index"))
    db.execute("DELETE FROM sys_org WHERE id = ?", (org_id,))
    db.commit()
    log_action("delete", "sys_org", org_id)
    flash("已删除。", "info")
    return redirect(url_for("organization.index"))


@org_bp.route("/org/tree-data")
@login_required
def tree_data() -> ResponseReturnValue:
    """供前端 AJAX 获取树形数据"""
    db = get_db()
    orgs = db.execute("SELECT id, name, parent_id FROM sys_org ORDER BY parent_id, sort_order").fetchall()
    result = []
    for o in orgs:
        result.append({"id": o["id"], "name": o["name"], "parent_id": o["parent_id"]})
    return jsonify(result)

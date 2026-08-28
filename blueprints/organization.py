"""单位/部门树形组织结构维护"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db
from utils.helpers import log_action
from utils.textref import (ORG_REFS, backup_before_bulk_edit, count_refs,
                           describe_refs, sync_refs, total_refs)

org_bp = Blueprint("organization", __name__)


@org_bp.route("/org/")
@login_required
def index() -> ResponseReturnValue:
    db = get_db()
    orgs = db.execute("SELECT * FROM sys_org ORDER BY parent_id, sort_order").fetchall()
    # 每个节点被多少条业务数据引用着。树上直接标出来，是为了让「这个能不能删、
    # 改名会波及多少」在动手之前就看得见，而不是点了删除才被弹回来。
    usage = {o["id"]: total_refs(ORG_REFS, o["name"]) for o in orgs}
    return render_template("organization/tree.html", orgs=orgs, usage=usage)


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
    row = db.execute("SELECT * FROM sys_org WHERE id = ?", (org_id,)).fetchone()
    if not row:
        flash("节点不存在。", "danger")
        return redirect(url_for("organization.index"))
    old = row["name"]

    # 改名要不要带上历史数据，得先问清楚。业务表里存的是名字的文字，不改则历史
    # 数据留在旧名下（同一个单位在统计里裂成两个），改则是批量重写历史。
    counts = count_refs(ORG_REFS, old) if name != old else []
    if counts and not request.form.get("sync_history"):
        flash(f"「{old}」已被 {describe_refs(counts)} 引用。改名前请在重命名框里选择"
              "历史数据是否一并更新——不勾选就只改组织树，历史数据仍留在旧名下。", "warning")
        return redirect(url_for("organization.index"))

    # 同名节点存在时无法按文字区分是谁的历史。「技术部」在两个单位下各有一个，
    # 一条 UPDATE 会把两边都扫走，而这不是用户要的。宁可不同步，也不能改错别人的。
    if counts and request.form.get("sync_history"):
        clash = db.execute(
            "SELECT COUNT(*) FROM sys_org WHERE name = ? AND id != ?", (old, org_id)
        ).fetchone()[0]
        if clash:
            flash(f"组织树上还有 {clash} 个节点同叫「{old}」，历史数据按文字分不出属于哪一个，"
                  "已中止同步。请先把重名的节点改成可区分的名称。", "danger")
            return redirect(url_for("organization.index"))
        if err := backup_before_bulk_edit():
            flash(err, "danger")
            return redirect(url_for("organization.index"))

    db.execute("UPDATE sys_org SET name = ?, parent_id = ? WHERE id = ?", (name, parent_id, org_id))
    db.commit()

    if counts and request.form.get("sync_history"):
        changed = sync_refs(ORG_REFS, old, name)
        log_action("update", "sys_org", org_id,
                   detail=f"组织改名同步历史数据：{old} → {name}，共 {changed} 条"
                          f"（{describe_refs(counts)}）")
        flash(f"已更新：{name}；并同步了 {changed} 条历史数据。改动前已自动备份。", "success")
    else:
        log_action("update", "sys_org", org_id, detail=name)
        flash(f"已更新：{name}", "success")
    return redirect(url_for("organization.index"))


@org_bp.route("/org/<int:org_id>/delete", methods=["POST"])
@login_required
def delete(org_id) -> ResponseReturnValue:
    db = get_db()
    row = db.execute("SELECT * FROM sys_org WHERE id = ?", (org_id,)).fetchone()
    if not row:
        flash("节点不存在。", "danger")
        return redirect(url_for("organization.index"))
    # 检查是否有子节点
    children = db.execute("SELECT COUNT(*) FROM sys_org WHERE parent_id = ?", (org_id,)).fetchone()[0]
    if children > 0:
        flash("该节点下还有子部门，请先删除子部门。", "danger")
        return redirect(url_for("organization.index"))

    # 业务数据里存的是名字的文字，删掉节点不会动它们——那些「技术部」会原地变成
    # 下拉里再也选不到的孤儿值：按部门筛选选不出来，导入校验也认不了。
    # 所以有人用就不许删；确实不用了，请先把那些数据改到别的单位/部门下。
    counts = count_refs(ORG_REFS, row["name"])
    if counts:
        flash(f"「{row['name']}」仍被 {describe_refs(counts)} 引用，不能删除。"
              "如该单位/部门已撤销，请先把这些数据改挂到其他单位/部门下，或改用重命名。",
              "danger")
        return redirect(url_for("organization.index"))

    db.execute("DELETE FROM sys_org WHERE id = ?", (org_id,))
    db.commit()
    log_action("delete", "sys_org", org_id, detail=row["name"])
    flash(f"已删除：{row['name']}", "info")
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

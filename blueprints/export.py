"""导出 & 打印蓝图"""
from flask import Blueprint, render_template, send_file, flash, redirect, url_for, session, request
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db
from utils.excel_export import (
    export_personnel_info,
    export_personnel_filing,
    export_certificates,
    export_travel_details,
    export_decontrol,
)
from utils.helpers import log_action

export_bp = Blueprint("export", __name__)


def _operator():
    return session.get("username", "unknown")


def _selected_ids():
    """从查询串解析选中行 ID（?ids=1,2,3）"""
    raw = request.args.get("ids", "")
    return [int(x) for x in raw.split(",") if x.strip().isdigit()]


def _scope_note(where_sql, ids) -> str:
    if ids:
        return f"选中{len(ids)}行"
    if where_sql:
        return "按筛选条件"
    return "全量"


# =========================================================================
# Excel 导出 — 5 类表单（支持 全量 / 按筛选 / 选中行）
# =========================================================================
@export_bp.route("/export/info")
@login_required
def info_export() -> ResponseReturnValue:
    from blueprints.personnel import build_filters
    try:
        ids = _selected_ids()
        where, params = build_filters(request.args, ids=ids or None)
        # 有筛选或选中时经 filing 关联导出；否则全量导出信息表
        joined = bool(where)
        filepath, filename = export_personnel_info(_operator(), where, params, joined=joined)
        log_action("export", "personnel_info", detail=f"{filename}（{_scope_note(where, ids)}）")
        return send_file(filepath, as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f"导出失败: {e}", "danger")
        return redirect(url_for("personnel.list"))


@export_bp.route("/export/filing")
@login_required
def filing_export() -> ResponseReturnValue:
    from blueprints.personnel import build_filters
    try:
        ids = _selected_ids()
        where, params = build_filters(request.args, ids=ids or None)
        filepath, filename = export_personnel_filing(_operator(), where, params)
        log_action("export", "personnel_filing", detail=f"{filename}（{_scope_note(where, ids)}）")
        return send_file(filepath, as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f"导出失败: {e}", "danger")
        return redirect(url_for("personnel.list"))


@export_bp.route("/export/certificate")
@login_required
def certificate_export() -> ResponseReturnValue:
    from blueprints.certificate import build_filters
    try:
        ids = _selected_ids()
        where, params = build_filters(request.args, ids=ids or None)
        filepath, filename = export_certificates(_operator(), where, params)
        log_action("export", "certificates", detail=f"{filename}（{_scope_note(where, ids)}）")
        return send_file(filepath, as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f"导出失败: {e}", "danger")
        return redirect(url_for("certificate.list"))


@export_bp.route("/export/travel")
@login_required
def travel_export() -> ResponseReturnValue:
    from blueprints.travel import build_filters
    try:
        ids = _selected_ids()
        where, params = build_filters(request.args, ids=ids or None)
        filepath, filename = export_travel_details(_operator(), where, params)
        log_action("export", "travel_details", detail=f"{filename}（{_scope_note(where, ids)}）")
        return send_file(filepath, as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f"导出失败: {e}", "danger")
        return redirect(url_for("travel.list"))


@export_bp.route("/export/decontrol")
@login_required
def decontrol_export() -> ResponseReturnValue:
    from blueprints.decontrol import build_filters
    try:
        ids = _selected_ids()
        where, params = build_filters(request.args, ids=ids or None)
        filepath, filename = export_decontrol(_operator(), where, params)
        log_action("export", "decontrol_filing", detail=f"{filename}（{_scope_note(where, ids)}）")
        return send_file(filepath, as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f"导出失败: {e}", "danger")
        return redirect(url_for("decontrol.list"))


# =========================================================================
# 在线打印 — 5 类表单
# =========================================================================
@export_bp.route("/print/<string:print_type>/<int:id>")
@login_required
def print_view(print_type, id) -> ResponseReturnValue:
    """渲染打印模板（新标签中打开）"""
    db = get_db()

    # --- 备案人员信息登记表 ---
    if print_type == "info":
        row = db.execute("SELECT * FROM personnel_info WHERE id = ?", (id,)).fetchone()
        if not row:
            flash("记录不存在。", "danger")
            return redirect(url_for("personnel.list"))
        return render_template("export/print.html", title="备案人员信息登记表", row=row, mode="info")

    # --- 登记备案表 ---
    elif print_type == "filing":
        row = db.execute("SELECT * FROM personnel_filing WHERE id = ?", (id,)).fetchone()
        if not row:
            flash("记录不存在。", "danger")
            return redirect(url_for("personnel.list"))
        info_row = db.execute(
            "SELECT * FROM personnel_info WHERE id = ?", (row["personnel_info_id"],)
        ).fetchone() if row["personnel_info_id"] else None
        return render_template("export/print.html", title="因私事出国（境）人员登记备案表", row=row, info=info_row, mode="filing")

    # --- 证照登记表 ---
    elif print_type == "certificate":
        row = db.execute("SELECT * FROM certificates WHERE id = ?", (id,)).fetchone()
        if not row:
            flash("记录不存在。", "danger")
            return redirect(url_for("certificate.list"))
        return render_template("export/print.html", title="因私出国（境）备案人员证照登记表", row=row, mode="certificate")

    # --- 出国明细表 ---
    elif print_type == "travel":
        row = db.execute("SELECT * FROM travel_details WHERE id = ?", (id,)).fetchone()
        if not row:
            flash("记录不存在。", "danger")
            return redirect(url_for("travel.list"))
        return render_template("export/print.html", title="因私出国（境）人员明细表", row=row, mode="travel")

    # --- 撤控备案表 ---
    elif print_type == "decontrol":
        row = db.execute("SELECT * FROM decontrol_filing WHERE id = ?", (id,)).fetchone()
        if not row:
            flash("记录不存在。", "danger")
            return redirect(url_for("decontrol.list"))
        return render_template("export/print.html", title="因私事出国（境）人员撤控备案表", row=row, mode="decontrol")

    flash("不支持的打印类型。", "danger")
    return redirect(url_for("dashboard.index"))


# =========================================================================
# 批量打印
# =========================================================================
@export_bp.route("/print/batch/<string:print_type>")
@login_required
def batch_print(print_type) -> ResponseReturnValue:
    """批量打印 — 支持多选ID"""
    ids_str = request.args.get("ids", "")
    if not ids_str:
        flash("请选择要打印的记录。", "warning")
        return redirect(request.referrer or url_for("dashboard.index"))

    ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
    if not ids:
        flash("未选择有效记录。", "warning")
        return redirect(request.referrer or url_for("dashboard.index"))

    db = get_db()
    table_map = {
        "filing": ("personnel_filing", "因私事出国（境）人员登记备案表"),
        "certificate": ("certificates", "因私出国（境）备案人员证照登记表"),
        "travel": ("travel_details", "因私出国（境）人员明细表"),
        "decontrol": ("decontrol_filing", "因私事出国（境）人员撤控备案表"),
        "info": ("personnel_info", "备案人员信息登记表"),
    }
    if print_type not in table_map:
        flash("不支持的打印类型。", "danger")
        return redirect(url_for("dashboard.index"))

    table, title = table_map[print_type]
    placeholders = ",".join("?" for _ in ids)
    rows = db.execute(
        f"SELECT * FROM {table} WHERE id IN ({placeholders}) ORDER BY id", ids
    ).fetchall()

    return render_template("export/batch_print.html", title=title, rows=rows, mode=print_type, total=len(rows))

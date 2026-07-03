"""操作日志查看蓝图"""
from flask import Blueprint, render_template, request

from auth import login_required
from utils.helpers import paginate

logs_bp = Blueprint("logs", __name__)


@logs_bp.route("/logs/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    action_filter = request.args.get("action", "").strip()
    target_filter = request.args.get("target_type", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    base = "SELECT * FROM operation_logs WHERE 1=1"
    params: list = []

    if action_filter:
        base += " AND action = ?"
        params.append(action_filter)

    if target_filter:
        base += " AND target_type = ?"
        params.append(target_filter)

    if date_from:
        base += " AND date(created_at) >= ?"
        params.append(date_from)

    if date_to:
        base += " AND date(created_at) <= ?"
        params.append(date_to)

    base += " ORDER BY created_at DESC"

    pg = paginate(base, tuple(params), page)

    action_types = [
        {"code": "create", "value": "新建"},
        {"code": "update", "value": "修改"},
        {"code": "delete", "value": "删除"},
        {"code": "export", "value": "导出"},
        {"code": "import", "value": "导入"},
    ]
    target_types = [
        {"code": "personnel_info", "value": "人员信息表"},
        {"code": "personnel_filing", "value": "登记备案表"},
        {"code": "certificates", "value": "证照登记表"},
        {"code": "travel_details", "value": "出国明细表"},
        {"code": "decontrol_filing", "value": "撤控备案表"},
        {"code": "batch", "value": "批量导入"},
    ]

    return render_template(
        "logs/view.html",
        items=pg,
        action_filter=action_filter,
        target_filter=target_filter,
        date_from=date_from,
        date_to=date_to,
        action_types=action_types,
        target_types=target_types,
    )

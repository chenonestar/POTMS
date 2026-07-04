"""操作日志查看蓝图"""
import json

from flask import Blueprint, render_template, request

from auth import login_required
from utils.helpers import paginate

logs_bp = Blueprint("logs", __name__)

# 字段名 → 中文标签（用于变更快照展示）
FIELD_LABELS = {
    "unit": "单位", "department": "部门", "name": "姓名", "gender": "性别",
    "birth_date": "出生日期", "id_number": "身份证号", "work_start_date": "参加工作日期",
    "education": "学历", "degree": "学位", "title": "职称", "rank": "职级",
    "political_status": "政治面貌", "party_join_date": "入党日期", "position": "职务",
    "surname": "中文姓", "given_name": "中文名", "residence": "户口所在地",
    "work_unit": "工作单位", "position_or_title": "职务/职称", "supervisor_unit": "人事主管单位",
    "tag": "标记", "informed": "已告知本人", "status": "状态", "remarks": "备注",
    "passport_no": "护照号", "passport_expiry": "护照有效期", "passport_submit_date": "护照上交日期",
    "hm_pass_no": "港澳通行证号", "hm_pass_expiry": "港澳有效期", "hm_pass_submit_date": "港澳上交日期",
    "tw_pass_no": "台湾通行证号", "tw_pass_expiry": "台湾有效期", "tw_pass_submit_date": "台湾上交日期",
    "destination_passport": "地点、证照", "category": "类别", "travel_dates": "计划出行日期",
    "travel_start": "出行起", "travel_end": "出行止", "approval_date": "批准日期",
    "need_new_passport": "是否做证", "passport_collect_date": "领用日期", "passport_return_date": "归还日期",
    "actual_return_date": "实际回国日期", "trip_status": "行程状态", "cancel_date": "取消日期",
    "submit_unit_name": "报送单位", "submit_unit_type": "报送类别", "submit_contact": "联系人",
    "submit_phone": "联系电话", "batch_no": "入库批号", "reason": "撤控原因", "operator": "操作人",
}


def _compute_changes(snapshot_json):
    """将 snapshot JSON 解析为可展示的变更结构。"""
    if not snapshot_json:
        return None
    try:
        data = json.loads(snapshot_json)
    except (ValueError, TypeError):
        return None
    before = data.get("before") or {}
    after = data.get("after") or {}

    def _label(k):
        return FIELD_LABELS.get(k, k)

    if before and after:
        diffs = []
        for k in after.keys():
            b, a = before.get(k), after.get(k)
            if str(b or "") != str(a or ""):
                diffs.append({"field": _label(k), "before": b, "after": a})
        return {"type": "update", "diffs": diffs} if diffs else None
    if after:
        return {"type": "create",
                "data": [{"field": _label(k), "value": v} for k, v in after.items() if v not in (None, "")]}
    if before:
        return {"type": "delete",
                "data": [{"field": _label(k), "value": v} for k, v in before.items() if v not in (None, "")]}
    return None


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

    # 解析变更快照，附加到每行
    parsed = []
    for r in pg["rows"]:
        d = {k: r[k] for k in r.keys()}
        d["changes"] = _compute_changes(r["snapshot"] if "snapshot" in r.keys() else None)
        parsed.append(d)
    pg["rows"] = parsed

    action_types = [
        {"code": "create", "value": "新建"},
        {"code": "update", "value": "修改"},
        {"code": "delete", "value": "删除"},
        {"code": "cancel", "value": "取消行程"},
        {"code": "restore", "value": "恢复行程"},
        {"code": "export", "value": "导出"},
        {"code": "import", "value": "导入"},
        {"code": "backup", "value": "备份"},
    ]
    target_types = [
        {"code": "personnel_info", "value": "人员信息表"},
        {"code": "personnel_filing", "value": "登记备案表"},
        {"code": "certificates", "value": "证照登记表"},
        {"code": "travel_details", "value": "出国明细表"},
        {"code": "decontrol_filing", "value": "撤控备案表"},
        {"code": "sys_dict", "value": "数据字典"},
        {"code": "sys_submit_unit", "value": "报送单位"},
        {"code": "users", "value": "账户"},
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

"""出国（境）申请蓝图 — 明细表 + 附件上传"""
from __future__ import annotations

import os
import uuid

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, session

from auth import login_required
from database import get_db
from utils.helpers import log_action, paginate, get_dict_options, row_snapshot
from utils.validators import (parse_date_input, validate_date_format, validate_id_number,
                              parse_travel_range, is_cert_overdue, cert_overdue_deadline)
from config import Config

travel_bp = Blueprint("travel", __name__)


# =========================================================================
# 列表
# =========================================================================
def build_filters(args, ids=None):
    """构建出国明细列表 WHERE 子句，供列表与导出复用。含出行日期区间筛选。"""
    where = ""
    params: list = []
    search = args.get("search", "").strip()
    if search:
        where += " AND (name LIKE ? OR destination_passport LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])
    if args.get("category", "").strip():
        where += " AND category = ?"
        params.append(args.get("category").strip())
    if args.get("need_new_passport", "").strip():
        where += " AND need_new_passport = ?"
        params.append(args.get("need_new_passport").strip())
    # 证件流转状态（在库/领用中/逾期未还），与首页仪表盘卡片口径一致
    ps = args.get("passport_status", "").strip()
    if ps == "storage":
        where += " AND (passport_collect_date IS NULL OR passport_collect_date = '')"
    elif ps == "inuse":
        where += " AND passport_collect_date IS NOT NULL AND passport_collect_date != '' " \
                 "AND (passport_return_date IS NULL OR passport_return_date = '')"
    elif ps == "overdue":
        # 逾期口径为「已领用 + 未归还 + 超过工作日时限」，需按行计算，
        # 故先在 Python 中算出逾期记录的 id 集合，再以 id 限定。
        oids = _overdue_ids()
        if oids:
            ph = ",".join("?" for _ in oids)
            where += f" AND id IN ({ph})"
            params.extend(oids)
        else:
            where += " AND 1=0"
    # 出行日期区间：出行起始日落在 [date_from, date_to] 内（与区间有交集）
    date_from = parse_date_input(args.get("date_from", ""))
    date_to = parse_date_input(args.get("date_to", ""))
    if date_from:
        where += " AND travel_end >= ? AND travel_end != ''"
        params.append(date_from)
    if date_to:
        where += " AND travel_start <= ? AND travel_start != ''"
        params.append(date_to)
    if ids:
        ph = ",".join("?" for _ in ids)
        where += f" AND id IN ({ph})"
        params.extend(ids)
    return where, tuple(params)


def _overdue_ids() -> set:
    """全量计算「证件逾期未还」记录的 id 集合（已领用 + 未归还 + 超工作日时限）。"""
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    db = get_db()
    rows = db.execute(
        "SELECT id, passport_collect_date, passport_return_date, actual_return_date, "
        "travel_end, trip_status, cancel_date FROM travel_details "
        "WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' "
        "AND (passport_return_date IS NULL OR passport_return_date = '')"
    ).fetchall()
    return {r["id"] for r in rows if is_cert_overdue(r, today)}


@travel_bp.route("/travel/")
@login_required
def list():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "").strip()
    category_filter = request.args.get("category", "").strip()
    need_passport_filter = request.args.get("need_new_passport", "").strip()
    passport_status = request.args.get("passport_status", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    where, params = build_filters(request.args)
    base = "SELECT * FROM travel_details WHERE 1=1" + where + " ORDER BY created_at DESC"

    pg = paginate(base, params, page)

    # 标记逾期未还（已领用 + 未归还 + 超过工作日时限），并附带应还到期日
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    overdue_ids = set()
    deadlines = {}
    for row in pg["rows"]:
        if is_cert_overdue(row, today):
            overdue_ids.add(row["id"])
            deadlines[row["id"]] = cert_overdue_deadline(row)

    return render_template(
        "travel/list.html",
        items=pg,
        search=search,
        category_filter=category_filter,
        need_passport_filter=need_passport_filter,
        passport_status=passport_status,
        date_from=date_from,
        date_to=date_to,
        overdue_ids=overdue_ids,
        deadlines=deadlines,
        category_opts=get_dict_options("travel_category"),
    )


# =========================================================================
# 附件总览（跨记录汇总 + 缺件检查）
# =========================================================================
# 各路径要求的必备附件类型
_REQUIRED_A = ["个人申请报告", "审批表"]
_REQUIRED_B = ["个人申请报告", "审批表", "同意申办函"]


@travel_bp.route("/travel/attachments")
@login_required
def attachments():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "").strip()
    type_filter = request.args.get("file_type", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    base = (
        "SELECT a.id, a.file_name, a.file_type, a.file_size, a.uploaded_at, "
        "t.id AS travel_id, t.name, t.unit, t.destination_passport, t.travel_dates "
        "FROM attachments a JOIN travel_details t ON a.travel_id = t.id WHERE 1=1"
    )
    params: list = []
    if search:
        base += " AND (t.name LIKE ? OR a.file_name LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])
    if type_filter:
        base += " AND a.file_type = ?"
        params.append(type_filter)
    if date_from:
        base += " AND date(a.uploaded_at) >= ?"
        params.append(date_from)
    if date_to:
        base += " AND date(a.uploaded_at) <= ?"
        params.append(date_to)
    base += " ORDER BY a.uploaded_at DESC"

    pg = paginate(base, tuple(params), page)

    # ——— 缺件检查：逐条申请核对必备附件 ———
    db = get_db()
    travels = db.execute(
        "SELECT id, name, unit, need_new_passport FROM travel_details ORDER BY created_at DESC"
    ).fetchall()
    missing = []
    for tv in travels:
        have = {r["file_type"] for r in db.execute(
            "SELECT DISTINCT file_type FROM attachments WHERE travel_id = ?", (tv["id"],)).fetchall()}
        required = _REQUIRED_B if tv["need_new_passport"] == "是" else _REQUIRED_A
        lack = [r for r in required if r not in have]
        if lack:
            missing.append({"id": tv["id"], "name": tv["name"], "unit": tv["unit"],
                            "path": "B" if tv["need_new_passport"] == "是" else "A", "lack": lack})

    # 各类型数量统计
    type_counts = {r["file_type"]: r["cnt"] for r in db.execute(
        "SELECT file_type, COUNT(*) AS cnt FROM attachments GROUP BY file_type").fetchall()}
    total_att = db.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]

    return render_template(
        "travel/attachments.html",
        items=pg, search=search, type_filter=type_filter,
        date_from=date_from, date_to=date_to,
        missing=missing, type_counts=type_counts, total_att=total_att,
        types=["个人申请报告", "审批表", "同意申办函"],
    )


# =========================================================================
# 新增
# =========================================================================
@travel_bp.route("/travel/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        data = _extract_form(request.form)
        errors = _validate_form(data)
        errors += _missing_attachment_errors(request.files, data["need_new_passport"])
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("travel/form.html", data=data, editing=False)

        db = get_db()
        t_start, t_end = parse_travel_range(data["travel_dates"])
        db.execute(
            "INSERT INTO travel_details (personnel_filing_id, unit, department, name, "
            "position, title, id_number, destination_passport, category, travel_dates, "
            "travel_start, travel_end, approval_date, need_new_passport, passport_no, "
            "passport_collect_date, passport_return_date, actual_return_date, operator) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["personnel_filing_id"], data["unit"], data["department"],
                data["name"], data["position"], data["title"], data["id_number"],
                data["destination_passport"], data["category"], data["travel_dates"],
                t_start, t_end, data["approval_date"], data["need_new_passport"], data["passport_no"],
                data["passport_collect_date"], data["passport_return_date"],
                data["actual_return_date"], data["operator"],
            ),
        )
        db.commit()
        travel_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 处理附件上传
        _save_attachments(travel_id, request.files)

        log_action("create", "travel_details", travel_id, after=row_snapshot("travel_details", travel_id))
        flash("出国（境）明细表已保存。", "success")
        return redirect(url_for("travel.list"))

    # 支持从人员列表跳转
    filing_id = request.args.get("filing_id", type=int)
    prefill = {}
    if filing_id:
        db = get_db()
        filing = db.execute(
            "SELECT pf.*, COALESCE((SELECT unit FROM personnel_info WHERE id = pf.personnel_info_id), pf.work_unit) AS info_unit, "
            "COALESCE((SELECT department FROM personnel_info WHERE id = pf.personnel_info_id), '') AS info_dept "
            "FROM personnel_filing pf WHERE pf.id = ?",
            (filing_id,),
        ).fetchone()
        if filing:
            prefill = {
                "personnel_filing_id": filing_id,
                "unit": filing["info_unit"] or filing["work_unit"],
                "department": filing["info_dept"],
                "name": f"{filing['surname']}{filing['given_name']}",
                "position": filing["position_or_title"],
                "id_number": filing["id_number"],
            }

    return render_template("travel/form.html", data=prefill, editing=False)


# =========================================================================
# 编辑
# =========================================================================
@travel_bp.route("/travel/<int:travel_id>/edit", methods=["GET", "POST"])
@login_required
def edit(travel_id):
    db = get_db()
    row = db.execute("SELECT * FROM travel_details WHERE id = ?", (travel_id,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("travel.list"))

    if request.method == "POST":
        data = _extract_form(request.form)
        errors = _validate_form(data)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("travel/form.html", data=data, editing=True, travel_id=travel_id)

        before = row_snapshot("travel_details", travel_id)
        t_start, t_end = parse_travel_range(data["travel_dates"])
        db.execute(
            "UPDATE travel_details SET personnel_filing_id=?, unit=?, department=?, "
            "name=?, position=?, title=?, id_number=?, destination_passport=?, "
            "category=?, travel_dates=?, travel_start=?, travel_end=?, approval_date=?, need_new_passport=?, "
            "passport_no=?, passport_collect_date=?, passport_return_date=?, actual_return_date=?, "
            "operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                data["personnel_filing_id"], data["unit"], data["department"],
                data["name"], data["position"], data["title"], data["id_number"],
                data["destination_passport"], data["category"], data["travel_dates"],
                t_start, t_end, data["approval_date"], data["need_new_passport"], data["passport_no"],
                data["passport_collect_date"], data["passport_return_date"],
                data["actual_return_date"], data["operator"], travel_id,
            ),
        )
        db.commit()

        # 补充上传附件
        _save_attachments(travel_id, request.files)

        log_action("update", "travel_details", travel_id,
                   before=before, after=row_snapshot("travel_details", travel_id))
        flash("明细表已更新。", "success")
        return redirect(url_for("travel.list"))

    attachments = db.execute(
        "SELECT * FROM attachments WHERE travel_id = ? ORDER BY uploaded_at", (travel_id,)
    ).fetchall()

    return render_template(
        "travel/form.html",
        data=dict(row),
        editing=True,
        travel_id=travel_id,
        attachments=attachments,
    )


# =========================================================================
# 查看
# =========================================================================
@travel_bp.route("/travel/<int:travel_id>")
@login_required
def view(travel_id):
    db = get_db()
    row = db.execute("SELECT * FROM travel_details WHERE id = ?", (travel_id,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("travel.list"))
    attachments = db.execute(
        "SELECT * FROM attachments WHERE travel_id = ? ORDER BY uploaded_at", (travel_id,)
    ).fetchall()
    return render_template("travel/view.html", travel=row, attachments=attachments)


# =========================================================================
# 删除
# =========================================================================
@travel_bp.route("/travel/<int:travel_id>/delete", methods=["POST"])
@login_required
def delete(travel_id):
    db = get_db()
    # 清理附件文件
    atts = db.execute(
        "SELECT file_path FROM attachments WHERE travel_id = ?", (travel_id,)
    ).fetchall()
    for att in atts:
        full_path = os.path.join(Config.UPLOAD_FOLDER, att["file_path"])
        if os.path.exists(full_path):
            os.remove(full_path)
    before = row_snapshot("travel_details", travel_id)
    db.execute("DELETE FROM attachments WHERE travel_id = ?", (travel_id,))
    db.execute("DELETE FROM travel_details WHERE id = ?", (travel_id,))
    db.commit()
    log_action("delete", "travel_details", travel_id, before=before)
    flash("出国申请记录已删除。", "info")
    return redirect(url_for("travel.list"))


# =========================================================================
# 行程取消 / 恢复
# =========================================================================
@travel_bp.route("/travel/<int:travel_id>/cancel", methods=["POST"])
@login_required
def cancel(travel_id):
    """取消行程：记录取消日期。已申领证件须在取消日起 5 个工作日内送回保管。"""
    db = get_db()
    row = db.execute("SELECT * FROM travel_details WHERE id = ?", (travel_id,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("travel.list"))
    if row["trip_status"] == "cancelled":
        flash("该行程已处于取消状态。", "info")
        return redirect(url_for("travel.view", travel_id=travel_id))

    cancel_date = parse_date_input(request.form.get("cancel_date", ""))
    if not cancel_date:
        from datetime import datetime
        cancel_date = datetime.now().strftime("%Y%m%d")
    ok, msg = validate_date_format(cancel_date)
    if not ok:
        flash(f"取消日期: {msg}", "danger")
        return redirect(url_for("travel.view", travel_id=travel_id))

    before = row_snapshot("travel_details", travel_id)
    db.execute(
        "UPDATE travel_details SET trip_status='cancelled', cancel_date=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE id=?", (cancel_date, travel_id))
    db.commit()
    log_action("cancel", "travel_details", travel_id,
               before=before, after=row_snapshot("travel_details", travel_id),
               detail=f"取消行程（{cancel_date}）")
    flash(f"行程已取消（{cancel_date}）。已申领证件请于 5 个工作日内送回保管。", "warning")
    return redirect(url_for("travel.view", travel_id=travel_id))


@travel_bp.route("/travel/<int:travel_id>/restore", methods=["POST"])
@login_required
def restore(travel_id):
    """恢复已取消的行程为正常状态。"""
    db = get_db()
    row = db.execute("SELECT * FROM travel_details WHERE id = ?", (travel_id,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("travel.list"))
    before = row_snapshot("travel_details", travel_id)
    db.execute(
        "UPDATE travel_details SET trip_status='normal', cancel_date=NULL, "
        "updated_at=CURRENT_TIMESTAMP WHERE id=?", (travel_id,))
    db.commit()
    log_action("restore", "travel_details", travel_id,
               before=before, after=row_snapshot("travel_details", travel_id),
               detail="恢复行程为正常")
    flash("行程已恢复为正常状态。", "success")
    return redirect(url_for("travel.view", travel_id=travel_id))


# =========================================================================
# 附件下载 / 删除
# =========================================================================
@travel_bp.route("/travel/attachment/<int:att_id>/download")
@login_required
def attachment_download(att_id):
    db = get_db()
    att = db.execute("SELECT * FROM attachments WHERE id = ?", (att_id,)).fetchone()
    if not att:
        flash("附件不存在。", "danger")
        return redirect(url_for("travel.list"))
    directory = os.path.join(Config.UPLOAD_FOLDER)
    return send_from_directory(directory, att["file_path"], download_name=att["file_name"])


@travel_bp.route("/travel/attachment/<int:att_id>/preview")
@login_required
def attachment_preview(att_id):
    """在浏览器内联预览 PDF 附件"""
    db = get_db()
    att = db.execute("SELECT * FROM attachments WHERE id = ?", (att_id,)).fetchone()
    if not att:
        flash("附件不存在。", "danger")
        return redirect(url_for("travel.list"))
    directory = os.path.join(Config.UPLOAD_FOLDER)
    return send_from_directory(directory, att["file_path"], mimetype="application/pdf", as_attachment=False)


@travel_bp.route("/travel/attachment/<int:att_id>/delete", methods=["POST"])
@login_required
def attachment_delete(att_id):
    db = get_db()
    att = db.execute("SELECT * FROM attachments WHERE id = ?", (att_id,)).fetchone()
    if att:
        full_path = os.path.join(Config.UPLOAD_FOLDER, att["file_path"])
        if os.path.exists(full_path):
            os.remove(full_path)
        travel_id = att["travel_id"]
        db.execute("DELETE FROM attachments WHERE id = ?", (att_id,))
        db.commit()
        flash("附件已删除。", "info")
        return redirect(url_for("travel.edit", travel_id=travel_id))
    flash("附件不存在。", "danger")
    return redirect(url_for("travel.list"))


# =========================================================================
# 辅助
# =========================================================================
def _extract_form(form):
    return {
        "personnel_filing_id": form.get("personnel_filing_id", "").strip(),
        "unit": form.get("unit", "").strip(),
        "department": form.get("department", "").strip(),
        "name": form.get("name", "").strip(),
        "position": form.get("position", "").strip(),
        "title": form.get("title", "").strip(),
        "id_number": form.get("id_number", "").strip().upper(),
        "destination_passport": form.get("destination_passport", "").strip(),
        "category": form.get("category", "").strip(),
        "travel_dates": form.get("travel_dates", "").strip(),
        "approval_date": parse_date_input(form.get("approval_date", "")),
        "need_new_passport": form.get("need_new_passport", "否").strip(),
        "passport_no": form.get("passport_no", "").strip(),
        "passport_collect_date": parse_date_input(form.get("passport_collect_date", "")),
        "passport_return_date": parse_date_input(form.get("passport_return_date", "")),
        "actual_return_date": parse_date_input(form.get("actual_return_date", "")),
        "operator": session.get("username", "admin"),
    }


def _validate_form(data: dict) -> list[str]:
    errors = []
    required = [
        ("personnel_filing_id", "备案人员"), ("unit", "单位"), ("department", "部门"),
        ("name", "姓名"), ("position", "职务"), ("id_number", "身份证号"),
        ("destination_passport", "地点、证照"), ("category", "类别"),
        ("travel_dates", "计划出行日期"), ("need_new_passport", "是否做证"),
    ]
    for field, label in required:
        if not data.get(field):
            errors.append(f"{label} 为必填项。")

    if data.get("id_number"):
        ok, msg = validate_id_number(data["id_number"])
        if not ok:
            errors.append(f"身份证号: {msg}")

    for field, label in [
        ("approval_date", "批准日期"),
        ("passport_collect_date", "证件领用日期"),
        ("passport_return_date", "证件归还日期"),
        ("actual_return_date", "实际回国日期"),
    ]:
        val = data.get(field)
        if val:
            ok, msg = validate_date_format(val)
            if not ok:
                errors.append(f"{label}: {msg}")

    # 路径A（已有证件，不做证）时，证件领用日期为必填
    if data.get("need_new_passport") == "否" and not data.get("passport_collect_date"):
        errors.append("路径A（已有证件）时，证件领用日期为必填。")

    return errors


def _missing_attachment_errors(files, need_new_passport: str) -> list:
    """附件必填校验：路径A须含《个人申请报告》《审批表》；路径B（需做证）另须《同意申办函》。"""
    errors = []

    def _has(field):
        for f in files.getlist(field):
            if f and f.filename:
                return True
        return False

    if not _has("att_application"):
        errors.append("附件《个人申请报告》为必传项（PDF）。")
    if not _has("att_approval"):
        errors.append("附件《审批表》为必传项（PDF）。")
    if need_new_passport == "是" and not _has("att_consent"):
        errors.append("需新办证件（路径B）时，《同意申办函》为必传项（PDF）。")
    return errors


def _save_attachments(travel_id: int, files):
    """保存分类上传的 PDF 附件"""
    CATEGORIES = {
        "att_application": "个人申请报告",
        "att_approval": "审批表",
        "att_consent": "同意申办函",
    }
    db = get_db()
    for field_name, display_name in CATEGORIES.items():
        if field_name not in files:
            continue
        for f in files.getlist(field_name):
            if not f.filename:
                continue
            ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
            if ext not in Config.ALLOWED_EXTENSIONS:
                flash(f"文件 {f.filename} 格式不支持（仅允许 PDF）。", "warning")
                continue
            saved_name = f"{uuid.uuid4().hex}.{ext}"
            save_path = os.path.join(Config.UPLOAD_FOLDER, saved_name)
            f.save(save_path)
            db.execute(
                "INSERT INTO attachments (travel_id, file_name, file_path, file_type, file_size) "
                "VALUES (?, ?, ?, ?, ?)",
                (travel_id, f.filename, saved_name, display_name, os.path.getsize(save_path)),
            )
    db.commit()


_CATEGORY_LABELS = {
    "个人申请报告": "个人申请报告",
    "审批表": "审批表",
    "同意申办函": "同意申办函",
    "attachment": "其他附件",
}

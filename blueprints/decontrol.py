"""撤控备案蓝图"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from auth import login_required
from database import get_db
from utils.helpers import log_action, paginate, normalize_residence, get_dict_options, row_snapshot
from utils.validators import validate_id_number, validate_birth_date_match, validate_date_format, parse_date_input

decontrol_bp = Blueprint("decontrol", __name__)


def build_filters(args, ids=None):
    """构建撤控列表 WHERE 子句，供列表与导出复用。"""
    where = ""
    params: list = []
    search = args.get("search", "").strip()
    if search:
        where += " AND (surname||given_name LIKE ? OR id_number LIKE ? OR reason LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    if args.get("submit_unit_type", "").strip():
        where += " AND submit_unit_type = ?"
        params.append(args.get("submit_unit_type").strip())
    if ids:
        ph = ",".join("?" for _ in ids)
        where += f" AND id IN ({ph})"
        params.extend(ids)
    return where, tuple(params)


@decontrol_bp.route("/decontrol/")
@login_required
def list():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "").strip()
    unit_type_filter = request.args.get("submit_unit_type", "").strip()

    where, params = build_filters(request.args)
    base = "SELECT * FROM decontrol_filing WHERE 1=1" + where + " ORDER BY created_at DESC"

    pg = paginate(base, params, page)
    return render_template(
        "decontrol/list.html",
        items=pg,
        search=search,
        unit_type_filter=unit_type_filter,
        unit_type_opts=get_dict_options("submit_unit_type"),
    )


@decontrol_bp.route("/decontrol/new/<int:filing_id>", methods=["GET", "POST"])
@login_required
def new(filing_id):
    db = get_db()
    filing = db.execute(
        "SELECT * FROM personnel_filing WHERE id = ?", (filing_id,)
    ).fetchone()
    if not filing:
        flash("备案人员不存在。", "danger")
        return redirect(url_for("decontrol.list"))

    if filing["status"] == "decontrolled":
        flash("该人员已被撤控。", "warning")
        return redirect(url_for("personnel.view", filing_id=filing_id))

    if request.method == "POST":
        data = _extract_form(request.form)
        errors = _validate_form(data)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "decontrol/form.html", data=data, filing=filing, filing_id=filing_id,
            )

        db.execute(
            "INSERT INTO decontrol_filing (personnel_filing_id, surname, given_name, "
            "gender, birth_date, id_number, residence, political_status, work_unit, "
            "supervisor_unit, submit_unit_name, submit_unit_type, submit_contact, "
            "submit_phone, batch_no, reason, decontrol_date, cert_handover_date, operator) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                filing_id, data["surname"], data["given_name"], data["gender"],
                data["birth_date"], data["id_number"], data["residence"],
                data["political_status"], data["work_unit"], data["supervisor_unit"],
                data["submit_unit_name"], data["submit_unit_type"],
                data["submit_contact"], data["submit_phone"], data["batch_no"],
                data["reason"], data["decontrol_date"], data["cert_handover_date"], data["operator"],
            ),
        )
        # 将原备案标记为已撤控
        db.execute(
            "UPDATE personnel_filing SET status = 'decontrolled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (filing_id,),
        )
        db.commit()
        dec_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        log_action("create", "decontrol_filing", dec_id, after=row_snapshot("decontrol_filing", dec_id))
        flash("撤控备案已提交。该人员备案状态已标记为'已撤控'。", "success")
        return redirect(url_for("personnel.list"))

    # 预填备案数据（撤控日期默认今天）
    prefill = {
        "surname": filing["surname"],
        "given_name": filing["given_name"],
        "gender": filing["gender"],
        "birth_date": filing["birth_date"],
        "id_number": filing["id_number"],
        "residence": filing["residence"],
        "political_status": filing["political_status"],
        "work_unit": filing["work_unit"],
        "supervisor_unit": filing["supervisor_unit"],
        "decontrol_date": datetime.now().strftime("%Y%m%d"),
    }
    return render_template(
        "decontrol/form.html", data=prefill, filing=filing, filing_id=filing_id,
    )


@decontrol_bp.route("/decontrol/<int:dec_id>")
@login_required
def view(dec_id):
    db = get_db()
    row = db.execute("SELECT * FROM decontrol_filing WHERE id = ?", (dec_id,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("decontrol.list"))
    return render_template("decontrol/view.html", dec=row)


def _extract_form(form):
    return {
        "surname": form.get("surname", "").strip(),
        "given_name": form.get("given_name", "").strip(),
        "gender": form.get("gender", "").strip(),
        "birth_date": parse_date_input(form.get("birth_date", "")),
        "id_number": form.get("id_number", "").strip().upper(),
        "residence": normalize_residence(form.get("residence", "")),
        "political_status": form.get("political_status", "").strip(),
        "work_unit": form.get("work_unit", "").strip(),
        "supervisor_unit": form.get("supervisor_unit", "").strip(),
        "submit_unit_name": form.get("submit_unit_name", "").strip(),
        "submit_unit_type": form.get("submit_unit_type", "").strip(),
        "submit_contact": form.get("submit_contact", "").strip(),
        "submit_phone": form.get("submit_phone", "").strip(),
        "batch_no": form.get("batch_no", "").strip(),
        "reason": form.get("reason", "").strip(),
        "decontrol_date": parse_date_input(form.get("decontrol_date", "")) or datetime.now().strftime("%Y%m%d"),
        "cert_handover_date": parse_date_input(form.get("cert_handover_date", "")),
        "operator": session.get("username", "admin"),
    }


def _validate_form(data: dict) -> list[str]:
    errors = []
    required = [
        ("surname", "中文姓"), ("given_name", "中文名"), ("gender", "性别"),
        ("birth_date", "出生日期"), ("id_number", "身份证号"),
        ("residence", "户口所在地"), ("political_status", "政治面貌"),
        ("work_unit", "工作单位"), ("supervisor_unit", "人事主管单位"),
        ("submit_unit_name", "报送单位名称"), ("submit_unit_type", "报送单位类别"),
        ("submit_contact", "报送单位联系人"), ("submit_phone", "报送单位联系电话"),
        ("batch_no", "入库批号"), ("reason", "撤控原因"),
    ]
    for field, label in required:
        if not data.get(field):
            errors.append(f"{label} 为必填项。")

    if data.get("birth_date"):
        ok, msg = validate_date_format(data["birth_date"])
        if not ok:
            errors.append(f"出生日期: {msg}")

    if data.get("id_number"):
        ok, msg = validate_id_number(data["id_number"])
        if not ok:
            errors.append(f"身份证号: {msg}")

    if data.get("cert_handover_date"):
        ok, msg = validate_date_format(data["cert_handover_date"])
        if not ok:
            errors.append(f"证件移交日期: {msg}")

    if data.get("decontrol_date"):
        ok, msg = validate_date_format(data["decontrol_date"])
        if not ok:
            errors.append(f"撤控日期: {msg}")

    return errors

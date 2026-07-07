"""证照登记蓝图 — 护照 / 港澳通行证 / 台湾通行证"""
from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db
from utils.helpers import log_action, list_all, row_snapshot
from utils.validators import parse_date_input, check_required, check_dates

certificate_bp = Blueprint("certificate", __name__)


def build_filters(args, ids=None):
    """构建证照列表 WHERE 子句，供列表与导出复用。"""
    where = ""
    params: list = []
    search = args.get("search", "").strip()
    if search:
        where += " AND (name LIKE ? OR unit LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])
    has_passport = args.get("has_passport", "").strip()
    if has_passport == "1":
        where += " AND passport_no IS NOT NULL AND passport_no != ''"
    elif has_passport == "0":
        where += " AND (passport_no IS NULL OR passport_no = '')"
    has_hm = args.get("has_hm", "").strip()
    if has_hm == "1":
        where += " AND hm_pass_no IS NOT NULL AND hm_pass_no != ''"
    elif has_hm == "0":
        where += " AND (hm_pass_no IS NULL OR hm_pass_no = '')"
    has_tw = args.get("has_tw", "").strip()
    if has_tw == "1":
        where += " AND tw_pass_no IS NOT NULL AND tw_pass_no != ''"
    elif has_tw == "0":
        where += " AND (tw_pass_no IS NULL OR tw_pass_no = '')"
    if ids:
        ph = ",".join("?" for _ in ids)
        where += f" AND id IN ({ph})"
        params.extend(ids)
    return where, tuple(params)


@certificate_bp.route("/certificate/")
@login_required
def list() -> ResponseReturnValue:
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "").strip()
    has_passport = request.args.get("has_passport", "").strip()
    has_hm = request.args.get("has_hm", "").strip()
    has_tw = request.args.get("has_tw", "").strip()

    where, params = build_filters(request.args)
    base = "SELECT * FROM certificates WHERE 1=1" + where + " ORDER BY updated_at DESC"

    pg = list_all(base, params)  # 全量下发，前端按视口窗口化分页

    # 标记即将到期的证照
    from datetime import datetime, timedelta
    from config import Config
    today = datetime.now().strftime("%Y%m%d")
    warn_date = (datetime.now() + timedelta(days=Config.CERT_EXPIRY_WARN_DAYS)).strftime("%Y%m%d")

    expired = []  # (row, passport_type_label)
    for row in pg["rows"]:
        for key, label in [
            ("passport_expiry", "普通护照"),
            ("hm_pass_expiry", "往来港澳通行证"),
            ("tw_pass_expiry", "大陆居民往来台湾通行证"),
        ]:
            expiry = row[key]
            if expiry and today <= expiry <= warn_date:
                expired.append((row["id"], label, expiry))

    return render_template(
        "certificate/list.html",
        items=pg,
        search=search,
        has_passport=has_passport, has_hm=has_hm, has_tw=has_tw,
        expired_set={(e[0], e[1]) for e in expired},
        expired_map={e[0]: e for e in expired},
    )


@certificate_bp.route("/certificate/new", methods=["GET", "POST"])
@login_required
def new() -> ResponseReturnValue:
    if request.method == "POST":
        data = _extract_form(request.form)
        errors = _validate_form(data)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("certificate/form.html", data=data, editing=False)

        db = get_db()
        db.execute(
            "INSERT INTO certificates (personnel_filing_id, unit, department, name, "
            "passport_no, passport_expiry, passport_submit_date, "
            "hm_pass_no, hm_pass_expiry, hm_pass_submit_date, "
            "tw_pass_no, tw_pass_expiry, tw_pass_submit_date, operator) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["personnel_filing_id"], data["unit"], data["department"],
                data["name"], data["passport_no"], data["passport_expiry"],
                data["passport_submit_date"], data["hm_pass_no"],
                data["hm_pass_expiry"], data["hm_pass_submit_date"],
                data["tw_pass_no"], data["tw_pass_expiry"],
                data["tw_pass_submit_date"], data["operator"],
            ),
        )
        db.commit()
        cert_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        log_action("create", "certificate", cert_id, after=row_snapshot("certificates", cert_id))
        flash("证照登记已保存。", "success")
        return redirect(url_for("certificate.list"))

    # 支持从人员列表跳转：预填人员信息
    filing_id = request.args.get("filing_id", type=int)
    prefill = {}
    if filing_id:
        db = get_db()
        filing = db.execute(
            "SELECT id, unit AS work_unit, name, "
            "COALESCE((SELECT unit FROM personnel_info WHERE id = personnel_filing.personnel_info_id), work_unit) AS unit_val "
            "FROM personnel_filing WHERE id = ?",
            (filing_id,),
        ).fetchone()
        if filing:
            prefill = {
                "personnel_filing_id": filing_id,
                "unit": filing["unit_val"] or filing["work_unit"],
                "department": "",
                "name": filing["name"],
            }

    return render_template("certificate/form.html", data=prefill, editing=False)


@certificate_bp.route("/certificate/<int:cert_id>/edit", methods=["GET", "POST"])
@login_required
def edit(cert_id) -> ResponseReturnValue:
    db = get_db()
    row = db.execute("SELECT * FROM certificates WHERE id = ?", (cert_id,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("certificate.list"))

    if request.method == "POST":
        data = _extract_form(request.form)
        errors = _validate_form(data)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("certificate/form.html", data=data, editing=True, cert_id=cert_id)

        before = row_snapshot("certificates", cert_id)
        db.execute(
            "UPDATE certificates SET personnel_filing_id=?, unit=?, department=?, name=?, "
            "passport_no=?, passport_expiry=?, passport_submit_date=?, "
            "hm_pass_no=?, hm_pass_expiry=?, hm_pass_submit_date=?, "
            "tw_pass_no=?, tw_pass_expiry=?, tw_pass_submit_date=?, "
            "operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                data["personnel_filing_id"], data["unit"], data["department"],
                data["name"], data["passport_no"], data["passport_expiry"],
                data["passport_submit_date"], data["hm_pass_no"],
                data["hm_pass_expiry"], data["hm_pass_submit_date"],
                data["tw_pass_no"], data["tw_pass_expiry"],
                data["tw_pass_submit_date"], data["operator"], cert_id,
            ),
        )
        db.commit()
        log_action("update", "certificate", cert_id,
                   before=before, after=row_snapshot("certificates", cert_id))
        flash("证照信息已更新。", "success")
        return redirect(url_for("certificate.list"))

    return render_template("certificate/form.html", data=dict(row), editing=True, cert_id=cert_id)


@certificate_bp.route("/certificate/<int:cert_id>/delete", methods=["POST"])
@login_required
def delete(cert_id) -> ResponseReturnValue:
    db = get_db()
    before = row_snapshot("certificates", cert_id)
    db.execute("DELETE FROM certificates WHERE id = ?", (cert_id,))
    db.commit()
    log_action("delete", "certificate", cert_id, before=before)
    flash("证照记录已删除。", "info")
    return redirect(url_for("certificate.list"))


# ---------------------------------------------------------------------------
def _extract_form(form):
    return {
        "personnel_filing_id": form.get("personnel_filing_id", "").strip(),
        "unit": form.get("unit", "").strip(),
        "department": form.get("department", "").strip(),
        "name": form.get("name", "").strip(),
        "passport_no": form.get("passport_no", "").strip(),
        "passport_expiry": parse_date_input(form.get("passport_expiry", "")),
        "passport_submit_date": parse_date_input(form.get("passport_submit_date", "")),
        "hm_pass_no": form.get("hm_pass_no", "").strip(),
        "hm_pass_expiry": parse_date_input(form.get("hm_pass_expiry", "")),
        "hm_pass_submit_date": parse_date_input(form.get("hm_pass_submit_date", "")),
        "tw_pass_no": form.get("tw_pass_no", "").strip(),
        "tw_pass_expiry": parse_date_input(form.get("tw_pass_expiry", "")),
        "tw_pass_submit_date": parse_date_input(form.get("tw_pass_submit_date", "")),
        "operator": session.get("username", "admin"),
    }


def _validate_form(data: dict) -> list[str]:
    errors = []
    errors += check_required(data, [
        ("personnel_filing_id", "备案人员"), ("unit", "单位"),
        ("department", "部门"), ("name", "姓名"),
    ])
    errors += check_dates(data, [
        ("passport_expiry", "护照有效日期"), ("passport_submit_date", "护照上交日期"),
        ("hm_pass_expiry", "港澳通行证有效日期"), ("hm_pass_submit_date", "港澳通行证上交日期"),
        ("tw_pass_expiry", "台湾通行证有效日期"), ("tw_pass_submit_date", "台湾通行证上交日期"),
    ])

    # 填写证件号时，有效日期与上交日期均为必填
    for no_field, exp_field, sub_field, label in [
        ("passport_no", "passport_expiry", "passport_submit_date", "护照"),
        ("hm_pass_no", "hm_pass_expiry", "hm_pass_submit_date", "港澳通行证"),
        ("tw_pass_no", "tw_pass_expiry", "tw_pass_submit_date", "台湾通行证"),
    ]:
        if data.get(no_field):
            if not data.get(exp_field):
                errors.append(f"填写{label}证件号时，有效日期为必填。")
            if not data.get(sub_field):
                errors.append(f"填写{label}证件号时，上交日期为必填。")

    return errors

"""证照登记蓝图 — 护照 / 港澳通行证 / 台湾通行证"""
from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, flash

from auth import login_required
from database import get_db
from utils.helpers import log_action, paginate
from utils.validators import parse_date_input, validate_date_format

certificate_bp = Blueprint("certificate", __name__)


@certificate_bp.route("/certificate/")
@login_required
def list():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "").strip()
    has_passport = request.args.get("has_passport", "").strip()
    has_hm = request.args.get("has_hm", "").strip()
    has_tw = request.args.get("has_tw", "").strip()

    base = "SELECT * FROM certificates WHERE 1=1"
    params: list = []
    if search:
        base += " AND (name LIKE ? OR unit LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])
    if has_passport == "1":
        base += " AND passport_no IS NOT NULL AND passport_no != ''"
    elif has_passport == "0":
        base += " AND (passport_no IS NULL OR passport_no = '')"
    if has_hm == "1":
        base += " AND hm_pass_no IS NOT NULL AND hm_pass_no != ''"
    elif has_hm == "0":
        base += " AND (hm_pass_no IS NULL OR hm_pass_no = '')"
    if has_tw == "1":
        base += " AND tw_pass_no IS NOT NULL AND tw_pass_no != ''"
    elif has_tw == "0":
        base += " AND (tw_pass_no IS NULL OR tw_pass_no = '')"
    base += " ORDER BY updated_at DESC"

    pg = paginate(base, tuple(params), page)

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
def new():
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
        log_action("create", "certificate", cert_id)
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
def edit(cert_id):
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
        log_action("update", "certificate", cert_id)
        flash("证照信息已更新。", "success")
        return redirect(url_for("certificate.list"))

    return render_template("certificate/form.html", data=dict(row), editing=True, cert_id=cert_id)


@certificate_bp.route("/certificate/<int:cert_id>/delete", methods=["POST"])
@login_required
def delete(cert_id):
    db = get_db()
    db.execute("DELETE FROM certificates WHERE id = ?", (cert_id,))
    db.commit()
    log_action("delete", "certificate", cert_id)
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
        "operator": form.get("operator", "").strip(),
    }


def _validate_form(data: dict) -> list[str]:
    errors = []
    required = [
        ("personnel_filing_id", "备案人员"), ("unit", "单位"),
        ("department", "部门"), ("name", "姓名"), ("operator", "操作人"),
    ]
    for field, label in required:
        if not data.get(field):
            errors.append(f"{label} 为必填项。")

    # 日期格式校验
    for field, label in [
        ("passport_expiry", "护照有效日期"), ("passport_submit_date", "护照上交日期"),
        ("hm_pass_expiry", "港澳通行证有效日期"), ("hm_pass_submit_date", "港澳通行证上交日期"),
        ("tw_pass_expiry", "台湾通行证有效日期"), ("tw_pass_submit_date", "台湾通行证上交日期"),
    ]:
        val = data.get(field)
        if val:
            ok, msg = validate_date_format(val)
            if not ok:
                errors.append(f"{label}: {msg}")

    # 证件号与有效日期至少有一个配套
    if data.get("passport_no") and not data.get("passport_expiry"):
        errors.append("填写护照证件号时，有效日期为必填。")
    if data.get("hm_pass_no") and not data.get("hm_pass_expiry"):
        errors.append("填写港澳通行证号时，有效日期为必填。")
    if data.get("tw_pass_no") and not data.get("tw_pass_expiry"):
        errors.append("填写台湾通行证号时，有效日期为必填。")

    return errors

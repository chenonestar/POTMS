"""首页仪表盘 — 增强版（维度分类 + 可点击）"""
from datetime import datetime, timedelta

from flask import Blueprint, render_template

from auth import login_required
from database import get_db

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    db = get_db()
    today = datetime.now().strftime("%Y%m%d")
    warn_date = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")

    # 基础统计
    total_active = db.execute("SELECT COUNT(*) FROM personnel_filing WHERE status = 'active'").fetchone()[0]
    total_decontrolled = db.execute("SELECT COUNT(*) FROM personnel_filing WHERE status = 'decontrolled'").fetchone()[0]
    total_certificates = db.execute("SELECT COUNT(*) FROM certificates").fetchone()[0]
    total_travel = db.execute("SELECT COUNT(*) FROM travel_details").fetchone()[0]

    # ——— 按单位维度 ———
    by_unit = db.execute(
        "SELECT work_unit AS label, COUNT(*) AS cnt FROM personnel_filing "
        "WHERE status = 'active' GROUP BY work_unit ORDER BY cnt DESC LIMIT 8"
    ).fetchall()

    # ——— 按政治面貌维度 ———
    by_political = db.execute(
        "SELECT political_status AS label, COUNT(*) AS cnt FROM personnel_filing "
        "WHERE status = 'active' GROUP BY political_status ORDER BY cnt DESC"
    ).fetchall()

    # ——— 按职级维度（personnel_info) ———
    by_rank = db.execute(
        "SELECT pi.rank AS label, COUNT(*) AS cnt FROM personnel_filing pf "
        "JOIN personnel_info pi ON pf.personnel_info_id = pi.id "
        "WHERE pf.status = 'active' GROUP BY pi.rank ORDER BY cnt DESC"
    ).fetchall()

    # ——— 证照状态分类 ———
    cert_in_storage = db.execute(
        "SELECT COUNT(*) FROM travel_details WHERE passport_collect_date IS NULL OR passport_collect_date = ''"
    ).fetchone()[0]
    cert_in_use = db.execute(
        "SELECT COUNT(*) FROM travel_details WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' "
        "AND (passport_return_date IS NULL OR passport_return_date = '')"
    ).fetchone()[0]
    cert_overdue = db.execute(
        "SELECT COUNT(*) FROM travel_details WHERE passport_return_date IS NOT NULL AND passport_return_date != '' "
        "AND passport_return_date < ?", (today,)
    ).fetchone()[0]

    # ——— 证照到期预警 ———
    cert_expiry_warnings = db.execute(
        "SELECT name, passport_expiry, hm_pass_expiry, tw_pass_expiry FROM certificates"
    ).fetchall()
    expiring = []
    for row in cert_expiry_warnings:
        for key, label in [
            ("passport_expiry", "普通护照"),
            ("hm_pass_expiry", "往来港澳通行证"),
            ("tw_pass_expiry", "大陆居民往来台湾通行证"),
        ]:
            expiry = row[key]
            if expiry and today <= expiry <= warn_date:
                expiring.append({"name": row["name"], "type": label, "expiry": expiry})

    # ——— 逾期未还 ———
    overdue = db.execute(
        "SELECT name, passport_return_date FROM travel_details "
        "WHERE passport_return_date < ? AND passport_collect_date IS NOT NULL AND passport_collect_date != '' "
        "ORDER BY passport_return_date",
        (today,),
    ).fetchall()

    # ——— 近期出行（按出行日期排序） ———
    recent_travel = db.execute(
        "SELECT name, destination_passport, travel_dates, created_at "
        "FROM travel_details ORDER BY travel_dates DESC LIMIT 5"
    ).fetchall()

    return render_template(
        "dashboard.html",
        total_active=total_active,
        total_decontrolled=total_decontrolled,
        total_certificates=total_certificates,
        total_travel=total_travel,
        by_unit=by_unit,
        by_political=by_political,
        by_rank=by_rank,
        cert_in_storage=cert_in_storage,
        cert_in_use=cert_in_use,
        cert_overdue=cert_overdue,
        expiring=expiring,
        overdue=[dict(r) for r in overdue],
        recent_travel=recent_travel,
    )

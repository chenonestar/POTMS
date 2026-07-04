"""首页仪表盘 — 增强版（维度分类 + 可点击）"""
from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash

from auth import login_required
from database import get_db
from utils.backup import run_daily_backup, latest_backup
from utils.helpers import log_action
from utils.validators import is_cert_overdue, cert_overdue_deadline

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/backup/now", methods=["POST"])
@login_required
def backup_now():
    """手动立即备份数据库"""
    try:
        result = run_daily_backup(force=True)
        log_action("backup", "database", detail=f"手动备份 {result['date']}，清理旧备份 {result['pruned']} 个")
        flash(f"数据库已备份（{result['date']}）。", "success")
    except Exception as e:
        flash(f"备份失败：{e}", "danger")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/")
@login_required
def index():
    # 长时间运行时，登录首页也触发每日备份检查（当天已备份则跳过）
    try:
        run_daily_backup()
    except Exception:
        pass
    _, backup_date = latest_backup()

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
    # 已领用未归还的证件（正常/取消行程均含在内），用于「使用中」与「逾期」判定
    in_use_rows = db.execute(
        "SELECT id, name, passport_collect_date, passport_return_date, "
        "actual_return_date, travel_end, trip_status, cancel_date "
        "FROM travel_details "
        "WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' "
        "AND (passport_return_date IS NULL OR passport_return_date = '')"
    ).fetchall()
    cert_in_use = len(in_use_rows)
    # 逾期未还：已领用 + 未归还 + 超过归还工作日时限（正常 10 / 取消 5）
    overdue = []
    for r in in_use_rows:
        if is_cert_overdue(r, today):
            overdue.append({
                "name": r["name"],
                "deadline": cert_overdue_deadline(r),
                "trip_status": r["trip_status"] or "normal",
            })
    overdue.sort(key=lambda x: x["deadline"])
    cert_overdue = len(overdue)

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

    # ——— 近期出行（按出行日期排序） ———
    recent_travel = db.execute(
        "SELECT name, destination_passport, travel_dates, created_at "
        "FROM travel_details "
        "ORDER BY CASE WHEN travel_start IS NULL OR travel_start = '' THEN 1 ELSE 0 END, "
        "travel_start DESC, created_at DESC LIMIT 5"
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
        overdue=overdue,
        recent_travel=recent_travel,
        backup_date=backup_date,
    )

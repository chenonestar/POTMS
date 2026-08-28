"""首页仪表盘 — 统计概览 + 待办告警"""
from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash
from flask.typing import ResponseReturnValue

from auth import login_required
from config import Config
from database import get_db
from utils.backup import run_daily_backup, latest_backup
from utils.helpers import log_action
from utils.validators import is_cert_overdue, is_new_cert_overdue, cert_overdue_deadline

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/backup/now", methods=["POST"])
@login_required
def backup_now() -> ResponseReturnValue:
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
def index() -> ResponseReturnValue:
    # 长时间运行时，登录首页也触发每日备份检查（当天已备份则跳过）
    try:
        run_daily_backup()
    except Exception:
        pass
    _, backup_date = latest_backup()

    db = get_db()
    today = datetime.now().strftime("%Y%m%d")
    # 用配置里的阈值，别在这里另写一个 30：首页与证照台账报的必须是同一批证，
    # 两处各拿一个天数，调了配置就只有一处跟着变，用的人无从判断哪个才算数。
    warn_date = (datetime.now() + timedelta(days=Config.CERT_EXPIRY_WARN_DAYS)).strftime("%Y%m%d")

    # 基础统计
    total_active = db.execute("SELECT COUNT(*) FROM personnel_filing WHERE status = 'active'").fetchone()[0]
    total_decontrolled = db.execute("SELECT COUNT(*) FROM personnel_filing WHERE status = 'decontrolled'").fetchone()[0]
    total_certificates = db.execute("SELECT COUNT(*) FROM certificates").fetchone()[0]
    total_travel = db.execute("SELECT COUNT(*) FROM travel_details").fetchone()[0]

    # 这里刻意没有「按单位 / 按政治面貌 / 按职级」三项分布统计。
    # 原来算了 by_unit / by_political / by_rank 三段并传给模板，而 dashboard.html
    # 从第一版起就没用过它们——每进一次首页白跑三个查询（其中职级那个还带 JOIN）。
    # 500 人、单用户的规模上，分布统计更像报表需求，放首页每天看意义不大；
    # .NET 与 Java 两版早已按这个口径不查也不显示，此处与它们对齐。

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
        # 已撤控人员不进告警，口径见 blueprints/travel.py 的 _ACTIVE_ONLY
        " AND EXISTS (SELECT 1 FROM personnel_filing pf "
        "             WHERE pf.id = travel_details.personnel_filing_id AND pf.status = 'active')"
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
    # 路径B（做证）没有领用记录，上面那批取数条件（passport_collect_date 非空）
    # 一条都抓不到。它们按「新证是否已进入证照台账」判，口径见
    # blueprints/travel.py:_registered_cert_travel_ids 与 is_new_cert_overdue。
    from blueprints.travel import _registered_cert_travel_ids
    registered = _registered_cert_travel_ids()
    for r in db.execute(
        "SELECT id, name, need_new_passport, actual_return_date, travel_end, "
        "trip_status, cancel_date, passport_collect_date FROM travel_details "
        "WHERE need_new_passport = '是' "
        "  AND (passport_collect_date IS NULL OR passport_collect_date = '')"
        "  AND EXISTS (SELECT 1 FROM personnel_filing pf "
        "              WHERE pf.id = travel_details.personnel_filing_id AND pf.status = 'active')"
    ).fetchall():
        if is_new_cert_overdue({**dict(r), "cert_registered": r["id"] in registered}, today):
            overdue.append({
                "name": r["name"],
                "deadline": cert_overdue_deadline(r),
                "trip_status": r["trip_status"] or "normal",
            })
    overdue.sort(key=lambda x: x["deadline"])
    cert_overdue = len(overdue)

    # ——— 证照到期预警 ———
    # 到期预警同样只看在控人员：人都撤控了，他那本证到不到期与本单位无关，
    # 报出来只会把真正要办的事淹掉。
    cert_expiry_warnings = db.execute(
        "SELECT c.name, c.passport_expiry, c.hm_pass_expiry, c.tw_pass_expiry "
        "FROM certificates c "
        "JOIN personnel_filing pf ON pf.id = c.personnel_filing_id "
        "WHERE pf.status = 'active'"
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
                # 带上还剩几天：光看一个日期还得心算，而这张卡要回答的就是「有多急」
                # 按自然日相减，不能拿 datetime 直接减：那样带上了当前时刻，
                # 5 天后到期会算成「剩 4 天」——早报一天没坏处，但数字对不上日期
                # 就会让人怀疑这张卡到底准不准。
                days = (datetime.strptime(expiry, "%Y%m%d").date() - datetime.now().date()).days
                expiring.append({"name": row["name"], "type": label,
                                 "expiry": expiry, "days": max(days, 0)})
    # 最先到期的排在最前——这张卡是「接下来要办什么」，不是一份名册
    expiring.sort(key=lambda x: x["expiry"])

    # ——— 近期出行（按出行日期排序） ———
    recent_travel = db.execute(
        "SELECT name, destination_passport, travel_dates, created_at "
        "FROM travel_details "
        "ORDER BY CASE WHEN travel_start IS NULL OR travel_start = '' THEN 1 ELSE 0 END, "
        "travel_start DESC, created_at DESC LIMIT 5"
    ).fetchall()

    # ——— 证件领用 ———
    iss_pending = db.execute(
        "SELECT COUNT(*) FROM cert_issuance WHERE status = 'issued'").fetchone()[0]
    iss_this_month = db.execute(
        "SELECT COUNT(*) FROM cert_issuance WHERE status != 'voided' AND issue_date LIKE ?",
        (datetime.now().strftime("%Y%m") + "%",)).fetchone()[0]

    return render_template(
        "dashboard.html",
        iss_pending=iss_pending,
        iss_this_month=iss_this_month,
        total_active=total_active,
        total_decontrolled=total_decontrolled,
        total_certificates=total_certificates,
        total_travel=total_travel,
        cert_in_storage=cert_in_storage,
        cert_in_use=cert_in_use,
        cert_overdue=cert_overdue,
        expiring=expiring,
        warn_days=Config.CERT_EXPIRY_WARN_DAYS,
        overdue=overdue,
        recent_travel=recent_travel,
        backup_date=backup_date,
    )

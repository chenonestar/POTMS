"""首页仪表盘 — 统计概览 + 待办告警"""
from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db
from utils.backup import run_daily_backup, latest_backup
from utils.helpers import log_action
from utils.validators import is_cert_overdue, is_new_cert_overdue

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

    # ——— 证件流转状态（在库 / 领用中 / 逾期未还）———
    cert_in_storage = db.execute(
        "SELECT COUNT(*) FROM travel_details WHERE passport_collect_date IS NULL OR passport_collect_date = ''"
    ).fetchone()[0]
    # 已领用未归还的证件（正常/取消行程均含在内），用于「领用中」与「逾期未还」两个数字。
    # 首页只报数字，名单与应还日期在出国明细列表上（点卡片过去），这里不再取姓名。
    in_use_rows = db.execute(
        "SELECT passport_collect_date, passport_return_date, "
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
    cert_overdue = sum(1 for r in in_use_rows if is_cert_overdue(r, today))
    # 路径B（做证）没有领用记录，上面那批取数条件（passport_collect_date 非空）
    # 一条都抓不到。它们按「新证是否已进入证照台账」判，口径见
    # blueprints/travel.py:_registered_cert_travel_ids 与 is_new_cert_overdue。
    from blueprints.travel import _registered_cert_travel_ids
    registered = _registered_cert_travel_ids()
    for r in db.execute(
        "SELECT id, need_new_passport, actual_return_date, travel_end, "
        "trip_status, cancel_date, passport_collect_date FROM travel_details "
        "WHERE need_new_passport = '是' "
        "  AND (passport_collect_date IS NULL OR passport_collect_date = '')"
        "  AND EXISTS (SELECT 1 FROM personnel_filing pf "
        "              WHERE pf.id = travel_details.personnel_filing_id AND pf.status = 'active')"
    ).fetchall():
        if is_new_cert_overdue({**dict(r), "cert_registered": r["id"] in registered}, today):
            cert_overdue += 1

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
        recent_travel=recent_travel,
        backup_date=backup_date,
    )

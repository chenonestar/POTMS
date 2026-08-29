"""首页仪表盘 — 统计概览 + 待办告警"""
from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db
from utils.backup import run_daily_backup, latest_backup
from utils.helpers import log_action

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

    # 基础统计
    total_active = db.execute("SELECT COUNT(*) FROM personnel_filing WHERE status = 'active'").fetchone()[0]
    total_decontrolled = db.execute("SELECT COUNT(*) FROM personnel_filing WHERE status = 'decontrolled'").fetchone()[0]
    # 证照登记只数**在控人员**的台账行。
    #
    # 原来是 COUNT(*) FROM certificates，不按状态过滤，于是这张卡与下面那行
    # 四档去向（全部只算在控）不可比：撤控一个人，他的台账行仍计进这张卡，
    # 他的证却已退出「在库」。两个数并排摆着，看的人无从知道口径不同。
    # 卡片链接同步带上 ?filing_status=active，数字与点开看到的列表必须一致。
    total_certificates = db.execute(
        "SELECT COUNT(*) FROM certificates c JOIN personnel_filing pf "
        "ON pf.id = c.personnel_filing_id WHERE pf.status = 'active'").fetchone()[0]
    total_travel = db.execute("SELECT COUNT(*) FROM travel_details").fetchone()[0]

    # 这里刻意没有「按单位 / 按政治面貌 / 按职级」三项分布统计。
    # 原来算了 by_unit / by_political / by_rank 三段并传给模板，而 dashboard.html
    # 从第一版起就没用过它们——每进一次首页白跑三个查询（其中职级那个还带 JOIN）。
    # 500 人、单用户的规模上，分布统计更像报表需求，放首页每天看意义不大；
    # .NET 与 Java 两版早已按这个口径不查也不显示，此处与它们对齐。

    # ——— 证件去向（四档，全部按「本」算）———
    #
    # 单位统一成「本」，是为了让「在库」这个数能真的拿去和保管处柜子里的实体证核对。
    # 原来这一行数的是**出国申请条数**，于是：没提过申请的人，他的证在柜子里躺着却
    # 一本都没被数进去；而路径B 那种「证在人手上但没有领用记录」的，又被算进了
    # 「在库」。数字自相矛盾到「逾期」比「领用中」还大。
    #
    # 两个恒等式撑着这四个数，任何一个不成立都说明口径出了问题：
    #   在库 + 借出未还 = 在控人员台账登记的总本数
    #   逾期 ⊆ 借出未还 + 新办未入库
    from blueprints.certificate import stock_split
    from blueprints.travel import new_making_travel_ids, _overdue_ids
    in_stock, lent_out, orphan_nos = stock_split()
    cert_in_stock = len(in_stock)
    cert_lent_out = len(lent_out)
    cert_new_making = len(new_making_travel_ids())
    # 逾期直接用出国明细那一套判据，不在这里另算一遍：首页的数与列表的
    # 「?passport_status=overdue」筛出来的行数必须永远一致。
    cert_overdue = len(_overdue_ids())

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
        cert_in_stock=cert_in_stock,
        cert_lent_out=cert_lent_out,
        cert_new_making=cert_new_making,
        cert_overdue=cert_overdue,
        orphan_nos=orphan_nos,
        recent_travel=recent_travel,
        backup_date=backup_date,
    )

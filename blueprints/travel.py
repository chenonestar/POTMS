"""出国（境）申请蓝图 — 明细表 + 附件上传"""
from __future__ import annotations

import os
from datetime import datetime
import uuid

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, session
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db
from utils.helpers import log_action, list_all, get_dict_options, row_snapshot, operator_name
from utils.validators import (parse_date_input, validate_date_format,
                              parse_travel_range, validate_travel_range, format_travel_range,
                              is_cert_overdue, is_new_cert_overdue, cert_overdue_deadline,
                              check_required, check_dates, check_identity)
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


def _registered_cert_travel_ids() -> set:
    """做证的出行记录中，新证已经进入证照台账的那些 id。

    判据是「明细表上补录的证件号码，出现在该人证照台账的三个号码槽之一」。
    台账登记时上交日期是必填的，所以「在台账里」等价于「已交回收缴」。
    号码没补录、或补录了但台账里没有，都算还没交回。

    JOIN 而不是子查询取一条：一个人可能有多条证照记录（历史遗留），
    只要**任意一条**里出现了这个号码就算数。
    """
    return {r[0] for r in get_db().execute(
        "SELECT DISTINCT t.id FROM travel_details t "
        "JOIN certificates c ON c.personnel_filing_id = t.personnel_filing_id "
        "WHERE t.need_new_passport = '是' "
        "  AND t.passport_no IS NOT NULL AND t.passport_no != '' "
        "  AND t.passport_no IN (c.passport_no, c.hm_pass_no, c.tw_pass_no)"
    ).fetchall()}


# 已撤控人员不再进入证件告警。
#
# 撤控本身就以证件收缴完毕为前提（见 decontrol._unsettled_certs），所以撤控之后
# 本来就不该还有未交回的证。这一条挡的是存量：在加上撤控前置校验之前撤控掉的人，
# 他名下那条逾期会一直挂在首页，而人已经不在管理范围内，谁也处理不掉——那是一笔
# 永远消不掉的死账，比漏报更糟，因为它会让人对整个告警区失去信任。
_ACTIVE_ONLY = (
    " AND EXISTS (SELECT 1 FROM personnel_filing pf "
    "             WHERE pf.id = travel_details.personnel_filing_id AND pf.status = 'active')"
)


def new_making_travel_ids() -> set:
    """路径B：做证出去了、新证还没进证照台账的出行 id（只算在控人员）。

    这批证**存在于现实，却不在证照台账里**——它是本人凭同意申办函自己去公安办的，
    从没进过保管处，号码也还没录进台账。所以盘库时它既不在「在库」里，也不在
    「借出未还」里（那两档说的都是台账上有的证），必须单独成一档，否则
    「在库 + 借出未还 = 台账总本数」这个用来对账的恒等式就会被它打破。

    判据与逾期告警同源（_registered_cert_travel_ids）：号码进了台账即视为已交回入库。
    这里不带时间条件——「还没交回」与「已经逾期」是两回事，逾期是本集合的子集。
    """
    registered = _registered_cert_travel_ids()
    rows = get_db().execute(
        "SELECT id FROM travel_details WHERE need_new_passport = '是' "
        "  AND COALESCE(trip_status, 'normal') != 'cancelled'" + _ACTIVE_ONLY
    ).fetchall()
    return {r[0] for r in rows if r[0] not in registered}


def _overdue_ids() -> set:
    """全量计算「证件逾期未交回」记录的 id 集合。

    两类合并：
    - 路径A：已领用 + 未归还 + 超工作日时限（判据在领用记录上）；
    - 路径B：做证 + 新证尚未进入台账 + 超工作日时限（路径B 没有领用记录，
      用老判据一条都抓不到，见 is_new_cert_overdue 的说明）。

    两类都只算在控人员，理由见 _ACTIVE_ONLY。
    """
    today = datetime.now().strftime("%Y%m%d")
    db = get_db()
    rows = db.execute(
        "SELECT id, passport_collect_date, passport_return_date, actual_return_date, "
        "travel_end, trip_status, cancel_date FROM travel_details "
        "WHERE passport_collect_date IS NOT NULL AND passport_collect_date != '' "
        "AND (passport_return_date IS NULL OR passport_return_date = '')" + _ACTIVE_ONLY
    ).fetchall()
    ids = {r["id"] for r in rows if is_cert_overdue(r, today)}

    registered = _registered_cert_travel_ids()
    new_rows = db.execute(
        "SELECT id, need_new_passport, actual_return_date, travel_end, "
        "trip_status, cancel_date, passport_collect_date FROM travel_details "
        "WHERE need_new_passport = '是'" + _ACTIVE_ONLY
    ).fetchall()
    for r in new_rows:
        # 已经走过领用流程的，归上面那套判据管，避免同一条记录被两边重复判定
        if r["passport_collect_date"]:
            continue
        if is_new_cert_overdue({**dict(r), "cert_registered": r["id"] in registered}, today):
            ids.add(r["id"])
    return ids


@travel_bp.route("/travel/")
@login_required
def list() -> ResponseReturnValue:
    search = request.args.get("search", "").strip()
    category_filter = request.args.get("category", "").strip()
    need_passport_filter = request.args.get("need_new_passport", "").strip()
    passport_status = request.args.get("passport_status", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    where, params = build_filters(request.args)
    # 带上附件条数：删除确认框要讲明「附件也会一并从磁盘删除且不可恢复」，
    # 而讲清楚就得说出有几个（提示文案规约二：挡下/提醒都要给数量明细）。
    base = ("SELECT travel_details.*, "
            "  (SELECT COUNT(*) FROM attachments a WHERE a.travel_id = travel_details.id) AS att_count "
            "FROM travel_details WHERE 1=1" + where + " ORDER BY created_at DESC")

    pg = list_all(base, params)  # 全量下发，前端按视口窗口化分页

    # 标记逾期未交回，并附带应还到期日。判据见 _overdue_ids 的说明。
    #
    # 直接复用 _overdue_ids()，而不是在这里另算一遍：本页的高亮与
    # 「?passport_status=overdue」筛选必须永远一致，两套并行实现迟早会漂移
    # （已撤控人员的排除就差点只加在筛选那一侧）。
    all_overdue = _overdue_ids()
    overdue_ids = {row["id"] for row in pg["rows"] if row["id"] in all_overdue}
    deadlines = {row["id"]: cert_overdue_deadline(row)
                 for row in pg["rows"] if row["id"] in overdue_ids}

    # 「证件领用登记」按钮此前对每一行都亮着，点进去才被挡回来——办不了的事不该
    # 先给个入口。判据与领用模块的准入完全一致（同一个函数），不在这里另写一套。
    from blueprints.issuance import open_issuance_travel_ids
    open_issuance = open_issuance_travel_ids()

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
        open_issuance=open_issuance,
        category_opts=get_dict_options("travel_category"),
    )


# =========================================================================
# 附件总览（跨记录汇总 + 缺件检查）
# =========================================================================
# 各路径要求的必备附件类型
_REQUIRED_A = ["个人申请报告", "审批表"]
_REQUIRED_B = ["个人申请报告", "审批表", "同意申办函"]


def _file_type_order_sql(col: str = "a.file_type") -> str:
    """把附件类型排成办件顺序（个人申请报告 → 审批表 → 同意申办函）的 CASE 表达式。

    这三个中文词按任何排序规则（拼音、笔画、UTF-8 码位）都排不出办件顺序，
    只能显式指定。次序直接取自 _REQUIRED_B——那里已经定义了必备附件的先后，
    再手抄一份迟早两边漂移。表里出现的其它类型统一排在最后。
    """
    whens = " ".join(f"WHEN '{t}' THEN {i}" for i, t in enumerate(_REQUIRED_B, start=1))
    return f"CASE {col} {whens} ELSE {len(_REQUIRED_B) + 1} END"


# 附件总览的排序方式。
#
# batch（默认）：先把同一条出行申请的附件聚成一组，组间与「出国明细」列表同序
# （created_at DESC），组内按办件顺序。此前只按 uploaded_at 排，一旦有过补传，
# 那条申请的附件就会被别人的插在中间，翻起来对不上人。
#
# uploaded：保留原来的按上传时间倒序，找「最近传了什么」时更顺手。
#
# 两种都以 a.id 收尾：uploaded_at 是 CURRENT_TIMESTAMP，只精确到秒，同一次提交
# 上传的多个文件时间戳完全相同，没有兜底列的话它们之间的先后在 SQL 层面是未定义的。
_ATT_SORTS = {
    "batch": f"ORDER BY t.created_at DESC, t.id DESC, {_file_type_order_sql()}, a.id",
    "uploaded": "ORDER BY a.uploaded_at DESC, a.id",
}
_ATT_SORT_DEFAULT = "batch"


@travel_bp.route("/travel/attachments")
@login_required
def attachments() -> ResponseReturnValue:
    search = request.args.get("search", "").strip()
    type_filter = request.args.get("file_type", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    # 白名单取值，不把查询串直接拼进 SQL
    sort = request.args.get("sort", "").strip()
    if sort not in _ATT_SORTS:
        sort = _ATT_SORT_DEFAULT

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
    base += " " + _ATT_SORTS[sort]

    pg = list_all(base, tuple(params))  # 全量下发，前端按视口窗口化分页

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
        date_from=date_from, date_to=date_to, sort=sort,
        missing=missing, type_counts=type_counts, total_att=total_att,
        types=["个人申请报告", "审批表", "同意申办函"],
    )


# =========================================================================
# 新增
# =========================================================================
@travel_bp.route("/travel/new", methods=["GET", "POST"])
@login_required
def new() -> ResponseReturnValue:
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
        data["travel_dates"] = format_travel_range(t_start, t_end) or data["travel_dates"]
        db.execute(
            # 证件领用/归还日期为派生字段，由证件领用模块写入，此处不落值
            "INSERT INTO travel_details (personnel_filing_id, unit, department, name, "
            "position, title, id_number, destination_passport, category, travel_dates, "
            "travel_start, travel_end, approval_date, need_new_passport, passport_no, "
            "actual_return_date, operator) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["personnel_filing_id"], data["unit"], data["department"],
                data["name"], data["position"], data["title"], data["id_number"],
                data["destination_passport"], data["category"], data["travel_dates"],
                t_start, t_end, data["approval_date"], data["need_new_passport"], data["passport_no"],
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
def edit(travel_id) -> ResponseReturnValue:
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
            from blueprints.issuance import travel_has_issuance
            return render_template("travel/form.html", data=data, editing=True,
                                   travel_id=travel_id,
                                   cert_no_derived=travel_has_issuance(travel_id),
                                   applicant_locked=travel_has_issuance(travel_id))

        before = row_snapshot("travel_details", travel_id)
        t_start, t_end = parse_travel_range(data["travel_dates"])
        data["travel_dates"] = format_travel_range(t_start, t_end) or data["travel_dates"]
        # 有领用记录时证件号码也是派生的（由领用记录回写），表单上那一栏是只读的。
        # 只读字段照样会随表单提交，伪造的 POST 更是想填什么填什么，所以这里
        # 直接沿用库里的既有值，不采信提交上来的。路径B 没有领用记录，
        # 那一栏是系统里唯一的来源，仍按提交值写入。
        from blueprints.issuance import travel_has_issuance
        locked = travel_has_issuance(travel_id)
        passport_no = row["passport_no"] if locked else data["passport_no"]
        # 申请人同理，而且更要紧：领用记录上有本人手写签名，签的就是「我为这次申请
        # 领了这本证」。事后把申请改挂到别人名下，那张签了字的凭证就指向了另一个人
        # ——这正是这套签名要防的事。登记领用时校验过一次「领用人必须就是申请人」，
        # 但那只是那一刻的事，事后改申请人能绕过去。要换人只能先作废领用记录。
        pfid = row["personnel_filing_id"] if locked else data["personnel_filing_id"]
        db.execute(
            # 证件领用/归还日期为派生字段，由证件领用模块维护，此处不覆盖
            "UPDATE travel_details SET personnel_filing_id=?, unit=?, department=?, "
            "name=?, position=?, title=?, id_number=?, destination_passport=?, "
            "category=?, travel_dates=?, travel_start=?, travel_end=?, approval_date=?, need_new_passport=?, "
            "passport_no=?, actual_return_date=?, "
            "operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                pfid, data["unit"], data["department"],
                data["name"], data["position"], data["title"], data["id_number"],
                data["destination_passport"], data["category"], data["travel_dates"],
                t_start, t_end, data["approval_date"], data["need_new_passport"], passport_no,
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

    from blueprints.issuance import travel_has_issuance
    return render_template(
        "travel/form.html",
        data=dict(row),
        editing=True,
        travel_id=travel_id,
        attachments=attachments,
        cert_no_derived=travel_has_issuance(travel_id),
        applicant_locked=travel_has_issuance(travel_id),
    )


# =========================================================================
# 查看
# =========================================================================
@travel_bp.route("/travel/<int:travel_id>")
@login_required
def view(travel_id) -> ResponseReturnValue:
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
def delete(travel_id) -> ResponseReturnValue:
    db = get_db()
    row = db.execute("SELECT * FROM travel_details WHERE id = ?", (travel_id,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("travel.list"))

    # 引用守卫：开过证件领用单就不能删这条申请，否则那张单指向一条不存在的出行。
    #
    # 原来的提示写的是「请先作废相关领用记录」——照做没有用：下面这条统计不看
    # status，作废的照样算数，作废完再来删还是被挡。而这不是判据写漏了：
    # 领用单上有本人手写签名，作废是「这次领用作废」，不是「这次领用没发生过」，
    # 单子仍要留档，仍然指着这条出行。
    #
    # 所以把话说准：这条申请删不掉，能做的是「取消行程」——申请确实发生过，
    # 只是没有成行，取消会记下取消日期并按 5 个工作日催还证件，历史也留得住。
    counts = db.execute(
        "SELECT SUM(status = 'issued') AS issued, SUM(status = 'returned') AS returned, "
        "       SUM(status = 'voided') AS voided, COUNT(*) AS total "
        "FROM cert_issuance WHERE travel_id = ?", (travel_id,)
    ).fetchone()
    if counts["total"]:
        parts = [f"{n} 条{label}" for label, n in
                 (("已领用未归还", counts["issued"]), ("已归还", counts["returned"]),
                  ("已作废", counts["voided"])) if n]
        flash(f"该出国申请已开出 {counts['total']} 条证件领用记录（{'、'.join(parts)}），不能删除"
              "——领用单上有本人签名，作废也仍要留档，删了申请那张单就指向一条不存在的出行。"
              "如果这次没有成行，请改用「取消行程」。", "danger")
        return redirect(url_for("travel.view", travel_id=travel_id))
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
def cancel(travel_id) -> ResponseReturnValue:
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
def restore(travel_id) -> ResponseReturnValue:
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
def attachment_download(att_id) -> ResponseReturnValue:
    db = get_db()
    att = db.execute("SELECT * FROM attachments WHERE id = ?", (att_id,)).fetchone()
    if not att:
        flash("附件不存在。", "danger")
        return redirect(url_for("travel.list"))
    directory = os.path.join(Config.UPLOAD_FOLDER)
    return send_from_directory(directory, att["file_path"], download_name=att["file_name"])


@travel_bp.route("/travel/attachment/<int:att_id>/preview")
@login_required
def attachment_preview(att_id) -> ResponseReturnValue:
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
def attachment_delete(att_id) -> ResponseReturnValue:
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
        # 注意：passport_collect_date / passport_return_date 已改为派生字段，
        # 由证件领用模块（blueprints/issuance.py）唯一写入，此处不再从表单读取。
        "need_new_passport": form.get("need_new_passport", "否").strip(),
        "passport_no": form.get("passport_no", "").strip(),
        "actual_return_date": parse_date_input(form.get("actual_return_date", "")),
        "operator": operator_name(),
    }


def _validate_form(data: dict) -> list[str]:
    errors = []
    required = [
        ("personnel_filing_id", "备案人员"), ("unit", "单位"), ("department", "部门"),
        ("name", "姓名"), ("position", "职务"), ("id_number", "身份证号"),
        ("destination_passport", "地点、证照"), ("category", "类别"),
        ("travel_dates", "计划出行日期"), ("need_new_passport", "是否做证"),
    ]
    errors += check_required(data, required)
    # 明细表身份证由备案信息自动带入、无性别/出生字段，仅校验号码本身
    errors += check_identity(data, birth_field=None, gender_field=None)

    # 计划出行日期区间：起止须为真实日期且起始不晚于结束
    if data.get("travel_dates"):
        ok, msg = validate_travel_range(data["travel_dates"])
        if not ok:
            errors.append(f"计划出行日期: {msg}")

    errors += check_dates(data, [
        ("approval_date", "批准日期"),
        ("actual_return_date", "实际回国日期"),
    ])

    # 证件领用日期原在此校验必填，现已迁移至证件领用模块（须手写签名后登记），
    # 出行表单不再收集该字段。

    # 一本可用的证都没有，却说不做证——这条记录本身就是错的。
    #
    # 「够不够用」判不了：系统不知道这趟要用哪种证（明细表只有「地点、证照」
    # 那段自由文本），有港澳通行证但要去美国这类情形只能靠经办人自己看。
    # 但「一本都没有」是可判的，而且无论去哪都不可能有证用，属于硬错误。
    #
    # 「有证」要算有效期：一本过期护照等于没有。证照登记里填了号码就必须填
    # 有效日期，所以这个判断的数据一定在。
    if data.get("need_new_passport") == "否" and data.get("personnel_filing_id"):
        today = datetime.now().strftime("%Y%m%d")
        usable = get_db().execute(
            # 一个人可能有多条证照记录（历史遗留），任意一条里有在有效期内的证就算数
            "SELECT 1 FROM certificates WHERE personnel_filing_id = ? AND ("
            "  (passport_no  IS NOT NULL AND passport_no  != '' AND passport_expiry  >= ?) OR"
            "  (hm_pass_no   IS NOT NULL AND hm_pass_no   != '' AND hm_pass_expiry   >= ?) OR"
            "  (tw_pass_no   IS NOT NULL AND tw_pass_no   != '' AND tw_pass_expiry   >= ?)) LIMIT 1",
            (data["personnel_filing_id"], today, today, today)).fetchone()
        if not usable:
            errors.append(
                "该备案人员名下没有在有效期内的出入境证件，「是否做证」应为「是」。")

    return errors


def _is_pdf(f) -> bool:
    """魔数校验：真实 PDF 以 %PDF- 开头（读取后回退流位置，不影响后续保存）。"""
    head = f.stream.read(5)
    f.stream.seek(0)
    return head == b"%PDF-"


def _missing_attachment_errors(files, need_new_passport: str) -> list:
    """附件必填校验：路径A须含《个人申请报告》《审批表》；路径B（需做证）另须《同意申办函》。
    同时做 PDF 魔数预检，伪造扩展名的文件在入库前即被拦截。"""
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

    # 魔数预检：提交阶段即拒绝非 PDF 内容，避免"记录已存、必传附件被拒"的不一致
    for field in ("att_application", "att_approval", "att_consent"):
        for f in files.getlist(field):
            if f and f.filename and not _is_pdf(f):
                errors.append(f"文件 {f.filename} 内容不是有效的 PDF，请上传真实的 PDF 扫描件。")
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
            # 魔数校验：真实 PDF 以 %PDF- 开头，防止改扩展名的任意文件入库
            head = f.stream.read(5)
            f.stream.seek(0)
            if head != b"%PDF-":
                flash(f"文件 {f.filename} 内容不是有效的 PDF（已拒绝）。", "warning")
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

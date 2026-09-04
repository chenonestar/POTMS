"""撤控备案蓝图"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db
from utils.helpers import log_action, list_all, normalize_residence, get_dict_options, row_snapshot, operator_name
from utils.validators import parse_date_input, check_required, check_dates, check_identity

decontrol_bp = Blueprint("decontrol", __name__)


def _unsettled_certs(filing_id) -> list[str]:
    """撤控前的清障检查：这个人名下还有哪些证件没清干净。

    撤控表上「证件移交日期」这一栏本身就说明：业务上撤控是以证件收缴完毕为前提的。
    但此前代码不查，于是可以「带证走人」——人撤控了，那条逾期告警还挂在首页，
    而这个人已经不在管理范围内，谁也处理不掉，成了永远消不掉的死账。

    两类未清，与逾期告警同源（见 blueprints/travel.py 的说明）：
    - 路径A：还有未归还的领用记录（证在本人手上，从保管处借出去没还）；
    - 路径B：做证的申请里，新证还没进证照台账（证从公安办出来就没回来过）。
    """
    db = get_db()
    problems = []
    issued = db.execute(
        "SELECT COUNT(*) FROM cert_issuance WHERE personnel_filing_id = ? AND status = 'issued'",
        (filing_id,)).fetchone()[0]
    if issued:
        problems.append(f"未归还的证件领用记录 {issued} 条")
    # 做证且新证号码没出现在该人证照台账里 —— 判据与 travel._registered_cert_travel_ids 一致
    pending = db.execute(
        "SELECT COUNT(*) FROM travel_details t "
        "WHERE t.personnel_filing_id = ? AND t.need_new_passport = '是' "
        "  AND COALESCE(t.trip_status, 'normal') != 'cancelled' "
        "  AND NOT EXISTS (SELECT 1 FROM certificates c "
        "                  WHERE c.personnel_filing_id = t.personnel_filing_id "
        "                    AND t.passport_no IS NOT NULL AND t.passport_no != '' "
        "                    AND t.passport_no IN (c.passport_no, c.hm_pass_no, c.tw_pass_no))",
        (filing_id,)).fetchone()[0]
    if pending:
        problems.append(f"新办后尚未交回入库的证件 {pending} 本")
    return problems


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
def list() -> ResponseReturnValue:
    search = request.args.get("search", "").strip()
    unit_type_filter = request.args.get("submit_unit_type", "").strip()

    where, params = build_filters(request.args)
    base = "SELECT * FROM decontrol_filing WHERE 1=1" + where + " ORDER BY created_at DESC"

    pg = list_all(base, params)  # 全量下发，前端按视口窗口化分页
    return render_template(
        "decontrol/list.html",
        items=pg,
        search=search,
        unit_type_filter=unit_type_filter,
        unit_type_opts=get_dict_options("submit_unit_type"),
    )


@decontrol_bp.route("/decontrol/new/<int:filing_id>", methods=["GET", "POST"])
@login_required
def new(filing_id) -> ResponseReturnValue:
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

    # 证件没清干净不许撤控。放在 GET 上也拦：让人填完一整张表再告诉他不行，
    # 是最没必要的一种为难。
    unsettled = _unsettled_certs(filing_id)
    if unsettled:
        flash("该人员名下尚有" + "、".join(unsettled)
              + "，请先办理归还或交回登记后再撤控。", "danger")
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
def view(dec_id) -> ResponseReturnValue:
    db = get_db()
    row = db.execute("SELECT * FROM decontrol_filing WHERE id = ?", (dec_id,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("decontrol.list"))
    return render_template("decontrol/view.html", dec=row)


@decontrol_bp.route("/decontrol/<int:dec_id>/revoke", methods=["POST"])
@login_required
def revoke(dec_id) -> ResponseReturnValue:
    """撤销撤控：把人放回「有效」，撤控记录本身物理删除。

    撤控此前是一扇单向门——错撤了一个人，界面上没有任何回头路，只能去改库。
    而撤控会把这个人从所有在办入口里摘掉（发起撤控的下拉、出行申请的选人、
    首页告警都只认 status='active'），所以「撤错了」的代价不是一条脏数据，
    是这个人的业务彻底办不了。

    为什么是物理删除而不是标记作废：撤控表是**报出去的备案单据**，一条记录就是
    「这个人已上报撤控」。撤销意味着这件事没有发生过，留一条作废的单据反而会在
    列表和导出里制造「他到底撤没撤」的歧义。完整的 before 快照进操作日志，
    需要追溯时查日志——这正是日志该干的事。
    """
    db = get_db()
    row = db.execute("SELECT * FROM decontrol_filing WHERE id = ?", (dec_id,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("decontrol.list"))

    before = row_snapshot("decontrol_filing", dec_id)
    filing_id = row["personnel_filing_id"]
    db.execute("DELETE FROM decontrol_filing WHERE id = ?", (dec_id,))
    # 人员备案可能已被删除（撤控单据自带姓名身份证快照，不依赖它存在）；
    # 只在还在的时候把状态放回去。
    restored = db.execute(
        "UPDATE personnel_filing SET status = 'active', updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND status = 'decontrolled'",
        (filing_id,),
    ).rowcount
    db.commit()
    log_action("delete", "decontrol_filing", dec_id, before=before)

    name = f"{row['surname']}{row['given_name']}"
    if restored:
        flash(f"已撤销 {name} 的撤控备案，该人员备案状态已恢复为「有效」。", "success")
        # 撤控以证件收缴移交为前提（cert_handover_date 必填），所以撤控那一刻
        # 他名下的证已经交出去了，盘库时也随之退出「在库」（stock_split 只算
        # 在控人员）。现在人回到在控，那些台账行**立刻重新计入在库**，
        # 可实体证是否已从报送单位收回，系统一无所知。
        #
        # 这里只提醒不拦：撤销撤控本来就是纠错入口，多数是「撤错了」——那种
        # 情形下证根本没真移交，拦下来反而是添乱。但账面与实体的这次错位
        # 必须当场说出来，否则盘库时才发现柜子里少了证，已经查不清是哪一步。
        n = db.execute(
            "SELECT (CASE WHEN COALESCE(passport_no,'')<>'' THEN 1 ELSE 0 END)"
            "     + (CASE WHEN COALESCE(hm_pass_no ,'')<>'' THEN 1 ELSE 0 END)"
            "     + (CASE WHEN COALESCE(tw_pass_no ,'')<>'' THEN 1 ELSE 0 END) AS n "
            "FROM certificates WHERE personnel_filing_id = ?", (filing_id,)).fetchall()
        total = sum(r["n"] for r in n)
        if total:
            handover = (row["cert_handover_date"] or "").strip()
            when = f"（撤控时移交日期 {handover}）" if handover else ""
            flash(f"注意：{name} 名下台账上的 {total} 本证件已重新计入「在库」{when}。"
                  "撤控时这些证件已办理移交，请确认实体证件确已收回保管处；"
                  "若实际未收回，盘库时会对不上。", "warning")
    else:
        flash(f"已撤销 {name} 的撤控备案。未找到对应的有效备案人员，"
              "请到「人员备案」确认其状态。", "warning")
    return redirect(url_for("decontrol.list"))


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
        "operator": operator_name(),
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
        ("reason", "撤控原因"),
        # 撤控以证件收缴完毕为前提，移交日期是这件事发生过的凭据，不能留空
        ("cert_handover_date", "证件移交日期"),
    ]
    # 「入库批号」改为选填。它指的是当初做备案时报给公安的那批纸质材料的批号，
    # 而系统从没生成过、也从没存过任何批号——personnel_filing 上根本没有这个字段。
    # 一个必填、却既给不出来源也校不了对错的格子，只会逼人随便敲一个数字进去，
    # 那比留空更糟：留空至少诚实地表示「不知道」。
    # 列仍是 NOT NULL，留空写入的是空串——不动 schema，也就不牵动另外四版的生成文件。
    errors += check_required(data, required)
    errors += check_dates(data, [
        ("birth_date", "出生日期"),
        ("cert_handover_date", "证件移交日期"),
        ("decontrol_date", "撤控日期"),
    ])
    errors += check_identity(data)
    errors += _date_order_errors(data)

    return errors


def _date_order_errors(data: dict) -> list[str]:
    """撤控日期与证件移交日期的先后关系。

    业务上撤控**以证件收缴完毕为前提**（这也是 _unsettled_certs 那道前置校验的
    依据），所以移交必然发生在撤控之前或当天：

        证件移交日期 ≤ 撤控日期 ≤ 今天

    不要求两者相同——先把证收上来、隔几天再报撤控，是正常节奏。
    两个日期都不得晚于今天：这两件事都是**已经发生过的事实**，撤控表是报出去的
    单据，上面不该出现还没发生的日期。此前这两条关系一条都没校验，随便填。
    """
    errors = []
    today = datetime.now().strftime("%Y%m%d")
    handover = (data.get("cert_handover_date") or "").strip()
    decontrol = (data.get("decontrol_date") or "").strip()
    for val, label in ((handover, "证件移交日期"), (decontrol, "撤控日期")):
        if val and val > today:
            errors.append(f"{label}不能晚于今天（{today}）——它记的是已经发生过的事。")
    if handover and decontrol and handover > decontrol:
        errors.append(
            f"证件移交日期（{handover}）不能晚于撤控日期（{decontrol}）："
            "撤控以证件收缴完毕为前提，证要先交回来，才谈得上报撤控。")
    return errors

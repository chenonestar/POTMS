"""证照登记蓝图 — 护照 / 港澳通行证 / 台湾通行证"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db
from utils.helpers import log_action, list_all, row_snapshot, operator_name
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
    # 持证人是否仍在控。首页那张「证照登记（人）」卡按 active 计数并带着这个参数
    # 跳过来，数字与列表必须能对上；不带参数时列表照旧显示全部（含已撤控，行上有标注）。
    filing_status = args.get("filing_status", "").strip()
    if filing_status in ("active", "decontrolled"):
        where += (" AND EXISTS (SELECT 1 FROM personnel_filing pf2 "
                  "             WHERE pf2.id = certificates.personnel_filing_id AND pf2.status = ?)")
        params.append(filing_status)
    if ids:
        ph = ",".join("?" for _ in ids)
        where += f" AND id IN ({ph})"
        params.extend(ids)
    return where, tuple(params)


@certificate_bp.route("/certificate/")
@login_required
def list() -> ResponseReturnValue:
    search = request.args.get("search", "").strip()
    has_passport = request.args.get("has_passport", "").strip()
    has_hm = request.args.get("has_hm", "").strip()
    has_tw = request.args.get("has_tw", "").strip()
    filing_status = request.args.get("filing_status", "").strip()

    where, params = build_filters(request.args)
    # 带上持证人的备案状态与撤控时的证件移交日期：人已撤控的，台账上要一眼看出来，
    # 否则「在库 N 本」这个数字里混着一批早已移交出去的证。两者都是关联查得到的，
    # 不在 certificates 上冗余列（那样五版共用的 schema 就得跟着改）。
    base = ("SELECT certificates.*, pf.status AS filing_status, "
            "       (SELECT d.cert_handover_date FROM decontrol_filing d "
            "        WHERE d.personnel_filing_id = certificates.personnel_filing_id "
            "        ORDER BY d.id DESC LIMIT 1) AS handover_date "
            "FROM certificates "
            "LEFT JOIN personnel_filing pf ON pf.id = certificates.personnel_filing_id "
            "WHERE 1=1" + where + " ORDER BY certificates.updated_at DESC")

    pg = list_all(base, params)  # 全量下发，前端按视口窗口化分页

    # 标记即将到期的证照
    from datetime import datetime, timedelta
    from config import Config
    today = datetime.now().strftime("%Y%m%d")
    warn_date = (datetime.now() + timedelta(days=Config.CERT_EXPIRY_WARN_DAYS)).strftime("%Y%m%d")

    expired = []  # (row, passport_type_label)
    for row in pg["rows"]:
        # 人都撤控了，他那本证到不到期与本单位无关，不再标黄
        if row["filing_status"] == "decontrolled":
            continue
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
        filing_status=filing_status,
    )


STOCK_IN, STOCK_OUT = "在库", "借出未还"


def stock_rows(args) -> dict:
    """盘库清单的行 —— 页面、打印、导出三处共用这一份。

    在库与借出未还合成**一张表**、用「去向」列区分，而不是两张表：
    一张表才能套用全站通用的那套列表行为（勾选、排序、窗口化分页、批量打印），
    两张表则每样都得再写一遍，而且没有哪一份是「整份清单」。
    导出的 Excel 本来也是一张带「去向」列的表，现在页面与它同形。

    筛选判据只写一次：此前页面与导出各写了一份 keep()，两边一改就会漂。
    """
    in_stock, lent_out, orphan_nos = stock_split()
    rows = ([dict(it, status=STOCK_IN) for it in in_stock]
            + [dict(it, status=STOCK_OUT) for it in lent_out])

    search = args.get("search", "").strip()
    type_filter = args.get("cert_type", "").strip()
    status_filter = args.get("status", "").strip()
    ids = {x for x in args.get("ids", "").split(",") if x.strip()}

    def keep(it):
        # 勾选行优先：打印/导出选中行时，其余筛选一律不再叠加，
        # 否则「勾了 3 行却导出 2 行」这种事说不清是谁的问题。
        if ids:
            return it["key"] in ids
        if status_filter and it["status"] != status_filter:
            return False
        if type_filter and it["cert_type"] != type_filter:
            return False
        if search:
            hay = f"{it['name']}{it['cert_no']}{it['unit']}{it['department']}".lower()
            return search.lower() in hay
        return True

    return {
        "rows": [it for it in rows if keep(it)],
        "total_in_stock": len(in_stock),
        "total_lent_out": len(lent_out),
        "orphan_nos": orphan_nos,
        "search": search,
        "type_filter": type_filter,
        "status_filter": status_filter,
        "ids": ",".join(sorted(ids)),
        "cert_types": [label for label, *_ in CERT_SLOTS],
        "printed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


@certificate_bp.route("/certificate/stock")
@login_required
def stock() -> ResponseReturnValue:
    """盘库清单：此刻在控人员台账上的每一本证，一本一行，供打开柜子逐本核对。

    首页那张「在库 N 本」只能核对总数——少一本多一本，看不出是哪一本。
    这页给的是清单本身：按单位 / 部门 / 姓名排序（柜子一般也这么放）。

    「借出未还」同表列出：盘库时手里这份清单要能回答「柜子里没有的那几本，
    去哪儿了」，否则对不上时还得再翻一次系统。
    """
    return render_template("certificate/stock.html", **stock_rows(request.args))


@certificate_bp.route("/certificate/stock/print")
@login_required
def stock_print() -> ResponseReturnValue:
    """盘库清单的打印页（独立排版，不是把整张网页打出来）。

    整页打印会把侧边栏、筛选表单、分页条一并印上纸，而且窗口化分页只显示当前页，
    打出来的清单是残的。这里单开一页：只有表、表头跨页重复、每行一个空勾选框。
    """
    return render_template("certificate/stock_print.html", **stock_rows(request.args))


@certificate_bp.route("/certificate/new", methods=["GET", "POST"])
@login_required
def new() -> ResponseReturnValue:
    if request.method == "POST":
        data = _extract_form(request.form)
        errors = _validate_form(data)
        # 一人一行：三种证件是同一行上的三组列，本来就装得下一个人的全部证件。
        # 需求文档写明「一行为一人」，但此前代码从未拦过，现实里很容易变成
        # 「没找到原记录就又建一条」——于是同一个人两个编辑入口，到期预警报两遍，
        # 想改护照有效期还得先点进去看哪条里有护照。
        dup_id = _existing_cert_id(data.get("personnel_filing_id"))
        if dup_id:
            errors.append(
                f"该备案人员已有证照记录（#{dup_id}）。三类证件登记在同一条记录上，"
                f"请直接编辑那一条，不要新建。")
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
        log_action("create", "certificates", cert_id, after=row_snapshot("certificates", cert_id))
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
        log_action("update", "certificates", cert_id,
                   before=before, after=row_snapshot("certificates", cert_id))
        flash("证照信息已更新。", "success")
        # 换发新证时最容易漏的一步：号码换了，有效期或上交日期还留着旧证的。
        # 台账是到期预警与「有没有可用证件」校验的唯一依据，日期不准这两样都会失灵。
        # 号码变化是换发的确切信号，此时提醒一次，成本为零。
        for changed in _renewed_labels(before, data):
            flash(f"{changed}号码已变更：请确认有效日期与上交日期同步更新为新证的。", "warning")
        return redirect(url_for("certificate.list"))

    return render_template("certificate/form.html", data=dict(row), editing=True, cert_id=cert_id)


@certificate_bp.route("/certificate/<int:cert_id>/delete", methods=["POST"])
@login_required
def delete(cert_id) -> ResponseReturnValue:
    db = get_db()
    row = db.execute("SELECT * FROM certificates WHERE id = ?", (cert_id,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("certificate.list"))

    refs = _cert_references(row)
    if refs:
        flash("该证照的号码" + "、".join(refs) + "，不能删除。"
              "如证件已注销或换发，请编辑本条记录更新号码，不要删除。", "danger")
        return redirect(url_for("certificate.list"))

    before = row_snapshot("certificates", cert_id)
    db.execute("DELETE FROM certificates WHERE id = ?", (cert_id,))
    db.commit()
    log_action("delete", "certificates", cert_id, before=before)
    flash("证照记录已删除。", "info")
    return redirect(url_for("certificate.list"))


def _cert_references(row) -> list[str]:
    """这条证照的号码被哪些业务记录引用了。

    此前删除是裸 DELETE，什么都不查，而后果是隐性的：
    - 出行表上补录的做证号码一旦在台账里找不到对应，那条出行**当场变回「逾期未交回」**
      （路径B 的判据就是「号码在不在台账里」，见 travel._registered_cert_travel_ids）；
    - 已签字的领用凭证上印着这个号码，台账里却查无此证。

    所以判据是「号码有没有被引用」，而不是「这条记录属于谁」——三个号码槽逐个查。
    """
    db = get_db()
    nos = [str(row[f] or "").strip() for _, f, _, _ in CERT_SLOTS]
    nos = [n for n in nos if n]
    if not nos:
        return []
    ph = ",".join("?" for _ in nos)
    out = []
    trav = db.execute(
        f"SELECT COUNT(*) FROM travel_details WHERE passport_no IN ({ph})", nos).fetchone()[0]
    if trav:
        out.append(f"已被 {trav} 条出国申请引用")
    iss = db.execute(
        f"SELECT COUNT(*) FROM cert_issuance WHERE cert_nos IN ({ph})", nos).fetchone()[0]
    if iss:
        out.append(f"已被 {iss} 条证件领用记录引用")
    return out


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
        "operator": operator_name(),
    }


# 三类证件的号码 / 有效期 / 上交日期字段，与中文名。多处遍历共用一份。
CERT_SLOTS = (
    ("普通护照", "passport_no", "passport_expiry", "passport_submit_date"),
    ("往来港澳通行证", "hm_pass_no", "hm_pass_expiry", "hm_pass_submit_date"),
    ("大陆居民往来台湾通行证", "tw_pass_no", "tw_pass_expiry", "tw_pass_submit_date"),
)


def lent_out_numbers() -> set:
    """当前借出未还的证件号码。

    领用记录是「这本证现在在谁手上」的权威来源——出国申请上的领用/归还日期是它
    回写的派生字段，绕道那边数会多一个可能不同步的环节。
    一次申请只能领一本证（见 issuance._validate_form），所以一条记录就是一本。
    """
    return {(r[0] or "").strip() for r in get_db().execute(
        "SELECT cert_nos FROM cert_issuance WHERE status = 'issued'").fetchall()
        if (r[0] or "").strip()}


def stock_split():
    """把在控人员台账上的每一本证分成「在库」与「借出未还」两堆。

    返回 (in_stock, lent_out, orphan_numbers)，前两者是一本一行的字典列表。

    三条口径，都是为了让「在库」这个数能真的拿去和柜子里的实体证核对：

    - **按号码槽算，不按台账行算。**一行最多放三本（护照 / 港澳 / 台湾）。
      一个人借走护照，另外两本还在柜子里，按行算就全丢了。
    - **只算在控人员。**撤控以证件收缴移交为前提（移交日期是必填项，见
      decontrol._validate_form），那些证已经交出去了，不在柜子里。台账行还留着
      是为了留痕，不是因为证还在。
    - **路径B 新办未入库的不在此列。**那本证还没进台账，也从没进过柜子，
      单独一档，见 travel.new_making_travel_ids。

    orphan_numbers 是「有借出记录、号码却不在任何在控人员台账里」的那些。
    它不影响在库数（本来就没算进去），但说明数据对不上，该报出来让人去查。
    """
    lent = lent_out_numbers()
    rows = get_db().execute(
        "SELECT c.*, pf.status AS filing_status FROM certificates c "
        "JOIN personnel_filing pf ON pf.id = c.personnel_filing_id "
        "WHERE pf.status = 'active' "
        "ORDER BY c.unit, c.department, c.name, c.id").fetchall()

    in_stock, lent_out, seen = [], [], set()
    for r in rows:
        for label, no_col, exp_col, sub_col in CERT_SLOTS:
            no = (r[no_col] or "").strip()
            if not no:
                continue
            seen.add(no)
            item = {
                "cert_id": r["id"], "personnel_filing_id": r["personnel_filing_id"],
                # 一本证的稳定标识：台账行 id + 号码槽列名。
                # 不能用证件号码当 key——号码本该唯一，但数据出错时会重复，
                # 那时勾一行会连带勾中另一个人的证。
                "key": f"{r['id']}:{no_col}",
                "unit": r["unit"], "department": r["department"], "name": r["name"],
                "cert_type": label, "cert_no": no,
                "expiry": r[exp_col] or "", "submit_date": r[sub_col] or "",
            }
            (lent_out if no in lent else in_stock).append(item)
    return in_stock, lent_out, sorted(lent - seen)


def _existing_cert_id(personnel_filing_id):
    """该备案人员是否已有证照记录；有则返回其 id。"""
    if not personnel_filing_id:
        return None
    row = get_db().execute(
        "SELECT id FROM certificates WHERE personnel_filing_id = ? ORDER BY id LIMIT 1",
        (personnel_filing_id,)).fetchone()
    return row["id"] if row else None


def _renewed_labels(before: dict, after: dict) -> list[str]:
    """哪几类证件的号码发生了变化（旧号码非空且与新号码不同）。

    只认「换发」：从空到有是首次登记，不提醒；改回空是注销，也不提醒。
    """
    out = []
    for label, no_f, _exp, _sub in CERT_SLOTS:
        old = ((before or {}).get(no_f) or "").strip()
        new = ((after or {}).get(no_f) or "").strip()
        if old and new and old != new:
            out.append(label)
    return out


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
    for label, no_field, exp_field, sub_field in CERT_SLOTS:
        if data.get(no_field):
            if not data.get(exp_field):
                errors.append(f"填写{label}证件号时，有效日期为必填。")
            if not data.get(sub_field):
                errors.append(f"填写{label}证件号时，上交日期为必填。")

    return errors

"""证件领用管理蓝图 — 领用登记 / 归还登记 / 作废，含手写签名

设计约束（已与业务方审定）：
1. 本模块是「证件领用/归还日期」的**唯一写入方**；travel_details 上的
   passport_collect_date / passport_return_date 降级为派生只读字段，
   由本模块回写，避免双数据源。
2. 签名一经保存**不可编辑**，登记有误只能作废（voided）后重新登记，
   以保证签名凭证的证据效力。
3. 签名以 PNG 位图 + 笔迹矢量双存于数据库（BLOB/TEXT），随每日备份一起
   落盘；不落文件系统（uploads 目录不在备份范围内）。
"""
from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, Response, abort)
from flask.typing import ResponseReturnValue

from auth import login_required
from config import Config
from database import get_db
from utils.helpers import log_action, list_all, row_snapshot, get_dict_value, operator_name
from utils.validators import parse_date_input, check_required, check_dates

issuance_bp = Blueprint("issuance", __name__)

# 证件种类代码 → certificates 表中对应的号码字段
CERT_NO_FIELD = {
    "01": "passport_no",
    "02": "hm_pass_no",
    "03": "tw_pass_no",
}

# 列表筛选里「待核实」的取值。真实种类代码是 01/02/03，不会撞。
CERT_TYPE_PENDING = "pending"

# PNG 魔数（防止前端传入非图片内容）
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# 单张签名上限：正常裁剪后 5–20KB，留足余量仍可拦住异常大图
MAX_SIGN_BYTES = 512 * 1024
MAX_META_CHARS = 400_000


# ---------------------------------------------------------------------------
# 签名解析
# ---------------------------------------------------------------------------
def _decode_signature(png_data_url: str) -> tuple[bytes | None, str]:
    """dataURL → PNG bytes。返回 (bytes, 错误信息)；失败时 bytes 为 None。

    留空是否算错，取决于 Config.REQUIRE_SIGNATURE（环境变量
    POTMS_REQUIRE_SIGNATURE，默认强制）。注意这里是**唯一**真正的守门人：
    前端那两道拦截（提交前校验、少于 8 点算误触）都在浏览器里，伪造 POST 绕得过。

    格式校验不受开关影响——签了就必须是合法 PNG，不能因为「不强制」就把
    坏数据放进库里。
    """
    raw = (png_data_url or "").strip()
    if not raw:
        if not Config.REQUIRE_SIGNATURE:
            return None, ""      # 放宽模式：留空即无签名，记录里如实存 NULL
        return None, "请手写签名后再提交。"
    prefix = "data:image/png;base64,"
    if not raw.startswith(prefix):
        return None, "签名数据格式不正确。"
    try:
        blob = base64.b64decode(raw[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        return None, "签名数据解析失败，请重新签名。"
    if not blob.startswith(_PNG_MAGIC):
        return None, "签名数据不是有效的 PNG 图像。"
    if len(blob) > MAX_SIGN_BYTES:
        return None, "签名图像过大，请重新签名。"
    return blob, ""


def _clean_meta(raw: str) -> str | None:
    """校验笔迹矢量 JSON；过大或非法则丢弃（不阻断业务，位图仍在）。"""
    raw = (raw or "").strip()
    if not raw or len(raw) > MAX_META_CHARS:
        return None
    try:
        json.loads(raw)
    except (ValueError, TypeError):
        return None
    return raw


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------
def build_filters(args, ids=None):
    """构建领用列表 WHERE 子句，供列表与导出复用。"""
    where = ""
    params: list = []
    search = args.get("search", "").strip()
    if search:
        where += " AND (i.holder_name LIKE ? OR i.id_number LIKE ? OR i.cert_nos LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    status = args.get("status", "").strip()
    if status in ("issued", "returned", "voided"):
        where += " AND i.status = ?"
        params.append(status)
    cert_type = args.get("cert_type", "").strip()
    if cert_type == CERT_TYPE_PENDING:
        # 历史回填里判不出种类的那批，cert_types 为空。上面那句 LIKE 对空值恒不
        # 匹配（'' 拼出来是 ',,'），所以单开一条——不能筛出来，这批待办就没法收口。
        where += " AND (i.cert_types IS NULL OR i.cert_types = '')"
    elif cert_type:
        where += " AND (',' || i.cert_types || ',') LIKE ?"
        params.append(f"%,{cert_type},%")
    date_from = args.get("date_from", "").strip()
    if date_from:
        where += " AND i.issue_date >= ?"
        params.append(parse_date_input(date_from))
    date_to = args.get("date_to", "").strip()
    if date_to:
        where += " AND i.issue_date <= ?"
        params.append(parse_date_input(date_to))
    if ids:
        ph = ",".join("?" for _ in ids)
        where += f" AND i.id IN ({ph})"
        params.extend(ids)
    return where, tuple(params)


# 列表/导出共用：JOIN 备案表以排除孤儿行（延续既有数据完整性口径）
BASE_SELECT = (
    "SELECT i.*, pf.work_unit AS work_unit "
    "FROM cert_issuance i "
    "JOIN personnel_filing pf ON i.personnel_filing_id = pf.id "
    "WHERE 1=1"
)


@issuance_bp.route("/issuance/")
@login_required
def list() -> ResponseReturnValue:
    where, params = build_filters(request.args)
    base = BASE_SELECT + where + " ORDER BY i.issue_date DESC, i.id DESC"
    pg = list_all(base, params)
    # 证件种类代码 → 中文标签，在这里算好再下发。模板里 split 字符串在三种
    # Jinja 实现（Jinja2 / gonja / minijinja）上写法不一，而五版模板要逐字一致。
    rows = []
    for r in pg["rows"]:
        d = dict(r)
        d["cert_type_labels"] = [
            get_dict_value("cert_type", c) or c
            for c in (d.get("cert_types") or "").split(",") if c.strip()
        ]
        rows.append(d)
    pg = {**pg, "rows": rows}
    return render_template(
        "issuance/list.html",
        items=pg,
        search=request.args.get("search", "").strip(),
        status_filter=request.args.get("status", "").strip(),
        cert_type_filter=request.args.get("cert_type", "").strip(),
        date_from=request.args.get("date_from", "").strip(),
        date_to=request.args.get("date_to", "").strip(),
    )


# ---------------------------------------------------------------------------
# 新建领用
# ---------------------------------------------------------------------------
@issuance_bp.route("/issuance/new", methods=["GET", "POST"])
@login_required
def new() -> ResponseReturnValue:
    db = get_db()

    if request.method == "POST":
        data = _extract_form(request.form)
        errors = _validate_form(data)
        blob, sig_err = _decode_signature(request.form.get("sign_png", ""))
        if sig_err:
            errors.append(sig_err)

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("issuance/form.html", data=data,
                                   travel=_travel_brief(data.get("travel_id")))

        meta = _clean_meta(request.form.get("sign_meta", ""))
        db.execute(
            "INSERT INTO cert_issuance (travel_id, personnel_filing_id, holder_name, id_number, "
            "cert_types, cert_nos, issue_date, issuer, sign_image, sign_meta, status, remarks, operator) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'issued', ?, ?)",
            (data["travel_id"] or None, data["personnel_filing_id"], data["holder_name"],
             data["id_number"], data["cert_types"], data["cert_nos"], data["issue_date"],
             data["issuer"], blob, meta, data["remarks"], data["operator"]),
        )
        db.commit()
        iss_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        _sync_travel_derived(data["travel_id"])
        log_action("create", "cert_issuance", iss_id,
                   detail=f"证件领用登记：{data['holder_name']}，{_types_label(data['cert_types'])}",
                   after=row_snapshot("cert_issuance", iss_id))
        flash("证件领用登记已保存。", "success")
        return redirect(url_for("issuance.view", iss_id=iss_id))

    # GET：领用必须挂在一条出国申请上。直接进本页（没带 travel_id）时，
    # 先让经办人挑一条申请，挑完再进登记表单——而不是给个能填空的表单，
    # 让人有机会登记出一条无主的领用记录。
    travel_id = request.args.get("travel_id", type=int)
    prefill: dict = {"issue_date": datetime.now().strftime("%Y%m%d")}
    travel = _travel_brief(travel_id)
    if not travel:
        if travel_id:
            flash("指定的出国申请不存在。", "warning")
        return render_template("issuance/pick_travel.html", travels=_eligible_travels())
    if travel:
        prefill.update({
            "travel_id": travel_id,
            "personnel_filing_id": travel["personnel_filing_id"],
            "holder_name": travel["name"],
            "id_number": travel["id_number"],
        })
    return render_template("issuance/form.html", data=prefill, travel=travel)


# ---------------------------------------------------------------------------
# 详情
# ---------------------------------------------------------------------------
@issuance_bp.route("/issuance/<int:iss_id>")
@login_required
def view(iss_id) -> ResponseReturnValue:
    row = _get_or_404(iss_id)
    travel = _travel_brief(row["travel_id"]) if row["travel_id"] else None
    return render_template("issuance/view.html", item=row, travel=travel,
                           type_labels=_types_label(row["cert_types"]),
                           can_fix=can_fix_cert_types(row))


# ---------------------------------------------------------------------------
# 归还登记（同样需签名）
# ---------------------------------------------------------------------------
@issuance_bp.route("/issuance/<int:iss_id>/return", methods=["GET", "POST"])
@login_required
def do_return(iss_id) -> ResponseReturnValue:
    row = _get_or_404(iss_id)
    if row["status"] != "issued":
        flash("该记录不是「已领用」状态，无法办理归还。", "warning")
        return redirect(url_for("issuance.view", iss_id=iss_id))

    if request.method == "POST":
        return_date = parse_date_input(request.form.get("return_date", ""))
        errors: list[str] = []
        if not return_date:
            errors.append("归还日期为必填项。")
        else:
            errors += check_dates({"return_date": return_date}, [("return_date", "归还日期")])
            if return_date < row["issue_date"]:
                errors.append(f"归还日期不应早于领用日期（{row['issue_date']}）。")
        blob, sig_err = _decode_signature(request.form.get("sign_png", ""))
        if sig_err:
            errors.append(sig_err)

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("issuance/return.html", item=row,
                                   return_date=return_date,
                                   type_labels=_types_label(row["cert_types"]))

        before = row_snapshot("cert_issuance", iss_id)
        db = get_db()
        db.execute(
            "UPDATE cert_issuance SET return_date=?, return_sign_image=?, return_sign_meta=?, "
            "return_operator=?, status='returned', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (return_date, blob, _clean_meta(request.form.get("sign_meta", "")),
             operator_name(), iss_id),
        )
        db.commit()
        _sync_travel_derived(row["travel_id"])
        log_action("update", "cert_issuance", iss_id,
                   detail=f"证件归还登记：{row['holder_name']}，归还日期 {return_date}",
                   before=before, after=row_snapshot("cert_issuance", iss_id))
        flash("证件归还登记已保存。", "success")
        return redirect(url_for("issuance.view", iss_id=iss_id))

    return render_template("issuance/return.html", item=row,
                           return_date=datetime.now().strftime("%Y%m%d"),
                           type_labels=_types_label(row["cert_types"]))


# ---------------------------------------------------------------------------
# 作废（签名不可编辑，登记有误走此路径）
# ---------------------------------------------------------------------------
@issuance_bp.route("/issuance/<int:iss_id>/void", methods=["POST"])
@login_required
def void(iss_id) -> ResponseReturnValue:
    row = _get_or_404(iss_id)
    if row["status"] == "voided":
        flash("该记录已是作废状态。", "info")
        return redirect(url_for("issuance.view", iss_id=iss_id))

    reason = request.form.get("void_reason", "").strip()
    if not reason:
        flash("作废原因为必填项。", "danger")
        return redirect(url_for("issuance.view", iss_id=iss_id))

    before = row_snapshot("cert_issuance", iss_id)
    db = get_db()
    db.execute(
        "UPDATE cert_issuance SET status='voided', void_reason=?, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=?", (reason, iss_id))
    db.commit()
    _sync_travel_derived(row["travel_id"])
    log_action("void", "cert_issuance", iss_id,
               detail=f"领用记录作废：{row['holder_name']}，原因：{reason}",
               before=before, after=row_snapshot("cert_issuance", iss_id))
    flash("领用记录已作废，如需更正请重新登记。", "info")
    return redirect(url_for("issuance.view", iss_id=iss_id))


# ---------------------------------------------------------------------------
# 更正证件种类（仅限无签名的记录）
# ---------------------------------------------------------------------------
def can_fix_cert_types(row) -> bool:
    """只有**没有签名**的记录允许改证件种类。

    模块约束是「签名一经保存不可编辑」，因为签名签的就是「我领了这几样证件」，
    事后改种类会让那个签名名不副实——那种记录只能作废重录。

    但历史回填行本来就没有签名（老库里根本没采集过），作废重录这条路也走不通：
    新建领用默认强制手写签名，而历史记录压根没有签名可采。不给它们一个更正入口，
    订正迁移标出来的「待核实」就成了永远填不上的死数据。

    判据用「无签名」而不是「备注是回填串」：放宽模式（POTMS_REQUIRE_SIGNATURE=0）
    下手工登记的记录同样没有签名，同样没有会被推翻的凭证，一并适用。
    """
    return not row["sign_image"]


@issuance_bp.route("/issuance/<int:iss_id>/cert-types", methods=["POST"])
@login_required
def fix_cert_types(iss_id) -> ResponseReturnValue:
    row = _get_or_404(iss_id)
    if not can_fix_cert_types(row):
        flash("该记录已有领用人签名，证件种类不可更改；如登记有误请作废后重新登记。", "warning")
        return redirect(url_for("issuance.view", iss_id=iss_id))

    types = [t for t in request.form.getlist("cert_types") if t.strip()]
    invalid = [t for t in types if t not in CERT_NO_FIELD]
    if invalid:
        flash(f"无效的证件种类代码：{'、'.join(invalid)}。", "danger")
        return redirect(url_for("issuance.view", iss_id=iss_id))
    if not types:
        flash("请选择证件种类。", "danger")
        return redirect(url_for("issuance.view", iss_id=iss_id))
    if len(types) > 1:
        # 与新建同一条规则：一次出国申请只领一本证
        flash("一次出国申请只能领用一本证件。", "danger")
        return redirect(url_for("issuance.view", iss_id=iss_id))

    before = row_snapshot("cert_issuance", iss_id)
    db = get_db()
    # 备注里「待核实 / 按护照推定」这类字样已经不成立，一并清掉；人工核定的结果
    # 不该继续挂着机器推断的说明。
    remarks = "历史数据回填（证件种类已人工核定，无签名）" \
        if (row["remarks"] or "").startswith("历史数据回填") else row["remarks"]
    db.execute(
        "UPDATE cert_issuance SET cert_types=?, remarks=?, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=?", (",".join(types), remarks, iss_id))
    db.commit()
    log_action("update", "cert_issuance", iss_id,
               detail=f"更正证件种类：{row['holder_name']}，"
                      f"{_types_label(row['cert_types'])} → {_types_label(','.join(types))}",
               before=before, after=row_snapshot("cert_issuance", iss_id))
    flash("证件种类已更正。", "success")
    return redirect(url_for("issuance.view", iss_id=iss_id))


# ---------------------------------------------------------------------------
# 签名图片服务
# ---------------------------------------------------------------------------
@issuance_bp.route("/issuance/<int:iss_id>/signature.png")
@login_required
def signature(iss_id) -> ResponseReturnValue:
    kind = request.args.get("kind", "issue")
    col = "return_sign_image" if kind == "return" else "sign_image"
    db = get_db()
    row = db.execute(f"SELECT {col} AS img FROM cert_issuance WHERE id = ?", (iss_id,)).fetchone()
    if not row or not row["img"]:
        abort(404)
    resp = Response(bytes(row["img"]), mimetype="image/png")
    # 签名一经保存不可变，可长期缓存
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _get_or_404(iss_id):
    db = get_db()
    row = db.execute(
        "SELECT i.*, pf.work_unit FROM cert_issuance i "
        "JOIN personnel_filing pf ON i.personnel_filing_id = pf.id WHERE i.id = ?",
        (iss_id,)).fetchone()
    if not row:
        abort(404)
    return row


def _travel_brief(travel_id):
    """取出行记录摘要（用于带入与展示）。"""
    if not travel_id:
        return None
    db = get_db()
    return db.execute(
        "SELECT id, personnel_filing_id, name, id_number, unit, department, "
        "destination_passport, travel_dates, approval_date, passport_no "
        "FROM travel_details WHERE id = ?", (travel_id,)).fetchone()


def open_issuance_travel_ids() -> set:
    """还挂着未归还领用记录的出国申请 id。

    同一申请下不允许两本证同时在外——一次申请一本证。「领用 → 归还 → 再领用」
    仍然可以，因为已归还的记录不在此列。
    """
    return {r[0] for r in get_db().execute(
        "SELECT DISTINCT travel_id FROM cert_issuance "
        "WHERE status = 'issued' AND travel_id IS NOT NULL").fetchall()}


def issuance_block_reasons() -> dict:
    """出国申请 id → 「为什么现在不能办领用」。不在这个字典里的就是能办的。

    判据只此一处，四个调用点共用：领用挑单页（_eligible_travels）、出国申请
    列表上那个按钮给不给点、领用登记的后端校验、以及提示文案本身。
    此前这三处各管一段，于是漏得五花八门——按钮灰了 POST 却照样过，
    挑单页排除了取消行程却没排除已撤控。

    四类都不能办：

    1. 行程已取消——不会再出行，没有领用的理由；
    2. 已有一条未归还的领用记录——一次申请一本证，办完归还才能再领；
    3. **行程已经结束**（实际回国日期已填）。这一条是补上的：原判据只看
       前两项，于是一条 3 月就走完、证也已归还的申请，9 月还能凭它再领一本
       护照出去——实测复现。「领用 → 归还 → 再领用」的设计本意是同一趟行程
       中途的反复，不是行程结束之后；
    4. **申请人已撤控**。撤控以证件收缴移交完毕为前提（见 decontrol._unsettled_certs），
       人都不在管理范围内了，系统却还允许给他办领用——同样是补上的。

    返回原因串而不是一个 id 集合：按钮的提示文案要说清楚为什么点不了，
    「办不了」和「为什么办不了」得是同一份判断的两个输出，各写一套就会出现
    「提示说行程已取消、实际是因为已有未归还记录」这种更难查的错。
    """
    reasons = {}
    # 顺带取出那条未归还记录的编号：「挡下要给明细」——只说「已有未归还记录」，
    # 经办人还得自己去翻是哪一张。
    open_iss = {r["travel_id"]: r["iss_id"] for r in get_db().execute(
        "SELECT travel_id, MIN(id) AS iss_id FROM cert_issuance "
        "WHERE status = 'issued' AND travel_id IS NOT NULL GROUP BY travel_id").fetchall()}
    for r in get_db().execute(
            "SELECT t.id, COALESCE(t.trip_status,'normal') AS st, t.actual_return_date, "
            "       pf.status AS filing_status "
            "FROM travel_details t "
            "LEFT JOIN personnel_filing pf ON pf.id = t.personnel_filing_id").fetchall():
        # 顺序即优先级：先说最根本的那个原因，一条申请可能同时命中好几项
        if r["filing_status"] != "active":
            reasons[r["id"]] = "申请人已撤控，不再办理证件领用"
        elif r["st"] == "cancelled":
            reasons[r["id"]] = "行程已取消，不再办理证件领用"
        elif (r["actual_return_date"] or "").strip():
            reasons[r["id"]] = (
                f"行程已结束（实际回国 {r['actual_return_date']}），不再办理证件领用；"
                "如需再次出行，请另建出国申请")
        elif r["id"] in open_iss:
            reasons[r["id"]] = (f"已有未归还的领用记录（#{open_iss[r['id']]}），"
                                "请先办理归还或作废")
    return reasons


def _eligible_travels():
    """可以办理领用的出国申请——判据见 issuance_block_reasons。"""
    blocked = issuance_block_reasons()
    rows = get_db().execute(
        "SELECT t.id, t.name, t.unit, t.destination_passport, t.travel_dates, "
        "       t.approval_date, t.need_new_passport "
        "FROM travel_details t ORDER BY t.created_at DESC").fetchall()
    return [r for r in rows if r["id"] not in blocked]


def _types_label(codes: str) -> str:
    """'01,02' → '普通护照、往来港澳通行证'；空值 → '待核实'。

    空值只可能来自历史回填里判不出种类的那批。打印件与日志上不能是个空格子——
    看的人分不清是「没有证件」还是「漏填了」，写明待核实才是实情。
    """
    out = []
    for c in (codes or "").split(","):
        c = c.strip()
        if c:
            out.append(get_dict_value("cert_type", c) or c)
    return "、".join(out) if out else "待核实"


def _sync_travel_derived(travel_id) -> None:
    """把领用/归还日期与证件号码回写到出行表（派生字段，本模块为唯一写入方）。

    日期：取该出行下**未作废**记录中最早的领用日期与最晚的归还日期；
    若全部作废或无记录，则清空，使逾期告警口径与领用记录始终一致。

    证件号码：一次申请一本证，所以该出行下所有未作废记录说的都是同一本；
    取最后一条的号码。号码原先是出行表单上手填的，与领用记录各写各的，
    打印件上「证件号码」和「证件领用日期」两个格子可能来自不同的证件。
    现在跟日期一样降级为派生——有领用记录就以领用记录为准。

    **不清空**号码：路径B（做证）没有领用记录，那一栏是系统里唯一的来源，
    手填的值必须保留；领用记录全部作废时也保留，那仍是当时用的号码。
    """
    if not travel_id:
        return
    db = get_db()
    agg = db.execute(
        "SELECT MIN(issue_date) AS c, "
        "       CASE WHEN COUNT(*) = SUM(CASE WHEN return_date IS NOT NULL AND return_date != '' "
        "                                     THEN 1 ELSE 0 END) "
        "            THEN MAX(return_date) ELSE NULL END AS r "
        "FROM cert_issuance WHERE travel_id = ? AND status != 'voided'",
        (travel_id,)).fetchone()
    collect = (agg["c"] if agg else None) or None
    ret = (agg["r"] if agg else None) or None
    db.execute(
        "UPDATE travel_details SET passport_collect_date=?, passport_return_date=? WHERE id=?",
        (collect, ret, travel_id))
    nos = db.execute(
        "SELECT cert_nos FROM cert_issuance WHERE travel_id = ? AND status != 'voided' "
        "  AND cert_nos IS NOT NULL AND cert_nos != '' ORDER BY id DESC LIMIT 1",
        (travel_id,)).fetchone()
    if nos:
        db.execute("UPDATE travel_details SET passport_no=? WHERE id=?", (nos["cert_nos"], travel_id))
    db.commit()


def travel_has_issuance(travel_id) -> bool:
    """该出行是否已有未作废的领用记录——有的话证件号码由领用记录派生，表单只读。"""
    if not travel_id:
        return False
    return get_db().execute(
        "SELECT 1 FROM cert_issuance WHERE travel_id = ? AND status != 'voided' LIMIT 1",
        (travel_id,)).fetchone() is not None


def _extract_form(form):
    types = [t for t in form.getlist("cert_types") if t.strip()]
    return {
        "travel_id": form.get("travel_id", "").strip(),
        "personnel_filing_id": form.get("personnel_filing_id", "").strip(),
        "holder_name": form.get("holder_name", "").strip(),
        "id_number": form.get("id_number", "").strip(),
        "cert_types": ",".join(types),
        "cert_nos": form.get("cert_nos", "").strip(),
        "issue_date": parse_date_input(form.get("issue_date", "")),
        "issuer": operator_name(),
        "remarks": form.get("remarks", "").strip(),
        "operator": operator_name(),
    }


def _validate_form(data: dict) -> list[str]:
    errors = check_required(data, [
        # 领用必须挂在一条出国申请上：证件是为某一次已批准的出行借出的，
        # 没有申请就没有借出的理由。无主的领用记录还会掉出逾期告警——
        # 告警按出行记录来算，挂不上申请的记录没人盯。
        ("travel_id", "关联出国申请"),
        ("personnel_filing_id", "领用人（备案人员）"),
        ("holder_name", "领用人姓名"),
        ("cert_types", "领用证件种类"),
        ("issue_date", "领用日期"),
    ])
    errors += check_dates(data, [("issue_date", "领用日期")])

    # 证件种类必须是字典内的合法代码。一次申请一本证，所以只能有一个。
    codes = [c for c in (data.get("cert_types") or "").split(",") if c]
    for c in codes:
        if c not in CERT_NO_FIELD:
            errors.append(f"无效的证件种类代码：{c}。")
    if len(codes) > 1:
        errors.append("一次出国申请只能领用一本证件；需要多本请分别提交出国申请。")

    if data.get("travel_id"):
        db = get_db()
        tv = db.execute(
            "SELECT personnel_filing_id, trip_status FROM travel_details WHERE id = ?",
            (data["travel_id"],)).fetchone()
        if not tv:
            errors.append("关联的出国申请不存在。")
        else:
            # 领用人必须就是申请人——证是为这条申请借的，不能借给别人
            if str(tv["personnel_filing_id"]) != str(data.get("personnel_filing_id") or ""):
                errors.append("领用人与该出国申请的申请人不一致。")
        # 这条申请此刻能不能办领用——与列表按钮、挑单页同一个判据。
        #
        # 后端这一关不能省：按钮灰掉只是不给入口，伪造的 POST 想提交什么提交什么。
        # 此前这里只挡「行程已取消」和「同一申请已有未归还记录」两项，于是一条
        # 已经走完、证也已归还的申请照样能被 POST 出一张新领用单——实测复现。
        reason = issuance_block_reasons().get(int(data["travel_id"])) \
            if str(data["travel_id"]).isdigit() else None
        if reason:
            errors.append(f"该出国申请不能办理证件领用：{reason}。")

    # 一本证同时只能在一个人手上——号码级的跨申请查重。
    #
    # 上面那条只查同一条出行（travel_id = ?），拦不住「这本证已经因为另一条
    # 申请借出去了、还没还回来」。实体证只有一本，两张都签了字的未归还领用单
    # 同时指向它时：
    #   - 归还时该销哪一张？作废其中一张，另一张继续挂着「未归还」；
    #   - 领用列表 ?status=issued 显示两行，首页「借出未还（本）」只算一本
    #     （lent_out_numbers 返回的是号码集合，天然去重），数字与列表当场对不上。
    # 恒等式「在库 + 借出未还 = 台账总本数」倒是没被打破，破的是领用单与实体
    # 证件的一一对应——而领用单上有本人手写签名，是这套系统的凭证。
    #
    # 只看 status='issued'：已归还、已作废的都不算占用，同一本证还回来之后
    # 再借给同一个人或别人，都是正常业务，不能拦。
    no = (data.get("cert_nos") or "").strip()
    if no:
        held = get_db().execute(
            "SELECT id, holder_name, travel_id FROM cert_issuance "
            "WHERE cert_nos = ? AND status = 'issued' LIMIT 1", (no,)).fetchone()
        if held:
            errors.append(
                f"证件号码 {no} 已由 {held['holder_name']} 领用且尚未归还"
                f"（领用记录 #{held['id']}，出国申请 #{held['travel_id']}）。"
                "一本证件同时只能在一个人手上，请先办理该记录的归还或作废。")
    return errors

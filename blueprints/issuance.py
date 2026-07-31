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
from database import get_db
from utils.helpers import log_action, list_all, row_snapshot, get_dict_value
from utils.validators import parse_date_input, check_required, check_dates

issuance_bp = Blueprint("issuance", __name__)

# 证件种类代码 → certificates 表中对应的号码字段
CERT_NO_FIELD = {
    "01": "passport_no",
    "02": "hm_pass_no",
    "03": "tw_pass_no",
}

# PNG 魔数（防止前端传入非图片内容）
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# 单张签名上限：正常裁剪后 5–20KB，留足余量仍可拦住异常大图
MAX_SIGN_BYTES = 512 * 1024
MAX_META_CHARS = 400_000


# ---------------------------------------------------------------------------
# 签名解析
# ---------------------------------------------------------------------------
def _decode_signature(png_data_url: str) -> tuple[bytes | None, str]:
    """dataURL → PNG bytes。返回 (bytes, 错误信息)；失败时 bytes 为 None。"""
    raw = (png_data_url or "").strip()
    if not raw:
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
    if cert_type:
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
        _sync_travel_dates(data["travel_id"])
        log_action("create", "cert_issuance", iss_id,
                   detail=f"证件领用登记：{data['holder_name']}，{_types_label(data['cert_types'])}",
                   after=row_snapshot("cert_issuance", iss_id))
        flash("证件领用登记已保存。", "success")
        return redirect(url_for("issuance.view", iss_id=iss_id))

    # GET：支持从出行记录跳转带入
    travel_id = request.args.get("travel_id", type=int)
    prefill: dict = {"issue_date": datetime.now().strftime("%Y%m%d")}
    travel = _travel_brief(travel_id)
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
                           type_labels=_types_label(row["cert_types"]))


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
             session.get("username", "admin"), iss_id),
        )
        db.commit()
        _sync_travel_dates(row["travel_id"])
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
    _sync_travel_dates(row["travel_id"])
    log_action("void", "cert_issuance", iss_id,
               detail=f"领用记录作废：{row['holder_name']}，原因：{reason}",
               before=before, after=row_snapshot("cert_issuance", iss_id))
    flash("领用记录已作废，如需更正请重新登记。", "info")
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


def _types_label(codes: str) -> str:
    """'01,02' → '因私护照、往来港澳通行证'"""
    out = []
    for c in (codes or "").split(","):
        c = c.strip()
        if c:
            out.append(get_dict_value("cert_type", c) or c)
    return "、".join(out)


def _sync_travel_dates(travel_id) -> None:
    """把领用/归还日期回写到出行表（派生字段，本模块为唯一写入方）。

    取该出行下**未作废**记录中最早的领用日期与最晚的归还日期；
    若全部作废或无记录，则清空，使逾期告警口径与领用记录始终一致。
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
    db.commit()


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
        "issuer": form.get("issuer", "").strip() or session.get("username", "admin"),
        "remarks": form.get("remarks", "").strip(),
        "operator": session.get("username", "admin"),
    }


def _validate_form(data: dict) -> list[str]:
    errors = check_required(data, [
        ("personnel_filing_id", "领用人（备案人员）"),
        ("holder_name", "领用人姓名"),
        ("cert_types", "领用证件种类"),
        ("issue_date", "领用日期"),
    ])
    errors += check_dates(data, [("issue_date", "领用日期")])

    # 证件种类必须是字典内的合法代码
    for c in (data.get("cert_types") or "").split(","):
        if c and c not in CERT_NO_FIELD:
            errors.append(f"无效的证件种类代码：{c}。")

    # 同一出行下不允许重复的未归还领用记录
    if data.get("travel_id"):
        db = get_db()
        dup = db.execute(
            "SELECT id FROM cert_issuance WHERE travel_id = ? AND status = 'issued'",
            (data["travel_id"],)).fetchone()
        if dup:
            errors.append(f"该出行记录已有未归还的领用记录（#{dup['id']}），请先办理归还或作废。")
    return errors

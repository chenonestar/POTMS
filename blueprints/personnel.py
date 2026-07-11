"""人员备案蓝图 — 信息登记表 + 登记备案表"""
from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db
from utils.helpers import (
    get_dict_options, get_dict_value, log_action, list_all,
    detect_surname_split, normalize_residence, row_snapshot,
)
from utils.validators import (
    parse_date_input, is_party_member,
    check_required, check_dates, check_identity,
)

personnel_bp = Blueprint("personnel", __name__)


# =========================================================================
# 列表页
# =========================================================================
def build_filters(args, ids=None):
    """构建人员备案列表的 WHERE 子句（pf/pi 别名），供列表与导出复用。"""
    where = ""
    params: list = []
    search = args.get("search", "").strip()
    if search:
        where += " AND (pf.surname||pf.given_name LIKE ? OR pf.id_number LIKE ? OR pf.work_unit LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    if args.get("status", "").strip():
        where += " AND pf.status = ?"
        params.append(args.get("status").strip())
    if args.get("political_status", "").strip():
        where += " AND pf.political_status = ?"
        params.append(args.get("political_status").strip())
    if args.get("rank", "").strip():
        where += " AND pi.rank = ?"
        params.append(args.get("rank").strip())
    if args.get("gender", "").strip():
        where += " AND pf.gender = ?"
        params.append(args.get("gender").strip())
    if args.get("tag", "").strip():
        where += " AND pf.tag = ?"
        params.append(args.get("tag").strip())
    if args.get("residence", "").strip():
        where += " AND pf.residence LIKE ?"
        params.append(f"%{args.get('residence').strip()}%")
    if ids:
        ph = ",".join("?" for _ in ids)
        where += f" AND pf.id IN ({ph})"
        params.extend(ids)
    return where, tuple(params)


@personnel_bp.route("/personnel/")
@login_required
def list() -> ResponseReturnValue:
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "").strip()
    political_filter = request.args.get("political_status", "").strip()
    rank_filter = request.args.get("rank", "").strip()
    gender_filter = request.args.get("gender", "").strip()
    tag_filter = request.args.get("tag", "").strip()
    residence_filter = request.args.get("residence", "").strip()
    sort_by = request.args.get("sort", "created_at_desc").strip()

    where, params = build_filters(request.args)
    base = (
        "SELECT pf.id, pf.surname, pf.given_name, pf.gender, pf.birth_date, "
        "pf.id_number, pf.work_unit, pf.position_or_title, pf.tag, pf.status, "
        "pf.created_at, pi.id AS info_id "
        "FROM personnel_filing pf "
        "LEFT JOIN personnel_info pi ON pf.personnel_info_id = pi.id "
        "WHERE 1=1" + where
    )

    # 排序
    sort_map = {
        "created_at_desc": "pf.created_at DESC",
        "created_at_asc": "pf.created_at ASC",
        "name_asc": "pf.surname||pf.given_name ASC",
        "birth_date_asc": "pf.birth_date ASC",
    }
    base += f" ORDER BY {sort_map.get(sort_by, 'pf.created_at DESC')}"

    pg = list_all(base, params)  # 全量下发，前端按视口窗口化分页

    return render_template(
        "personnel/list.html",
        items=pg,
        search=search,
        status_filter=status_filter,
        political_filter=political_filter,
        rank_filter=rank_filter,
        gender_filter=gender_filter,
        tag_filter=tag_filter,
        residence_filter=residence_filter,
        sort_by=sort_by,
        statuses=[{"code": "active", "value": "有效"}, {"code": "decontrolled", "value": "已撤控"}],
        political_opts=get_dict_options("political_status"),
        rank_opts=get_dict_options("rank"),
        tags=[{"code": "新增", "value": "新增"}, {"code": "更新", "value": "更新"}],
        genders=[{"code": "男", "value": "男"}, {"code": "女", "value": "女"}],
        sorts=[
            {"code": "created_at_desc", "value": "录入时间（新→旧）"},
            {"code": "created_at_asc", "value": "录入时间（旧→新）"},
            {"code": "name_asc", "value": "姓名排序"},
            {"code": "birth_date_asc", "value": "出生日期"},
        ],
    )


# =========================================================================
# 信息登记表 — 新增
# =========================================================================
@personnel_bp.route("/personnel/info/new", methods=["GET", "POST"])
@login_required
def info_new() -> ResponseReturnValue:
    if request.method == "POST":
        data = _extract_info_form(request.form)
        errors = _validate_info_form(data)
        # #5 防重复：同一身份证号已存在信息登记表则拦截（避免产生同号孤儿行；
        # 如需修改请直接编辑原记录）
        if not errors and data["id_number"]:
            dup = get_db().execute(
                "SELECT id FROM personnel_info WHERE id_number = ? LIMIT 1",
                (data["id_number"],),
            ).fetchone()
            if dup:
                errors.append(
                    f"该身份证号已存在信息登记表（编号 {dup['id']}），"
                    "如需修改请直接编辑该记录，请勿重复录入。"
                )
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("personnel/info_form.html", data=data, editing=False)

        db = get_db()
        db.execute(
            "INSERT INTO personnel_info (unit, department, name, gender, birth_date, "
            "id_number, work_start_date, education, degree, title, rank, political_status, "
            "party_join_date, position, operator) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["unit"], data["department"], data["name"], data["gender"],
                data["birth_date"], data["id_number"], data["work_start_date"], data["education"],
                data["degree"], data["title"], data["rank"], data["political_status"],
                data["party_join_date"], data["position"], data["operator"],
            ),
        )
        db.commit()
        info_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        log_action("create", "personnel_info", info_id, after=row_snapshot("personnel_info", info_id))
        flash("备案人员信息登记表已保存。请继续填写登记备案表。", "success")
        return redirect(url_for("personnel.filing_new", info_id=info_id))

    return render_template("personnel/info_form.html", data={}, editing=False)


# =========================================================================
# 信息登记表 — 编辑
# =========================================================================
@personnel_bp.route("/personnel/info/<int:info_id>/edit", methods=["GET", "POST"])
@login_required
def info_edit(info_id) -> ResponseReturnValue:
    db = get_db()
    row = db.execute("SELECT * FROM personnel_info WHERE id = ?", (info_id,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("personnel.list"))

    if request.method == "POST":
        data = _extract_info_form(request.form)
        errors = _validate_info_form(data)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("personnel/info_form.html", data=data, editing=True, info_id=info_id)

        before = row_snapshot("personnel_info", info_id)
        db.execute(
            "UPDATE personnel_info SET unit=?, department=?, name=?, gender=?, "
            "birth_date=?, id_number=?, work_start_date=?, education=?, degree=?, title=?, rank=?, "
            "political_status=?, party_join_date=?, position=?, operator=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (
                data["unit"], data["department"], data["name"], data["gender"],
                data["birth_date"], data["id_number"], data["work_start_date"], data["education"],
                data["degree"], data["title"], data["rank"], data["political_status"],
                data["party_join_date"], data["position"], data["operator"], info_id,
            ),
        )
        db.commit()
        log_action("update", "personnel_info", info_id,
                   before=before, after=row_snapshot("personnel_info", info_id))
        flash("信息登记表已更新。", "success")
        return redirect(url_for("personnel.list"))

    return render_template(
        "personnel/info_form.html",
        data=dict(row),
        editing=True,
        info_id=info_id,
    )


# =========================================================================
# 登记备案表 — 新增
# =========================================================================
@personnel_bp.route("/personnel/filing/new", methods=["GET", "POST"])
@login_required
def filing_new() -> ResponseReturnValue:
    info_id = request.args.get("info_id", type=int)
    info_row = None
    if info_id:
        db = get_db()
        info_row = db.execute("SELECT * FROM personnel_info WHERE id = ?", (info_id,)).fetchone()

    if request.method == "POST":
        data = _extract_filing_form(request.form)
        errors = _validate_filing_form(data)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "personnel/filing_form.html",
                data=data, editing=False, info_id=info_id,
            )

        db = get_db()
        db.execute(
            "INSERT INTO personnel_filing (personnel_info_id, surname, given_name, gender, "
            "birth_date, id_number, residence, political_status, work_unit, "
            "position_or_title, supervisor_unit, tag, informed, remarks, operator) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                info_id, data["surname"], data["given_name"], data["gender"],
                data["birth_date"], data["id_number"], data["residence"],
                data["political_status"], data["work_unit"], data["position_or_title"],
                data["supervisor_unit"], data["tag"], data["informed"],
                data.get("remarks", ""), data["operator"],
            ),
        )
        db.commit()
        filing_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 撤控重报关联：若存在同一身份证的已撤控旧记录，建立新旧关联并标记为"更新"
        prior = db.execute(
            "SELECT id FROM personnel_filing WHERE id_number = ? AND status = 'decontrolled' "
            "AND replaced_by_id IS NULL AND id != ? ORDER BY id DESC LIMIT 1",
            (data["id_number"], filing_id),
        ).fetchone()
        if prior:
            db.execute("UPDATE personnel_filing SET replaced_by_id = ? WHERE id = ?", (filing_id, prior["id"]))
            db.execute("UPDATE personnel_filing SET tag = '更新' WHERE id = ?", (filing_id,))
            db.commit()
            flash(f"已与原撤控记录（#{prior['id']}）建立关联，本记录标记为“更新”。", "info")

        log_action("create", "personnel_filing", filing_id, after=row_snapshot("personnel_filing", filing_id))
        flash("登记备案表已保存。", "success")
        return redirect(url_for("personnel.list"))

    # GET — 预填信息登记表数据
    prefill = {}
    if info_row:
        surname, given_name = detect_surname_split(info_row["name"])
        prefill = {
            "surname": surname,
            "given_name": given_name,
            "gender": info_row["gender"],
            "birth_date": info_row["birth_date"],
            "id_number": info_row["id_number"] or "",
            "political_status": info_row["political_status"],
            "work_unit": info_row["unit"],
            "position_or_title": info_row["position"] or info_row["rank"],
        }

    return render_template(
        "personnel/filing_form.html",
        data=prefill,
        editing=False,
        info_id=info_id,
    )


# =========================================================================
# 登记备案表 — 编辑
# =========================================================================
@personnel_bp.route("/personnel/filing/<int:filing_id>/edit", methods=["GET", "POST"])
@login_required
def filing_edit(filing_id) -> ResponseReturnValue:
    db = get_db()
    row = db.execute("SELECT * FROM personnel_filing WHERE id = ?", (filing_id,)).fetchone()
    if not row:
        flash("记录不存在。", "danger")
        return redirect(url_for("personnel.list"))

    if request.method == "POST":
        data = _extract_filing_form(request.form)
        errors = _validate_filing_form(data, skip_id_dup_check=True)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "personnel/filing_form.html",
                data=data, editing=True, filing_id=filing_id,
            )

        before = row_snapshot("personnel_filing", filing_id)
        db.execute(
            "UPDATE personnel_filing SET surname=?, given_name=?, gender=?, birth_date=?, "
            "id_number=?, residence=?, political_status=?, work_unit=?, "
            "position_or_title=?, supervisor_unit=?, tag=?, informed=?, remarks=?, "
            "operator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                data["surname"], data["given_name"], data["gender"],
                data["birth_date"], data["id_number"], data["residence"],
                data["political_status"], data["work_unit"], data["position_or_title"],
                data["supervisor_unit"], data["tag"], data["informed"],
                data.get("remarks", ""), data["operator"], filing_id,
            ),
        )
        db.commit()
        log_action("update", "personnel_filing", filing_id,
                   before=before, after=row_snapshot("personnel_filing", filing_id))
        flash("登记备案表已更新。", "success")
        return redirect(url_for("personnel.list"))

    return render_template(
        "personnel/filing_form.html",
        data=dict(row),
        editing=True,
        filing_id=filing_id,
    )


# =========================================================================
# 查看详情
# =========================================================================
@personnel_bp.route("/personnel/<int:filing_id>")
@login_required
def view(filing_id) -> ResponseReturnValue:
    db = get_db()
    filing = db.execute(
        "SELECT * FROM personnel_filing WHERE id = ?", (filing_id,)
    ).fetchone()
    if not filing:
        flash("记录不存在。", "danger")
        return redirect(url_for("personnel.list"))

    info_row = None
    if filing["personnel_info_id"]:
        info_row = db.execute(
            "SELECT * FROM personnel_info WHERE id = ?",
            (filing["personnel_info_id"],),
        ).fetchone()

    # 撤控重报关联链路
    successor = None  # 本（旧）记录被哪条新记录替代
    if filing["replaced_by_id"]:
        successor = db.execute(
            "SELECT id, surname, given_name, created_at FROM personnel_filing WHERE id = ?",
            (filing["replaced_by_id"],),
        ).fetchone()
    predecessor = db.execute(  # 本记录替代了哪条旧记录（即本记录为重报）
        "SELECT id, surname, given_name, created_at FROM personnel_filing WHERE replaced_by_id = ?",
        (filing_id,),
    ).fetchone()

    return render_template(
        "personnel/view.html",
        filing=filing,
        info=info_row,
        successor=successor,
        predecessor=predecessor,
    )


# =========================================================================
# 删除
# =========================================================================
@personnel_bp.route("/personnel/<int:filing_id>/delete", methods=["POST"])
@login_required
def delete(filing_id) -> ResponseReturnValue:
    db = get_db()
    if not db.execute("SELECT id FROM personnel_filing WHERE id = ?", (filing_id,)).fetchone():
        flash("记录不存在。", "danger")
        return redirect(url_for("personnel.list"))
    # #3 删除前拦截：名下若有证照/出国明细/撤控记录（均 NOT NULL 外键引用本表），
    # 直接 DELETE 会因外键约束静默失败，故先检查并给出明确提示。
    cert_cnt = db.execute(
        "SELECT COUNT(*) FROM certificates WHERE personnel_filing_id = ?", (filing_id,)
    ).fetchone()[0]
    travel_cnt = db.execute(
        "SELECT COUNT(*) FROM travel_details WHERE personnel_filing_id = ?", (filing_id,)
    ).fetchone()[0]
    dec_cnt = db.execute(
        "SELECT COUNT(*) FROM decontrol_filing WHERE personnel_filing_id = ?", (filing_id,)
    ).fetchone()[0]
    if cert_cnt or travel_cnt or dec_cnt:
        flash(
            f"该人员名下尚有证照 {cert_cnt} 条、出国明细 {travel_cnt} 条、撤控记录 {dec_cnt} 条，"
            "请先删除或处理这些关联记录后再删除备案。",
            "danger",
        )
        return redirect(url_for("personnel.list"))
    before = row_snapshot("personnel_filing", filing_id)
    db.execute("DELETE FROM personnel_filing WHERE id = ?", (filing_id,))
    db.commit()
    log_action("delete", "personnel_filing", filing_id, before=before)
    flash("备案记录已删除。", "info")
    return redirect(url_for("personnel.list"))


# =========================================================================
# 信息登记表 — 管理（一览 / 删除孤儿）
# =========================================================================
@personnel_bp.route("/personnel/info/")
@login_required
def info_list() -> ResponseReturnValue:
    """列出信息登记表（含关联备案数、搜索/筛选/分页），供清理孤儿记录。"""
    args = request.args
    where = ""
    params: list = []
    search = args.get("search", "").strip()
    if search:
        where += " AND (pi.name LIKE ? OR pi.id_number LIKE ? OR pi.unit LIKE ? OR pi.department LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like, like]
    ref_count = "(SELECT COUNT(*) FROM personnel_filing pf WHERE pf.personnel_info_id = pi.id)"
    ref = args.get("ref", "").strip()
    if ref == "orphan":
        where += f" AND {ref_count} = 0"
    elif ref == "linked":
        where += f" AND {ref_count} > 0"
    sql = (f"SELECT pi.*, {ref_count} AS filing_count "
           f"FROM personnel_info pi WHERE 1=1{where} ORDER BY pi.id")
    items = list_all(sql, params)  # 全量下发，前端按视口窗口化分页
    return render_template("personnel/info_list.html", items=items, search=search, ref=ref)


@personnel_bp.route("/personnel/info/<int:info_id>/delete", methods=["POST"])
@login_required
def info_delete(info_id) -> ResponseReturnValue:
    """#2 物理删除信息登记表：仅当无任何备案记录引用时才允许，防止悬空外键。"""
    db = get_db()
    if not db.execute("SELECT id FROM personnel_info WHERE id = ?", (info_id,)).fetchone():
        flash("记录不存在。", "danger")
        return redirect(url_for("personnel.info_list"))
    ref = db.execute(
        "SELECT COUNT(*) FROM personnel_filing WHERE personnel_info_id = ?", (info_id,)
    ).fetchone()[0]
    if ref:
        flash(f"该信息登记表已被 {ref} 条备案记录引用，不能删除。请先删除相关备案记录。", "danger")
        return redirect(url_for("personnel.info_list"))
    before = row_snapshot("personnel_info", info_id)
    db.execute("DELETE FROM personnel_info WHERE id = ?", (info_id,))
    db.commit()
    log_action("delete", "personnel_info", info_id, before=before)
    flash("信息登记表已删除。", "info")
    return redirect(url_for("personnel.info_list"))


# =========================================================================
# 表单提取 & 校验
# =========================================================================
def _extract_info_form(form):
    """从 POST 数据提取信息登记表字段"""
    return {
        "unit": form.get("unit", "").strip(),
        "department": form.get("department", "").strip(),
        "name": form.get("name", "").strip(),
        "gender": form.get("gender", "").strip(),
        "birth_date": parse_date_input(form.get("birth_date", "")),
        "id_number": form.get("id_number", "").strip().upper(),
        "work_start_date": parse_date_input(form.get("work_start_date", "")),
        "education": form.get("education", "").strip(),
        "degree": form.get("degree", "").strip(),
        "title": form.get("title", "").strip(),
        "rank": form.get("rank", "").strip(),
        "political_status": form.get("political_status", "").strip(),
        "party_join_date": parse_date_input(form.get("party_join_date", "")),
        "position": form.get("position", "").strip(),
        "operator": session.get("username", "admin"),
    }


def _validate_info_form(data: dict) -> list[str]:
    errors = []
    required = [
        ("unit", "单位"), ("department", "部门"), ("name", "姓名"),
        ("gender", "性别"), ("birth_date", "出生日期"), ("id_number", "身份证号"),
        ("work_start_date", "参加工作日期"),
        ("education", "学历"), ("degree", "学位"), ("title", "职称"),
        ("rank", "职级"), ("political_status", "政治面貌"),
        ("position", "职务（岗位名称）"),
    ]
    errors += check_required(data, required)
    errors += check_dates(data, [
        ("birth_date", "出生日期"),
        ("work_start_date", "参加工作日期"),
        ("party_join_date", "入党日期"),
    ])
    errors += check_identity(data)

    if is_party_member(data["political_status"]) and not data["party_join_date"]:
        errors.append("中共党员/预备党员须填写入党日期。")

    return errors


def _extract_filing_form(form):
    return {
        "surname": form.get("surname", "").strip(),
        "given_name": form.get("given_name", "").strip(),
        "gender": form.get("gender", "").strip(),
        "birth_date": parse_date_input(form.get("birth_date", "")),
        "id_number": form.get("id_number", "").strip().upper(),
        "residence": normalize_residence(form.get("residence", "")),
        "political_status": form.get("political_status", "").strip(),
        "work_unit": form.get("work_unit", "").strip(),
        "position_or_title": form.get("position_or_title", "").strip(),
        "supervisor_unit": form.get("supervisor_unit", "").strip(),
        "tag": form.get("tag", "新增").strip(),
        "informed": form.get("informed", "否").strip(),
        "remarks": form.get("remarks", "").strip(),
        "operator": session.get("username", "admin"),
    }


def _validate_filing_form(data: dict, skip_id_dup_check: bool = False) -> list[str]:
    errors = []
    required = [
        ("surname", "中文姓"), ("given_name", "中文名"), ("gender", "性别"),
        ("birth_date", "出生日期"), ("id_number", "身份证号"),
        ("residence", "户口所在地"), ("political_status", "政治面貌"),
        ("work_unit", "工作单位"), ("position_or_title", "职务（级）或职称"),
        ("supervisor_unit", "人事主管单位"), ("tag", "标记"),
        ("informed", "已告知本人"),
    ]
    errors += check_required(data, required)
    errors += check_dates(data, [("birth_date", "出生日期")])
    errors += check_identity(data)

    if data["id_number"] and not skip_id_dup_check:
        db = get_db()
        dup = db.execute(
            "SELECT id FROM personnel_filing WHERE id_number = ? AND status = 'active'",
            (data["id_number"],),
        ).fetchone()
        if dup:
            errors.append("该身份证号已存在有效备案记录，请勿重复登记。")

    return errors

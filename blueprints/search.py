"""全局搜索 — 按姓名/身份证/证件号一次搜遍五个业务模块。

领用单是最后补上的一类，而它本该是最先有的：按证件号码搜，搜得到证照台账
（这本证登记在谁名下）、搜得到出国申请（哪次出行用了它），唯独搜不到
**「这本证现在在谁手上」的那张领用单**——而领用单才是这件事的权威来源
（在库/借出未还两档就是按它算的）。保管处最常问的一句「这本证呢」，
以前在全局搜索里恰恰答不上来。
"""
from flask import Blueprint, render_template, request
from flask.typing import ResponseReturnValue

from auth import login_required
from database import get_db

search_bp = Blueprint("search", __name__)

_LIMIT = 50  # 每模块最多展示条数


@search_bp.route("/search")
@login_required
def index() -> ResponseReturnValue:
    q = request.args.get("q", "").strip()
    results = {"personnel": [], "certificate": [], "travel": [],
               "issuance": [], "decontrol": []}
    if q:
        db = get_db()
        like = f"%{q}%"
        results["personnel"] = db.execute(
            "SELECT id, surname, given_name, id_number, work_unit, status "
            "FROM personnel_filing WHERE surname||given_name LIKE ? OR id_number LIKE ? "
            "ORDER BY created_at DESC LIMIT ?", (like, like, _LIMIT)).fetchall()
        results["certificate"] = db.execute(
            "SELECT id, name, unit, passport_no, hm_pass_no, tw_pass_no "
            "FROM certificates WHERE name LIKE ? OR passport_no LIKE ? "
            "OR hm_pass_no LIKE ? OR tw_pass_no LIKE ? "
            "ORDER BY created_at DESC LIMIT ?", (like, like, like, like, _LIMIT)).fetchall()
        results["travel"] = db.execute(
            "SELECT id, name, destination_passport, travel_dates, trip_status "
            "FROM travel_details WHERE name LIKE ? OR destination_passport LIKE ? "
            "OR passport_no LIKE ? ORDER BY created_at DESC LIMIT ?",
            (like, like, like, _LIMIT)).fetchall()
        # 「什么算命中」这条判据不在这里另写：直接借领用模块自己的 build_filters，
        # 与领用列表的搜索框完全同源。各写一套的话，同一个号码在两处搜出不同结果，
        # 而用户没有任何办法知道哪一处是对的。
        #
        # 只借 WHERE，SELECT 列自己写：BASE_SELECT 取的是 i.*，里面有两列手写签名
        # BLOB（PNG），50 行全捞出来只为了列个表，不值当。
        from blueprints.issuance import build_filters as _issuance_filters
        iss_where, iss_params = _issuance_filters({"search": q})
        results["issuance"] = db.execute(
            "SELECT i.id, i.holder_name, i.cert_types, i.cert_nos, i.issue_date, "
            "       i.return_date, i.status, i.travel_id, pf.work_unit "
            "FROM cert_issuance i "
            "JOIN personnel_filing pf ON i.personnel_filing_id = pf.id "
            "WHERE 1=1" + iss_where + " ORDER BY i.issue_date DESC, i.id DESC LIMIT ?",
            (*iss_params, _LIMIT)).fetchall()
        results["decontrol"] = db.execute(
            "SELECT id, surname, given_name, work_unit, reason, decontrol_date "
            "FROM decontrol_filing WHERE surname||given_name LIKE ? OR id_number LIKE ? "
            "OR reason LIKE ? ORDER BY created_at DESC LIMIT ?",
            (like, like, like, _LIMIT)).fetchall()

    total = sum(len(v) for v in results.values())
    from blueprints.issuance import _types_label
    return render_template("search/results.html", q=q, results=results, total=total,
                           types_label=_types_label)

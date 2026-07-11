"""全局搜索 — 按姓名/身份证/证件号一次搜遍四个业务模块"""
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
    results = {"personnel": [], "certificate": [], "travel": [], "decontrol": []}
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
        results["decontrol"] = db.execute(
            "SELECT id, surname, given_name, work_unit, reason, decontrol_date "
            "FROM decontrol_filing WHERE surname||given_name LIKE ? OR id_number LIKE ? "
            "OR reason LIKE ? ORDER BY created_at DESC LIMIT ?",
            (like, like, like, _LIMIT)).fetchall()

    total = sum(len(v) for v in results.values())
    return render_template("search/results.html", q=q, results=results, total=total)

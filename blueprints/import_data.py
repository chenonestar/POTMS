"""批量导入蓝图"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask.typing import ResponseReturnValue

from auth import login_required
from utils.excel_import import parse_import_file, generate_import_template
from utils.helpers import log_action

import_bp = Blueprint("import_data", __name__)


@import_bp.route("/import/", methods=["GET", "POST"])
@login_required
def index() -> ResponseReturnValue:
    result = None
    if request.method == "POST":
        if "file" not in request.files:
            flash("请选择要上传的文件。", "warning")
            return render_template("import/form.html", result=None)

        f = request.files["file"]
        if not f.filename:
            flash("请选择要上传的文件。", "warning")
            return render_template("import/form.html", result=None)

        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ("xlsx", "xls"):
            flash("仅支持 .xlsx 格式的 Excel 文件。", "danger")
            return render_template("import/form.html", result=None)

        try:
            result = parse_import_file(f.stream)
            log_action("import", "batch", detail=f"total={result['total']}, success={result['success']}, errors={len(result['errors'])}")
            if result["success"] > 0:
                flash(f"成功导入 {result['success']} 条记录（共 {result['total']} 条）。", "success")
            if result["errors"]:
                flash(f"{len(result['errors'])} 条记录存在错误，详见下方报告。", "warning")
        except Exception as e:
            flash(f"导入失败: {e}", "danger")

    return render_template("import/form.html", result=result)


@import_bp.route("/import/template")
@login_required
def download_template() -> ResponseReturnValue:
    """下载 Excel 导入模板"""
    buf = generate_import_template()
    return send_file(
        buf,
        as_attachment=True,
        download_name="备案人员导入模板.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

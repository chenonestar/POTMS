"""认证蓝图 — 单用户登录/登出"""
from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from database import get_db

auth_bp = Blueprint("auth", __name__)


def login_required(view):
    """登录校验装饰器"""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            flash("请先登录。", "warning")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("请输入用户名和密码。", "danger")
            return render_template("login.html")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        from utils.security import verify_password, hash_password

        ok, needs_rehash = verify_password(password, user["password_hash"]) if user else (False, False)
        if ok:
            # 旧哈希登录成功后透明升级为 bcrypt
            if needs_rehash:
                db.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(password), user["id"]),
                )
                db.commit()
            session.permanent = True  # 启用 PERMANENT_SESSION_LIFETIME 超时（默认1小时）
            session["logged_in"] = True
            session["username"] = user["username"]
            flash("登录成功。", "success")
            return redirect(url_for("dashboard.index"))

        flash("用户名或密码错误。", "danger")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("已退出登录。", "info")
    return redirect(url_for("auth.login"))

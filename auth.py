"""认证蓝图 — 单用户登录/登出"""
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from flask.typing import ResponseReturnValue

import sqlite3

from database import get_db

auth_bp = Blueprint("auth", __name__)

# ---- 登录防爆破：按来源 IP 记失败次数，连续 5 次失败锁定 10 分钟 ----
# 进程内存级即可（waitress 单进程；重启即清零，不影响正常使用）
_MAX_LOGIN_FAILS = 5
_LOCK_MINUTES = 10
_login_fails: dict = {}  # ip -> {"count": int, "lock_until": datetime|None}


def _fail_state(ip: str) -> dict:
    return _login_fails.setdefault(ip, {"count": 0, "lock_until": None})


def _locked_remaining(ip: str) -> int:
    """若该 IP 处于锁定期，返回剩余秒数；否则返回 0（并顺带解除过期锁定）。"""
    st = _fail_state(ip)
    if st["lock_until"]:
        remain = (st["lock_until"] - datetime.now()).total_seconds()
        if remain > 0:
            return int(remain)
        st["count"] = 0
        st["lock_until"] = None
    return 0


def _record_login_failure(ip: str, username: str) -> None:
    st = _fail_state(ip)
    st["count"] += 1
    if st["count"] >= _MAX_LOGIN_FAILS:
        st["lock_until"] = datetime.now() + timedelta(minutes=_LOCK_MINUTES)
        # 锁定事件写入操作日志（audit trail）
        try:
            from utils.helpers import log_action
            log_action("lock", "users",
                       detail=f"登录连续失败 {st['count']} 次，锁定 {_LOCK_MINUTES} 分钟（尝试用户名: {username}，IP: {ip}）")
        except Exception:
            pass  # 日志失败不影响锁定本身生效


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
def login() -> ResponseReturnValue:
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        ip = request.remote_addr or "unknown"
        remain = _locked_remaining(ip)
        if remain:
            flash(f"登录失败次数过多，已临时锁定，请 {max(1, remain // 60 + 1)} 分钟后再试。", "danger")
            return render_template("login.html")

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
            _login_fails.pop(ip, None)  # 成功登录清零失败计数
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
            # 单据上的经办人取这个；没填姓名时回退到账号，保证字段永不为空
            session["full_name"] = (user["full_name"] or "").strip() or user["username"]
            flash("登录成功。", "success")
            return redirect(url_for("dashboard.index"))

        _record_login_failure(ip, username)
        left = _MAX_LOGIN_FAILS - _fail_state(ip)["count"]
        if left > 0:
            flash(f"用户名或密码错误（再失败 {left} 次将锁定 {_LOCK_MINUTES} 分钟）。", "danger")
        else:
            flash(f"登录失败次数过多，已锁定 {_LOCK_MINUTES} 分钟。", "danger")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout() -> ResponseReturnValue:
    session.clear()
    flash("已退出登录。", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/account", methods=["GET", "POST"])
@login_required
def account() -> ResponseReturnValue:
    """账户设置：修改用户名 / 密码"""
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE username = ?", (session.get("username"),)
    ).fetchone()
    if not user:
        session.clear()
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        from utils.security import verify_password, hash_password
        from utils.helpers import log_action

        current_pw = request.form.get("current_password", "")
        new_username = request.form.get("new_username", "").strip()
        new_full_name = request.form.get("new_full_name", "").strip()
        new_pw = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")

        errors = []
        ok, _ = verify_password(current_pw, user["password_hash"])
        if not ok:
            errors.append("当前密码不正确。")

        change_username = bool(new_username) and new_username != user["username"]
        change_password = bool(new_pw)
        change_full_name = new_full_name != (user["full_name"] or "")

        if not change_username and not change_password and not change_full_name:
            errors.append("未检测到任何修改。")
        if len(new_full_name) > 30:
            errors.append("姓名过长（最多 30 个字符）。")
        if not new_username:
            errors.append("用户名不能为空。")
        elif change_username:
            if len(new_username) < 3:
                errors.append("用户名至少 3 个字符。")
            elif db.execute("SELECT id FROM users WHERE username = ? AND id != ?",
                            (new_username, user["id"])).fetchone():
                errors.append("该用户名已被占用。")
        if change_password:
            if len(new_pw) < 6:
                errors.append("新密码至少 6 个字符。")
            elif new_pw != confirm_pw:
                errors.append("两次输入的新密码不一致。")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("account.html", username=user["username"],
                                   full_name=user["full_name"] or "",
                                   legacy=_legacy_operator_counts(user["username"]))

        if change_username:
            db.execute("UPDATE users SET username = ? WHERE id = ?", (new_username, user["id"]))
        if change_password:
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                       (hash_password(new_pw), user["id"]))
        if change_full_name:
            db.execute("UPDATE users SET full_name = ? WHERE id = ?",
                       (new_full_name or None, user["id"]))
        db.commit()
        log_action("update", "users", user["id"],
                   detail="账户变更：" + "、".join(
                       ([f"用户名→{new_username}"] if change_username else [])
                       + ([f"姓名→{new_full_name or '（清空）'}"] if change_full_name else [])
                       + (["密码"] if change_password else [])))

        # 改密码后为安全起见强制重新登录
        if change_password:
            session.clear()
            flash("密码已修改，请使用新密码重新登录。", "success")
            return redirect(url_for("auth.login"))

        if change_username:
            session["username"] = new_username
        if change_username or change_full_name:
            session["full_name"] = new_full_name or new_username or user["username"]
        flash("账户信息已更新。", "success")
        return redirect(url_for("auth.account"))

    return render_template("account.html", username=user["username"],
                           full_name=user["full_name"] or "",
                           legacy=_legacy_operator_counts(user["username"]))


# ---------------------------------------------------------------------------
# 历史经办人回填
#
# 升级那一刻系统还不知道真实姓名——得先去账户设置填。所以「加列」和「改历史
# 数据」不能是同一步，回填只能等姓名填好之后由用户显式触发。
#
# 刻意做成按钮而不是升级时静默 UPDATE：批量改历史数据不可逆，得让人看清影响
# 条数再点。执行前自动备一次库，整件事也记进操作日志。
# ---------------------------------------------------------------------------

# 业务表的经办人字段。operation_logs 不在其列——那是审计痕迹，记的是账号。
_OPERATOR_COLUMNS = [
    ("personnel_info", "operator"),
    ("personnel_filing", "operator"),
    ("certificates", "operator"),
    ("travel_details", "operator"),
    ("decontrol_filing", "operator"),
    ("cert_issuance", "operator"),
    ("cert_issuance", "issuer"),
    ("cert_issuance", "return_operator"),
]


def _legacy_operator_counts(username: str) -> dict:
    """统计业务表里还有多少条记录把登录账号当经办人。"""
    db = get_db()
    total = 0
    for table, col in _OPERATOR_COLUMNS:
        try:
            total += db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (username,)).fetchone()[0]
        except sqlite3.OperationalError:
            continue        # 老库可能还没有 cert_issuance 表
    return {"username": username, "total": total}


@auth_bp.route("/account/backfill-operator", methods=["POST"])
@login_required
def backfill_operator() -> ResponseReturnValue:
    """把业务表里等于登录账号的经办人，批量改成真实姓名。"""
    from utils.helpers import log_action
    from utils.backup import run_daily_backup

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?",
                      (session.get("username"),)).fetchone()
    if not user:
        session.clear()
        return redirect(url_for("auth.login"))

    full_name = (user["full_name"] or "").strip()
    if not full_name:
        flash("请先填写并保存姓名，再回填历史记录。", "warning")
        return redirect(url_for("auth.account"))
    if full_name == user["username"]:
        flash("姓名与登录账号相同，无需回填。", "info")
        return redirect(url_for("auth.account"))

    # 不可逆的批量写入，先留一份退路
    try:
        run_daily_backup(force=True)               # force：当天已备过也要再备，因为马上要改数据
    except Exception as exc:                       # noqa: BLE001 - 备份失败就别动数据
        flash(f"自动备份失败（{exc}），已中止回填。请手动备份 data.db 后重试。", "danger")
        return redirect(url_for("auth.account"))

    changed = 0
    for table, col in _OPERATOR_COLUMNS:
        try:
            cur = db.execute(f"UPDATE {table} SET {col} = ? WHERE {col} = ?",
                             (full_name, user["username"]))
            changed += cur.rowcount
        except sqlite3.OperationalError:
            continue
    db.commit()

    log_action("update", "users", user["id"],
               detail=f"历史经办人回填：{user['username']} → {full_name}，共 {changed} 条")
    flash(f"已把 {changed} 条历史记录的经办人由「{user['username']}」更新为「{full_name}」。"
          "操作日志保持原样（审计需要登录账号）。", "success")
    return redirect(url_for("auth.account"))

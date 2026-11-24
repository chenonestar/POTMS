"""轻量 CSRF 防护（不依赖 Flask-WTF，零额外打包体积）。

原理：为每个会话生成一个随机令牌存入 session，页面把令牌暴露到
<meta name="csrf-token"> 与各表单隐藏域；对所有会改变状态的请求
（POST/PUT/PATCH/DELETE）在 before_request 阶段做常量时间比对，
不通过则 400 拒绝。
"""
import secrets

from flask import session, request, redirect, url_for, flash

CSRF_SESSION_KEY = "_csrf_token"
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRFToken"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def generate_csrf() -> str:
    """返回当前会话的 CSRF 令牌，不存在则生成并写入 session。"""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def _submitted_token() -> str:
    """从表单域 / 请求头 / 查询串中提取客户端提交的令牌。"""
    return (
        request.form.get(CSRF_FIELD)
        or request.headers.get(CSRF_HEADER)
        or request.args.get(CSRF_FIELD)
        or ""
    )


def init_csrf(app):
    """在应用上注册 CSRF 校验钩子与模板函数。"""

    @app.before_request
    def _csrf_protect():
        if request.method in _SAFE_METHODS:
            return
        expected = session.get(CSRF_SESSION_KEY)
        sent = _submitted_token()
        if not expected or not sent or not secrets.compare_digest(str(expected), str(sent)):
            # 直接返回重定向，不走 abort(400)。
            #
            # before_request 返回响应就会跳过视图，效果与原来一样（都是 302 到
            # 登录页），但**不再需要一个 400 处理器**。原先那个处理器里有一支
            # `return err`：非 CSRF 的 400 原样返回，也就是 werkzeug 的英文默认页。
            # 目前全仓只有这一处 abort(400)，那一支还不可达，但它是个装好了的
            # 陷阱——谁写一句 abort(400, "参数不对")，当场就是一屏英文。
            #
            # 去掉那个处理器之后，任何 400 都落到 app.py 里的 HTTPException
            # 兜底处理器，拿到中文页。少一个处理器，少一条要维护的判据。
            #
            # CSRF 失败多因会话过期，所以不是停在错误页，而是引导重新登录。
            flash("会话已过期或页面已失效，请重新登录后再试。", "warning")
            return redirect(url_for("auth.login"))

    @app.context_processor
    def _inject_csrf():
        return {"csrf_token": generate_csrf}

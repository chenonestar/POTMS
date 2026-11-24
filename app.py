"""因私出国（境）人员审批管理系统 — 主入口"""
import os
import sys

from flask import Flask

from config import Config


def _resource_root() -> str:
    """模板/静态资源根目录：打包为单文件 exe 时位于临时解压目录 _MEIPASS。"""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.abspath(os.path.dirname(__file__))


def create_app() -> Flask:
    root = _resource_root()
    app = Flask(
        __name__,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )
    app.config.from_object(Config)

    # 确保运行时目录存在
    for folder in [Config.UPLOAD_FOLDER, Config.EXPORT_FOLDER, Config.BACKUP_FOLDER]:
        os.makedirs(folder, exist_ok=True)

    # 初始化数据库（首次运行）
    first_run = not os.path.exists(Config.DATABASE)
    if first_run:
        from database import init_db, seed_data
        init_db()
        seed_data()
    app.config["FIRST_RUN"] = first_run

    # 轻量迁移（已存在的数据库补齐新增字段）
    from database import run_migrations
    run_migrations()

    # 每日自动备份（幂等：当天已备份则跳过）
    try:
        from utils.backup import run_daily_backup
        run_daily_backup()
    except Exception:
        pass

    # 注册蓝图
    from auth import auth_bp
    from blueprints.dashboard import dashboard_bp
    from blueprints.personnel import personnel_bp
    from blueprints.certificate import certificate_bp
    from blueprints.travel import travel_bp
    from blueprints.issuance import issuance_bp
    from blueprints.decontrol import decontrol_bp
    from blueprints.export import export_bp
    from blueprints.import_data import import_bp
    from blueprints.logs import logs_bp
    from blueprints.organization import org_bp
    from blueprints.dict_admin import dict_bp
    from blueprints.submit_unit import submit_unit_bp
    from blueprints.search import search_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(personnel_bp)
    app.register_blueprint(certificate_bp)
    app.register_blueprint(travel_bp)
    app.register_blueprint(issuance_bp)
    app.register_blueprint(decontrol_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(import_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(org_bp)
    app.register_blueprint(dict_bp)
    app.register_blueprint(submit_unit_bp)
    app.register_blueprint(search_bp)

    # CSRF 防护（轻量内置，覆盖所有状态变更请求）
    from utils.csrf import init_csrf
    init_csrf(app)

    # 中文错误页：404 / 500（500 同时记录异常堆栈到应用日志）
    from flask import render_template
    from jinja2 import TemplateNotFound

    def _error_page(template: str, fallback: str, code: int, **ctx):
        r"""错误页本身不能再成为错误源。

        打包成单文件 exe 时，PyInstaller 把资源解压到 %TEMP%\_MEIxxxx，程序退出时
        又把它删掉。一旦服务进程比那个目录活得久（关控制台窗口后 waitress 线程还在
        跑就会这样），模板与静态文件一起消失：渲染 errors/404.html 抛
        TemplateNotFound，把一个 404 升级成 500；500 处理器渲染 errors/500.html
        再抛一次，最后由 waitress 打出整屏堆栈。退回纯文本，至少让浏览器拿到正确的
        状态码，日志里也只剩一行有用的信息。
        """
        try:
            return render_template(template, **ctx), code
        except TemplateNotFound:
            return fallback, code, {"Content-Type": "text/plain; charset=utf-8"}

    # 浏览器无条件索要的 /favicon.ico。本系统不带站点图标，但每开一个标签页
    # 浏览器都要问一次；没有这条路由，每次都会走一遍 404 处理器并在日志里留一行。
    # 明确应答 204，浏览器会记住并停止追问。
    @app.route("/favicon.ico")
    def _favicon():
        return "", 204

    @app.errorhandler(404)
    def _not_found(err):
        return _error_page("errors/404.html", "404 页面不存在", 404)

    @app.errorhandler(413)
    def _too_large(err):
        """上传超过 MAX_CONTENT_LENGTH。

        此前没有这个处理器，走的是 werkzeug 的默认页：整屏英文
        「413 Request Entity Too Large / The data value transmitted exceeds
        the capacity limit.」，没有导航、没有中文，而且是整页替换——填了半天
        的表单当场丢光。

        **不能说「单个文件超过 10MB」。** MAX_CONTENT_LENGTH 限的是整个请求体，
        三个各 4MB 的附件每个都合规、合计 12MB 照样被拒。而且请求体在这一步
        根本没被解析过，服务端不知道是哪个文件大——只能说「合计」。

        真正的修复在前端（提交前用 file.size 预检，请求根本不发出去，
        表单和已填内容都留在页面上）；这里是兜底：JS 被禁、或伪造的 POST。
        """
        limit = app.config.get("MAX_CONTENT_LENGTH") or 0
        limit_mb = round(limit / (1024 * 1024), 1) if limit else "—"
        # 数字里有小数点才留小数位，10.0MB 读起来像是精确到了 0.1MB
        if isinstance(limit_mb, float) and limit_mb.is_integer():
            limit_mb = int(limit_mb)
        return _error_page(
            "errors/413.html",
            f"413 上传内容过大。本次提交的文件合计超过 {limit_mb}MB 上限——"
            "这是整次提交的总量，不是单个文件的上限。请减小附件后重新提交。",
            413, limit_mb=limit_mb)

    @app.errorhandler(500)
    def _server_error(err):
        app.logger.exception("Internal Server Error: %s", err)
        return _error_page(
            "errors/500.html",
            "500 服务器内部错误。若本程序是单文件 exe 且刚刚关过窗口，"
            "请彻底结束 POTMS 进程后重新启动。",
            500,
        )

    # ------------------------------------------------------------------
    # 其余所有 HTTP 错误的兜底
    #
    # 上面三个（404 / 413 / 500）有各自的专页。问题是**没有专页的那些**原先
    # 一律走 werkzeug 默认页：英文、没有导航、整页替换。实测过的：
    #
    #   405  ✗ 框架默认页   真实可达：21 条 POST-only 路由（删除 / 取消 / 恢复 /
    #                       作废 / 备份 / 字典与组织机构增删），地址栏手输、
    #                       收藏、对提交后的页面按刷新都会撞到
    #   400  ✗ 框架默认页   非 CSRF 的那一支（CSRF 失败另有处理，见 utils/csrf.py）
    #   403  ✗ 框架默认页   目前无调用点，但那一支敞着
    #   401  ✗ 框架默认页   同上
    #
    # 不一条条补，补根：注册一个 HTTPException 处理器。Flask 查处理器时**先按
    # 状态码找，找不到再按异常类的 MRO 找**，所以 404 / 413 / 500 仍走各自专页，
    # 其余一律落到这里。这样保证的不是「这三个补上了」，而是**框架默认页再也
    # 逃不出去**——下次冒出个 409、422 同样接得住。
    #
    # 这些码在本系统的部署形态下根本不会出现，所以不写：
    #   502 / 504  要有反向代理才会出，而这是单机 waitress
    #   429        没有限流
    #   waitress 自己在进 Flask 之前拒掉的（请求行过长、HTTP 报文畸形）——
    #              那层这个处理器管不到，只能记在这里
    # ------------------------------------------------------------------
    from werkzeug.exceptions import HTTPException

    # 状态码 → (标题, 说明, 图标, 「什么都没发生」的安心话)
    # 说明一律是自己写的中文；**不透传 err.description**，理由见模板里的注释。
    _HTTP_TEXT = {
        400: ("请求无法识别", "浏览器送来的数据不完整或格式不对，服务器没能读懂。"
                             "通常是页面停留过久或中途刷新导致的，<strong>回到首页重新操作一次</strong>即可。",
              "bi-question-circle", "服务器没有执行任何操作，数据没有改动。"),
        401: ("需要登录", "这个页面要登录后才能访问。", "bi-person-lock", None),
        403: ("没有权限", "当前账号不能访问这个页面或执行这个操作。", "bi-shield-lock", None),
        405: ("这个地址不能直接打开",
              "删除、取消、恢复、作废、备份这类<strong>操作</strong>只能通过页面上的按钮来提交，"
              "不能在地址栏里直接输入、不能收藏后打开、也不能对提交完的页面按刷新。"
              "<br>请回到对应的列表页，用那一行上的按钮操作。",
              "bi-sign-do-not-enter",
              "你刚才的操作没有被执行，数据没有任何改动。"),
    }

    @app.errorhandler(HTTPException)
    def _http_error(err):
        code = err.code or 500
        title, detail, icon, reassure = _HTTP_TEXT.get(
            code,
            ("请求未能完成",
             "服务器无法处理这次请求。请回到首页重新操作；若反复出现，请记下这个页面的编号后联系维护人员。",
             "bi-exclamation-circle", None))
        return _error_page(
            "errors/http.html",
            f"{code} {title}。请返回首页重新操作。",
            # 模板里那个变量不能也叫 code：_error_page 的第三个形参就叫 code，
            # 同名会撞成 TypeError: got multiple values for argument 'code'。
            code, status=code, title=title, detail=detail, icon=icon, reassure=reassure)

    # 数据库连接关闭
    from database import close_db
    app.teardown_appcontext(close_db)

    # Jinja2 过滤器：UTC → 本地时间显示（store UTC / display local）
    from utils.helpers import to_local_time
    app.jinja_env.filters["localtime"] = to_local_time

    # Jinja2 模板全局函数（数据字典查询）
    from utils.helpers import get_dict_options, get_dict_value, get_org_tree_options, get_org_children, get_org_flat, get_personnel_options, get_submit_units

    @app.context_processor
    def inject_dict_helpers():
        return {
            "dict_opts": get_dict_options,
            "dict_value": get_dict_value,
            "org_tree_opts": get_org_tree_options,
            "org_children": get_org_children,
            "org_flat": get_org_flat,
            "personnel_opts": get_personnel_options,
            "submit_units": get_submit_units,
        }

    return app


# =========================================================================
def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _force_utf8_console() -> None:
    """把 stdout / stderr 固定为 UTF-8，避免中文输出把进程打死。

    Windows 上 stdout 一旦不是控制台——重定向到文件（`POTMS.exe > log.txt`）、
    注册成服务、被别的进程接管管道——Python 就改按系统 ANSI 代码页编码。
    非简体中文的区域设置（英文 Windows 是 cp1252）编不出启动横幅里的中文，
    print 直接抛 UnicodeEncodeError，程序**启动即崩**，而且崩在写日志这件事上，
    日志里往往什么也留不下。

    只设 PYTHONUTF8 / PYTHONIOENCODING 不管用：PyInstaller 冻结后的解释器
    不读 PYTHON* 环境变量，所以必须在代码里定死。

    errors="replace" 是最后一道保险：真碰上编不出的字符就显示问号，
    不能让一行日志把整个服务带走。
    """
    for stream in (sys.stdout, sys.stderr):
        # --noconsole / pythonw 下 stdout 可能是 None
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


if __name__ == "__main__":
    _force_utf8_console()  # 必须在第一次 print 之前
    app = create_app()

    host = os.environ.get("POTMS_HOST", "127.0.0.1")
    port = int(os.environ.get("POTMS_PORT", "5000"))
    debug = _env_flag("POTMS_DEBUG")  # 生产默认关闭；需调试时设 POTMS_DEBUG=1
    shown_host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host

    print("=" * 56)
    print("  因私出国（境）人员审批管理系统")
    print(f"  http://{shown_host}:{port}")
    if app.config.get("FIRST_RUN"):
        print("  首次运行，默认管理员: admin / admin123（请尽快改密）")
    print("=" * 56)

    if debug:
        # 开发调试模式（含热重载与调试器，切勿用于生产）
        app.run(debug=True, host=host, port=port)
    else:
        # 生产模式：使用 waitress（纯 Python WSGI 服务器）
        try:
            from waitress import serve
            serve(app, host=host, port=port, threads=8)
        except ImportError:
            print("  [提示] 未安装 waitress，暂以内置服务器运行；生产请 pip install waitress")
            app.run(debug=False, host=host, port=port)

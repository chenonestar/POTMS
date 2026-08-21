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

    def _error_page(template: str, fallback: str, code: int):
        r"""错误页本身不能再成为错误源。

        打包成单文件 exe 时，PyInstaller 把资源解压到 %TEMP%\_MEIxxxx，程序退出时
        又把它删掉。一旦服务进程比那个目录活得久（关控制台窗口后 waitress 线程还在
        跑就会这样），模板与静态文件一起消失：渲染 errors/404.html 抛
        TemplateNotFound，把一个 404 升级成 500；500 处理器渲染 errors/500.html
        再抛一次，最后由 waitress 打出整屏堆栈。退回纯文本，至少让浏览器拿到正确的
        状态码，日志里也只剩一行有用的信息。
        """
        try:
            return render_template(template), code
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

    @app.errorhandler(500)
    def _server_error(err):
        app.logger.exception("Internal Server Error: %s", err)
        return _error_page(
            "errors/500.html",
            "500 服务器内部错误。若本程序是单文件 exe 且刚刚关过窗口，"
            "请彻底结束 POTMS 进程后重新启动。",
            500,
        )

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


if __name__ == "__main__":
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

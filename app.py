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
    from blueprints.decontrol import decontrol_bp
    from blueprints.export import export_bp
    from blueprints.import_data import import_bp
    from blueprints.logs import logs_bp
    from blueprints.organization import org_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(personnel_bp)
    app.register_blueprint(certificate_bp)
    app.register_blueprint(travel_bp)
    app.register_blueprint(decontrol_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(import_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(org_bp)

    # 数据库连接关闭
    from database import close_db
    app.teardown_appcontext(close_db)

    # Jinja2 模板全局函数（数据字典查询）
    from utils.helpers import get_dict_options, get_dict_value, get_org_tree_options, get_org_children, get_personnel_options

    @app.context_processor
    def inject_dict_helpers():
        return {
            "dict_opts": get_dict_options,
            "dict_value": get_dict_value,
            "org_tree_opts": get_org_tree_options,
            "org_children": get_org_children,
            "personnel_opts": get_personnel_options,
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

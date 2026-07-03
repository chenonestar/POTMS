"""因私出国（境）人员审批管理系统 — 主入口"""
import os
import sys

from flask import Flask

from config import Config


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    # 确保运行时目录存在
    for folder in [Config.UPLOAD_FOLDER, Config.EXPORT_FOLDER, Config.BACKUP_FOLDER]:
        os.makedirs(folder, exist_ok=True)

    # 初始化数据库（首次运行）
    if not os.path.exists(Config.DATABASE):
        from database import init_db, seed_data
        init_db()
        seed_data()

    # 轻量迁移（已存在的数据库补齐新增字段）
    from database import run_migrations
    run_migrations()

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
if __name__ == "__main__":
    app = create_app()
    print("=" * 56)
    print("  因私出国（境）人员审批管理系统")
    print("  http://localhost:5000")
    print("  管理员账户: admin / admin123")
    print("=" * 56)
    app.run(debug=True, host="127.0.0.1", port=5000)

"""应用配置"""
import os
import sys
import secrets

# 数据目录：打包为单文件 exe 时，数据（data.db/uploads/exports/backup）
# 需持久化到 exe 所在目录，而非临时解压目录。
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _load_or_create_secret() -> str:
    """持久化 SECRET_KEY 到数据目录，避免每次重启导致会话失效（登录态丢失）。"""
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    key_file = os.path.join(BASE_DIR, ".secret_key")
    try:
        if os.path.exists(key_file):
            with open(key_file, "r", encoding="utf-8") as f:
                val = f.read().strip()
                if val:
                    return val
        val = secrets.token_hex(32)
        with open(key_file, "w", encoding="utf-8") as f:
            f.write(val)
        return val
    except OSError:
        # 无写权限时退化为随机（重启会话失效，但不影响功能）
        return secrets.token_hex(32)


class Config:
    # Flask
    SECRET_KEY = _load_or_create_secret()

    # SQLite（纯 Python 驱动，无需编译）
    DATABASE = os.path.join(BASE_DIR, "data.db")

    # 文件存储
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    EXPORT_FOLDER = os.path.join(BASE_DIR, "exports")
    BACKUP_FOLDER = os.path.join(BASE_DIR, "backup")

    # 上传限制
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB
    ALLOWED_EXTENSIONS = {"pdf"}

    # 会话
    PERMANENT_SESSION_LIFETIME = 3600  # 1小时超时
    # Cookie 安全标志显式声明（不依赖框架/浏览器默认行为）
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # 分页（业务列表一屏可容纳的行数；操作日志因含多行变更详情单独取更小值）
    PAGE_SIZE = 12
    PAGE_SIZE_LOGS = 10

    # 时间显示：数据库统一存储 UTC，展示时按此偏移换算为本地时间。
    # 中国大陆固定 UTC+8 且无夏令时；如需其它时区，设环境变量 POTMS_TZ_OFFSET（单位：小时）。
    DISPLAY_TZ_OFFSET_HOURS = int(os.environ.get("POTMS_TZ_OFFSET", "8"))

    # 证照到期预警（天）
    CERT_EXPIRY_WARN_DAYS = 30

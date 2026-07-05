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

    # 分页
    PAGE_SIZE = 20

    # 证照到期预警（天）
    CERT_EXPIRY_WARN_DAYS = 30

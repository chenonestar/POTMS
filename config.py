"""应用配置"""
import os
import secrets

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

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

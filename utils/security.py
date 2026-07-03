"""密码哈希与校验 — bcrypt（兼容旧 werkzeug 哈希，登录时透明升级）"""
import bcrypt
from werkzeug.security import check_password_hash


def hash_password(password: str) -> str:
    """使用 bcrypt 生成加盐哈希（返回字符串）。"""
    # bcrypt 仅取前 72 字节，足够
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    """
    校验密码。
    返回 (是否匹配, 是否需要升级为bcrypt)。
    - bcrypt 哈希（$2...）：直接校验，无需升级。
    - 旧 werkzeug 哈希（pbkdf2:/scrypt:）：兼容校验，匹配后建议升级为 bcrypt。
    """
    if not stored_hash:
        return (False, False)
    if stored_hash.startswith("$2"):
        try:
            ok = bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except ValueError:
            ok = False
        return (ok, False)
    # 兼容旧哈希
    try:
        ok = check_password_hash(stored_hash, password)
    except Exception:
        ok = False
    return (ok, ok)  # 旧哈希校验通过则需要升级

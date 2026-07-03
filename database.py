"""数据库初始化、连接管理、种子数据"""
import sqlite3
import os
from datetime import datetime

from config import Config

# ---------------------------------------------------------------------------
# 字典种子数据
# ---------------------------------------------------------------------------
SEED_DICT = [
    # 学历
    ("education", "01", "博士研究生", 1),
    ("education", "02", "硕士研究生", 2),
    ("education", "03", "大学本科", 3),
    ("education", "04", "大学专科", 4),
    ("education", "05", "中专", 5),
    ("education", "06", "高中", 6),
    ("education", "07", "初中及以下", 7),
    # 学位
    ("degree", "01", "博士", 1),
    ("degree", "02", "硕士", 2),
    ("degree", "03", "学士", 3),
    ("degree", "99", "无", 4),
    # 职称
    ("title", "01", "正高", 1),
    ("title", "02", "副高", 2),
    ("title", "03", "中级", 3),
    ("title", "04", "初级", 4),
    ("title", "99", "无", 5),
    # 职级
    ("rank", "01", "处级", 1),
    ("rank", "02", "副处级", 2),
    ("rank", "03", "正科", 3),
    ("rank", "04", "副科", 4),
    ("rank", "05", "科员", 5),
    ("rank", "99", "其他", 6),
    # 政治面貌
    ("political_status", "01", "中共党员", 1),
    ("political_status", "02", "中共预备党员", 2),
    ("political_status", "03", "共青团员", 3),
    ("political_status", "04", "民革会员", 4),
    ("political_status", "05", "民盟盟员", 5),
    ("political_status", "06", "民建会员", 6),
    ("political_status", "07", "民进会员", 7),
    ("political_status", "08", "农工党党员", 8),
    ("political_status", "09", "致工党党员", 9),
    ("political_status", "10", "九三学社社员", 10),
    ("political_status", "99", "群众", 11),
    # 出国（境）类别
    ("travel_category", "01", "旅游", 1),
    ("travel_category", "02", "探亲", 2),
    ("travel_category", "03", "访友", 3),
    ("travel_category", "04", "商务", 4),
    ("travel_category", "05", "留学", 5),
    ("travel_category", "99", "其他", 6),
    # 报送单位类别
    ("submit_unit_type", "01", "党政机关", 1),
    ("submit_unit_type", "02", "金融系统", 2),
    ("submit_unit_type", "03", "教科文卫系统", 3),
    ("submit_unit_type", "04", "国有大中型企业单位", 4),
    ("submit_unit_type", "99", "其他单位", 5),
]


def get_db():
    """获取数据库连接（每次请求调用）"""
    import flask
    if "db" not in flask.g:
        flask.g.db = sqlite3.connect(Config.DATABASE)
        flask.g.db.row_factory = sqlite3.Row
        flask.g.db.execute("PRAGMA journal_mode=WAL")
        flask.g.db.execute("PRAGMA foreign_keys=ON")
    return flask.g.db


def close_db(exception=None):
    """关闭数据库连接"""
    import flask
    db = flask.g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """创建全部表结构"""
    db = sqlite3.connect(Config.DATABASE)
    db.executescript(SCHEMA)
    db.commit()
    db.close()


def run_migrations():
    """轻量迁移：为已存在的数据库补齐新增字段（幂等）"""
    db = sqlite3.connect(Config.DATABASE)
    try:
        info_cols = {row[1] for row in db.execute("PRAGMA table_info(personnel_info)").fetchall()}
        if "id_number" not in info_cols:
            db.execute("ALTER TABLE personnel_info ADD COLUMN id_number TEXT")

        # 出国明细：规范化的出行起止日期（用于日期区间筛选）
        travel_cols = {row[1] for row in db.execute("PRAGMA table_info(travel_details)").fetchall()}
        need_backfill = False
        if "travel_start" not in travel_cols:
            db.execute("ALTER TABLE travel_details ADD COLUMN travel_start TEXT")
            need_backfill = True
        if "travel_end" not in travel_cols:
            db.execute("ALTER TABLE travel_details ADD COLUMN travel_end TEXT")
            need_backfill = True

        # 操作日志：变更前后数据快照（JSON）
        log_cols = {row[1] for row in db.execute("PRAGMA table_info(operation_logs)").fetchall()}
        if "snapshot" not in log_cols:
            db.execute("ALTER TABLE operation_logs ADD COLUMN snapshot TEXT")

        db.commit()

        # 回填历史出行记录的起止日期
        if need_backfill:
            from utils.validators import parse_travel_range
            rows = db.execute("SELECT id, travel_dates FROM travel_details").fetchall()
            for tid, dates in rows:
                start, end = parse_travel_range(dates or "")
                db.execute("UPDATE travel_details SET travel_start=?, travel_end=? WHERE id=?",
                           (start, end, tid))
            db.commit()
    finally:
        db.close()


def seed_data():
    """写入种子数据（幂等）"""
    db = sqlite3.connect(Config.DATABASE)
    db.execute("PRAGMA foreign_keys=ON")

    # --- 管理员账户 ---
    existing = db.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if not existing:
        from utils.security import hash_password
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            ("admin", hash_password("admin123")),
        )

    # --- 数据字典 ---
    for category, code, value, sort_order in SEED_DICT:
        db.execute(
            "INSERT OR IGNORE INTO sys_dict (category, code, value, sort_order) VALUES (?, ?, ?, ?)",
            (category, code, value, sort_order),
        )

    # --- 组织架构种子数据 ---
    existing_org = db.execute("SELECT id FROM sys_org LIMIT 1").fetchone()
    if not existing_org:
        orgs = [
            (1, "总部", 0, 1),
            (2, "办公室", 1, 1),
            (3, "人事处", 1, 2),
            (4, "财务处", 1, 3),
            (5, "业务一部", 1, 4),
            (6, "业务二部", 1, 5),
        ]
        for oid, name, pid, sort in orgs:
            db.execute("INSERT INTO sys_org (id, name, parent_id, sort_order) VALUES (?, ?, ?, ?)",
                       (oid, name, pid, sort))

    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# 建表 SQL
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS personnel_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit TEXT NOT NULL,
    department TEXT NOT NULL,
    name TEXT NOT NULL,
    gender TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    id_number TEXT,
    work_start_date TEXT,
    education TEXT,
    degree TEXT,
    title TEXT,
    rank TEXT NOT NULL,
    political_status TEXT NOT NULL,
    party_join_date TEXT,
    position TEXT NOT NULL,
    operator TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS personnel_filing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personnel_info_id INTEGER REFERENCES personnel_info(id),
    surname TEXT NOT NULL,
    given_name TEXT NOT NULL,
    gender TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    id_number TEXT NOT NULL,
    residence TEXT NOT NULL,
    political_status TEXT NOT NULL,
    work_unit TEXT NOT NULL,
    position_or_title TEXT NOT NULL,
    supervisor_unit TEXT NOT NULL,
    tag TEXT NOT NULL DEFAULT '新增',
    informed TEXT NOT NULL DEFAULT '否',
    status TEXT NOT NULL DEFAULT 'active',
    remarks TEXT,
    replaced_by_id INTEGER,
    operator TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS certificates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personnel_filing_id INTEGER NOT NULL REFERENCES personnel_filing(id),
    unit TEXT NOT NULL,
    department TEXT NOT NULL,
    name TEXT NOT NULL,
    passport_no TEXT,
    passport_expiry TEXT,
    passport_submit_date TEXT,
    hm_pass_no TEXT,
    hm_pass_expiry TEXT,
    hm_pass_submit_date TEXT,
    tw_pass_no TEXT,
    tw_pass_expiry TEXT,
    tw_pass_submit_date TEXT,
    operator TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS travel_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personnel_filing_id INTEGER NOT NULL REFERENCES personnel_filing(id),
    unit TEXT NOT NULL,
    department TEXT NOT NULL,
    name TEXT NOT NULL,
    position TEXT NOT NULL,
    title TEXT,
    id_number TEXT NOT NULL,
    destination_passport TEXT NOT NULL,
    category TEXT NOT NULL,
    travel_dates TEXT NOT NULL,
    approval_date TEXT,
    need_new_passport TEXT NOT NULL DEFAULT '否',
    passport_no TEXT,
    passport_collect_date TEXT,
    passport_return_date TEXT,
    operator TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS decontrol_filing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personnel_filing_id INTEGER NOT NULL REFERENCES personnel_filing(id),
    surname TEXT NOT NULL,
    given_name TEXT NOT NULL,
    gender TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    id_number TEXT NOT NULL,
    residence TEXT NOT NULL,
    political_status TEXT NOT NULL,
    work_unit TEXT NOT NULL,
    supervisor_unit TEXT NOT NULL,
    submit_unit_name TEXT NOT NULL,
    submit_unit_type TEXT NOT NULL,
    submit_contact TEXT NOT NULL,
    submit_phone TEXT NOT NULL,
    batch_no TEXT NOT NULL,
    reason TEXT NOT NULL,
    operator TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    travel_id INTEGER NOT NULL REFERENCES travel_details(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sys_dict (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    code TEXT NOT NULL,
    value TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    UNIQUE(category, code)
);

CREATE TABLE IF NOT EXISTS sys_org (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parent_id INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operator TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id INTEGER,
    detail TEXT,
    ip_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

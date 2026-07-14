// 数据库：建表/迁移/种子 + 查询助手（行 → serde_json，供 minijinja 使用）
// schema 与 Go / Python 版逐字对应，三版共用同一个 data.db
use rusqlite::{params_from_iter, types::Value as SqlValue, types::ValueRef, Connection};
use serde_json::{Map, Value};

pub type Row = Value; // 每行是一个 JSON Object

pub const SCHEMA_SQL: &str = r#"
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS personnel_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit TEXT NOT NULL, department TEXT NOT NULL, name TEXT NOT NULL,
    gender TEXT NOT NULL, birth_date TEXT NOT NULL, id_number TEXT,
    work_start_date TEXT, education TEXT, degree TEXT, title TEXT,
    rank TEXT NOT NULL, political_status TEXT NOT NULL, party_join_date TEXT,
    position TEXT NOT NULL, operator TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS personnel_filing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personnel_info_id INTEGER REFERENCES personnel_info(id),
    surname TEXT NOT NULL, given_name TEXT NOT NULL, gender TEXT NOT NULL,
    birth_date TEXT NOT NULL, id_number TEXT NOT NULL, residence TEXT NOT NULL,
    political_status TEXT NOT NULL, work_unit TEXT NOT NULL,
    position_or_title TEXT NOT NULL, supervisor_unit TEXT NOT NULL,
    tag TEXT NOT NULL DEFAULT '新增', informed TEXT NOT NULL DEFAULT '否',
    status TEXT NOT NULL DEFAULT 'active', remarks TEXT, replaced_by_id INTEGER,
    operator TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS certificates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personnel_filing_id INTEGER NOT NULL REFERENCES personnel_filing(id),
    unit TEXT NOT NULL, department TEXT NOT NULL, name TEXT NOT NULL,
    passport_no TEXT, passport_expiry TEXT, passport_submit_date TEXT,
    hm_pass_no TEXT, hm_pass_expiry TEXT, hm_pass_submit_date TEXT,
    tw_pass_no TEXT, tw_pass_expiry TEXT, tw_pass_submit_date TEXT,
    operator TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS travel_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personnel_filing_id INTEGER NOT NULL REFERENCES personnel_filing(id),
    unit TEXT NOT NULL, department TEXT NOT NULL, name TEXT NOT NULL,
    position TEXT NOT NULL, title TEXT, id_number TEXT NOT NULL,
    destination_passport TEXT NOT NULL, category TEXT NOT NULL,
    travel_dates TEXT NOT NULL, travel_start TEXT, travel_end TEXT,
    approval_date TEXT, need_new_passport TEXT NOT NULL DEFAULT '否',
    passport_no TEXT, passport_collect_date TEXT, passport_return_date TEXT,
    actual_return_date TEXT, trip_status TEXT DEFAULT 'normal', cancel_date TEXT,
    operator TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS decontrol_filing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personnel_filing_id INTEGER NOT NULL REFERENCES personnel_filing(id),
    surname TEXT NOT NULL, given_name TEXT NOT NULL, gender TEXT NOT NULL,
    birth_date TEXT NOT NULL, id_number TEXT NOT NULL, residence TEXT NOT NULL,
    political_status TEXT NOT NULL, work_unit TEXT NOT NULL,
    supervisor_unit TEXT NOT NULL, submit_unit_name TEXT NOT NULL,
    submit_unit_type TEXT NOT NULL, submit_contact TEXT NOT NULL,
    submit_phone TEXT NOT NULL, batch_no TEXT NOT NULL, reason TEXT NOT NULL,
    decontrol_date TEXT, cert_handover_date TEXT, operator TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sys_submit_unit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, contact TEXT, phone TEXT, sort_order INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    travel_id INTEGER NOT NULL REFERENCES travel_details(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL, file_path TEXT NOT NULL, file_type TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sys_dict (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL, code TEXT NOT NULL, value TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0, UNIQUE(category, code)
);
CREATE TABLE IF NOT EXISTS sys_org (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, parent_id INTEGER DEFAULT 0, sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operator TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT NOT NULL,
    target_id INTEGER, detail TEXT, ip_address TEXT, snapshot TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"#;

pub fn open(path: &std::path::Path) -> Connection {
    let conn = Connection::open(path).expect("打开数据库失败");
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;",
    )
    .expect("设置 PRAGMA 失败");
    conn
}

pub fn init_schema(conn: &Connection) {
    conn.execute_batch(SCHEMA_SQL).expect("建表失败");
}

pub fn run_migrations(conn: &Connection) {
    for idx in [
        "CREATE INDEX IF NOT EXISTS idx_pf_id_number ON personnel_filing(id_number)",
        "CREATE INDEX IF NOT EXISTS idx_pf_status ON personnel_filing(status)",
        "CREATE INDEX IF NOT EXISTS idx_td_pf_id ON travel_details(personnel_filing_id)",
        "CREATE INDEX IF NOT EXISTS idx_cert_pf_id ON certificates(personnel_filing_id)",
        "CREATE INDEX IF NOT EXISTS idx_dec_pf_id ON decontrol_filing(personnel_filing_id)",
        "CREATE INDEX IF NOT EXISTS idx_att_travel_id ON attachments(travel_id)",
        "CREATE INDEX IF NOT EXISTS idx_logs_created_at ON operation_logs(created_at)",
    ] {
        let _ = conn.execute(idx, []);
    }
}

const SEED_DICT: &[(&str, &str, &str, i64)] = &[
    ("education", "01", "博士研究生", 1), ("education", "02", "硕士研究生", 2),
    ("education", "03", "大学本科", 3), ("education", "04", "大学专科", 4),
    ("education", "05", "中专", 5), ("education", "06", "高中", 6),
    ("education", "07", "初中及以下", 7),
    ("degree", "01", "博士", 1), ("degree", "02", "硕士", 2),
    ("degree", "03", "学士", 3), ("degree", "99", "无", 4),
    ("title", "01", "正高", 1), ("title", "02", "副高", 2),
    ("title", "03", "中级", 3), ("title", "04", "初级", 4), ("title", "99", "无", 5),
    ("rank", "01", "处级", 1), ("rank", "02", "副处级", 2), ("rank", "03", "正科", 3),
    ("rank", "04", "副科", 4), ("rank", "05", "科员", 5), ("rank", "99", "其他", 6),
    ("political_status", "01", "中共党员", 1), ("political_status", "02", "中共预备党员", 2),
    ("political_status", "03", "共青团员", 3), ("political_status", "04", "民革会员", 4),
    ("political_status", "05", "民盟盟员", 5), ("political_status", "06", "民建会员", 6),
    ("political_status", "07", "民进会员", 7), ("political_status", "08", "农工党党员", 8),
    ("political_status", "09", "致工党党员", 9), ("political_status", "10", "九三学社社员", 10),
    ("political_status", "99", "群众", 11),
    ("travel_category", "01", "旅游", 1), ("travel_category", "02", "探亲", 2),
    ("travel_category", "03", "访友", 3), ("travel_category", "04", "商务", 4),
    ("travel_category", "05", "留学", 5), ("travel_category", "99", "其他", 6),
    ("submit_unit_type", "01", "党政机关", 1), ("submit_unit_type", "02", "金融系统", 2),
    ("submit_unit_type", "03", "教科文卫系统", 3), ("submit_unit_type", "04", "国有大中型企业单位", 4),
    ("submit_unit_type", "99", "其他单位", 5),
    ("supervisor_unit", "S01", "人事处", 1),
];

pub fn seed_data(conn: &Connection) -> bool {
    let mut first_run = false;
    let exists: bool = conn
        .query_row("SELECT 1 FROM users WHERE username = 'admin'", [], |_| Ok(true))
        .unwrap_or(false);
    if !exists {
        first_run = true;
        let hash = crate::security::hash_password("admin123");
        let _ = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            rusqlite::params!["admin", hash],
        );
    }
    for (cat, code, val, sort) in SEED_DICT {
        let _ = conn.execute(
            "INSERT OR IGNORE INTO sys_dict (category, code, value, sort_order) VALUES (?, ?, ?, ?)",
            rusqlite::params![cat, code, val, sort],
        );
    }
    let has_org: bool = conn
        .query_row("SELECT 1 FROM sys_org LIMIT 1", [], |_| Ok(true))
        .unwrap_or(false);
    if !has_org {
        for (id, name, parent, sort) in [
            (1, "总部", 0, 1), (2, "办公室", 1, 1), (3, "人事处", 1, 2),
            (4, "财务处", 1, 3), (5, "业务一部", 1, 4), (6, "业务二部", 1, 5),
        ] {
            let _ = conn.execute(
                "INSERT INTO sys_org (id, name, parent_id, sort_order) VALUES (?, ?, ?, ?)",
                rusqlite::params![id, name, parent, sort],
            );
        }
    }
    first_run
}

// ---------------------------------------------------------------------------
// 查询助手：行 → serde_json::Value（Object），供模板按字段名访问
// ---------------------------------------------------------------------------
fn value_ref_to_json(v: ValueRef) -> Value {
    match v {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(n) => Value::from(n),
        ValueRef::Real(f) => Value::from(f),
        ValueRef::Text(t) => Value::from(String::from_utf8_lossy(t).into_owned()),
        ValueRef::Blob(_) => Value::Null,
    }
}

pub fn query_maps(conn: &Connection, sql: &str, params: &[SqlValue]) -> Vec<Row> {
    let mut stmt = match conn.prepare(sql) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("SQL 准备失败: {e}\n  {sql}");
            return vec![];
        }
    };
    let cols: Vec<String> = stmt.column_names().iter().map(|s| s.to_string()).collect();
    let mapped = stmt.query_map(params_from_iter(params.iter()), |row| {
        let mut obj = Map::new();
        for (i, c) in cols.iter().enumerate() {
            obj.insert(c.clone(), value_ref_to_json(row.get_ref(i)?));
        }
        Ok(Value::Object(obj))
    });
    match mapped {
        Ok(iter) => iter.filter_map(|r| r.ok()).collect(),
        Err(e) => {
            eprintln!("SQL 执行失败: {e}\n  {sql}");
            vec![]
        }
    }
}

pub fn query_one(conn: &Connection, sql: &str, params: &[SqlValue]) -> Option<Row> {
    query_maps(conn, sql, params).into_iter().next()
}

pub fn count(conn: &Connection, sql: &str, params: &[SqlValue]) -> i64 {
    conn.query_row(sql, params_from_iter(params.iter()), |r| r.get::<_, i64>(0))
        .unwrap_or(0)
}

pub fn exec(conn: &Connection, sql: &str, params: &[SqlValue]) -> rusqlite::Result<usize> {
    conn.execute(sql, params_from_iter(params.iter()))
}

// 便捷构造 SqlValue 参数
pub fn sv_str(s: impl Into<String>) -> SqlValue {
    SqlValue::Text(s.into())
}
pub fn sv_i64(n: i64) -> SqlValue {
    SqlValue::Integer(n)
}
pub fn sv_opt(s: &str) -> SqlValue {
    if s.is_empty() {
        SqlValue::Null
    } else {
        SqlValue::Text(s.to_string())
    }
}

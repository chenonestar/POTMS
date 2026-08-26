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
    full_name TEXT,
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

    // 登录账户的真实姓名。
    //
    // 单据上的「经办人」要写真人名字，不能写登录账号——打印出来的领用凭证上
    // 一个 admin，是没法拿去归档的。账号继续用于操作日志（账号是身份标识，
    // 姓名可以改；日志只记姓名的话，改名后历史记录就对不上人了）。
    //
    // 五版共用一个 data.db，库可能是任意一版建的，所以每一版都要能补这一列。
    add_column(conn, "users", "full_name", "TEXT");

    // 证件领用记录表（REQ-012，含手写签名）。放在迁移里而不是 SCHEMA_SQL：
    // 建表语句要与 Python 版 run_migrations 逐字对齐，五版共用同一个 data.db。
    let _ = conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS cert_issuance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            travel_id INTEGER REFERENCES travel_details(id),
            personnel_filing_id INTEGER NOT NULL REFERENCES personnel_filing(id),
            holder_name TEXT NOT NULL, id_number TEXT,
            cert_types TEXT NOT NULL, cert_nos TEXT,
            issue_date TEXT NOT NULL, issuer TEXT NOT NULL,
            sign_image BLOB, sign_meta TEXT,
            return_date TEXT, return_sign_image BLOB, return_sign_meta TEXT,
            return_operator TEXT,
            status TEXT NOT NULL DEFAULT 'issued', void_reason TEXT, remarks TEXT,
            operator TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
         CREATE INDEX IF NOT EXISTS idx_issuance_travel ON cert_issuance(travel_id);
         CREATE INDEX IF NOT EXISTS idx_issuance_filing ON cert_issuance(personnel_filing_id);
         CREATE INDEX IF NOT EXISTS idx_issuance_status ON cert_issuance(status);",
    );

    // 证件种类字典：seed_data 只在首次运行执行，存量库在此补齐
    for (cat, code, val, ord) in SEED_DICT.iter().filter(|d| d.0 == "cert_type") {
        let _ = conn.execute(
            "INSERT OR IGNORE INTO sys_dict (category, code, value, sort_order) VALUES (?, ?, ?, ?)",
            rusqlite::params![cat, code, val, ord],
        );
    }

    backfill_legacy_issuance(conn);
}

/// 证件种类代码 → 证照登记表里对应的号码列。
/// helpers.rs 的 cert_type_map 用的是同一套映射，两处改动须同步。
pub const CERT_TYPE_COLUMNS: [(&str, &str); 3] =
    [("01", "passport_no"), ("02", "hm_pass_no"), ("03", "tw_pass_no")];

/// 「地点、证照」自由文本里的证件名称关键字。
/// 只认**证件名**不认地名——「香港」既可能持港澳通行证也可能持护照过境，拿地名猜会猜错。
/// 顺序即优先级：先长后短。
const CERT_NAME_HINTS: [(&str, &[&str]); 3] = [
    ("03", &["大陆居民往来台湾", "台湾通行证", "台胞证"]),
    ("02", &["往来港澳", "港澳通行证"]),
    ("01", &["护照"]),
];

/// 回填记录的备注。三个串互不相同，订正迁移靠「备注是否还是旧串」判断是否已处理，
/// 改完备注下次启动自然扫不到，不需要额外的版本表。
pub const BACKFILL_REMARK_LEGACY: &str = "历史数据回填（证件种类按护照推定，无签名）";
pub const BACKFILL_REMARK_INFERRED: &str = "历史数据回填（证件种类据证照登记推定，无签名）";
pub const BACKFILL_REMARK_PENDING: &str = "历史数据回填（证件种类待核实，无签名）";

/// 推断一条历史出行记录用的是哪种证件，判不出返回空串。
///
/// 原先一律记作因私护照（'01'）。这是个**主动编造**的答案：往来港澳通行证、
/// 台湾通行证都被写成护照，而领用凭证是要归档的，错的种类比空着更糟。
///
/// 三级判据，从硬到软：
///   1. 出行记录上的证件号码对上证照登记表的哪一列 —— 号码唯一，这条最硬；
///   2. 「地点、证照」里出现的证件名称 —— 号码没填时的退路；
///   3. 该人在证照登记表里只登记了一种证件 —— 那就只能是它。
///
/// 三条都不成立时返回空串，宁可留空标「待核实」让人来补，也不替他猜一个。
///
/// 遍历该人**所有**证照记录合并三个槽位，不能只取一条：需求文档说证照登记
/// 「一行为一人」，但现实里很容易出现「先登记了护照，过一阵办了港澳通行证时
/// 没找到原记录，又新建了一条」。只看第一条会连着踩空三级判据，最后自信地
/// 答出一个错误答案。
pub fn infer_cert_type(
    conn: &Connection,
    personnel_filing_id: i64,
    cert_no: &str,
    destination_passport: &str,
) -> String {
    let mut held = [String::new(), String::new(), String::new()];
    for r in query_maps(
        conn,
        "SELECT passport_no, hm_pass_no, tw_pass_no FROM certificates \
         WHERE personnel_filing_id = ? ORDER BY id",
        &[sv_i64(personnel_filing_id)],
    ) {
        for (i, (_code, col)) in CERT_TYPE_COLUMNS.iter().enumerate() {
            if held[i].is_empty() {
                held[i] = crate::helpers::row_str(&r, col).trim().to_string();
            }
        }
    }

    // ① 证件号匹配
    let no = cert_no.trim();
    if !no.is_empty() {
        for (i, (code, _col)) in CERT_TYPE_COLUMNS.iter().enumerate() {
            if !held[i].is_empty() && held[i] == no {
                return code.to_string();
            }
        }
    }

    // ② 「地点、证照」里的证件名称
    for (code, keywords) in CERT_NAME_HINTS.iter() {
        if keywords.iter().any(|k| destination_passport.contains(k)) {
            return code.to_string();
        }
    }

    // ③ 该人只登记了一种证件
    let owned: Vec<&str> = CERT_TYPE_COLUMNS
        .iter()
        .enumerate()
        .filter(|(i, _)| !held[*i].is_empty())
        .map(|(_, (code, _))| *code)
        .collect();
    if owned.len() == 1 {
        return owned[0].to_string();
    }
    String::new()
}

/// 把「出行表上已有领用日期、却没有领用记录」的历史数据补成一条领用记录（无签名）。
/// 幂等：仅对尚无领用记录的 travel_id 回填。
///
/// 早期库允许 personnel_filing_id 为空，这类记录无法确定领用人，跳过——其出行表上的
/// 领用日期保持原样，不影响既有逾期口径。
fn backfill_legacy_issuance(conn: &Connection) {
    let rows = query_maps(
        conn,
        "SELECT t.id, t.personnel_filing_id, t.name, t.id_number, t.passport_no, \
         t.destination_passport, \
         t.passport_collect_date, t.passport_return_date, t.operator \
         FROM travel_details t \
         WHERE t.passport_collect_date IS NOT NULL AND t.passport_collect_date != '' \
           AND t.personnel_filing_id IS NOT NULL \
           AND NOT EXISTS (SELECT 1 FROM cert_issuance c WHERE c.travel_id = t.id)",
        &[],
    );
    for r in rows {
        let op = {
            let o = crate::helpers::row_str(&r, "operator");
            if o.is_empty() { "system".to_string() } else { o }
        };
        let rdate = crate::helpers::row_str(&r, "passport_return_date");
        let returned = !rdate.is_empty();
        let ctype = infer_cert_type(
            conn,
            crate::helpers::row_i64(&r, "personnel_filing_id"),
            &crate::helpers::row_str(&r, "passport_no"),
            &crate::helpers::row_str(&r, "destination_passport"),
        );
        let remark = if ctype.is_empty() { BACKFILL_REMARK_PENDING } else { BACKFILL_REMARK_INFERRED };
        let _ = conn.execute(
            "INSERT INTO cert_issuance (travel_id, personnel_filing_id, holder_name, id_number, \
             cert_types, cert_nos, issue_date, issuer, return_date, return_operator, status, \
             remarks, operator) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rusqlite::params![
                crate::helpers::row_i64(&r, "id"),
                crate::helpers::row_i64(&r, "personnel_filing_id"),
                crate::helpers::row_str(&r, "name"),
                crate::helpers::row_str(&r, "id_number"),
                &ctype,
                crate::helpers::row_str(&r, "passport_no"),
                crate::helpers::row_str(&r, "passport_collect_date"),
                &op,
                if returned { Some(rdate.clone()) } else { None },
                if returned { Some(op.clone()) } else { None },
                if returned { "returned" } else { "issued" },
                remark,
                &op,
            ],
        );
    }

    correct_legacy_cert_types(conn);
}

/// 订正上一版回填留下的错标。
///
/// 上面那段回填曾经把 cert_types 一律写成 '01'（因私护照），实际可能是往来港澳
/// 通行证或大陆居民往来台湾通行证。而回填带幂等守卫（travel_id 已有记录就跳过），
/// 光把上面改对，**对已经回填过的库毫无作用**——错的行会一直躺着。
///
/// 判据卡死在回填自己产的行上：备注是那句原文，且没有签名。手工登记的记录有签名、
/// 备注也不同，碰不到。改完备注即失配，下次启动自然跳过。
fn correct_legacy_cert_types(conn: &Connection) {
    let stale = query_maps(
        conn,
        "SELECT c.id, c.personnel_filing_id, c.cert_nos, c.travel_id \
         FROM cert_issuance c WHERE c.remarks = ? AND c.sign_image IS NULL",
        &[sv_str(BACKFILL_REMARK_LEGACY)],
    );
    if stale.is_empty() {
        return;
    }
    // 动的是业务记录，先留一份改动前的快照。每日备份排在迁移之后，等它就晚了。
    // run_migrations 不带 Config，这里就地取一份——它只读环境变量与目录，代价可忽略。
    crate::backup::run_daily_backup(conn, &crate::config::Config::load(), true);

    let (mut fixed, mut pending) = (0usize, 0usize);
    for r in &stale {
        let travel_id = crate::helpers::row_i64(r, "travel_id");
        let dest = if travel_id > 0 {
            query_maps(
                conn,
                "SELECT destination_passport FROM travel_details WHERE id = ?",
                &[sv_i64(travel_id)],
            )
            .first()
            .map(|t| crate::helpers::row_str(t, "destination_passport"))
            .unwrap_or_default()
        } else {
            String::new()
        };
        let ctype = infer_cert_type(
            conn,
            crate::helpers::row_i64(r, "personnel_filing_id"),
            &crate::helpers::row_str(r, "cert_nos"),
            &dest,
        );
        let remark = if ctype.is_empty() {
            pending += 1;
            BACKFILL_REMARK_PENDING
        } else {
            fixed += 1;
            BACKFILL_REMARK_INFERRED
        };
        let _ = conn.execute(
            "UPDATE cert_issuance SET cert_types = ?, remarks = ?, \
             updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            rusqlite::params![&ctype, remark, crate::helpers::row_i64(r, "id")],
        );
    }
    // 直接写日志表：log_action 依赖请求上下文，迁移跑在那之外。
    let _ = conn.execute(
        "INSERT INTO operation_logs (operator, action, target_type, detail) \
         VALUES ('system', 'migrate', 'cert_issuance', ?)",
        rusqlite::params![format!(
            "订正历史回填的证件种类：共 {} 条，据证照登记推定 {} 条，待核实 {} 条",
            stale.len(), fixed, pending
        )],
    );
}

/// 幂等地补一列：列已存在就什么都不做。
///
/// PRAGMA 对不存在的表返回空集，这时也直接返回——极旧的库可能连 users 表都
/// 没有，对着不存在的表 ALTER 会报错。
fn add_column(conn: &Connection, table: &str, column: &str, typ: &str) {
    let mut stmt = match conn.prepare(&format!("PRAGMA table_info({table})")) {
        Ok(s) => s,
        Err(_) => return,
    };
    let names: Vec<String> = match stmt.query_map([], |r| r.get::<_, String>(1)) {
        Ok(rows) => rows.filter_map(Result::ok).collect(),
        Err(_) => return,
    };
    if !names.is_empty() && !names.iter().any(|n| n == column) {
        let _ = conn.execute(&format!("ALTER TABLE {table} ADD COLUMN {column} {typ}"), []);
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
    ("cert_type", "01", "因私护照", 1), ("cert_type", "02", "往来港澳通行证", 2),
    ("cert_type", "03", "大陆居民往来台湾通行证", 3),
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

#[cfg(test)]
mod tests {
    use super::*;

    fn mem() -> Connection {
        let c = Connection::open_in_memory().unwrap();
        init_schema(&c);
        c
    }

    fn columns(conn: &Connection, table: &str) -> Vec<String> {
        let mut st = conn.prepare(&format!("PRAGMA table_info({table})")).unwrap();
        let rows = st.query_map([], |r| r.get::<_, String>(1)).unwrap();
        rows.filter_map(Result::ok).collect()
    }

    /// 五版共用一个 data.db，users 的建表 DDL 必须逐版一致地带上 full_name。
    #[test]
    fn schema_has_full_name() {
        let c = mem();
        assert!(columns(&c, "users").contains(&"full_name".to_string()));
    }

    /// 迁移每次启动都会跑，重复执行不能报错、也不能把列加两遍。
    #[test]
    fn add_column_is_idempotent() {
        let c = mem();
        run_migrations(&c);
        run_migrations(&c);
        let n = columns(&c, "users").iter().filter(|n| *n == "full_name").count();
        assert_eq!(n, 1, "full_name 列应恰好一列");
    }

    /// 老库补列：模拟一个没有 full_name 的 users 表，启动时应被自动补上。
    #[test]
    fn migration_adds_column_to_legacy_db() {
        let c = Connection::open_in_memory().unwrap();
        c.execute_batch(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT)",
        )
        .unwrap();
        assert!(!columns(&c, "users").contains(&"full_name".to_string()));
        run_migrations(&c);
        assert!(columns(&c, "users").contains(&"full_name".to_string()));
    }

    /// 极旧的库可能连 users 表都没有：PRAGMA 返回空集，此时不能去 ALTER 一张不存在的表。
    #[test]
    fn migration_skips_missing_table() {
        let c = Connection::open_in_memory().unwrap();
        run_migrations(&c); // 不 panic 即通过
        assert!(columns(&c, "users").is_empty());
    }
}


CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT,
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
    intended_cert_type TEXT,
    category TEXT NOT NULL,
    travel_dates TEXT NOT NULL,
    approval_date TEXT,
    need_new_passport TEXT NOT NULL DEFAULT '否',
    passport_no TEXT,
    passport_collect_date TEXT,
    passport_return_date TEXT,
    actual_return_date TEXT,
    trip_status TEXT DEFAULT 'normal',
    cancel_date TEXT,
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
    decontrol_date TEXT,
    cert_handover_date TEXT,
    operator TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sys_submit_unit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact TEXT,
    phone TEXT,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cert_issuance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    travel_id INTEGER REFERENCES travel_details(id),
    personnel_filing_id INTEGER NOT NULL REFERENCES personnel_filing(id),
    holder_name TEXT NOT NULL,
    id_number TEXT,
    cert_types TEXT NOT NULL,
    cert_nos TEXT,
    issue_date TEXT NOT NULL,
    issuer TEXT NOT NULL,
    sign_image BLOB,
    sign_meta TEXT,
    return_date TEXT,
    return_sign_image BLOB,
    return_sign_meta TEXT,
    return_operator TEXT,
    status TEXT NOT NULL DEFAULT 'issued',
    void_reason TEXT,
    remarks TEXT,
    operator TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

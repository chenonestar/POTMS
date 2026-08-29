// 数据库初始化、迁移、种子数据 — 对应 Python 版 database.py
package main

import (
	"database/sql"
	"fmt"
	"log"
	"strings"

	_ "modernc.org/sqlite"
)

var db *sql.DB

// Row 通用行类型：模板中以属性方式访问字段（等价 sqlite3.Row）
type Row map[string]interface{}

func openDB() {
	var err error
	db, err = sql.Open("sqlite", DatabasePath+"?_pragma=journal_mode(WAL)&_pragma=foreign_keys(ON)&_pragma=busy_timeout(5000)")
	if err != nil {
		log.Fatal(err)
	}
	db.SetMaxOpenConns(1) // 单用户系统，串行化避免 SQLITE_BUSY
}

// queryMaps 查询并把每行转为 map（模板与快照通用）
func queryMaps(query string, args ...interface{}) ([]Row, error) {
	rows, err := db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	cols, _ := rows.Columns()
	var out []Row
	for rows.Next() {
		vals := make([]interface{}, len(cols))
		ptrs := make([]interface{}, len(cols))
		for i := range vals {
			ptrs[i] = &vals[i]
		}
		if err := rows.Scan(ptrs...); err != nil {
			return nil, err
		}
		m := Row{}
		for i, c := range cols {
			switch v := vals[i].(type) {
			case []byte:
				m[c] = string(v)
			default:
				m[c] = v
			}
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

func queryOne(query string, args ...interface{}) Row {
	rows, err := queryMaps(query, args...)
	if err != nil || len(rows) == 0 {
		return nil
	}
	return rows[0]
}

func countQuery(query string, args ...interface{}) int64 {
	var n int64
	db.QueryRow(query, args...).Scan(&n)
	return n
}

func lastInsertID(res sql.Result) int64 {
	id, _ := res.LastInsertId()
	return id
}

// ---------------------------------------------------------------------------
// 建表 / 迁移 / 种子（与 Python 版 SCHEMA、run_migrations、seed_data 逐行对应）
// ---------------------------------------------------------------------------
const schemaSQL = `
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
`

func initSchema() {
	if _, err := db.Exec(schemaSQL); err != nil {
		log.Fatal("建表失败: ", err)
	}
}

func runMigrations() {
	// 幂等索引（对应 Python 版 F1 优化）
	for _, idx := range []string{
		"CREATE INDEX IF NOT EXISTS idx_pf_id_number ON personnel_filing(id_number)",
		"CREATE INDEX IF NOT EXISTS idx_pf_status ON personnel_filing(status)",
		"CREATE INDEX IF NOT EXISTS idx_td_pf_id ON travel_details(personnel_filing_id)",
		"CREATE INDEX IF NOT EXISTS idx_cert_pf_id ON certificates(personnel_filing_id)",
		"CREATE INDEX IF NOT EXISTS idx_dec_pf_id ON decontrol_filing(personnel_filing_id)",
		"CREATE INDEX IF NOT EXISTS idx_att_travel_id ON attachments(travel_id)",
		"CREATE INDEX IF NOT EXISTS idx_logs_created_at ON operation_logs(created_at)",
	} {
		db.Exec(idx)
	}

	// 登录账户的真实姓名。
	//
	// 单据上的「经办人」要写真人名字，不能写登录账号——打印出来的领用凭证上
	// 一个 admin，是没法拿去归档的。账号继续用于操作日志（账号是身份标识，
	// 姓名可以改；日志只记姓名的话，改名后历史记录就对不上人了）。
	//
	// 五版共用一个 data.db，库可能是任意一版建的，所以每一版都要能补这一列。
	addColumn("users", "full_name", "TEXT")

	// 证件种类 01 的显示名与证照台账槽位标签对齐：因私护照 → 普通护照。
	// 业务表存的是编码（cert_issuance.cert_types = '01'），改显示值不动任何
	// 业务数据。五版共用一个 data.db，任何一版都要能把老库改过来。
	db.Exec("UPDATE sys_dict SET value = '普通护照' " +
		"WHERE category = 'cert_type' AND code = '01' AND value = '因私护照'")

	// 证件领用记录表（REQ-012，含手写签名）。放在迁移里而不是 schemaSQL：
	// 建表语句要与 Python 版 run_migrations 逐字对齐，五版共用同一个 data.db。
	db.Exec(`CREATE TABLE IF NOT EXISTS cert_issuance (
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
		updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)`)
	for _, idx := range []string{
		"CREATE INDEX IF NOT EXISTS idx_issuance_travel ON cert_issuance(travel_id)",
		"CREATE INDEX IF NOT EXISTS idx_issuance_filing ON cert_issuance(personnel_filing_id)",
		"CREATE INDEX IF NOT EXISTS idx_issuance_status ON cert_issuance(status)",
	} {
		db.Exec(idx)
	}

	// 证件种类字典：seedData 只在首次运行执行，存量库在此补齐
	for _, d := range seedDict {
		if d[0] == "cert_type" {
			db.Exec("INSERT OR IGNORE INTO sys_dict (category, code, value, sort_order) VALUES (?, ?, ?, ?)",
				d[0], d[1], d[2], d[3])
		}
	}

	backfillLegacyIssuance()
}

// certTypeColumns 证件种类代码 → 证照登记表里对应的号码列。
// helpers.go 的 certTypeMap 用的是同一套映射，两处改动须同步。
var certTypeColumns = [3]struct{ code, col string }{
	{"01", "passport_no"}, {"02", "hm_pass_no"}, {"03", "tw_pass_no"},
}

// certNameHints 「地点、证照」自由文本里的证件名称关键字。
// 只认**证件名**不认地名——「香港」既可能持港澳通行证也可能持护照过境，拿地名猜会猜错。
// 顺序即优先级：先长后短。
var certNameHints = []struct {
	code     string
	keywords []string
}{
	{"03", []string{"大陆居民往来台湾", "台湾通行证", "台胞证"}},
	{"02", []string{"往来港澳", "港澳通行证"}},
	{"01", []string{"护照"}},
}

// 回填记录的备注。三个串互不相同，订正迁移靠「备注是否还是旧串」判断是否已处理，
// 改完备注下次启动自然扫不到，不需要额外的版本表。
const (
	backfillRemarkLegacy   = "历史数据回填（证件种类按护照推定，无签名）"
	backfillRemarkInferred = "历史数据回填（证件种类据证照登记推定，无签名）"
	backfillRemarkPending  = "历史数据回填（证件种类待核实，无签名）"
)

// inferCertType 推断一条历史出行记录用的是哪种证件，判不出返回空串。
//
// 原先一律记作普通护照（'01'）。这是个**主动编造**的答案：往来港澳通行证、
// 台湾通行证都被写成护照，而领用凭证是要归档的，错的种类比空着更糟。
//
// 三级判据，从硬到软：
//  1. 出行记录上的证件号码对上证照登记表的哪一列 —— 号码唯一，这条最硬；
//  2. 「地点、证照」里出现的证件名称 —— 号码没填时的退路；
//  3. 该人在证照登记表里只登记了一种证件 —— 那就只能是它。
//
// 三条都不成立时返回空串，宁可留空标「待核实」让人来补，也不替他猜一个。
//
// 遍历该人**所有**证照记录合并三个槽位，不能只取一条：需求文档说证照登记
// 「一行为一人」，但现实里很容易出现「先登记了护照，过一阵办了港澳通行证时
// 没找到原记录，又新建了一条」。只看第一条会连着踩空三级判据，最后自信地
// 答出一个错误答案。
func inferCertType(personnelFilingID interface{}, certNo, destinationPassport string) string {
	var held [3]string
	rows, err := queryMaps(
		"SELECT passport_no, hm_pass_no, tw_pass_no FROM certificates "+
			"WHERE personnel_filing_id = ? ORDER BY id", personnelFilingID)
	if err == nil {
		for _, r := range rows {
			for i, c := range certTypeColumns {
				if held[i] == "" {
					held[i] = strings.TrimSpace(rowStr(r, c.col))
				}
			}
		}
	}

	// ① 证件号匹配
	if no := strings.TrimSpace(certNo); no != "" {
		for i, c := range certTypeColumns {
			if held[i] != "" && held[i] == no {
				return c.code
			}
		}
	}

	// ② 「地点、证照」里的证件名称
	for _, h := range certNameHints {
		for _, kw := range h.keywords {
			if strings.Contains(destinationPassport, kw) {
				return h.code
			}
		}
	}

	// ③ 该人只登记了一种证件
	owned := ""
	count := 0
	for i, c := range certTypeColumns {
		if held[i] != "" {
			owned, count = c.code, count+1
		}
	}
	if count == 1 {
		return owned
	}
	return ""
}

// backfillLegacyIssuance 把「出行表上已有领用日期、却没有领用记录」的历史数据
// 补成一条领用记录（无签名）。幂等：仅对尚无领用记录的 travel_id 回填。
//
// 早期库允许 personnel_filing_id 为空，这类记录无法确定领用人，跳过——其出行表上的
// 领用日期保持原样，不影响既有逾期口径。
func backfillLegacyIssuance() {
	rows, err := queryMaps(
		"SELECT t.id, t.personnel_filing_id, t.name, t.id_number, t.passport_no, " +
			"t.destination_passport, " +
			"t.passport_collect_date, t.passport_return_date, t.operator " +
			"FROM travel_details t " +
			"WHERE t.passport_collect_date IS NOT NULL AND t.passport_collect_date != '' " +
			"  AND t.personnel_filing_id IS NOT NULL " +
			"  AND NOT EXISTS (SELECT 1 FROM cert_issuance c WHERE c.travel_id = t.id)")
	if err != nil {
		return
	}
	for _, r := range rows {
		op := rowStr(r, "operator")
		if op == "" {
			op = "system"
		}
		rdate := rowStr(r, "passport_return_date")
		status, retOp := "issued", interface{}(nil)
		if rdate != "" {
			status, retOp = "returned", op
		}
		var retDate interface{}
		if rdate != "" {
			retDate = rdate
		}
		ctype := inferCertType(r["personnel_filing_id"], rowStr(r, "passport_no"),
			rowStr(r, "destination_passport"))
		remark := backfillRemarkPending
		if ctype != "" {
			remark = backfillRemarkInferred
		}
		db.Exec(
			"INSERT INTO cert_issuance (travel_id, personnel_filing_id, holder_name, id_number, "+
				"cert_types, cert_nos, issue_date, issuer, return_date, return_operator, status, "+
				"remarks, operator) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
			r["id"], r["personnel_filing_id"], rowStr(r, "name"), rowStr(r, "id_number"),
			ctype, rowStr(r, "passport_no"), rowStr(r, "passport_collect_date"), op,
			retDate, retOp, status, remark, op)
	}

	correctLegacyCertTypes()
}

// correctLegacyCertTypes 订正上一版回填留下的错标。
//
// 上面那段回填曾经把 cert_types 一律写成 '01'（普通护照），实际可能是往来港澳
// 通行证或大陆居民往来台湾通行证。而回填带幂等守卫（travel_id 已有记录就跳过），
// 光把上面改对，**对已经回填过的库毫无作用**——错的行会一直躺着。
//
// 判据卡死在回填自己产的行上：备注是那句原文，且没有签名。手工登记的记录有签名、
// 备注也不同，碰不到。改完备注即失配，下次启动自然跳过。
func correctLegacyCertTypes() {
	stale, err := queryMaps(
		"SELECT c.id, c.personnel_filing_id, c.cert_nos, c.travel_id "+
			"FROM cert_issuance c WHERE c.remarks = ? AND c.sign_image IS NULL",
		backfillRemarkLegacy)
	if err != nil || len(stale) == 0 {
		return
	}
	// 动的是业务记录，先留一份改动前的快照。每日备份排在迁移之后，等它就晚了。
	runDailyBackup(true)

	fixed, pending := 0, 0
	for _, r := range stale {
		dest := ""
		if r["travel_id"] != nil {
			dest = rowStr(queryOne(
				"SELECT destination_passport FROM travel_details WHERE id = ?", r["travel_id"]),
				"destination_passport")
		}
		ctype := inferCertType(r["personnel_filing_id"], rowStr(r, "cert_nos"), dest)
		remark := backfillRemarkPending
		if ctype != "" {
			remark, fixed = backfillRemarkInferred, fixed+1
		} else {
			pending++
		}
		db.Exec("UPDATE cert_issuance SET cert_types = ?, remarks = ?, "+
			"updated_at = CURRENT_TIMESTAMP WHERE id = ?", ctype, remark, r["id"])
	}
	// 直接写日志表：logAction 依赖请求上下文，迁移跑在那之外。
	db.Exec("INSERT INTO operation_logs (operator, action, target_type, detail) "+
		"VALUES ('system', 'migrate', 'cert_issuance', ?)",
		fmt.Sprintf("订正历史回填的证件种类：共 %d 条，据证照登记推定 %d 条，待核实 %d 条",
			len(stale), fixed, pending))
}

// addColumn 幂等地补一列：列已存在就什么都不做。
//
// PRAGMA 对不存在的表返回空集，这时也直接返回——极旧的库可能连 users 表都
// 没有，对着不存在的表 ALTER 会报错。
func addColumn(table, column, typ string) {
	rows, err := db.Query("PRAGMA table_info(" + table + ")")
	if err != nil {
		return
	}
	defer rows.Close()
	found, any := false, false
	for rows.Next() {
		var cid int
		var name, ctype string
		var notnull, pk int
		var dflt sql.NullString
		if err := rows.Scan(&cid, &name, &ctype, &notnull, &dflt, &pk); err != nil {
			return
		}
		any = true
		if name == column {
			found = true
		}
	}
	if any && !found {
		db.Exec("ALTER TABLE " + table + " ADD COLUMN " + column + " " + typ)
	}
}

var seedDict = [][4]interface{}{
	{"education", "01", "博士研究生", 1}, {"education", "02", "硕士研究生", 2},
	{"education", "03", "大学本科", 3}, {"education", "04", "大学专科", 4},
	{"education", "05", "中专", 5}, {"education", "06", "高中", 6},
	{"education", "07", "初中及以下", 7},
	{"degree", "01", "博士", 1}, {"degree", "02", "硕士", 2},
	{"degree", "03", "学士", 3}, {"degree", "99", "无", 4},
	{"title", "01", "正高", 1}, {"title", "02", "副高", 2},
	{"title", "03", "中级", 3}, {"title", "04", "初级", 4}, {"title", "99", "无", 5},
	{"rank", "01", "处级", 1}, {"rank", "02", "副处级", 2}, {"rank", "03", "正科", 3},
	{"rank", "04", "副科", 4}, {"rank", "05", "科员", 5}, {"rank", "99", "其他", 6},
	{"political_status", "01", "中共党员", 1}, {"political_status", "02", "中共预备党员", 2},
	{"political_status", "03", "共青团员", 3}, {"political_status", "04", "民革会员", 4},
	{"political_status", "05", "民盟盟员", 5}, {"political_status", "06", "民建会员", 6},
	{"political_status", "07", "民进会员", 7}, {"political_status", "08", "农工党党员", 8},
	{"political_status", "09", "致工党党员", 9}, {"political_status", "10", "九三学社社员", 10},
	{"political_status", "99", "群众", 11},
	{"travel_category", "01", "旅游", 1}, {"travel_category", "02", "探亲", 2},
	{"travel_category", "03", "访友", 3}, {"travel_category", "04", "商务", 4},
	{"travel_category", "05", "留学", 5}, {"travel_category", "99", "其他", 6},
	{"submit_unit_type", "01", "党政机关", 1}, {"submit_unit_type", "02", "金融系统", 2},
	{"submit_unit_type", "03", "教科文卫系统", 3}, {"submit_unit_type", "04", "国有大中型企业单位", 4},
	{"submit_unit_type", "99", "其他单位", 5},
	{"cert_type", "01", "普通护照", 1}, {"cert_type", "02", "往来港澳通行证", 2},
	{"cert_type", "03", "大陆居民往来台湾通行证", 3},
	{"supervisor_unit", "S01", "人事处", 1},
}

func seedData() (firstRun bool) {
	var uid int64
	err := db.QueryRow("SELECT id FROM users WHERE username = 'admin'").Scan(&uid)
	if err == sql.ErrNoRows {
		firstRun = true
		hash, _ := hashPassword("admin123")
		db.Exec("INSERT INTO users (username, password_hash) VALUES (?, ?)", "admin", hash)
	}
	for _, s := range seedDict {
		db.Exec("INSERT OR IGNORE INTO sys_dict (category, code, value, sort_order) VALUES (?, ?, ?, ?)",
			s[0], s[1], s[2], s[3])
	}
	var oid int64
	if db.QueryRow("SELECT id FROM sys_org LIMIT 1").Scan(&oid) == sql.ErrNoRows {
		for _, o := range [][4]interface{}{
			{1, "总部", 0, 1}, {2, "办公室", 1, 1}, {3, "人事处", 1, 2},
			{4, "财务处", 1, 3}, {5, "业务一部", 1, 4}, {6, "业务二部", 1, 5},
		} {
			db.Exec("INSERT INTO sys_org (id, name, parent_id, sort_order) VALUES (?, ?, ?, ?)",
				o[0], o[1], o[2], o[3])
		}
	}
	return firstRun
}

func placeholders(n int) string {
	if n == 0 {
		return ""
	}
	s := "?"
	for i := 1; i < n; i++ {
		s += ",?"
	}
	return s
}

var _ = fmt.Sprintf

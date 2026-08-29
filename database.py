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
    # 人事主管单位（下拉配置，可在数据字典维护）
    ("supervisor_unit", "S01", "人事处", 1),
    # 证件种类（证件领用登记用；与 certificates 表的三类证件一一对应）
    # 与 certificates 表的槽位标签一字不差：那边叫「普通护照」，这里就不能叫
    # 「因私护照」。同一本证两个叫法，只要有人写一段按名称匹配的代码（导入校验、
    # 报表归类、跨版本对齐），立刻就是个真 bug。
    ("cert_type", "01", "普通护照", 1),
    ("cert_type", "02", "往来港澳通行证", 2),
    ("cert_type", "03", "大陆居民往来台湾通行证", 3),
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


# ---------------------------------------------------------------------------
# 历史领用记录的证件种类推断
# ---------------------------------------------------------------------------
# 证照登记表用三个独立字段存三种证件，与证件种类字典的对应关系。
# utils/helpers.py 里的 cert_type_map 用的是同一套映射，两处改动须同步。
_CERT_TYPE_COLUMNS = (("01", "passport_no"), ("02", "hm_pass_no"), ("03", "tw_pass_no"))

# 「地点、证照」是自由文本（如「美国-护照」「香港/港澳通行证」）。只认**证件名称**，
# 不认地名——「香港」既可能持港澳通行证也可能持护照过境，拿地名猜会猜错。
# 顺序即优先级：先长后短，免得「大陆居民往来台湾通行证」被「护照」之外的短词抢走。
_CERT_NAME_HINTS = (
    ("03", ("大陆居民往来台湾", "台湾通行证", "台胞证")),
    ("02", ("往来港澳", "港澳通行证")),
    ("01", ("护照",)),
)

# 回填记录的备注。三个串互不相同，订正迁移靠「备注是否还是旧串」判断是否已处理，
# 改完备注下次启动自然扫不到，不需要额外的版本表。
BACKFILL_REMARK_LEGACY = "历史数据回填（证件种类按护照推定，无签名）"
BACKFILL_REMARK_INFERRED = "历史数据回填（证件种类据证照登记推定，无签名）"
BACKFILL_REMARK_PENDING = "历史数据回填（证件种类待核实，无签名）"


def infer_cert_type(db, personnel_filing_id, cert_no, destination_passport) -> str:
    """推断一条历史出行记录用的是哪种证件，判不出返回空串。

    原先一律记作普通护照（'01'）。这是个**主动编造**的答案：往来港澳通行证、
    台湾通行证都被写成护照，而领用凭证是要归档的，错的种类比空着更糟。

    三级判据，从硬到软：

    1. 出行记录上的证件号码对上证照登记表的哪一列 —— 号码是唯一的，这条最硬；
    2. 「地点、证照」里出现的证件名称 —— 号码没填时的退路；
    3. 该人在证照登记表里只登记了一种证件 —— 那就只能是它。

    三条都不成立时返回空串（例如三本证都有、出行记录没填号码、文字里也没写
    证件名）。此时数据里确实没有信息，宁可留空标「待核实」让人来补，
    也不替他猜一个。
    """
    # 遍历该人**所有**证照记录合并三个槽位，不能只取一条。
    #
    # 需求文档说证照登记「一行为一人」，但代码从未拦过重复，现实里很容易出现
    # 「先登记了护照，过一阵办了港澳通行证时没找到原记录，又新建了一条」。
    # 只取第一条会连着踩空三级判据：第①级拿不到港澳号码所以对不上，第③级
    # 又因为那条里「只有护照」而自信地答出 01——**给出一个错误答案，比判不出
    # 更糟**，恰恰是这个函数当初要纠正的毛病。
    # utils/helpers.py 的 cert_type_map 本来就是跨行合并的，此处与之对齐。
    held = [None, None, None]
    for row in db.execute(
            "SELECT passport_no, hm_pass_no, tw_pass_no FROM certificates "
            "WHERE personnel_filing_id = ? ORDER BY id", (personnel_filing_id,)).fetchall():
        for i, v in enumerate(row):
            if held[i] is None and v and str(v).strip():
                held[i] = v

    # ① 证件号匹配
    no = (cert_no or "").strip()
    if no:
        for (code, _col), v in zip(_CERT_TYPE_COLUMNS, held):
            if v and v.strip() == no:
                return code

    # ② 「地点、证照」里的证件名称
    text = destination_passport or ""
    for code, keywords in _CERT_NAME_HINTS:
        if any(k in text for k in keywords):
            return code

    # ③ 该人只登记了一种证件
    owned = [code for (code, _col), v in zip(_CERT_TYPE_COLUMNS, held) if v and v.strip()]
    if len(owned) == 1:
        return owned[0]

    return ""


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
        # 出国明细：实际回国日期 / 行程状态 / 取消日期（逾期口径修正 + 行程取消）
        if "actual_return_date" not in travel_cols:
            db.execute("ALTER TABLE travel_details ADD COLUMN actual_return_date TEXT")
        if "trip_status" not in travel_cols:
            db.execute("ALTER TABLE travel_details ADD COLUMN trip_status TEXT DEFAULT 'normal'")
            db.commit()
            db.execute("UPDATE travel_details SET trip_status = 'normal' "
                       "WHERE trip_status IS NULL OR trip_status = ''")
        if "cancel_date" not in travel_cols:
            db.execute("ALTER TABLE travel_details ADD COLUMN cancel_date TEXT")

        # 操作日志：变更前后数据快照（JSON）
        log_cols = {row[1] for row in db.execute("PRAGMA table_info(operation_logs)").fetchall()}
        if "snapshot" not in log_cols:
            db.execute("ALTER TABLE operation_logs ADD COLUMN snapshot TEXT")

        # 登录账户的真实姓名。
        #
        # 单据上的「经办人」要写真人名字，不能写登录账号——打印出来的领用凭证上
        # 一个 admin，是没法拿去归档的。账号继续用于操作日志（账号是身份标识，
        # 姓名可以改；日志只记姓名的话，改名后历史记录就对不上人了）。
        # PRAGMA 对不存在的表返回空集，直接 ALTER 会炸——极旧的库可能连 users 表
        # 都没有（迁移用例就构造了这种形态），所以先确认表在不在。
        user_cols = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        if user_cols and "full_name" not in user_cols:
            db.execute("ALTER TABLE users ADD COLUMN full_name TEXT")

        # 撤控：证件移交日期 / 撤控日期
        dec_cols = {row[1] for row in db.execute("PRAGMA table_info(decontrol_filing)").fetchall()}
        if "cert_handover_date" not in dec_cols:
            db.execute("ALTER TABLE decontrol_filing ADD COLUMN cert_handover_date TEXT")
        if "decontrol_date" not in dec_cols:
            db.execute("ALTER TABLE decontrol_filing ADD COLUMN decontrol_date TEXT")
            db.commit()
            # 历史记录用 created_at 的日期回填
            db.execute(
                "UPDATE decontrol_filing SET decontrol_date = strftime('%Y%m%d', created_at) "
                "WHERE decontrol_date IS NULL OR decontrol_date = ''")

        # 证件种类 01 的显示名与证照台账槽位标签对齐：因私护照 → 普通护照。
        # 业务表存的是编码（cert_issuance.cert_types = '01'），改显示值不动任何
        # 业务数据；只有还叫旧名的库需要跟一下，改过或已是新名的库不受影响。
        db.execute("UPDATE sys_dict SET value = '普通护照' "
                   "WHERE category = 'cert_type' AND code = '01' AND value = '因私护照'")

        # 报送单位配置表（名称/联系人/电话）
        db.execute(
            "CREATE TABLE IF NOT EXISTS sys_submit_unit ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
            "contact TEXT, phone TEXT, sort_order INTEGER DEFAULT 0)")

        # 证件领用记录表（含手写签名）
        db.execute(
            "CREATE TABLE IF NOT EXISTS cert_issuance ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "travel_id INTEGER REFERENCES travel_details(id), "
            "personnel_filing_id INTEGER NOT NULL REFERENCES personnel_filing(id), "
            "holder_name TEXT NOT NULL, id_number TEXT, "
            "cert_types TEXT NOT NULL, cert_nos TEXT, "
            "issue_date TEXT NOT NULL, issuer TEXT NOT NULL, "
            "sign_image BLOB, sign_meta TEXT, "
            "return_date TEXT, return_sign_image BLOB, return_sign_meta TEXT, "
            "return_operator TEXT, "
            "status TEXT NOT NULL DEFAULT 'issued', void_reason TEXT, remarks TEXT, "
            "operator TEXT NOT NULL, "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_issuance_travel ON cert_issuance(travel_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_issuance_filing ON cert_issuance(personnel_filing_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_issuance_status ON cert_issuance(status)")

        # 证件种类字典（seed_data 仅首次运行执行，存量库在此补齐）
        for _cat, _code, _val, _ord in SEED_DICT:
            if _cat == "cert_type":
                db.execute(
                    "INSERT OR IGNORE INTO sys_dict (category, code, value, sort_order) "
                    "VALUES (?, ?, ?, ?)", (_cat, _code, _val, _ord))

        db.commit()

        # 历史回填：已有「证件领用日期」的出行记录 → 生成对应领用记录（无签名）。
        # 幂等守卫：仅对尚无领用记录的 travel_id 回填。
        # 早期库允许 personnel_filing_id 为空，此类记录无法确定领用人，跳过回填
        # （其出行表上的领用日期保持原样，不影响既有逾期口径）。
        legacy_issue = db.execute(
            "SELECT t.id, t.personnel_filing_id, t.name, t.id_number, t.passport_no, "
            "       t.passport_collect_date, t.passport_return_date, t.operator "
            "FROM travel_details t "
            "WHERE t.passport_collect_date IS NOT NULL AND t.passport_collect_date != '' "
            "  AND t.personnel_filing_id IS NOT NULL "
            "  AND NOT EXISTS (SELECT 1 FROM cert_issuance c WHERE c.travel_id = t.id)"
        ).fetchall()
        for tid, pfid, nm, idn, pno, cdate, rdate, op in legacy_issue:
            dest = db.execute(
                "SELECT destination_passport FROM travel_details WHERE id = ?", (tid,)).fetchone()
            ctype = infer_cert_type(db, pfid, pno, dest[0] if dest else "")
            db.execute(
                "INSERT INTO cert_issuance (travel_id, personnel_filing_id, holder_name, id_number, "
                "cert_types, cert_nos, issue_date, issuer, return_date, return_operator, status, "
                "remarks, operator) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tid, pfid, nm or "", idn or "", ctype, pno or "", cdate,
                 op or "system", rdate or None, (op or "system") if rdate else None,
                 "returned" if rdate else "issued",
                 BACKFILL_REMARK_INFERRED if ctype else BACKFILL_REMARK_PENDING,
                 op or "system"))
        if legacy_issue:
            db.commit()

        # 订正上一版回填留下的错标。
        #
        # 上面那段回填曾经把 cert_types 一律写成 '01'（普通护照），实际可能是往来
        # 港澳通行证或大陆居民往来台湾通行证。而回填带幂等守卫（travel_id 已有记录
        # 就跳过），光把上面改对，**对已经回填过的库毫无作用**——错的行会一直躺着。
        #
        # 判据卡死在回填自己产的行上：备注是那句原文，且没有签名。手工登记的记录
        # 有签名、备注也不同，碰不到。改完备注即失配，下次启动自然跳过。
        #
        # 注：判不出的行 cert_types 置空。五版共用同一个 data.db，另外四版目前会把
        # 空值显示成空白（不报错）——待它们各自补上「待核实」呈现。
        stale = db.execute(
            "SELECT c.id, c.personnel_filing_id, c.cert_nos, c.travel_id "
            "FROM cert_issuance c WHERE c.remarks = ? AND c.sign_image IS NULL",
            (BACKFILL_REMARK_LEGACY,)).fetchall()
        if stale:
            # 动的是业务记录，先留一份改动前的快照。create_app 里的每日备份排在
            # 迁移之后，等它就晚了；而且每日备份同一天会被覆盖，这份要能一直
            # 指向「这次订正之前」那个状态，所以用独立的带时间戳快照。
            try:
                from utils.backup import snapshot_before_change
                snapshot_before_change("migrate_cert_types")
            except Exception:
                pass
            fixed = pending = 0
            for cid, pfid, cnos, tid in stale:
                dest = db.execute(
                    "SELECT destination_passport FROM travel_details WHERE id = ?",
                    (tid,)).fetchone() if tid else None
                ctype = infer_cert_type(db, pfid, cnos, dest[0] if dest else "")
                db.execute(
                    "UPDATE cert_issuance SET cert_types = ?, remarks = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (ctype,
                     BACKFILL_REMARK_INFERRED if ctype else BACKFILL_REMARK_PENDING,
                     cid))
                if ctype:
                    fixed += 1
                else:
                    pending += 1
            # 直接写日志表：log_action 依赖 Flask 的应用上下文与 request，
            # 迁移跑在那之外。
            db.execute(
                "INSERT INTO operation_logs (operator, action, target_type, detail) "
                "VALUES ('system', 'migrate', 'cert_issuance', ?)",
                (f"订正历史回填的证件种类：共 {len(stale)} 条，"
                 f"据证照登记推定 {fixed} 条，待核实 {pending} 条",))
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

        # 统一"计划出行日期"存储格式为 YYYY/MM/DD-YYYY/MM/DD（转换历史 - 分隔写法）
        # 转换后含 '/'，故以 NOT LIKE '%/%' 作幂等守卫，后续启动不再重复处理
        from utils.validators import parse_travel_range, format_travel_range
        legacy = db.execute(
            "SELECT id, travel_dates FROM travel_details "
            "WHERE travel_dates IS NOT NULL AND travel_dates != '' AND travel_dates NOT LIKE '%/%'"
        ).fetchall()
        for tid, td in legacy:
            s, e = parse_travel_range(td or "")
            canon = format_travel_range(s, e)
            if canon:
                db.execute("UPDATE travel_details SET travel_dates=? WHERE id=?", (canon, tid))
        if legacy:
            db.commit()

        # 引导"人事主管单位"字典：把已有记录中的去重值补入字典（幂等）
        existing = {r[0] for r in db.execute(
            "SELECT value FROM sys_dict WHERE category = 'supervisor_unit'").fetchall()}
        distinct = db.execute(
            "SELECT DISTINCT supervisor_unit FROM personnel_filing "
            "WHERE supervisor_unit IS NOT NULL AND supervisor_unit != '' "
            "UNION SELECT DISTINCT supervisor_unit FROM decontrol_filing "
            "WHERE supervisor_unit IS NOT NULL AND supervisor_unit != ''"
        ).fetchall()
        maxn = 0
        for r in db.execute("SELECT code FROM sys_dict WHERE category = 'supervisor_unit'").fetchall():
            cc = r[0] or ""
            if cc.startswith("S") and cc[1:].isdigit():
                maxn = max(maxn, int(cc[1:]))
        order = len(existing)
        for (val,) in distinct:
            if val not in existing:
                maxn += 1
                order += 1
                db.execute(
                    "INSERT OR IGNORE INTO sys_dict (category, code, value, sort_order) "
                    "VALUES ('supervisor_unit', ?, ?, ?)", (f"S{maxn:02d}", val, order))
                existing.add(val)

        # 引导"报送单位"配置：从已有撤控记录补齐（名称去重，带联系人/电话）
        su_existing = {r[0] for r in db.execute("SELECT name FROM sys_submit_unit").fetchall()}
        su_rows = db.execute(
            "SELECT submit_unit_name, submit_contact, submit_phone FROM decontrol_filing "
            "WHERE submit_unit_name IS NOT NULL AND submit_unit_name != '' "
            "GROUP BY submit_unit_name"
        ).fetchall()
        su_order = len(su_existing)
        for name, contact, phone in su_rows:
            if name not in su_existing:
                su_order += 1
                db.execute(
                    "INSERT INTO sys_submit_unit (name, contact, phone, sort_order) VALUES (?, ?, ?, ?)",
                    (name, contact or "", phone or "", su_order))
                su_existing.add(name)
        db.commit()

        # 索引（幂等）：身份证查重、状态过滤、外键关联、日志时间筛选
        # 逐条容错：个别表/列在极旧库中缺失时跳过该条，不影响其余索引
        for idx_sql in (
            "CREATE INDEX IF NOT EXISTS idx_pf_id_number ON personnel_filing(id_number)",
            "CREATE INDEX IF NOT EXISTS idx_pf_status ON personnel_filing(status)",
            "CREATE INDEX IF NOT EXISTS idx_td_pf_id ON travel_details(personnel_filing_id)",
            "CREATE INDEX IF NOT EXISTS idx_cert_pf_id ON certificates(personnel_filing_id)",
            "CREATE INDEX IF NOT EXISTS idx_dec_pf_id ON decontrol_filing(personnel_filing_id)",
            "CREATE INDEX IF NOT EXISTS idx_att_travel_id ON attachments(travel_id)",
            "CREATE INDEX IF NOT EXISTS idx_logs_created_at ON operation_logs(created_at)",
        ):
            try:
                db.execute(idx_sql)
            except sqlite3.OperationalError:
                pass
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
"""

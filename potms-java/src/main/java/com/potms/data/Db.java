package com.potms.data;

import com.potms.Config;
import com.potms.util.TravelDates;
import java.nio.file.Files;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import javax.sql.DataSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * 数据访问入口 — 对应 Python 版 database.py。
 *
 * <p>刻意不使用 JPA/Hibernate：它会引入自己的元数据表并接管 schema，
 * 破坏五个语言版本共用同一个 data.db 的前提。这里只用 JdbcTemplate
 * 这层薄封装，配合由 database.py 生成的常量 DDL + 幂等 migrate()，
 * 与 Go / Rust / .NET 三版的做法保持一致。
 */
@Component
public class Db {

    private final Config cfg;
    private final DataSource dataSource;
    private final JdbcTemplate jdbc;

    public Db(Config cfg) {
        this.cfg = cfg;
        // 必须用连接池而非 DriverManagerDataSource：后者每条语句新开一个连接，
        // 会造成两个隐蔽故障——
        //   1) SQLite 的 PRAGMA foreign_keys 是「逐连接」设置，一次性执行等于没开，
        //      所有删除守卫赖以生效的外键约束会全程失效；
        //   2) last_insert_rowid() 落在另一条连接上，永远返回 0。
        // 这里用连接池 + connectionInitSql，保证每条连接都开启外键。
        var hikari = new com.zaxxer.hikari.HikariConfig();
        hikari.setJdbcUrl(cfg.jdbcUrl());
        hikari.setDriverClassName("org.sqlite.JDBC");
        hikari.setConnectionInitSql("PRAGMA foreign_keys=ON");
        hikari.setMaximumPoolSize(4);        // 单用户系统，够用且避免 SQLite 写锁竞争
        hikari.setPoolName("potms-sqlite");
        this.dataSource = new com.zaxxer.hikari.HikariDataSource(hikari);
        this.jdbc = new JdbcTemplate(dataSource);
    }

    /**
     * 插入并返回自增主键。
     *
     * <p>不能用 {@code SELECT last_insert_rowid()} —— 连接池下那条查询未必落在
     * 刚写入的连接上。必须走 JDBC 的 getGeneratedKeys()，由驱动在同一连接内取回。
     */
    public long insert(String sql, Object... params) {
        var holder = new org.springframework.jdbc.support.GeneratedKeyHolder();
        jdbc.update(cn -> {
            var ps = cn.prepareStatement(sql, java.sql.Statement.RETURN_GENERATED_KEYS);
            for (int i = 0; i < params.length; i++) {
                ps.setObject(i + 1, params[i]);
            }
            return ps;
        }, holder);
        Number key = holder.getKey();
        if (key == null) {
            throw new IllegalStateException("插入后未取到自增主键: " + sql);
        }
        return key.longValue();
    }

    public JdbcTemplate jdbc() {
        return jdbc;
    }

    public DataSource dataSource() {
        return dataSource;
    }

    /** 数据库文件不存在或为空 → 首次运行。 */
    public boolean isFirstRun() {
        try {
            return !Files.exists(cfg.database) || Files.size(cfg.database) == 0;
        } catch (java.io.IOException e) {
            return true;
        }
    }

    /** 建表（DDL 由 database.py 生成，五版逐字节一致）。 */
    public void initialize() {
        try (Connection cn = DriverManager.getConnection(cfg.jdbcUrl());
             Statement st = cn.createStatement()) {
            st.executeUpdate("PRAGMA foreign_keys=ON");
            for (String stmt : Schema.ddl().split(";")) {
                if (!stmt.isBlank()) {
                    st.executeUpdate(stmt);
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("初始化数据库失败", e);
        }
    }

    /** 写入种子数据（幂等）：管理员、数据字典、组织架构。 */
    public void seedData(java.util.function.Function<String, String> hashPassword) {
        Integer n = jdbc.queryForObject(
                "SELECT COUNT(*) FROM users WHERE username = ?", Integer.class, "admin");
        if (n == null || n == 0) {
            jdbc.update("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    "admin", hashPassword.apply("admin123"));
        }

        seedDict();

        Integer orgs = jdbc.queryForObject("SELECT COUNT(*) FROM sys_org", Integer.class);
        if (orgs == null || orgs == 0) {
            Object[][] seed = {
                {1, "总部", 0, 1}, {2, "办公室", 1, 1}, {3, "人事处", 1, 2},
                {4, "财务处", 1, 3}, {5, "业务一部", 1, 4}, {6, "业务二部", 1, 5},
            };
            for (Object[] o : seed) {
                jdbc.update("INSERT INTO sys_org (id, name, parent_id, sort_order) VALUES (?, ?, ?, ?)",
                        o[0], o[1], o[2], o[3]);
            }
        }
    }

    private void seedDict() {
        for (Schema.SeedDict d : Schema.SEED_DICT) {
            jdbc.update("INSERT OR IGNORE INTO sys_dict (category, code, value, sort_order) "
                    + "VALUES (?, ?, ?, ?)", d.category(), d.code(), d.value(), d.sortOrder());
        }
    }

    // ------------------------------------------------------------------
    // 轻量迁移 — 逐条对应 Python 版 run_migrations()，全部幂等
    // ------------------------------------------------------------------

    public void migrate() {
        Set<String> infoCols = columns("personnel_info");
        if (!infoCols.contains("id_number")) {
            jdbc.execute("ALTER TABLE personnel_info ADD COLUMN id_number TEXT");
        }

        // 出国明细：规范化的出行起止日期（用于日期区间筛选）
        Set<String> travelCols = columns("travel_details");
        boolean needBackfill = false;
        if (!travelCols.contains("travel_start")) {
            jdbc.execute("ALTER TABLE travel_details ADD COLUMN travel_start TEXT");
            needBackfill = true;
        }
        if (!travelCols.contains("travel_end")) {
            jdbc.execute("ALTER TABLE travel_details ADD COLUMN travel_end TEXT");
            needBackfill = true;
        }
        // 实际回国日期 / 行程状态 / 取消日期（逾期口径修正 + 行程取消）
        if (!travelCols.contains("actual_return_date")) {
            jdbc.execute("ALTER TABLE travel_details ADD COLUMN actual_return_date TEXT");
        }
        if (!travelCols.contains("trip_status")) {
            jdbc.execute("ALTER TABLE travel_details ADD COLUMN trip_status TEXT DEFAULT 'normal'");
            jdbc.update("UPDATE travel_details SET trip_status = 'normal' "
                    + "WHERE trip_status IS NULL OR trip_status = ''");
        }
        if (!travelCols.contains("cancel_date")) {
            jdbc.execute("ALTER TABLE travel_details ADD COLUMN cancel_date TEXT");
        }

        // 操作日志：变更前后数据快照（JSON）
        if (!columns("operation_logs").contains("snapshot")) {
            jdbc.execute("ALTER TABLE operation_logs ADD COLUMN snapshot TEXT");
        }

        // 登录账户的真实姓名。
        //
        // 单据上的「经办人」要写真人名字，不能写登录账号——打印出来的领用凭证上
        // 一个 admin，是没法拿去归档的。账号继续用于操作日志（账号是身份标识，
        // 姓名可以改；日志只记姓名的话，改名后历史记录就对不上人了）。
        //
        // PRAGMA 对不存在的表返回空集，直接 ALTER 会炸——极旧的库可能连 users
        // 表都没有，所以先确认表在不在。
        Set<String> userCols = columns("users");
        if (!userCols.isEmpty() && !userCols.contains("full_name")) {
            jdbc.execute("ALTER TABLE users ADD COLUMN full_name TEXT");
        }

        // 撤控：证件移交日期 / 撤控日期
        Set<String> decCols = columns("decontrol_filing");
        if (!decCols.contains("cert_handover_date")) {
            jdbc.execute("ALTER TABLE decontrol_filing ADD COLUMN cert_handover_date TEXT");
        }
        if (!decCols.contains("decontrol_date")) {
            jdbc.execute("ALTER TABLE decontrol_filing ADD COLUMN decontrol_date TEXT");
            // 历史记录用 created_at 的日期回填
            jdbc.update("UPDATE decontrol_filing SET decontrol_date = strftime('%Y%m%d', created_at) "
                    + "WHERE decontrol_date IS NULL OR decontrol_date = ''");
        }

        // 报送单位配置表
        jdbc.execute("CREATE TABLE IF NOT EXISTS sys_submit_unit ("
                + "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
                + "contact TEXT, phone TEXT, sort_order INTEGER DEFAULT 0)");

        // 证件领用记录表（含手写签名）
        jdbc.execute("CREATE TABLE IF NOT EXISTS cert_issuance ("
                + "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                + "travel_id INTEGER REFERENCES travel_details(id), "
                + "personnel_filing_id INTEGER NOT NULL REFERENCES personnel_filing(id), "
                + "holder_name TEXT NOT NULL, id_number TEXT, "
                + "cert_types TEXT NOT NULL, cert_nos TEXT, "
                + "issue_date TEXT NOT NULL, issuer TEXT NOT NULL, "
                + "sign_image BLOB, sign_meta TEXT, "
                + "return_date TEXT, return_sign_image BLOB, return_sign_meta TEXT, "
                + "return_operator TEXT, "
                + "status TEXT NOT NULL DEFAULT 'issued', void_reason TEXT, remarks TEXT, "
                + "operator TEXT NOT NULL, "
                + "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                + "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)");
        jdbc.execute("CREATE INDEX IF NOT EXISTS idx_issuance_travel ON cert_issuance(travel_id)");
        jdbc.execute("CREATE INDEX IF NOT EXISTS idx_issuance_filing ON cert_issuance(personnel_filing_id)");
        jdbc.execute("CREATE INDEX IF NOT EXISTS idx_issuance_status ON cert_issuance(status)");

        // 国密签章存证表 —— 仅 Java 版写入，是本版相对其它四版的功能增量。
        // 刻意不往 cert_issuance 加列：那张表由 database.py 统一定义、五版共用，
        // 加列会牵动全部版本；独立成表则是纯增量，其它四版对它无感知。
        jdbc.execute("CREATE TABLE IF NOT EXISTS cert_issuance_seal ("
                + "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                + "issuance_id INTEGER NOT NULL REFERENCES cert_issuance(id), "
                + "kind TEXT NOT NULL, "              // issue | return
                + "payload_hash TEXT NOT NULL, "      // SM3(规范化待签数据)
                + "signature TEXT NOT NULL, "         // SM3withSM2 签名值
                + "cert_subject TEXT, cert_serial TEXT, cert_source TEXT, "
                + "signed_at TEXT NOT NULL, "
                + "UNIQUE(issuance_id, kind))");
        jdbc.execute("CREATE INDEX IF NOT EXISTS idx_seal_issuance "
                + "ON cert_issuance_seal(issuance_id)");

        // 字典种子（存量库补齐新增分类，如 cert_type）
        seedDict();

        backfillIssuance();

        // 回填历史出行记录的起止日期
        if (needBackfill) {
            for (var row : jdbc.queryForList("SELECT id, travel_dates FROM travel_details")) {
                var r = TravelDates.parse((String) row.get("travel_dates"));
                jdbc.update("UPDATE travel_details SET travel_start=?, travel_end=? WHERE id=?",
                        r.start(), r.end(), row.get("id"));
            }
        }

        // 统一「计划出行日期」存储格式为 YYYY/MM/DD-YYYY/MM/DD。
        // 转换后含 '/'，以 NOT LIKE '%/%' 作幂等守卫，后续启动不再重复处理。
        for (var row : jdbc.queryForList("SELECT id, travel_dates FROM travel_details "
                + "WHERE travel_dates IS NOT NULL AND travel_dates != '' AND travel_dates NOT LIKE '%/%'")) {
            var r = TravelDates.parse((String) row.get("travel_dates"));
            String canon = TravelDates.format(r.start(), r.end());
            if (!canon.isEmpty()) {
                jdbc.update("UPDATE travel_details SET travel_dates=? WHERE id=?", canon, row.get("id"));
            }
        }

        bootstrapSupervisorUnits();
        bootstrapSubmitUnits();
        createIndexes();
    }

    /**
     * 历史回填：已有「证件领用日期」的出行记录 → 生成对应领用记录（无签名）。
     *
     * <p>两重守卫：仅对尚无领用记录的 travel_id 回填；且早期库允许
     * personnel_filing_id 为空，此类记录无法确定领用人，必须跳过
     * （否则触发 NOT NULL 约束失败）。
     */
    private void backfillIssuance() {
        var rows = jdbc.queryForList(
                "SELECT t.id, t.personnel_filing_id, t.name, t.id_number, t.passport_no, "
                + "       t.passport_collect_date, t.passport_return_date, t.operator "
                + "FROM travel_details t "
                + "WHERE t.passport_collect_date IS NOT NULL AND t.passport_collect_date != '' "
                + "  AND t.personnel_filing_id IS NOT NULL "
                + "  AND NOT EXISTS (SELECT 1 FROM cert_issuance c WHERE c.travel_id = t.id)");
        for (var r : rows) {
            String op = str(r.get("operator"), "system");
            String rdate = str(r.get("passport_return_date"), "");
            boolean returned = !rdate.isEmpty();
            jdbc.update("INSERT INTO cert_issuance (travel_id, personnel_filing_id, holder_name, "
                    + "id_number, cert_types, cert_nos, issue_date, issuer, return_date, "
                    + "return_operator, status, remarks, operator) "
                    + "VALUES (?, ?, ?, ?, '01', ?, ?, ?, ?, ?, ?, ?, ?)",
                    r.get("id"), r.get("personnel_filing_id"),
                    str(r.get("name"), ""), str(r.get("id_number"), ""),
                    str(r.get("passport_no"), ""), r.get("passport_collect_date"), op,
                    returned ? rdate : null, returned ? op : null,
                    returned ? "returned" : "issued",
                    "历史数据回填（证件种类按护照推定，无签名）", op);
        }
    }

    /** 引导「人事主管单位」字典：把已有记录中的去重值补入字典（幂等）。 */
    private void bootstrapSupervisorUnits() {
        Set<String> existing = new HashSet<>(jdbc.queryForList(
                "SELECT value FROM sys_dict WHERE category = 'supervisor_unit'", String.class));
        List<String> distinct = jdbc.queryForList(
                "SELECT DISTINCT supervisor_unit FROM personnel_filing "
                + "WHERE supervisor_unit IS NOT NULL AND supervisor_unit != '' "
                + "UNION SELECT DISTINCT supervisor_unit FROM decontrol_filing "
                + "WHERE supervisor_unit IS NOT NULL AND supervisor_unit != ''", String.class);

        int maxn = 0;
        for (String cc : jdbc.queryForList(
                "SELECT code FROM sys_dict WHERE category = 'supervisor_unit'", String.class)) {
            if (cc != null && cc.startsWith("S") && cc.length() > 1
                    && cc.substring(1).chars().allMatch(Character::isDigit)) {
                maxn = Math.max(maxn, Integer.parseInt(cc.substring(1)));
            }
        }
        int order = existing.size();
        for (String val : distinct) {
            if (!existing.contains(val)) {
                maxn++;
                order++;
                jdbc.update("INSERT OR IGNORE INTO sys_dict (category, code, value, sort_order) "
                        + "VALUES ('supervisor_unit', ?, ?, ?)", String.format("S%02d", maxn), val, order);
                existing.add(val);
            }
        }
    }

    /** 引导「报送单位」配置：从已有撤控记录补齐（名称去重，带联系人/电话）。 */
    private void bootstrapSubmitUnits() {
        Set<String> existing = new HashSet<>(jdbc.queryForList(
                "SELECT name FROM sys_submit_unit", String.class));
        var rows = jdbc.queryForList(
                "SELECT submit_unit_name, submit_contact, submit_phone FROM decontrol_filing "
                + "WHERE submit_unit_name IS NOT NULL AND submit_unit_name != '' "
                + "GROUP BY submit_unit_name");
        int order = existing.size();
        for (var r : rows) {
            String name = (String) r.get("submit_unit_name");
            if (!existing.contains(name)) {
                order++;
                jdbc.update("INSERT INTO sys_submit_unit (name, contact, phone, sort_order) "
                        + "VALUES (?, ?, ?, ?)", name,
                        str(r.get("submit_contact"), ""), str(r.get("submit_phone"), ""), order);
                existing.add(name);
            }
        }
    }

    /** 索引（幂等）。逐条容错：个别表/列在极旧库中缺失时跳过该条，不影响其余索引。 */
    private void createIndexes() {
        String[] idx = {
            "CREATE INDEX IF NOT EXISTS idx_pf_id_number ON personnel_filing(id_number)",
            "CREATE INDEX IF NOT EXISTS idx_pf_status ON personnel_filing(status)",
            "CREATE INDEX IF NOT EXISTS idx_td_pf_id ON travel_details(personnel_filing_id)",
            "CREATE INDEX IF NOT EXISTS idx_cert_pf_id ON certificates(personnel_filing_id)",
            "CREATE INDEX IF NOT EXISTS idx_dec_pf_id ON decontrol_filing(personnel_filing_id)",
            "CREATE INDEX IF NOT EXISTS idx_att_travel_id ON attachments(travel_id)",
            "CREATE INDEX IF NOT EXISTS idx_logs_created_at ON operation_logs(created_at)",
        };
        for (String sql : idx) {
            try {
                jdbc.execute(sql);
            } catch (org.springframework.dao.DataAccessException ignored) {
                // 极旧库缺表/缺列，跳过
            }
        }
    }

    private Set<String> columns(String table) {
        Set<String> cols = new HashSet<>();
        try (Connection cn = DriverManager.getConnection(cfg.jdbcUrl());
             Statement st = cn.createStatement();
             ResultSet rs = st.executeQuery("PRAGMA table_info(" + table + ")")) {
            while (rs.next()) {
                cols.add(rs.getString("name"));
            }
        } catch (SQLException e) {
            throw new IllegalStateException("读取表结构失败: " + table, e);
        }
        return cols;
    }

    private static String str(Object o, String dflt) {
        if (o == null) {
            return dflt;
        }
        String s = o.toString();
        return s.isEmpty() ? dflt : s;
    }

    /** 供测试与工具使用：一次性取出所有表名。 */
    public List<String> tableNames() {
        return new ArrayList<>(jdbc.queryForList(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                + "ORDER BY name", String.class));
    }
}

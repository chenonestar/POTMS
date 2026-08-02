package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.potms.data.Db;
import com.potms.data.Schema;
import com.potms.service.Security;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Schema 与迁移的守护测试。
 *
 * <p>五个语言版本共用同一个 data.db，建表结果必须稳定；这些用例在 schema
 * 意外漂移时先失败。
 */
class SchemaParityTest {

    private Path dir;
    private Db db;

    /** database.py 定义、五版共用的对象（表 + 索引）。 */
    private static final List<String> SHARED_TABLES = List.of(
            "users", "personnel_info", "personnel_filing", "certificates", "travel_details",
            "decontrol_filing", "attachments", "sys_dict", "sys_org", "operation_logs");

    /** 迁移期建立、同样五版共用的表。 */
    private static final List<String> MIGRATED_TABLES = List.of("sys_submit_unit", "cert_issuance");

    /** 仅 Java 版写入的增量表，其它四版对它无感知。 */
    private static final String JAVA_ONLY_TABLE = "cert_issuance_seal";

    @BeforeEach
    void setUp() throws IOException {
        dir = Files.createTempDirectory("potms-schema-");
        var cfg = new Config(dir);
        db = new Db(cfg);
        db.initialize();
        db.seedData(Security::hashPassword);
        db.migrate();
    }

    @AfterEach
    void tearDown() throws IOException {
        try (var s = Files.walk(dir)) {
            s.sorted(java.util.Comparator.reverseOrder()).forEach(p -> {
                try {
                    Files.deleteIfExists(p);
                } catch (IOException ignored) {
                    // 临时目录清理失败不影响结论
                }
            });
        }
    }

    @Test
    @DisplayName("建表：五版共用的表全部存在")
    void createsSharedTables() {
        var actual = db.tableNames();
        for (String t : SHARED_TABLES) {
            assertTrue(actual.contains(t), "缺少共用表 " + t);
        }
        for (String t : MIGRATED_TABLES) {
            assertTrue(actual.contains(t), "缺少迁移建立的共用表 " + t);
        }
    }

    @Test
    @DisplayName("Java 独有的签章表不影响四版共用")
    void javaOnlyTableIsAdditive() {
        assertTrue(db.tableNames().contains(JAVA_ONLY_TABLE));
        // 关键：签章存在独立表里，cert_issuance 本身没有被加列
        var cols = db.jdbc().queryForList("SELECT * FROM cert_issuance WHERE 1=0");
        assertTrue(cols.isEmpty());
        var meta = db.jdbc().queryForList("PRAGMA table_info(cert_issuance)");
        var names = meta.stream().map(m -> String.valueOf(m.get("name"))).toList();
        assertFalse(names.contains("signature"), "签章字段不得混入共用表");
        assertFalse(names.contains("payload_hash"), "签章字段不得混入共用表");
    }

    @Test
    @DisplayName("种子数据：管理员 / 字典 / 组织")
    void seeds() {
        assertEquals(1, count("SELECT COUNT(*) FROM users WHERE username = 'admin'"));
        assertEquals(Schema.SEED_DICT.length, count("SELECT COUNT(*) FROM sys_dict"));
        assertEquals(6, count("SELECT COUNT(*) FROM sys_org"));
        // 领用模块依赖的证件种类字典必须齐备
        assertEquals(3, count("SELECT COUNT(*) FROM sys_dict WHERE category = 'cert_type'"));
    }

    @Test
    @DisplayName("管理员初始密码为 bcrypt，且能被验证")
    void adminPasswordIsBcrypt() {
        String hash = db.jdbc().queryForObject(
                "SELECT password_hash FROM users WHERE username='admin'", String.class);
        assertTrue(hash != null && hash.startsWith("$2"), "应为 bcrypt 格式");
        assertTrue(Security.verifyPassword("admin123", hash).matched());
    }

    @Test
    @DisplayName("迁移幂等：重复执行不报错、不产生重复数据")
    void migrateIsIdempotent() {
        long dictBefore = count("SELECT COUNT(*) FROM sys_dict");
        db.migrate();
        db.migrate();
        assertEquals(dictBefore, count("SELECT COUNT(*) FROM sys_dict"));
        assertEquals(1, count("SELECT COUNT(*) FROM users"));
    }

    /**
     * 早期库允许 travel_details.personnel_filing_id 为空，这类记录无法确定领用人。
     * 回填必须跳过它们，否则触发 NOT NULL 约束失败——Python 版就是这么炸过一次的。
     */
    @Test
    @DisplayName("历史回填：跳过 personnel_filing_id 为空的出行记录")
    void backfillSkipsRowsWithoutFilingId() {
        // 现行 schema 的 personnel_filing_id 是 NOT NULL，插不进空值；
        // 这条守卫针对的是加上该约束之前建的老库，故先还原成老库的表结构。
        makeLegacyTravelTable();
        db.jdbc().execute("DROP TABLE cert_issuance");
        db.jdbc().update(
                "INSERT INTO travel_details (personnel_filing_id, unit, department, name, position, "
                + "id_number, destination_passport, category, travel_dates, operator, "
                + "passport_collect_date) "
                + "VALUES (NULL,'u','d','无主','p','x','德国','因私','2026/01/01','sys','20260101')");
        db.migrate();   // 重建 cert_issuance 并回填
        assertEquals(0, count("SELECT COUNT(*) FROM cert_issuance"),
                "无法确定领用人的记录不应被回填");
    }

    @Test
    @DisplayName("出行日期格式统一：历史「-」写法转为 YYYY/MM/DD-YYYY/MM/DD")
    void normalizesTravelDates() {
        long filingId = insertFiling();
        db.jdbc().update(
                "INSERT INTO travel_details (personnel_filing_id, unit, department, name, position, "
                + "id_number, destination_passport, category, travel_dates, operator) "
                + "VALUES (?,'u','d','甲','p','x','德国','因私','2023-6-20-2023-6-26','sys')", filingId);
        db.migrate();
        String dates = db.jdbc().queryForObject(
                "SELECT travel_dates FROM travel_details WHERE name='甲'", String.class);
        assertEquals("2023/06/20-2023/06/26", dates);
    }

    /** 还原「personnel_filing_id 可为空」的旧表结构，用于验证针对老库的守卫。 */
    private void makeLegacyTravelTable() {
        db.jdbc().execute("DROP TABLE travel_details");
        db.jdbc().execute("CREATE TABLE travel_details ("
                + "id INTEGER PRIMARY KEY AUTOINCREMENT, personnel_filing_id INTEGER, "
                + "unit TEXT NOT NULL, department TEXT NOT NULL, name TEXT NOT NULL, "
                + "position TEXT NOT NULL, title TEXT, id_number TEXT NOT NULL, "
                + "destination_passport TEXT NOT NULL, category TEXT NOT NULL, "
                + "travel_dates TEXT NOT NULL, approval_date TEXT, need_new_passport TEXT, "
                + "passport_no TEXT, passport_collect_date TEXT, passport_return_date TEXT, "
                + "actual_return_date TEXT, trip_status TEXT DEFAULT 'normal', cancel_date TEXT, "
                + "travel_start TEXT, travel_end TEXT, operator TEXT NOT NULL, "
                + "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                + "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)");
    }

    private long insertFiling() {
        return db.insert("INSERT INTO personnel_filing (surname, given_name, gender, birth_date, "
                + "id_number, residence, political_status, work_unit, position_or_title, "
                + "supervisor_unit, operator) VALUES ('甲','某','男','19900101','x','宁波','群众',"
                + "'总部','处级','某某国资委','sys')");
    }

    private long count(String sql) {
        Long n = db.jdbc().queryForObject(sql, Long.class);
        return n == null ? 0 : n;
    }
}

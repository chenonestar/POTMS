package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.potms.data.Db;
import com.potms.service.Security;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 历史回填的证件种类：三级推断 / 存量订正 / 待核实呈现 / 人工更正。
 *
 * <p>原先回填一律把 cert_types 写成 '01'（因私护照）——往来港澳通行证、大陆居民往来
 * 台湾通行证全被标成护照。领用凭证是要归档的，错的种类比空着更糟。
 *
 * <p>五版共用同一个 data.db，本版必须与 Python 版同口径：改对回填还不够，回填带幂等
 * 守卫，已经回填过的库只能靠一支独立的订正迁移才能纠正。
 */
class CertTypeBackfillTest {

    /** (姓名, certificates 填哪一列, 证件号, 出行表填的号, 「地点、证照」, 应判出的种类) */
    private record Case(String name, String slot, String no, String travNo, String dest, String want) {}

    private static final List<Case> CASES = List.of(
            new Case("张三", "passport_no", "E12345678", "E12345678", "美国-护照", "01"),
            new Case("李四", "hm_pass_no", "C87654321", "C87654321", "香港", "02"),
            new Case("王五", "tw_pass_no", "T11112222", "T11112222", "台湾", "03"),
            new Case("赵六", "hm_pass_no", "C40000001", "", "澳门/港澳通行证", "02"),
            new Case("孙七", "passport_no", "E55556666", "", "泰国", "01"));

    private Path dir;
    private Config cfg;
    private Db db;

    @BeforeEach
    void setUp() throws IOException {
        dir = Files.createTempDirectory("potms-backfill-");
        cfg = new Config(dir);
        db = new Db(cfg);
        db.initialize();
        db.seedData(Security::hashPassword);
        // cert_issuance 是在迁移里建的、不在基础 schema 里，先空跑一次把表建出来
        // （此时还没有出行记录，回填无事可做），造完数据再 migrate() 才是被测的那一趟。
        db.migrate();
        com.potms.service.Backup.resetCheckedDate();
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

    /**
     * 造一个「升级前」的库：出行表已有领用日期。
     *
     * <p>withIssuance=true 时先塞入错标的领用记录，模拟已被老版本回填过的存量库——
     * 那正是订正迁移要处理的形态。
     */
    private void seedLegacy(boolean withIssuance) {
        var jdbc = db.jdbc();
        for (int i = 0; i < CASES.size(); i++) {
            Case c = CASES.get(i);
            long id = i + 1;
            jdbc.update("INSERT INTO personnel_filing (id, surname, given_name, gender, birth_date,"
                    + " id_number, residence, political_status, work_unit, position_or_title,"
                    + " supervisor_unit, operator) VALUES (?, ?, '', '男', '19900101',"
                    + " '110101199001012133', '浙江宁波市鄞州区', '群众', '总部', '科长',"
                    + " '人事处', 'admin')", id, c.name());
            jdbc.update("INSERT INTO certificates (personnel_filing_id, unit, department, name, "
                    + c.slot() + ", operator) VALUES (?, '总部', '技术部', ?, ?, 'admin')",
                    id, c.name(), c.no());
            jdbc.update("INSERT INTO travel_details (id, personnel_filing_id, unit, department,"
                    + " name, position, id_number, destination_passport, category, travel_dates,"
                    + " need_new_passport, passport_no, passport_collect_date, operator)"
                    + " VALUES (?, ?, '总部', '技术部', ?, '科长', '110101199001012133', ?, '因私',"
                    + " '2026/03/01-2026/03/10', '否', ?, '20260225', 'admin')",
                    id, id, c.name(), c.dest(), c.travNo());
            if (withIssuance) {
                jdbc.update("INSERT INTO cert_issuance (id, travel_id, personnel_filing_id,"
                        + " holder_name, id_number, cert_types, cert_nos, issue_date, issuer,"
                        + " status, remarks, operator) VALUES (?, ?, ?, ?, '110101199001012133',"
                        + " '01', ?, '20260225', 'admin', 'issued', ?, 'admin')",
                        id, id, id, c.name(), c.travNo(), Db.BACKFILL_REMARK_LEGACY);
            }
        }
    }

    private Map<String, String> stored() {
        Map<String, String> out = new LinkedHashMap<>();
        for (var r : db.jdbc().queryForList("SELECT holder_name, cert_types FROM cert_issuance")) {
            out.put((String) r.get("holder_name"),
                    r.get("cert_types") == null ? "" : r.get("cert_types").toString());
        }
        return out;
    }

    private Map<String, String> remarks() {
        Map<String, String> out = new LinkedHashMap<>();
        for (var r : db.jdbc().queryForList("SELECT holder_name, remarks FROM cert_issuance")) {
            out.put((String) r.get("holder_name"),
                    r.get("remarks") == null ? "" : r.get("remarks").toString());
        }
        return out;
    }

    private void assertAllInferred() {
        var got = stored();
        for (Case c : CASES) {
            assertEquals(c.want(), got.get(c.name()), c.name() + " 的证件种类判错");
        }
    }

    /** 三本证都有、出行表没填号码、文字里也没写证件名——数据里确实没有信息。 */
    private void seedUndeterminable(boolean withIssuance) {
        var jdbc = db.jdbc();
        jdbc.update("INSERT INTO personnel_filing (id, surname, given_name, gender, birth_date,"
                + " id_number, residence, political_status, work_unit, position_or_title,"
                + " supervisor_unit, operator) VALUES (9, '周', '八', '男', '19900101',"
                + " '110101199001012133', '浙江宁波市鄞州区', '群众', '总部', '科长',"
                + " '人事处', 'admin')");
        jdbc.update("INSERT INTO certificates (personnel_filing_id, unit, department, name,"
                + " passport_no, hm_pass_no, tw_pass_no, operator)"
                + " VALUES (9, '总部', '技术部', '周八', 'E9', 'C9', 'T9', 'admin')");
        jdbc.update("INSERT INTO travel_details (id, personnel_filing_id, unit, department, name,"
                + " position, id_number, destination_passport, category, travel_dates,"
                + " need_new_passport, passport_collect_date, operator)"
                + " VALUES (9, 9, '总部', '技术部', '周八', '科长', '110101199001012133',"
                + " '新加坡', '因私', '2026/03/01-2026/03/10', '否', '20260225', 'admin')");
        if (withIssuance) {
            jdbc.update("INSERT INTO cert_issuance (id, travel_id, personnel_filing_id,"
                    + " holder_name, id_number, cert_types, cert_nos, issue_date, issuer,"
                    + " status, remarks, operator) VALUES (9, 9, 9, '周八',"
                    + " '110101199001012133', '01', '', '20260225', 'admin', 'issued', ?, 'admin')",
                    Db.BACKFILL_REMARK_LEGACY);
        }
    }

    // ------------------------------------------------------------------
    // 回填本身（从没回填过的库）
    // ------------------------------------------------------------------
    @Test
    @DisplayName("回填时就判对种类，而不是一律记成护照")
    void backfillInfersRealCertType() {
        seedLegacy(false);
        db.migrate();
        assertAllInferred();
    }

    @Test
    @DisplayName("判不出的留空并在备注里写明待核实，不替他猜一个")
    void backfillMarksUndeterminableAsPending() {
        seedLegacy(false);
        seedUndeterminable(false);
        db.migrate();

        assertEquals("", stored().get("周八"));
        var rm = remarks();
        assertEquals(Db.BACKFILL_REMARK_PENDING, rm.get("周八"));
        assertEquals(Db.BACKFILL_REMARK_INFERRED, rm.get("李四"));
        assertFalse(rm.containsValue(Db.BACKFILL_REMARK_LEGACY), "不该再留下旧备注");
    }

    // ------------------------------------------------------------------
    // 存量订正（已经被老版本回填过的库）
    // ------------------------------------------------------------------
    @Test
    @DisplayName("光把回填改对没用：存量错标行要靠独立的订正迁移")
    void correctionFixesExistingRows() {
        seedLegacy(true);
        assertEquals(java.util.Set.of("01"), new java.util.HashSet<>(stored().values()),
                "前置条件：全是错的");
        db.migrate();
        assertAllInferred();
    }

    @Test
    @DisplayName("订正幂等：跑三遍只留一条日志")
    void correctionIsIdempotent() {
        seedLegacy(true);
        db.migrate();
        var first = Map.copyOf(stored());
        var firstRemarks = Map.copyOf(remarks());

        db.migrate();
        db.migrate();
        assertEquals(first, stored());
        assertEquals(firstRemarks, remarks());

        // 只比对结果不够：备注若没换掉，每次启动都会重跑、重复备份、重复写日志，
        // 而结果恰好相同，比对不出来。直接数日志条数。
        Integer n = db.jdbc().queryForObject("SELECT COUNT(*) FROM operation_logs "
                + "WHERE action='migrate' AND target_type='cert_issuance'", Integer.class);
        assertEquals(1, n, "订正跑了 3 次，日志攒了 " + n + " 条——幂等守卫没生效");
    }

    @Test
    @DisplayName("有签名的记录不被订正改动")
    void correctionNeverTouchesSignedRecords() {
        seedLegacy(true);
        // 把李四那条伪装成「有签名但备注恰好也是旧串」的极端情形
        db.jdbc().update("UPDATE cert_issuance SET sign_image = ? WHERE holder_name = '李四'",
                (Object) new byte[] {(byte) 0x89, 'P', 'N', 'G'});
        db.migrate();

        var got = stored();
        assertEquals("01", got.get("李四"), "有签名的记录不该被订正改动");
        assertEquals("03", got.get("王五"), "无签名的记录照常订正");
    }

    @Test
    @DisplayName("订正前先落备份，并留下操作日志")
    void correctionBacksUpAndLogs() throws IOException {
        seedLegacy(true);
        seedUndeterminable(true);
        db.migrate();

        try (var s = Files.list(cfg.backupFolder)) {
            assertTrue(s.anyMatch(p -> p.getFileName().toString().startsWith("data_")),
                    "订正前应留下备份");
        }
        String detail = db.jdbc().queryForObject("SELECT detail FROM operation_logs "
                + "WHERE action='migrate' AND target_type='cert_issuance'", String.class);
        assertTrue(detail.contains("共 6 条"), "日志摘要不对：" + detail);
        assertTrue(detail.contains("推定 5 条"), "日志摘要不对：" + detail);
        assertTrue(detail.contains("待核实 1 条"), "日志摘要不对：" + detail);
    }
}

package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 人工更正入口与「待核实」的呈现 —— 走 HTTP，和用户看到的是同一条路。
 *
 * <p>没有这个入口，「判不出就留空」等于制造一批永远填不上的死数据：新建强制签名，
 * 回填行没有签名也无从重录，只能就地更正。
 *
 * <p>两条待核实记录各归各的用例，避免互相踩：900 供成功更正，901 只承接被挡回的
 * 提交，因此在筛选用例看来它始终是待核实状态，不依赖用例执行顺序。
 */
class CertTypeCorrectionHttpTest {

    private static PageSmokeTest.AppUnderTest app;

    /** 种子数据里的领用记录 1 是带手写签名的，正好用作「不许改」的对照。 */
    private static final long SIGNED_ID = 1;

    @BeforeAll
    static void start() throws Exception {
        app = PageSmokeTest.AppUnderTest.start(5795, true);
        seedPending(900, "待核实甲");
        seedPending(901, "待核实乙");
    }

    @AfterAll
    static void stop() {
        if (app != null) {
            app.stop();
        }
    }

    /** 回填判不出种类的形态：cert_types 为空串、无签名、备注写着待核实。 */
    private static void seedPending(long id, String name) throws Exception {
        app.sql("INSERT INTO cert_issuance (id, personnel_filing_id, holder_name, id_number, "
                + "cert_types, cert_nos, issue_date, issuer, status, remarks, operator) VALUES ("
                + id + ", 1, '" + name + "', '110101199001012133', '', '', '20260225', "
                + "'admin', 'issued', '" + com.potms.data.Db.BACKFILL_REMARK_PENDING
                + "', 'admin')");
    }

    private static String types(long id) throws Exception {
        return app.queryOne("SELECT cert_types FROM cert_issuance WHERE id = " + id);
    }

    /** 提交更正并跟随重定向，返回落地页 HTML（flash 提示在那上面）。 */
    private static String postCertTypes(long id, String... picked) throws Exception {
        String path = "/issuance/" + id;
        StringBuilder form = new StringBuilder("csrf_token=").append(app.token(path));
        for (String p : picked) {
            form.append("&cert_types=").append(p);
        }
        var res = app.post(path + "/cert-types", form.toString());
        assertEquals(302, res.statusCode(), "更正应重定向回详情页，实际 " + res.statusCode());
        // Location 是绝对地址，而 app.get() 自己拼 base，这里只取路径部分
        String to = res.headers().firstValue("location").orElse(path);
        int slash = to.indexOf('/', to.indexOf("//") + 2);
        return app.get(to.startsWith("http") ? to.substring(slash) : to).body();
    }

    @Test
    @DisplayName("待核实记录可人工补上种类")
    void pendingRowCanBeCorrected() throws Exception {
        assertEquals("", types(900));
        assertTrue(postCertTypes(900, "02").contains("证件种类已更正"), "没有出现成功提示");
        assertEquals("02", types(900));
    }

    @Test
    @DisplayName("有签名的记录不许改：入口不出现，直接提交也挡回")
    void correctionRejectedOnSignedRecord() throws Exception {
        String page = app.get("/issuance/" + SIGNED_ID).body();
        assertFalse(page.contains("更正证件种类"), "有签名的记录不该出现更正入口");
        assertTrue(postCertTypes(SIGNED_ID, "02").contains("不可更改"), "服务端没有挡回");
        assertEquals("01", types(SIGNED_ID), "原值被改动了");
    }

    @Test
    @DisplayName("非法代码 / 空选 / 多选都挡回，不把记录改成更烂的状态")
    void correctionRejectsInvalidEmptyAndMulti() throws Exception {
        assertTrue(postCertTypes(901, "99").contains("无效的证件种类代码"), "非法代码没挡回");
        assertTrue(postCertTypes(901).contains("请选择证件种类"), "空选没挡回");
        assertTrue(postCertTypes(901, "01", "02").contains("只能领用一本证件"), "多选没挡回");
        assertEquals("", types(901), "一次都不该被改坏");
    }

    @Test
    @DisplayName("待核实能筛出来，且列表与详情都写明「待核实」")
    void pendingFilterFindsThemAndShowsBadge() throws Exception {
        // 现有筛选是 (','||cert_types||',') LIKE '%,01,%'，对空值恒不匹配，
        // 筛不出来这批待办就没法收口
        String html = app.get("/issuance?cert_type=pending").body();
        assertTrue(html.contains("待核实乙"), "待核实记录没被筛出来");
        assertFalse(html.contains("史迪威"), "筛选把有种类的记录也带出来了");
        // 列表与详情都要写明「待核实」，空白格子会被当成漏渲染
        assertTrue(html.contains("待核实</span>"), "列表上没有「待核实」标记");
        assertTrue(app.get("/issuance/901").body().contains("待核实</span>"),
                "详情页上没有「待核实」标记");
    }
}

package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.potms.PageSmokeTest.AppUnderTest;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 起一个 POTMS_REQUIRE_SIGNATURE=0 的实例，验证开关真的贯通到了两端。
 *
 * <p>单测层面（SignatureSwitchTest）只能证明 Signature.decode 的分支对；
 * 开关要真起作用，还得从 Config 读到、传进控制器、传进模板。中间任何一环
 * 漏接，单测都照样绿。所以这里跑真进程。
 */
class RelaxedSignatureTest {

    private static AppUnderTest app;

    @BeforeAll
    static void start() throws Exception {
        app = AppUnderTest.start(5793, true, Map.of("POTMS_REQUIRE_SIGNATURE", "0"));
    }

    @AfterAll
    static void stop() {
        if (app != null) {
            app.stop();
        }
    }

    @Test
    @DisplayName("放宽模式下签名板标「可留空」并给出提示")
    void padShowsRelaxedHint() throws Exception {
        String body = app.get("/issuance/new?travel_id=1").body();
        assertTrue(body.contains("可留空"), "签名板未标注「可留空」");
        assertTrue(body.contains("非强制"), "未提示当前为非强制模式");
        assertTrue(body.contains("var signRequired = false"),
                "前端拦截仍按强制模式下发，留空会被浏览器挡住");
    }

    @Test
    @DisplayName("放宽模式下不签名也能提交，库里如实存 NULL")
    void submitsWithoutSignature() throws Exception {
        String id = AppUnderTest.validId();
        // 种子数据里出行 1 已经有一条未归还的领用记录，一次申请只能有一本证在外，
        // 所以另造一条申请来承接本次登记
        app.sql("INSERT INTO travel_details (id, personnel_filing_id, unit, department, name, "
                + "position, id_number, destination_passport, category, travel_dates, "
                + "travel_start, travel_end, operator, need_new_passport, trip_status) "
                + "VALUES (2,1,'总部','办公室','史迪威','处级','" + id + "','法国','因私',"
                + "'2026/10/01-2026/10/10','20261001','20261010','admin','否','normal')");
        var res = app.post("/issuance/new", "csrf_token=" + app.token("/issuance/new?travel_id=2")
                + "&travel_id=2&personnel_filing_id=1&holder_name=" + e("史迪威")
                + "&id_number=" + id + "&cert_types=01&cert_nos=E1234567"
                + "&issue_date=20260803&sign_png=");
        assertEquals(302, res.statusCode(),
                "放宽模式下留空签名应放行，实际被挡回表单页：" + errorsIn(res.body()));

        assertNull(app.queryOne(
                "SELECT sign_image FROM cert_issuance WHERE issue_date = '20260803'"),
                "无签名就该存 NULL，不能凭空造一张图");
    }

    @Test
    @DisplayName("放宽只放开「留空」，坏签名照样拒绝")
    void stillRejectsMalformedSignature() throws Exception {
        var res = app.post("/issuance/new", "csrf_token=" + app.token("/issuance/new?travel_id=1")
                + "&travel_id=1&personnel_filing_id=1&holder_name=" + e("史迪威")
                + "&id_number=" + AppUnderTest.validId()
                + "&cert_types=01&cert_nos=E1234567&issue_date=20260804"
                + "&sign_png=" + e("data:image/jpeg;base64,AAAA"));
        assertNotEquals(302, res.statusCode(), "格式非法的签名不该被放行");
        assertTrue(res.body().contains("签名数据格式不正确"), "未给出格式错误提示");
    }

    @Test
    @DisplayName("404 走中文错误页，不是 Whitelabel")
    void notFoundRendersChinesePage() throws Exception {
        var res = app.get("/no/such/page");
        assertEquals(404, res.statusCode());
        assertTrue(res.body().contains("您访问的页面不存在或已被移除"),
                "404 未渲染中文错误页：" + res.body().substring(0, Math.min(300, res.body().length())));
        assertTrue(res.body().contains("返回首页"));
    }

    /** 从回填的表单页里摘出 flash 报错，便于定位到底卡在哪一条校验。 */
    private static String errorsIn(String html) {
        var m = java.util.regex.Pattern.compile("alert-danger[^>]*>(?:\\s|<[^>]+>)*([^<]+)")
                .matcher(html);
        var sb = new StringBuilder();
        while (m.find()) {
            sb.append(m.group(1).trim()).append(" | ");
        }
        return sb.length() == 0 ? "（页面上没有 alert-danger）" : sb.toString();
    }

    private static String e(String s) {
        return URLEncoder.encode(s, StandardCharsets.UTF_8);
    }
}

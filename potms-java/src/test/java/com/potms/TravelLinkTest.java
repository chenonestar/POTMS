package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 领用必须挂在出国申请上、路径B（做证）的逾期告警、证件号码派生、做证校验。
 *
 * <p>四条规则同源：证件是为某一次已批准的出行借出/办理的。挂不上申请的领用记录是
 * 无主的，还会掉出逾期告警（告警按出行记录算）；路径B 压根没有领用记录（证是本人凭函
 * 去公安办的，从没进过保管处），原来的告警判据「passport_collect_date 非空」对它恒
 * 不成立，整类人不受监管；明细表上的证件号码原先手填，与领用记录各写各的，打印件上
 * 两个格子可能来自不同的证件；一本可用的证都没有却说不做证，这条申请本身就是错的。
 *
 * <p>造数刻意用<b>相对今天</b>的日期，让记录永远处于逾期状态，不依赖跑在哪一天。
 * 各用例共用一个应用实例，所以每条用例只碰自己那条记录，互不干扰。
 */
class TravelLinkTest {

    private static PageSmokeTest.AppUnderTest app;

    private static final long PATH_A = 801;     // 已有证件，走领用
    private static final long PATH_B = 802;     // 做证，没有领用记录
    private static final long FILING_B = 802;   // 名下一本证都没有的备案人
    private static final String ID = "110101199001012133";

    @BeforeAll
    static void start() throws Exception {
        app = PageSmokeTest.AppUnderTest.start(5796, true);
        seed();
    }

    @AfterAll
    static void stop() {
        if (app != null) {
            app.stop();
        }
    }

    private static String ymdDaysAgo(int n) {
        return LocalDate.now().minusDays(n).format(DateTimeFormatter.ofPattern("yyyyMMdd"));
    }

    private static String e(String s) {
        return URLEncoder.encode(s, StandardCharsets.UTF_8);
    }

    /** 两条都已回国 90 天、证都没交回的申请，区别只在是否做证。 */
    private static void seed() throws Exception {
        String ago = ymdDaysAgo(90);
        app.sql("INSERT INTO personnel_filing (id,surname,given_name,gender,birth_date,id_number,"
                + "residence,political_status,work_unit,position_or_title,supervisor_unit,operator) "
                + "VALUES (" + FILING_B + ",'李','四','男','19900101','" + ID + "',"
                + "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')");
        for (Object[] r : new Object[][] {
            {PATH_A, 1L, "路径A张三", "否"},
            {PATH_B, FILING_B, "路径B李四", "是"},
        }) {
            app.sql("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,"
                    + "position,id_number,destination_passport,category,travel_dates,travel_start,"
                    + "travel_end,need_new_passport,actual_return_date,trip_status,operator) VALUES ("
                    + r[0] + "," + r[1] + ",'总部','技术部','" + r[2] + "','科长','" + ID + "',"
                    + "'美国/护照','因私','" + ago + "-" + ago + "','" + ago + "','" + ago + "',"
                    + "'" + r[3] + "','" + ago + "','normal','admin')");
        }
    }

    private static long issuanceCount() throws Exception {
        return Long.parseLong(app.queryOne(
                "SELECT COUNT(*) FROM cert_issuance WHERE travel_id IN (" + PATH_A + "," + PATH_B + ")"));
    }

    /** 提交一条挂在申请 801 上的领用登记，over 里的同名键覆盖默认值。 */
    private static java.net.http.HttpResponse<String> postIssue(String... over) throws Exception {
        var fields = new java.util.LinkedHashMap<String, String>();
        fields.put("travel_id", String.valueOf(PATH_A));
        fields.put("personnel_filing_id", "1");
        fields.put("holder_name", e("路径A张三"));
        fields.put("id_number", ID);
        fields.put("cert_types", "01");
        fields.put("cert_nos", "E12345678");
        fields.put("issue_date", ymdDaysAgo(90));
        fields.put("sign_png", e(PageSmokeTest.AppUnderTest.pngDataUrl()));
        StringBuilder extra = new StringBuilder();
        for (int i = 0; i < over.length; i += 2) {
            if ("cert_types+".equals(over[i])) {
                extra.append("&cert_types=").append(over[i + 1]);   // 追加成多选
            } else {
                fields.put(over[i], over[i + 1]);
            }
        }
        StringBuilder body = new StringBuilder(
                "csrf_token=" + app.token("/issuance/new?travel_id=" + PATH_A));
        fields.forEach((k, v) -> body.append('&').append(k).append('=').append(v));
        body.append(extra);
        return app.post("/issuance/new", body.toString());
    }

    /** 提交结果落地页：成功是 302（跳详情），失败是 200（带 flash 重渲染）。 */
    private static String landing(java.net.http.HttpResponse<String> res) throws Exception {
        if (res.statusCode() != 302) {
            return res.body();
        }
        // Location 是绝对地址，而 app.get() 自己拼 base，这里只取路径部分
        String loc = res.headers().firstValue("location").orElse("/issuance");
        if (loc.startsWith("http")) {
            loc = loc.substring(loc.indexOf('/', loc.indexOf("//") + 2));
        }
        return app.get(loc).body();
    }

    // ------------------------------------------------------------------
    // A1 领用必须挂出国申请
    // ------------------------------------------------------------------
    @Test
    @DisplayName("不挂申请的领用被挡回，且一条都不入库")
    void issueWithoutTravelIsRejected() throws Exception {
        long before = issuanceCount();
        assertTrue(landing(postIssue("travel_id", "")).contains("关联出国申请"), "未提示必须关联出国申请");
        assertEquals(before, issuanceCount(), "无主的领用记录被写进库了");
    }

    @Test
    @DisplayName("挂不存在的申请被挡回")
    void issueWithUnknownTravelIsRejected() throws Exception {
        long before = issuanceCount();
        assertTrue(landing(postIssue("travel_id", "999999")).contains("关联的出国申请不存在"),
                "未校验申请是否存在");
        assertEquals(before, issuanceCount());
    }

    @Test
    @DisplayName("领用人必须就是申请人")
    void holderMustMatchApplicant() throws Exception {
        long before = issuanceCount();
        String html = landing(postIssue(
                "personnel_filing_id", String.valueOf(FILING_B), "holder_name", e("路径B李四")));
        assertTrue(html.contains("与该出国申请的申请人不一致"), "领用人与申请人不一致未被拦下");
        assertEquals(before, issuanceCount());
    }

    @Test
    @DisplayName("一次申请只能领一本证")
    void oneCertPerApplication() throws Exception {
        long before = issuanceCount();
        assertTrue(landing(postIssue("cert_types+", "02")).contains("只能领用一本证件"),
                "一次申请领多本未被拦下");
        assertEquals(before, issuanceCount());
    }

    @Test
    @DisplayName("直接进新建页先选申请")
    void newWithoutTravelIdShowsPicker() throws Exception {
        var res = app.get("/issuance/new");
        assertEquals(200, res.statusCode());
        // 用路径B 那条做断言：路径A 在别的用例里会被登记上领用记录而从可选列表消失，
        // 用例之间的执行顺序不该影响这条
        for (String want : new String[] {"选择出国申请", "登记领用", "路径B李四"}) {
            assertTrue(res.body().contains(want), "选择页缺少「" + want + "」");
        }
    }

    // ------------------------------------------------------------------
    // A2 路径B 的逾期告警
    // ------------------------------------------------------------------
    @Test
    @DisplayName("路径B 未交回也要报逾期，列表与仪表盘都要带上")
    void pathBWithoutRegisteredCertIsOverdue() throws Exception {
        var res = app.get("/travel?passport_status=overdue");
        assertEquals(200, res.statusCode());
        assertTrue(res.body().contains("路径B李四"), "逾期筛选没带上路径B");

        // 仪表盘不能只断言姓名出现——「近期出行」板块本来就会列出这个人，那样即使
        // 逾期统计完全失灵也照样通过。逾期清单那一行姓名后面跟的是应还日期，查它。
        String home = app.get("/").body();
        assertTrue(java.util.regex.Pattern
                        .compile("路径B李四</td>\\s*<td[^>]*>(\\d{8})</td>").matcher(home).find(),
                "仪表盘逾期清单里没有路径B（姓名后面没跟着应还日期）");
    }

    @Test
    @DisplayName("证进了台账就不再告警；只补录号码没入库仍算没交回")
    void pathBClearedOnlyAfterRegistration() throws Exception {
        // 只在明细表补录号码——还没入台账，仍要报
        app.sql("UPDATE travel_details SET passport_no='E99999999' WHERE id=" + PATH_B);
        assertTrue(app.get("/travel?passport_status=overdue").body().contains("路径B李四"),
                "只补录号码未入台账，应仍算逾期");

        // 交回入库、登记进台账之后就不该再告警
        app.sql("INSERT INTO certificates (personnel_filing_id,unit,department,name,"
                + "passport_no,passport_expiry,passport_submit_date,operator) VALUES ("
                + FILING_B + ",'总部','技术部','路径B李四','E99999999','20360101','20260101','admin')");
        assertFalse(app.get("/travel?passport_status=overdue").body().contains("路径B李四"),
                "证已进台账仍在告警");

        // 收尾：把台账那条删掉，不影响别的用例
        app.sql("DELETE FROM certificates WHERE passport_no='E99999999'");
        app.sql("UPDATE travel_details SET passport_no=NULL WHERE id=" + PATH_B);
    }

    // ------------------------------------------------------------------
    // C 证件号码派生
    // ------------------------------------------------------------------
    @Test
    @DisplayName("证件号码由领用记录派生，表单只读且提交不能覆盖")
    void certNoDerivedFromIssuance() throws Exception {
        var res = postIssue("cert_nos", "E77778888");
        assertEquals(302, res.statusCode(), "领用登记失败：" + errorsIn(res.body()));
        assertEquals("E77778888",
                app.queryOne("SELECT passport_no FROM travel_details WHERE id=" + PATH_A),
                "证件号码未从领用记录派生到出行表");

        // 表单上那一栏应变成只读。不能只查页面上有没有 readonly——领用日期、归还日期
        // 两栏本来就是只读的，那样查恒为真。只看 passport_no 这个 input。
        String tag = passportNoInput(app.get("/travel/" + PATH_A + "/edit").body());
        assertTrue(tag.contains("readonly"), "有领用记录时证件号码栏未置为只读：" + tag);

        // 就算绕过只读直接提交，也不能覆盖派生值
        app.post("/travel/" + PATH_A + "/edit",
                "csrf_token=" + app.token("/travel/" + PATH_A + "/edit")
                + "&personnel_filing_id=1&unit=" + e("总部") + "&department=" + e("技术部")
                + "&name=" + e("路径A张三") + "&position=" + e("科长") + "&id_number=" + ID
                + "&destination_passport=" + e("美国-护照") + "&category=" + e("因私")
                + "&travel_dates=2026/09/01-2026/09/11&need_new_passport=" + e("否")
                + "&passport_no=BOGUS999");
        assertEquals("E77778888",
                app.queryOne("SELECT passport_no FROM travel_details WHERE id=" + PATH_A),
                "绕过只读的提交覆盖了派生的证件号码");
    }

    private static String passportNoInput(String html) {
        int i = html.indexOf("name=\"passport_no\"");
        assertTrue(i >= 0, "页面上找不到证件号码输入框");
        int start = html.lastIndexOf("<input", i);
        int end = html.indexOf('>', i);
        return html.substring(start, end + 1);
    }

    // ------------------------------------------------------------------
    // D 做证校验
    // ------------------------------------------------------------------
    private static String postTravel(String needNewPassport) throws Exception {
        return app.post("/travel/new", "csrf_token=" + app.token("/travel/new")
                + "&personnel_filing_id=" + FILING_B + "&unit=" + e("总部")
                + "&department=" + e("技术部") + "&name=" + e("李四") + "&position=" + e("科长")
                + "&id_number=" + ID + "&destination_passport=" + e("美国-护照")
                + "&category=" + e("因私") + "&travel_dates=2026/09/01-2026/09/11"
                + "&need_new_passport=" + e(needNewPassport)).body();
    }

    @Test
    @DisplayName("一本可用的证都没有却填「不做证」，挡回；过期证件不算数")
    void noUsableCertMustMakeNew() throws Exception {
        assertTrue(postTravel("否").contains("没有在有效期内的出入境证件"),
                "一本证都没有却填「不做证」，未被拦下");

        // 一本过期护照等于没有——只看有没有号码是不够的
        app.sql("INSERT INTO certificates (personnel_filing_id,unit,department,name,"
                + "passport_no,passport_expiry,passport_submit_date,operator) VALUES ("
                + FILING_B + ",'总部','技术部','李四','E11112222','20200101','20190101','admin')");
        assertTrue(postTravel("否").contains("没有在有效期内的出入境证件"), "过期证件被当成可用");

        // 换一本在有效期内的，就不该再报
        app.sql("INSERT INTO certificates (personnel_filing_id,unit,department,name,"
                + "hm_pass_no,hm_pass_expiry,hm_pass_submit_date,operator) VALUES ("
                + FILING_B + ",'总部','技术部','李四','C11112222','20360101','20260101','admin')");
        assertFalse(postTravel("否").contains("没有在有效期内的出入境证件"),
                "名下有在有效期内的证件，却被判为必须做证");

        app.sql("DELETE FROM certificates WHERE personnel_filing_id=" + FILING_B);
    }

    @Test
    @DisplayName("做证=是 时不校验名下证件")
    void needNewPassportSkipsCertCheck() throws Exception {
        assertFalse(postTravel("是").contains("没有在有效期内的出入境证件"),
                "做证=是 时不该校验名下证件");
    }

    /** 从页面上摘出 flash 里的错误提示，失败时好定位。 */
    private static String errorsIn(String body) {
        var m = java.util.regex.Pattern
                .compile("alert-danger[^>]*>\\s*([^<]{2,80})").matcher(body);
        StringBuilder sb = new StringBuilder();
        while (m.find()) {
            sb.append(m.group(1).trim()).append(" | ");
        }
        return sb.length() == 0 ? "（页面上没有 alert-danger）" : sb.toString();
    }
}

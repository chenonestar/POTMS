package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 第 3 批：领用列表批量打印、附件总览按批次排序、证件种类单选、证照一人一行 + 换发提醒。
 *
 * <p>四条都是「界面与语义」层面的：功能都在，但呈现或口径与 Python 版不一致，用起来会
 * 出错——批量打印缺一整个入口（连勾选框都没有）；附件按上传时间排，同一个人同一批次的
 * 附件被别人的插在中间；证件种类是复选框，而业务上一次申请只能领一本；证照允许同一个人
 * 建多条，于是两个编辑入口、预警报两遍。
 */
class Batch3Test {

    private static PageSmokeTest.AppUnderTest app;
    private static final String ID = "110101199001012133";

    @BeforeAll
    static void start() throws Exception {
        app = PageSmokeTest.AppUnderTest.start(5797, true);
        seedAttachments();
    }

    @AfterAll
    static void stop() {
        if (app != null) {
            app.stop();
        }
    }

    private static String e(String s) {
        return URLEncoder.encode(s, StandardCharsets.UTF_8);
    }

    /**
     * 造两条申请各带两个附件，且刻意让上传时间交叉：申请 901 的附件一早一晚，
     * 申请 902 的夹在中间。按上传时间排会把 902 插进 901 中间；按批次排则各自聚拢。
     */
    private static void seedAttachments() throws Exception {
        for (int tid : new int[] {901, 902}) {
            app.sql("INSERT INTO travel_details (id,personnel_filing_id,unit,department,name,position,"
                    + "id_number,destination_passport,category,travel_dates,need_new_passport,operator) "
                    + "VALUES (" + tid + ",1,'总部','技术部','批次" + tid + "','科长','" + ID + "',"
                    + "'美国/护照','因私','2026/03/01-2026/03/10','否','admin')");
        }
        Object[][] atts = {
            {9011, 901, "审批表", "2026-03-05 10:00:00"},        // 901 的第二件，先传
            {9021, 902, "个人申请报告", "2026-03-06 10:00:00"},   // 902 的，夹在中间
            {9012, 901, "个人申请报告", "2026-03-07 10:00:00"},   // 901 的第一件，后补传
            {9022, 902, "审批表", "2026-03-08 10:00:00"},
        };
        for (Object[] a : atts) {
            app.sql("INSERT INTO attachments (id,travel_id,file_name,file_path,file_type,file_size,"
                    + "uploaded_at) VALUES (" + a[0] + "," + a[1] + ",'f" + a[0] + ".pdf','x.pdf','"
                    + a[2] + "',1024,'" + a[3] + "')");
        }
    }

    /** 断言几个片段在页面上按给定顺序出现。 */
    private static void assertOrder(String body, String what, String... keys) {
        int last = -1;
        for (String k : keys) {
            int pos = body.indexOf(k);
            assertTrue(pos >= 0, what + "：页面上没有 " + k);
            assertTrue(pos > last, what + "：" + k + " 出现得太早（" + pos + " <= " + last + "）");
            last = pos;
        }
    }

    // ------------------------------------------------------------------
    // 1 批量打印
    // ------------------------------------------------------------------
    @Test
    @DisplayName("领用列表有批量打印入口与勾选框")
    void issuanceListHasBatchPrint() throws Exception {
        String body = app.get("/issuance").body();
        assertTrue(body.contains("批量打印"), "领用列表缺少批量打印入口");
        assertTrue(body.contains("batchPrint('issuance')"), "批量打印按钮没接上 issuance 类型");
        // 没有勾选框，batchPrint() 收集不到任何 id，按钮等于摆设
        assertTrue(body.contains("class=\"row-check\""), "列表没有行勾选框");
        assertTrue(body.contains("id=\"selectAll\""), "列表没有全选框");
    }

    @Test
    @DisplayName("批量打印页印出领用清单，签名按行取图")
    void batchPrintIssuanceRendersRows() throws Exception {
        var res = app.get("/print/batch/issuance?ids=1");
        assertEquals(200, res.statusCode(), "批量打印返回 " + res.statusCode());
        String body = res.body();
        for (String want : new String[] {
            "因私出国（境）证件领用登记表", "史迪威", "因私护照", "E1234567", "共 1 条记录",
        }) {
            assertTrue(body.contains(want), "批量打印页缺少「" + want + "」");
        }
        assertTrue(body.contains("/issuance/1/signature.png"), "没有按行引用签名图");
    }

    @Test
    @DisplayName("没选记录时不进打印页")
    void batchPrintWithoutIdsIsRejected() throws Exception {
        assertEquals(302, app.get("/print/batch/issuance").statusCode());
    }

    // ------------------------------------------------------------------
    // 2 附件总览排序
    // ------------------------------------------------------------------
    @Test
    @DisplayName("默认按出国批次聚组，组内按办件顺序")
    void attachmentsGroupedByBatchByDefault() throws Exception {
        var res = app.get("/travel/attachments");
        assertEquals(200, res.statusCode());
        // 902 那组（created_at 更晚）整组在前，组内按办件顺序（个人申请报告 → 审批表）
        assertOrder(res.body(), "默认排序不是「按批次聚组 + 组内办件顺序」",
                "f9021.pdf", "f9022.pdf", "f9012.pdf", "f9011.pdf");
    }

    @Test
    @DisplayName("可切到按上传时间排序，且选择器回显")
    void attachmentsSortByUploadedTime() throws Exception {
        String body = app.get("/travel/attachments?sort=uploaded").body();
        assertOrder(body, "sort=uploaded 没有按上传时间倒序",
                "f9022.pdf", "f9012.pdf", "f9021.pdf", "f9011.pdf");
        assertTrue(body.contains("value=\"uploaded\" selected"), "排序选择器没有回显 uploaded");
    }

    @Test
    @DisplayName("非法排序参数退回默认，不拼进 SQL")
    void attachmentsSortFallsBackOnGarbage() throws Exception {
        var res = app.get("/travel/attachments?sort=" + e("a.id; DROP TABLE attachments"));
        assertEquals(200, res.statusCode(), "非法排序参数把页面打挂了");
        assertTrue(res.body().contains("f9021.pdf"), "非法排序参数下附件列表为空");
        assertTrue(Integer.parseInt(app.queryOne("SELECT COUNT(*) FROM attachments")) > 0,
                "attachments 表没了——排序参数被拼进了 SQL");
    }

    // ------------------------------------------------------------------
    // 3 证件种类单选
    // ------------------------------------------------------------------
    @Test
    @DisplayName("证件种类是单选，不是复选框")
    void issuanceFormUsesRadioForCertType() throws Exception {
        String body = app.get("/issuance/new?travel_id=1").body();
        int i = body.indexOf("name=\"cert_types\"");
        assertTrue(i >= 0, "表单上找不到证件种类控件");
        int start = body.lastIndexOf("<input", i);
        String tag = body.substring(start, i);
        assertTrue(tag.contains("type=\"radio\""),
                "证件种类仍是复选框——业务上一次申请只能领一本证：" + tag);
    }

    // ------------------------------------------------------------------
    // 4 证照一人一行 + 换发提醒
    // ------------------------------------------------------------------
    private static final long FILING_C = 960;

    private static void seedFiling() throws Exception {
        app.sql("INSERT OR REPLACE INTO personnel_filing (id,surname,given_name,gender,birth_date,"
                + "id_number,residence,political_status,work_unit,position_or_title,supervisor_unit,"
                + "operator) VALUES (" + FILING_C + ",'证','照某','男','19900101','" + ID + "',"
                + "'浙江宁波市鄞州区','群众','总部','科长','人事处','admin')");
    }

    private static java.net.http.HttpResponse<String> postCert(String url, String... over)
            throws Exception {
        var fields = new java.util.LinkedHashMap<String, String>();
        fields.put("personnel_filing_id", String.valueOf(FILING_C));
        fields.put("unit", e("总部"));
        fields.put("department", e("技术部"));
        fields.put("name", e("证照某"));
        fields.put("passport_no", "E20000001");
        fields.put("passport_expiry", "20360101");
        fields.put("passport_submit_date", "20260101");
        for (int i = 0; i < over.length; i += 2) {
            fields.put(over[i], over[i + 1]);
        }
        StringBuilder body = new StringBuilder("csrf_token=" + app.token(url));
        fields.forEach((k, v) -> body.append('&').append(k).append('=').append(v));
        return app.post(url, body.toString());
    }

    @Test
    @DisplayName("同一备案人员只能有一条证照记录")
    void certificateOneRowPerPerson() throws Exception {
        seedFiling();
        app.sql("DELETE FROM certificates WHERE personnel_filing_id = " + FILING_C);
        assertEquals(302, postCert("/certificate/new").statusCode(), "首次登记应放行");

        var second = postCert("/certificate/new", "passport_no", "E30000003");
        assertEquals(200, second.statusCode(), "第二条应被挡回并重渲染表单");
        assertTrue(second.body().contains("已有证照记录"), "未提示「一人一行」");
        assertEquals("1", app.queryOne(
                "SELECT COUNT(*) FROM certificates WHERE personnel_filing_id = " + FILING_C),
                "库里应仍只有 1 条证照记录");
    }

    @Test
    @DisplayName("换发（号码变了）提醒同步有效期与上交日期")
    void certificateRenewalWarnsAboutDates() throws Exception {
        seedFiling();
        app.sql("DELETE FROM certificates WHERE personnel_filing_id = " + FILING_C);
        assertEquals(302, postCert("/certificate/new").statusCode());
        String certId = app.queryOne(
                "SELECT id FROM certificates WHERE personnel_filing_id = " + FILING_C);

        // 换发：只改号码，日期没跟着改
        assertEquals(302, postCert("/certificate/" + certId + "/edit",
                "passport_no", "E99999999").statusCode());
        String body = app.get("/certificate").body();
        assertTrue(body.contains("号码已变更"), "换发后没有提醒同步日期");
        assertTrue(body.contains("普通护照"), "提醒里没有说明是哪一类证件");
    }

    @Test
    @DisplayName("号码没变不提醒——否则这条提醒会被当成噪音")
    void certificateEditWithoutNumberChangeIsQuiet() throws Exception {
        seedFiling();
        app.sql("DELETE FROM certificates WHERE personnel_filing_id = " + FILING_C);
        assertEquals(302, postCert("/certificate/new").statusCode());
        String certId = app.queryOne(
                "SELECT id FROM certificates WHERE personnel_filing_id = " + FILING_C);

        assertEquals(302, postCert("/certificate/" + certId + "/edit",
                "department", e("办公室")).statusCode());
        assertFalse(app.get("/certificate").body().contains("号码已变更"),
                "号码没变也提醒了换发");
    }
}

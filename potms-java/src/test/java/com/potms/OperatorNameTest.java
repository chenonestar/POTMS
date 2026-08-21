package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.potms.PageSmokeTest.AppUnderTest;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;

/**
 * 经办人身份的分层：业务单据记真实姓名，操作日志记登录账号。
 *
 * <p>这不是显示细节，是两类字段的不同口径。账号是身份标识、姓名可以随时改，
 * 所以审计痕迹只能挂在账号上；而打印出来的领用凭证上一个 admin 没法拿去归档，
 * 必须是真人名字。
 *
 * <p>用例按序号跑：前半段验证「填了姓名之后新写入的单据用姓名」，后半段验证
 * 「升级前留下的历史数据能被回填」——后者依赖前者造出的库态，拆开反而要多起
 * 一个 Tomcat 进程。
 */
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class OperatorNameTest {

    private static final String NAME = "张建国";
    private static AppUnderTest app;

    @BeforeAll
    static void start() throws Exception {
        // 带种子数据启动：seed() 灌的那批记录经办人都是 admin，正是升级前的历史形态
        app = AppUnderTest.start(5792, true);
    }

    @AfterAll
    static void stop() {
        if (app != null) {
            app.stop();
        }
    }

    @Test
    @Order(1)
    @DisplayName("users 表带 full_name 列（五版共用 data.db，DDL 必须一致）")
    void schemaHasFullName() throws Exception {
        assertNotNull(app.queryOne(
                "SELECT name FROM pragma_table_info('users') WHERE name = 'full_name'"),
                "users 表缺少 full_name 列");
    }

    @Test
    @Order(2)
    @DisplayName("未填姓名时仪表盘提示一次，且单据回退到登录账号")
    void promptsWhenNameMissing() throws Exception {
        assertTrue(app.get("/").body().contains("尚未填写"), "未填姓名时仪表盘应提示");
        assertTrue(app.get("/issuance/new").body().contains("value=\"admin\""),
                "未填姓名时领用表单的经办人应回退到登录账号");
    }

    @Test
    @Order(3)
    @DisplayName("账户设置保存姓名，会话与库同步更新")
    void savesFullName() throws Exception {
        saveFullName(NAME);
        assertEquals(NAME, app.queryOne("SELECT full_name FROM users WHERE username = 'admin'"));
        assertFalse(app.get("/").body().contains("尚未填写"), "填了姓名之后不该再提示");
    }

    @Test
    @Order(4)
    @DisplayName("单据与打印件的经办人用真实姓名")
    void documentsUseRealName() throws Exception {
        assertTrue(app.get("/issuance/new").body().contains("value=\"" + NAME + "\""),
                "领用表单的经办人应显示真实姓名");
        assertTrue(app.get("/print/filing/1").body().contains("操作人：" + NAME),
                "打印页脚的操作人应显示真实姓名");
    }

    @Test
    @Order(5)
    @DisplayName("新写入的业务记录记姓名，操作日志仍记账号")
    void newRecordsUseNameLogsKeepAccount() throws Exception {
        app.post("/certificate/new", "csrf_token=" + app.token("/certificate/new")
                + "&personnel_filing_id=1&unit=" + e("总部") + "&department=" + e("办公室")
                + "&name=" + e("史迪威") + "&passport_no=E7654321"
                + "&passport_expiry=20311231&passport_submit_date=20260201");

        assertEquals(NAME, app.queryOne(
                "SELECT operator FROM certificates WHERE passport_no = 'E7654321'"),
                "新建的业务记录应记真实姓名");
        assertEquals("0", app.queryOne(
                "SELECT COUNT(*) FROM operation_logs WHERE operator = '" + NAME + "'"),
                "操作日志不该出现姓名——账号才是审计身份");
        assertTrue(Integer.parseInt(app.queryOne(
                "SELECT COUNT(*) FROM operation_logs WHERE operator = 'admin'")) > 0,
                "操作日志应以 admin 记录");
    }

    @Test
    @Order(6)
    @DisplayName("日志页把操作人渲染成「张三（admin）」")
    void logsPageShowsNameWithAccount() throws Exception {
        String body = app.get("/logs").body();
        assertTrue(body.contains(NAME) && body.contains("（admin）"),
                "日志页应同时显示姓名与账号");
    }

    @Test
    @Order(7)
    @DisplayName("回填改业务表、不动操作日志")
    void backfillRewritesBusinessRowsOnly() throws Exception {
        // seed() 造的那批记录经办人仍是 admin
        assertTrue(Integer.parseInt(app.queryOne(
                "SELECT COUNT(*) FROM personnel_info WHERE operator = 'admin'")) > 0,
                "应先有一批以 admin 为经办人的历史数据");
        assertTrue(app.get("/account").body().contains("历史经办人回填"),
                "账户设置页应出现回填面板");

        var res = app.post("/account/backfill-operator",
                "csrf_token=" + app.token("/account"));
        assertEquals(302, res.statusCode(), "回填后应重定向回账户页");

        assertEquals("0", app.queryOne(
                "SELECT COUNT(*) FROM personnel_info WHERE operator = 'admin'"),
                "回填后不该再有以 admin 为经办人的业务记录");
        assertEquals(NAME, app.queryOne("SELECT operator FROM personnel_info LIMIT 1"));
        assertEquals("0", app.queryOne(
                "SELECT COUNT(*) FROM operation_logs WHERE operator = '" + NAME + "'"),
                "回填不该动操作日志");
    }

    @Test
    @Order(8)
    @DisplayName("姓名清空后拒绝回填")
    void backfillRefusedWithoutName() throws Exception {
        saveFullName("");
        app.sql("UPDATE personnel_info SET operator = 'admin'");

        var res = app.post("/account/backfill-operator",
                "csrf_token=" + app.token("/account"));
        assertEquals(302, res.statusCode());
        assertTrue(Integer.parseInt(app.queryOne(
                "SELECT COUNT(*) FROM personnel_info WHERE operator = 'admin'")) > 0,
                "没填姓名就把历史数据改了");
    }

    private void saveFullName(String name) throws Exception {
        app.post("/account", "csrf_token=" + app.token("/account")
                + "&current_password=admin123&new_username=admin&new_full_name=" + e(name));
    }

    private static String e(String s) {
        return URLEncoder.encode(s, StandardCharsets.UTF_8);
    }
}

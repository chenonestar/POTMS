package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;

/**
 * 全站 GET 页面冒烟：任何页面都不得返回 5xx。
 *
 * <p>分空库与有数据两种库态各跑一遍，因为两者触发的失败路径不同：
 * 空库暴露的是「结果集为空时的取值假设」，有数据暴露的是拆箱、空集合、
 * 字典键为 null 之类。.NET 版就是在空库这条路径上出过 500，人工冒烟
 * 总是带着数据做，测不出来。
 */
class PageSmokeTest {

    private static AppUnderTest empty;
    private static AppUnderTest seeded;

    @BeforeAll
    static void startAll() throws Exception {
        empty = AppUnderTest.start(5790, false);
        seeded = AppUnderTest.start(5791, true);
    }

    @AfterAll
    static void stopAll() {
        if (empty != null) {
            empty.stop();
        }
        if (seeded != null) {
            seeded.stop();
        }
    }

    /** 全部 GET 页面。详情页统一用 id=1：空库下应重定向，有数据时应 200。 */
    static List<String> urls() {
        return List.of(
                "/", "/login", "/account",
                "/search", "/search?q=%E5%8F%B2",
                "/personnel", "/personnel?search=%E5%8F%B2&sort=name_asc",
                "/personnel/info", "/personnel/info?ref=orphan",
                "/personnel/info/new", "/personnel/info/1/edit",
                "/personnel/filing/new", "/personnel/filing/new?info_id=1",
                "/personnel/filing/1/edit", "/personnel/1",
                "/certificate", "/certificate?has_passport=1",
                "/certificate/new", "/certificate/new?filing_id=1", "/certificate/1/edit",
                "/travel", "/travel?passport_status=overdue", "/travel?passport_status=inuse",
                "/travel/new", "/travel/new?filing_id=1", "/travel/1", "/travel/1/edit",
                "/travel/attachments", "/travel/attachments?file_type=%E5%AE%A1%E6%89%B9%E8%A1%A8",
                "/travel/attachment/1/preview",
                "/issuance", "/issuance?status=issued", "/issuance?cert_type=01",
                "/issuance/new", "/issuance/new?travel_id=1", "/issuance/1",
                "/issuance/1/return", "/issuance/1/signature.png",
                "/decontrol", "/decontrol/new?filing_id=1", "/decontrol/1",
                "/dict", "/org", "/org/tree-data", "/submit-unit",
                "/logs", "/logs?action=create&page=2",
                "/import", "/import/template",
                "/export/info", "/export/filing", "/export/certificate",
                "/export/travel", "/export/decontrol", "/export/issuance",
                "/logs/export?year=2026",
                "/print/info/1", "/print/filing/1", "/print/certificate/1",
                "/print/travel/1", "/print/decontrol/1", "/print/issuance/1",
                "/print/batch/filing?ids=1");
    }

    @ParameterizedTest(name = "空库 GET {0}")
    @MethodSource("urls")
    @DisplayName("空库：全站无 5xx")
    void emptyDatabase(String url) throws Exception {
        assertNo5xx(empty, url);
    }

    @ParameterizedTest(name = "有数据 GET {0}")
    @MethodSource("urls")
    @DisplayName("有数据：全站无 5xx")
    void seededDatabase(String url) throws Exception {
        assertNo5xx(seeded, url);
    }

    /** 抽查几处确实取到了数据，避免「页面其实是空的所以不炸」的假通过。 */
    @Test
    @DisplayName("有数据时关键页面确实渲染出内容")
    void seededPagesRenderData() throws Exception {
        for (String url : List.of("/personnel", "/travel", "/issuance", "/travel/attachments")) {
            var res = seeded.get(url);
            assertEquals(200, res.statusCode(), url);
            assertTrue(res.body().contains("史迪威"), url + " 未渲染出种子数据");
        }
    }

    @Test
    @DisplayName("空库登录可用（仅有种子管理员）")
    void loginWorksOnEmptyDatabase() throws Exception {
        assertEquals(200, empty.get("/").statusCode());
    }

    // ==================================================================
    // 与 Python 版的界面一致性
    //
    // 这几条是回归用的。五版共用同一套界面约定，Java 版当初出现过三处漂移：
    // 仪表盘多渲染了三张 Python 从没显示过的统计卡、侧边栏漏掉两个菜单、
    // 组织架构的「排序」列错显成主键 ID。都不报错，只是跟别的版本长得不一样，
    // 靠人眼比对根本比不出来。
    // ==================================================================

    @Test
    @DisplayName("侧边栏菜单与 Python 版一致，账户设置与批量导入都在")
    void sidebarMatchesPython() throws Exception {
        String html = seeded.get("/").body();
        for (String href : List.of("/org", "/dict", "/submit-unit", "/account",
                "/import", "/logs", "/personnel", "/certificate", "/travel",
                "/issuance", "/travel/attachments", "/decontrol")) {
            assertTrue(html.contains("href=\"" + href + "\""), "侧边栏缺少菜单项 " + href);
        }
    }

    @Test
    @DisplayName("仪表盘不含 Python 版没有的统计卡")
    void dashboardHasNoExtraCards() throws Exception {
        String html = seeded.get("/").body();
        // Python 的 dashboard.py 算了 by_unit / by_political / by_rank，但模板从没用过，
        // 是留在源头的死查询。Java 照着 controller 抄，就成了唯一显示它们的版本。
        for (String card : List.of("按单位分布", "按政治面貌", "按职级")) {
            assertTrue(!html.contains(card), "仪表盘多出 Python 版没有的「" + card + "」卡片");
        }
    }

    @Test
    @DisplayName("组织架构是树形界面，层级与徽章都对，且不再暴露排序字段")
    void orgRendersTree() throws Exception {
        seeded.sql("INSERT OR REPLACE INTO sys_org (id, name, parent_id, sort_order) VALUES "
                + "(41, '甲单位', 0, 1), (42, '乙部门', 41, 2), (43, '丙部门', 41, 1), "
                + "(44, '丁科室', 43, 1)");

        String html = seeded.get("/org").body();
        assertTrue(html.contains("badge bg-primary\">单位"), "顶级节点应标「单位」徽章");
        assertTrue(html.contains("badge bg-info\">部门"), "第二级应标「部门」徽章");
        assertTrue(html.contains("badge bg-secondary\">子部门"), "第三级应标「子部门」徽章");
        assertTrue(html.contains("（下辖 2 个部门）"), "顶级单位应显示下辖部门数");

        var names = orgTreeOrder(html);
        int i = names.indexOf("甲单位");
        assertTrue(i >= 0, "树里找不到甲单位：" + names);
        assertEquals(List.of("甲单位", "丙部门", "丁科室", "乙部门"), names.subList(i, i + 4),
                "树的展开次序不对：子节点应紧跟父节点，同级按 sort_order（丙=1 在 乙=2 前）");

        // 排序字段不再出现在界面上——与 Python / Go / Rust 一致
        assertTrue(!html.contains("name=\"sort_order\""), "组织架构页不该再有排序输入框");
    }

    @Test
    @DisplayName("重命名不会把老库里已有的排序值抹平")
    void renameKeepsExistingSortOrder() throws Exception {
        seeded.sql("INSERT OR REPLACE INTO sys_org (id, name, parent_id, sort_order) "
                + "VALUES (61, '戊单位', 0, 6)");
        // 树形界面的重命名表单只提交 name 与 parent_id，没有 sort_order
        seeded.post("/org/61/edit", "csrf_token=" + seeded.token("/org")
                + "&name=" + java.net.URLEncoder.encode("戊单位改名", StandardCharsets.UTF_8)
                + "&parent_id=0");

        assertEquals("6", seeded.queryOne("SELECT sort_order FROM sys_org WHERE id = 61"),
                "表单里没有 sort_order 时应原样保留，不能一律写 0");
        assertEquals("戊单位改名", seeded.queryOne("SELECT name FROM sys_org WHERE id = 61"));
    }

    /**
     * 按树的展开次序取出节点名。
     *
     * <p>抓的是「节点名 + 紧随其后的层级徽章」这个组合。不能拿整页
     * {@code indexOf(名称)} 当次序用——名称在别处（比如确认删除的提示文案里）
     * 也会出现，比出来的先后未必是树上的先后。
     */
    private static List<String> orgTreeOrder(String html) {
        var out = new java.util.ArrayList<String>();
        Matcher m = Pattern.compile(
                "<span class=\"(?:fw-bold)?\">([^<]+)</span>\\s*<span class=\"badge").matcher(html);
        while (m.find()) {
            out.add(m.group(1).trim());
        }
        return out;
    }

    // ==================================================================
    // 打印
    // ==================================================================

    @Test
    @DisplayName("批量打印是一张宽表、一条记录一行，不是 N 份单据")
    void batchPrintIsOneWideTable() throws Exception {
        String html = seeded.get("/print/batch/filing?ids=1").body();

        assertTrue(html.contains("A4 landscape"), "批量打印应是 A4 横向");
        assertEquals(1, count(html, "<table>"), "应只有一张表，而不是每条一份单据");
        assertTrue(html.contains("打印全部（1 条）"), "按钮应写明条数");
        assertTrue(html.contains("（共 1 条）"), "标题应带记录数");
        assertTrue(html.contains("<th>中文姓</th>"), "应是清单式表头");
        // 单据式的签章栏不该出现在清单上
        assertTrue(!html.contains("填表人："), "清单不需要逐份签章栏");
    }

    @Test
    @DisplayName("领用凭证不做批量打印，与 Python 版一致")
    void batchPrintRejectsIssuance() throws Exception {
        // 逐份签字的单据摊成清单没有意义，签名图也放不进去
        assertEquals(302, seeded.get("/print/batch/issuance?ids=1").statusCode());
    }

    @Test
    @DisplayName("单据打印带签章栏与页脚，且不加载 Bootstrap")
    void singlePrintHasSignatureBlock() throws Exception {
        String html = seeded.get("/print/filing/1").body();

        for (String needle : List.of("填表人：", "审核人：", "批准人：", "打印日期")) {
            assertTrue(html.contains(needle), "单据打印缺少「" + needle + "」");
        }
        // 打印页是独立文档：Bootstrap 的 reset 会改掉边框与字号，纸面就跟别的版本对不上
        assertTrue(!html.contains("bootstrap"), "打印页不该引入 Bootstrap");
        assertTrue(html.contains("SimSun"), "打印页应固定宋体");
    }

    @Test
    @DisplayName("备案表打印附带关联的信息登记表")
    void filingPrintIncludesLinkedInfo() throws Exception {
        String html = seeded.get("/print/filing/1").body();
        assertTrue(html.contains("关联：备案人员信息登记表"),
                "备案表有 personnel_info_id 时应附上信息登记表");
        assertEquals(2, count(html, "<table>"), "应是两张表：备案表 + 关联信息表");
    }

    @Test
    @DisplayName("关联信息登记表的字典字段打成中文，不是裸代码")
    void filingPrintResolvesDictCodesInLinkedInfo() throws Exception {
        // 学历 01 = 博士研究生（种子字典），打印上必须是中文
        seeded.sql("UPDATE personnel_info SET education = '01', degree = '01', "
                + "title = '01', rank = '01' WHERE id = 1");
        String html = seeded.get("/print/filing/1").body();

        int at = html.indexOf("关联：备案人员信息登记表");
        assertTrue(at >= 0, "备案表打印应附关联信息登记表");
        String linked = html.substring(at);
        assertTrue(linked.contains("博士研究生"), "关联信息表的学历应转成中文：" + snippet(linked));
        assertTrue(!linked.contains("<td>01</td>"),
                "关联信息表里不该出现裸字典代码：" + snippet(linked));
    }

    private static String snippet(String s) {
        return s.substring(0, Math.min(400, s.length()));
    }

    @Test
    @DisplayName("出行明细打印含职称、行程状态与取消日期")
    void travelPrintHasAllFields() throws Exception {
        seeded.sql("UPDATE travel_details SET title = '高级经济师', "
                + "trip_status = 'cancelled', cancel_date = '20261015' WHERE id = 1");
        String html = seeded.get("/print/travel/1").body();
        for (String needle : List.of("职称", "高级经济师", "行程状态", "取消行程", "取消日期", "20261015")) {
            assertTrue(html.contains(needle), "出行明细打印缺少「" + needle + "」");
        }
        seeded.sql("UPDATE travel_details SET trip_status = 'normal', cancel_date = '' WHERE id = 1");
    }

    private static int count(String haystack, String needle) {
        int n = 0;
        for (int i = haystack.indexOf(needle); i >= 0; i = haystack.indexOf(needle, i + 1)) {
            n++;
        }
        return n;
    }

    @Test
    @DisplayName("操作日志的动作按类型着色，与 Python 版同一套配色")
    void logActionBadgesAreColoured() throws Exception {
        seeded.sql("INSERT INTO operation_logs (operator, action, target_type, target_id, "
                + "detail, ip_address) VALUES ('admin','delete','sys_org',52,'丁单位','127.0.0.1')");
        String html = seeded.get("/logs").body();
        // 新建绿 / 修改黄 / 删除红：一屏日志靠颜色分辨「谁动了数据」
        assertTrue(html.contains("badge bg-success"), "新建应是绿色徽章");
        assertTrue(html.contains("badge bg-warning"), "修改应是黄色徽章");
        assertTrue(html.contains("badge bg-danger"), "删除应是红色徽章");
        assertTrue(!html.contains("badge bg-light text-dark\">新建"), "动作徽章不该是清一色的灰");
    }

    @Test
    @DisplayName("操作日志的变更详情是折叠的，改动列三列表、删除列全量")
    void logChangesAreCollapsed() throws Exception {
        // 直接造两条带快照的日志：走业务操作凑齐必填项对本用例没有额外价值
        seeded.sql("INSERT INTO operation_logs (operator, action, target_type, target_id, "
                + "detail, ip_address, snapshot) VALUES ('admin','update','sys_org',41,"
                + "'甲单位','127.0.0.1','{\"before\":{\"name\":\"旧名\"},"
                + "\"after\":{\"name\":\"新名\"}}')");
        seeded.sql("INSERT INTO operation_logs (operator, action, target_type, target_id, "
                + "detail, ip_address, snapshot) VALUES ('admin','delete','sys_org',42,"
                + "'乙单位','127.0.0.1','{\"before\":{\"name\":\"乙单位\"}}')");

        String html = seeded.get("/logs").body();
        assertTrue(html.contains("变更详情"), "日志页应有「变更详情」展开入口");
        assertTrue(html.contains("data-bs-toggle=\"collapse\""),
                "变更详情应折叠展示，与 Python 版一致——全量摊开会把整页撑满");
        assertTrue(html.contains("<th>变更前</th>") && html.contains("<th>变更后</th>"),
                "改动应展开成「字段 / 变更前 / 变更后」三列表格");
        assertTrue(html.contains("删除前内容"),
                "删除没有可对照的另一面，应列删除前的全量内容而不是空 diff");
    }

    /**
     * 页面里引用的每个静态资源都必须真能取到。
     *
     * <p>这条是补出来的窟窿：原先只断言 HTML 页面不是 5xx，而 CSS/JS 全 404
     * 时页面照样返回 200，只是退化成没有样式的裸 HTML——测试全绿，用户一开
     * 浏览器就发现界面是散的。断言里连 Content-Type 一起查，是因为还有另一种
     * 坏法：静态路径没进鉴权白名单，被 302 到登录页，浏览器拿到一篇 HTML 当
     * 样式表用，同样是 200。
     */
    @ParameterizedTest(name = "静态资源 {0}")
    @MethodSource("staticAssets")
    @DisplayName("模板引用的 CSS / JS / 字体全部可取")
    void staticAssetsResolve(String url) throws Exception {
        var res = seeded.get(url);
        assertEquals(200, res.statusCode(), "GET " + url + " 取不到，页面会退化成裸 HTML");
        String type = res.headers().firstValue("content-type").orElse("");
        assertTrue(!type.startsWith("text/html"),
                "GET " + url + " 返回的是 HTML（" + type + "），多半是被重定向到了登录页");
        assertTrue(res.body().length() > 100, "GET " + url + " 内容为空");
    }

    /** 从真实渲染出的页面里扒引用，而不是手写清单——手写的清单会跟着模板一起过时。 */
    static List<String> staticAssets() throws Exception {
        var found = new java.util.TreeSet<String>();
        Pattern ref = Pattern.compile("(?:href|src)=\"(/static/[^\"]+)\"");
        for (String page : List.of("/login", "/", "/issuance/new", "/personnel/info/new")) {
            Matcher m = ref.matcher(seeded.get(page).body());
            while (m.find()) {
                found.add(m.group(1));
            }
        }
        assertTrue(found.size() >= 6, "只扒到 " + found.size() + " 个静态引用，抓取正则可能失配了");
        return List.copyOf(found);
    }

    private static void assertNo5xx(AppUnderTest app, String url) throws Exception {
        var res = app.get(url);
        assertTrue(res.statusCode() < 500,
                "GET " + url + " -> " + res.statusCode() + "\n"
                        + res.body().substring(0, Math.min(600, res.body().length())));
    }

    // ==================================================================
    // 被测应用：起真进程，走真 HTTP
    // ==================================================================

    /**
     * 起独立进程而不是用 MockMvc，是为了把 Tomcat、过滤器链、JTE 预编译模板
     * 全都算进来——.NET 版那个 500 正是在这几层的接缝处，单测层面看不见。
     */
    static final class AppUnderTest {

        private static final Pattern CSRF =
                Pattern.compile("name=\"csrf_token\" value=\"([^\"]+)\"");

        private final Process process;
        private final Path dir;
        private final String base;
        private final HttpClient http;
        private String cookie = "";

        private AppUnderTest(Process p, Path dir, int port) {
            this.process = p;
            this.dir = dir;
            this.base = "http://127.0.0.1:" + port;
            this.http = HttpClient.newBuilder()
                    .followRedirects(HttpClient.Redirect.NEVER).build();
        }

        static AppUnderTest start(int port, boolean seed) throws Exception {
            return start(port, seed, java.util.Map.of());
        }

        /** env：额外的环境变量，用于验证配置开关（如 POTMS_REQUIRE_SIGNATURE）。 */
        static AppUnderTest start(int port, boolean seed, java.util.Map<String, String> env)
                throws Exception {
            Path dir = Files.createTempDirectory("potms-smoke-");
            Path jar = Path.of("target", "potms.jar");
            var pb = new ProcessBuilder("java", "-Dstdout.encoding=UTF-8",
                    "-jar", jar.toAbsolutePath().toString());
            pb.environment().put("POTMS_BASE", dir.toString());
            pb.environment().put("POTMS_PORT", String.valueOf(port));
            pb.environment().putAll(env);
            pb.redirectErrorStream(true);
            pb.redirectOutput(dir.resolve("app.log").toFile());
            Process p = pb.start();

            AppUnderTest app = new AppUnderTest(p, dir, port);
            app.waitReady();
            app.login();
            if (seed) {
                app.seed();
            }
            return app;
        }

        private void waitReady() throws Exception {
            for (int i = 0; i < 120; i++) {
                try {
                    get("/login");
                    return;
                } catch (IOException | InterruptedException e) {
                    Thread.sleep(500);
                }
            }
            throw new IllegalStateException("应用未能在 60 秒内就绪，日志见 " + dir.resolve("app.log"));
        }

        HttpResponse<String> get(String path) throws IOException, InterruptedException {
            var req = HttpRequest.newBuilder(URI.create(base + path))
                    .header("Cookie", cookie).GET().build();
            var res = http.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            captureCookie(res);
            return res;
        }

        HttpResponse<String> post(String path, String form) throws IOException, InterruptedException {
            var req = HttpRequest.newBuilder(URI.create(base + path))
                    .header("Cookie", cookie)
                    .header("Content-Type", "application/x-www-form-urlencoded")
                    .POST(HttpRequest.BodyPublishers.ofString(form, StandardCharsets.UTF_8)).build();
            var res = http.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            captureCookie(res);
            return res;
        }

        private void captureCookie(HttpResponse<String> res) {
            res.headers().firstValue("set-cookie").ifPresent(v -> cookie = v.split(";")[0]);
        }

        String token(String path) throws IOException, InterruptedException {
            Matcher m = CSRF.matcher(get(path).body());
            return m.find() ? m.group(1) : "";
        }

        private void login() throws IOException, InterruptedException {
            String t = token("/login");
            post("/login", "csrf_token=" + t + "&username=admin&password=admin123");
        }

        /** 灌一条贯穿全模块的数据链：备案 → 证照 → 出行 → 领用（含签名）。 */
        private void seed() throws Exception {
            String id = validId();
            post("/personnel/info/new", "csrf_token=" + token("/personnel/info/new")
                    + "&unit=" + e("总部") + "&department=" + e("办公室") + "&name=" + e("史迪威")
                    + "&gender=" + e("男") + "&birth_date=19900101&id_number=" + id
                    + "&work_start_date=20120701&education=01&degree=01&title=01&rank=01"
                    + "&political_status=" + e("群众") + "&position=" + e("工程师"));
            post("/personnel/filing/new?info_id=1",
                    "csrf_token=" + token("/personnel/filing/new?info_id=1")
                    + "&surname=" + e("史") + "&given_name=" + e("迪威") + "&gender=" + e("男")
                    + "&birth_date=19900101&id_number=" + id
                    + "&residence=" + e("浙江宁波市鄞州区") + "&political_status=" + e("群众")
                    + "&work_unit=" + e("总部") + "&position_or_title=" + e("处级")
                    + "&supervisor_unit=" + e("某某国资委") + "&tag=" + e("新增")
                    + "&informed=" + e("是"));
            post("/certificate/new", "csrf_token=" + token("/certificate/new")
                    + "&personnel_filing_id=1&unit=" + e("总部") + "&department=" + e("办公室")
                    + "&name=" + e("史迪威") + "&passport_no=E1234567"
                    + "&passport_expiry=20301231&passport_submit_date=20260101");
            // 出行记录直接写库：走 HTTP 需要 multipart 附件，对冒烟没有额外价值
            sql("INSERT INTO travel_details (id, personnel_filing_id, unit, department, name, "
                    + "position, id_number, destination_passport, category, travel_dates, "
                    + "travel_start, travel_end, operator, need_new_passport, trip_status) "
                    + "VALUES (1,1,'总部','办公室','史迪威','处级','" + id + "','德国','因私',"
                    + "'2026/09/01-2026/09/10','20260901','20260910','admin','否','normal')");
            sql("INSERT INTO attachments (id, travel_id, file_name, file_path, file_type, file_size) "
                    + "VALUES (1,1,'申请表.pdf','nonexistent.pdf','个人申请报告',1024)");
            post("/issuance/new", "csrf_token=" + token("/issuance/new")
                    + "&travel_id=1&personnel_filing_id=1&holder_name=" + e("史迪威")
                    + "&id_number=" + id + "&cert_types=01&cert_nos=E1234567"
                    + "&issue_date=20260802&sign_png=" + e(pngDataUrl()));
        }

        /** 直读一个标量，用于验证「页面看不见但库里必须对」的字段。 */
        String queryOne(String query) throws Exception {
            try (var cn = java.sql.DriverManager.getConnection(
                    "jdbc:sqlite:" + dir.resolve("data.db"));
                 var st = cn.createStatement();
                 var rs = st.executeQuery(query)) {
                return rs.next() ? rs.getString(1) : null;
            }
        }

        void sql(String statement) throws Exception {
            try (var cn = java.sql.DriverManager.getConnection(
                    "jdbc:sqlite:" + dir.resolve("data.db"));
                 var st = cn.createStatement()) {
                st.executeUpdate(statement);
            }
        }

        void stop() {
            process.destroy();
            try {
                process.waitFor(10, java.util.concurrent.TimeUnit.SECONDS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }

        private static String e(String s) {
            return java.net.URLEncoder.encode(s, StandardCharsets.UTF_8);
        }

        /** 按国标校验位算法造一个合法身份证号。 */
        static String validId() {
            String body = "110101" + "19900101" + "213";
            int[] w = {7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2};
            int s = 0;
            for (int i = 0; i < 17; i++) {
                s += (body.charAt(i) - '0') * w[i];
            }
            return body + "10X98765432".charAt(s % 11);
        }

        /** 1×1 白色 PNG 的 dataURL，签名校验只看魔数与大小。 */
        static String pngDataUrl() {
            return "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                    + "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
        }
    }
}

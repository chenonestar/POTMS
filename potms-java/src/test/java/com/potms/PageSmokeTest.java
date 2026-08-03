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
            Path dir = Files.createTempDirectory("potms-smoke-");
            Path jar = Path.of("target", "potms.jar");
            var pb = new ProcessBuilder("java", "-Dstdout.encoding=UTF-8",
                    "-jar", jar.toAbsolutePath().toString());
            pb.environment().put("POTMS_BASE", dir.toString());
            pb.environment().put("POTMS_PORT", String.valueOf(port));
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

        private String token(String path) throws IOException, InterruptedException {
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

        private void sql(String statement) throws Exception {
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

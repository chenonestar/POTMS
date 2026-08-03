package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.WebSocket;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 手写签名的浏览器级验证：真的用鼠标在画布上画，真的画出墨迹。
 *
 * <p>为什么非要开浏览器：签名板坏过一次——模板引了 signature.js 却没调
 * {@code POTMSSignature.attach()}，画布一片空白、鼠标点了没反应。而页面 HTTP
 * 200、HTML 里该有的元素一个不少，纯 HTTP 层的冒烟全绿。同一类窟窿之前还漏过
 * CSS 全 404（页面照样 200，只是没样式）。凡是「渲染出来才算数」的东西，
 * 只有真跑一个浏览器才测得到。
 *
 * <p>用 CDP 直接驱动 Chrome，不引 Selenium / Playwright：一是政务项目要少一
 * 个依赖是一个，二是 java.net.http 自带 WebSocket，够用。找不到浏览器时整类
 * 跳过，不拖累没有图形环境的机器。
 */
class BrowserSignatureTest {

    private static final ObjectMapper JSON = new ObjectMapper();
    private static final int PORT = 5793;

    private static PageSmokeTest.AppUnderTest app;
    private static Process chrome;
    private static Cdp cdp;

    @BeforeAll
    static void startAll() throws Exception {
        String bin = findChrome();
        Assumptions.assumeTrue(bin != null, "未找到 Chrome/Chromium，跳过浏览器级验证");

        app = PageSmokeTest.AppUnderTest.start(PORT, true);

        Path profile = Files.createTempDirectory("potms-chrome-");
        int dbg = freePort();
        chrome = new ProcessBuilder(bin, "--headless=new", "--no-sandbox", "--disable-gpu",
                "--disable-dev-shm-usage", "--window-size=1400,1000",
                "--user-data-dir=" + profile, "--remote-debugging-port=" + dbg, "about:blank")
                .redirectErrorStream(true)
                .redirectOutput(profile.resolve("chrome.log").toFile())
                .start();
        cdp = Cdp.connect(dbg);
    }

    @AfterAll
    static void stopAll() {
        if (cdp != null) {
            cdp.close();
        }
        if (chrome != null) {
            chrome.destroy();
        }
        if (app != null) {
            app.stop();
        }
    }

    @Test
    @DisplayName("鼠标能在签名板上画出墨迹，并写入提交用的隐藏域")
    void mouseDrawsInk() throws Exception {
        login();
        open("/issuance/new");
        waitFor("!!document.getElementById('signCanvas') && !!window.POTMSSignature",
                "签名画布或 signature.js 没加载出来");

        // attach() 没跑的话画布连自己的尺寸都不会设，这里先把「初始化过」钉死
        assertEquals(640, evalInt("document.getElementById('signCanvas').width"
                        + " / (window.devicePixelRatio || 1)"),
                "画布逻辑宽度不对——POTMSSignature.attach() 多半没被调用");

        JsonNode rect = canvasRect();
        double left = rect.get("left").asDouble();
        double top = rect.get("top").asDouble();
        double w = rect.get("width").asDouble();
        double h = rect.get("height").asDouble();

        int before = darkPixels();
        assertEquals(0, before, "还没落笔，画布上就不该有墨色像素（基准线是浅灰 #dee2e6）");

        // 画一道横向的波浪线。点数要够：signature.js 少于 8 个采样点当误触，不算签名
        drag(left, top, w, h);

        int after = darkPixels();
        assertTrue(after > 200,
                "鼠标拖过之后画布上应出现墨迹，实际墨色像素 " + before + " -> " + after);

        assertEquals("已签名，可点「清除」重签",
                evalString("document.getElementById('signHint').textContent"),
                "提示文案没变，说明 onChange 回调没接上");

        // 表单提交时才把签名写进隐藏域。派发一个合成 submit 事件即可触发监听器，
        // 不会真的导航走，省得再去凑表单其余必填项。
        eval("document.getElementById('signForm').dispatchEvent("
                + "new Event('submit',{cancelable:true,bubbles:true}));");
        assertTrue(evalString("document.getElementById('signPng').value")
                        .startsWith("data:image/png;base64,"),
                "提交时没把签名图写进 sign_png");

        JsonNode meta = JSON.readTree(evalString("document.getElementById('signMeta').value"));
        assertTrue(meta.get("strokes").size() >= 1, "笔迹矢量没写进 sign_meta");
        assertTrue(meta.get("meta").get("pointCount").asInt() >= 8,
                "采样点数不足，笔迹会被当成误触");
        assertEquals("mouse", meta.get("meta").get("pointerType").asString(),
                "设备类型该记成鼠标");
    }

    @Test
    @DisplayName("归还登记页的签名板同样已初始化")
    void returnPageAlsoWired() throws Exception {
        login();
        open("/issuance/1/return");
        waitFor("!!document.getElementById('signCanvas') && !!window.POTMSSignature",
                "归还页签名画布没加载出来");
        assertEquals(640, evalInt("document.getElementById('signCanvas').width"
                        + " / (window.devicePixelRatio || 1)"),
                "归还页的 POTMSSignature.attach() 没被调用");
    }

    // ==================================================================
    // 页面操作
    // ==================================================================

    private static void login() throws Exception {
        open("/login");
        if (evalString("location.pathname").equals("/login")) {
            eval("document.querySelector('input[name=username]').value='admin';"
                    + "document.querySelector('input[name=password]').value='admin123';"
                    + "document.querySelector('form').submit();");
            waitFor("location.pathname !== '/login'", "登录后没有跳转");
        }
    }

    private static void open(String path) throws Exception {
        cdp.call("Page.navigate", Map.of("url", "http://127.0.0.1:" + PORT + path));
        waitFor("document.readyState === 'complete'", "页面 " + path + " 没加载完");
    }

    /**
     * 取画布位置，并保证它整个落在视口内。
     *
     * <p>不走 scrollIntoView：签名板在长表单的底部，实测滚不动（页面滚动被布局
     * 容器接管，scrollY 始终为 0），坐标算出来在视口之外，鼠标事件就打空了。
     * 直接把视口撑到足够高，比跟滚动较劲可靠。
     */
    private static JsonNode canvasRect() throws Exception {
        int need = evalInt("(function(){var r=document.getElementById('signCanvas')"
                + ".getBoundingClientRect();return Math.ceil(r.bottom + window.scrollY + 80);})()");
        cdp.call("Emulation.setDeviceMetricsOverride", Map.of(
                "width", 1400, "height", Math.max(1000, need),
                "deviceScaleFactor", 1, "mobile", false));
        JsonNode rect = evalJson(
                "JSON.stringify(document.getElementById('signCanvas').getBoundingClientRect())");
        assertTrue(rect.get("bottom").asDouble() <= evalInt("window.innerHeight"),
                "签名板没能完整落进视口，鼠标坐标会打空：" + rect);
        return rect;
    }

    /** 一道横向波浪线，中间多打几个点，保证越过「少于 8 点算误触」的门槛。 */
    private static void drag(double left, double top, double w, double h) throws Exception {
        double y = top + h / 2;
        mouse("mousePressed", left + w * 0.15, y);
        for (int i = 1; i <= 16; i++) {
            double x = left + w * (0.15 + 0.7 * i / 16.0);
            mouse("mouseMoved", x, y + Math.sin(i) * h * 0.2);
        }
        mouse("mouseReleased", left + w * 0.85, y);
    }

    private static void mouse(String type, double x, double y) throws Exception {
        cdp.call("Input.dispatchMouseEvent", Map.of(
                "type", type, "x", x, "y", y,
                "button", "left", "buttons", 1, "clickCount", 1, "pointerType", "mouse"));
    }

    /** 数「墨色」像素：基准线是 #dee2e6，墨迹是 #111，阈值取 100 刚好把两者分开。 */
    private static int darkPixels() throws Exception {
        return evalInt("(function(){var c=document.getElementById('signCanvas');"
                + "var d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;var n=0;"
                + "for(var i=0;i<d.length;i+=4){if(d[i]<100&&d[i+1]<100&&d[i+2]<100)n++;}"
                + "return n;})()");
    }

    private static void waitFor(String jsCondition, String message) throws Exception {
        for (int i = 0; i < 100; i++) {
            try {
                if ("true".equals(evalString("String(" + jsCondition + ")"))) {
                    return;
                }
            } catch (RuntimeException ignored) {
                // 导航中途执行上下文会被销毁，重试即可
            }
            Thread.sleep(100);
        }
        throw new IllegalStateException(message);
    }

    private static JsonNode evalRaw(String js) throws Exception {
        JsonNode res = cdp.call("Runtime.evaluate",
                Map.of("expression", js, "returnByValue", true, "awaitPromise", true));
        JsonNode result = res.path("result").path("result");
        if (res.path("result").has("exceptionDetails")) {
            throw new IllegalStateException("JS 执行出错: "
                    + res.path("result").path("exceptionDetails").toString());
        }
        return result.path("value");
    }

    private static void eval(String js) throws Exception {
        evalRaw(js);
    }

    private static String evalString(String js) throws Exception {
        return evalRaw(js).asString();
    }

    private static int evalInt(String js) throws Exception {
        return (int) Math.round(evalRaw(js).asDouble());
    }

    private static JsonNode evalJson(String js) throws Exception {
        return JSON.readTree(evalString(js));
    }

    // ==================================================================
    // 极简 CDP 客户端
    // ==================================================================

    /** 只做「发一条命令、等一条同 id 的回包」，事件一律丢弃——本用例用不上。 */
    private static final class Cdp implements WebSocket.Listener {

        private final AtomicInteger ids = new AtomicInteger();
        private final Map<Integer, CompletableFuture<JsonNode>> pending = new ConcurrentHashMap<>();
        private final StringBuilder buffer = new StringBuilder();
        private WebSocket ws;

        static Cdp connect(int debugPort) throws Exception {
            var http = HttpClient.newHttpClient();
            String wsUrl = null;
            for (int i = 0; i < 100 && wsUrl == null; i++) {
                try {
                    var req = HttpRequest.newBuilder(
                            URI.create("http://127.0.0.1:" + debugPort + "/json/list")).build();
                    JsonNode targets = JSON.readTree(
                            http.send(req, HttpResponse.BodyHandlers.ofString()).body());
                    for (JsonNode t : targets) {
                        if ("page".equals(t.path("type").asString(""))) {
                            wsUrl = t.path("webSocketDebuggerUrl").asString(null);
                        }
                    }
                } catch (Exception ignored) {
                    Thread.sleep(100);      // 浏览器还没起来
                }
            }
            if (wsUrl == null) {
                throw new IllegalStateException("连不上 Chrome 的调试端口 " + debugPort);
            }
            Cdp cdp = new Cdp();
            cdp.ws = http.newWebSocketBuilder()
                    .buildAsync(URI.create(wsUrl), cdp).get(30, TimeUnit.SECONDS);
            cdp.call("Page.enable", Map.of());
            cdp.call("Runtime.enable", Map.of());
            return cdp;
        }

        JsonNode call(String method, Map<String, Object> params) throws Exception {
            int id = ids.incrementAndGet();
            var future = new CompletableFuture<JsonNode>();
            pending.put(id, future);
            ws.sendText(JSON.writeValueAsString(
                    Map.of("id", id, "method", method, "params", params)), true).get();
            return future.orTimeout(30, TimeUnit.SECONDS).get();
        }

        @Override
        public CompletionStage<?> onText(WebSocket socket, CharSequence data, boolean last) {
            buffer.append(data);
            if (last) {
                String text = buffer.toString();
                buffer.setLength(0);
                JsonNode msg = JSON.readTree(text);
                if (msg.has("id")) {
                    var f = pending.remove(msg.get("id").asInt());
                    if (f != null) {
                        f.complete(msg);
                    }
                }
            }
            socket.request(1);
            return null;
        }

        void close() {
            if (ws != null) {
                ws.abort();
            }
        }
    }

    // ==================================================================

    private static String findChrome() {
        String env = System.getenv("CHROME_BIN");
        List<String> candidates = new java.util.ArrayList<>();
        if (env != null && !env.isBlank()) {
            candidates.add(env);
        }
        candidates.addAll(List.of(
                "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium", "/usr/bin/chromium-browser",
                "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"));
        for (String c : candidates) {
            if (Files.isExecutable(Path.of(c))) {
                return c;
            }
        }
        // Playwright 预装的浏览器（本地开发容器常见）
        String pw = System.getenv("PLAYWRIGHT_BROWSERS_PATH");
        if (pw != null && Files.isDirectory(Path.of(pw))) {
            try (var s = Files.walk(Path.of(pw), 3)) {
                return s.filter(p -> p.getFileName().toString().equals("chrome")
                                && Files.isExecutable(p))
                        .map(Path::toString).findFirst().orElse(null);
            } catch (Exception ignored) {
                return null;
            }
        }
        return null;
    }

    private static int freePort() throws Exception {
        try (var s = new java.net.ServerSocket(0)) {
            return s.getLocalPort();
        }
    }

    static {
        // 冒烟进程起得慢，给 CDP 等待留足余量
        HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5));
    }
}

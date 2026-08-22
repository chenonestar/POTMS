package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.potms.service.Excel;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;
import java.util.zip.ZipFile;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** Excel 导出：表结构、签名嵌图、文件名回退。 */
class ExcelTest {

    private Path dir;

    @BeforeEach
    void setUp() throws IOException {
        dir = Files.createTempDirectory("potms-xls-");
    }

    @AfterEach
    void tearDown() throws IOException {
        try (var s = Files.walk(dir)) {
            s.sorted(java.util.Comparator.reverseOrder()).forEach(p -> {
                try {
                    Files.deleteIfExists(p);
                } catch (IOException ignored) {
                    // 清理失败不影响结论
                }
            });
        }
    }

    @Test
    @DisplayName("普通导出：生成合法 xlsx，含标题与表头")
    void writesPlainSheet() throws IOException {
        var spec = new Excel.SheetSpec("测试表", List.of("姓名", "单位"),
                List.of(List.of("史迪威", "总部")), List.of("说明：这是一行注释。"));
        var r = Excel.write(dir, spec, "测试表", "admin", null);
        assertTrue(Files.size(r.path()) > 0);
        assertTrue(r.fileName().startsWith("测试表_"), "下载名应保留中文");
        try (var zip = new ZipFile(r.path().toFile())) {
            String ss = new String(zip.getInputStream(zip.getEntry("xl/sharedStrings.xml"))
                    .readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
            assertTrue(ss.contains("史迪威"));
            assertTrue(ss.contains("说明：这是一行注释。"));
        }
    }

    /**
     * 签名嵌图：POI 借 JDK 自带 ImageIO 算尺寸，不需要第三方图像库。
     * Python 版与 .NET 版为避开 Pillow / ImageSharp 都得手写 IHDR 解析器。
     */
    @Test
    @DisplayName("签名列嵌入真实 PNG，产物里能找到 media 与 drawing")
    void embedsSignatureImage() throws IOException {
        byte[] png = onePixelPng();
        var spec = new Excel.SheetSpec("领用表", List.of("领用人", "签名"),
                List.of(Arrays.asList("史迪威", png)), null);
        var r = Excel.write(dir, spec, "领用表", "admin", List.of(1));
        try (var zip = new ZipFile(r.path().toFile())) {
            boolean media = zip.stream().anyMatch(e -> e.getName().startsWith("xl/media/"));
            boolean drawing = zip.stream().anyMatch(e -> e.getName().startsWith("xl/drawings/drawing"));
            assertTrue(media, "未找到内嵌图片");
            assertTrue(drawing, "未找到 drawing 关系");
        }
    }

    @Test
    @DisplayName("签名为空时不嵌图，也不报错")
    void toleratesMissingSignature() throws IOException {
        var spec = new Excel.SheetSpec("领用表", List.of("领用人", "签名"),
                List.of(Arrays.asList("无签名", null)), null);
        var r = Excel.write(dir, spec, "领用表", "admin", List.of(1));
        assertTrue(Files.size(r.path()) > 0);
    }

    /**
     * 落盘名与下载名分离：C/POSIX 语系下文件系统编码表示不了中文，
     * 直接用中文名会抛 Malformed input。此时应退回 ASCII 名而不是导出失败。
     */
    @Test
    @DisplayName("文件系统编不了中文时，落盘名退回 ASCII，下载名仍为中文")
    void fallsBackToAsciiDiskName() throws IOException {
        var spec = new Excel.SheetSpec("表", List.of("列"), List.of(List.of("值")), null);
        var r = Excel.write(dir, spec, "因私出国境证件领用登记表", "admin", null);

        assertTrue(r.fileName().startsWith("因私出国境证件领用登记表_"), "下载名必须保留中文");
        String enc = System.getProperty("sun.jnu.encoding");
        boolean fsSupportsChinese = enc != null
                && java.nio.charset.Charset.forName(enc).newEncoder().canEncode(r.fileName());
        String onDisk = r.path().getFileName().toString();
        if (fsSupportsChinese) {
            assertEquals(r.fileName(), onDisk);
        } else {
            assertTrue(onDisk.startsWith("export_"), "应退回 ASCII 名，实际为 " + onDisk);
            assertFalse(onDisk.chars().anyMatch(c -> c > 127), "回退名不应含非 ASCII 字符");
        }
        assertTrue(Files.exists(r.path()));
    }

    private static byte[] onePixelPng() {
        return java.util.Base64.getDecoder().decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                + "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==");
    }
}

package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.potms.service.Sm2Seal;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** 国密 SM2 签章：自签模式下的签 / 验 / 防篡改。 */
class Sm2SealTest {

    private Path dir;
    private Config cfg;
    private Sm2Seal seal;

    private static final byte[] PNG = "fake-png-bytes".getBytes(StandardCharsets.UTF_8);
    private static final String META = "{\"strokes\":[[{\"x\":1,\"y\":2}]]}";
    private static final String FACTS = "史迪威|110101199001012133|01|E1234567|20260802";

    @BeforeEach
    void setUp() throws IOException {
        dir = Files.createTempDirectory("potms-sm2-");
        cfg = new Config(dir);
        seal = new Sm2Seal(cfg);
    }

    @AfterEach
    void tearDown() throws IOException {
        try (var s = Files.walk(dir)) {
            s.sorted(java.util.Comparator.reverseOrder()).forEach(p -> {
                try {
                    Files.deleteIfExists(p);
                } catch (IOException ignored) {
                    // 临时目录清理失败不影响用例结论
                }
            });
        }
    }

    @Test
    @DisplayName("自签模式：首次调用生成密钥并落盘，签章后可自验")
    void signAndVerify() {
        var s = seal.sign(PNG, META, FACTS);
        assertEquals(Sm2Seal.Source.SELF_SIGNED, s.source());
        assertEquals(64, s.payloadHash().length(), "SM3 摘要应为 32 字节 / 64 个十六进制字符");
        assertFalse(s.signatureHex().isEmpty());
        assertTrue(Files.exists(dir.resolve(".sm2.p12")), "密钥应落盘复用");
        assertTrue(seal.verify(PNG, META, FACTS, s.signatureHex()));
    }

    @Test
    @DisplayName("防篡改：签名图 / 笔迹 / 领用要素任一被改，验章即失败")
    void tamperDetection() {
        var s = seal.sign(PNG, META, FACTS);

        byte[] tamperedPng = "fake-png-byteS".getBytes(StandardCharsets.UTF_8);
        assertFalse(seal.verify(tamperedPng, META, FACTS, s.signatureHex()), "改签名图应验章失败");
        assertFalse(seal.verify(PNG, "{\"strokes\":[]}", FACTS, s.signatureHex()), "改笔迹应验章失败");
        assertFalse(seal.verify(PNG, META, FACTS.replace("20260802", "20260801"), s.signatureHex()),
                "改领用日期应验章失败");
    }

    @Test
    @DisplayName("规范化拼装：字段边界不可被挪动（防拼接歧义）")
    void canonicalPayloadIsUnambiguous() {
        // 「张三」+「123」与「张」+「三123」若简单相接会得到同一串，
        // 加了单元分隔符后必须不同
        byte[] a = Sm2Seal.canonicalPayload(null, "张三", "123");
        byte[] b = Sm2Seal.canonicalPayload(null, "张", "三123");
        assertNotEquals(java.util.Arrays.toString(a), java.util.Arrays.toString(b));
    }

    @Test
    @DisplayName("密钥复用：同一数据目录再次装载得到同一证书")
    void keyIsReused() {
        var first = seal.sign(PNG, META, FACTS);
        var second = new Sm2Seal(cfg);
        assertEquals(first.certSerial(), second.sign(PNG, META, FACTS).certSerial());
        // 换一个实例仍能验早先的章
        assertTrue(second.verify(PNG, META, FACTS, first.signatureHex()));
    }

    @Test
    @DisplayName("证书可导出为 PEM，便于归档与外部独立验章")
    void exportsPem() {
        seal.sign(PNG, META, FACTS);
        String pem = seal.certificatePem();
        assertTrue(pem.startsWith("-----BEGIN CERTIFICATE-----"));
        assertTrue(pem.trim().endsWith("-----END CERTIFICATE-----"));
    }
}

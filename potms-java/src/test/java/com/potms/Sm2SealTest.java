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
        assertTrue(seal.verify(PNG, META, FACTS, s.signatureHex(), s.signedAt()));
    }

    @Test
    @DisplayName("防篡改：签名图 / 笔迹 / 领用要素任一被改，验章即失败")
    void tamperDetection() {
        var s = seal.sign(PNG, META, FACTS);

        byte[] tamperedPng = "fake-png-byteS".getBytes(StandardCharsets.UTF_8);
        assertFalse(seal.verify(tamperedPng, META, FACTS, s.signatureHex(), s.signedAt()),
                "改签名图应验章失败");
        assertFalse(seal.verify(PNG, "{\"strokes\":[]}", FACTS, s.signatureHex(), s.signedAt()),
                "改笔迹应验章失败");
        assertFalse(seal.verify(PNG, META, FACTS.replace("20260802", "20260801"),
                s.signatureHex(), s.signedAt()), "改领用日期应验章失败");
    }

    @Test
    @DisplayName("规范化拼装：字段边界不可被挪动（防拼接歧义）")
    void canonicalPayloadIsUnambiguous() {
        // 「张三」+「123」与「张」+「三123」若简单相接会得到同一串，
        // 加了单元分隔符后必须不同
        byte[] a = Sm2Seal.canonicalPayload(null, "张三", "123", "T");
        byte[] b = Sm2Seal.canonicalPayload(null, "张", "三123", "T");
        assertNotEquals(java.util.Arrays.toString(a), java.util.Arrays.toString(b));
    }

    @Test
    @DisplayName("密钥复用：同一数据目录再次装载得到同一证书")
    void keyIsReused() {
        var first = seal.sign(PNG, META, FACTS);
        var second = new Sm2Seal(cfg);
        assertEquals(first.certSerial(), second.sign(PNG, META, FACTS).certSerial());
        // 换一个实例仍能验早先的章
        assertTrue(second.verify(PNG, META, FACTS, first.signatureHex(), first.signedAt()));
    }


    @Test
    @DisplayName("签章时间在载荷内：改 signed_at 即验章失败")
    void signedAtIsTamperEvident() {
        var s = seal.sign(PNG, META, FACTS);
        assertFalse(s.signedAt().isEmpty(), "签章时间不应为空");
        assertTrue(seal.verify(PNG, META, FACTS, s.signatureHex(), s.signedAt()),
                "原时间应验得过");

        // 这正是改动前的漏洞：谁能写库，谁就能把签章时间改到任意时点而签名照旧
        assertFalse(seal.verify(PNG, META, FACTS, s.signatureHex(), "2026-03-01T00:00:00Z"),
                "改签章时间应验章失败");
        assertFalse(seal.verify(PNG, META, FACTS, s.signatureHex(), ""),
                "抹掉签章时间应验章失败");
    }

    @Test
    @DisplayName("同样的内容两次签章，因时间不同而签名不同")
    void signatureVariesWithTime() throws InterruptedException {
        var a = seal.sign(PNG, META, FACTS);
        Thread.sleep(5);   // Instant 精度足够，睡一下确保时间确实推进
        var b = seal.sign(PNG, META, FACTS);
        assertNotEquals(a.signedAt(), b.signedAt());
        assertNotEquals(a.payloadHash(), b.payloadHash(),
                "时间已进载荷，摘要就该跟着变");
    }

    @Test
    @DisplayName("旧版签章（时间在载荷外）仍验得过，但要被识别为旧版")
    void legacySealStillVerifies() {
        // 手工造一枚改动前形态的章：对三字段载荷签名
        var s = seal.sign(PNG, META, FACTS);   // 先触发密钥生成
        assertFalse(seal.verifyLegacy(PNG, META, FACTS, s.signatureHex()),
                "新章不该被旧路认成有效——否则新章里被篡改的时间会被放行");

        // 直接用旧载荷签一枚，模拟历史存证。刻意不往生产代码开测试专用口子，
        // 而是从落盘的 .sm2.p12 里取同一把私钥自己签——这样测的是真实密钥路径。
        String legacyHex = signWithStoredKey(Sm2Seal.canonicalPayload(PNG, META, FACTS, null));
        assertTrue(seal.verifyLegacy(PNG, META, FACTS, legacyHex), "旧章应仍能验过");
        assertFalse(seal.verify(PNG, META, FACTS, legacyHex, s.signedAt()),
                "旧章不该被当成新章验过");
    }

    @Test
    @DisplayName("证书可导出为 PEM，便于归档与外部独立验章")
    void exportsPem() {
        seal.sign(PNG, META, FACTS);
        String pem = seal.certificatePem();
        assertTrue(pem.startsWith("-----BEGIN CERTIFICATE-----"));
        assertTrue(pem.trim().endsWith("-----END CERTIFICATE-----"));
    }

    /**
     * 用落盘的 .sm2.p12 私钥对给定载荷签名，用来伪造一枚「改动前形态」的章。
     *
     * <p>口令写死成与 Sm2Seal 相同的默认值：一旦那边改了口令，这里会当场失败，
     * 正好提醒来同步——这是想要的效果。
     */
    private String signWithStoredKey(byte[] payload) {
        try {
            if (java.security.Security.getProvider("BC") == null) {
                java.security.Security.addProvider(
                        new org.bouncycastle.jce.provider.BouncyCastleProvider());
            }
            var ks = java.security.KeyStore.getInstance("PKCS12", "BC");
            try (var in = Files.newInputStream(dir.resolve(".sm2.p12"))) {
                ks.load(in, "potms".toCharArray());
            }
            String alias = ks.aliases().nextElement();
            var key = (java.security.PrivateKey) ks.getKey(alias, "potms".toCharArray());
            var sig = java.security.Signature.getInstance("SM3withSM2", "BC");
            sig.initSign(key);
            sig.update(payload);
            return java.util.HexFormat.of().formatHex(sig.sign());
        } catch (Exception e) {
            throw new IllegalStateException("测试内签名失败", e);
        }
    }
}

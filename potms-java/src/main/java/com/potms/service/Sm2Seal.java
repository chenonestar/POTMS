package com.potms.service;

import com.potms.Config;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.SecureRandom;
import java.security.Security;
import java.security.cert.X509Certificate;
import java.security.spec.ECGenParameterSpec;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Date;
import java.util.HexFormat;
import org.bouncycastle.asn1.x500.X500Name;
import org.bouncycastle.cert.jcajce.JcaX509CertificateConverter;
import org.bouncycastle.cert.jcajce.JcaX509v3CertificateBuilder;
import org.bouncycastle.jce.provider.BouncyCastleProvider;
import org.bouncycastle.operator.jcajce.JcaContentSignerBuilder;

/**
 * 国密 SM2 签章 — 给手写签名加一层防篡改绑定。
 *
 * <p><b>为什么需要它。</b>手写签名位图本身在《电子签名法》下不构成可靠电子签名：
 * 谁有数据库写权限，谁就能换掉那张图，事后无法自证。这里用 SM3withSM2 对
 * 「签名图摘要 + 笔迹矢量摘要 + 领用要素」整体签章，锁死这份凭证。
 *
 * <p><b>证书来源可配置</b>，三种模式业务代码一致，只换密钥装载方式：
 * <ul>
 *   <li>{@code selfsigned}（默认）：首次运行自动生成 SM2 密钥对与自签证书，
 *       存于数据目录的 {@code .sm2.p12}。<b>只防内部篡改，不能对外举证</b>——
 *       没有第三方证明这个公钥属于本单位。零成本、零采购。
 *   <li>{@code pkcs12}：加载有资质 CA 签发的 .p12 证书文件，构成可靠电子签名。
 *   <li>{@code pkcs11}：走 USB Key / 智能密码钥匙，私钥不出介质。
 * </ul>
 *
 * <p>切换来源只改环境变量，不动业务逻辑——这正是当初把「证书来源」
 * 定为可配置项的目的。
 */
public final class Sm2Seal {

    static {
        if (Security.getProvider(BouncyCastleProvider.PROVIDER_NAME) == null) {
            Security.addProvider(new BouncyCastleProvider());
        }
    }

    private static final String BC = BouncyCastleProvider.PROVIDER_NAME;
    private static final String SIG_ALGO = "SM3withSM2";
    private static final String CURVE = "sm2p256v1";
    private static final char[] DEFAULT_PASSWORD = "potms".toCharArray();

    /** 证书来源模式。 */
    public enum Source {
        SELF_SIGNED, PKCS12, PKCS11;

        static Source parse(String s) {
            if (s == null) {
                return SELF_SIGNED;
            }
            return switch (s.trim().toLowerCase()) {
                case "pkcs12", "p12" -> PKCS12;
                case "pkcs11", "usbkey", "ukey" -> PKCS11;
                default -> SELF_SIGNED;
            };
        }
    }

    /** 一次签章的结果。 */
    public record Seal(String payloadHash, String signatureHex, String certSubject,
                       String certSerial, String signedAt, Source source) {}

    private final Config cfg;
    private final Source source;
    private PrivateKey privateKey;
    private X509Certificate certificate;

    public Sm2Seal(Config cfg) {
        this.cfg = cfg;
        this.source = Source.parse(System.getenv("POTMS_SM2_SOURCE"));
    }

    public Source source() {
        return source;
    }

    /** 当前证书主体，供页面展示；未就绪时返回空串。 */
    public String subject() {
        try {
            ensureLoaded();
            return certificate.getSubjectX500Principal().getName();
        } catch (RuntimeException e) {
            return "";
        }
    }

    /**
     * 对领用凭证签章。
     *
     * @param signImage 手写签名 PNG 字节（可为 null）
     * @param signMeta  笔迹矢量 JSON（可为 null）
     * @param facts     领用要素的规范化串（领用人 / 证件号 / 日期等）
     */
    public Seal sign(byte[] signImage, String signMeta, String facts) {
        ensureLoaded();
        byte[] payload = canonicalPayload(signImage, signMeta, facts);
        String hash = HexFormat.of().formatHex(sm3(payload));
        try {
            var sig = java.security.Signature.getInstance(SIG_ALGO, BC);
            sig.initSign(privateKey);
            sig.update(payload);
            String hex = HexFormat.of().formatHex(sig.sign());
            return new Seal(hash, hex,
                    certificate.getSubjectX500Principal().getName(),
                    certificate.getSerialNumber().toString(16),
                    Instant.now().toString(), source);
        } catch (java.security.GeneralSecurityException e) {
            throw new IllegalStateException("SM2 签章失败: " + e.getMessage(), e);
        }
    }

    /** 用当前证书公钥验章。凭证被改过任何一个字节，这里就会返回 false。 */
    public boolean verify(byte[] signImage, String signMeta, String facts, String signatureHex) {
        ensureLoaded();
        try {
            var sig = java.security.Signature.getInstance(SIG_ALGO, BC);
            sig.initVerify(certificate.getPublicKey());
            sig.update(canonicalPayload(signImage, signMeta, facts));
            return sig.verify(HexFormat.of().parseHex(signatureHex));
        } catch (java.security.GeneralSecurityException | IllegalArgumentException e) {
            return false;
        }
    }

    /**
     * 待签数据的规范化拼装。字段以 0x1F（单元分隔符）连接，避免
     * 「张三|123」与「张|三123」这类拼接歧义被用来构造碰撞。
     */
    public static byte[] canonicalPayload(byte[] signImage, String signMeta, String facts) {
        var out = new java.io.ByteArrayOutputStream();
        writeField(out, signImage == null ? new byte[0] : sm3(signImage));
        writeField(out, (signMeta == null ? "" : signMeta).getBytes(StandardCharsets.UTF_8));
        writeField(out, (facts == null ? "" : facts).getBytes(StandardCharsets.UTF_8));
        return out.toByteArray();
    }

    private static void writeField(java.io.ByteArrayOutputStream out, byte[] b) {
        out.write(b, 0, b.length);
        out.write(0x1F);
    }

    static byte[] sm3(byte[] data) {
        try {
            return MessageDigest.getInstance("SM3", BC).digest(data);
        } catch (java.security.GeneralSecurityException e) {
            throw new IllegalStateException("缺少 SM3 实现", e);
        }
    }

    // ------------------------------------------------------------------
    // 密钥装载
    // ------------------------------------------------------------------

    private synchronized void ensureLoaded() {
        if (privateKey != null) {
            return;
        }
        switch (source) {
            case PKCS12 -> loadPkcs12();
            case PKCS11 -> loadPkcs11();
            default -> loadOrCreateSelfSigned();
        }
    }

    private void loadPkcs12() {
        String path = env("POTMS_SM2_KEYSTORE");
        if (path == null) {
            throw new IllegalStateException("POTMS_SM2_SOURCE=pkcs12 时必须设置 POTMS_SM2_KEYSTORE");
        }
        char[] pw = password();
        try (InputStream in = Files.newInputStream(Path.of(path))) {
            KeyStore ks = KeyStore.getInstance("PKCS12", BC);
            ks.load(in, pw);
            adopt(ks, pw);
        } catch (IOException | java.security.GeneralSecurityException e) {
            throw new IllegalStateException("加载 PKCS#12 证书失败: " + e.getMessage(), e);
        }
    }

    /**
     * USB Key / 智能密码钥匙。厂商 PKCS#11 驱动路径由 POTMS_SM2_PKCS11_LIB 指定，
     * JDK 自带的 SunPKCS11 负责桥接；私钥不出介质，只把待签数据送进去。
     */
    private void loadPkcs11() {
        String lib = env("POTMS_SM2_PKCS11_LIB");
        if (lib == null) {
            throw new IllegalStateException("POTMS_SM2_SOURCE=pkcs11 时必须设置 POTMS_SM2_PKCS11_LIB");
        }
        String conf = "name=POTMS\nlibrary=" + lib + "\n";
        var p = Security.getProvider("SunPKCS11");
        if (p == null) {
            throw new IllegalStateException("当前 JDK 不含 SunPKCS11，无法使用 USB Key");
        }
        var configured = p.configure("--" + conf);
        Security.addProvider(configured);
        char[] pw = password();
        try {
            KeyStore ks = KeyStore.getInstance("PKCS11", configured);
            ks.load(null, pw);
            adopt(ks, pw);
        } catch (IOException | java.security.GeneralSecurityException e) {
            throw new IllegalStateException("加载 USB Key 证书失败: " + e.getMessage(), e);
        }
    }

    private void adopt(KeyStore ks, char[] pw) throws java.security.GeneralSecurityException {
        String alias = env("POTMS_SM2_ALIAS");
        if (alias == null) {
            var it = ks.aliases().asIterator();
            while (it.hasNext()) {
                String a = it.next();
                if (ks.isKeyEntry(a)) {
                    alias = a;
                    break;
                }
            }
        }
        if (alias == null) {
            throw new IllegalStateException("证书库中未找到可用的密钥条目");
        }
        privateKey = (PrivateKey) ks.getKey(alias, pw);
        certificate = (X509Certificate) ks.getCertificate(alias);
        if (privateKey == null || certificate == null) {
            throw new IllegalStateException("证书库条目 " + alias + " 缺少私钥或证书");
        }
    }

    /** 自签模式：首次调用生成并落盘，之后复用。 */
    private void loadOrCreateSelfSigned() {
        Path store = cfg.baseDir.resolve(".sm2.p12");
        char[] pw = password();
        try {
            if (Files.exists(store)) {
                try (InputStream in = Files.newInputStream(store)) {
                    KeyStore ks = KeyStore.getInstance("PKCS12", BC);
                    ks.load(in, pw);
                    adopt(ks, pw);
                    return;
                }
            }
            KeyPair kp = generateSm2KeyPair();
            X509Certificate cert = selfSign(kp);
            KeyStore ks = KeyStore.getInstance("PKCS12", BC);
            ks.load(null, pw);
            ks.setKeyEntry("potms", kp.getPrivate(), pw, new java.security.cert.Certificate[] {cert});
            try (OutputStream out = Files.newOutputStream(store)) {
                ks.store(out, pw);
            }
            privateKey = kp.getPrivate();
            certificate = cert;
        } catch (IOException | java.security.GeneralSecurityException e) {
            throw new IllegalStateException("自签 SM2 证书失败: " + e.getMessage(), e);
        }
    }

    static KeyPair generateSm2KeyPair() throws java.security.GeneralSecurityException {
        var gen = KeyPairGenerator.getInstance("EC", BC);
        gen.initialize(new ECGenParameterSpec(CURVE), new SecureRandom());
        return gen.generateKeyPair();
    }

    private X509Certificate selfSign(KeyPair kp) throws java.security.GeneralSecurityException {
        String cn = env("POTMS_SM2_SUBJECT");
        X500Name subject = new X500Name("CN=" + (cn == null ? "POTMS 自签存证" : cn) + ", C=CN");
        Instant now = Instant.now();
        var builder = new JcaX509v3CertificateBuilder(
                subject,
                new BigInteger(64, new SecureRandom()),
                Date.from(now.minus(1, ChronoUnit.DAYS)),
                Date.from(now.plus(3650, ChronoUnit.DAYS)),
                subject,
                kp.getPublic());
        try {
            var signer = new JcaContentSignerBuilder(SIG_ALGO).setProvider(BC).build(kp.getPrivate());
            return new JcaX509CertificateConverter().setProvider(BC)
                    .getCertificate(builder.build(signer));
        } catch (org.bouncycastle.operator.OperatorCreationException e) {
            throw new java.security.GeneralSecurityException("构造签名器失败", e);
        }
    }

    private static char[] password() {
        String pw = env("POTMS_SM2_PASSWORD");
        return pw == null ? DEFAULT_PASSWORD : pw.toCharArray();
    }

    private static String env(String key) {
        String v = System.getenv(key);
        return (v == null || v.isBlank()) ? null : v;
    }

    /** 供公钥导出/存档：证书的 PEM 形式。 */
    public String certificatePem() {
        ensureLoaded();
        try {
            return "-----BEGIN CERTIFICATE-----\n"
                    + java.util.Base64.getMimeEncoder(64, new byte[] {'\n'})
                            .encodeToString(certificate.getEncoded())
                    + "\n-----END CERTIFICATE-----\n";
        } catch (java.security.cert.CertificateEncodingException e) {
            return "";
        }
    }

    /** 公钥，供外部独立验章。 */
    public PublicKey publicKey() {
        ensureLoaded();
        return certificate.getPublicKey();
    }
}

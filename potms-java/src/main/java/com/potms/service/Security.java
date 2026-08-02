package com.potms.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.spec.InvalidKeySpecException;
import java.util.HexFormat;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

/**
 * 密码哈希与校验 — 对应 Python 版 utils/security.py。
 *
 * <p>五个语言版本共用同一张 users 表，因此本实现必须能验证 Python 版 bcrypt
 * 生成的哈希；同时兼容更早的 werkzeug {@code pbkdf2:sha256} 哈希，登录时透明升级。
 */
public final class Security {

    private Security() {}

    private static final BCryptPasswordEncoder ENCODER = new BCryptPasswordEncoder();

    /** 校验结果：是否匹配 / 是否需要升级为 bcrypt。 */
    public record Result(boolean matched, boolean needsRehash) {}

    public static String hashPassword(String password) {
        return ENCODER.encode(password);
    }

    public static Result verifyPassword(String password, String storedHash) {
        if (storedHash == null || storedHash.isEmpty()) {
            return new Result(false, false);
        }
        if (storedHash.startsWith("$2")) {
            try {
                return new Result(ENCODER.matches(password, storedHash), false);
            } catch (IllegalArgumentException e) {
                return new Result(false, false);   // 哈希格式损坏
            }
        }
        // 旧 werkzeug 哈希：校验通过则需要升级
        boolean ok = verifyWerkzeug(password, storedHash);
        return new Result(ok, ok);
    }

    /**
     * 兼容 werkzeug 的 {@code pbkdf2:sha256:<iters>$<salt>$<hex>} 格式。
     *
     * <p>只支持 pbkdf2 系；werkzeug 的 scrypt 变体 JDK 无内置实现，
     * 遇到时返回 false（用户走"忘记密码"重置，不影响 bcrypt 主路径）。
     */
    private static boolean verifyWerkzeug(String password, String stored) {
        String[] parts = stored.split("\\$");
        if (parts.length != 3) {
            return false;
        }
        String[] method = parts[0].split(":");
        if (method.length < 2 || !"pbkdf2".equals(method[0])) {
            return false;
        }
        String algo = method[1];
        int iterations;
        try {
            iterations = method.length >= 3 ? Integer.parseInt(method[2]) : 260000;
        } catch (NumberFormatException e) {
            return false;
        }
        String jcaAlgo = switch (algo) {
            case "sha256" -> "PBKDF2WithHmacSHA256";
            case "sha512" -> "PBKDF2WithHmacSHA512";
            case "sha1" -> "PBKDF2WithHmacSHA1";
            default -> null;
        };
        if (jcaAlgo == null) {
            return false;
        }
        int bits = switch (algo) {
            case "sha512" -> 512;
            case "sha1" -> 160;
            default -> 256;
        };
        try {
            var spec = new PBEKeySpec(password.toCharArray(),
                    parts[1].getBytes(StandardCharsets.UTF_8), iterations, bits);
            byte[] derived = SecretKeyFactory.getInstance(jcaAlgo).generateSecret(spec).getEncoded();
            return constantTimeEquals(HexFormat.of().formatHex(derived), parts[2]);
        } catch (NoSuchAlgorithmException | InvalidKeySpecException e) {
            return false;
        }
    }

    /** 定长比较，避免按字符早退泄露信息。 */
    public static boolean constantTimeEquals(String a, String b) {
        if (a == null || b == null) {
            return false;
        }
        return MessageDigest.isEqual(a.getBytes(StandardCharsets.UTF_8),
                b.getBytes(StandardCharsets.UTF_8));
    }
}

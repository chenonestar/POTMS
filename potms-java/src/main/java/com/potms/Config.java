package com.potms;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.util.HexFormat;
import org.springframework.stereotype.Component;

/** 应用配置 — 对应 Python 版 config.py / Rust 版 config.rs / .NET 版 Config.cs。 */
@Component
public class Config {

    // ---- 与其它四版保持一致的常量 ----
    public static final int PAGE_SIZE = 12;               // 业务列表每页
    public static final int PAGE_SIZE_LOGS = 10;          // 操作日志每页（含变更详情，取更小值）
    public static final int CERT_EXPIRY_WARN_DAYS = 30;   // 证照到期预警
    public static final long MAX_CONTENT_LENGTH = 20L * 1024 * 1024;
    public static final int SESSION_TIMEOUT_SECONDS = 1800;
    public static final int LOCK_THRESHOLD = 5;           // 登录失败锁定阈值
    public static final int LOCK_SECONDS = 600;

    /** 数据目录：data.db / uploads / exports / backup 均位于此。 */
    public final Path baseDir;
    public final Path database;
    public final Path uploadFolder;
    public final Path exportFolder;
    public final Path backupFolder;
    public final byte[] secretKey;
    public final int tzOffsetHours;

    public Config() {
        this(null);
    }

    public Config(Path base) {
        Path b = base;
        if (b == null) {
            String env = System.getenv("POTMS_BASE");
            // 优先级：显式传入 → 环境变量 POTMS_BASE → 当前工作目录
            b = (env != null && !env.isBlank()) ? Path.of(env) : Path.of("").toAbsolutePath();
        }
        this.baseDir = b.toAbsolutePath();
        this.database = baseDir.resolve("data.db");
        this.uploadFolder = baseDir.resolve("uploads");
        this.exportFolder = baseDir.resolve("exports");
        this.backupFolder = baseDir.resolve("backup");
        try {
            Files.createDirectories(baseDir);
            for (Path d : new Path[] {uploadFolder, exportFolder, backupFolder}) {
                Files.createDirectories(d);
            }
        } catch (IOException e) {
            throw new IllegalStateException("创建数据目录失败: " + baseDir, e);
        }

        String tz = System.getenv("POTMS_TZ_OFFSET");
        int off = 8;
        if (tz != null && !tz.isBlank()) {
            try {
                off = Integer.parseInt(tz.trim());
            } catch (NumberFormatException ignored) {
                // 非法值退回默认东八区，不因配置笔误拒绝启动
            }
        }
        this.tzOffsetHours = off;
        this.secretKey = loadOrCreateSecret();
    }

    public String jdbcUrl() {
        return "jdbc:sqlite:" + database;
    }

    /** 持久化密钥到数据目录，避免重启导致会话失效。 */
    private byte[] loadOrCreateSecret() {
        String env = System.getenv("SECRET_KEY");
        if (env != null && !env.isBlank()) {
            return env.getBytes(StandardCharsets.UTF_8);
        }
        Path file = baseDir.resolve(".secret_key");
        try {
            if (Files.exists(file)) {
                String existing = Files.readString(file, StandardCharsets.UTF_8).trim();
                if (!existing.isEmpty()) {
                    return existing.getBytes(StandardCharsets.UTF_8);
                }
            }
            byte[] raw = new byte[32];
            new SecureRandom().nextBytes(raw);
            String val = HexFormat.of().formatHex(raw);
            Files.writeString(file, val, StandardCharsets.UTF_8);
            return val.getBytes(StandardCharsets.UTF_8);
        } catch (IOException e) {
            // 落盘失败不阻断启动：退化为进程内临时密钥（重启后会话失效）
            byte[] raw = new byte[32];
            new SecureRandom().nextBytes(raw);
            return HexFormat.of().formatHex(raw).getBytes(StandardCharsets.UTF_8);
        }
    }
}

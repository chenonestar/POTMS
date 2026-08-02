package com.potms.service;

import com.potms.Config;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Comparator;
import java.util.List;
import java.util.stream.Stream;

/** 数据库每日自动备份 + 保留 30 天 — 对应 Python 版 utils/backup.py。 */
public final class Backup {

    private Backup() {}

    public static final int RETAIN_DAYS = 30;
    private static final String PREFIX = "data_";
    private static final String SUFFIX = ".db";
    private static final DateTimeFormatter YMD = DateTimeFormatter.ofPattern("yyyyMMdd");

    /**
     * 进程内「今日已检查」标记：首页每次访问都会触发备份检查，
     * 同一天第二次起直接跳过文件系统扫描。
     */
    private static volatile String checkedDate;

    public record Result(boolean created, Path path, int pruned, String date) {}

    /** 最近一次备份的 (文件名, 日期)；无备份时两者皆为 null。 */
    public record Latest(String fileName, String date) {}

    public static Latest latest(Config cfg) {
        if (!Files.isDirectory(cfg.backupFolder)) {
            return new Latest(null, null);
        }
        try (Stream<Path> s = Files.list(cfg.backupFolder)) {
            List<String> files = s.map(p -> p.getFileName().toString())
                    .filter(n -> n.startsWith(PREFIX) && n.endsWith(SUFFIX))
                    .sorted(Comparator.reverseOrder())
                    .toList();
            if (files.isEmpty()) {
                return new Latest(null, null);
            }
            String f = files.get(0);
            return new Latest(f, f.substring(PREFIX.length(), f.length() - SUFFIX.length()));
        } catch (IOException e) {
            return new Latest(null, null);
        }
    }

    /** 删除超过保留期的备份，返回删除数量。 */
    public static int pruneOld(Config cfg, int retainDays) {
        if (!Files.isDirectory(cfg.backupFolder)) {
            return 0;
        }
        String cutoff = today(cfg).minusDays(retainDays).format(YMD);
        int removed = 0;
        try (Stream<Path> s = Files.list(cfg.backupFolder)) {
            for (Path p : s.toList()) {
                String n = p.getFileName().toString();
                if (!n.startsWith(PREFIX) || !n.endsWith(SUFFIX)) {
                    continue;
                }
                String date = n.substring(PREFIX.length(), n.length() - SUFFIX.length());
                if (date.chars().allMatch(Character::isDigit) && date.compareTo(cutoff) < 0) {
                    try {
                        Files.delete(p);
                        removed++;
                    } catch (IOException ignored) {
                        // 文件被占用等情况跳过，不影响本次备份主流程
                    }
                }
            }
        } catch (IOException ignored) {
            return removed;
        }
        return removed;
    }

    public static Result runDaily(Config cfg) {
        return runDaily(cfg, false);
    }

    /**
     * 执行每日备份（幂等）：当天已有备份则跳过；force=true 时强制覆盖。
     * 完成后清理超过保留期的旧备份。
     */
    public static Result runDaily(Config cfg, boolean force) {
        String date = today(cfg).format(YMD);
        if (!force && date.equals(checkedDate)) {
            return new Result(false, null, 0, date);
        }
        Path target = cfg.backupFolder.resolve(PREFIX + date + SUFFIX);
        boolean created = false;
        if (force || !Files.exists(target)) {
            try {
                Files.createDirectories(cfg.backupFolder);
                // 直接拷贝库文件：单用户系统无并发写入，且与其它四版做法一致
                Files.copy(cfg.database, target, StandardCopyOption.REPLACE_EXISTING);
                created = true;
            } catch (IOException e) {
                throw new IllegalStateException("备份失败: " + e.getMessage(), e);
            }
        }
        int pruned = pruneOld(cfg, RETAIN_DAYS);
        checkedDate = date;
        return new Result(created, target, pruned, date);
    }

    private static LocalDate today(Config cfg) {
        return LocalDate.ofInstant(java.time.Instant.now(),
                ZoneOffset.ofHours(cfg.tzOffsetHours));
    }

    /** 供测试使用：清除「今日已检查」标记。 */
    public static void resetCheckedDate() {
        checkedDate = null;
    }
}

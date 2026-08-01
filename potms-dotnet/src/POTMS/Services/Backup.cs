using System.Globalization;

namespace POTMS.Services;

/// <summary>数据库每日备份 + 保留 30 天 — 对应 Python 版 utils/backup.py。</summary>
public static class Backup
{
    private const int RetainDays = 30;
    private const string Prefix = "data_";
    private const string Suffix = ".db";

    private static string? _checkedDate;   // 进程内「今日已检查」标记

    /// <summary>执行每日备份（幂等）：当天已有备份则跳过；force 强制重做。
    /// 返回 (日期 YYYYMMDD, 是否新建, 清理数量)。</summary>
    public static (string Date, bool Created, int Pruned) RunDaily(Config cfg, bool force = false)
    {
        var today = DateTime.UtcNow.AddHours(cfg.TzOffsetHours).ToString("yyyyMMdd", CultureInfo.InvariantCulture);
        if (!force && _checkedDate == today) return (today, false, 0);

        Directory.CreateDirectory(cfg.BackupFolder);
        var dest = Path.Combine(cfg.BackupFolder, $"{Prefix}{today}{Suffix}");

        var created = false;
        if (File.Exists(cfg.Database) && (force || !File.Exists(dest)))
        {
            // 用 VACUUM INTO 生成一致性快照（含已合并的 WAL），比直接复制文件更安全
            using var cn = new Microsoft.Data.Sqlite.SqliteConnection($"Data Source={cfg.Database}");
            cn.Open();
            if (File.Exists(dest)) File.Delete(dest);
            using var cmd = cn.CreateCommand();
            cmd.CommandText = "VACUUM INTO $dest";
            cmd.Parameters.AddWithValue("$dest", dest);
            cmd.ExecuteNonQuery();
            created = true;
        }

        var pruned = PruneOld(cfg);
        _checkedDate = today;
        return (today, created, pruned);
    }

    public static int PruneOld(Config cfg, int retainDays = RetainDays)
    {
        if (!Directory.Exists(cfg.BackupFolder)) return 0;
        var cutoff = DateTime.UtcNow.AddHours(cfg.TzOffsetHours).AddDays(-retainDays)
                             .ToString("yyyyMMdd", CultureInfo.InvariantCulture);
        var removed = 0;
        foreach (var path in Directory.GetFiles(cfg.BackupFolder, $"{Prefix}*{Suffix}"))
        {
            var name = Path.GetFileName(path);
            var date = name[Prefix.Length..^Suffix.Length];
            if (date.Length != 8 || !date.All(char.IsAsciiDigit)) continue;
            if (string.CompareOrdinal(date, cutoff) >= 0) continue;
            try { File.Delete(path); removed++; } catch (IOException) { /* 占用中，下次再清 */ }
        }
        return removed;
    }

    /// <summary>最新备份日期（YYYY-MM-DD），无则空串。</summary>
    public static string LatestBackup(Config cfg)
    {
        if (!Directory.Exists(cfg.BackupFolder)) return "";
        var latest = "";
        foreach (var path in Directory.GetFiles(cfg.BackupFolder, $"{Prefix}*{Suffix}"))
        {
            var name = Path.GetFileName(path);
            var date = name[Prefix.Length..^Suffix.Length];
            if (date.Length == 8 && date.All(char.IsAsciiDigit) && string.CompareOrdinal(date, latest) > 0)
                latest = date;
        }
        return latest.Length == 8 ? $"{latest[..4]}-{latest.Substring(4, 2)}-{latest.Substring(6, 2)}" : "";
    }

    /// <summary>供测试重置进程内标记。</summary>
    internal static void ResetCheckedDate() => _checkedDate = null;
}

namespace POTMS;

/// <summary>应用配置 — 对应 Python 版 config.py / Rust 版 config.rs</summary>
public sealed class Config
{
    /// <summary>数据目录：data.db / uploads / exports / backup 均位于此。
    /// 优先级：环境变量 POTMS_BASE → 可执行文件所在目录 → 当前工作目录。</summary>
    public string BaseDir { get; }
    public string Database { get; }
    public string UploadFolder { get; }
    public string ExportFolder { get; }
    public string BackupFolder { get; }
    public byte[] SecretKey { get; }
    public int TzOffsetHours { get; }

    // ---- 与其它三版保持一致的常量 ----
    public const int PageSize = 12;              // 业务列表每页
    public const int PageSizeLogs = 10;          // 操作日志每页（含变更详情，取更小值）
    public const int CertExpiryWarnDays = 30;    // 证照到期预警
    public const long MaxContentLength = 20L * 1024 * 1024;
    public const int SessionTimeoutSeconds = 1800;
    public const int LockThreshold = 5;          // 登录失败锁定阈值
    public const int LockSeconds = 600;

    public Config(string? baseDir = null)
    {
        BaseDir = baseDir
                  ?? Environment.GetEnvironmentVariable("POTMS_BASE")
                  ?? AppContext.BaseDirectory;
        Directory.CreateDirectory(BaseDir);

        Database = Path.Combine(BaseDir, "data.db");
        UploadFolder = Path.Combine(BaseDir, "uploads");
        ExportFolder = Path.Combine(BaseDir, "exports");
        BackupFolder = Path.Combine(BaseDir, "backup");
        foreach (var d in new[] { UploadFolder, ExportFolder, BackupFolder })
            Directory.CreateDirectory(d);

        TzOffsetHours = int.TryParse(Environment.GetEnvironmentVariable("POTMS_TZ_OFFSET"), out var tz) ? tz : 8;
        SecretKey = LoadOrCreateSecret();
    }

    public string ConnectionString => $"Data Source={Database}";

    /// <summary>持久化密钥到数据目录，避免重启导致会话失效。</summary>
    private byte[] LoadOrCreateSecret()
    {
        var env = Environment.GetEnvironmentVariable("SECRET_KEY");
        if (!string.IsNullOrWhiteSpace(env))
            return System.Text.Encoding.UTF8.GetBytes(env);

        var file = Path.Combine(BaseDir, ".secret_key");
        try
        {
            if (File.Exists(file))
            {
                var existing = File.ReadAllText(file).Trim();
                if (existing.Length > 0) return System.Text.Encoding.UTF8.GetBytes(existing);
            }
            var val = Convert.ToHexString(System.Security.Cryptography.RandomNumberGenerator.GetBytes(32));
            File.WriteAllText(file, val);
            return System.Text.Encoding.UTF8.GetBytes(val);
        }
        catch (IOException)
        {
            // 无写权限时退化为随机（重启会话失效，但不影响功能）
            return System.Security.Cryptography.RandomNumberGenerator.GetBytes(32);
        }
    }
}

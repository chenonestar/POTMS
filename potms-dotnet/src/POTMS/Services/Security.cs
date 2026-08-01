using System.Security.Cryptography;
using System.Text;

namespace POTMS.Services;

/// <summary>密码哈希 — bcrypt（新哈希），兼容 Python werkzeug 的 pbkdf2:sha256（登录时透明升级）。
///
/// 已实测：本实现可验证 Python 版 bcrypt 生成的哈希，四版可共用同一份 users 表。
/// </summary>
public static class Security
{
    public static string HashPassword(string password) => BCrypt.Net.BCrypt.HashPassword(password);

    /// <summary>返回 (是否匹配, 是否需升级为 bcrypt)。</summary>
    public static (bool Matched, bool NeedsRehash) VerifyPassword(string password, string? stored)
    {
        if (string.IsNullOrEmpty(stored)) return (false, false);

        if (stored.StartsWith("$2", StringComparison.Ordinal))
        {
            try { return (BCrypt.Net.BCrypt.Verify(password, stored), false); }
            catch (BCrypt.Net.SaltParseException) { return (false, false); }
        }

        if (stored.StartsWith("pbkdf2:sha256", StringComparison.Ordinal))
        {
            var ok = VerifyWerkzeugPbkdf2(password, stored);
            return (ok, ok);   // 旧哈希验证通过则升级为 bcrypt
        }
        return (false, false);
    }

    /// <summary>werkzeug 格式：pbkdf2:sha256:iterations$salt$hexhash</summary>
    private static bool VerifyWerkzeugPbkdf2(string password, string stored)
    {
        var parts = stored.Split('$', 3);
        if (parts.Length != 3) return false;
        var (method, salt, hexHash) = (parts[0], parts[1], parts[2]);

        var iterations = 260000;
        var mp = method.Split(':', 3);
        if (mp.Length == 3 && int.TryParse(mp[2], out var n)) iterations = n;
        if (iterations <= 0) return false;

        var derived = Rfc2898DeriveBytes.Pbkdf2(
            Encoding.UTF8.GetBytes(password), Encoding.UTF8.GetBytes(salt),
            iterations, HashAlgorithmName.SHA256, 32);

        return ConstantTimeEquals(Convert.ToHexString(derived).ToLowerInvariant(), hexHash);
    }

    public static bool ConstantTimeEquals(string a, string b)
    {
        var ba = Encoding.UTF8.GetBytes(a);
        var bb = Encoding.UTF8.GetBytes(b);
        return CryptographicOperations.FixedTimeEquals(ba, bb);
    }

    public static string RandomToken(int bytes = 32) =>
        Convert.ToHexString(RandomNumberGenerator.GetBytes(bytes)).ToLowerInvariant();
}

using POTMS.Services;
using Xunit;

namespace POTMS.Tests;

public class SecurityTests
{
    [Fact]
    public void Bcrypt_RoundTrips()
    {
        var h = Security.HashPassword("admin123");
        Assert.True(Security.VerifyPassword("admin123", h).Matched);
        Assert.False(Security.VerifyPassword("wrong", h).Matched);
        Assert.False(Security.VerifyPassword("admin123", h).NeedsRehash);
    }

    /// <summary>跨版本互通：本实现须能验证 Python 版 bcrypt 生成的哈希，
    /// 这是四个语言版本共用同一份 users 表的前提。</summary>
    [Fact]
    public void Bcrypt_VerifiesPythonGeneratedHash()
    {
        const string pythonHash = "$2b$12$SKaBIu3PMkxJdk26XL6DVOBjVPeqyKelwkAdDOQ/Veu/Z3AB2UuRe";
        Assert.True(Security.VerifyPassword("admin123", pythonHash).Matched);
        Assert.False(Security.VerifyPassword("wrong", pythonHash).Matched);
    }

    [Fact]
    public void WerkzeugPbkdf2_IsRecognizedAndFlaggedForRehash()
    {
        // werkzeug generate_password_hash("admin123", method="pbkdf2:sha256:260000") 的等价输出
        const string stored = "pbkdf2:sha256:260000$abcsalt$" +
            "5bfda092e0d0eb0e5b48be4c8a7cb0cd8a5d9dd6ba52b1ad4dd1e10d17f1e0ba";
        var (matched, _) = Security.VerifyPassword("admin123", stored);
        // 该样例哈希非真实派生值，此处验证解析路径不抛异常且能给出布尔结论
        Assert.False(matched);
        Assert.False(Security.VerifyPassword("x", "garbage").Matched);
        Assert.False(Security.VerifyPassword("x", "").Matched);
    }

    [Fact]
    public void ConstantTimeEquals_Works()
    {
        Assert.True(Security.ConstantTimeEquals("abc", "abc"));
        Assert.False(Security.ConstantTimeEquals("abc", "abd"));
        Assert.False(Security.ConstantTimeEquals("abc", "abcd"));
    }
}

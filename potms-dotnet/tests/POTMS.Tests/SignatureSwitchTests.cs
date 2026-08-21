using Xunit;
using POTMS.Services;

namespace POTMS.Tests;

/// <summary>
/// 手写签名的强制开关（POTMS_REQUIRE_SIGNATURE，默认强制）。
///
/// <para>开关只影响「留空算不算错」这一件事。格式校验不受它影响——签了就必须是
/// 合法 PNG，不能因为「不强制」就把坏数据放进库里。这个区分很容易在重构时被
/// 抹平成一个 if，所以逐条钉住。</para>
///
/// <para>后端这一层是**唯一**真正的守门人：前端那两道拦截（提交前校验、少于 8 点
/// 算误触）都在浏览器里，伪造 POST 绕得过。</para>
/// </summary>
public class SignatureSwitchTests
{
    private static readonly byte[] Png =
        [0x89, (byte)'P', (byte)'N', (byte)'G', 0x0D, 0x0A, 0x1A, 0x0A, 0, 0, 0, 0x0D];

    [Theory]
    [InlineData("")]
    [InlineData(null)]
    [InlineData("   ")]
    public void Required_RejectsEmpty(string? input)
    {
        var (blob, err) = Signature.Decode(input, required: true);
        Assert.Equal("请手写签名后再提交。", err);
        Assert.Null(blob);
    }

    [Theory]
    [InlineData("")]
    [InlineData(null)]
    [InlineData("   ")]
    public void Relaxed_AcceptsEmpty(string? input)
    {
        var (blob, err) = Signature.Decode(input, required: false);
        Assert.Equal("", err);
        // 留空就是无签名，不能凭空造一张图
        Assert.Null(blob);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void FormatCheck_IgnoresSwitch(bool required)
    {
        Assert.Equal("签名数据格式不正确。",
            Signature.Decode("data:image/jpeg;base64,AAAA", required).Error);
        Assert.Equal("签名数据解析失败，请重新签名。",
            Signature.Decode("data:image/png;base64,!!!not-base64!!!", required).Error);
        Assert.Equal("签名数据不是有效的 PNG 图像。",
            Signature.Decode("data:image/png;base64,QUJDRA==", required).Error);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void ValidSignature_PassesEither(bool required)
    {
        var url = "data:image/png;base64," + Convert.ToBase64String(Png);
        var (blob, err) = Signature.Decode(url, required);
        Assert.Equal("", err);
        Assert.NotNull(blob);
    }

    [Fact]
    public void DefaultOverload_StaysStrict()
    {
        // 老调用点不传第二参，行为必须与强制模式一致
        Assert.Equal("请手写签名后再提交。", Signature.Decode("").Error);
    }

    [Theory]
    [InlineData(null, true)]
    [InlineData("1", true)]
    [InlineData("yes", true)]
    [InlineData("0", false)]
    [InlineData("false", false)]
    [InlineData("FALSE", false)]
    [InlineData("no", false)]
    [InlineData("off", false)]
    [InlineData(" off ", false)]
    public void Config_ParsesSwitch(string? env, bool expected)
    {
        var prev = Environment.GetEnvironmentVariable("POTMS_REQUIRE_SIGNATURE");
        var dir = Path.Combine(Path.GetTempPath(), "potms-cfg-" + Guid.NewGuid().ToString("N"));
        try
        {
            Environment.SetEnvironmentVariable("POTMS_REQUIRE_SIGNATURE", env);
            Assert.Equal(expected, new POTMS.Config(dir).RequireSignature);
        }
        finally
        {
            Environment.SetEnvironmentVariable("POTMS_REQUIRE_SIGNATURE", prev);
            try { Directory.Delete(dir, true); } catch (IOException) { }
        }
    }
}

/// <summary>中文错误页：404 不再是一片空白，500 不再是 ASP.NET 的英文默认页。</summary>
[Collection(AppCollection.Name)]
public class ErrorPageTests(EmptyDbAppFactory factory)
{
    [Fact]
    public async Task NotFound_RendersChinesePage()
    {
        var client = await factory.LoggedInClientAsync();
        var res = await client.GetAsync("/no/such/page");
        Assert.Equal(System.Net.HttpStatusCode.NotFound, res.StatusCode);

        var html = await res.Content.ReadAsStringAsync();
        Assert.Contains("您访问的页面不存在或已被移除", html);
        Assert.Contains("返回首页", html);
    }

    [Fact]
    public async Task ErrorPage_IsAnonymous()
    {
        // 未登录也要能看到错误页——否则 404 会被重定向到登录页，看不出哪里错了
        var client = factory.CreateClient(
            new Microsoft.AspNetCore.Mvc.Testing.WebApplicationFactoryClientOptions
            { AllowAutoRedirect = false });
        var res = await client.GetAsync("/Error/404");
        Assert.Equal(System.Net.HttpStatusCode.NotFound, res.StatusCode);
        Assert.Contains("您访问的页面不存在或已被移除", await res.Content.ReadAsStringAsync());
    }
}

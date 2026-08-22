using POTMS.Services;
using Xunit;

namespace POTMS.Tests;

public class SignatureTests
{
    // 真实的 1x1 PNG
    private static readonly byte[] Png = Convert.FromBase64String(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVQI12P4//8/AAX+Av6nNdKGAAAAAElFTkSuQmCC");
    private static string DataUrl => "data:image/png;base64," + Convert.ToBase64String(Png);

    [Fact]
    public void Decode_AcceptsValidPng()
    {
        var (blob, err) = Signature.Decode(DataUrl);
        Assert.Equal("", err);
        Assert.NotNull(blob);
        Assert.Equal(0x89, blob![0]);
    }

    [Theory]
    [InlineData("", "请手写签名")]
    [InlineData("notadataurl", "格式不正确")]
    [InlineData("data:image/png;base64,!!!bad!!!", "解析失败")]
    public void Decode_RejectsBadInput(string raw, string fragment)
    {
        var (blob, err) = Signature.Decode(raw);
        Assert.Null(blob);
        Assert.Contains(fragment, err);
    }

    [Fact]
    public void Decode_RejectsNonPngPayload()
    {
        var raw = "data:image/png;base64," + Convert.ToBase64String("plain text"u8.ToArray());
        var (blob, err) = Signature.Decode(raw);
        Assert.Null(blob);
        Assert.Contains("不是有效的 PNG", err);
    }

    [Fact]
    public void Decode_RejectsOversize()
    {
        // u8 字面量会把 \x89 编成 2 字节 UTF-8，此处须直接给出 PNG 魔数字节
        var big = new byte[Signature.MaxSignBytes + 1024];
        new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A }.CopyTo(big, 0);
        var (blob, err) = Signature.Decode("data:image/png;base64," + Convert.ToBase64String(big));
        Assert.Null(blob);
        Assert.Contains("过大", err);
    }

    [Fact]
    public void CleanMeta_ValidatesJson()
    {
        Assert.Equal("{\"a\":1}", Signature.CleanMeta("{\"a\":1}"));
        Assert.Null(Signature.CleanMeta(""));
        Assert.Null(Signature.CleanMeta("{not json"));
        Assert.Null(Signature.CleanMeta(new string('x', Signature.MaxMetaChars + 1)));
    }

    /// <summary>PNG 尺寸自 IHDR 解析 —— 替代图像库依赖的关键实现。</summary>
    [Fact]
    public void PngSize_ParsesIhdr()
    {
        Assert.Equal((1, 1), ExcelWriter.PngSize(Png));
        Assert.Throws<ArgumentException>(() => ExcelWriter.PngSize("not a png at all...."u8.ToArray()));
    }
}

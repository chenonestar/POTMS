namespace POTMS.Services;

/// <summary>手写签名数据解析与校验 —— 对应 Python 版 blueprints/issuance.py 的 _decode_signature。
///
/// 签名以 PNG 位图 + 笔迹矢量双存于数据库（BLOB/TEXT），随每日备份一起落盘；
/// 不落文件系统（uploads 目录不在备份范围内，签名凭证丢失无法补签）。
/// </summary>
public static class Signature
{
    private static readonly byte[] PngMagic = [0x89, (byte)'P', (byte)'N', (byte)'G', 0x0D, 0x0A, 0x1A, 0x0A];
    private const string Prefix = "data:image/png;base64,";
    public const int MaxSignBytes = 512 * 1024;
    public const int MaxMetaChars = 400_000;

    /// <summary>dataURL → PNG 字节。失败时返回 (null, 错误信息)。</summary>
    public static (byte[]? Blob, string Error) Decode(string? pngDataUrl)
    {
        var raw = (pngDataUrl ?? "").Trim();
        if (raw.Length == 0) return (null, "请手写签名后再提交。");
        if (!raw.StartsWith(Prefix, StringComparison.Ordinal)) return (null, "签名数据格式不正确。");

        byte[] blob;
        try { blob = Convert.FromBase64String(raw[Prefix.Length..]); }
        catch (FormatException) { return (null, "签名数据解析失败，请重新签名。"); }

        if (blob.Length < PngMagic.Length || !blob.Take(PngMagic.Length).SequenceEqual(PngMagic))
            return (null, "签名数据不是有效的 PNG 图像。");
        if (blob.Length > MaxSignBytes) return (null, "签名图像过大，请重新签名。");
        return (blob, "");
    }

    /// <summary>校验笔迹矢量 JSON；过大或非法则丢弃（不阻断业务，位图仍在）。</summary>
    public static string? CleanMeta(string? raw)
    {
        raw = (raw ?? "").Trim();
        if (raw.Length == 0 || raw.Length > MaxMetaChars) return null;
        try { using var _ = System.Text.Json.JsonDocument.Parse(raw); return raw; }
        catch (System.Text.Json.JsonException) { return null; }
    }
}

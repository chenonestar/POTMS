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

    /// <summary>dataURL → PNG 字节。失败时返回 (null, 错误信息)。
    ///
    /// <para>留空是否算错，取决于 <paramref name="required"/>（来自 POTMS_REQUIRE_SIGNATURE，
    /// 默认强制）。注意这里是**唯一**真正的守门人：前端那两道拦截（提交前校验、
    /// 少于 8 点算误触）都在浏览器里，伪造 POST 绕得过。</para>
    ///
    /// <para>格式校验不受开关影响——签了就必须是合法 PNG，不能因为「不强制」就把
    /// 坏数据放进库里。</para>
    /// </summary>
    public static (byte[]? Blob, string Error) Decode(string? pngDataUrl, bool required = true)
    {
        var raw = (pngDataUrl ?? "").Trim();
        // 放宽模式：留空即无签名，记录里如实存 NULL
        if (raw.Length == 0) return (null, required ? "请手写签名后再提交。" : "");
        if (!raw.StartsWith(Prefix, StringComparison.Ordinal)) return (null, "签名数据格式不正确。");

        var payload = raw[Prefix.Length..];
        // 先按 base64 长度粗判体积再解码，避免为超大载荷先分配一遍内存
        if ((long)payload.Length * 3 / 4 > MaxSignBytes) return (null, "签名图像过大，请重新签名。");

        byte[] blob;
        try { blob = Convert.FromBase64String(payload); }
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

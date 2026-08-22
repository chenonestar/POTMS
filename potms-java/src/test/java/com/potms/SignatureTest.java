package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.potms.service.Signature;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** 手写签名的解析与校验。 */
class SignatureTest {

    private static final byte[] PNG = {
        (byte) 0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n', 0, 0, 0, 13,
    };

    @Test
    @DisplayName("合法 dataURL 解出 PNG 字节")
    void decodesValidPng() {
        var d = Signature.decode(Signature.toDataUrl(PNG));
        assertTrue(d.ok());
        assertEquals(PNG.length, d.bytes().length);
        assertEquals("", d.error());
    }

    @Test
    @DisplayName("空 / 前缀错 / base64 坏 / 非 PNG 各自给出提示")
    void rejectsBadInput() {
        assertEquals("请手写签名后再提交。", Signature.decode("").error());
        assertEquals("请手写签名后再提交。", Signature.decode(null).error());
        assertEquals("签名数据格式不正确。", Signature.decode("data:image/jpeg;base64,AAAA").error());
        assertEquals("签名数据解析失败，请重新签名。",
                Signature.decode("data:image/png;base64,!!!not-base64!!!").error());
        assertEquals("签名数据不是有效的 PNG 图像。",
                Signature.decode("data:image/png;base64,"
                        + Base64.getEncoder().encodeToString("hello".getBytes(StandardCharsets.UTF_8)))
                        .error());
    }

    /** 尺寸守卫必须在 base64 解码之前，否则超大输入会先把内存吃掉再报错。 */
    @Test
    @DisplayName("超大签名在解码前就被拦下")
    void rejectsOversizeBeforeDecoding() {
        String huge = "A".repeat(Signature.MAX_SIGN_BYTES * 2);
        var d = Signature.decode("data:image/png;base64," + huge);
        assertFalse(d.ok());
        assertEquals("签名图像过大，请重新签名。", d.error());
    }

    @Test
    @DisplayName("笔迹矢量：合法 JSON 保留，非法或超长丢弃（不阻断业务）")
    void cleansMeta() {
        assertEquals("{\"a\":1}", Signature.cleanMeta("{\"a\":1}"));
        assertEquals("[]", Signature.cleanMeta("  []  "));
        assertNull(Signature.cleanMeta(""));
        assertNull(Signature.cleanMeta(null));
        assertNull(Signature.cleanMeta("{not json"));
        assertNull(Signature.cleanMeta("[" + "1,".repeat(Signature.MAX_META_CHARS) + "1]"));
    }
}

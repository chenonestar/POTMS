package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.potms.service.Signature;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 手写签名的强制开关（POTMS_REQUIRE_SIGNATURE，默认强制）。
 *
 * <p>开关只影响「留空算不算错」这一件事。格式校验不受它影响——签了就必须是
 * 合法 PNG，不能因为「不强制」就把坏数据放进库里。这个区分很容易在重构时被
 * 抹平成一个 if，所以逐条钉住。
 *
 * <p>后端这一层是**唯一**真正的守门人：前端那两道拦截（提交前校验、少于 8 点
 * 算误触）都在浏览器里，伪造 POST 绕得过。
 */
class SignatureSwitchTest {

    private static final byte[] PNG = {(byte) 0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A,
        0x00, 0x00, 0x00, 0x0D};

    @Test
    @DisplayName("强制模式下留空报错")
    void requiredRejectsEmpty() {
        assertEquals("请手写签名后再提交。", Signature.decode("", true).error());
        assertEquals("请手写签名后再提交。", Signature.decode(null, true).error());
        assertEquals("请手写签名后再提交。", Signature.decode("   ", true).error());
    }

    @Test
    @DisplayName("放宽模式下留空放行，且如实返回「无签名」")
    void relaxedAcceptsEmpty() {
        var d = Signature.decode("", false);
        assertEquals("", d.error(), "放宽模式不该报错");
        assertNull(d.bytes(), "留空就是无签名，不能凭空造一张图");
        assertFalse(d.ok());

        assertEquals("", Signature.decode(null, false).error());
        assertEquals("", Signature.decode("   ", false).error());
    }

    @Test
    @DisplayName("格式校验不受开关影响：签了就必须是合法 PNG")
    void formatCheckIgnoresSwitch() {
        for (boolean required : new boolean[] {true, false}) {
            assertEquals("签名数据格式不正确。",
                    Signature.decode("data:image/jpeg;base64,AAAA", required).error(),
                    "required=" + required);
            assertEquals("签名数据解析失败，请重新签名。",
                    Signature.decode("data:image/png;base64,!!!not-base64!!!", required).error(),
                    "required=" + required);
            assertEquals("签名数据不是有效的 PNG 图像。",
                    Signature.decode("data:image/png;base64,QUJDRA==", required).error(),
                    "required=" + required);
        }
    }

    @Test
    @DisplayName("合法签名两种模式下都通过")
    void validSignaturePassesEither() {
        String url = Signature.toDataUrl(PNG);
        for (boolean required : new boolean[] {true, false}) {
            var d = Signature.decode(url, required);
            assertTrue(d.ok(), "required=" + required + " 时合法签名被拒：" + d.error());
            assertNotNull(d.bytes());
        }
    }

    @Test
    @DisplayName("单参重载等价于强制模式（老调用点行为不变）")
    void singleArgOverloadStaysStrict() {
        assertEquals(Signature.decode("", true).error(), Signature.decode("").error());
    }
}

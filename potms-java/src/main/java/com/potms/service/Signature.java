package com.potms.service;

import java.util.Base64;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

/**
 * 手写签名的解析与校验 — 对应 Python 版 blueprints/issuance.py 的
 * {@code _decode_signature} / {@code _clean_meta}。
 *
 * <p>签名以 PNG 位图 + 笔迹矢量双存于数据库（BLOB/TEXT），随每日备份一起落盘；
 * 刻意不落文件系统——uploads 目录不在备份范围内，签名是凭证不能丢。
 */
public final class Signature {

    private Signature() {}

    private static final ObjectMapper JSON = new ObjectMapper();
    private static final String PREFIX = "data:image/png;base64,";

    /** PNG 魔数，防止前端传入非图片内容。 */
    private static final byte[] PNG_MAGIC = {
        (byte) 0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n',
    };

    /** 单张签名上限：正常裁剪后 5–20KB，留足余量仍能拦住异常大图。 */
    public static final int MAX_SIGN_BYTES = 512 * 1024;
    public static final int MAX_META_CHARS = 400_000;

    /** 解析结果：成功时 bytes 非空、error 为空串；失败时反之。 */
    public record Decoded(byte[] bytes, String error) {
        public boolean ok() {
            return bytes != null;
        }
    }

    /** dataURL → PNG 字节，强制签名（等价 {@code decode(dataUrl, true)}）。 */
    public static Decoded decode(String dataUrl) {
        return decode(dataUrl, true);
    }

    /**
     * dataURL → PNG 字节。
     *
     * <p>留空是否算错，取决于 {@code required}（来自 POTMS_REQUIRE_SIGNATURE，
     * 默认强制）。注意这里是**唯一**真正的守门人：前端那两道拦截（提交前校验、
     * 少于 8 点算误触）都在浏览器里，伪造 POST 绕得过。
     *
     * <p>格式校验不受开关影响——签了就必须是合法 PNG，不能因为「不强制」就把
     * 坏数据放进库里。
     */
    public static Decoded decode(String dataUrl, boolean required) {
        String raw = dataUrl == null ? "" : dataUrl.trim();
        if (raw.isEmpty()) {
            // 放宽模式：留空即无签名，记录里如实存 NULL
            return new Decoded(null, required ? "请手写签名后再提交。" : "");
        }
        if (!raw.startsWith(PREFIX)) {
            return new Decoded(null, "签名数据格式不正确。");
        }
        String b64 = raw.substring(PREFIX.length());
        // 先按 base64 长度估算解码后大小再真解码，避免超大输入把内存打满
        if ((long) b64.length() / 4 * 3 > MAX_SIGN_BYTES) {
            return new Decoded(null, "签名图像过大，请重新签名。");
        }
        byte[] blob;
        try {
            blob = Base64.getDecoder().decode(b64);
        } catch (IllegalArgumentException e) {
            return new Decoded(null, "签名数据解析失败，请重新签名。");
        }
        if (!startsWithMagic(blob)) {
            return new Decoded(null, "签名数据不是有效的 PNG 图像。");
        }
        if (blob.length > MAX_SIGN_BYTES) {
            return new Decoded(null, "签名图像过大，请重新签名。");
        }
        return new Decoded(blob, "");
    }

    /** 校验笔迹矢量 JSON；过大或非法则丢弃（不阻断业务，位图仍在）。 */
    public static String cleanMeta(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.isEmpty() || s.length() > MAX_META_CHARS) {
            return null;
        }
        try {
            JSON.readTree(s);
        } catch (JacksonException e) {
            return null;
        }
        return s;
    }

    private static boolean startsWithMagic(byte[] blob) {
        if (blob.length < PNG_MAGIC.length) {
            return false;
        }
        for (int i = 0; i < PNG_MAGIC.length; i++) {
            if (blob[i] != PNG_MAGIC[i]) {
                return false;
            }
        }
        return true;
    }

    /** 供测试构造 dataURL。 */
    public static String toDataUrl(byte[] png) {
        return PREFIX + Base64.getEncoder().encodeToString(png);
    }

    /** 供日志/详情展示：字节数转 KB 文案。 */
    public static String sizeLabel(byte[] blob) {
        if (blob == null) {
            return "-";
        }
        return Math.max(1, Math.round(blob.length / 1024.0))
                + " KB（" + blob.length + " 字节）";
    }
}

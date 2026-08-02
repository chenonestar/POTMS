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

    /** dataURL → PNG 字节。 */
    public static Decoded decode(String dataUrl) {
        String raw = dataUrl == null ? "" : dataUrl.trim();
        if (raw.isEmpty()) {
            return new Decoded(null, "请手写签名后再提交。");
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

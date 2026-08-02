package com.potms.web;

import java.util.List;
import java.util.Map;

/**
 * 模板取值与展示格式化。
 *
 * <p>JTE 是类型安全的，没有 Jinja 那种对 dict/Row 的宽松下标取值，
 * 列表页的行普遍是 {@code Map<String,Object>}，故集中提供空安全的取值助手，
 * 避免每个模板里写一长串三元判空。
 */
public final class Fmt {

    private Fmt() {}

    /** 取字符串，null 与缺键都返回空串。 */
    public static String s(Map<String, Object> row, String key) {
        Object v = row == null ? null : row.get(key);
        return v == null ? "" : v.toString();
    }

    /** 取字符串，空值时返回占位符。 */
    public static String s(Map<String, Object> row, String key, String dflt) {
        String v = s(row, key);
        return v.isEmpty() ? dflt : v;
    }

    public static long n(Map<String, Object> row, String key) {
        Object v = row == null ? null : row.get(key);
        return v instanceof Number num ? num.longValue() : 0L;
    }

    public static boolean eq(Map<String, Object> row, String key, String expected) {
        return expected.equals(s(row, key));
    }

    /** 身份证脱敏：保留前 3 位与后 4 位。 */
    public static String maskId(String id) {
        if (id == null || id.length() < 7) {
            return id == null ? "" : id;
        }
        return id.substring(0, 3) + "***********" + id.substring(id.length() - 4);
    }

    public static String maskId(Map<String, Object> row, String key) {
        return maskId(s(row, key));
    }

    /** YYYYMMDD → YYYY-MM-DD；非 8 位原样返回。 */
    public static String date(String ymd) {
        if (ymd == null || ymd.length() != 8) {
            return ymd == null ? "" : ymd;
        }
        return ymd.substring(0, 4) + "-" + ymd.substring(4, 6) + "-" + ymd.substring(6, 8);
    }

    public static String date(Map<String, Object> row, String key) {
        return date(s(row, key));
    }

    /** UTC 时间戳字符串 → 按偏移换算后的本地展示串；非时间戳原样返回。 */
    public static String localTime(Object value, int tzOffset, String pattern) {
        if (value == null) {
            return "";
        }
        String s = value.toString();
        if (s.isEmpty()) {
            return "";
        }
        try {
            var utc = java.time.LocalDateTime.parse(
                    s.replace('T', ' ').substring(0, Math.min(19, s.length())),
                    java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
            return utc.plusHours(tzOffset)
                    .format(java.time.format.DateTimeFormatter.ofPattern(pattern));
        } catch (RuntimeException e) {
            return s;
        }
    }

    /** 备案状态展示名。 */
    public static String statusLabel(String status) {
        return "active".equals(status) ? "有效" : "已撤控";
    }

    /** 在字典选项里按 code 找显示值；找不到时回退 code 本身。 */
    public static String dict(List<Helpers.DictOption> opts, String code) {
        if (code == null || code.isEmpty()) {
            return "";
        }
        for (Helpers.DictOption o : opts) {
            if (o.code().equals(code)) {
                return o.value();
            }
        }
        return code;
    }

    /** 表单回填：从 data 映射取值，缺键返回空串。 */
    public static String v(Map<String, String> data, String key) {
        String s = data == null ? null : data.get(key);
        return s == null ? "" : s;
    }

    /** 表单回填：带默认值。 */
    public static String v(Map<String, String> data, String key, String dflt) {
        String s = v(data, key);
        return s.isEmpty() ? dflt : s;
    }

    /**
     * 布尔属性判定，配合 JTE 的 {@code selected="${...}"} 写法使用。
     *
     * <p>JTE 禁止在「属性名位置」出现表达式（防 XSS），所以不能照搬 Jinja 的
     * {@code {{ 'selected' if ... }}}；改为把布尔值给到属性值，JTE 在为 false 时
     * 会整个省略该属性。
     */
    public static boolean is(String actual, String expected) {
        return expected.equals(actual);
    }
}

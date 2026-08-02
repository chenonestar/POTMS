package com.potms.util;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 「计划出行日期」的解析与规范化 — 对应 Python 版 utils/validators.py 的
 * parse_travel_range / format_travel_range。
 *
 * <p>迁移逻辑依赖这两个函数，故单独成类，供 Db 与 Validators 共用。
 */
public final class TravelDates {

    private TravelDates() {}

    /** 匹配 YYYY-M-D / YYYY/M/D / YYYYMMDD 三种历史写法。 */
    private static final Pattern DATE = Pattern.compile("(\\d{4})[-/.]?(\\d{1,2})[-/.]?(\\d{1,2})");

    /** 起止日期，均为 YYYYMMDD；无法解析时两者皆为空串。 */
    public record Range(String start, String end) {
        public boolean isEmpty() {
            return start.isEmpty() || end.isEmpty();
        }
    }

    /** 从文本中解析出起止日期（取第一个与最后一个匹配），规范化为 YYYYMMDD。 */
    public static Range parse(String text) {
        if (text == null || text.isEmpty()) {
            return new Range("", "");
        }
        List<String> found = new ArrayList<>();
        Matcher m = DATE.matcher(text);
        while (m.find()) {
            found.add(m.group(1) + pad(m.group(2)) + pad(m.group(3)));
        }
        if (found.isEmpty()) {
            return new Range("", "");
        }
        return new Range(found.get(0), found.get(found.size() - 1));
    }

    /** 组装为统一存储格式 YYYY/MM/DD-YYYY/MM/DD；起止相同或仅有单个日期时返回单个。 */
    public static String format(String start, String end) {
        String fs = slash(start);
        String fe = slash(end);
        if (!fs.isEmpty() && !fe.isEmpty() && !fs.equals(fe)) {
            return fs + "-" + fe;
        }
        return !fs.isEmpty() ? fs : fe;
    }

    private static String pad(String s) {
        return s.length() == 1 ? "0" + s : s;
    }

    private static String slash(String s) {
        if (s == null || s.length() != 8) {
            return "";
        }
        return s.substring(0, 4) + "/" + s.substring(4, 6) + "/" + s.substring(6, 8);
    }
}

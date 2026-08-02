package com.potms.web;

import java.util.ArrayList;
import java.util.List;

/**
 * 列表页查询条件拼装器 — 只追加参数化片段，杜绝字符串拼值。
 *
 * <p>对应 .NET 版的 Filter：各列表页的筛选逻辑高度雷同，抽出来避免
 * 每页手写一遍 WHERE 拼接时漏掉参数占位。
 */
public final class Filter {

    private final StringBuilder where = new StringBuilder();
    private final List<Object> params = new ArrayList<>();

    /** 追加一个条件片段，{@code ?} 的个数须与 values 数量一致。 */
    public Filter and(String fragment, Object... values) {
        where.append(" AND ").append(fragment);
        java.util.Collections.addAll(params, values);
        return this;
    }

    /** 值非空时才追加等值条件。 */
    public Filter eq(String column, String value) {
        if (value != null && !value.isBlank()) {
            and(column + " = ?", value.trim());
        }
        return this;
    }

    /**
     * 模糊匹配：keyword 非空时把 {@code %kw%} 重复填入 fragment 的每个 {@code ?}。
     *
     * @param fragment 形如 {@code (name LIKE ? OR unit LIKE ?)}
     * @param slots    fragment 中占位符个数
     */
    public Filter like(String fragment, String keyword, int slots) {
        if (keyword == null || keyword.isBlank()) {
            return this;
        }
        String kw = "%" + keyword.trim() + "%";
        Object[] vals = new Object[slots];
        java.util.Arrays.fill(vals, kw);
        return and(fragment, vals);
    }

    /** 日期区间下界（含）。 */
    public Filter from(String column, String value) {
        if (value != null && !value.isBlank()) {
            and(column + " >= ?", value.trim());
        }
        return this;
    }

    /** 日期区间上界（含）。 */
    public Filter to(String column, String value) {
        if (value != null && !value.isBlank()) {
            and(column + " <= ?", value.trim());
        }
        return this;
    }

    /** 追加在 {@code WHERE 1=1} 之后的片段（可能为空串）。 */
    public String where() {
        return where.toString();
    }

    public Object[] params() {
        return params.toArray();
    }

    /** 解析逗号分隔的 id 串（批量打印 / 批量导出用），忽略非法项。 */
    public static List<Long> parseIds(String raw) {
        List<Long> out = new ArrayList<>();
        if (raw == null || raw.isBlank()) {
            return out;
        }
        for (String part : raw.split(",")) {
            String t = part.trim();
            if (t.isEmpty()) {
                continue;
            }
            try {
                out.add(Long.parseLong(t));
            } catch (NumberFormatException ignored) {
                // 前端传来的脏数据直接丢弃，不因此报错
            }
        }
        return out;
    }
}

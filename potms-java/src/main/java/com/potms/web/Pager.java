package com.potms.web;

import java.util.ArrayList;
import java.util.List;

/**
 * 分页链接拼装 —— 保留当前筛选条件，只替换 page 参数。
 *
 * <p>Python 版靠 {@code request.args.to_dict()} + {@code **qargs} 做这件事，
 * Rust 版为此专门加了 {@code page_url()} 全局函数（原实现照搬 Flask 写法导致
 * 有数据时模板渲染 500）。Java 这里同样显式实现，不依赖模板引擎的动态能力。
 */
public final class Pager {

    private Pager() {}

    /** 去掉查询串里已有的 page，避免与新的 page= 冲突。 */
    public static String stripPage(String query) {
        if (query == null || query.isEmpty()) {
            return "";
        }
        List<String> kept = new ArrayList<>();
        for (String pair : query.split("&")) {
            if (pair.isEmpty() || pair.equals("page") || pair.startsWith("page=")) {
                continue;
            }
            kept.add(pair);
        }
        return String.join("&", kept);
    }

    /** 拼出 {@code basePath?其它筛选&page=N}。 */
    public static String url(String basePath, String strippedQuery, int page) {
        StringBuilder sb = new StringBuilder(basePath).append('?');
        if (strippedQuery != null && !strippedQuery.isEmpty()) {
            sb.append(strippedQuery).append('&');
        }
        return sb.append("page=").append(page).toString();
    }
}

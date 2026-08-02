package com.potms.web;

import jakarta.servlet.http.HttpServletRequest;
import java.util.List;

/**
 * 每个页面共享的渲染上下文 — 对应 Flask 模板里可直接取到的
 * {@code session} / {@code request} / {@code csrf_token()} / flash 消息。
 *
 * <p>JTE 是编译期类型安全的，没有 Flask 那种隐式全局变量，故显式建模。
 * 控制器统一用 {@link #of} 构造，避免每页手工组装漏项。
 *
 * @param user      当前登录用户名；未登录为 null
 * @param csrfToken 当前会话的 CSRF 令牌
 * @param flashes   本次请求要展示的闪现消息（取出即清空）
 * @param path      当前请求路径，供侧边栏高亮
 * @param query     原始查询串，供分页拼接
 */
public record Ctx(String user, String csrfToken, List<Flash.Message> flashes,
                  String path, String query) {

    public static Ctx of(HttpServletRequest req) {
        return new Ctx(
                SecurityFilters.currentUser(req),
                Csrf.token(req),
                Flash.pop(req),
                req.getRequestURI(),
                req.getQueryString() == null ? "" : req.getQueryString());
    }

    public boolean loggedIn() {
        return user != null;
    }

    /** 侧边栏高亮：当前路径是否落在某个模块下。 */
    public boolean active(String prefix) {
        return "/".equals(prefix) ? "/".equals(path) : path.startsWith(prefix);
    }
}

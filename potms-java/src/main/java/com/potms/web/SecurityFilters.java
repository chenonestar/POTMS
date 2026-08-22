package com.potms.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpSession;
import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 会话认证与 CSRF —— 用朴素的 Servlet 过滤器实现，不引入 Spring Security。
 *
 * <p>理由：其它四版都是同一套「session cookie + 手写 CSRF + 每 IP 锁定」的模型，
 * 引入 Spring Security 会带来另一套语义（认证入口、登出、CSRF 存储方式都不同），
 * 反而让五版行为难以对齐。这里只要求与前四版逐条一致。
 */
@Configuration
public class SecurityFilters {

    public static final String SESSION_USER = "_user";
    /** 登录者的真实姓名，登录时从 users.full_name 读入，供业务单据显示经办人。 */
    public static final String SESSION_FULL_NAME = "_full_name";

    /** 免登录路径：登录页本身、静态资源、错误页。 */
    private static final Set<String> ANONYMOUS_PREFIXES = Set.of(
            "/login", "/static/", "/favicon.ico", "/error");

    private static boolean isAnonymous(String path) {
        for (String p : ANONYMOUS_PREFIXES) {
            if (path.equals(p) || path.startsWith(p)) {
                return true;
            }
        }
        return false;
    }

    /**
     * 当前登录**账号**；未登录返回 null。
     *
     * <p>操作日志记的就是它——账号是身份标识，姓名可以随时改；日志只记「张三」
     * 的话，改名之后历史记录就对不上人了。
     */
    public static String currentUser(HttpServletRequest req) {
        HttpSession s = req.getSession(false);
        return s == null ? null : (String) s.getAttribute(SESSION_USER);
    }

    /**
     * 业务单据上的**经办人**：真实姓名，没填则回退到登录账号。
     *
     * <p>单据、打印件、导出表上的「经办人」必须是真人名字——打印出来的领用凭证上
     * 一个 admin，没法拿去归档。姓名在「账户设置」里维护，登录时放进会话。
     */
    public static String operatorName(HttpServletRequest req) {
        HttpSession s = req.getSession(false);
        String n = s == null ? null : (String) s.getAttribute(SESSION_FULL_NAME);
        return n == null || n.isBlank() ? currentUser(req) : n;
    }

    public static String clientIp(HttpServletRequest req) {
        String ip = req.getRemoteAddr();
        return ip == null ? "-" : ip;
    }

    @Bean
    FilterRegistrationBean<AuthFilter> authFilter() {
        var bean = new FilterRegistrationBean<>(new AuthFilter());
        bean.addUrlPatterns("/*");
        bean.setOrder(1);
        return bean;
    }

    @Bean
    FilterRegistrationBean<CsrfFilter> csrfFilter() {
        var bean = new FilterRegistrationBean<>(new CsrfFilter());
        bean.addUrlPatterns("/*");
        bean.setOrder(2);
        return bean;
    }

    /** 默认全站需登录；未登录跳转登录页并带上原始去向。 */
    public static class AuthFilter extends OncePerRequestFilter {
        @Override
        protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res,
                                        FilterChain chain) throws ServletException, IOException {
            String path = req.getRequestURI();
            if (isAnonymous(path) || currentUser(req) != null) {
                chain.doFilter(req, res);
                return;
            }
            String target = path + (req.getQueryString() == null ? "" : "?" + req.getQueryString());
            res.sendRedirect("/login?ReturnUrl="
                    + URLEncoder.encode(target, StandardCharsets.UTF_8));
        }
    }

    /** 非安全方法一律校验 CSRF 令牌。 */
    public static class CsrfFilter extends OncePerRequestFilter {
        private static final Set<String> SAFE = Set.of("GET", "HEAD", "OPTIONS", "TRACE");

        @Override
        protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res,
                                        FilterChain chain) throws ServletException, IOException {
            if (SAFE.contains(req.getMethod()) || Csrf.valid(req)) {
                chain.doFilter(req, res);
                return;
            }
            res.sendError(HttpServletResponse.SC_BAD_REQUEST, "CSRF 校验失败，请刷新页面后重试。");
        }
    }
}

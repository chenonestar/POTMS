package com.potms.web;

import com.potms.service.Security;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSession;
import java.security.SecureRandom;
import java.util.HexFormat;

/**
 * CSRF 令牌 — 表单域名 {@code csrf_token}、请求头 {@code X-CSRFToken}，
 * 与其它四版命名一致，前端脚本可直接复用。
 */
public final class Csrf {

    private Csrf() {}

    public static final String FIELD = "csrf_token";
    public static final String HEADER = "X-CSRFToken";
    private static final String SESSION_KEY = "_csrf_token";
    private static final SecureRandom RANDOM = new SecureRandom();

    /** 取当前会话的令牌，没有则生成并存入。 */
    public static String token(HttpServletRequest req) {
        HttpSession s = req.getSession(true);
        Object existing = s.getAttribute(SESSION_KEY);
        if (existing instanceof String str && !str.isEmpty()) {
            return str;
        }
        byte[] raw = new byte[32];
        RANDOM.nextBytes(raw);
        String token = HexFormat.of().formatHex(raw);
        s.setAttribute(SESSION_KEY, token);
        return token;
    }

    /** 校验请求携带的令牌是否与会话中的一致。 */
    public static boolean valid(HttpServletRequest req) {
        HttpSession s = req.getSession(false);
        if (s == null) {
            return false;
        }
        Object expected = s.getAttribute(SESSION_KEY);
        if (!(expected instanceof String exp) || exp.isEmpty()) {
            return false;
        }
        String got = req.getHeader(HEADER);
        if (got == null || got.isEmpty()) {
            got = req.getParameter(FIELD);
        }
        return got != null && Security.constantTimeEquals(exp, got);
    }
}

package com.potms.web;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSession;
import java.util.ArrayList;
import java.util.List;

/**
 * 闪现消息 — 对应 Flask 的 flash() / get_flashed_messages()。
 *
 * <p>存在 session 里跨重定向传递，取出即清空。类别沿用 Bootstrap 的
 * success / danger / warning / info，与其它四版一致。
 */
public final class Flash {

    private Flash() {}

    private static final String KEY = "_flashes";

    /** 一条闪现消息。 */
    public record Message(String category, String text) {}

    public static void add(HttpServletRequest req, String category, String text) {
        HttpSession s = req.getSession(true);
        @SuppressWarnings("unchecked")
        List<Message> list = (List<Message>) s.getAttribute(KEY);
        if (list == null) {
            list = new ArrayList<>();
        }
        list.add(new Message(category, text));
        s.setAttribute(KEY, list);
    }

    public static void success(HttpServletRequest req, String text) {
        add(req, "success", text);
    }

    public static void danger(HttpServletRequest req, String text) {
        add(req, "danger", text);
    }

    public static void warning(HttpServletRequest req, String text) {
        add(req, "warning", text);
    }

    public static void info(HttpServletRequest req, String text) {
        add(req, "info", text);
    }

    /** 取出并清空（供布局渲染）。 */
    public static List<Message> pop(HttpServletRequest req) {
        HttpSession s = req.getSession(false);
        if (s == null) {
            return List.of();
        }
        @SuppressWarnings("unchecked")
        List<Message> list = (List<Message>) s.getAttribute(KEY);
        if (list == null) {
            return List.of();
        }
        s.removeAttribute(KEY);
        return list;
    }
}

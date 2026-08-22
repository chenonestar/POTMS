package com.potms.web;

import jakarta.servlet.RequestDispatcher;
import jakarta.servlet.http.HttpServletRequest;
// Boot 4 把 ErrorController 从 org.springframework.boot.web.servlet.error
// 挪到了 org.springframework.boot.webmvc.error
import org.springframework.boot.webmvc.error.ErrorController;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.RequestMapping;

/**
 * 中文错误页。对应 Python 版 templates/errors/404.html 与 500.html。
 *
 * <p>此前 Java 版没有这一层，404 / 500 落到 Spring Boot 自带的 Whitelabel Error Page
 * ——满屏英文，与另外三版对不上。这里接管 Boot 的 {@code /error} 转发点。
 *
 * <p>这一页刻意不依赖数据库、会话与 layout：错误页最需要的就是在别的东西都坏掉时
 * 仍能渲染出来。
 */
@Controller
public class ErrorPageController implements ErrorController {

    @RequestMapping("/error")
    public String error(HttpServletRequest req, Model model) {
        Object raw = req.getAttribute(RequestDispatcher.ERROR_STATUS_CODE);
        int code = raw instanceof Integer i && i >= 400 && i < 600 ? i : 500;

        String title;
        String message;
        String hint = "";
        String icon;
        String color;
        switch (code) {
            case 404 -> {
                title = "页面不存在";
                message = "您访问的页面不存在或已被移除。";
                icon = "bi-compass text-secondary";
                color = "#1a5276";
            }
            case 403 -> {
                title = "没有权限";
                message = "本次请求被拒绝。";
                hint = "若是表单提交失败，多半是页面停留过久令牌过期，请返回重新打开页面再试。";
                icon = "bi-shield-exclamation text-warning";
                color = "#b9770e";
            }
            default -> {
                title = "系统内部错误";
                message = "系统内部发生错误，本次操作未完成。";
                hint = "已有数据不受影响。请返回重试；若反复出现，请联系系统维护人员并说明操作步骤。";
                icon = "bi-exclamation-octagon text-danger";
                color = "#c0392b";
            }
        }

        model.addAttribute("code", code);
        model.addAttribute("title", title);
        model.addAttribute("message", message);
        model.addAttribute("hint", hint);
        model.addAttribute("icon", icon);
        model.addAttribute("color", color);
        return "errors/page";
    }
}

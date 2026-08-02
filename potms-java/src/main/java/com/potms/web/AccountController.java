package com.potms.web;

import static com.potms.web.PersonnelController.operator;
import static com.potms.web.PersonnelController.trim;

import com.potms.data.Db;
import com.potms.service.Security;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;

/** 账户设置：修改用户名 / 密码。对应 Python 版 auth.account。 */
@Controller
public class AccountController {

    private final Db db;

    public AccountController(Db db) {
        this.db = db;
    }

    @GetMapping("/account")
    public String account(HttpServletRequest req, Model model) {
        var user = currentUser(req);
        if (user == null) {
            return "redirect:/login";
        }
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("username", user.get("username"));
        return "account";
    }

    @PostMapping("/account")
    public String update(HttpServletRequest req, Model model) {
        var user = currentUser(req);
        if (user == null) {
            return "redirect:/login";
        }
        String currentUsername = String.valueOf(user.get("username"));
        String currentPw = req.getParameter("current_password");
        String newUsername = trim(req, "new_username");
        String newPw = req.getParameter("new_password");
        String confirmPw = req.getParameter("confirm_password");

        List<String> errors = new ArrayList<>();
        if (!Security.verifyPassword(currentPw == null ? "" : currentPw,
                String.valueOf(user.get("password_hash"))).matched()) {
            errors.add("当前密码不正确。");
        }

        boolean changeUsername = !newUsername.isEmpty() && !newUsername.equals(currentUsername);
        boolean changePassword = newPw != null && !newPw.isEmpty();

        if (!changeUsername && !changePassword) {
            errors.add("未检测到任何修改。");
        }
        if (newUsername.isEmpty()) {
            errors.add("用户名不能为空。");
        } else if (changeUsername) {
            if (newUsername.length() < 3) {
                errors.add("用户名至少 3 个字符。");
            } else {
                Long dup = db.jdbc().queryForObject(
                        "SELECT COUNT(*) FROM users WHERE username = ? AND id != ?",
                        Long.class, newUsername, user.get("id"));
                if (dup != null && dup > 0) {
                    errors.add("该用户名已被占用。");
                }
            }
        }
        if (changePassword) {
            if (newPw.length() < 6) {
                errors.add("新密码至少 6 个字符。");
            } else if (!newPw.equals(confirmPw)) {
                errors.add("两次输入的新密码不一致。");
            }
        }

        if (!errors.isEmpty()) {
            errors.forEach(e -> Flash.danger(req, e));
            model.addAttribute("ctx", Ctx.of(req));
            model.addAttribute("username", currentUsername);
            return "account";
        }

        if (changeUsername) {
            db.jdbc().update("UPDATE users SET username = ? WHERE id = ?",
                    newUsername, user.get("id"));
        }
        if (changePassword) {
            db.jdbc().update("UPDATE users SET password_hash = ? WHERE id = ?",
                    Security.hashPassword(newPw), user.get("id"));
        }

        List<String> what = new ArrayList<>();
        if (changeUsername) {
            what.add("用户名→" + newUsername);
        }
        if (changePassword) {
            what.add("密码");
        }
        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "update", "users", ((Number) user.get("id")).longValue(),
                "账户变更：" + String.join("、", what), null, null);

        // 改密码后强制重新登录
        if (changePassword) {
            var s = req.getSession(false);
            if (s != null) {
                s.invalidate();
            }
            Flash.success(req, "密码已修改，请使用新密码重新登录。");
            return "redirect:/login";
        }
        if (changeUsername) {
            req.getSession(true).setAttribute(SecurityFilters.SESSION_USER, newUsername);
        }
        Flash.success(req, "账户信息已更新。");
        return "redirect:/account";
    }

    private Map<String, Object> currentUser(HttpServletRequest req) {
        String name = SecurityFilters.currentUser(req);
        if (name == null) {
            return null;
        }
        var rows = db.jdbc().queryForList("SELECT * FROM users WHERE username = ?", name);
        return rows.isEmpty() ? null : rows.get(0);
    }
}

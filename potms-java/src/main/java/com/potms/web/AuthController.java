package com.potms.web;

import com.potms.Config;
import com.potms.data.Db;
import com.potms.service.Lockout;
import com.potms.service.Security;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSession;
import java.util.Map;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;

/** 登录 / 登出 — 对应 Python 版 auth.py。 */
@Controller
public class AuthController {

    private final Db db;
    private final Lockout lockout;

    public AuthController(Db db, Lockout lockout) {
        this.db = db;
        this.lockout = lockout;
    }

    @GetMapping("/login")
    public String loginPage(HttpServletRequest req, Model model) {
        // 未登录被重定向至此时补一条提示，与其它四版一致
        if (req.getParameter("ReturnUrl") != null) {
            Flash.warning(req, "请先登录。");
        }
        model.addAttribute("ctx", Ctx.of(req));
        return "login";
    }

    @PostMapping("/login")
    public String login(HttpServletRequest req,
                        @RequestParam(required = false) String username,
                        @RequestParam(required = false) String password,
                        Model model) {
        String ip = SecurityFilters.clientIp(req);

        int remain = lockout.remaining(ip);
        if (remain > 0) {
            Flash.danger(req, "登录失败次数过多，已临时锁定，请 " + (remain / 60 + 1) + " 分钟后再试。");
            return redirectLogin(req, model);
        }

        String user = username == null ? "" : username.trim();
        String pass = password == null ? "" : password;
        if (user.isEmpty() || pass.isEmpty()) {
            Flash.danger(req, "请输入用户名和密码。");
            return redirectLogin(req, model);
        }

        Map<String, Object> row = db.jdbc().queryForList(
                "SELECT id, username, password_hash, full_name FROM users WHERE username = ?", user)
                .stream().findFirst().orElse(null);

        Security.Result result = row == null
                ? new Security.Result(false, false)
                : Security.verifyPassword(pass, (String) row.get("password_hash"));

        if (result.matched()) {
            lockout.reset(ip);
            if (result.needsRehash()) {   // 旧 werkzeug pbkdf2 哈希，登录时透明升级为 bcrypt
                db.jdbc().update("UPDATE users SET password_hash = ? WHERE id = ?",
                        Security.hashPassword(pass), row.get("id"));
            }
            // 防会话固定：登录成功后换一个新 session id
            HttpSession old = req.getSession(false);
            if (old != null) {
                old.invalidate();
            }
            HttpSession s = req.getSession(true);
            s.setAttribute(SecurityFilters.SESSION_USER, user);
            // 单据上的经办人取这个；没填姓名时回退到账号，保证字段永不为空
            String fullName = row.get("full_name") == null ? "" : row.get("full_name").toString().trim();
            s.setAttribute(SecurityFilters.SESSION_FULL_NAME, fullName.isEmpty() ? user : fullName);
            s.setMaxInactiveInterval(Config.SESSION_TIMEOUT_SECONDS);

            Flash.success(req, "登录成功。");
            return "redirect:/";
        }

        lockout.recordFailure(ip);
        Helpers.logAction(db.jdbc(), user, ip, "login_fail", "auth", null, "登录失败", null, null);
        if (lockout.justLocked(ip)) {
            Helpers.logAction(db.jdbc(), user, ip, "lock", "auth", null,
                    "账户锁定 " + (Config.LOCK_SECONDS / 60) + " 分钟", null, null);
        }

        int left = lockout.failsLeft(ip);
        Flash.danger(req, left > 0
                ? "用户名或密码错误（再失败 " + left + " 次将锁定 " + (Config.LOCK_SECONDS / 60) + " 分钟）。"
                : "登录失败次数过多，已锁定 " + (Config.LOCK_SECONDS / 60) + " 分钟。");
        return redirectLogin(req, model);
    }

    @GetMapping("/logout")
    public String logout(HttpServletRequest req) {
        String user = SecurityFilters.currentUser(req);
        if (user != null) {
            Helpers.logAction(db.jdbc(), user, SecurityFilters.clientIp(req),
                    "logout", "auth", null, "退出登录", null, null);
        }
        HttpSession s = req.getSession(false);
        if (s != null) {
            s.invalidate();
        }
        Flash.info(req, "已安全退出。");
        return "redirect:/login";
    }

    /** 失败时重新渲染登录页（而非重定向），使闪现消息与其它四版同一时序出现。 */
    private String redirectLogin(HttpServletRequest req, Model model) {
        model.addAttribute("ctx", Ctx.of(req));
        return "login";
    }
}

package com.potms.web;

import static com.potms.web.PersonnelController.operator;
import static com.potms.web.PersonnelController.trim;

import com.potms.Config;
import com.potms.data.Db;
import com.potms.service.Backup;
import com.potms.service.Security;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;

/** 账户设置：修改用户名 / 姓名 / 密码，以及历史经办人回填。对应 Python 版 auth.account。 */
@Controller
public class AccountController {

    private final Db db;
    private final Config cfg;

    public AccountController(Db db, Config cfg) {
        this.db = db;
        this.cfg = cfg;
    }

    @GetMapping("/account")
    public String account(HttpServletRequest req, Model model) {
        var user = currentUser(req);
        if (user == null) {
            return "redirect:/login";
        }
        fillView(req, model, String.valueOf(user.get("username")), str(user.get("full_name")));
        return "account";
    }

    @PostMapping("/account")
    public String update(HttpServletRequest req, Model model) {
        var user = currentUser(req);
        if (user == null) {
            return "redirect:/login";
        }
        String currentUsername = String.valueOf(user.get("username"));
        String currentFullName = str(user.get("full_name"));
        String currentPw = req.getParameter("current_password");
        String newUsername = trim(req, "new_username");
        String newFullName = trim(req, "new_full_name");
        String newPw = req.getParameter("new_password");
        String confirmPw = req.getParameter("confirm_password");

        List<String> errors = new ArrayList<>();
        if (!Security.verifyPassword(currentPw == null ? "" : currentPw,
                String.valueOf(user.get("password_hash"))).matched()) {
            errors.add("当前密码不正确。");
        }

        boolean changeUsername = !newUsername.isEmpty() && !newUsername.equals(currentUsername);
        boolean changePassword = newPw != null && !newPw.isEmpty();
        boolean changeFullName = !newFullName.equals(currentFullName);

        if (!changeUsername && !changePassword && !changeFullName) {
            errors.add("未检测到任何修改。");
        }
        if (newFullName.length() > 30) {
            errors.add("姓名过长（最多 30 个字符）。");
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
            fillView(req, model, currentUsername, newFullName);
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
        if (changeFullName) {
            db.jdbc().update("UPDATE users SET full_name = ? WHERE id = ?",
                    newFullName.isEmpty() ? null : newFullName, user.get("id"));
        }

        List<String> what = new ArrayList<>();
        if (changeUsername) {
            what.add("用户名→" + newUsername);
        }
        if (changeFullName) {
            what.add("姓名→" + (newFullName.isEmpty() ? "（清空）" : newFullName));
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
        if (changeUsername || changeFullName) {
            var s = req.getSession(true);
            String name = changeUsername ? newUsername : currentUsername;
            s.setAttribute(SecurityFilters.SESSION_USER, name);
            s.setAttribute(SecurityFilters.SESSION_FULL_NAME,
                    newFullName.isEmpty() ? name : newFullName);
        }
        Flash.success(req, "账户信息已更新。");
        return "redirect:/account";
    }

    // ------------------------------------------------------------------
    // 历史经办人回填
    //
    // 升级那一刻系统还不知道真实姓名——得先去账户设置填。所以「加列」和「改历史
    // 数据」不能是同一步，回填只能等姓名填好之后由用户显式触发。
    //
    // 刻意做成按钮而不是升级时静默 UPDATE：批量改历史数据不可逆，得让人看清影响
    // 条数再点。执行前自动备一次库，整件事也记进操作日志。
    // ------------------------------------------------------------------

    /** 业务表的经办人字段。operation_logs 不在其列——那是审计痕迹，记的是账号。 */
    private static final String[][] OPERATOR_COLUMNS = {
        {"personnel_info", "operator"},
        {"personnel_filing", "operator"},
        {"certificates", "operator"},
        {"travel_details", "operator"},
        {"decontrol_filing", "operator"},
        {"cert_issuance", "operator"},
        {"cert_issuance", "issuer"},
        {"cert_issuance", "return_operator"},
    };

    @PostMapping("/account/backfill-operator")
    public String backfillOperator(HttpServletRequest req) {
        var user = currentUser(req);
        if (user == null) {
            return "redirect:/login";
        }
        String username = String.valueOf(user.get("username"));
        String fullName = str(user.get("full_name"));
        if (fullName.isEmpty()) {
            Flash.warning(req, "请先填写并保存姓名，再回填历史记录。");
            return "redirect:/account";
        }
        if (fullName.equals(username)) {
            Flash.info(req, "姓名与登录账号相同，无需回填。");
            return "redirect:/account";
        }

        // 不可逆的批量写入，先留一份退路。force：当天已备过也要再备，因为马上要改数据。
        if (!Backup.runDaily(cfg, true).created()) {
            Flash.danger(req, "自动备份失败，已中止回填。请手动备份 data.db 后重试。");
            return "redirect:/account";
        }

        long changed = 0;
        for (String[] tc : OPERATOR_COLUMNS) {
            try {
                changed += db.jdbc().update(
                        "UPDATE " + tc[0] + " SET " + tc[1] + " = ? WHERE " + tc[1] + " = ?",
                        fullName, username);
            } catch (DataAccessException e) {
                // 老库可能还没有 cert_issuance 表
            }
        }

        Helpers.logAction(db.jdbc(), operator(req), SecurityFilters.clientIp(req),
                "update", "users", ((Number) user.get("id")).longValue(),
                "历史经办人回填：" + username + " → " + fullName + "，共 " + changed + " 条",
                null, null);
        Flash.success(req, "已把 " + changed + " 条历史记录的经办人由「" + username
                + "」更新为「" + fullName + "」。操作日志保持原样（审计需要登录账号）。");
        return "redirect:/account";
    }

    /** 统计业务表里还有多少条记录把登录账号当经办人。 */
    private long legacyOperatorCount(String username) {
        long total = 0;
        for (String[] tc : OPERATOR_COLUMNS) {
            try {
                Long n = db.jdbc().queryForObject(
                        "SELECT COUNT(*) FROM " + tc[0] + " WHERE " + tc[1] + " = ?",
                        Long.class, username);
                total += n == null ? 0 : n;
            } catch (DataAccessException e) {
                // 老库可能还没有 cert_issuance 表
            }
        }
        return total;
    }

    private void fillView(HttpServletRequest req, Model model, String username, String fullName) {
        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("username", username);
        model.addAttribute("fullName", fullName);
        model.addAttribute("legacyTotal", legacyOperatorCount(username));
    }

    private static String str(Object o) {
        return o == null ? "" : o.toString().trim();
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

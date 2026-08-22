using System.Security.Claims;
using Dapper;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages;

[AllowAnonymous]
public class LoginModel(Db db, Flash flash, Lockout lockout) : PageModel
{
    public void OnGet()
    {
        // 未登录被重定向至此时补一条提示，与其它三版一致
        if (Request.Query.ContainsKey("ReturnUrl"))
            flash.Warning("请先登录。");
    }

    public async Task<IActionResult> OnPostAsync(string? username, string? password)
    {
        var ip = HttpContext.Connection.RemoteIpAddress?.ToString() ?? "-";

        var remain = lockout.Remaining(ip);
        if (remain > 0)
        {
            flash.Danger($"登录失败次数过多，已临时锁定，请 {remain / 60 + 1} 分钟后再试。");
            return Page();
        }

        username = (username ?? "").Trim();
        password ??= "";
        if (username.Length == 0 || password.Length == 0)
        {
            flash.Danger("请输入用户名和密码。");
            return Page();
        }

        using var cn = db.Open();
        var user = cn.QueryFirstOrDefault(
            "SELECT id, username, password_hash, full_name FROM users WHERE username = @u",
            new { u = username });

        var (matched, needsRehash) = user is null
            ? (false, false)
            : Security.VerifyPassword(password, (string?)user.password_hash);

        if (matched)
        {
            lockout.Reset(ip);
            if (needsRehash)   // 旧 werkzeug pbkdf2 哈希，登录时透明升级为 bcrypt
                cn.Execute("UPDATE users SET password_hash = @h WHERE id = @id",
                    new { h = Security.HashPassword(password), id = (long)user!.id });

            // 单据上的经办人取 GivenName；没填姓名时回退到账号，保证字段永不为空
            var fullName = ((string?)user!.full_name ?? "").Trim();
            if (fullName.Length == 0) fullName = username;
            var identity = new ClaimsIdentity(
                [new Claim(ClaimTypes.Name, username), new Claim(ClaimTypes.GivenName, fullName)],
                CookieAuthenticationDefaults.AuthenticationScheme);
            await HttpContext.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme,
                new ClaimsPrincipal(identity), new AuthenticationProperties { IsPersistent = false });

            flash.Success("登录成功。");
            return Redirect("/");
        }

        lockout.RecordFailure(ip);
        Helpers.LogAction(cn, username, ip, "login_fail", "auth", detail: "登录失败");
        if (lockout.JustLocked(ip))
            Helpers.LogAction(cn, username, ip, "lock", "auth",
                detail: $"账户锁定 {Config.LockSeconds / 60} 分钟");

        var left = lockout.FailsLeft(ip);
        flash.Danger(left > 0
            ? $"用户名或密码错误（再失败 {left} 次将锁定 {Config.LockSeconds / 60} 分钟）。"
            : $"登录失败次数过多，已锁定 {Config.LockSeconds / 60} 分钟。");
        return Page();
    }
}

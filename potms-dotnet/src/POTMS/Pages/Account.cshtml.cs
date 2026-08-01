using Dapper;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages;

public class AccountModel(Db db, Flash flash) : AppPageModel(flash)
{
    public string Username { get; private set; } = "";

    public void OnGet() => Username = CurrentUser;

    public async Task<IActionResult> OnPostAsync(string? currentPassword, string? newUsername,
                                                 string? newPassword, string? confirmPassword)
    {
        Username = CurrentUser;
        using var cn = db.Open();
        var user = cn.QueryFirstOrDefault("SELECT id, username, password_hash FROM users WHERE username=@u",
            new { u = CurrentUser });
        if (user is null)
        {
            await HttpContext.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
            return Redirect("/Login");
        }

        long uid = user.id;
        string curName = user.username;
        newUsername = (newUsername ?? "").Trim();

        var errs = new List<string>();
        if (!Security.VerifyPassword(currentPassword ?? "", (string?)user.password_hash).Matched)
            errs.Add("当前密码不正确。");

        var changeName = newUsername.Length > 0 && newUsername != curName;
        var changePwd = !string.IsNullOrEmpty(newPassword);
        if (!changeName && !changePwd) errs.Add("未检测到任何修改。");
        if (newUsername.Length == 0) errs.Add("用户名不能为空。");
        else if (changeName)
        {
            if (newUsername.Length < 3) errs.Add("用户名至少 3 个字符。");
            else if (cn.QueryFirstOrDefault<long?>(
                         "SELECT id FROM users WHERE username=@u AND id != @id",
                         new { u = newUsername, id = uid }) is not null)
                errs.Add("该用户名已被占用。");
        }
        if (changePwd)
        {
            if (newPassword!.Length < 6) errs.Add("新密码至少 6 个字符。");
            else if (newPassword != confirmPassword) errs.Add("两次输入的新密码不一致。");
        }

        if (errs.Count > 0) { foreach (var e in errs) Flash.Danger(e); return Page(); }

        if (changeName)
            cn.Execute("UPDATE users SET username=@u WHERE id=@id", new { u = newUsername, id = uid });
        if (changePwd)
            cn.Execute("UPDATE users SET password_hash=@h WHERE id=@id",
                new { h = Security.HashPassword(newPassword!), id = uid });

        var parts = new List<string>();
        if (changeName) parts.Add($"用户名→{newUsername}");
        if (changePwd) parts.Add("密码");
        Log(cn, "update", "users", uid, $"账户变更：{string.Join("、", parts)}");

        if (changePwd)
        {
            await HttpContext.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
            Flash.Success("密码已修改，请使用新密码重新登录。");
            return Redirect("/Login");
        }

        // 仅改用户名：重新签发身份，避免后续操作仍记到旧账户名下
        var identity = new System.Security.Claims.ClaimsIdentity(
            [new System.Security.Claims.Claim(System.Security.Claims.ClaimTypes.Name, newUsername)],
            CookieAuthenticationDefaults.AuthenticationScheme);
        await HttpContext.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme,
            new System.Security.Claims.ClaimsPrincipal(identity));
        Flash.Success("账户信息已更新。");
        return Redirect("/Account");
    }
}

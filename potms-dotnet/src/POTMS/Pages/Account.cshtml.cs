using Dapper;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;

namespace POTMS.Pages;

public class AccountModel(Db db, Flash flash, Config cfg) : AppPageModel(flash)
{
    public string Username { get; private set; } = "";
    public string FullName { get; private set; } = "";

    /// <summary>业务表里还有多少条记录把登录账号当经办人（0 表示不用回填）。</summary>
    public long LegacyTotal { get; private set; }

    public void OnGet() => LoadView();

    private void LoadView()
    {
        Username = CurrentUser;
        using var cn = db.Open();
        FullName = cn.QueryFirstOrDefault<string?>(
            "SELECT full_name FROM users WHERE username=@u", new { u = CurrentUser }) ?? "";
        LegacyTotal = LegacyOperatorCount(cn, CurrentUser);
    }

    public async Task<IActionResult> OnPostAsync(string? currentPassword, string? newUsername,
                                                 string? newFullName,
                                                 string? newPassword, string? confirmPassword)
    {
        Username = CurrentUser;
        using var cn = db.Open();
        var user = cn.QueryFirstOrDefault(
            "SELECT id, username, password_hash, full_name FROM users WHERE username=@u",
            new { u = CurrentUser });
        if (user is null)
        {
            await HttpContext.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
            return Redirect("/Login");
        }

        long uid = user.id;
        string curName = user.username;
        string curFullName = ((string?)user.full_name ?? "");
        newUsername = (newUsername ?? "").Trim();
        newFullName = (newFullName ?? "").Trim();
        FullName = newFullName;

        var errs = new List<string>();
        if (!Security.VerifyPassword(currentPassword ?? "", (string?)user.password_hash).Matched)
            errs.Add("当前密码不正确。");

        var changeName = newUsername.Length > 0 && newUsername != curName;
        var changePwd = !string.IsNullOrEmpty(newPassword);
        var changeFullName = newFullName != curFullName;
        if (!changeName && !changePwd && !changeFullName) errs.Add("未检测到任何修改。");
        if (newFullName.Length > 30) errs.Add("姓名过长（最多 30 个字符）。");
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

        if (errs.Count > 0)
        {
            foreach (var e in errs) Flash.Danger(e);
            LegacyTotal = LegacyOperatorCount(cn, CurrentUser);
            return Page();
        }

        if (changeName)
            cn.Execute("UPDATE users SET username=@u WHERE id=@id", new { u = newUsername, id = uid });
        if (changePwd)
            cn.Execute("UPDATE users SET password_hash=@h WHERE id=@id",
                new { h = Security.HashPassword(newPassword!), id = uid });
        if (changeFullName)
            cn.Execute("UPDATE users SET full_name=@n WHERE id=@id",
                new { n = newFullName.Length == 0 ? null : newFullName, id = uid });

        var parts = new List<string>();
        if (changeName) parts.Add($"用户名→{newUsername}");
        if (changeFullName) parts.Add($"姓名→{(newFullName.Length == 0 ? "（清空）" : newFullName)}");
        if (changePwd) parts.Add("密码");
        Log(cn, "update", "users", uid, $"账户变更：{string.Join("、", parts)}");

        if (changePwd)
        {
            await HttpContext.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
            Flash.Success("密码已修改，请使用新密码重新登录。");
            return Redirect("/Login");
        }

        // 改了用户名或姓名：重新签发身份，避免后续操作仍带着旧值
        await ReissueIdentity(newUsername, newFullName);
        Flash.Success("账户信息已更新。");
        return Redirect("/Account");
    }

    // -----------------------------------------------------------------------
    // 历史经办人回填
    //
    // 升级那一刻系统还不知道真实姓名——得先去账户设置填。所以「加列」和「改历史
    // 数据」不能是同一步，回填只能等姓名填好之后由用户显式触发。
    //
    // 刻意做成按钮而不是升级时静默 UPDATE：批量改历史数据不可逆，得让人看清影响
    // 条数再点。执行前自动备一次库，整件事也记进操作日志。
    // -----------------------------------------------------------------------

    /// <summary>业务表的经办人字段。operation_logs 不在其列——那是审计痕迹，记的是账号。</summary>
    private static readonly (string Table, string Column)[] OperatorColumns =
    [
        ("personnel_info", "operator"),
        ("personnel_filing", "operator"),
        ("certificates", "operator"),
        ("travel_details", "operator"),
        ("decontrol_filing", "operator"),
        ("cert_issuance", "operator"),
        ("cert_issuance", "issuer"),
        ("cert_issuance", "return_operator"),
    ];

    private static long LegacyOperatorCount(System.Data.IDbConnection cn, string username)
    {
        long total = 0;
        foreach (var (table, col) in OperatorColumns)
        {
            try
            {
                total += cn.ExecuteScalar<long>(
                    $"SELECT COUNT(*) FROM {table} WHERE {col} = @u", new { u = username });
            }
            catch (Microsoft.Data.Sqlite.SqliteException)
            {
                // 老库可能还没有 cert_issuance 表
            }
        }
        return total;
    }

    public async Task<IActionResult> OnPostBackfillAsync()
    {
        using var cn = db.Open();
        var user = cn.QueryFirstOrDefault(
            "SELECT id, username, full_name FROM users WHERE username=@u", new { u = CurrentUser });
        if (user is null)
        {
            await HttpContext.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
            return Redirect("/Login");
        }

        long uid = user.id;
        string username = user.username;
        string fullName = ((string?)user.full_name ?? "").Trim();
        if (fullName.Length == 0)
        {
            Flash.Warning("请先填写并保存姓名，再回填历史记录。");
            return Redirect("/Account");
        }
        if (fullName == username)
        {
            Flash.Info("姓名与登录账号相同，无需回填。");
            return Redirect("/Account");
        }

        // 不可逆的批量写入，先留一份退路。force：当天已备过也要再备，因为马上要改数据。
        if (!Backup.RunDaily(cfg, force: true).Created)
        {
            Flash.Danger("自动备份失败，已中止回填。请手动备份 data.db 后重试。");
            return Redirect("/Account");
        }

        long changed = 0;
        foreach (var (table, col) in OperatorColumns)
        {
            try
            {
                changed += cn.Execute($"UPDATE {table} SET {col} = @n WHERE {col} = @u",
                    new { n = fullName, u = username });
            }
            catch (Microsoft.Data.Sqlite.SqliteException)
            {
                // 老库缺表，跳过
            }
        }

        Log(cn, "update", "users", uid, $"历史经办人回填：{username} → {fullName}，共 {changed} 条");
        Flash.Success($"已把 {changed} 条历史记录的经办人由「{username}」更新为「{fullName}」。" +
                      "操作日志保持原样（审计需要登录账号）。");
        return Redirect("/Account");
    }

    private async Task ReissueIdentity(string username, string fullName)
    {
        var shown = fullName.Length == 0 ? username : fullName;
        var identity = new System.Security.Claims.ClaimsIdentity(
            [
                new System.Security.Claims.Claim(System.Security.Claims.ClaimTypes.Name, username),
                new System.Security.Claims.Claim(System.Security.Claims.ClaimTypes.GivenName, shown),
            ],
            CookieAuthenticationDefaults.AuthenticationScheme);
        await HttpContext.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme,
            new System.Security.Claims.ClaimsPrincipal(identity));
    }
}

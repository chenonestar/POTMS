using Microsoft.AspNetCore.Authentication.Cookies;
using System.Text.Encodings.Web;
using System.Text.Unicode;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.Extensions.WebEncoders;
using POTMS;
using POTMS.Data;
using POTMS.Services;

var cfg = new Config();

// 初始化数据库（首次运行建表 + 种子），随后执行幂等迁移
var db = new Db(cfg);
var firstRun = db.IsFirstRun;
if (firstRun)
{
    db.Initialize();
    db.SeedData();
}
db.Migrate();

// --init-db：仅初始化数据库后退出（供 CI 与 schema 一致性校验使用）
if (args.Contains("--init-db"))
{
    Console.WriteLine($"数据库已初始化：{cfg.Database}");
    return;
}

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddSingleton(cfg);
builder.Services.AddSingleton(db);
builder.Services.AddSingleton<Lockout>();
builder.Services.AddScoped<Flash>();
builder.Services.AddHttpContextAccessor();

builder.Services.AddRazorPages(o =>
{
    o.Conventions.AuthorizeFolder("/");            // 默认全站需登录
    o.Conventions.AllowAnonymousToPage("/Login");
    o.Conventions.AllowAnonymousToPage("/Error");
});

builder.Services.AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme)
    .AddCookie(o =>
    {
        o.LoginPath = "/Login";
        o.LogoutPath = "/Logout";
        o.AccessDeniedPath = "/Login";
        o.Cookie.Name = "potms_session";
        o.Cookie.HttpOnly = true;
        o.Cookie.SameSite = SameSiteMode.Lax;
        o.ExpireTimeSpan = TimeSpan.FromSeconds(Config.SessionTimeoutSeconds);
        o.SlidingExpiration = true;                // 会话滑动续期
    });

// CSRF：表单域名与请求头沿用其它三版的命名，前端脚本可直接复用
builder.Services.AddAntiforgery(o =>
{
    o.FormFieldName = "csrf_token";
    o.HeaderName = "X-CSRFToken";
});

builder.Services.Configure<FormOptions>(o =>
{
    o.MultipartBodyLengthLimit = Config.MaxContentLength;
});

// Razor 默认把非 ASCII 转义为 &#x...; 数字实体，中文页面体积会膨胀约 3 倍且不可读。
// 放开 Unicode 全范围，中文直接以 UTF-8 输出（XSS 防护由 HTML 编码本身保证，不受影响）。
builder.Services.Configure<WebEncoderOptions>(o =>
    o.TextEncoderSettings = new TextEncoderSettings(UnicodeRanges.All));

builder.WebHost.UseUrls($"http://{Environment.GetEnvironmentVariable("POTMS_HOST") ?? "127.0.0.1"}:" +
                        $"{Environment.GetEnvironmentVariable("POTMS_PORT") ?? "5000"}");

var app = builder.Build();

app.UseStaticFiles();
app.UseRouting();
app.UseAuthentication();
app.UseAuthorization();
app.MapRazorPages();

// 每日自动备份（幂等：当天已备份则跳过）
try { Backup.RunDaily(cfg); } catch { /* 备份失败不应阻断启动 */ }

Console.WriteLine(new string('=', 56));
Console.WriteLine("  因私出国（境）人员审批管理系统 (.NET)");
Console.WriteLine($"  http://localhost:{Environment.GetEnvironmentVariable("POTMS_PORT") ?? "5000"}");
if (firstRun) Console.WriteLine("  首次运行，默认管理员: admin / admin123（请尽快改密）");
Console.WriteLine(new string('=', 56));

app.Run();

/// <summary>供集成测试引用的入口标记类型。</summary>
public partial class Program;

using System.Data;
using Microsoft.AspNetCore.Mvc.RazorPages;
using POTMS.Services;

namespace POTMS.Pages;

/// <summary>页面基类：统一提供当前操作人、客户端 IP 与写日志的入口。</summary>
public abstract class AppPageModel(Flash flash) : PageModel
{
    protected Flash Flash { get; } = flash;
    protected string CurrentUser => User.Identity?.Name ?? "unknown";
    protected string? ClientIp => HttpContext.Connection.RemoteIpAddress?.ToString();

    protected void Log(IDbConnection cn, string action, string targetType, long? targetId = null,
                       string? detail = null,
                       Dictionary<string, object?>? before = null,
                       Dictionary<string, object?>? after = null) =>
        Helpers.LogAction(cn, CurrentUser, ClientIp, action, targetType, targetId, detail, before, after);
}

using System.Data;
using Microsoft.AspNetCore.Mvc.RazorPages;
using POTMS.Services;

namespace POTMS.Pages;

/// <summary>页面基类：统一提供当前操作人、客户端 IP 与写日志的入口。</summary>
public abstract class AppPageModel(Flash flash) : PageModel
{
    protected Flash Flash { get; } = flash;

    /// <summary>登录**账号**。操作日志记的就是它——账号是身份标识，姓名可以随时改；
    /// 日志只记「张三」的话，改名之后历史记录就对不上人了。</summary>
    protected string CurrentUser => User.Identity?.Name ?? "unknown";

    /// <summary>业务单据上的**经办人**：真实姓名，没填则回退到登录账号。
    ///
    /// 单据、打印件、导出表上的「经办人」必须是真人名字——打印出来的领用凭证上
    /// 一个 admin，没法拿去归档。姓名在「账户设置」里维护，登录时写进 GivenName 声明。</summary>
    protected string OperatorName
    {
        get
        {
            var n = User.FindFirst(System.Security.Claims.ClaimTypes.GivenName)?.Value;
            return string.IsNullOrWhiteSpace(n) ? CurrentUser : n;
        }
    }

    protected string? ClientIp => HttpContext.Connection.RemoteIpAddress?.ToString();

    protected void Log(IDbConnection cn, string action, string targetType, long? targetId = null,
                       string? detail = null,
                       Dictionary<string, object?>? before = null,
                       Dictionary<string, object?>? after = null) =>
        Helpers.LogAction(cn, CurrentUser, ClientIp, action, targetType, targetId, detail, before, after);
}

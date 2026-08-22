using Microsoft.AspNetCore.Mvc.RazorPages;

namespace POTMS.Pages;

/// <summary>中文错误页。对应 Python 版 templates/errors/404.html 与 500.html。
///
/// <para>接管两条入口：UseStatusCodePagesWithReExecute 把 4xx/5xx 状态码重定向到这里，
/// UseExceptionHandler 把未捕获异常也送到这里。此前两者都没配，
/// 404 是一片空白、500 是 ASP.NET 的英文默认页——与另外三版对不上。</para>
///
/// <para>这一页刻意不依赖数据库、会话与 _Layout：错误页最需要的就是在别的东西
/// 都坏掉时仍能渲染出来。</para>
/// </summary>
public class ErrorModel : PageModel
{
    public int Code { get; private set; } = 500;
    public string Title { get; private set; } = "系统内部错误";
    public string Message { get; private set; } = "";
    public string Hint { get; private set; } = "";
    public string Icon { get; private set; } = "bi-exclamation-octagon text-danger";
    public string Color { get; private set; } = "#c0392b";

    public void OnGet(int? code)
    {
        Code = code is >= 400 and < 600 ? code.Value : 500;
        if (Code == 404)
        {
            Title = "页面不存在";
            Message = "您访问的页面不存在或已被移除。";
            Icon = "bi-compass text-secondary";
            Color = "#1a5276";
        }
        else if (Code == 403)
        {
            Title = "没有权限";
            Message = "本次请求被拒绝。";
            Hint = "若是表单提交失败，多半是页面停留过久令牌过期，请返回重新打开页面再试。";
            Icon = "bi-shield-exclamation text-warning";
            Color = "#b9770e";
        }
        else
        {
            Title = "系统内部错误";
            Message = "系统内部发生错误，本次操作未完成。";
            Hint = "已有数据不受影响。请返回重试；若反复出现，请联系系统维护人员并说明操作步骤。";
        }
        Response.StatusCode = Code;
    }
}

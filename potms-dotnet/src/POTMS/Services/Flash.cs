using System.Text.Json;
using Microsoft.AspNetCore.Mvc.ViewFeatures;

namespace POTMS.Services;

/// <summary>闪现消息 — 对应 Flask 的 flash() / get_flashed_messages()。
/// 借助 TempData 跨重定向传递；类别沿用 Bootstrap 的 success/danger/warning/info。</summary>
public sealed class Flash(IHttpContextAccessor accessor)
{
    private const string Key = "_flashes";
    private readonly IHttpContextAccessor _accessor = accessor;

    private ITempDataDictionary Temp =>
        _accessor.HttpContext!.RequestServices
            .GetRequiredService<ITempDataDictionaryFactory>()
            .GetTempData(_accessor.HttpContext!);

    public void Add(string message, string category = "info")
    {
        var temp = Temp;
        var list = Read(temp);
        list.Add(new FlashMessage(category, message));
        temp[Key] = JsonSerializer.Serialize(list);
    }

    public void Success(string m) => Add(m, "success");
    public void Danger(string m) => Add(m, "danger");
    public void Warning(string m) => Add(m, "warning");
    public void Info(string m) => Add(m, "info");

    /// <summary>取出并清空（供布局渲染）。</summary>
    public List<FlashMessage> Pop()
    {
        var temp = Temp;
        var list = Read(temp);
        temp.Remove(Key);
        return list;
    }

    private static List<FlashMessage> Read(ITempDataDictionary temp) =>
        temp.Peek(Key) is string s && s.Length > 0
            ? JsonSerializer.Deserialize<List<FlashMessage>>(s) ?? []
            : [];
}

public record FlashMessage(string Category, string Message);

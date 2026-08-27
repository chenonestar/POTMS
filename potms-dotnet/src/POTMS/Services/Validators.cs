using System.Globalization;
using System.Text.RegularExpressions;

namespace POTMS.Services;

/// <summary>校验工具 — 对应 Python 版 utils/validators.py，逐条对齐错误文案。</summary>
public static partial class Validators
{
    private static readonly int[] IdWeights = { 7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2 };
    private const string IdCheck = "10X98765432";

    [GeneratedRegex(@"(\d{4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})")]
    private static partial Regex DateScanRegex();

    private static bool IsDigits(string s) => s.Length > 0 && s.All(char.IsAsciiDigit);

    /// <summary>解析 YYYYMMDD；不存在的日期（如 20260230）返回 null。</summary>
    public static DateTime? ParseYmd(string? s)
    {
        if (string.IsNullOrEmpty(s) || s.Length != 8 || !IsDigits(s)) return null;
        return DateTime.TryParseExact(s, "yyyyMMdd", CultureInfo.InvariantCulture,
            DateTimeStyles.None, out var d) ? d : null;
    }

    public static (bool Ok, string Msg) ValidateIdNumber(string? idNumber)
    {
        if (string.IsNullOrEmpty(idNumber) || idNumber.Length != 18)
            return (false, "身份证号须为18位。");
        if (!IsDigits(idNumber[..17]))
            return (false, "身份证号前17位须为数字。");

        var total = 0;
        for (var i = 0; i < 17; i++) total += (idNumber[i] - '0') * IdWeights[i];
        var expected = IdCheck[total % 11];
        if (char.ToUpperInvariant(idNumber[17]) != expected)
            return (false, $"身份证校验位不正确，应为 {expected}。");

        if (ParseYmd(idNumber.Substring(6, 8)) is null)
            return (false, "身份证号中出生日期不合法。");
        return (true, "");
    }

    public static (bool Ok, string Msg) ValidateBirthDateMatch(string idNumber, string birthDate)
    {
        var idBirth = idNumber.Substring(6, 8);
        return idBirth != birthDate
            ? (false, $"出生日期与身份证号不一致（身份证中为 {idBirth}）。")
            : (true, "");
    }

    /// <summary>第17位顺序码奇数→男，偶数→女。</summary>
    public static (bool Ok, string Msg) ValidateGenderMatch(string? idNumber, string? gender)
    {
        if (string.IsNullOrEmpty(idNumber) || idNumber.Length != 18 || !char.IsAsciiDigit(idNumber[16]))
            return (true, "");   // 号码本身不合规交由 ValidateIdNumber 报错，此处不重复
        var expected = (idNumber[16] - '0') % 2 == 1 ? "男" : "女";
        if (!string.IsNullOrEmpty(gender) && gender != expected)
            return (false, $"性别与身份证号不一致（身份证中为 {expected}）。");
        return (true, "");
    }

    public static (bool Ok, string Msg) ValidateDateFormat(string? s)
    {
        if (string.IsNullOrEmpty(s) || s.Length != 8) return (false, "日期格式须为 YYYYMMDD（8位数字）。");
        if (!IsDigits(s)) return (false, "日期须为纯数字。");
        return ParseYmd(s) is null ? (false, "日期不合法。") : (true, "");
    }

    /// <summary>清洗用户输入：2023-06-20 / 2023/06/20 / 20230620 → YYYYMMDD。</summary>
    public static string ParseDateInput(string? raw)
    {
        raw = (raw ?? "").Trim();
        if (raw.Length == 0) return "";
        if (raw.Length == 8 && IsDigits(raw)) return raw;
        foreach (var sep in new[] { '-', '/', '.' })
        {
            if (!raw.Contains(sep)) continue;
            var parts = raw.Split(sep);
            if (parts.Length == 3)
                return $"{parts[0]}{parts[1].PadLeft(2, '0')}{parts[2].PadLeft(2, '0')}";
        }
        return raw;
    }

    public static bool IsPartyMember(string? status) =>
        status is "中共党员" or "中共预备党员";

    /// <summary>从出行日期文本解析 (起, 止)，取第一处与最后一处日期。</summary>
    public static (string Start, string End) ParseTravelRange(string? text)
    {
        if (string.IsNullOrEmpty(text)) return ("", "");
        var ms = DateScanRegex().Matches(text);
        if (ms.Count == 0) return ("", "");
        static string Norm(Match m) =>
            $"{m.Groups[1].Value}{m.Groups[2].Value.PadLeft(2, '0')}{m.Groups[3].Value.PadLeft(2, '0')}";
        return (Norm(ms[0]), Norm(ms[^1]));
    }

    /// <summary>统一存储格式 YYYY/MM/DD-YYYY/MM/DD（同日折叠为单个）。</summary>
    public static string FormatTravelRange(string? start, string? end)
    {
        static string F(string? s) =>
            !string.IsNullOrEmpty(s) && s.Length == 8 ? $"{s[..4]}/{s.Substring(4, 2)}/{s.Substring(6, 2)}" : "";
        var fs = F(start);
        var fe = F(end);
        if (fs.Length > 0 && fe.Length > 0 && fs != fe) return $"{fs}-{fe}";
        return fs.Length > 0 ? fs : fe;
    }

    public static (bool Ok, string Msg) ValidateTravelRange(string? text)
    {
        if (string.IsNullOrWhiteSpace(text)) return (false, "计划出行日期不能为空。");
        var (start, end) = ParseTravelRange(text);
        if (start.Length == 0 || end.Length == 0)
            return (false, "计划出行日期格式无法识别，请填「起始-结束」，如 2026-8-1-2026-8-11。");
        var (ok, msg) = ValidateDateFormat(start);
        if (!ok) return (false, $"起始日期不合法（解析为 {start}）：{msg}");
        (ok, msg) = ValidateDateFormat(end);
        if (!ok) return (false, $"结束日期不合法（解析为 {end}）：{msg}");
        if (string.CompareOrdinal(start, end) > 0)
            return (false, $"起始日期（{start}）不应晚于结束日期（{end}）。");
        return (true, "");
    }

    /// <summary>以 startYmd 为第 0 天向后顺延 n 个工作日（仅跳过周六日，不含法定节假日）。</summary>
    public static string AddWorkingDays(string? startYmd, int n)
    {
        var d = ParseYmd(startYmd);
        if (d is null) return "";
        var cur = d.Value;
        var counted = 0;
        while (counted < n)
        {
            cur = cur.AddDays(1);
            if (cur.DayOfWeek is not (DayOfWeek.Saturday or DayOfWeek.Sunday)) counted++;
        }
        return cur.ToString("yyyyMMdd", CultureInfo.InvariantCulture);
    }

    // ---- 公共校验器（对应 Python 的 check_* 系列）----
    public static List<string> CheckRequired(IDictionary<string, string?> data,
                                             params (string Field, string Label)[] fields)
    {
        var errs = new List<string>();
        foreach (var (field, label) in fields)
            if (!data.TryGetValue(field, out var v) || string.IsNullOrEmpty(v))
                errs.Add($"{label} 为必填项。");
        return errs;
    }

    public static List<string> CheckDates(IDictionary<string, string?> data,
                                          params (string Field, string Label)[] fields)
    {
        var errs = new List<string>();
        foreach (var (field, label) in fields)
        {
            if (!data.TryGetValue(field, out var v) || string.IsNullOrEmpty(v)) continue;
            var (ok, msg) = ValidateDateFormat(v);
            if (!ok) errs.Add($"{label}: {msg}");
        }
        return errs;
    }

    public static List<string> CheckIdentity(IDictionary<string, string?> data,
                                             string idField = "id_number",
                                             string? birthField = "birth_date",
                                             string? genderField = "gender")
    {
        var errs = new List<string>();
        data.TryGetValue(idField, out var idNo);
        if (string.IsNullOrEmpty(idNo)) return errs;

        var (ok, msg) = ValidateIdNumber(idNo);
        if (!ok) { errs.Add($"身份证号: {msg}"); return errs; }

        if (!string.IsNullOrEmpty(birthField) && data.TryGetValue(birthField, out var b) && !string.IsNullOrEmpty(b))
        {
            var (ok2, msg2) = ValidateBirthDateMatch(idNo, b);
            if (!ok2) errs.Add(msg2);
        }
        if (!string.IsNullOrEmpty(genderField) && data.TryGetValue(genderField, out var g) && !string.IsNullOrEmpty(g))
        {
            var (ok3, msg3) = ValidateGenderMatch(idNo, g);
            if (!ok3) errs.Add(msg3);
        }
        return errs;
    }

    // ---- 证件逾期口径（与其它三版一致）----

    /// <summary>归还到期日：正常行程以实际回国日（缺省回退计划结束日）+10 工作日；
    /// 取消行程以取消日 +5 工作日。无法确定基准日返回空串。</summary>
    public static string CertOverdueDeadline(string? tripStatus, string? cancelDate,
                                             string? actualReturnDate, string? travelEnd)
    {
        if ((tripStatus ?? "normal") == "cancelled")
            return AddWorkingDays(cancelDate ?? "", 5);
        var baseDate = !string.IsNullOrEmpty(actualReturnDate) ? actualReturnDate : travelEnd ?? "";
        return AddWorkingDays(baseDate, 10);
    }

    /// <summary>判断路径B（做证）的新办证件是否逾期未交回。
    ///
    /// <para>路径B 的人没有领用记录——证是他凭同意申办函自己去公安办的，从没进过保管处，
    /// 系统里没有「领用」这个动作可记。而 <see cref="IsCertOverdue"/> 的第一道判据是
    /// passport_collect_date 非空，那个字段由领用记录派生，路径B 永远是空，于是
    /// <b>这类人整个掉出了逾期告警</b>。偏偏他们风险最高：那本证从办出来起一直在本人
    /// 手上，单位连见都没见过。</para>
    ///
    /// <para>这里换一套判据：证件是否已经进入证照台账。台账里有，说明已交回收缴
    /// （登记时上交日期是必填的）；台账里没有——号码都还没录，或录了但没入库——就是
    /// 还没交回。到期日沿用同一套算法（回国后 10 个工作日 / 取消后 5 个）。</para>
    /// </summary>
    public static bool IsNewCertOverdue(string? needNewPassport, bool certRegistered,
                                        string? tripStatus, string? cancelDate,
                                        string? actualReturnDate, string? travelEnd, string today)
    {
        if (needNewPassport != "是") return false;
        if (certRegistered) return false;
        var deadline = CertOverdueDeadline(tripStatus, cancelDate, actualReturnDate, travelEnd);
        if (deadline.Length == 0) return false;
        return string.CompareOrdinal(today, deadline) > 0;
    }

    /// <summary>是否证件逾期未还：已领用 + 未归还 + today 严格大于到期日。</summary>
    public static bool IsCertOverdue(string? collectDate, string? returnDate, string? tripStatus,
                                     string? cancelDate, string? actualReturnDate, string? travelEnd,
                                     string today)
    {
        if (string.IsNullOrEmpty(collectDate)) return false;
        if (!string.IsNullOrEmpty(returnDate)) return false;
        var deadline = CertOverdueDeadline(tripStatus, cancelDate, actualReturnDate, travelEnd);
        if (deadline.Length == 0) return false;
        return string.CompareOrdinal(today, deadline) > 0;
    }
}

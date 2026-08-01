using POTMS.Services;
using Xunit;

namespace POTMS.Tests;

public class ValidatorTests
{
    [Theory]
    [InlineData("110101199001012133", true)]
    [InlineData("11010119900101213X", false)]   // 校验位错误
    [InlineData("123", false)]
    [InlineData("", false)]
    public void IdNumber_ChecksDigit(string id, bool expected) =>
        Assert.Equal(expected, Validators.ValidateIdNumber(id).Ok);

    [Theory]
    [InlineData("110101199001012133", "男", true)]    // 第17位 3 奇 → 男
    [InlineData("110101199001012133", "女", false)]
    [InlineData("110101199001012133", "", true)]      // 未填不校验
    public void Gender_MatchesIdNumber(string id, string gender, bool expected) =>
        Assert.Equal(expected, Validators.ValidateGenderMatch(id, gender).Ok);

    [Theory]
    [InlineData("20260101", true)]
    [InlineData("20260230", false)]   // 2月30日不存在
    [InlineData("20261340", false)]
    [InlineData("2026131", false)]
    public void DateFormat_RejectsImpossibleDates(string d, bool expected) =>
        Assert.Equal(expected, Validators.ValidateDateFormat(d).Ok);

    [Theory]
    [InlineData("2023-06-20", "20230620")]
    [InlineData("2023/6/2", "20230602")]
    [InlineData("20230620", "20230620")]
    [InlineData("", "")]
    public void ParseDateInput_Normalizes(string raw, string expected) =>
        Assert.Equal(expected, Validators.ParseDateInput(raw));

    [Fact]
    public void AddWorkingDays_SkipsWeekends()
    {
        // 2026-08-11(周二) + 10 个工作日 → 2026-08-25(周二)
        Assert.Equal("20260825", Validators.AddWorkingDays("20260811", 10));
        Assert.Equal("", Validators.AddWorkingDays("bad", 5));
    }

    [Fact]
    public void TravelRange_ParsesAndValidates()
    {
        var (s, e) = Validators.ParseTravelRange("2026-8-1-2026-8-11");
        Assert.Equal("20260801", s);
        Assert.Equal("20260811", e);
        Assert.Equal("2026/08/01-2026/08/11", Validators.FormatTravelRange(s, e));
        Assert.True(Validators.ValidateTravelRange("2026/08/01-2026/08/11").Ok);
        Assert.False(Validators.ValidateTravelRange("2026/08/11-2026/08/01").Ok);  // 起晚于止
        Assert.False(Validators.ValidateTravelRange("").Ok);
    }

    [Fact]
    public void FormatTravelRange_CollapsesSameDay() =>
        Assert.Equal("2026/08/01", Validators.FormatTravelRange("20260801", "20260801"));

    [Fact]
    public void CertOverdue_NormalTripUses10WorkingDays()
    {
        // 回国 2026-08-11(周二) + 10 工作日 = 2026-08-25；26 日才算逾期
        Assert.False(Validators.IsCertOverdue("20260701", null, "normal", null, "20260811", null, "20260825"));
        Assert.True(Validators.IsCertOverdue("20260701", null, "normal", null, "20260811", null, "20260826"));
    }

    [Fact]
    public void CertOverdue_CancelledTripUses5WorkingDays()
    {
        // 取消日 2026-08-11(周二) + 5 工作日 = 2026-08-18
        Assert.Equal("20260818", Validators.CertOverdueDeadline("cancelled", "20260811", null, null));
    }

    [Fact]
    public void CertOverdue_ReturnedIsNeverOverdue() =>
        Assert.False(Validators.IsCertOverdue("20260701", "20260712", "normal", null, "20260702", null, "20261231"));

    [Fact]
    public void CertOverdue_NotCollectedIsNeverOverdue() =>
        Assert.False(Validators.IsCertOverdue(null, null, "normal", null, "20260101", null, "20261231"));
}

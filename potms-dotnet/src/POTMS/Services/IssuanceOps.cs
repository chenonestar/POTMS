using System.Data;
using Dapper;
using POTMS.Data;

namespace POTMS.Services;

/// <summary>证件领用的共享业务操作。</summary>
public static class IssuanceOps
{
    /// <summary>'01,02' → '因私护照、往来港澳通行证'</summary>
    /// <summary>列表筛选里「待核实」的取值。真实种类代码是 01/02/03，不会撞。</summary>
    public const string CertTypePending = "pending";

    /// <summary>把 "01,02" 转成「因私护照、往来港澳通行证」；空值转成「待核实」。
    ///
    /// <para>空值只可能来自历史回填里判不出种类的那批。打印件与日志上不能是个空格子——
    /// 看的人分不清是「没有证件」还是「漏填了」，写明待核实才是实情。</para>
    /// </summary>
    public static string TypesLabel(IDbConnection cn, string? codes)
    {
        var parts = (codes ?? "")
            .Split(',', StringSplitOptions.RemoveEmptyEntries)
            .Select(c => Helpers.GetDictValue(cn, "cert_type", c.Trim()))
            .ToList();
        return parts.Count == 0 ? "待核实" : string.Join("、", parts);
    }

    /// <summary>只有<b>没有签名</b>的记录允许改证件种类。
    ///
    /// <para>模块约束是「签名一经保存不可编辑」——签名签的就是「我领了这几样证件」，
    /// 事后改种类会让那个签名名不副实，那种记录只能作废重录。</para>
    ///
    /// <para>但历史回填行本来就没有签名（老库里根本没采集过），作废重录这条路也走不通：
    /// 新建领用默认强制手写签名，而历史记录压根没有签名可采。不给它们一个更正入口，
    /// 订正迁移标出来的「待核实」就成了永远填不上的死数据。</para>
    ///
    /// <para>判据用「无签名」而不是「备注是回填串」：放宽模式（POTMS_REQUIRE_SIGNATURE=0）
    /// 下手工登记的记录同样没有签名，同样没有会被推翻的凭证，一并适用。</para>
    /// </summary>
    public static bool CanFixCertTypes(CertIssuance row) =>
        row.SignImage is null || row.SignImage.Length == 0;

    /// <summary>把领用/归还日期回写到出行表（派生字段，本模块为唯一写入方）。
    ///
    /// 取该出行下**未作废**记录中最早的领用日期；仅当全部已归还时取最晚归还日期，
    /// 否则为空。若全部作废或无记录则清空，使逾期告警口径与领用记录始终一致。
    /// </summary>
    public static void SyncTravelDates(IDbConnection cn, string? travelId)
    {
        if (string.IsNullOrEmpty(travelId)) return;
        SyncTravelDates(cn, long.Parse(travelId));
    }

    public static void SyncTravelDates(IDbConnection cn, long? travelId)
    {
        if (travelId is null) return;
        var agg = cn.QueryFirstOrDefault(
            "SELECT MIN(issue_date) AS c, " +
            "       CASE WHEN COUNT(*) = SUM(CASE WHEN return_date IS NOT NULL AND return_date != '' " +
            "                                     THEN 1 ELSE 0 END) " +
            "            THEN MAX(return_date) ELSE NULL END AS r " +
            "FROM cert_issuance WHERE travel_id=@t AND status != 'voided'", new { t = travelId });

        string? collect = agg?.c as string;
        string? ret = agg?.r as string;
        cn.Execute("UPDATE travel_details SET passport_collect_date=@c, passport_return_date=@r WHERE id=@id",
            new
            {
                c = string.IsNullOrEmpty(collect) ? null : collect,
                r = string.IsNullOrEmpty(ret) ? null : ret,
                id = travelId,
            });
    }
}

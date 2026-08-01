using System.Data;
using Dapper;

namespace POTMS.Services;

/// <summary>证件领用的共享业务操作。</summary>
public static class IssuanceOps
{
    /// <summary>'01,02' → '因私护照、往来港澳通行证'</summary>
    public static string TypesLabel(IDbConnection cn, string? codes) =>
        string.Join("、", (codes ?? "")
            .Split(',', StringSplitOptions.RemoveEmptyEntries)
            .Select(c => Helpers.GetDictValue(cn, "cert_type", c.Trim())));

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

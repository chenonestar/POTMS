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

    /// <summary>把领用/归还日期与证件号码回写到出行表（派生字段，本模块为唯一写入方）。
    ///
    /// <para>日期：取该出行下<b>未作废</b>记录中最早的领用日期；仅当全部已归还时取最晚
    /// 归还日期，否则为空。若全部作废或无记录则清空，使逾期告警口径与领用记录始终一致。</para>
    ///
    /// <para>证件号码：一次申请一本证，所以该出行下所有未作废记录说的都是同一本；取
    /// 最后一条的号码。号码原先是出行表单上手填的，与领用记录各写各的，打印件上
    /// 「证件号码」和「证件领用日期」两个格子可能来自不同的证件。现在跟日期一样降级为
    /// 派生——有领用记录就以领用记录为准。</para>
    ///
    /// <para><b>不清空</b>号码：路径B（做证）没有领用记录，那一栏是系统里唯一的来源，
    /// 手填的值必须保留；领用记录全部作废时也保留，那仍是当时用的号码。</para>
    /// </summary>
    public static void SyncTravelDerived(IDbConnection cn, string? travelId)
    {
        if (string.IsNullOrEmpty(travelId)) return;
        SyncTravelDerived(cn, long.Parse(travelId));
    }

    public static void SyncTravelDerived(IDbConnection cn, long? travelId)
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

        var nos = cn.QueryFirstOrDefault<string>(
            "SELECT cert_nos FROM cert_issuance WHERE travel_id=@t AND status != 'voided' " +
            "  AND cert_nos IS NOT NULL AND cert_nos != '' ORDER BY id DESC LIMIT 1",
            new { t = travelId });
        if (!string.IsNullOrEmpty(nos))
            cn.Execute("UPDATE travel_details SET passport_no=@n WHERE id=@id",
                       new { n = nos, id = travelId });
    }

    /// <summary>该出行是否已有未作废的领用记录——有的话证件号码由领用记录派生，
    /// 出行表单上那一栏是只读的。</summary>
    public static bool TravelHasIssuance(IDbConnection cn, long? travelId) =>
        travelId is not null && cn.QueryFirstOrDefault<long?>(
            "SELECT 1 FROM cert_issuance WHERE travel_id=@t AND status != 'voided' LIMIT 1",
            new { t = travelId }) is not null;

    /// <summary>做证的出行记录中，新证已经进入证照台账的那些 id。
    ///
    /// <para>判据是「明细表上补录的证件号码，出现在该人证照台账的三个号码槽之一」。
    /// 台账登记时上交日期是必填的，所以「在台账里」等价于「已交回收缴」。号码没补录、
    /// 或补录了但台账里没有，都算还没交回。</para>
    ///
    /// <para>JOIN 而不是子查询取一条：一个人可能有多条证照记录（历史遗留），只要
    /// <b>任意一条</b>里出现了这个号码就算数。</para>
    /// </summary>
    public static HashSet<long> RegisteredCertTravelIds(IDbConnection cn) =>
        cn.Query<long>(
            "SELECT DISTINCT t.id FROM travel_details t " +
            "JOIN certificates c ON c.personnel_filing_id = t.personnel_filing_id " +
            "WHERE t.need_new_passport = '是' " +
            "  AND t.passport_no IS NOT NULL AND t.passport_no != '' " +
            "  AND t.passport_no IN (c.passport_no, c.hm_pass_no, c.tw_pass_no)").ToHashSet();

    /// <summary>可以办理领用的出国申请。
    ///
    /// <para>排除两类：已取消的行程（不会再出行，没有领用的理由），以及已有一条未归还
    /// 领用记录的申请（同一申请下不允许两本证同时在外——一次申请一本证）。
    /// 「领用 → 归还 → 再领用」仍然可以，因为已归还的记录不在排除之列。</para>
    /// </summary>
    public static IEnumerable<TravelDetail> EligibleTravels(IDbConnection cn) =>
        cn.Query<TravelDetail>(
            "SELECT t.id, t.name, t.unit, t.destination_passport, t.travel_dates, " +
            "       t.approval_date, t.need_new_passport " +
            "FROM travel_details t " +
            "WHERE COALESCE(t.trip_status, 'normal') != 'cancelled' " +
            "  AND NOT EXISTS (SELECT 1 FROM cert_issuance c " +
            "                  WHERE c.travel_id = t.id AND c.status = 'issued') " +
            "ORDER BY t.created_at DESC");
}

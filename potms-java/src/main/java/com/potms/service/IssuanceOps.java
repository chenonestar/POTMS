package com.potms.service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;

/** 证件领用的共用规则：证件种类映射与派生日期回写。 */
public final class IssuanceOps {

    private IssuanceOps() {}

    /** 证件种类代码 → certificates 表中对应的号码字段。 */
    public static final Map<String, String> CERT_NO_FIELD = Map.of(
            "01", "passport_no",
            "02", "hm_pass_no",
            "03", "tw_pass_no");

    /**
     * 列表筛选里表示「历史回填判不出种类」的伪代码。
     *
     * <p>不是字典值：这批记录的 cert_types 就是空串，只是需要一个能筛出它们的入口，
     * 否则这批待办没法收口。
     */
    public static final String CERT_TYPE_PENDING = "pending";

    /**
     * 该记录的证件种类可否人工更正。
     *
     * <p>判据只有一条：没有领用人签名。签名签的就是「我领了这几样」，改了就名不副实，
     * 那种情况只能作废后重新登记。历史回填行本来就没有签名，也无从重录（新建强制签名），
     * 只能就地更正。
     */
    public static boolean canFixCertTypes(Map<String, Object> row) {
        Object img = row.get("sign_image");
        return img == null || (img instanceof byte[] b && b.length == 0);
    }

    /** {@code "01,02"} → {@code "普通护照、往来港澳通行证"}；空串（待核实）显式标出。 */
    public static String typesLabel(JdbcTemplate jdbc, String codes) {
        if (codes == null || codes.isBlank()) {
            return "待核实";
        }
        List<String> out = new ArrayList<>();
        for (String c : codes.split(",")) {
            String code = c.trim();
            if (!code.isEmpty()) {
                out.add(dictValue(jdbc, code));
            }
        }
        return String.join("、", out);
    }

    private static String dictValue(JdbcTemplate jdbc, String code) {
        var v = jdbc.queryForList(
                "SELECT value FROM sys_dict WHERE category = 'cert_type' AND code = ?",
                String.class, code);
        return v.isEmpty() ? code : v.get(0);
    }

    /**
     * 把领用/归还日期与证件号码回写到出行表。本模块是这些派生字段的唯一写入方。
     *
     * <p>日期：取该出行下<b>未作废</b>记录中最早的领用日期；归还日期只有在所有未作废
     * 记录都已归还时才写入（取最晚），否则留空——否则「部分归还」会被误判为已还清，
     * 逾期告警就失真了。全部作废或无记录时一律清空。
     *
     * <p>证件号码：一次申请一本证，所以该出行下所有未作废记录说的都是同一本；取最后
     * 一条的号码。号码原先是出行表单上手填的，与领用记录各写各的，打印件上「证件号码」
     * 和「证件领用日期」两个格子可能来自不同的证件。现在跟日期一样降级为派生。
     *
     * <p><b>不清空</b>号码：路径B（做证）没有领用记录，那一栏是系统里唯一的来源，
     * 手填的值必须保留；领用记录全部作废时也保留，那仍是当时用的号码。
     */
    public static void syncTravelDerived(JdbcTemplate jdbc, Long travelId) {
        if (travelId == null) {
            return;
        }
        var rows = jdbc.queryForList(
                "SELECT MIN(issue_date) AS c, "
                + "       CASE WHEN COUNT(*) = SUM(CASE WHEN return_date IS NOT NULL "
                + "                                      AND return_date != '' THEN 1 ELSE 0 END) "
                + "            THEN MAX(return_date) ELSE NULL END AS r "
                + "FROM cert_issuance WHERE travel_id = ? AND status != 'voided'", travelId);
        Object collect = null;
        Object ret = null;
        if (!rows.isEmpty()) {
            collect = blankToNull(rows.get(0).get("c"));
            ret = blankToNull(rows.get(0).get("r"));
        }
        jdbc.update("UPDATE travel_details SET passport_collect_date=?, passport_return_date=? "
                + "WHERE id=?", collect, ret, travelId);

        var nos = jdbc.queryForList(
                "SELECT cert_nos FROM cert_issuance WHERE travel_id = ? AND status != 'voided' "
                + "  AND cert_nos IS NOT NULL AND cert_nos != '' ORDER BY id DESC LIMIT 1",
                String.class, travelId);
        if (!nos.isEmpty()) {
            jdbc.update("UPDATE travel_details SET passport_no=? WHERE id=?", nos.get(0), travelId);
        }
    }

    /**
     * 该出行是否已有未作废的领用记录——有的话证件号码由领用记录派生，
     * 出行表单上那一栏是只读的。
     */
    public static boolean travelHasIssuance(JdbcTemplate jdbc, Long travelId) {
        if (travelId == null) {
            return false;
        }
        return !jdbc.queryForList(
                "SELECT 1 FROM cert_issuance WHERE travel_id = ? AND status != 'voided' LIMIT 1",
                travelId).isEmpty();
    }

    /**
     * 做证的出行记录中，新证已经进入证照台账的那些 id。
     *
     * <p>判据是「明细表上补录的证件号码，出现在该人证照台账的三个号码槽之一」。台账
     * 登记时上交日期是必填的，所以「在台账里」等价于「已交回收缴」。号码没补录、或
     * 补录了但台账里没有，都算还没交回。
     *
     * <p>JOIN 而不是子查询取一条：一个人可能有多条证照记录（历史遗留），只要
     * <b>任意一条</b>里出现了这个号码就算数。
     */
    public static java.util.Set<Long> registeredCertTravelIds(JdbcTemplate jdbc) {
        return new java.util.HashSet<>(jdbc.queryForList(
                "SELECT DISTINCT t.id FROM travel_details t "
                + "JOIN certificates c ON c.personnel_filing_id = t.personnel_filing_id "
                + "WHERE t.need_new_passport = '是' "
                + "  AND t.passport_no IS NOT NULL AND t.passport_no != '' "
                + "  AND t.passport_no IN (c.passport_no, c.hm_pass_no, c.tw_pass_no)",
                Long.class));
    }

    /**
     * 可以办理领用的出国申请。
     *
     * <p>排除两类：已取消的行程（不会再出行，没有领用的理由），以及已有一条未归还领用
     * 记录的申请（同一申请下不允许两本证同时在外——一次申请一本证）。
     * 「领用 → 归还 → 再领用」仍然可以，因为已归还的记录不在排除之列。
     */
    public static List<Map<String, Object>> eligibleTravels(JdbcTemplate jdbc) {
        return jdbc.queryForList(
                "SELECT t.id, t.name, t.unit, t.destination_passport, t.travel_dates, "
                + "       t.approval_date, t.need_new_passport "
                + "FROM travel_details t "
                + "WHERE COALESCE(t.trip_status, 'normal') != 'cancelled' "
                + "  AND NOT EXISTS (SELECT 1 FROM cert_issuance c "
                + "                  WHERE c.travel_id = t.id AND c.status = 'issued') "
                + "ORDER BY t.created_at DESC");
    }

    private static Object blankToNull(Object o) {
        if (o == null) {
            return null;
        }
        String s = o.toString();
        return s.isEmpty() ? null : s;
    }
}

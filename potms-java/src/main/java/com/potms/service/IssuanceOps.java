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

    /** {@code "01,02"} → {@code "因私护照、往来港澳通行证"}。 */
    public static String typesLabel(JdbcTemplate jdbc, String codes) {
        if (codes == null || codes.isBlank()) {
            return "";
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
     * 把领用/归还日期回写到出行表。本模块是这两个派生字段的唯一写入方。
     *
     * <p>取该出行下**未作废**记录中最早的领用日期；归还日期只有在所有未作废记录
     * 都已归还时才写入（取最晚），否则留空——否则「部分归还」会被误判为已还清，
     * 逾期告警就失真了。全部作废或无记录时一律清空。
     */
    public static void syncTravelDates(JdbcTemplate jdbc, Long travelId) {
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
    }

    private static Object blankToNull(Object o) {
        if (o == null) {
            return null;
        }
        String s = o.toString();
        return s.isEmpty() ? null : s;
    }
}

package com.potms.service;

import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * 领用凭证的国密签章存取。
 *
 * <p>签章写在独立的 {@code cert_issuance_seal} 表，而不是往 {@code cert_issuance}
 * 加列——后者由 database.py 统一定义、五版共用，加列要牵动全部版本。
 */
@Component
public class SealStore {

    /**
     * 验章结论。
     *
     * @param legacy 该签章生成于「签章时间纳入载荷」之前，其 signedAt 不受签名保护。
     *               单独标出来，是因为把它跟新章混作「签章有效」会让人误以为
     *               那个时间也是可核验的。
     */
    public record Status(boolean present, boolean valid, String signedAt,
                         String certSubject, String source, boolean legacy) {
        public static final Status ABSENT = new Status(false, false, "", "", "", false);

        /** 页面展示用的一句话结论。 */
        public String label() {
            if (!present) {
                return "未签章";
            }
            if (!valid) {
                return "签章校验失败";
            }
            return legacy ? "签章有效（旧版，时间未受保护）" : "签章有效";
        }
    }

    private final Sm2Seal sm2;

    public SealStore(Sm2Seal sm2) {
        this.sm2 = sm2;
    }

    /**
     * 领用要素的规范化串——参与签章的业务字段。
     *
     * <p>字段选取原则：凡是「改了就等于换了一份凭证」的都要进去。
     */
    public static String facts(Map<String, Object> row, String kind) {
        return String.join("|",
                kind,
                s(row.get("holder_name")),
                s(row.get("id_number")),
                s(row.get("cert_types")),
                s(row.get("cert_nos")),
                s(row.get("issue_date")),
                s(row.get("return_date")),
                s(row.get("issuer")),
                s(row.get("travel_id")));
    }

    /** 对某条领用记录的领用（issue）或归还（return）环节签章并入库。 */
    public void seal(JdbcTemplate jdbc, long issuanceId, String kind,
                     byte[] signImage, String signMeta, Map<String, Object> row) {
        var s = sm2.sign(signImage, signMeta, facts(row, kind));
        jdbc.update("INSERT OR REPLACE INTO cert_issuance_seal "
                + "(issuance_id, kind, payload_hash, signature, cert_subject, cert_serial, "
                + " cert_source, signed_at) VALUES (?,?,?,?,?,?,?,?)",
                issuanceId, kind, s.payloadHash(), s.signatureHex(),
                s.certSubject(), s.certSerial(), s.source().name(), s.signedAt());
    }

    /** 取出签章并当场验一遍：库里的图/笔迹/要素被改过就会验不过。 */
    public Status verify(JdbcTemplate jdbc, long issuanceId, String kind,
                         byte[] signImage, String signMeta, Map<String, Object> row) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT * FROM cert_issuance_seal WHERE issuance_id = ? AND kind = ?",
                issuanceId, kind);
        if (rows.isEmpty()) {
            return Status.ABSENT;
        }
        var seal = rows.get(0);
        String signedAt = s(seal.get("signed_at"));
        String signature = s(seal.get("signature"));
        String facts = facts(row, kind);
        boolean ok;
        boolean legacy = false;
        try {
            ok = sm2.verify(signImage, signMeta, facts, signature, signedAt);
            if (!ok) {
                // 先按新载荷验，不过再退回旧载荷试一次。顺序不能反：
                // 反过来的话，新章里被篡改的时间会先撞上旧路而被放行。
                legacy = sm2.verifyLegacy(signImage, signMeta, facts, signature);
                ok = legacy;
            }
        } catch (RuntimeException e) {
            ok = false;   // 证书不可用时按「验不过」处理，不掩盖问题
        }
        return new Status(true, ok, signedAt,
                s(seal.get("cert_subject")), s(seal.get("cert_source")), legacy);
    }

    private static String s(Object o) {
        return o == null ? "" : o.toString();
    }
}

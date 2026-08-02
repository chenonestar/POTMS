package com.potms.util;

import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.ResolverStyle;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** 校验工具：身份证、日期、必填字段 — 对应 Python 版 utils/validators.py。 */
public final class Validators {

    private Validators() {}

    /** 校验结果：是否通过 + 错误信息。 */
    public record Check(boolean ok, String message) {
        public static final Check PASS = new Check(true, "");

        public static Check fail(String msg) {
            return new Check(false, msg);
        }
    }

    /** 字段名 + 中文标签，用于批量必填 / 日期校验。 */
    public record Field(String name, String label) {}

    // 身份证校验位权重
    private static final int[] ID_WEIGHTS = {7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2};
    private static final String ID_CHECK = "10X98765432";

    /** STRICT 解析：拒绝 20260230 这类不存在的日期（SMART 会静默改成 0228）。 */
    private static final DateTimeFormatter YMD =
            DateTimeFormatter.ofPattern("uuuuMMdd").withResolverStyle(ResolverStyle.STRICT);

    // ------------------------------------------------------------------
    // 身份证
    // ------------------------------------------------------------------

    public static Check validateIdNumber(String id) {
        if (id == null || id.length() != 18) {
            return Check.fail("身份证号须为18位。");
        }
        for (int i = 0; i < 17; i++) {
            if (!Character.isDigit(id.charAt(i))) {
                return Check.fail("身份证号前17位须为数字。");
            }
        }
        int total = 0;
        for (int i = 0; i < 17; i++) {
            total += (id.charAt(i) - '0') * ID_WEIGHTS[i];
        }
        char expected = ID_CHECK.charAt(total % 11);
        if (Character.toUpperCase(id.charAt(17)) != expected) {
            return Check.fail("身份证校验位不正确，应为 " + expected + "。");
        }
        if (!parseYmd(id.substring(6, 14))) {
            return Check.fail("身份证号中出生日期不合法。");
        }
        return Check.PASS;
    }

    public static Check validateBirthDateMatch(String id, String birthDate) {
        String idBirth = id.substring(6, 14);
        if (!idBirth.equals(birthDate)) {
            return Check.fail("出生日期与身份证号不一致（身份证中为 " + idBirth + "）。");
        }
        return Check.PASS;
    }

    /**
     * 校验性别与身份证第 17 位（顺序码奇偶）是否一致：奇→男，偶→女。
     *
     * <p>号码本身不合规时直接放行，由 validateIdNumber 报错，避免重复提示。
     */
    public static Check validateGenderMatch(String id, String gender) {
        if (id == null || id.length() != 18 || !Character.isDigit(id.charAt(16))) {
            return Check.PASS;
        }
        String expected = (id.charAt(16) - '0') % 2 == 1 ? "男" : "女";
        if (gender != null && !gender.isEmpty() && !gender.equals(expected)) {
            return Check.fail("性别与身份证号不一致（身份证中为 " + expected + "）。");
        }
        return Check.PASS;
    }

    /** 身份证综合校验：校验位通过后，再比对出生日期与性别（字段存在且非空时）。 */
    public static List<String> checkIdentity(Map<String, String> data, String idField,
                                             String birthField, String genderField) {
        List<String> errors = new ArrayList<>();
        String id = data.get(idField);
        if (id == null || id.isEmpty()) {
            return errors;
        }
        Check c = validateIdNumber(id);
        if (!c.ok()) {
            errors.add("身份证号: " + c.message());
            return errors;
        }
        String birth = birthField == null ? null : data.get(birthField);
        if (birth != null && !birth.isEmpty()) {
            Check c2 = validateBirthDateMatch(id, birth);
            if (!c2.ok()) {
                errors.add(c2.message());
            }
        }
        String gender = genderField == null ? null : data.get(genderField);
        if (gender != null && !gender.isEmpty()) {
            Check c3 = validateGenderMatch(id, gender);
            if (!c3.ok()) {
                errors.add(c3.message());
            }
        }
        return errors;
    }

    public static List<String> checkIdentity(Map<String, String> data) {
        return checkIdentity(data, "id_number", "birth_date", "gender");
    }

    // ------------------------------------------------------------------
    // 日期与必填
    // ------------------------------------------------------------------

    public static Check validateDateFormat(String s) {
        if (s == null || s.length() != 8) {
            return Check.fail("日期格式须为 YYYYMMDD（8位数字）。");
        }
        for (int i = 0; i < 8; i++) {
            if (!Character.isDigit(s.charAt(i))) {
                return Check.fail("日期须为纯数字。");
            }
        }
        return parseYmd(s) ? Check.PASS : Check.fail("日期不合法。");
    }

    /** 清洗用户输入的日期，支持 2023-06-20 / 2023/06/20 / 20230620，返回 YYYYMMDD。 */
    public static String parseDateInput(String raw) {
        if (raw == null) {
            return "";
        }
        String s = raw.trim();
        if (s.isEmpty()) {
            return "";
        }
        if (s.length() == 8 && s.chars().allMatch(Character::isDigit)) {
            return s;
        }
        for (String sep : new String[] {"-", "/", "."}) {
            if (s.contains(sep)) {
                String[] parts = s.split(java.util.regex.Pattern.quote(sep));
                if (parts.length == 3) {
                    return parts[0] + pad(parts[1]) + pad(parts[2]);
                }
            }
        }
        return s;
    }

    public static List<String> checkRequired(Map<String, String> data, List<Field> fields) {
        List<String> errors = new ArrayList<>();
        for (Field f : fields) {
            String v = data.get(f.name());
            if (v == null || v.isEmpty()) {
                errors.add(f.label() + " 为必填项。");
            }
        }
        return errors;
    }

    public static List<String> checkDates(Map<String, String> data, List<Field> fields) {
        List<String> errors = new ArrayList<>();
        for (Field f : fields) {
            String v = data.get(f.name());
            if (v != null && !v.isEmpty()) {
                Check c = validateDateFormat(v);
                if (!c.ok()) {
                    errors.add(f.label() + ": " + c.message());
                }
            }
        }
        return errors;
    }

    /** 是否为中共党员/预备党员（需要填写入党日期）。 */
    public static boolean isPartyMember(String politicalStatus) {
        return "中共党员".equals(politicalStatus) || "中共预备党员".equals(politicalStatus);
    }

    // ------------------------------------------------------------------
    // 计划出行日期
    // ------------------------------------------------------------------

    public static Check validateTravelRange(String text) {
        if (text == null || text.isBlank()) {
            return Check.fail("计划出行日期不能为空。");
        }
        var r = TravelDates.parse(text);
        if (r.isEmpty()) {
            return Check.fail("计划出行日期格式无法识别，请填「起始-结束」，如 2026-8-1-2026-8-11。");
        }
        Check cs = validateDateFormat(r.start());
        if (!cs.ok()) {
            return Check.fail("起始日期不合法（解析为 " + r.start() + "）：" + cs.message());
        }
        Check ce = validateDateFormat(r.end());
        if (!ce.ok()) {
            return Check.fail("结束日期不合法（解析为 " + r.end() + "）：" + ce.message());
        }
        if (r.start().compareTo(r.end()) > 0) {
            return Check.fail("起始日期（" + r.start() + "）不应晚于结束日期（" + r.end() + "）。");
        }
        return Check.PASS;
    }

    // ------------------------------------------------------------------
    // 证件归还到期与逾期
    // ------------------------------------------------------------------

    /**
     * 以 startYmd 为第 0 天，向后顺延 n 个工作日（仅跳过周六/周日，不含法定节假日）。
     *
     * <p>语义：10 个工作日内归还，即到期日为「回国日之后第 10 个工作日」；
     * 超过到期日（严格大于）才算逾期，到期日当天仍算未逾期。
     */
    public static String addWorkingDays(String startYmd, int n) {
        if (startYmd == null || startYmd.length() != 8
                || !startYmd.chars().allMatch(Character::isDigit)) {
            return "";
        }
        LocalDate d;
        try {
            d = LocalDate.parse(startYmd, YMD);
        } catch (DateTimeParseException e) {
            return "";
        }
        int counted = 0;
        while (counted < n) {
            d = d.plusDays(1);
            if (d.getDayOfWeek() != DayOfWeek.SATURDAY && d.getDayOfWeek() != DayOfWeek.SUNDAY) {
                counted++;
            }
        }
        return d.format(YMD);
    }

    /**
     * 某条出国明细的证件归还到期日（YYYYMMDD）。
     *
     * <ul>
     *   <li>正常行程：以「实际回国日期」优先，否则回退「计划出行结束日」，顺延 10 个工作日
     *   <li>取消行程：以「取消日期」为基准，顺延 5 个工作日
     * </ul>
     */
    public static String certOverdueDeadline(Map<String, Object> row) {
        String status = str(row.get("trip_status"));
        if (status.isEmpty()) {
            status = "normal";
        }
        if ("cancelled".equals(status)) {
            return addWorkingDays(str(row.get("cancel_date")), 5);
        }
        String base = str(row.get("actual_return_date"));
        if (base.isEmpty()) {
            base = str(row.get("travel_end"));
        }
        return addWorkingDays(base, 10);
    }

    /**
     * 是否「证件逾期未还」：已领用（collect 非空）+ 未归还（return 空）+ 已过到期日。
     *
     * @param today YYYYMMDD
     */
    public static boolean isCertOverdue(Map<String, Object> row, String today) {
        if (str(row.get("passport_collect_date")).isEmpty()) {
            return false;
        }
        if (!str(row.get("passport_return_date")).isEmpty()) {
            return false;   // 已归还
        }
        String deadline = certOverdueDeadline(row);
        return !deadline.isEmpty() && today.compareTo(deadline) > 0;
    }

    // ------------------------------------------------------------------

    private static boolean parseYmd(String s) {
        try {
            LocalDate.parse(s, YMD);
            return true;
        } catch (DateTimeParseException e) {
            return false;
        }
    }

    private static String pad(String s) {
        return s.length() == 1 ? "0" + s : s;
    }

    private static String str(Object o) {
        return o == null ? "" : o.toString();
    }
}

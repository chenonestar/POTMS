package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.potms.util.TravelDates;
import com.potms.util.Validators;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

/** 校验器 — 与 Python 版 utils/validators.py 逐条对齐。 */
class ValidatorsTest {

    // 按国标校验位算法构造的合法身份证号（末位顺序码 3 为奇数 → 男）
    private static final String VALID_ID = makeValidId("19900101", "213");

    private static String makeValidId(String birth, String seq) {
        String body = "110101" + birth + seq;
        int[] w = {7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2};
        int s = 0;
        for (int i = 0; i < 17; i++) {
            s += (body.charAt(i) - '0') * w[i];
        }
        return body + "10X98765432".charAt(s % 11);
    }

    @Test
    @DisplayName("身份证：合法号码通过")
    void validId() {
        assertTrue(Validators.validateIdNumber(VALID_ID).ok());
    }

    @Test
    @DisplayName("身份证：位数 / 非数字 / 校验位 / 出生日期各自报错")
    void invalidId() {
        assertEquals("身份证号须为18位。", Validators.validateIdNumber("11010119900101").message());
        assertEquals("身份证号前17位须为数字。",
                Validators.validateIdNumber("11010119900101X213").message());
        // 篡改末位校验码
        char wrong = VALID_ID.charAt(17) == '1' ? '2' : '1';
        assertTrue(Validators.validateIdNumber(VALID_ID.substring(0, 17) + wrong)
                .message().startsWith("身份证校验位不正确"));
        // 出生日期 2 月 30 日：STRICT 解析必须拒绝，而非静默改成 2 月 28 日
        String badBirth = makeValidId("19900230", "213");
        assertEquals("身份证号中出生日期不合法。", Validators.validateIdNumber(badBirth).message());
    }

    @Test
    @DisplayName("身份证：出生日期与性别一致性")
    void identityCrossCheck() {
        Map<String, String> data = new HashMap<>();
        data.put("id_number", VALID_ID);
        data.put("birth_date", "19900101");
        data.put("gender", "男");
        assertTrue(Validators.checkIdentity(data).isEmpty());

        data.put("birth_date", "19900102");
        assertTrue(Validators.checkIdentity(data).get(0).contains("出生日期与身份证号不一致"));

        data.put("birth_date", "19900101");
        data.put("gender", "女");
        assertTrue(Validators.checkIdentity(data).get(0).contains("性别与身份证号不一致"));
    }

    @Test
    @DisplayName("身份证：号码为空时不报错（非必填场景）")
    void emptyIdSkipped() {
        assertTrue(Validators.checkIdentity(Map.of("id_number", "")).isEmpty());
    }

    @ParameterizedTest
    @DisplayName("日期格式：YYYYMMDD，拒绝不存在的日期")
    @CsvSource({
        "20260101, true",
        "20260229, false",   // 2026 非闰年
        "20240229, true",    // 2024 是闰年
        "20261301, false",
        "2026010,  false",
        "2026010a, false",
    })
    void dateFormat(String input, boolean expected) {
        assertEquals(expected, Validators.validateDateFormat(input).ok());
    }

    @ParameterizedTest
    @DisplayName("日期清洗：多种分隔符归一为 YYYYMMDD")
    @CsvSource({
        "2023-06-20, 20230620",
        "2023/6/20,  20230620",
        "2023.6.5,   20230605",
        "20230620,   20230620",
        "'',         ''",
    })
    void parseDateInput(String raw, String expected) {
        assertEquals(expected, Validators.parseDateInput(raw));
    }

    @ParameterizedTest
    @DisplayName("出行日期区间：解析起止")
    @CsvSource({
        "'2023-6-20-2023-6-26', 20230620, 20230626",
        "'20230620-20230626',   20230620, 20230626",
        "'2023/06/20',          20230620, 20230620",
        "'无法识别',              '',       ''",
    })
    void travelRangeParse(String text, String start, String end) {
        var r = TravelDates.parse(text);
        assertEquals(start, r.start());
        assertEquals(end, r.end());
    }

    @Test
    @DisplayName("出行日期区间：格式化与校验")
    void travelRangeFormatAndValidate() {
        assertEquals("2023/06/20-2023/06/26", TravelDates.format("20230620", "20230626"));
        assertEquals("2023/06/20", TravelDates.format("20230620", "20230620"));
        assertEquals("", TravelDates.format("", ""));

        assertTrue(Validators.validateTravelRange("2026-8-1-2026-8-11").ok());
        assertEquals("计划出行日期不能为空。", Validators.validateTravelRange("  ").message());
        assertTrue(Validators.validateTravelRange("2026-8-11-2026-8-1")
                .message().contains("不应晚于结束日期"));
    }

    @Test
    @DisplayName("工作日顺延：跳过周六周日")
    void workingDays() {
        // 2026-08-03 是周一，+5 个工作日 → 08-10（周一）
        assertEquals("20260810", Validators.addWorkingDays("20260803", 5));
        // 2026-08-07 是周五，+1 个工作日 → 08-10（周一），跳过周末
        assertEquals("20260810", Validators.addWorkingDays("20260807", 1));
        assertEquals("", Validators.addWorkingDays("bad", 5));
        assertEquals("", Validators.addWorkingDays("", 10));
    }

    @Test
    @DisplayName("证件逾期：正常行程按实际回国日 +10 工作日")
    void overdueNormal() {
        Map<String, Object> row = new HashMap<>();
        row.put("trip_status", "normal");
        row.put("actual_return_date", "20260803");
        row.put("passport_collect_date", "20260701");
        row.put("passport_return_date", null);

        String deadline = Validators.certOverdueDeadline(row);
        assertEquals("20260817", deadline);
        assertFalse(Validators.isCertOverdue(row, deadline), "到期日当天不算逾期");
        assertTrue(Validators.isCertOverdue(row, "20260818"));
    }

    @Test
    @DisplayName("证件逾期：取消行程按取消日 +5 工作日")
    void overdueCancelled() {
        Map<String, Object> row = new HashMap<>();
        row.put("trip_status", "cancelled");
        row.put("cancel_date", "20260803");
        row.put("passport_collect_date", "20260701");
        assertEquals("20260810", Validators.certOverdueDeadline(row));
    }

    @Test
    @DisplayName("证件逾期：未领用或已归还一律不算逾期")
    void overdueGuards() {
        Map<String, Object> notCollected = new HashMap<>();
        notCollected.put("travel_end", "20200101");
        assertFalse(Validators.isCertOverdue(notCollected, "20260802"));

        Map<String, Object> returned = new HashMap<>();
        returned.put("passport_collect_date", "20200101");
        returned.put("passport_return_date", "20200201");
        returned.put("travel_end", "20200110");
        assertFalse(Validators.isCertOverdue(returned, "20260802"));
    }

    @Test
    @DisplayName("必填与日期批量校验")
    void bulkChecks() {
        var fields = List.of(new Validators.Field("name", "姓名"),
                new Validators.Field("unit", "单位"));
        assertEquals(List.of("单位 为必填项。"),
                Validators.checkRequired(Map.of("name", "张三", "unit", ""), fields));

        var dateFields = List.of(new Validators.Field("birth_date", "出生日期"));
        assertTrue(Validators.checkDates(Map.of("birth_date", "20261301"), dateFields)
                .get(0).startsWith("出生日期: "));
        assertTrue(Validators.checkDates(Map.of("birth_date", ""), dateFields).isEmpty());
    }

    @Test
    @DisplayName("党员判定")
    void partyMember() {
        assertTrue(Validators.isPartyMember("中共党员"));
        assertTrue(Validators.isPartyMember("中共预备党员"));
        assertFalse(Validators.isPartyMember("群众"));
        assertFalse(Validators.isPartyMember(null));
    }
}

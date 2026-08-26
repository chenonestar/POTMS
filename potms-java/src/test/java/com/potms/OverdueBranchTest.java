package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 出国明细列表的「证件逾期未还」分支。
 *
 * <p>五版里这个分支从来没有任何用例覆盖过。Go 版因此带着一个到 2026-08-26 才引爆的
 * 故障：gonja 索引不了整数键的 map，模板里 {@code deadlines[row.id]} 一旦真有人逾期
 * 就渲染失败、整页 500——之前没暴露，只是因为测试数据还没跨过应还日期。Rust 版同一处
 * 更隐蔽：minijinja 查不到键时静默渲染成空，页面上是「应还: )」。
 *
 * <p>本版用的是 {@code Map<Long,String>} 配 {@code getOrDefault}，类型对得上，理应没
 * 问题——但「理应」不算数，补上用例把它钉住。
 *
 * <p>造数刻意用<b>相对今天</b>的日期，让记录永远处于逾期状态，不依赖跑在哪一天。
 * 逾期记录没法用 HTTP 造（表单会校验日期、还要传附件），所以直接写 data.db。
 */
class OverdueBranchTest {

    private static PageSmokeTest.AppUnderTest app;

    @BeforeAll
    static void start() throws Exception {
        app = PageSmokeTest.AppUnderTest.start(5794, true);
        seedOverdue();
    }

    @AfterAll
    static void stop() {
        if (app != null) {
            app.stop();
        }
    }

    private static String ymdDaysAgo(int n) {
        return LocalDate.now().minusDays(n).format(DateTimeFormatter.ofPattern("yyyyMMdd"));
    }

    /** 造一条「早就该交回却没交回」的出行记录：回国 90 天远超 10 个工作日的时限。 */
    private static void seedOverdue() throws Exception {
        String ago = ymdDaysAgo(90);
        String url = "jdbc:sqlite:" + app.dataDir().resolve("data.db");
        try (Connection cn = DriverManager.getConnection(url);
                PreparedStatement ps = cn.prepareStatement(
                        "INSERT INTO travel_details (id, personnel_filing_id, unit, department,"
                        + " name, position, id_number, destination_passport, category,"
                        + " travel_dates, travel_start, travel_end, need_new_passport,"
                        + " actual_return_date, passport_collect_date, operator)"
                        + " VALUES (900, 1, '总部', '办公室', '逾期某', '工程师',"
                        + " '110101199001012133', '德国', '因私', ?, ?, ?, '否', ?, ?, 'admin')")) {
            ps.setString(1, ago + "-" + ago);
            ps.setString(2, ago);
            ps.setString(3, ago);
            ps.setString(4, ago);
            ps.setString(5, ymdDaysAgo(120));
            ps.executeUpdate();
        }
    }

    @Test
    @DisplayName("出国明细列表渲染逾期分支，且应还到期日不为空")
    void travelListRendersOverdueBranch() throws Exception {
        var res = app.get("/travel");
        assertEquals(200, res.statusCode(), "出国明细列表返回 " + res.statusCode());
        String body = res.body();
        assertTrue(body.contains("逾期"), "页面上没有逾期提示");
        assertTrue(body.contains("逾期某"), "逾期提示里没有列出该人员");

        // 「应还」两个字在模板里是死的，光查它不够——必须确认后面真跟着日期。
        // 那正是 Go / Rust 两版失手的地方：字在、值是空的。
        int i = body.indexOf("应还");
        assertTrue(i >= 0, "页面上没有「应还」字样");
        String after = body.substring(i + 2).replaceFirst("^[\\s:：]+", "");
        assertTrue(after.length() >= 8 && after.substring(0, 8).matches("\\d{8}"),
                "应还到期日为空，实际渲染：「应还"
                        + after.substring(0, Math.min(40, after.length())) + "」");
    }

    @Test
    @DisplayName("按逾期筛选能筛出该记录")
    void overdueFilterFindsIt() throws Exception {
        var res = app.get("/travel?passport_status=overdue");
        assertEquals(200, res.statusCode());
        assertTrue(res.body().contains("逾期某"), "按逾期筛选没有筛出逾期记录");
    }
}

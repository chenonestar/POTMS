package com.potms;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.potms.web.LogsController;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 操作日志快照的解析，口径与 Python 版 {@code _compute_changes} 一致。
 *
 * <p>三型的区别不是显示细节：改动有前后两面，列 diff；新建和删除只有一面，
 * 列的是当时那条记录的全量内容。当初 Java 版对三型一视同仁地走 diff，
 * 删除记录展开后只剩「（空） → 值」这种半截话。
 */
class LogChangesTest {

    @Test
    @DisplayName("改动：只列真正变了的字段")
    void update() {
        var cs = LogsController.computeChanges(
                "{\"before\":{\"name\":\"旧名\",\"sort_order\":\"1\"},"
                + "\"after\":{\"name\":\"新名\",\"sort_order\":\"1\"}}");
        assertEquals("update", cs.type());
        assertTrue(cs.isUpdate());
        assertEquals(1, cs.items().size(), "没变的字段不该出现：" + cs.items());
        assertEquals("旧名", cs.items().get(0).before());
        assertEquals("新名", cs.items().get(0).after());
    }

    @Test
    @DisplayName("新建：列新建后的全量内容，空字段不占版面")
    void create() {
        var cs = LogsController.computeChanges(
                "{\"after\":{\"name\":\"甲单位\",\"remarks\":\"\",\"sort_order\":\"3\"}}");
        assertEquals("create", cs.type());
        assertEquals("新建内容", cs.heading());
        assertEquals(2, cs.items().size(), "空字段应被略去：" + cs.items());
        assertEquals("甲单位", cs.items().get(0).after());
    }

    @Test
    @DisplayName("删除：列删除前的全量内容")
    void delete() {
        var cs = LogsController.computeChanges("{\"before\":{\"name\":\"乙单位\"}}");
        assertEquals("delete", cs.type());
        assertEquals("删除前内容", cs.heading());
        assertEquals("乙单位", cs.items().get(0).before());
    }

    @Test
    @DisplayName("空快照与损坏快照都不许把日志页搞挂")
    void malformed() {
        assertTrue(LogsController.computeChanges(null).isEmpty());
        assertTrue(LogsController.computeChanges("").isEmpty());
        assertTrue(LogsController.computeChanges("{ 这不是 JSON").isEmpty());
        assertTrue(LogsController.computeChanges("{\"before\":{},\"after\":{}}").isEmpty());
    }
}

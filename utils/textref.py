"""按「文字」引用的配置项：使用量统计、改名同步、删除守卫。

sys_org / sys_dict / sys_submit_unit 这三张配置表都**不是被外键引用的**。业务表里
存的是当时那个名字的文字本身——`certificates.unit = '总部'`、
`personnel_filing.political_status = '群众'`、`decontrol_filing.submit_unit_name =
'某某国资委'`。这是有意的：单据一旦开出，上面印的单位名就该定格在开单那天，
后来单位改了名，历史单据不该跟着变。

代价是配置表这一侧完全不知道自己被谁用着，于是有两个洞：

- **删除**：把「技术部」从组织树上删掉，几百条历史记录里的「技术部」原地变成
  一个下拉里再也选不到的孤儿值——按部门筛选选不出来，导入校验也认不了。
- **改名**：「技术部」改叫「工程技术部」之后，新数据用新名、老数据用旧名，
  同一个部门在统计里裂成两个，两边都不全。

所以这两件事都不能默认放行：删除要先报使用量，改名要问清楚「历史数据跟不跟着改」。
跟着改属于批量重写历史，走强制备份 + 一条操作日志的路子（同第 1 批经办人回填）。

本模块只提供口径与执行，「怎么问」交给各自的蓝图——三处的措辞和确认位置不一样，
但判据和写法必须是同一套，否则迟早漂移。
"""
from __future__ import annotations

import sqlite3
from typing import NamedTuple

from database import get_db


class TextRef(NamedTuple):
    """一处按文字引用配置项的地方。"""
    table: str
    column: str
    label: str      # 报给用户看的说法，例如「证照台账·工作单位」


# 组织名（单位 / 部门）出现的所有位置。
# 单位名与部门名共用同一批列：一个节点是单位还是部门只由它在树上的层级决定，
# 而业务表里存的就是一个名字，分不出来也不需要分——文字对上了就是引用。
ORG_REFS = (
    TextRef("personnel_info", "unit", "人员信息·单位"),
    TextRef("personnel_info", "department", "人员信息·部门"),
    TextRef("personnel_filing", "work_unit", "备案人员·工作单位"),
    TextRef("certificates", "unit", "证照台账·单位"),
    TextRef("certificates", "department", "证照台账·部门"),
    TextRef("travel_details", "unit", "出国申请·单位"),
    TextRef("travel_details", "department", "出国申请·部门"),
    TextRef("decontrol_filing", "work_unit", "撤控备案·工作单位"),
)


def count_refs(refs, value: str) -> list[tuple[TextRef, int]]:
    """逐处统计 value 被引用了多少条，只返回大于 0 的。

    表可能不存在（极旧的库、迁移中途），缺表当作 0——统计不到不该让整个页面挂掉。
    """
    db = get_db()
    out = []
    for ref in refs:
        try:
            n = db.execute(
                f"SELECT COUNT(*) FROM {ref.table} WHERE {ref.column} = ?", (value,)
            ).fetchone()[0]
        except sqlite3.OperationalError:
            continue
        if n:
            out.append((ref, n))
    return out


def total_refs(refs, value: str) -> int:
    return sum(n for _, n in count_refs(refs, value))


def describe_refs(counts: list[tuple[TextRef, int]]) -> str:
    """把统计结果拼成一句人话：「证照台账·单位 3 条、出国申请·单位 12 条」。"""
    return "、".join(f"{ref.label} {n} 条" for ref, n in counts)


def sync_refs(refs, old: str, new: str) -> int:
    """把所有引用处的 old 就地改成 new，返回改动条数。调用方负责备份与日志。"""
    db = get_db()
    changed = 0
    for ref in refs:
        try:
            cur = db.execute(
                f"UPDATE {ref.table} SET {ref.column} = ? WHERE {ref.column} = ?",
                (new, old),
            )
        except sqlite3.OperationalError:
            continue
        changed += cur.rowcount
    db.commit()
    return changed


def backup_before_bulk_edit(tag: str) -> tuple[str | None, str | None]:
    """批量重写历史前存一份改前快照，返回 (文件名, 错误信息)，两者恰有一个为 None。

    改名同步是不可逆的批量写入：几百条历史记录同时被改掉，改错了没有 undo。
    备份失败就别动数据——这是第 1 批经办人回填定下的规矩，三处改名同步照办。

    用的是独立的带时间戳快照（backup/before_<tag>_YYYYMMDD_HHMMSS.db）而不是
    每日备份：同一天做两次改名同步，两份改前快照都要留得住，否则第二次的备份会
    盖掉第一次改之前的那一份，第一次改错了就再也退不回去了。
    """
    from utils.backup import snapshot_before_change
    try:
        return snapshot_before_change(tag), None
    except Exception as exc:           # noqa: BLE001 - 备份失败就别动数据
        return None, f"自动备份失败（{exc}），已中止同步。请手动备份 data.db 后重试。"

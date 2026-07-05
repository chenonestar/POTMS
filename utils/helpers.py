"""辅助函数：复姓识别、户口所在地映射、日志记录"""
import re
import sqlite3
from typing import Any, Optional, TypedDict

from flask import request

from database import get_db


class PageResult(TypedDict):
    """paginate() 的返回结构，便于 IDE 智能提示与静态检查。"""
    rows: list[sqlite3.Row]
    page: int
    total: int
    pages: int
    has_prev: bool
    has_next: bool
    per_page: int

# 常见复姓列表
_COMPOUND_SURNAMES = [
    "欧阳", "司马", "上官", "诸葛", "令狐", "慕容", "独孤", "拓跋",
    "尉迟", "呼延", "端木", "皇甫", "东方", "南宫", "夏侯", "宇文",
    "长孙", "公孙", "闾丘", "亓官", "司寇", "巫马", "公西", "壤驷",
    "乐正", "公良", "季孙", "仲孙", "宰父", "谷梁", "段干", "百里",
    "东郭", "南门", "羊舌", "微生", "梁丘", "左丘", "西门", "第五",
]


def detect_surname_split(full_name: str) -> tuple[str, str]:
    """
    尝试将完整姓名拆分为 (姓, 名)。
    支持复姓识别。
    """
    if not full_name or len(full_name) < 2:
        return (full_name or "", "")
    if full_name[:2] in _COMPOUND_SURNAMES:
        return (full_name[:2], full_name[2:])
    return (full_name[0], full_name[1:])


def normalize_residence(raw: str) -> str:
    """
    规范化户口所在地：
    - 省份去"省"字
    - 江东区、鄞县 → 鄞州区
    """
    raw = raw.strip()
    # 去省字
    if "省" in raw:
        raw = raw.replace("省", "")
    # 江东区 → 浙江宁波市鄞州区
    raw = raw.replace("江东区", "鄞州区")
    raw = raw.replace("鄞县", "鄞州区")
    return raw


def log_action(action: str, target_type: str, target_id: Optional[int] = None,
               detail: Optional[str] = None, before: Optional[dict] = None,
               after: Optional[dict] = None) -> None:
    """写入操作日志。before/after 为变更前后的数据快照（可选），序列化为 JSON 存入 snapshot。"""
    import json
    snapshot = None
    if before is not None or after is not None:
        snapshot = json.dumps(
            {"before": _clean_snapshot(before), "after": _clean_snapshot(after)},
            ensure_ascii=False, default=str,
        )
    db = get_db()
    db.execute(
        "INSERT INTO operation_logs (operator, action, target_type, target_id, detail, ip_address, snapshot) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            _operator_name(),
            action,
            target_type,
            target_id,
            detail,
            request.remote_addr,
            snapshot,
        ),
    )
    db.commit()


# 快照中忽略的字段（时间戳等无意义变更）
_SNAPSHOT_SKIP = {"created_at", "updated_at"}


def _clean_snapshot(data: Any) -> Optional[dict]:
    """将 sqlite Row / dict 转为纯 dict，过滤时间戳字段"""
    if data is None:
        return None
    d = dict(data)
    return {k: v for k, v in d.items() if k not in _SNAPSHOT_SKIP}


# row_snapshot 允许查询的表白名单（防御性：杜绝动态表名注入的可能）
_SNAPSHOT_TABLES = frozenset({
    "personnel_info", "personnel_filing", "certificates", "travel_details",
    "decontrol_filing", "sys_dict", "sys_org", "sys_submit_unit",
})


def row_snapshot(table: str, row_id: int) -> Optional[dict]:
    """读取指定表某行的当前快照（dict），不存在返回 None。

    表名经白名单校验后才拼入 SQL，杜绝动态表名注入。
    """
    if table not in _SNAPSHOT_TABLES:
        raise ValueError(f"row_snapshot: 不允许的表名 {table!r}")
    db = get_db()
    row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return dict(row) if row else None


def _operator_name() -> str:
    from flask import session
    return session.get("username", "unknown")


def get_dict_options(category: str) -> list[dict]:
    """获取某类数据字典选项"""
    db = get_db()
    rows = db.execute(
        "SELECT code, value FROM sys_dict WHERE category = ? ORDER BY sort_order",
        (category,),
    ).fetchall()
    return [{"code": r["code"], "value": r["value"]} for r in rows]


def get_dict_value(category: str, code: str) -> str:
    """通过 code 获取字典显示值"""
    db = get_db()
    row = db.execute(
        "SELECT value FROM sys_dict WHERE category = ? AND code = ?",
        (category, code),
    ).fetchone()
    return row["value"] if row else code


def paginate(query: str, params: tuple, page: int, per_page: int = 20) -> PageResult:
    """
    对查询结果进行分页。
    query 应为不含 LIMIT/OFFSET 的完整 SQL 查询。
    返回 PageResult: { rows, page, total, pages, has_prev, has_next, per_page }
    """
    import math
    # 去掉已有的 LIMIT/OFFSET 以得到纯数据源
    base = re.sub(r'\s+LIMIT\s+\d+(\s+OFFSET\s+\d+)?', '', query, flags=re.IGNORECASE)
    count_sql = f"SELECT COUNT(*) FROM ({base}) AS _cnt"
    db = get_db()
    total = db.execute(count_sql, params).fetchone()[0]
    pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, pages))
    offset = (page - 1) * per_page
    rows = db.execute(f"{query} LIMIT {per_page} OFFSET {offset}", params).fetchall()
    return {
        "rows": rows,
        "page": page,
        "total": total,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
        "per_page": per_page,
    }


def get_org_tree_options() -> list[dict]:
    """获取组织架构树形选项（用于下拉菜单，含缩进前缀）"""
    db = get_db()
    orgs = db.execute("SELECT id, name, parent_id FROM sys_org ORDER BY parent_id, sort_order").fetchall()

    def _build(parent_id: int, depth: int) -> list[dict]:
        result = []
        for o in orgs:
            if o["parent_id"] == parent_id:
                prefix = "　" * depth + ("└ " if depth > 0 else "")
                result.append({"id": o["id"], "name": prefix + o["name"]})
                result.extend(_build(o["id"], depth + 1))
        return result

    return _build(0, 0)


def get_submit_units() -> list[dict]:
    """获取报送单位配置（名称/联系人/电话），用于撤控表下拉联动。"""
    db = get_db()
    rows = db.execute(
        "SELECT id, name, contact, phone FROM sys_submit_unit ORDER BY sort_order, name"
    ).fetchall()
    return [{"id": r["id"], "name": r["name"], "contact": r["contact"] or "", "phone": r["phone"] or ""}
            for r in rows]


def get_org_flat() -> list[dict]:
    """获取全部组织节点（含 parent_id），用于单位/部门两级联动。"""
    db = get_db()
    rows = db.execute(
        "SELECT id, name, parent_id FROM sys_org ORDER BY parent_id, sort_order"
    ).fetchall()
    return [{"id": r["id"], "name": r["name"], "parent_id": r["parent_id"]} for r in rows]


def get_org_children(parent_id: int = 0) -> list[dict]:
    """获取指定节点的直接子节点（用于级联选择）"""
    db = get_db()
    rows = db.execute(
        "SELECT id, name FROM sys_org WHERE parent_id = ? ORDER BY sort_order",
        (parent_id,),
    ).fetchall()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def get_personnel_options() -> list[dict]:
    """获取所有有效备案人员列表（用于下拉选择，含完整信息）"""
    db = get_db()
    rows = db.execute(
        "SELECT pf.id, pf.surname, pf.given_name, pf.work_unit, pf.id_number, pf.position_or_title, "
        "COALESCE(pi.department, '') AS department, "
        "(SELECT value FROM sys_dict WHERE category = 'title' AND code = pi.title) AS title_val "
        "FROM personnel_filing pf "
        "LEFT JOIN personnel_info pi ON pf.personnel_info_id = pi.id "
        "WHERE pf.status = 'active' ORDER BY pf.surname, pf.given_name"
    ).fetchall()
    # 每人已登记的证件号（护照/港澳/台湾），一次查询建映射
    cert_map: dict = {}
    for cr in db.execute(
        "SELECT personnel_filing_id, passport_no, hm_pass_no, tw_pass_no FROM certificates"
    ).fetchall():
        lst = cert_map.setdefault(cr["personnel_filing_id"], [])
        for v in (cr["passport_no"], cr["hm_pass_no"], cr["tw_pass_no"]):
            if v and v.strip() and v.strip() not in lst:
                lst.append(v.strip())
    result = []
    for r in rows:
        name = f"{r['surname']}{r['given_name']}"
        result.append({
            "id": r["id"],
            "name": name,
            "full_name": f"{name} ({r['work_unit']})",
            "unit": r["work_unit"],
            "department": r["department"],
            "id_number": r["id_number"],
            "position": r["position_or_title"],
            "title": r["title_val"] or "",
            "cert_nos": cert_map.get(r["id"], []),
        })
    return result

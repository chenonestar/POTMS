"""确保测试可从仓库根目录导入应用模块。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def make_valid_id(birth: str = "19900101", seq: str = "213") -> str:
    """按国标校验位算法生成一个合法 18 位身份证号（供多个测试复用）。

    seq 末位奇偶决定性别：奇→男，偶→女。默认 213（男）。
    """
    body = "110101" + birth + seq
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check = "10X98765432"
    s = sum(int(body[i]) * weights[i] for i in range(17))
    return body + check[s % 11]


def valid_id(n: int = 1) -> str:
    """第 n 个人的身份证号，互不相同（性别男，与各 fixture 里写死的 '男' 一致）。

    以前多个测试人物共用同一个号码。那种数据在真实系统里现在存不进去——
    「一人一号一备案」已经落到库层：personnel_info 全量唯一、personnel_filing
    在 status='active' 内唯一（见 database.run_migrations 的两个唯一索引）。
    拿存不进去的数据做出来的断言本来也不算数，所以造数据时一人一号。
    """
    return make_valid_id(seq=f"{101 + 2 * n:03d}")


def seed_required_attachments(db, travel_id: int, need_new_passport: str = "否") -> None:
    """给一条出行申请补齐必备附件行（路径A 两件，路径B 三件）。

    直接往库里插出行记录、却不给附件，造出来的是**现实中不存在**的数据：
    应用里唯一的插入口 travel.new 一直强制必传附件。编辑保存也补上了同一道
    校验之后（travel._attachment_errors），这种申请会被挡在保存那一步——
    挡得对，只是 fixture 该照着真实形态造数据。

    附件文件本身不落盘：这些用例只关心「有没有这一件」，不读文件内容。
    """
    types = ["个人申请报告", "审批表"] + (["同意申办函"] if need_new_passport == "是" else [])
    for i, t in enumerate(types):
        db.execute("INSERT INTO attachments (travel_id, file_name, file_path, file_type, file_size) "
                   "VALUES (?, ?, ?, ?, 1024)",
                   (travel_id, f"{t}.pdf", f"seed-{travel_id}-{i}.pdf", t))

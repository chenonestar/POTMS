"""校验工具：身份证、日期、必填字段"""
import re
from datetime import datetime


# 身份证校验位权重
_ID_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
_ID_CHECK = "10X98765432"


def validate_id_number(id_number: str) -> tuple[bool, str]:
    """
    校验 18 位身份证号。
    返回 (是否通过, 错误信息)
    """
    if not id_number or len(id_number) != 18:
        return False, "身份证号须为18位。"

    # 前 17 位必须为数字
    if not id_number[:17].isdigit():
        return False, "身份证号前17位须为数字。"

    # 校验位
    total = sum(int(id_number[i]) * _ID_WEIGHTS[i] for i in range(17))
    expected = _ID_CHECK[total % 11]
    if id_number[17].upper() != expected:
        return False, f"身份证校验位不正确，应为 {expected}。"

    # 出生日期合法性
    birth_str = id_number[6:14]
    try:
        datetime.strptime(birth_str, "%Y%m%d")
    except ValueError:
        return False, "身份证号中出生日期不合法。"

    return True, ""


def validate_birth_date_match(id_number: str, birth_date: str) -> tuple[bool, str]:
    """
    校验身份证中的出生日期与填写的出生日期是否一致。
    birth_date 格式: YYYYMMDD
    """
    id_birth = id_number[6:14]
    if id_birth != birth_date:
        return False, f"出生日期与身份证号不一致（身份证中为 {id_birth}）。"
    return True, ""


def validate_date_format(date_str: str) -> tuple[bool, str]:
    """校验 YYYYMMDD 日期格式"""
    if not date_str or len(date_str) != 8:
        return False, "日期格式须为 YYYYMMDD（8位数字）。"
    if not date_str.isdigit():
        return False, "日期须为纯数字。"
    try:
        datetime.strptime(date_str, "%Y%m%d")
        return True, ""
    except ValueError:
        return False, "日期不合法。"


def parse_date_input(raw: str) -> str:
    """
    清洗用户输入的日期，支持 2023-06-20 / 2023/06/20 / 20230620。
    返回 YYYYMMDD 或空字符串。
    """
    raw = raw.strip()
    if not raw:
        return ""
    # 仅数字 → 直接返回
    if raw.isdigit() and len(raw) == 8:
        return raw
    # 带分隔符
    for sep in ("-", "/", "."):
        if sep in raw:
            parts = raw.split(sep)
            if len(parts) == 3:
                return f"{parts[0]}{parts[1].zfill(2)}{parts[2].zfill(2)}"
    return raw


def is_party_member(political_status: str) -> bool:
    """是否为中共党员/预备党员（需要填写入党日期）"""
    return political_status in ("中共党员", "中共预备党员")


def parse_travel_range(text: str) -> tuple[str, str]:
    """
    从计划出行日期文本中解析出起止日期（规范化为 YYYYMMDD）。
    支持形如 "2023-6-20-2023-6-26" / "20230620-20230626" / 单个日期。
    返回 (start, end)，无法解析则返回 ("", "")。
    """
    if not text:
        return ("", "")
    # 匹配 YYYY-M-D / YYYY/M/D / YYYYMMDD
    matches = re.findall(r"(\d{4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})", text)
    if not matches:
        return ("", "")
    def _norm(m):
        return f"{m[0]}{m[1].zfill(2)}{m[2].zfill(2)}"
    start = _norm(matches[0])
    end = _norm(matches[-1])
    return (start, end)

"""校验工具：身份证、日期、必填字段"""
import re
from datetime import datetime, timedelta


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


def check_required(data: dict, fields: list) -> list:
    """必填项校验。fields 为 [(字段名, 中文标签), ...]，返回错误信息列表。"""
    return [f"{label} 为必填项。" for field, label in fields if not data.get(field)]


def check_dates(data: dict, fields: list) -> list:
    """日期格式校验：对每个非空字段校验 YYYYMMDD 合法性（拒绝不存在的日期）。"""
    errors = []
    for field, label in fields:
        val = data.get(field)
        if val:
            ok, msg = validate_date_format(val)
            if not ok:
                errors.append(f"{label}: {msg}")
    return errors


def check_identity(data: dict, id_field: str = "id_number",
                   birth_field: str = "birth_date", gender_field: str = "gender") -> list:
    """
    身份证综合校验：18位校验位；通过后再校验其与"出生日期""性别"的一致性
    （对应字段存在且非空时才校验）。返回错误信息列表。
    """
    errors = []
    id_no = data.get(id_field)
    if not id_no:
        return errors
    ok, msg = validate_id_number(id_no)
    if not ok:
        errors.append(f"身份证号: {msg}")
        return errors
    if birth_field and data.get(birth_field):
        ok2, msg2 = validate_birth_date_match(id_no, data[birth_field])
        if not ok2:
            errors.append(msg2)
    if gender_field and data.get(gender_field):
        ok3, msg3 = validate_gender_match(id_no, data[gender_field])
        if not ok3:
            errors.append(msg3)
    return errors


def validate_gender_match(id_number: str, gender: str) -> tuple[bool, str]:
    """
    校验填写的性别与身份证号第17位（顺序码奇偶）是否一致。
    第17位为奇数→男，偶数→女。id_number 须为已通过基本校验的18位号码。
    """
    if not id_number or len(id_number) != 18 or not id_number[16].isdigit():
        return True, ""  # 号码本身不合规时交由 validate_id_number 报错，此处不重复
    expected = "男" if int(id_number[16]) % 2 == 1 else "女"
    if gender and gender != expected:
        return False, f"性别与身份证号不一致（身份证中为 {expected}）。"
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


def format_travel_range(start: str, end: str) -> str:
    """
    将起止日期（YYYYMMDD）组装为统一存储/展示格式 YYYY/MM/DD-YYYY/MM/DD。
    起止相同或仅有单个日期时，返回单个 YYYY/MM/DD。
    """
    def _f(s):
        return f"{s[0:4]}/{s[4:6]}/{s[6:8]}" if s and len(s) == 8 else ""
    fs, fe = _f(start), _f(end)
    if fs and fe and fs != fe:
        return f"{fs}-{fe}"
    return fs or fe or ""


def validate_travel_range(text: str) -> tuple[bool, str]:
    """
    校验"计划出行日期"区间文本：须能解析出起止两个真实存在的日期，
    且起始日期不晚于结束日期。返回 (是否通过, 错误信息)。
    """
    if not text or not text.strip():
        return False, "计划出行日期不能为空。"
    start, end = parse_travel_range(text)
    if not start or not end:
        return False, "计划出行日期格式无法识别，请填「起始-结束」，如 2026-8-1-2026-8-11。"
    ok, msg = validate_date_format(start)
    if not ok:
        return False, f"起始日期不合法（解析为 {start}）：{msg}"
    ok, msg = validate_date_format(end)
    if not ok:
        return False, f"结束日期不合法（解析为 {end}）：{msg}"
    if start > end:
        return False, f"起始日期（{start}）不应晚于结束日期（{end}）。"
    return True, ""


def add_working_days(start_ymd: str, n: int) -> str:
    """
    以 start_ymd（YYYYMMDD）为第 0 天，向后顺延 n 个工作日（仅跳过周六/周日，
    不含法定节假日日历），返回到期日 YYYYMMDD。

    语义：例如 10 个工作日内归还，即到期日为「回国日之后第 10 个工作日」。
    超过到期日（严格大于）才算逾期，故到期日当天仍算未逾期。
    无法解析 start_ymd 时返回空字符串。
    """
    if not start_ymd or len(start_ymd) != 8 or not start_ymd.isdigit():
        return ""
    try:
        d = datetime.strptime(start_ymd, "%Y%m%d")
    except ValueError:
        return ""
    counted = 0
    while counted < n:
        d += timedelta(days=1)
        if d.weekday() < 5:  # 0=周一 … 4=周五
            counted += 1
    return d.strftime("%Y%m%d")


def cert_overdue_deadline(row) -> str:
    """
    计算某条出国明细的证件归还到期日（YYYYMMDD）。
    - 正常行程：以「实际回国日期」优先，否则回退「计划出行结束日 travel_end」，
      向后顺延 10 个工作日。
    - 取消行程：以「取消日期 cancel_date」为基准，向后顺延 5 个工作日。
    row 支持 sqlite3.Row 或 dict。无法确定基准日时返回空字符串。
    """
    def _g(key):
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return None

    status = (_g("trip_status") or "normal")
    if status == "cancelled":
        base = _g("cancel_date") or ""
        return add_working_days(base, 5)
    base = (_g("actual_return_date") or "") or (_g("travel_end") or "")
    return add_working_days(base, 10)


def is_cert_overdue(row, today: str) -> bool:
    """
    判断某条出国明细是否「证件逾期未还」。
    条件：已领用证件（passport_collect_date 非空）+ 尚未归还（passport_return_date 空）
    + 已过归还到期日（today 严格大于到期日）。
    today 为 YYYYMMDD。
    """
    def _g(key):
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return None

    collect = _g("passport_collect_date")
    ret = _g("passport_return_date")
    if not collect:
        return False
    if ret:  # 已归还
        return False
    deadline = cert_overdue_deadline(row)
    if not deadline:
        return False
    return today > deadline

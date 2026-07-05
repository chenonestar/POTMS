"""utils/validators.py 纯函数单元测试。"""
import pytest

from conftest import make_valid_id
from utils.validators import (
    validate_id_number, validate_birth_date_match, validate_gender_match,
    validate_date_format, parse_date_input,
    parse_travel_range, validate_travel_range, format_travel_range,
    add_working_days, cert_overdue_deadline, is_cert_overdue,
    check_required, check_dates, check_identity,
)

MALE = make_valid_id("19900101", "213")    # 顺序码末位奇 → 男
FEMALE = make_valid_id("19900101", "212")  # 顺序码末位偶 → 女


# ------------------------- 身份证 -------------------------
def test_id_valid():
    assert validate_id_number(MALE)[0] is True


@pytest.mark.parametrize("bad", [
    "", "123", "11010119900101213",            # 长度不足
    "11010119900101213X",                        # 错误校验位
    "110101209013012130",                        # 出生月份 90 非法
])
def test_id_invalid(bad):
    assert validate_id_number(bad)[0] is False


def test_birth_match():
    assert validate_birth_date_match(MALE, "19900101")[0] is True
    ok, msg = validate_birth_date_match(MALE, "19910101")
    assert ok is False and "不一致" in msg


def test_gender_match():
    assert validate_gender_match(MALE, "男")[0] is True
    assert validate_gender_match(FEMALE, "女")[0] is True
    assert validate_gender_match(MALE, "女")[0] is False
    assert validate_gender_match(FEMALE, "男")[0] is False
    # 号码不合规时不重复报错，交由 validate_id_number 处理
    assert validate_gender_match("123", "男")[0] is True


# ------------------------- 日期 -------------------------
@pytest.mark.parametrize("d,ok", [
    ("20240229", True),   # 闰年 2 月 29
    ("20260101", True),
    ("20260230", False),  # 2 月无 30
    ("20260231", False),
    ("20261301", False),  # 无 13 月
    ("20260229", False),  # 平年无 2 月 29
    ("2026013", False),   # 位数不足
    ("abcdefgh", False),
])
def test_date_format(d, ok):
    assert validate_date_format(d)[0] is ok


def test_parse_date_input():
    assert parse_date_input("2026-8-1") == "20260801"
    assert parse_date_input("2026/08/01") == "20260801"
    assert parse_date_input("20260801") == "20260801"
    assert parse_date_input("") == ""


# ------------------------- 出行区间 -------------------------
def test_parse_travel_range():
    assert parse_travel_range("2026-8-1-2026-8-11") == ("20260801", "20260811")
    assert parse_travel_range("2026/8/1") == ("20260801", "20260801")
    assert parse_travel_range("abc") == ("", "")


@pytest.mark.parametrize("text,ok", [
    ("2026-8-1-2026-8-11", True),
    ("2026/08/01-2026/08/11", True),
    ("2026-8-1", True),                 # 单日
    ("2026-8-11-2026-8-1", False),      # 起晚于止
    ("2026-2-30-2026-3-5", False),      # 起始非法
    ("", False),
    ("abc", False),
])
def test_validate_travel_range(text, ok):
    assert validate_travel_range(text)[0] is ok


def test_format_travel_range():
    assert format_travel_range("20260801", "20260811") == "2026/08/01-2026/08/11"
    assert format_travel_range("20260801", "20260801") == "2026/08/01"  # 同日折叠为单个
    assert format_travel_range("20260801", "") == "2026/08/01"
    assert format_travel_range("", "") == ""


# ------------------------- 工作日 -------------------------
def test_add_working_days_skips_weekends():
    # 2026-08-11 是周二，顺延 10 个工作日（跨两个周末）= 2026-08-25
    assert add_working_days("20260811", 10) == "20260825"
    # 2026-07-03 是周五，顺延 5 个工作日 = 2026-07-10
    assert add_working_days("20260703", 5) == "20260710"
    assert add_working_days("", 10) == ""
    assert add_working_days("2026081", 10) == ""


# ------------------------- 逾期判定 -------------------------
def _row(**kw):
    base = dict(passport_collect_date="", passport_return_date="",
                actual_return_date="", travel_end="", trip_status="normal", cancel_date="")
    base.update(kw)
    return base


def test_deadline_normal_uses_actual_return_then_travel_end():
    # 有实际回国日期时以其为准
    r = _row(actual_return_date="20260901", travel_end="20260811")
    assert cert_overdue_deadline(r) == add_working_days("20260901", 10)
    # 无实际回国日期回退到计划结束日
    r2 = _row(travel_end="20260811")
    assert cert_overdue_deadline(r2) == "20260825"


def test_deadline_cancelled_uses_cancel_date_5wd():
    r = _row(trip_status="cancelled", cancel_date="20260703")
    assert cert_overdue_deadline(r) == "20260710"


def test_overdue_rules():
    # 已领用 + 未归还 + 过期 → 逾期
    r = _row(passport_collect_date="20260101", travel_end="20260811")
    assert is_cert_overdue(r, "20260826") is True
    # 到期日当天不算逾期
    assert is_cert_overdue(r, "20260825") is False
    # 已归还 → 不逾期
    assert is_cert_overdue(_row(passport_collect_date="20260101",
                                passport_return_date="20260820",
                                travel_end="20260811"), "20260901") is False
    # 未领用 → 不逾期
    assert is_cert_overdue(_row(travel_end="20260101"), "20260901") is False


# ------------------------- 公共校验器 -------------------------
def test_check_required():
    errs = check_required({"a": "x", "b": ""}, [("a", "甲"), ("b", "乙"), ("c", "丙")])
    assert errs == ["乙 为必填项。", "丙 为必填项。"]


def test_check_dates():
    errs = check_dates({"d1": "20260230", "d2": "20260101", "d3": ""},
                       [("d1", "日一"), ("d2", "日二"), ("d3", "日三")])
    assert len(errs) == 1 and "日一" in errs[0]


def test_check_identity():
    assert check_identity({"id_number": MALE, "birth_date": "19900101", "gender": "男"}) == []
    errs = check_identity({"id_number": MALE, "birth_date": "19900101", "gender": "女"})
    assert any("性别" in e for e in errs)
    # 号码非法时只报号码错误，不再连带比对
    errs2 = check_identity({"id_number": "123", "birth_date": "19900101", "gender": "男"})
    assert len(errs2) == 1 and "身份证号" in errs2[0]
    # 明细表场景：无出生/性别字段，仅校验号码
    assert check_identity({"id_number": MALE}, birth_field=None, gender_field=None) == []

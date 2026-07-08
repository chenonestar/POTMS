"""UTC → 本地时间显示转换测试（store UTC / display local）。"""
from utils.helpers import to_local_time


def test_utc_to_local_default_plus8():
    # 数据库存 UTC 10:00，默认 +8 → 本地 18:00
    assert to_local_time("2026-07-05 10:00:00") == "2026-07-05 18:00:00"


def test_cross_midnight():
    # UTC 20:00 + 8h → 次日 04:00
    assert to_local_time("2026-07-05 20:00:00") == "2026-07-06 04:00:00"


def test_custom_format_date_only():
    assert to_local_time("2026-07-05 20:00:00", "%Y-%m-%d") == "2026-07-06"


def test_empty_and_bad_input():
    assert to_local_time("") == ""
    assert to_local_time(None) == ""
    assert to_local_time("not-a-date") == "not-a-date"  # 原样返回，不抛错


def test_fractional_seconds_tolerated():
    assert to_local_time("2026-07-05 10:00:00.123456") == "2026-07-05 18:00:00"

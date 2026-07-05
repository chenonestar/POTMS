"""数据库迁移幂等性与历史数据回填测试。"""
import sqlite3

import pytest

from config import Config


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """每个测试独立的临时数据库路径。"""
    db_path = tmp_path / "t.db"
    monkeypatch.setattr(Config, "DATABASE", str(db_path))
    return str(db_path)


def _cols(db, table):
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}


def test_fresh_schema_has_new_columns(fresh_db):
    import database
    database.init_db()
    database.run_migrations()
    db = sqlite3.connect(fresh_db)
    cols = _cols(db, "travel_details")
    assert {"actual_return_date", "trip_status", "cancel_date"} <= cols


def test_migrations_idempotent(fresh_db):
    import database
    database.init_db()
    database.run_migrations()
    # 再跑两次不应报错、不改变列集合
    before = None
    db = sqlite3.connect(fresh_db)
    before = _cols(db, "travel_details")
    db.close()
    database.run_migrations()
    database.run_migrations()
    db = sqlite3.connect(fresh_db)
    assert _cols(db, "travel_details") == before


def test_legacy_db_upgrade_and_backfill(fresh_db):
    """模拟旧库（缺新列、travel_dates 为 - 分隔）升级后应补列并规整。"""
    db = sqlite3.connect(fresh_db)
    # 旧版 travel_details：无 actual_return_date/trip_status/cancel_date/travel_start/travel_end
    db.execute(
        "CREATE TABLE travel_details (id INTEGER PRIMARY KEY, personnel_filing_id INTEGER, "
        "unit TEXT, department TEXT, name TEXT, position TEXT, title TEXT, id_number TEXT, "
        "destination_passport TEXT, category TEXT, travel_dates TEXT, approval_date TEXT, "
        "need_new_passport TEXT, passport_no TEXT, passport_collect_date TEXT, "
        "passport_return_date TEXT, operator TEXT)"
    )
    # 迁移依赖的其它表
    db.execute("CREATE TABLE personnel_info (id INTEGER PRIMARY KEY)")
    db.execute("CREATE TABLE operation_logs (id INTEGER PRIMARY KEY)")
    db.execute("CREATE TABLE decontrol_filing (id INTEGER PRIMARY KEY, submit_unit_name TEXT, "
               "submit_contact TEXT, submit_phone TEXT, supervisor_unit TEXT, created_at TEXT)")
    db.execute("CREATE TABLE personnel_filing (id INTEGER PRIMARY KEY, supervisor_unit TEXT)")
    db.execute("CREATE TABLE sys_dict (id INTEGER PRIMARY KEY, category TEXT, code TEXT, "
               "value TEXT, sort_order INTEGER)")
    db.execute(
        "INSERT INTO travel_details (name, travel_dates, passport_collect_date, passport_return_date) "
        "VALUES ('张三', '2026-8-1-2026-8-11', '20260725', '')"
    )
    db.commit()
    db.close()

    import database
    database.run_migrations()

    db = sqlite3.connect(fresh_db)
    cols = _cols(db, "travel_details")
    assert {"actual_return_date", "trip_status", "cancel_date", "travel_start", "travel_end"} <= cols
    row = db.execute(
        "SELECT trip_status, travel_start, travel_end, travel_dates FROM travel_details WHERE id=1"
    ).fetchone()
    assert row[0] == "normal"                 # 默认行程状态
    assert row[1] == "20260801"               # travel_start 回填
    assert row[2] == "20260811"               # travel_end 回填
    assert row[3] == "2026/08/01-2026/08/11"  # travel_dates 规整为统一格式

    # 再次迁移：travel_dates 已含 '/'，不应被再次改动
    db.close()
    database.run_migrations()
    db = sqlite3.connect(fresh_db)
    assert db.execute("SELECT travel_dates FROM travel_details WHERE id=1").fetchone()[0] \
        == "2026/08/01-2026/08/11"

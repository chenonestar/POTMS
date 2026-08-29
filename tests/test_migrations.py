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


# ---------------------------------------------------------------------------
# 生成物同步：改了 database.py 就得重新生成 .NET / Java 两份 schema
# ---------------------------------------------------------------------------
def test_generated_schemas_are_in_sync_with_database_py():
    """.NET 与 Java 两版的 schema 由 database.py 生成，必须与源头一致。

    这条本来只有 CI 在看（三个工作流各跑一次 gen-schema*.py --check）。
    结果就是：本地改完 database.py 的 SEED_DICT 一路全绿，推上去三个工作流
    同时红——反馈来得太晚，而且要等一轮 CI 才知道。

    真实经过：把字典里的「因私护照」改成「普通护照」（为了与证照台账的槽位
    标签统一），忘了重新生成，Python / Java / .NET 三个构建一起挂在这一步。
    交付自检清单上明明写着「改了 schema 就重新生成了 .NET / Java 两份吗？」，
    我跳过了那一条——所以把它从清单挪进测试里，让机器来问。
    """
    import pathlib
    import subprocess
    import sys

    root = pathlib.Path(__file__).resolve().parent.parent
    for tool in ("potms-dotnet/tools/gen-schema.py", "potms-java/tools/gen-schema-java.py"):
        # 显式 encoding="utf-8"：脚本的输出全是中文，而 text=True 在 Windows 上
        # 按 locale（cp1252）解码，会把提示信息糊成乱码甚至解不出来。
        # 脚本那一侧也已经把 stdout 重设为 UTF-8——两头都要说同一种编码。
        r = subprocess.run([sys.executable, str(root / tool), "--check"],
                           cwd=root, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        assert r.returncode == 0, (
            f"{tool} --check 失败：\n{r.stdout}{r.stderr}"
            f"\n改了 database.py 的 SCHEMA 或 SEED_DICT，就要重新跑一遍生成脚本。")


def test_generator_output_survives_a_non_utf8_console():
    """生成脚本的中文输出，在默认编码不是 UTF-8 的终端上也得打得出来。

    上一条测试自己把 Windows CI 弄红了：schema 明明是同步的，脚本却在
    `print("Schema.cs 与 database.py 同步 ✓")` 上抛 UnicodeEncodeError——
    Windows 标准输出默认 cp1252，编不出「与」和「✓」，退出码 1，
    于是断言认定「不同步」。**卡住的只是那句成功提示。**

    这是本项目第三次栽在「默认编码不是 UTF-8」上：
      1) 产品代码 Path.write_text 写中文没给 encoding；
      2) 测试代码同样的写法；
      3) 这次是工具脚本的 stdout。
    前两次的规矩是「读写文本文件必须显式 encoding」——它没覆盖 stdout。
    所以规矩要扩成：**凡是可能出现中文的输出口，都要显式指定 UTF-8。**

    用 PYTHONIOENCODING=cp1252 在任何平台上复现 Windows 的条件。
    """
    import os
    import pathlib
    import subprocess
    import sys

    root = pathlib.Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    for tool in ("potms-dotnet/tools/gen-schema.py", "potms-java/tools/gen-schema-java.py"):
        r = subprocess.run([sys.executable, str(root / tool), "--check"],
                           cwd=root, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
        assert "UnicodeEncodeError" not in (r.stdout + r.stderr), (
            f"{tool} 在 cp1252 终端上打印中文炸了：\n{r.stdout}{r.stderr}")
        assert r.returncode == 0, f"{tool} --check 失败：\n{r.stdout}{r.stderr}"

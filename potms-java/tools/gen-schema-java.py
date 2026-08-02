#!/usr/bin/env python3
"""从 Python 版 database.py 生成 Java 版的 schema.sql 与 Schema.java。

五个语言版本（Python / Go / Rust / .NET / Java）共用同一个 data.db，
schema 必须逐字节一致。手抄容易漂移，故由本脚本从单一来源生成。

用法（在仓库根目录执行）：
    python3 potms-java/tools/gen-schema-java.py
    python3 potms-java/tools/gen-schema-java.py --check   # CI 校验用

产出两个文件：
  - src/main/resources/schema.sql   DDL 原文（classpath 资源，逐字节复制）
  - src/main/java/com/potms/data/Schema.java   种子字典 + DDL 读取入口

DDL 走资源文件而非 Java 字符串常量，是刻意的：Java 文本块会按最小缩进
剥离前导空白、并裁掉每行行尾空白，无法保证与来源逐字节相同。
"""
import io
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "database.py")
BASE = os.path.join(ROOT, "potms-java")
DST_SQL = os.path.join(BASE, "src", "main", "resources", "schema.sql")
DST_JAVA = os.path.join(BASE, "src", "main", "java", "com", "potms", "data", "Schema.java")

HEADER = (
    "// 本文件由 Python 版 database.py 生成，请勿手工编辑。\n"
    "// 重新生成： python3 potms-java/tools/gen-schema-java.py\n"
    "//\n"
    "// 目的：五个语言版本（Python / Go / Rust / .NET / Java）共用同一个 data.db，\n"
    "//       schema 必须逐字节一致，故由脚本从单一来源生成而非手抄。\n"
)


def parse():
    src = open(SRC, encoding="utf-8").read()
    m = re.search(r'SCHEMA\s*=\s*"""(.*?)"""', src, re.S)
    if not m:
        sys.exit("未能在 database.py 中定位 SCHEMA 常量")
    seed = re.findall(r'^\s*\("([a-z_]+)",\s*"([^"]+)",\s*"([^"]+)",\s*(\d+)\),', src, re.M)
    if not seed:
        sys.exit("未能在 database.py 中解析 SEED_DICT")
    return m.group(1), seed


def java_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def gen_java(seed) -> str:
    out = io.StringIO()
    out.write(HEADER)
    out.write("package com.potms.data;\n\n")
    out.write("import java.io.IOException;\n")
    out.write("import java.io.InputStream;\n")
    out.write("import java.nio.charset.StandardCharsets;\n\n")
    out.write("/** 建表 DDL 与字典种子数据（由 database.py 生成）。 */\n")
    out.write("public final class Schema {\n")
    out.write("    private Schema() {}\n\n")
    out.write("    /** 字典种子数据：分类 / 代码 / 显示值 / 排序。 */\n")
    out.write("    public record SeedDict(String category, String code, String value, int sortOrder) {}\n\n")
    out.write("    /** 建表 DDL，读自 classpath 资源 schema.sql（与 database.py 逐字节一致）。 */\n")
    out.write("    public static String ddl() {\n")
    out.write("        try (InputStream in = Schema.class.getResourceAsStream(\"/schema.sql\")) {\n")
    out.write("            if (in == null) throw new IllegalStateException(\"缺少 classpath 资源 /schema.sql\");\n")
    out.write("            return new String(in.readAllBytes(), StandardCharsets.UTF_8);\n")
    out.write("        } catch (IOException e) {\n")
    out.write("            throw new IllegalStateException(\"读取 schema.sql 失败\", e);\n")
    out.write("        }\n")
    out.write("    }\n\n")
    out.write("    public static final SeedDict[] SEED_DICT = {\n")
    for cat, code, val, order in seed:
        out.write("        new SeedDict(%s, %s, %s, %s),\n"
                  % (java_str(cat), java_str(code), java_str(val), order))
    out.write("    };\n")
    out.write("}\n")
    return out.getvalue()


def main():
    schema, seed = parse()
    java = gen_java(seed)
    check = "--check" in sys.argv

    for path, content in ((DST_SQL, schema), (DST_JAVA, java)):
        if check:
            current = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
            if current != content:
                sys.exit("%s 与 database.py 不同步，请运行： "
                         "python3 potms-java/tools/gen-schema-java.py" % os.path.basename(path))
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)

    if check:
        print("schema.sql / Schema.java 与 database.py 同步 ✓")
    else:
        print("已生成 %s（%d 字节）" % (os.path.relpath(DST_SQL, ROOT), len(schema)))
        print("已生成 %s（种子字典 %d 条）" % (os.path.relpath(DST_JAVA, ROOT), len(seed)))


if __name__ == "__main__":
    main()

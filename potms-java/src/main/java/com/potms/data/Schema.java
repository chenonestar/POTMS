// 本文件由 Python 版 database.py 生成，请勿手工编辑。
// 重新生成： python3 potms-java/tools/gen-schema-java.py
//
// 目的：五个语言版本（Python / Go / Rust / .NET / Java）共用同一个 data.db，
//       schema 必须逐字节一致，故由脚本从单一来源生成而非手抄。
package com.potms.data;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** 建表 DDL 与字典种子数据（由 database.py 生成）。 */
public final class Schema {
    private Schema() {}

    /** 字典种子数据：分类 / 代码 / 显示值 / 排序。 */
    public record SeedDict(String category, String code, String value, int sortOrder) {}

    /** 建表 DDL，读自 classpath 资源 schema.sql（与 database.py 逐字节一致）。 */
    public static String ddl() {
        try (InputStream in = Schema.class.getResourceAsStream("/schema.sql")) {
            if (in == null) throw new IllegalStateException("缺少 classpath 资源 /schema.sql");
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new IllegalStateException("读取 schema.sql 失败", e);
        }
    }

    public static final SeedDict[] SEED_DICT = {
        new SeedDict("education", "01", "博士研究生", 1),
        new SeedDict("education", "02", "硕士研究生", 2),
        new SeedDict("education", "03", "大学本科", 3),
        new SeedDict("education", "04", "大学专科", 4),
        new SeedDict("education", "05", "中专", 5),
        new SeedDict("education", "06", "高中", 6),
        new SeedDict("education", "07", "初中及以下", 7),
        new SeedDict("degree", "01", "博士", 1),
        new SeedDict("degree", "02", "硕士", 2),
        new SeedDict("degree", "03", "学士", 3),
        new SeedDict("degree", "99", "无", 4),
        new SeedDict("title", "01", "正高", 1),
        new SeedDict("title", "02", "副高", 2),
        new SeedDict("title", "03", "中级", 3),
        new SeedDict("title", "04", "初级", 4),
        new SeedDict("title", "99", "无", 5),
        new SeedDict("rank", "01", "处级", 1),
        new SeedDict("rank", "02", "副处级", 2),
        new SeedDict("rank", "03", "正科", 3),
        new SeedDict("rank", "04", "副科", 4),
        new SeedDict("rank", "05", "科员", 5),
        new SeedDict("rank", "99", "其他", 6),
        new SeedDict("political_status", "01", "中共党员", 1),
        new SeedDict("political_status", "02", "中共预备党员", 2),
        new SeedDict("political_status", "03", "共青团员", 3),
        new SeedDict("political_status", "04", "民革会员", 4),
        new SeedDict("political_status", "05", "民盟盟员", 5),
        new SeedDict("political_status", "06", "民建会员", 6),
        new SeedDict("political_status", "07", "民进会员", 7),
        new SeedDict("political_status", "08", "农工党党员", 8),
        new SeedDict("political_status", "09", "致工党党员", 9),
        new SeedDict("political_status", "10", "九三学社社员", 10),
        new SeedDict("political_status", "99", "群众", 11),
        new SeedDict("travel_category", "01", "旅游", 1),
        new SeedDict("travel_category", "02", "探亲", 2),
        new SeedDict("travel_category", "03", "访友", 3),
        new SeedDict("travel_category", "04", "商务", 4),
        new SeedDict("travel_category", "05", "留学", 5),
        new SeedDict("travel_category", "99", "其他", 6),
        new SeedDict("submit_unit_type", "01", "党政机关", 1),
        new SeedDict("submit_unit_type", "02", "金融系统", 2),
        new SeedDict("submit_unit_type", "03", "教科文卫系统", 3),
        new SeedDict("submit_unit_type", "04", "国有大中型企业单位", 4),
        new SeedDict("submit_unit_type", "99", "其他单位", 5),
        new SeedDict("supervisor_unit", "S01", "人事处", 1),
        new SeedDict("cert_type", "01", "普通护照", 1),
        new SeedDict("cert_type", "02", "往来港澳通行证", 2),
        new SeedDict("cert_type", "03", "大陆居民往来台湾通行证", 3),
    };
}

// Excel 导出（5 表 + 日志归档）与批量导入 — rust_xlsxwriter + calamine
use crate::config::Config;
use crate::db::{self, Row};
use crate::helpers;
use crate::validators as v;
use rusqlite::types::Value::{Integer as I, Text as T};
use rusqlite::types::Value as SqlValue;
use rusqlite::Connection;
use rust_xlsxwriter::{Color, Format, FormatAlign, FormatBorder, Workbook};
use serde_json::json;
use std::path::PathBuf;

const EXPORT_RETENTION_DAYS: u64 = 7;

fn prune_old_exports(cfg: &Config) {
    let cutoff = std::time::SystemTime::now()
        .checked_sub(std::time::Duration::from_secs(EXPORT_RETENTION_DAYS * 86400));
    if let (Ok(entries), Some(cutoff)) = (std::fs::read_dir(&cfg.export_folder), cutoff) {
        for e in entries.flatten() {
            let name = e.file_name().to_string_lossy().to_lowercase();
            if name.ends_with(".xlsx") {
                if let Ok(meta) = e.metadata() {
                    if let Ok(modified) = meta.modified() {
                        if modified < cutoff {
                            let _ = std::fs::remove_file(e.path());
                        }
                    }
                }
            }
        }
    }
}

fn build_export(cfg: &Config, sheet: &str, title: &str, headers: &[&str], rows: &[Vec<String>], prefix: &str, operator: &str, notes: &[&str]) -> (Option<PathBuf>, String) {
    let mut wb = Workbook::new();
    let title_fmt = Format::new().set_bold().set_font_size(16).set_align(FormatAlign::Center).set_align(FormatAlign::VerticalCenter);
    let header_fmt = Format::new().set_bold().set_font_color(Color::White).set_background_color(Color::RGB(0x1A5276))
        .set_align(FormatAlign::Center).set_align(FormatAlign::VerticalCenter).set_text_wrap().set_border(FormatBorder::Thin);
    let data_fmt = Format::new().set_align(FormatAlign::VerticalCenter).set_text_wrap().set_border(FormatBorder::Thin);

    {
        let ws = wb.add_worksheet();
        let _ = ws.set_name(sheet);
        let ncol = headers.len() as u16;
        let _ = ws.merge_range(0, 0, 0, ncol - 1, title, &title_fmt);
        let _ = ws.set_row_height(0, 30);
        for (i, h) in headers.iter().enumerate() {
            let _ = ws.write_string_with_format(1, i as u16, *h, &header_fmt);
        }
        for (r, vals) in rows.iter().enumerate() {
            for (c, val) in vals.iter().enumerate() {
                let _ = ws.write_string_with_format(r as u32 + 2, c as u16, val, &data_fmt);
            }
        }
        let _ = ws.set_freeze_panes(2, 0);
        // 自动列宽
        for c in 0..headers.len() {
            let mut maxlen = headers[c].chars().count();
            for row in rows {
                if let Some(cell) = row.get(c) {
                    maxlen = maxlen.max(cell.chars().count());
                }
            }
            let w = ((maxlen + 4) as f64).min(40.0);
            let _ = ws.set_column_width(c as u16, w);
        }
    }
    if !notes.is_empty() {
        let ws2 = wb.add_worksheet();
        let _ = ws2.set_name("填表说明");
        for (i, n) in notes.iter().enumerate() {
            let _ = ws2.write_string(i as u32, 0, *n);
        }
    }

    let now = time::OffsetDateTime::now_utc() + time::Duration::hours(cfg.tz_offset_hours);
    let ts = format!("{:04}{:02}{:02}_{:02}{:02}{:02}", now.year(), now.month() as u8, now.day(), now.hour(), now.minute(), now.second());
    let filename = format!("{prefix}_{ts}_{operator}.xlsx");
    let _ = std::fs::create_dir_all(&cfg.export_folder);
    prune_old_exports(cfg);
    let path = cfg.export_folder.join(&filename);
    match wb.save(&path) {
        Ok(_) => (Some(path), filename),
        Err(_) => (None, filename),
    }
}

fn s(r: &Row, k: &str) -> String { helpers::row_str(r, k) }

pub fn export_personnel_info(conn: &Connection, cfg: &Config, operator: &str, where_sql: &str, params: &[SqlValue]) -> (Option<PathBuf>, String) {
    let rows = db::query_maps(conn, &format!("SELECT pi.* FROM personnel_info pi JOIN personnel_filing pf ON pf.personnel_info_id = pi.id WHERE 1=1 {where_sql} GROUP BY pi.id ORDER BY pi.created_at DESC"), params);
    let dv = |cat: &str, code: &str| -> String { if code.is_empty() { String::new() } else { helpers::get_dict_value(conn, cat, code) } };
    let data: Vec<Vec<String>> = rows.iter().map(|r| vec![
        s(r, "unit"), s(r, "department"), s(r, "name"), s(r, "gender"), s(r, "birth_date"), s(r, "id_number"), s(r, "work_start_date"),
        dv("education", &s(r, "education")), dv("degree", &s(r, "degree")), dv("title", &s(r, "title")), dv("rank", &s(r, "rank")),
        s(r, "political_status"), s(r, "party_join_date"), s(r, "position"),
    ]).collect();
    build_export(cfg, "备案人员信息登记表", "备案人员信息登记表",
        &["单位","部门","姓名","性别","出生日期","身份证号","参加工作日期","学历","学位","职称","职级","政治面貌","入党日期","职务（岗位名称）"],
        &data, "备案人员信息登记表", operator,
        &["填表说明：","1. 出生日期格式为YYYYMMDD，需与身份证号对应。","2. 学历、学位、职称、职级、政治面貌从系统数据字典中选择。","3. 中共党员/预备党员须填写入党日期。"])
}

pub fn export_personnel_filing(conn: &Connection, cfg: &Config, operator: &str, where_sql: &str, params: &[SqlValue]) -> (Option<PathBuf>, String) {
    let rows = db::query_maps(conn, &format!("SELECT pf.* FROM personnel_filing pf LEFT JOIN personnel_info pi ON pf.personnel_info_id = pi.id WHERE 1=1 {where_sql} ORDER BY pf.created_at DESC"), params);
    let data: Vec<Vec<String>> = rows.iter().map(|r| {
        let status = if s(r, "status") != "active" { "已撤控" } else { "有效" };
        vec![s(r,"surname"),s(r,"given_name"),s(r,"gender"),s(r,"birth_date"),s(r,"id_number"),s(r,"residence"),s(r,"political_status"),s(r,"work_unit"),s(r,"position_or_title"),s(r,"supervisor_unit"),s(r,"tag"),s(r,"informed"),status.to_string(),s(r,"remarks")]
    }).collect();
    build_export(cfg, "登记备案表", "因私事出国（境）人员登记备案表",
        &["中文姓","中文名","性别","出生日期","身份证号","户口所在地","政治面貌","工作单位","职务（级）或职称","人事主管单位","标记","已告知本人","状态","备注"],
        &data, "登记备案表", operator,
        &["填表说明：","1. 姓与名分开填写，特别注意复姓人员。","2. 出生日期格式为YYYYMMDD，生日需与身份证号对应。","3. 工作单位请写全称。","4. 职务/职称栏：处级领导填'处级'或'副处级'，副处级单位班子成员填'正科'，其他人员填'副高'或'正高'。","5. 人事主管单位名称需与印章一致。","6. 户口所在地填至区级，省份不加'省'字，江东区、鄞县统一为'鄞州区'。","7. 标记：新增、更新。","8. 已告知本人：是、否。"])
}

pub fn export_certificates(conn: &Connection, cfg: &Config, operator: &str, where_sql: &str, params: &[SqlValue]) -> (Option<PathBuf>, String) {
    let rows = db::query_maps(conn, &format!("SELECT * FROM certificates WHERE 1=1 {where_sql} ORDER BY updated_at DESC"), params);
    let data: Vec<Vec<String>> = rows.iter().map(|r| vec![
        s(r,"unit"),s(r,"department"),s(r,"name"),s(r,"passport_no"),s(r,"passport_expiry"),s(r,"passport_submit_date"),
        s(r,"hm_pass_no"),s(r,"hm_pass_expiry"),s(r,"hm_pass_submit_date"),s(r,"tw_pass_no"),s(r,"tw_pass_expiry"),s(r,"tw_pass_submit_date"),
    ]).collect();
    build_export(cfg, "证照登记表", "因私出国（境）备案人员证照登记表",
        &["单位","部门","姓名","护照证件号","护照有效日期","护照上交日期","港澳通行证号","港澳有效日期","港澳上交日期","台湾通行证号","台湾有效日期","台湾上交日期"],
        &data, "证照登记表", operator, &["填表说明：","1. 日期格式均为YYYYMMDD。","2. 无对应证件的列留空。"])
}

pub fn export_travel(conn: &Connection, cfg: &Config, operator: &str, where_sql: &str, params: &[SqlValue]) -> (Option<PathBuf>, String) {
    let rows = db::query_maps(conn, &format!("SELECT * FROM travel_details WHERE 1=1 {where_sql} ORDER BY created_at DESC"), params);
    let data: Vec<Vec<String>> = rows.iter().map(|r| {
        let status = if s(r, "trip_status") == "cancelled" { "取消行程" } else { "正常" };
        vec![s(r,"unit"),s(r,"department"),s(r,"name"),s(r,"position"),s(r,"title"),s(r,"id_number"),s(r,"destination_passport"),s(r,"category"),s(r,"travel_dates"),s(r,"approval_date"),s(r,"need_new_passport"),s(r,"passport_no"),s(r,"passport_collect_date"),s(r,"actual_return_date"),s(r,"passport_return_date"),status.to_string(),s(r,"cancel_date")]
    }).collect();
    build_export(cfg, "出国明细表", "因私出国（境）人员明细表",
        &["单位","部门","姓名","职务","职称","身份证号","地点、证照","类别","计划出行日期","批准日期","是否做证","证件号码","证件领用日期","实际回国日期","证件归还日期","行程状态","取消日期"],
        &data, "出国明细表", operator, &["1. 计划出行日期格式：起始日期-结束日期，如 2023-6-20-2023-6-26。","2. 附件需线下查看系统存储的PDF扫描件。"])
}

pub fn export_decontrol(conn: &Connection, cfg: &Config, operator: &str, where_sql: &str, params: &[SqlValue]) -> (Option<PathBuf>, String) {
    let rows = db::query_maps(conn, &format!("SELECT * FROM decontrol_filing WHERE 1=1 {where_sql} ORDER BY created_at DESC"), params);
    let data: Vec<Vec<String>> = rows.iter().map(|r| vec![
        s(r,"surname"),s(r,"given_name"),s(r,"gender"),s(r,"birth_date"),s(r,"id_number"),s(r,"residence"),s(r,"political_status"),s(r,"work_unit"),s(r,"supervisor_unit"),s(r,"submit_unit_name"),s(r,"submit_unit_type"),s(r,"submit_contact"),s(r,"submit_phone"),s(r,"batch_no"),s(r,"decontrol_date"),s(r,"cert_handover_date"),s(r,"reason"),
    ]).collect();
    build_export(cfg, "撤控备案表", "因私事出国（境）人员撤控备案表",
        &["中文姓","中文名","性别","出生日期","身份证号","户口所在地","政治面貌","工作单位","人事主管单位","报送单位名称","报送类别","联系人","联系电话","入库批号","撤控日期","证件移交日期","撤控原因"],
        &data, "撤控备案表", operator, &["1. 出生日期格式为YYYYMMDD，生日需与身份证号对应。","2. 户口所在地填至区级，省份不加'省'字。","3. 报送单位类别：党政机关,金融系统,教科文卫系统,国有大中型企业单位,其他单位。"])
}

pub fn export_logs(conn: &Connection, cfg: &Config, operator: &str, year: &str) -> (Option<PathBuf>, String) {
    let tz = format!("+{} hours", cfg.tz_offset_hours);
    let rows = db::query_maps(conn, "SELECT * FROM operation_logs WHERE strftime('%Y', datetime(created_at, ?)) = ? ORDER BY created_at", &[T(tz), T(year.to_string())]);
    let data: Vec<Vec<String>> = rows.iter().map(|r| vec![
        helpers::to_local_time(&s(r, "created_at"), "%Y-%m-%d %H:%M:%S", cfg.tz_offset_hours),
        s(r,"operator"),s(r,"action"),s(r,"target_type"),
        { let t = helpers::row_i64(r, "target_id"); if r.get("target_id").map(|v| v.is_null()).unwrap_or(true) { String::new() } else { t.to_string() } },
        s(r,"detail"),s(r,"ip_address"),s(r,"snapshot"),
    ]).collect();
    build_export(cfg, &format!("{year}年操作日志"), &format!("操作日志归档（{year} 年）"),
        &["时间（本地）","操作人","动作","对象类型","对象ID","详情","IP","变更快照(JSON)"],
        &data, &format!("操作日志归档_{year}年"), operator,
        &["1. 时间已按系统配置时区换算为本地时间。","2. 本文件为审计归档副本；数据库中的日志不可删除，仍完整保留。"])
}

// ---- 导入模板 ----
const IMPORT_HEADERS: &[&str] = &[
    "单位","部门","姓名","性别","出生日期","参加工作日期","身份证号","户口所在地","政治面貌","职务（级）或职称",
    "人事主管单位","学历","学位","职称","职级","入党日期","职务（岗位名称）","标记","已告知本人","备注",
];

pub fn generate_import_template() -> Vec<u8> {
    let mut wb = Workbook::new();
    let header_fmt = Format::new().set_bold().set_font_color(Color::White).set_background_color(Color::RGB(0x3A5A7C));
    {
        let ws = wb.add_worksheet();
        let _ = ws.set_name("备案人员导入模板");
        for (i, h) in IMPORT_HEADERS.iter().enumerate() {
            let _ = ws.write_string_with_format(0, i as u16, *h, &header_fmt);
        }
        let example = ["XX单位","XX部门","张三","男","19800103","20000701","330102198001031230","浙江杭州市西湖区","中共党员","处级","人事处","大学本科","学士","副高","处级","20050701","处长","新增","是",""];
        for (i, e) in example.iter().enumerate() {
            let _ = ws.write_string(1, i as u16, *e);
        }
        let widths = [18.0,14.0,10.0,6.0,12.0,12.0,20.0,22.0,14.0,18.0,14.0,12.0,10.0,10.0,10.0,12.0,18.0,8.0,12.0,20.0];
        for (i, w) in widths.iter().enumerate() {
            let _ = ws.set_column_width(i as u16, *w);
        }
    }
    wb.save_to_buffer().unwrap_or_default()
}

// ---- 批量导入解析 ----
pub struct ImportResult {
    pub total: i64,
    pub success: i64,
    pub errors: Vec<serde_json::Value>,
}

pub fn parse_import_file(conn: &Connection, bytes: &[u8], operator: &str) -> Result<ImportResult, String> {
    use calamine::{Reader, Xlsx};
    let cursor = std::io::Cursor::new(bytes.to_vec());
    let mut wb: Xlsx<_> = Xlsx::new(cursor).map_err(|e| e.to_string())?;
    let range = wb.worksheet_range_at(0).ok_or("空工作簿")?.map_err(|e| e.to_string())?;
    let mut res = ImportResult { total: 0, success: 0, errors: vec![] };
    let rows: Vec<Vec<String>> = range.rows().map(|r| r.iter().map(|c| c.to_string().trim().to_string()).collect()).collect();
    if rows.len() <= 1 { return Ok(res); }
    let data_rows = &rows[1..];
    res.total = data_rows.len() as i64;
    let cell = |row: &[String], i: usize| -> String { row.get(i).cloned().unwrap_or_default() };
    for (idx, row) in data_rows.iter().enumerate() {
        let row_no = idx + 2;
        if row.iter().all(|c| c.trim().is_empty()) { res.total -= 1; continue; }
        let mut d = std::collections::HashMap::new();
        d.insert("unit".to_string(), cell(row, 0));
        d.insert("department".into(), cell(row, 1));
        d.insert("name".into(), cell(row, 2));
        d.insert("gender".into(), cell(row, 3));
        d.insert("birth_date".into(), v::parse_date_input(&cell(row, 4)));
        d.insert("work_start_date".into(), v::parse_date_input(&cell(row, 5)));
        d.insert("id_number".into(), cell(row, 6).to_uppercase());
        d.insert("residence".into(), cell(row, 7));
        d.insert("political_status".into(), cell(row, 8));
        d.insert("position_or_title".into(), cell(row, 9));
        d.insert("supervisor_unit".into(), cell(row, 10));
        d.insert("education_code".into(), cell(row, 11));
        d.insert("degree_code".into(), cell(row, 12));
        d.insert("title_code".into(), cell(row, 13));
        d.insert("rank_code".into(), cell(row, 14));
        d.insert("party_join_date".into(), v::parse_date_input(&cell(row, 15)));
        d.insert("position".into(), cell(row, 16));
        d.insert("tag".into(), cell(row, 17));
        d.insert("informed".into(), cell(row, 18));
        d.insert("remarks".into(), cell(row, 19));

        let row_errs = validate_import_row(conn, &d);
        if !row_errs.is_empty() {
            for (field, msg) in row_errs {
                res.errors.push(json!({"row": row_no, "field": field, "message": msg}));
            }
            continue;
        }
        let g = |k: &str| d.get(k).cloned().unwrap_or_default();
        let info_ok = db::exec(conn, "INSERT INTO personnel_info (unit, department, name, gender, birth_date, id_number, work_start_date, education, degree, title, rank, political_status, party_join_date, position, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            &[db::sv_opt(&g("unit")), db::sv_opt(&g("department")), db::sv_opt(&g("name")), db::sv_opt(&g("gender")), db::sv_opt(&g("birth_date")), db::sv_opt(&g("id_number")), db::sv_opt(&g("work_start_date")), db::sv_opt(&g("education_code")), db::sv_opt(&g("degree_code")), db::sv_opt(&g("title_code")), db::sv_opt(&g("rank_code")), db::sv_opt(&g("political_status")), db::sv_opt(&g("party_join_date")), db::sv_opt(&g("position")), T(operator.to_string())]);
        if info_ok.is_err() { res.errors.push(json!({"row": row_no, "field": "—", "message": "数据库写入失败"})); continue; }
        let info_id = conn.last_insert_rowid();
        let (surname, given) = helpers::detect_surname_split(&g("name"));
        let supervisor = { let s = g("supervisor_unit"); if s.is_empty() { "人事处".into() } else { s } };
        let informed = { let s = g("informed"); if s.is_empty() { "是".into() } else { s } };
        let fok = db::exec(conn, "INSERT INTO personnel_filing (personnel_info_id, surname, given_name, gender, birth_date, id_number, residence, political_status, work_unit, position_or_title, supervisor_unit, tag, informed, remarks, operator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            &[I(info_id), T(surname), T(given), db::sv_opt(&g("gender")), db::sv_opt(&g("birth_date")), db::sv_opt(&g("id_number")), T(helpers::normalize_residence(&g("residence"))), db::sv_opt(&g("political_status")), db::sv_opt(&g("unit")), db::sv_opt(&g("position_or_title")), T(supervisor), T("新增".into()), T(informed), db::sv_opt(&g("remarks")), T(operator.to_string())]);
        if fok.is_err() { res.errors.push(json!({"row": row_no, "field": "—", "message": "数据库写入失败"})); continue; }
        res.success += 1;
    }
    Ok(res)
}

fn validate_import_row(conn: &Connection, d: &std::collections::HashMap<String, String>) -> Vec<(String, String)> {
    let mut errs = vec![];
    for (field, label) in [("unit","单位"),("department","部门"),("name","姓名"),("gender","性别"),("birth_date","出生日期"),("id_number","身份证号"),("political_status","政治面貌"),("position","职务（岗位名称）")] {
        if d.get(field).map(|s| s.is_empty()).unwrap_or(true) { errs.push((label.to_string(), format!("{label}为必填项"))); }
    }
    if !errs.is_empty() { return errs; }
    let birth = d.get("birth_date").cloned().unwrap_or_default();
    let id = d.get("id_number").cloned().unwrap_or_default();
    let (ok, msg) = v::validate_date_format(&birth);
    if !ok { return vec![("出生日期".into(), msg)]; }
    let (ok, msg) = v::validate_id_number(&id);
    if !ok { return vec![("身份证号".into(), msg)]; }
    if !v::validate_birth_match(&id, &birth).0 {
        return vec![("出生日期/身份证号".into(), format!("出生日期与身份证号不一致（身份证中为 {}）。", &id[6..14]))];
    }
    let gender = d.get("gender").cloned().unwrap_or_default();
    let (ok, msg) = v::validate_gender_match(&id, &gender);
    if !ok { errs.push(("性别".into(), msg)); }
    if db::query_one(conn, "SELECT id FROM personnel_filing WHERE id_number = ? AND status = 'active'", &[T(id)]).is_some() {
        errs.push(("身份证号".into(), "系统中已存在有效备案记录".into()));
    }
    errs
}

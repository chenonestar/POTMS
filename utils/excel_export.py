"""Excel 导出 — 使用 openpyxl 生成 5 类表单"""
import os
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from database import get_db
from config import Config

# 通用样式
HEADER_FONT = Font(name="微软雅黑", bold=True, size=11, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="1A5276", end_color="1A5276", fill_type="solid")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
CELL_ALIGN = Alignment(vertical="center", wrap_text=True)
THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin"),
)
TITLE_FONT = Font(name="微软雅黑", bold=True, size=14)


def _style_header(ws, headers: list, col_count: int):
    """写入表头并应用样式"""
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
    # 冻结首行
    ws.freeze_panes = "A2"


def _style_data(ws, start_row: int, end_row: int, col_count: int):
    """给数据区加边框和对齐"""
    for row in range(start_row, end_row + 1):
        for col in range(1, col_count + 1):
            cell = ws.cell(row=row, column=col)
            cell.alignment = CELL_ALIGN
            cell.border = THIN_BORDER


def _auto_width(ws, col_count: int, max_width: int = 40):
    """自动列宽"""
    for col in range(1, col_count + 1):
        max_len = 0
        for row in ws.iter_rows(min_col=col, max_col=col, values_only=True):
            for val in row:
                if val:
                    max_len = max(max_len, len(str(val)))
        ws.column_dimensions[get_column_letter(col)].width = min(max_len + 4, max_width)


def _save_and_return(ws, prefix: str, operator: str, notes: list = None):
    """保存到文件，返回路径"""
    # 添加填表说明 Sheet
    if notes:
        ws2 = ws.parent.create_sheet("填表说明")
        for i, note in enumerate(notes, 1):
            ws2.cell(row=i, column=1, value=note).font = Font(name="微软雅黑", size=10)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{ts}_{operator}.xlsx"
    filepath = os.path.join(Config.EXPORT_FOLDER, filename)
    os.makedirs(Config.EXPORT_FOLDER, exist_ok=True)
    ws.parent.save(filepath)
    return filepath, filename


# =========================================================================
# 1. 备案人员信息登记表
# =========================================================================
HEADERS_INFO = [
    "单位", "部门", "姓名", "性别", "出生日期", "身份证号", "参加工作日期",
    "学历", "学位", "职称", "职级", "政治面貌", "入党日期", "职务（岗位名称）",
]

NOTES_INFO = [
    "填表说明：",
    "1. 出生日期格式为YYYYMMDD，需与身份证号对应。",
    "2. 学历、学位、职称、职级、政治面貌从系统数据字典中选择。",
    "3. 中共党员/预备党员须填写入党日期。",
]


def export_personnel_info(operator: str) -> str:
    db = get_db()
    rows = db.execute("SELECT * FROM personnel_info ORDER BY created_at DESC").fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = "备案人员信息登记表"
    _style_header(ws, HEADERS_INFO, len(HEADERS_INFO))

    for i, row in enumerate(rows, 2):
        values = [
            row["unit"], row["department"], row["name"], row["gender"],
            row["birth_date"], row["id_number"] or "", row["work_start_date"] or "",
            row["education"] or "", row["degree"] or "", row["title"] or "",
            row["rank"], row["political_status"], row["party_join_date"] or "",
            row["position"],
        ]
        for col, val in enumerate(values, 1):
            ws.cell(row=i, column=col, value=val)

    _style_data(ws, 2, len(rows) + 1, len(HEADERS_INFO))
    _auto_width(ws, len(HEADERS_INFO))
    return _save_and_return(ws, "备案人员信息登记表", operator, NOTES_INFO)


# =========================================================================
# 2. 因私事出国（境）人员登记备案表
# =========================================================================
HEADERS_FILING = [
    "中文姓", "中文名", "性别", "出生日期", "身份证号", "户口所在地",
    "政治面貌", "工作单位", "职务（级）或职称", "人事主管单位",
    "标记", "已告知本人", "状态", "备注",
]

NOTES_FILING = [
    "填表说明：",
    "1. 姓与名分开填写，特别注意复姓人员。",
    "2. 出生日期格式为YYYYMMDD，生日需与身份证号对应。",
    "3. 工作单位请写全称。",
    "4. 职务/职称栏：处级领导填'处级'或'副处级'，副处级单位班子成员填'正科'，其他人员填'副高'或'正高'。",
    "5. 人事主管单位名称需与印章一致。",
    "6. 户口所在地填至区级，省份不加'省'字，江东区、鄞县统一为'鄞州区'。",
    "7. 标记：新增、更新。",
    "8. 已告知本人：是、否。",
]


def export_personnel_filing(operator: str) -> str:
    db = get_db()
    rows = db.execute("SELECT * FROM personnel_filing ORDER BY created_at DESC").fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = "登记备案表"
    _style_header(ws, HEADERS_FILING, len(HEADERS_FILING))

    for i, row in enumerate(rows, 2):
        values = [
            row["surname"], row["given_name"], row["gender"], row["birth_date"],
            row["id_number"], row["residence"], row["political_status"],
            row["work_unit"], row["position_or_title"], row["supervisor_unit"],
            row["tag"], row["informed"],
            "有效" if row["status"] == "active" else "已撤控",
            row["remarks"] or "",
        ]
        for col, val in enumerate(values, 1):
            ws.cell(row=i, column=col, value=val)

    _style_data(ws, 2, len(rows) + 1, len(HEADERS_FILING))
    _auto_width(ws, len(HEADERS_FILING))
    return _save_and_return(ws, "登记备案表", operator, NOTES_FILING)


# =========================================================================
# 3. 证照登记表
# =========================================================================
HEADERS_CERT = [
    "单位", "部门", "姓名",
    "普通护照", "护照证件号", "护照有效日期", "护照上交日期",
    "港澳通行证", "港澳通行证号", "港澳通有效日期", "港澳通上交日期",
    "台湾通行证", "台湾通行证号", "台湾通有效日期", "台湾通上交日期",
]


def export_certificates(operator: str) -> str:
    db = get_db()
    rows = db.execute("SELECT * FROM certificates ORDER BY updated_at DESC").fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = "证照登记表"
    _style_header(ws, HEADERS_CERT, len(HEADERS_CERT))

    for i, row in enumerate(rows, 2):
        values = [
            row["unit"], row["department"], row["name"],
            "普通护照", row["passport_no"] or "", row["passport_expiry"] or "", row["passport_submit_date"] or "",
            "往来港澳通行证", row["hm_pass_no"] or "", row["hm_pass_expiry"] or "", row["hm_pass_submit_date"] or "",
            "大陆居民往来台湾通行证", row["tw_pass_no"] or "", row["tw_pass_expiry"] or "", row["tw_pass_submit_date"] or "",
        ]
        for col, val in enumerate(values, 1):
            ws.cell(row=i, column=col, value=val)

    _style_data(ws, 2, len(rows) + 1, len(HEADERS_CERT))
    _auto_width(ws, len(HEADERS_CERT))
    return _save_and_return(ws, "证照登记表", operator, [])


# =========================================================================
# 4. 因私出国（境）人员明细表
# =========================================================================
HEADERS_TRAVEL = [
    "单位", "部门", "姓名", "职务", "职称", "身份证号",
    "地点、证照", "类别", "计划出行日期", "批准日期",
    "是否做证", "证件号码", "证件领用日期", "证件归还日期",
]


def export_travel_details(operator: str) -> str:
    db = get_db()
    rows = db.execute("SELECT * FROM travel_details ORDER BY created_at DESC").fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = "出国明细表"
    _style_header(ws, HEADERS_TRAVEL, len(HEADERS_TRAVEL))

    for i, row in enumerate(rows, 2):
        values = [
            row["unit"], row["department"], row["name"], row["position"],
            row["title"] or "", row["id_number"], row["destination_passport"],
            row["category"], row["travel_dates"], row["approval_date"] or "",
            row["need_new_passport"], row["passport_no"] or "",
            row["passport_collect_date"] or "", row["passport_return_date"] or "",
        ]
        for col, val in enumerate(values, 1):
            ws.cell(row=i, column=col, value=val)

    _style_data(ws, 2, len(rows) + 1, len(HEADERS_TRAVEL))
    _auto_width(ws, len(HEADERS_TRAVEL))
    return _save_and_return(ws, "出国明细表", operator, [
        "1. 计划出行日期格式：起始日期-结束日期，如 2023-6-20-2023-6-26。",
        "2. 附件需线下查看系统存储的PDF扫描件。",
    ])


# =========================================================================
# 5. 撤控备案表
# =========================================================================
HEADERS_DEC = [
    "中文姓", "中文名", "性别", "出生日期", "身份证号", "户口所在地",
    "政治面貌", "工作单位", "人事主管单位", "报送单位名称",
    "报送单位类别", "报送单位联系人", "报送单位联系电话",
    "入库批号", "撤控原因",
]


def export_decontrol(operator: str) -> str:
    db = get_db()
    rows = db.execute("SELECT * FROM decontrol_filing ORDER BY created_at DESC").fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = "撤控备案表"
    _style_header(ws, HEADERS_DEC, len(HEADERS_DEC))

    for i, row in enumerate(rows, 2):
        values = [
            row["surname"], row["given_name"], row["gender"], row["birth_date"],
            row["id_number"], row["residence"], row["political_status"],
            row["work_unit"], row["supervisor_unit"], row["submit_unit_name"],
            row["submit_unit_type"], row["submit_contact"], row["submit_phone"],
            row["batch_no"], row["reason"],
        ]
        for col, val in enumerate(values, 1):
            ws.cell(row=i, column=col, value=val)

    _style_data(ws, 2, len(rows) + 1, len(HEADERS_DEC))
    _auto_width(ws, len(HEADERS_DEC))
    return _save_and_return(ws, "撤控备案表", operator, [
        "1. 出生日期格式为YYYYMMDD，生日需与身份证号对应。",
        "2. 户口所在地填至区级，省份不加'省'字。",
        "3. 报送单位类别：党政机关,金融系统,教科文卫系统,国有大中型企业单位,其他单位。",
    ])

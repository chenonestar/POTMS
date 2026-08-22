using System.Data;
using Dapper;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;

namespace POTMS.Services;

/// <summary>Excel 批量导入 —— 逐行校验 + 错误报告。
/// 列顺序与导入模板一致（见 Columns），操作人由登录会话自动写入，不在表格中填写。</summary>
public static class ExcelImport
{
    /// <summary>模板列顺序（与 Python 版 utils/excel_import.py 的 fields 完全一致）。</summary>
    public static readonly (string Field, string Header)[] Columns =
    {
        ("unit", "单位*"), ("department", "部门*"), ("name", "姓名*"), ("gender", "性别*"),
        ("birth_date", "出生日期*(YYYYMMDD)"), ("work_start_date", "参加工作日期"),
        ("id_number", "身份证号*"), ("residence", "户口所在地"), ("political_status", "政治面貌*"),
        ("position_or_title", "职务（级）或职称"), ("supervisor_unit", "人事主管单位"),
        ("education_code", "学历代码"), ("degree_code", "学位代码"), ("title_code", "职称代码"),
        ("rank_code", "职级代码"), ("party_join_date", "入党日期"), ("position", "职务（岗位名称）*"),
        ("tag", "标记"), ("informed", "已告知本人"), ("remarks", "备注"),
    };

    public record RowError(int Row, string Field, string Message);
    public record Result(int Total, int Success, List<RowError> Errors);

    public static Result Parse(IDbConnection cn, Stream stream, string @operator, string? ip)
    {
        var errors = new List<RowError>();
        var rows = ReadRows(stream);
        var total = 0;
        var success = 0;

        foreach (var (rowNumber, cells) in rows)
        {
            if (cells.All(string.IsNullOrWhiteSpace)) continue;   // 跳过完全空行
            total++;

            var data = new Dictionary<string, string?>();
            for (var i = 0; i < Columns.Length; i++)
                data[Columns[i].Field] = i < cells.Count ? (cells[i] ?? "").Trim() : "";
            foreach (var k in new[] { "birth_date", "work_start_date", "party_join_date" })
                data[k] = Validators.ParseDateInput(data[k]);

            var rowErrors = Validate(cn, data);
            if (rowErrors.Count > 0)
            {
                errors.AddRange(rowErrors.Select(e => new RowError(rowNumber, e.Field, e.Message)));
                continue;
            }

            cn.Execute(
                "INSERT INTO personnel_info (unit, department, name, gender, birth_date, id_number, " +
                "work_start_date, education, degree, title, rank, political_status, party_join_date, " +
                "position, operator) VALUES (@unit, @dept, @name, @gender, @birth, @idn, @ws, @edu, " +
                "@deg, @title, @rank, @pol, @pjd, @pos, @op)",
                new
                {
                    unit = data["unit"], dept = data["department"], name = data["name"],
                    gender = data["gender"], birth = data["birth_date"], idn = data["id_number"],
                    ws = data["work_start_date"], edu = data["education_code"], deg = data["degree_code"],
                    title = data["title_code"], rank = data["rank_code"], pol = data["political_status"],
                    pjd = data["party_join_date"], pos = data["position"], op = @operator,
                });
            var infoId = cn.ExecuteScalar<long>("SELECT last_insert_rowid()");

            var (surname, givenName) = Helpers.DetectSurnameSplit(data["name"] ?? "");
            cn.Execute(
                "INSERT INTO personnel_filing (personnel_info_id, surname, given_name, gender, birth_date, " +
                "id_number, residence, political_status, work_unit, position_or_title, supervisor_unit, " +
                "tag, informed, remarks, operator) VALUES (@iid, @sn, @gn, @gender, @birth, @idn, @res, " +
                "@pol, @unit, @pot, @sup, '新增', @informed, @remarks, @op)",
                new
                {
                    iid = infoId, sn = surname, gn = givenName, gender = data["gender"],
                    birth = data["birth_date"], idn = data["id_number"],
                    res = Helpers.NormalizeResidence(data["residence"]),
                    pol = data["political_status"], unit = data["unit"],
                    pot = string.IsNullOrEmpty(data["position_or_title"]) ? data["position"] : data["position_or_title"],
                    sup = string.IsNullOrEmpty(data["supervisor_unit"]) ? "人事处" : data["supervisor_unit"],
                    informed = string.IsNullOrEmpty(data["informed"]) ? "是" : data["informed"],
                    remarks = data["remarks"], op = @operator,
                });
            success++;
        }

        Helpers.LogAction(cn, @operator, ip, "import", "batch",
            detail: $"total={total}, success={success}, errors={errors.Count}");
        return new Result(total, success, errors);
    }

    private static List<(string Field, string Message)> Validate(IDbConnection cn, Dictionary<string, string?> d)
    {
        var errs = new List<(string, string)>();
        foreach (var (field, label) in new[]
                 {
                     ("unit", "单位"), ("department", "部门"), ("name", "姓名"), ("gender", "性别"),
                     ("birth_date", "出生日期"), ("id_number", "身份证号"),
                     ("political_status", "政治面貌"), ("position", "职务（岗位名称）"),
                 })
            if (string.IsNullOrEmpty(d[field])) errs.Add((label, "必填项为空"));

        if (!string.IsNullOrEmpty(d["birth_date"]))
        {
            var (ok, msg) = Validators.ValidateDateFormat(d["birth_date"]);
            if (!ok) errs.Add(("出生日期", msg));
        }
        if (!string.IsNullOrEmpty(d["id_number"]))
        {
            var (ok, msg) = Validators.ValidateIdNumber(d["id_number"]);
            if (!ok) errs.Add(("身份证号", msg));
            else if (!string.IsNullOrEmpty(d["birth_date"]))
            {
                var (ok2, msg2) = Validators.ValidateBirthDateMatch(d["id_number"]!, d["birth_date"]!);
                if (!ok2) errs.Add(("出生日期/身份证号", msg2));
            }
            var dup = cn.QueryFirstOrDefault<long?>(
                "SELECT id FROM personnel_filing WHERE id_number=@n AND status='active'",
                new { n = d["id_number"] });
            if (dup is not null) errs.Add(("身份证号", "系统中已存在有效备案记录"));
        }
        return errs;
    }

    /// <summary>读取首个工作表，返回 (行号, 各列文本)，跳过表头行。</summary>
    private static List<(int RowNumber, List<string?> Cells)> ReadRows(Stream stream)
    {
        var result = new List<(int, List<string?>)>();
        using var doc = SpreadsheetDocument.Open(stream, false);
        var wbPart = doc.WorkbookPart!;
        var sheet = wbPart.Workbook.Descendants<Sheet>().FirstOrDefault();
        if (sheet is null) return result;
        var wsPart = (WorksheetPart)wbPart.GetPartById(sheet.Id!);
        var shared = wbPart.SharedStringTablePart?.SharedStringTable;

        foreach (var row in wsPart.Worksheet.Descendants<Row>())
        {
            var idx = (int)(row.RowIndex?.Value ?? 0);
            if (idx <= 1) continue;   // 跳过表头
            var cells = new List<string?>();
            var expected = 1;
            foreach (var c in row.Elements<Cell>())
            {
                // 补齐被跳过的空单元格，保证列位置对齐
                var colIdx = ColIndex(c.CellReference?.Value ?? "");
                while (expected < colIdx) { cells.Add(""); expected++; }
                cells.Add(CellText(c, shared));
                expected++;
            }
            result.Add((idx, cells));
        }
        return result;
    }

    private static string CellText(Cell c, SharedStringTable? shared)
    {
        if (c.DataType?.Value == CellValues.InlineString)
            return c.InlineString?.Text?.Text ?? "";
        var v = c.CellValue?.Text ?? "";
        if (c.DataType?.Value == CellValues.SharedString && shared is not null
            && int.TryParse(v, out var i) && i < shared.ChildElements.Count)
            return shared.ChildElements[i].InnerText;
        return v;
    }

    private static int ColIndex(string reference)
    {
        var n = 0;
        foreach (var ch in reference)
        {
            if (!char.IsAsciiLetter(ch)) break;
            n = n * 26 + (char.ToUpperInvariant(ch) - 'A' + 1);
        }
        return n == 0 ? 1 : n;
    }

    /// <summary>生成导入模板（表头 + 一行示例 + 说明页）。</summary>
    public static byte[] GenerateTemplate(IDbConnection cn)
    {
        var sample = new List<string?[]>
        {
            new string?[]
            {
                "总部", "人事处", "张三", "男", "19900101", "20120701", "110101199001012133",
                "北京市朝阳区", "群众", "科长", "人事处", "03", "03", "03", "03", "", "科长", "新增", "是", "",
            },
        };
        string Codes(string cat) => string.Join("；",
            Helpers.GetDictOptions(cn, cat).Select(o => $"{o.Code}={o.Value}"));

        using var w = new ExcelWriter();
        w.AddSheet("导入模板", "备案人员批量导入模板",
            Columns.Select(c => c.Header).ToArray(), sample, notes:
            [
                "1. 带 * 的列为必填项；第 2 行为示例数据，导入前请删除。",
                "2. 日期一律填 8 位数字 YYYYMMDD，如 19900101。",
                "3. 出生日期须与身份证号第 7–14 位一致；身份证号须通过校验位算法。",
                "4. 系统中已存在同身份证号的有效备案记录时，该行会被拒绝并在报告中列出。",
                "5. 操作人由当前登录账户自动记录，无需在表格中填写。",
                $"6. 学历代码：{Codes("education")}",
                $"7. 学位代码：{Codes("degree")}",
                $"8. 职称代码：{Codes("title")}",
                $"9. 职级代码：{Codes("rank")}",
            ]);
        return w.ToArray();
    }
}

using System.Data;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;
using A = DocumentFormat.OpenXml.Drawing;
using Xdr = DocumentFormat.OpenXml.Drawing.Spreadsheet;

namespace POTMS.Services;

/// <summary>Excel 生成 —— 使用 DocumentFormat.OpenXml（MIT）。
///
/// 不引入图像库：签名固定为 PNG，尺寸直接从 IHDR 块解析
/// （与 Python 版 utils/excel_export.py 的 _png_size 同一做法）。
/// </summary>
public sealed class ExcelWriter : IDisposable
{
    private readonly MemoryStream _ms = new();
    private readonly SpreadsheetDocument _doc;
    private readonly WorkbookPart _wb;
    private readonly Sheets _sheets;
    private uint _sheetId = 1;

    private const long Emu = 9525;              // 1 px @96dpi
    private const int SignHeightPx = 48;

    public ExcelWriter()
    {
        _doc = SpreadsheetDocument.Create(_ms, SpreadsheetDocumentType.Workbook);
        _wb = _doc.AddWorkbookPart();
        _wb.Workbook = new Workbook();
        _wb.Workbook.AppendChild(new Stylesheet(
            new Fonts(
                new Font(),                                                        // 0 普通
                new Font(new Bold(), new Color { Rgb = "FFFFFFFF" },
                         new FontSize { Val = 11 }, new FontName { Val = "微软雅黑" }),  // 1 表头
                new Font(new Bold(), new FontSize { Val = 16 },
                         new FontName { Val = "微软雅黑" })) { Count = 3 },              // 2 标题
            new Fills(
                new Fill(new PatternFill { PatternType = PatternValues.None }),
                new Fill(new PatternFill { PatternType = PatternValues.Gray125 }),
                new Fill(new PatternFill(new ForegroundColor { Rgb = "FF1A5276" })
                    { PatternType = PatternValues.Solid })) { Count = 3 },
            new Borders(
                new Border(),
                new Border(new LeftBorder { Style = BorderStyleValues.Thin },
                           new RightBorder { Style = BorderStyleValues.Thin },
                           new TopBorder { Style = BorderStyleValues.Thin },
                           new BottomBorder { Style = BorderStyleValues.Thin })) { Count = 2 },
            new CellFormats(
                new CellFormat(),                                                  // 0 默认
                new CellFormat { FontId = 1, FillId = 2, BorderId = 1, ApplyFont = true,
                    ApplyFill = true, ApplyBorder = true,
                    Alignment = new Alignment { Horizontal = HorizontalAlignmentValues.Center,
                        Vertical = VerticalAlignmentValues.Center, WrapText = true } },   // 1 表头
                new CellFormat { BorderId = 1, ApplyBorder = true,
                    Alignment = new Alignment { Vertical = VerticalAlignmentValues.Center,
                        WrapText = true } },                                        // 2 数据
                new CellFormat { FontId = 2, ApplyFont = true,
                    Alignment = new Alignment { Horizontal = HorizontalAlignmentValues.Center,
                        Vertical = VerticalAlignmentValues.Center } }               // 3 标题
            ) { Count = 4 }));
        _sheets = _wb.Workbook.AppendChild(new Sheets());
    }

    /// <summary>写一个工作表。标题行合并居中 + 表头 + 数据，冻结 A3。
    /// signatureCols 给出需要嵌图的列序号（1 起）及其 PNG 数据取值。</summary>
    public void AddSheet(string sheetName, string title, string[] headers, List<string?[]> rows,
                         Dictionary<int, List<byte[]?>>? signatureCols = null, string[]? notes = null)
    {
        var wsPart = _wb.AddNewPart<WorksheetPart>();
        var sheetData = new SheetData();
        var cols = headers.Length;

        // 第1行标题（合并居中）
        var titleRow = new Row { RowIndex = 1, Height = 30, CustomHeight = true };
        titleRow.Append(TextCell("A1", title, 3));
        sheetData.Append(titleRow);

        // 第2行表头
        var headRow = new Row { RowIndex = 2 };
        for (var i = 0; i < cols; i++)
            headRow.Append(TextCell($"{ColName(i + 1)}2", headers[i], 1));
        sheetData.Append(headRow);

        // 数据自第3行起
        var widths = headers.Select(h => (double)DisplayWidth(h) + 4).ToArray();
        for (var r = 0; r < rows.Count; r++)
        {
            var rowIdx = (uint)(r + 3);
            var row = new Row { RowIndex = rowIdx };
            if (signatureCols is not null &&
                signatureCols.Values.Any(v => r < v.Count && v[r] is { Length: > 0 }))
            {
                row.Height = 40; row.CustomHeight = true;
            }
            for (var c = 0; c < cols; c++)
            {
                var v = c < rows[r].Length ? rows[r][c] : "";
                row.Append(TextCell($"{ColName(c + 1)}{rowIdx}", v ?? "", 2));
                widths[c] = Math.Max(widths[c], Math.Min(DisplayWidth(v ?? "") + 4, 40));
            }
            sheetData.Append(row);
        }

        var columns = new Columns();
        for (var i = 0; i < cols; i++)
        {
            var w = widths[i];
            if (signatureCols?.ContainsKey(i + 1) == true) w = 22;   // 签名列按图片宽度留白
            columns.Append(new Column { Min = (uint)(i + 1), Max = (uint)(i + 1),
                Width = w, CustomWidth = true });
        }

        var ws = new Worksheet();
        // 冻结标题行与表头（Pane 是 SheetView 的子元素，需 Append 而非属性赋值）
        var sheetView = new SheetView { WorkbookViewId = 0, TabSelected = _sheetId == 1 };
        sheetView.Append(new Pane
        {
            VerticalSplit = 2, TopLeftCell = "A3",
            ActivePane = PaneValues.BottomLeft, State = PaneStateValues.Frozen,
        });
        ws.Append(new SheetViews(sheetView));
        ws.Append(columns);
        ws.Append(sheetData);
        ws.Append(new MergeCells(new MergeCell { Reference = $"A1:{ColName(cols)}1" }) { Count = 1 });
        wsPart.Worksheet = ws;

        if (signatureCols is { Count: > 0 })
            AddSignatures(wsPart, signatureCols, rows.Count);

        _sheets.Append(new Sheet { Id = _wb.GetIdOfPart(wsPart), SheetId = _sheetId++, Name = sheetName });

        if (notes is { Length: > 0 }) AddNotesSheet(notes);
    }

    private void AddSignatures(WorksheetPart wsPart, Dictionary<int, List<byte[]?>> cols, int rowCount)
    {
        var drawings = wsPart.AddNewPart<DrawingsPart>();
        var anchors = new List<OpenXmlElement>();
        uint shapeId = 1;
        foreach (var (col, blobs) in cols)
        {
            for (var r = 0; r < rowCount && r < blobs.Count; r++)
            {
                var blob = blobs[r];
                if (blob is null || blob.Length == 0) continue;
                int w, h;
                try { (w, h) = PngSize(blob); }
                catch (ArgumentException) { continue; }   // 单张签名损坏不应中断整表导出

                var imgPart = drawings.AddImagePart(ImagePartType.Png);
                using (var s = new MemoryStream(blob)) imgPart.FeedData(s);
                var dispH = SignHeightPx;
                var dispW = Math.Max(1, w * dispH / Math.Max(h, 1));

                anchors.Add(new Xdr.OneCellAnchor(
                    new Xdr.FromMarker
                    {
                        ColumnId = new Xdr.ColumnId((col - 1).ToString()),
                        ColumnOffset = new Xdr.ColumnOffset("0"),
                        RowId = new Xdr.RowId((r + 2).ToString()),   // 数据自第3行(索引2)起
                        RowOffset = new Xdr.RowOffset("0"),
                    },
                    new Xdr.Extent { Cx = dispW * Emu, Cy = dispH * Emu },
                    new Xdr.Picture(
                        new Xdr.NonVisualPictureProperties(
                            new Xdr.NonVisualDrawingProperties { Id = shapeId++, Name = $"Sig{shapeId}" },
                            new Xdr.NonVisualPictureDrawingProperties(new A.PictureLocks { NoChangeAspect = true })),
                        new Xdr.BlipFill(new A.Blip { Embed = drawings.GetIdOfPart(imgPart) },
                                         new A.Stretch(new A.FillRectangle())),
                        new Xdr.ShapeProperties(
                            new A.Transform2D(new A.Offset { X = 0, Y = 0 },
                                              new A.Extents { Cx = dispW * Emu, Cy = dispH * Emu }),
                            new A.PresetGeometry(new A.AdjustValueList()) { Preset = A.ShapeTypeValues.Rectangle })),
                    new Xdr.ClientData()));
            }
        }
        if (anchors.Count == 0) return;
        drawings.WorksheetDrawing = new Xdr.WorksheetDrawing(anchors);
        wsPart.Worksheet.Append(new Drawing { Id = wsPart.GetIdOfPart(drawings) });
    }

    private void AddNotesSheet(string[] notes)
    {
        var part = _wb.AddNewPart<WorksheetPart>();
        var sd = new SheetData();
        var head = new Row { RowIndex = 1 };
        head.Append(TextCell("A1", "填表说明", 1));
        sd.Append(head);
        for (var i = 0; i < notes.Length; i++)
        {
            var row = new Row { RowIndex = (uint)(i + 2) };
            row.Append(TextCell($"A{i + 2}", notes[i], 2));
            sd.Append(row);
        }
        part.Worksheet = new Worksheet(
            new Columns(new Column { Min = 1, Max = 1, Width = 90, CustomWidth = true }), sd);
        _sheets.Append(new Sheet { Id = _wb.GetIdOfPart(part), SheetId = _sheetId++, Name = "填表说明" });
    }

    public byte[] ToArray()
    {
        _wb.Workbook.Save();
        _doc.Dispose();
        return _ms.ToArray();
    }

    public void Dispose() => _ms.Dispose();

    // ---- 工具 ----
    private static Cell TextCell(string reference, string text, uint styleIndex) => new()
    {
        CellReference = reference,
        DataType = CellValues.InlineString,
        StyleIndex = styleIndex,
        InlineString = new InlineString(new Text(text) { Space = SpaceProcessingModeValues.Preserve }),
    };

    private static string ColName(int index)
    {
        var s = "";
        while (index > 0) { index--; s = (char)('A' + index % 26) + s; index /= 26; }
        return s;
    }

    /// <summary>列宽估算：中日韩字符按 2 个字符宽计。</summary>
    private static int DisplayWidth(string s) =>
        s.Sum(ch => ch >= 0x2E80 ? 2 : 1);

    /// <summary>从 PNG 的 IHDR 块解析 (宽, 高)——无需图像库。
    /// PNG 结构：8 字节签名 + 4 字节块长 + 'IHDR' + 宽(4) + 高(4)。</summary>
    public static (int W, int H) PngSize(byte[] d)
    {
        if (d.Length < 24 || d[0] != 0x89 || d[1] != 'P' || d[2] != 'N' || d[3] != 'G'
            || d[12] != 'I' || d[13] != 'H' || d[14] != 'D' || d[15] != 'R')
            throw new ArgumentException("不是有效的 PNG 数据", nameof(d));
        return ((d[16] << 24) | (d[17] << 16) | (d[18] << 8) | d[19],
                (d[20] << 24) | (d[21] << 16) | (d[22] << 8) | d[23]);
    }
}

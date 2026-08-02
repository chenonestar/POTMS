package com.potms.service;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.List;
import java.util.stream.Stream;
import org.apache.poi.ss.usermodel.BorderStyle;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.CellStyle;
import org.apache.poi.ss.usermodel.Drawing;
import org.apache.poi.ss.usermodel.FillPatternType;
import org.apache.poi.ss.usermodel.Font;
import org.apache.poi.ss.usermodel.HorizontalAlignment;
import org.apache.poi.ss.usermodel.IndexedColors;
import org.apache.poi.ss.usermodel.Picture;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.VerticalAlignment;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.util.CellRangeAddress;
import org.apache.poi.ss.util.ImageUtils;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;

/**
 * Excel 导出 — 对应 Python 版 utils/excel_export.py。
 *
 * <p>签名嵌图这块比 Python / .NET 两版都省事：POI 借 JDK 自带的 ImageIO 就能
 * 算出 PNG 原始尺寸，不需要第三方图像库。那两版为了避开 Pillow / ImageSharp，
 * 都得手写 IHDR 字节解析器。
 */
public final class Excel {

    private Excel() {}

    /** 签名图在表格中的展示高度（磅）。 */
    private static final int SIGN_IMG_HEIGHT = 48;

    /** 导出文件保留天数，与备份口径一致。 */
    private static final int RETAIN_DAYS = 30;

    /** 一张工作表的定义。 */
    public record SheetSpec(String title, List<String> headers, List<List<Object>> rows,
                            List<String> notes) {}

    /** 导出结果：落盘路径 + 建议的下载文件名。 */
    public record Result(Path path, String fileName) {}

    /**
     * 生成单表 xlsx 并落盘。
     *
     * @param signColumns 需要嵌签名图的列（0 起）；对应单元格的值须是 byte[] 或 null
     */
    public static Result write(Path exportFolder, SheetSpec spec, String prefix,
                               String operator, List<Integer> signColumns) {
        try (Workbook wb = new XSSFWorkbook()) {
            Sheet sheet = wb.createSheet(safeSheetName(spec.title()));
            styleHeader(wb, sheet, spec.title(), spec.headers());
            fillRows(wb, sheet, spec, signColumns);
            autoWidth(sheet, spec.headers().size());
            appendNotes(wb, sheet, spec);
            return save(wb, exportFolder, prefix, operator);
        } catch (IOException e) {
            throw new IllegalStateException("导出 Excel 失败: " + e.getMessage(), e);
        }
    }

    // ------------------------------------------------------------------

    private static void styleHeader(Workbook wb, Sheet sheet, String title, List<String> headers) {
        // 第 1 行：合并的大标题
        Row titleRow = sheet.createRow(0);
        Cell titleCell = titleRow.createCell(0);
        titleCell.setCellValue(title);
        Font titleFont = wb.createFont();
        titleFont.setBold(true);
        titleFont.setFontHeightInPoints((short) 14);
        CellStyle titleStyle = wb.createCellStyle();
        titleStyle.setFont(titleFont);
        titleStyle.setAlignment(HorizontalAlignment.CENTER);
        titleStyle.setVerticalAlignment(VerticalAlignment.CENTER);
        titleCell.setCellStyle(titleStyle);
        if (headers.size() > 1) {
            sheet.addMergedRegion(new CellRangeAddress(0, 0, 0, headers.size() - 1));
        }
        titleRow.setHeightInPoints(26);

        // 第 2 行：表头
        Row headerRow = sheet.createRow(1);
        CellStyle headerStyle = wb.createCellStyle();
        Font headerFont = wb.createFont();
        headerFont.setBold(true);
        headerStyle.setFont(headerFont);
        headerStyle.setAlignment(HorizontalAlignment.CENTER);
        headerStyle.setVerticalAlignment(VerticalAlignment.CENTER);
        headerStyle.setFillForegroundColor(IndexedColors.GREY_25_PERCENT.getIndex());
        headerStyle.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        border(headerStyle);
        for (int i = 0; i < headers.size(); i++) {
            Cell c = headerRow.createCell(i);
            c.setCellValue(headers.get(i));
            c.setCellStyle(headerStyle);
        }
        // 冻结前两行，滚动时表头常驻
        sheet.createFreezePane(0, 2);
    }

    private static void fillRows(Workbook wb, Sheet sheet, SheetSpec spec,
                                 List<Integer> signColumns) {
        CellStyle dataStyle = wb.createCellStyle();
        dataStyle.setVerticalAlignment(VerticalAlignment.CENTER);
        dataStyle.setWrapText(true);
        border(dataStyle);

        Drawing<?> drawing = sheet.createDrawingPatriarch();
        var helper = wb.getCreationHelper();

        for (int r = 0; r < spec.rows().size(); r++) {
            Row row = sheet.createRow(r + 2);
            List<Object> values = spec.rows().get(r);
            boolean hasImage = false;

            for (int c = 0; c < values.size(); c++) {
                Cell cell = row.createCell(c);
                cell.setCellStyle(dataStyle);
                Object v = values.get(c);

                if (signColumns != null && signColumns.contains(c)) {
                    if (v instanceof byte[] png && png.length > 0) {
                        hasImage = embedSignature(wb, sheet, drawing, helper, png, r + 2, c)
                                || hasImage;
                        if (!hasImage) {
                            cell.setCellValue("[签名图无法读取]");
                        }
                    }
                    continue;   // 签名列不写文本
                }
                if (v != null) {
                    cell.setCellValue(v.toString());
                }
            }
            if (hasImage) {
                row.setHeightInPoints(SIGN_IMG_HEIGHT + 6);
            }
        }
    }

    /**
     * 把签名 PNG 嵌到指定单元格，按固定高度等比缩放。
     *
     * <p>单张失败不中断整表导出——一份签名读不出来，不该让整个月的台账导不出。
     */
    private static boolean embedSignature(Workbook wb, Sheet sheet, Drawing<?> drawing,
                                          org.apache.poi.ss.usermodel.CreationHelper helper,
                                          byte[] png, int rowIdx, int colIdx) {
        try {
            var size = ImageUtils.getImageDimension(new ByteArrayInputStream(png),
                    Workbook.PICTURE_TYPE_PNG);
            int idx = wb.addPicture(png, Workbook.PICTURE_TYPE_PNG);
            var anchor = helper.createClientAnchor();
            anchor.setCol1(colIdx);
            anchor.setRow1(rowIdx);
            Picture pic = drawing.createPicture(anchor, idx);
            pic.resize();
            if (size.height > 0) {
                double ratio = SIGN_IMG_HEIGHT / (double) size.height;
                pic.resize(ratio, ratio);
            }
            return true;
        } catch (RuntimeException e) {
            return false;
        }
    }

    private static void appendNotes(Workbook wb, Sheet sheet, SheetSpec spec) {
        if (spec.notes() == null || spec.notes().isEmpty()) {
            return;
        }
        int start = spec.rows().size() + 4;
        CellStyle noteStyle = wb.createCellStyle();
        Font f = wb.createFont();
        f.setFontHeightInPoints((short) 9);
        f.setColor(IndexedColors.GREY_50_PERCENT.getIndex());
        noteStyle.setFont(f);
        for (int i = 0; i < spec.notes().size(); i++) {
            Row row = sheet.createRow(start + i);
            Cell c = row.createCell(0);
            c.setCellValue(spec.notes().get(i));
            c.setCellStyle(noteStyle);
        }
    }

    private static void autoWidth(Sheet sheet, int colCount) {
        for (int i = 0; i < colCount; i++) {
            try {
                sheet.autoSizeColumn(i);
                int w = sheet.getColumnWidth(i);
                // autoSizeColumn 对中文估得偏窄，统一放宽一档并设上下限
                sheet.setColumnWidth(i, Math.min(Math.max((int) (w * 1.3), 2200), 10000));
            } catch (RuntimeException e) {
                sheet.setColumnWidth(i, 3200);   // 无字体环境下降级为固定宽度
            }
        }
    }

    private static void border(CellStyle s) {
        s.setBorderTop(BorderStyle.THIN);
        s.setBorderBottom(BorderStyle.THIN);
        s.setBorderLeft(BorderStyle.THIN);
        s.setBorderRight(BorderStyle.THIN);
    }

    /** Excel 工作表名不能含 : \ / ? * [ ]，且不超过 31 字符。 */
    private static String safeSheetName(String raw) {
        String s = raw.replaceAll("[:\\\\/?*\\[\\]]", "_");
        return s.length() > 31 ? s.substring(0, 31) : s;
    }

    private static Result save(Workbook wb, Path folder, String prefix, String operator)
            throws IOException {
        pruneOld(folder);
        Files.createDirectories(folder);
        String stamp = java.time.LocalDateTime.now()
                .format(java.time.format.DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"));
        String downloadName = prefix + "_" + stamp + ".xlsx";

        // 落盘名与下载名分开：下载名始终是中文（HTTP 头按 RFC 5987 编码，各平台都正常），
        // 落盘名则要看文件系统编码能不能表示中文。中文 Windows（GBK）可以，
        // 而 C/POSIX 语系的容器与 CI（sun.jnu.encoding=ANSI_X3.4-1968）不行——
        // 直接用中文名会抛 “Malformed input or input contains unmappable characters”。
        Path target = folder.resolve(fsSafe(downloadName, stamp));
        try (OutputStream out = Files.newOutputStream(target)) {
            wb.write(out);
        }
        return new Result(target, downloadName);
    }

    /** 文件系统编码表示不了中文时，退回 ASCII 名，不让导出整体失败。 */
    private static String fsSafe(String preferred, String stamp) {
        String enc = System.getProperty("sun.jnu.encoding");
        try {
            if (enc != null && java.nio.charset.Charset.forName(enc)
                    .newEncoder().canEncode(preferred)) {
                return preferred;
            }
        } catch (RuntimeException ignored) {
            // 编码名无法识别时按不支持处理
        }
        return "export_" + stamp + ".xlsx";
    }

    /** 清理超过保留期的导出文件，避免 exports 目录无限增长。 */
    private static void pruneOld(Path folder) {
        if (!Files.isDirectory(folder)) {
            return;
        }
        long cutoff = System.currentTimeMillis() - RETAIN_DAYS * 86_400_000L;
        try (Stream<Path> s = Files.list(folder)) {
            s.sorted(Comparator.naturalOrder()).forEach(p -> {
                try {
                    if (Files.isRegularFile(p) && Files.getLastModifiedTime(p).toMillis() < cutoff) {
                        Files.deleteIfExists(p);
                    }
                } catch (IOException ignored) {
                    // 单个文件删不掉不影响本次导出
                }
            });
        } catch (IOException ignored) {
            // 目录不可读时跳过清理
        }
    }
}

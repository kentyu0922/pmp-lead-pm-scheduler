# -*- coding: utf-8 -*-
"""Unified PDF export for .mpp schedule plans.

Two output formats:
  --format=table  : A3 landscape table (序号/任务名称/工期/开始/完成/前置)
  --format=gantt  : A3 landscape gantt chart with task bars + milestone diamonds

Usage:
  python export_pdf.py                          # default: table
  python export_pdf.py --format=gantt
  python export_pdf.py --format=table --mpp path/to/file.mpp --out path/to/out.pdf
"""
import os
import sys
import argparse
import datetime

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Table,
                                TableStyle, Paragraph)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ---- paths ----
BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MPP = os.path.join(BASE, "output_mpp", "Shanghai_Xuhui_1000_DnB.mpp")
DEFAULT_TITLE = "上海徐汇区 1000㎡ D&B 办公工装项目"

# ---- shared font registration (lazy) ----
# 原实现在 import 阶段硬编码 C:\Windows\Fonts\msyh.ttc，非 Windows 直接 TTFError 崩溃。
# 现改为：首次真正导出 PDF 时才解析字体；按候选列表逐个尝试，最终兜底 reportlab 内建
# CJK CID 字体 STSong-Light（无需任何字体文件，任何平台可用）。
# 可用环境变量 PMP_PDF_FONT 指定 .ttf/.ttc 路径覆盖。
FONT = r"C:\Windows\Fonts\msyh.ttc"          # 保留旧常量名（Windows 首选：微软雅黑）
FONT_CN = "CN"                                # 实际注册的常规字体名（_ensure_fonts 可能改写）
FONT_CN_BOLD = "CN-Bold"                      # 实际注册的粗体字体名
FONT_SOURCE = None                            # 解析结果说明（用于日志/测试）
_FONTS_READY = False

# (路径, 常规 subfontIndex, 粗体 subfontIndex)；.ttc 之外的单字体文件 bold 复用同一字形
_FONT_CANDIDATES = [
    (FONT, 0, 1),                                                   # Windows 微软雅黑
    (r"C:\Windows\Fonts\simhei.ttf", 0, 0),                          # Windows 黑体
    ("/System/Library/Fonts/PingFang.ttc", 0, 0),                    # macOS
    ("/System/Library/Fonts/STHeiti Light.ttc", 0, 0),               # macOS (older)
    ("/Library/Fonts/Arial Unicode.ttf", 0, 0),                      # macOS (Office)
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0, 0),        # Debian/Ubuntu fonts-wqy-microhei
    ("/usr/share/fonts/wqy-microhei/wqy-microhei.ttc", 0, 0),        # Fedora/Arch
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0, 0),
    ("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 0, 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 0, 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0, 0),
]


def _try_register_ttf(path, idx_regular, idx_bold):
    """尝试用一个字体文件注册 CN / CN-Bold；成功返回 True，失败(不存在/CFF轮廓等)返回 False。"""
    if not path or not os.path.exists(path):
        return False
    try:
        pdfmetrics.registerFont(TTFont("CN", path, subfontIndex=idx_regular))
        try:
            pdfmetrics.registerFont(TTFont("CN-Bold", path, subfontIndex=idx_bold))
        except Exception:
            pdfmetrics.registerFont(TTFont("CN-Bold", path, subfontIndex=idx_regular))
        return True
    except Exception:
        return False


def _ensure_fonts():
    """惰性注册中文字体。幂等；只在真正构建 PDF 时调用，import 阶段零副作用。"""
    global _FONTS_READY, FONT_CN, FONT_CN_BOLD, FONT_SOURCE
    if _FONTS_READY:
        return FONT_CN, FONT_CN_BOLD

    candidates = []
    env_font = os.environ.get("PMP_PDF_FONT")
    if env_font:
        candidates.append((env_font, 0, 0))
    candidates.extend(_FONT_CANDIDATES)

    for path, i_reg, i_bold in candidates:
        if _try_register_ttf(path, i_reg, i_bold):
            FONT_CN, FONT_CN_BOLD = "CN", "CN-Bold"
            FONT_SOURCE = path
            break
    else:
        # 兜底：reportlab 内建 CJK CID 字体（Identity-H，无需外部文件；粗体退化为同字形）
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        FONT_CN = FONT_CN_BOLD = "STSong-Light"
        FONT_SOURCE = "reportlab builtin CID font STSong-Light (no CJK TTF found)"

    _FONTS_READY = True
    return FONT_CN, FONT_CN_BOLD


# ============================================================
# Shared: read tasks from .mpp via COM
# ============================================================
def read_tasks(mpp_path):
    """Read all tasks (including summary) from an .mpp file.

    Returns (title, tasks) where each task dict carries fields needed by
    both the table and gantt builders.

    Windows-only（MS Project COM）。非 Windows 调用会抛 MSProjectUnavailableError；
    pywin32 只在这里延迟 import，保证本模块可在任意平台被 import。
    """
    try:
        from core.msp_session import require_win32
    except ImportError:  # 独立运行 exporters/ 时的兜底
        sys.path.insert(0, os.path.dirname(BASE))
        from core.msp_session import require_win32
    require_win32()
    import pythoncom  # noqa: WPS433 — lazy, Windows-only
    import win32com.client  # noqa: WPS433 — lazy, Windows-only

    pythoncom.CoInitialize()
    app = win32com.client.DispatchEx("MSProject.Application")
    app.Visible = False
    app.DisplayAlerts = False
    app.FileOpen(os.path.abspath(mpp_path))
    proj = app.Projects(1)
    try:
        app.OutlineShowAllTasks()
    except Exception:
        pass
    # MPP 中的日期已在 build_mpp 阶段通过直接写入 Start 确保正确，
    # 此处不再尝试重算（app.Calculate() 在 COM 中不可用，且"触摸" Duration
    # 可能触发自动重算覆盖已写入的约束日期）。
    # 仅确保自动计算模式，防止读取到过时缓存。
    try:
        app.Calculation = 0  # pjAutomatic
    except Exception:
        pass
    title = (getattr(proj, "Title", "") or "").strip()

    tasks = []
    for t in proj.Tasks:
        if t is None:
            continue
        try:
            lvl = int(t.OutlineLevel)
        except Exception:
            lvl = 1
        onum = (getattr(t, "OutlineNumber", "") or "").strip() or str(t.ID)
        name = t.Name or ""
        dur_min = t.Duration if t.Duration is not None else 0
        dur_days = int(round(dur_min / 480)) if dur_min else 0

        start_str = str(t.Start)[:10] if t.Start else ""
        finish_str = str(t.Finish)[:10] if t.Finish else ""
        sd = fd = None
        if start_str:
            try:
                sd = datetime.date.fromisoformat(start_str)
            except ValueError:
                pass
        if finish_str:
            try:
                fd = datetime.date.fromisoformat(finish_str)
            except ValueError:
                pass

        preds = []
        try:
            ptc = t.PredecessorTasks
            for i in range(1, ptc.Count + 1):
                try:
                    pt = ptc(i).Predecessor
                except Exception:
                    pt = ptc(i)
                pn = (getattr(pt, "OutlineNumber", "") or "").strip()
                if not pn:
                    pn = str(getattr(pt, "ID", ""))
                if pn:
                    preds.append(pn)
        except Exception:
            pass

        tasks.append({
            "level": lvl, "no": onum, "name": name,
            "dur": dur_days, "start": start_str, "finish": finish_str,
            "sd": sd, "fd": fd,
            "pred": ", ".join(preds),
            "milestone": bool(getattr(t, "Milestone", False)),
            "summary": bool(getattr(t, "Summary", False)),
        })

    app.FileCloseEx(0)
    app.Quit()
    pythoncom.CoUninitialize()
    return title, tasks


# ============================================================
# Format 1: Table PDF
# ============================================================
def build_table_pdf(tasks, out_path, title=DEFAULT_TITLE):
    _ensure_fonts()
    doc = BaseDocTemplate(out_path, pagesize=landscape(A3),
                          leftMargin=36, rightMargin=36, topMargin=70, bottomMargin=58,
                          title=title)
    usable = doc.width
    fixed = 46 + 56 + 80 + 80 + 90
    name_w = usable - fixed
    colWidths = [46, name_w, 56, 80, 80, 90]

    header_style = ParagraphStyle("hdr", fontName=FONT_CN_BOLD, fontSize=9,
                                   leading=11, textColor=colors.black, alignment=TA_CENTER)
    name_base = ParagraphStyle("nb", fontName=FONT_CN, fontSize=8.5, leading=11,
                               textColor=colors.black, alignment=TA_LEFT)
    name_bold = ParagraphStyle("nb_b", parent=name_base, fontName=FONT_CN_BOLD)
    cell_center = ParagraphStyle("cc", fontName=FONT_CN, fontSize=8.5, leading=11,
                                 textColor=colors.black, alignment=TA_CENTER)

    def name_cell(task):
        indent = (task["level"] - 1) * 14
        st = ParagraphStyle("n_%s" % task["no"], parent=(name_bold if task["summary"] else name_base),
                            leftIndent=indent)
        return Paragraph(escape(task["name"]), st)

    header = [Paragraph("序号", header_style), Paragraph("任务名称", header_style),
              Paragraph("工期", header_style), Paragraph("开始时间", header_style),
              Paragraph("完成时间", header_style), Paragraph("前置任务", header_style)]
    data = [header]
    for t in tasks:
        if t["milestone"]:
            dur_txt = "0 天"
        elif t["dur"]:
            dur_txt = "%d 天" % t["dur"]
        else:
            dur_txt = "—"
        data.append([
            Paragraph(t["no"], cell_center),
            name_cell(t),
            Paragraph(dur_txt, cell_center),
            Paragraph(t["start"], cell_center),
            Paragraph(t["finish"], cell_center),
            Paragraph(t["pred"], cell_center),
        ])

    ts = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9D9D9")),
        ("FONTNAME", (0, 0), (-1, 0), FONT_CN_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBBBBB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F4F4")]),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ])
    table = Table(data, colWidths=colWidths, repeatRows=1)
    table.setStyle(ts)

    def on_page(canvas_obj, d):
        canvas_obj.saveState()
        w, h = d.pagesize
        canvas_obj.setFont(FONT_CN_BOLD, 11)
        canvas_obj.setFillColor(colors.black)
        canvas_obj.drawString(36, h - 38, "%s — 进度计划 (V3)" % title)
        canvas_obj.setFont(FONT_CN, 8)
        canvas_obj.drawRightString(w - 36, h - 38,
                                   "导出日期：%s    第 %d 页" % (datetime.date.today().isoformat(), d.page))
        canvas_obj.setStrokeColor(colors.HexColor("#888888"))
        canvas_obj.setLineWidth(0.6)
        canvas_obj.line(36, h - 45, w - 36, h - 45)
        canvas_obj.setFont(FONT_CN, 7.5)
        canvas_obj.setFillColor(colors.HexColor("#444444"))
        legend = ("图例：任务名称缩进表示层级深度（层级越深缩进越多）；名称前缀 [M] 为里程碑；"
                  "工期以工作日计；\u201c前置任务\u201d为上游任务序号（WBS 编号）。本表由 MPP 原始排程导出，仅供打印审阅。")
        canvas_obj.drawString(36, 30, legend)
        canvas_obj.line(36, 42, w - 36, 42)
        canvas_obj.restoreState()

    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=on_page)])
    doc.build([table])


# ============================================================
# Format 2: Gantt PDF
# ============================================================
# gantt-specific colors
NAVY = HexColor("#1F4E79")
GOLD = HexColor("#BF9000")
SLATE = HexColor("#404040")
BLUE = HexColor("#2E5C8A")
GRID = HexColor("#D9D9D9")
ZEBRA = HexColor("#F5F7FA")
INK = colors.black

LEFT_COLS = [
    ("序号",     0,   38),
    ("任务名称", 42,  196),
    ("工期",     242, 34),
    ("开始时间", 280, 64),
    ("完成时间", 348, 64),
    ("前置任务", 416, 50),
]
LW = 470


def build_gantt_pdf(title, tasks, out_path):
    _ensure_fonts()
    # filter tasks that have valid dates
    gantt_tasks = [t for t in tasks if t["sd"] and t["fd"]]
    if not gantt_tasks:
        print("[WARN] No tasks with valid start/finish dates for gantt chart")
        return

    W, H = landscape(A3)
    c = canvas.Canvas(out_path, pagesize=(W, H))
    margin_x = 36
    header_h = 52
    footer_h = 46
    axis_h = 20
    row_h = 14
    chart_x0 = margin_x + LW
    GW = W - margin_x - chart_x0

    min_d = min(t["sd"] for t in gantt_tasks)
    max_d = max(t["fd"] for t in gantt_tasks)
    pad = datetime.timedelta(days=4)
    min_d -= pad
    max_d += pad
    total = (max_d - min_d).days
    pxd = GW / total

    y_top = H - header_h - axis_h
    y_bot = footer_h + 6
    max_rows = int((y_top - y_bot) / row_h)
    today = datetime.date.today().isoformat()

    pages = [gantt_tasks[i:i + max_rows] for i in range(0, len(gantt_tasks), max_rows)]

    for pi, chunk in enumerate(pages, 1):
        # ---- header ----
        c.setFillColor(NAVY)
        c.rect(0, H - header_h, W, header_h, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(FONT_CN_BOLD, 15)
        c.drawString(margin_x, H - header_h + 16, title)
        c.setFont(FONT_CN, 8)
        c.drawRightString(W - margin_x, H - header_h + 18,
                          "导出日期：%s    第 %d 页 / 共 %d 页" % (today, pi, len(pages)))
        c.setStrokeColor(GOLD)
        c.setLineWidth(1.2)
        c.line(0, H - header_h, W, H - header_h)

        # ---- left table header ----
        c.setFillColor(NAVY)
        c.rect(0, y_top, chart_x0, axis_h, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(FONT_CN_BOLD, 8)
        for ctitle, cx, cw in LEFT_COLS:
            c.drawString(margin_x + cx, y_top + 6, ctitle)
        c.setStrokeColor(NAVY)
        c.setLineWidth(0.8)
        c.line(chart_x0, y_bot, chart_x0, H - header_h)

        # ---- month grid ----
        d = datetime.date(min_d.year, min_d.month, 1)
        while d <= max_d:
            nx = chart_x0 + (d - min_d).days * pxd
            c.setStrokeColor(GRID)
            c.setLineWidth(0.4)
            c.line(nx, y_bot, nx, y_top)
            c.setFillColor(NAVY)
            c.setFont(FONT_CN, 7)
            c.drawString(nx + 2, y_top + 5, "%d-%02d" % (d.year, d.month))
            ny = d.year + (1 if d.month == 12 else 0)
            nm = 1 if d.month == 12 else d.month + 1
            d = datetime.date(ny, nm, 1)

        # ---- task rows ----
        y = y_top
        for ri, t in enumerate(chunk):
            if ri % 2 == 1:
                c.setFillColor(ZEBRA)
                c.rect(margin_x, y - row_h, LW, row_h, fill=1, stroke=0)
            cy = y - row_h / 2
            indent = (t["level"] - 1) * 10
            is_bold = t["summary"]
            c.setFont(FONT_CN, 7.5)
            c.setFillColor(INK)
            c.drawString(margin_x + LEFT_COLS[0][1], cy - 3, t["no"])
            avail = LEFT_COLS[1][2] - indent - 4
            maxc = max(6, int(avail / 7.5))
            nm = t["name"]
            if len(nm) > maxc:
                nm = nm[:maxc - 1] + "…"
            c.setFont(FONT_CN_BOLD if is_bold else FONT_CN, 7.5)
            c.drawString(margin_x + LEFT_COLS[1][1] + indent, cy - 3, nm)
            c.setFont(FONT_CN, 7.5)
            dur_str = ("%d天" % t["dur"]) if t["dur"] else ""
            c.drawString(margin_x + LEFT_COLS[2][1], cy - 3, dur_str)
            c.drawString(margin_x + LEFT_COLS[3][1], cy - 3, t["sd"].isoformat())
            c.drawString(margin_x + LEFT_COLS[4][1], cy - 3, t["fd"].isoformat())
            pr = t["pred"]
            if len(pr) > 6:
                pr = pr[:5] + "…"
            c.drawString(margin_x + LEFT_COLS[5][1], cy - 3, pr)

            # gantt bar
            sx = chart_x0 + (t["sd"] - min_d).days * pxd
            if t["milestone"]:
                ex = sx
                dd = 5
                c.setFillColor(GOLD)
                p = c.beginPath()
                p.moveTo(ex, cy - dd)
                p.lineTo(ex + dd, cy)
                p.lineTo(ex, cy + dd)
                p.lineTo(ex - dd, cy)
                p.close()
                c.drawPath(p, fill=1, stroke=0)
                c.setFont(FONT_CN, 7)
                c.setFillColor(INK)
                c.drawString(ex + 7, cy - 3, t["sd"].isoformat())
            elif t["summary"]:
                ex = chart_x0 + (t["fd"] - min_d).days * pxd
                c.setFillColor(SLATE)
                c.rect(sx, cy - 3, max(ex - sx, 2), 6, fill=1, stroke=0)
                c.setFont(FONT_CN, 7)
                c.setFillColor(INK)
                c.drawCentredString((sx + ex) / 2, cy - 11,
                                    "%s ~ %s" % (t["sd"].isoformat(), t["fd"].isoformat()))
            else:
                ex = chart_x0 + (t["fd"] - min_d).days * pxd
                c.setFillColor(BLUE)
                c.roundRect(sx, cy - 3, max(ex - sx, 2), 6, 2, fill=1, stroke=0)
            y -= row_h

        # ---- footer ----
        c.setFillColor(NAVY)
        c.rect(0, 0, W, footer_h, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(FONT_CN, 8)
        legend = ("图例：◆ 金色菱形 = 里程碑（标注开始/结束日期）   |   ▬ 深灰粗条 = 阶段/汇总节点（标注起止）"
                  "   |   ▭ 蓝色条 = 普通任务   |   名称缩进 = 任务层级")
        c.drawString(margin_x, footer_h / 2 - 3, legend)
        c.showPage()

    c.save()


def _normalize_tasks_from_dict(task_list):
    """Normalize raw solver task dicts into the format expected by PDF builders."""
    tasks = []
    for t in task_list:
        lvl = int(t.get("outline_level", t.get("level", 3)))
        onum = str(t.get("id", ""))
        name = str(t.get("name", ""))
        dur = t.get("duration_days", t.get("duration", 0))
        dur_days = int(round(float(dur))) if dur else 0
        start_str = str(t.get("start", ""))[:10]
        finish_str = str(t.get("finish", ""))[:10]
        sd = fd = None
        if start_str and len(start_str) >= 10:
            try:
                sd = datetime.date.fromisoformat(start_str)
            except Exception:
                pass
        if finish_str and len(finish_str) >= 10:
            try:
                fd = datetime.date.fromisoformat(finish_str)
            except Exception:
                pass
        preds = str(t.get("predecessors", ""))
        is_ms = bool(t.get("milestone", False)) or dur_days == 0
        is_sum = lvl <= 2 or bool(t.get("summary", False))
        tasks.append({
            "level": lvl, "no": onum, "name": name,
            "dur": dur_days, "start": start_str, "finish": finish_str,
            "sd": sd, "fd": fd,
            "pred": preds,
            "milestone": is_ms,
            "summary": is_sum,
        })
    return tasks


def export_pdf(mpp_or_tasks=DEFAULT_MPP, out_path: str = None, format: str = "table", title: str = None) -> str:
    """Export schedule to PDF format ('table' or 'gantt').
    Accepts either an .mpp file path (str) or a list of task dicts (list).
    """
    if isinstance(mpp_or_tasks, (list, tuple)):
        tasks = _normalize_tasks_from_dict(mpp_or_tasks)
        if not title:
            title = DEFAULT_TITLE
        if not out_path:
            out_path = os.path.join(BASE, "output_mpp", "Schedule_Report.pdf")
    else:
        mpp_path = str(mpp_or_tasks)
        if not out_path:
            base, _ = os.path.splitext(mpp_path)
            suffix = "_gantt" if format == "gantt" else ""
            out_path = base + suffix + ".pdf"

        mpp_title, tasks = read_tasks(mpp_path)
        if not title:
            title = mpp_title or DEFAULT_TITLE

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    if format == "gantt":
        build_gantt_pdf(title, tasks, out_path)
    else:
        build_table_pdf(tasks, out_path, title=title)
    return out_path


# ============================================================
# CLI entry point
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Export .mpp schedule to PDF")
    parser.add_argument("--format", choices=["table", "gantt"], default="table",
                        help="PDF output format (default: table)")
    parser.add_argument("--mpp", default=DEFAULT_MPP,
                        help="Path to .mpp file (default: Shanghai_Xuhui_1000_DnB.mpp)")
    parser.add_argument("--out", default=None,
                        help="Output PDF path (default: auto-derived from --mpp and --format)")
    args = parser.parse_args()

    if args.out:
        out_path = args.out
    else:
        base, _ = os.path.splitext(args.mpp)
        suffix = "_gantt" if args.format == "gantt" else ""
        out_path = base + suffix + ".pdf"

    print("Reading MPP:", args.mpp)
    title, tasks = read_tasks(args.mpp)
    if not title:
        title = DEFAULT_TITLE
    print("Project title:", title, "| tasks:", len(tasks))

    if args.format == "table":
        build_table_pdf(tasks, out_path, title=title)
    else:
        build_gantt_pdf(title, tasks, out_path)

    print("PDF written:", out_path, "| size:", os.path.getsize(out_path), "bytes")


if __name__ == "__main__":
    main()

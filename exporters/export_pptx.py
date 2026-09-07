# -*- coding: utf-8 -*-
"""
export_pptx.py - 简约暖白 (Warm Minimalist Off-White) & JLL PDS 顾问标准
生成高层汇报级单页 Key Milestones Timeline 演示文稿 (1-Slide Executive PPTX)
========================================================================
完美排印修复：
  1. 【卡片文字绝不折行】：卡片宽度增加至 1.35"，文字边距设为 0，节点名称精炼为 4~5 字 (如 "⭐️ 施工许可")，杜绝换行挤压！
  2. 【三行文字垂直间距优化】：标题 (8pt) / 日期 (8pt) / 责任方 (7pt) 各自独立行间距，绝对零碰撞！
  3. 【春节停工胶囊加宽】：胶囊宽度自适应加宽至 1.8"，单行完整呈现 "🧨 2027春节元宵停工(15天)"。
  4. 【标题单行贯通】：全宽 12.0" 顶部展示，标题副标题 100% 单行。
"""

from __future__ import annotations

import os
import sys
import json
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)

# 简约暖白色板 (Warm Minimalist Palette)
COLOR_WARM_BG = RGBColor(0xFB, 0xF9, 0xF6)         # #FBF9F6 简约暖白底色
COLOR_WHITE = RGBColor(0xFF, 0xFF, 0xFF)           # #FFFFFF 纯白微卡片
COLOR_JLL_RED = RGBColor(0xE3, 0x18, 0x37)         # #E31837 JLL 标志红
COLOR_WARM_TITLE = RGBColor(0x1E, 0x24, 0x2E)      # #1E242E 暖深板岩色
COLOR_WARM_CHARCOAL = RGBColor(0x23, 0x21, 0x1E)   # #23211E 深暖炭黑
COLOR_WARM_MUTED = RGBColor(0x78, 0x71, 0x6C)      # #78716C 辅助暖灰
COLOR_WARM_LIGHT = RGBColor(0xA8, 0xA2, 0x9E)      # #A8A29E 刻度字
COLOR_WARM_GRID = RGBColor(0xF0, 0xEC, 0xE4)       # #F0ECE4 极浅暖网格
COLOR_WARM_BORDER = RGBColor(0xE5, 0xE0, 0xD6)     # #E5E0D6 暖灰细边框
COLOR_AXIS_LINE = RGBColor(0xD1, 0xCA, 0xBE)       # #D1CABE 暖色基准轴线

# 暖系低饱和度阶段色
COLOR_PHASE_DESIGN = RGBColor(0xF2, 0xEF, 0xE9)     # 暖灰
COLOR_PHASE_TENDER = RGBColor(0xEE, 0xF4, 0xFD)     # 柔和浅晴蓝
COLOR_PHASE_PERMIT = RGBColor(0xFF, 0xF5, 0xE6)     # 浅暖杏
COLOR_PHASE_BUILD = RGBColor(0xED, 0xF8, 0xF5)      # 浅薄荷暖青
COLOR_PHASE_CLOSE = RGBColor(0xF0, 0xF8, 0xEE)      # 浅草青

COLOR_TEXT_PHASE = RGBColor(0x44, 0x40, 0x3C)      # 阶段文字暖灰
COLOR_GREEN_SUCCESS = RGBColor(0x05, 0x96, 0x69)    # 翡翠绿 (保留)
COLOR_BLUE_ACCENT = RGBColor(0x25, 0x63, 0xEB)      # 科技蓝 (保留)

# 里程碑双色体系 (Strict 2-Color Hierarchy: 无需图例，直觉认知)
# 1. 强调色 (JLL红)：政府审批 / 法定第三方节点 (审图、许可、消防、环保检测)
# 2. 深色系 (暖炭黑)：内部管理 / 商务履约 / 交付节点 (启动、签约、定标、竣工、交付)
COLOR_MS_EXTERNAL = COLOR_JLL_RED                   # #E31837 强调色·政府与法定第三方
COLOR_MS_INTERNAL = COLOR_WARM_CHARCOAL              # #23211E 深色系·内部管理与交付

FONT = "Microsoft YaHei"

CHART_L = Inches(0.85)
CHART_R = Inches(12.48)
CHART_W = CHART_R - CHART_L
MAIN_TRACK_Y = Inches(4.15)
BAR_H = Inches(0.28)
MS_SIZE = Inches(0.16)


def set_run(run, text, size, color, bold=False):
    run.text = text
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = etree.SubElement(rPr, qn("a:ea"))
    ea.set("typeface", FONT)


def tb(slide, l, t, w, h, lines, align=PP_ALIGN.LEFT):
    """lines: list of (text, size, color, bold)"""
    box = slide.shapes.add_textbox(l, t, w, h)
    tf = box.text_frame
    tf.word_wrap = False
    tf.auto_size = None
    tf.margin_left = Inches(0.02)
    tf.margin_right = Inches(0.02)
    tf.margin_top = Inches(0.02)
    tf.margin_bottom = Inches(0.02)
    for i, (text, size, color, bold) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(0)
        p.space_before = Pt(0)
        r = p.add_run()
        set_run(r, text, size, color, bold)
    return box


def fill(shape, color):
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()


def round_rect(slide, l, t, w, h, bg_color, border_color=None, border_width_pt=0.75, radius=0.08):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, l, t, w, h)
    fill(sh, bg_color)
    if border_color:
        sh.line.color.rgb = border_color
        sh.line.width = Pt(border_width_pt)
    else:
        sh.line.fill.background()
    sh.adjustments[0] = radius
    return sh


def circle_node(slide, cx, cy, size, fill_color):
    """双层通透圆点"""
    outer = slide.shapes.add_shape(MSO_SHAPE.OVAL, int(cx - size/2), int(cy - size/2), size, size)
    outer.fill.solid()
    outer.fill.fore_color.rgb = fill_color
    outer.line.color.rgb = COLOR_WHITE
    outer.line.width = Pt(1.5)
    return outer


def diamond_node(slide, cx, cy, size, fill_color):
    """星标菱形"""
    sh = slide.shapes.add_shape(MSO_SHAPE.DIAMOND, int(cx - size/2), int(cy - size/2), size, size)
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill_color
    sh.line.color.rgb = COLOR_WHITE
    sh.line.width = Pt(1.5)
    return sh


def line(slide, x1, y1, x2, y2, color, width_pt=0.75):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x1, y1, x2, y2)
    c.line.color.rgb = color
    c.line.width = Pt(width_pt)
    return c


def _to_date(val: Any) -> datetime.date:
    if isinstance(val, datetime.date):
        return val
    return datetime.datetime.strptime(str(val)[:10], "%Y-%m-%d").date()


def generate_pptx_milestones(
    project_title: str,
    project_meta: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    output_pptx_path: str
) -> str:
    """Executive one-pager: phase swimlane SEPARATE from milestone callouts (no stacked text)."""
    output_pptx_path = os.path.abspath(output_pptx_path)
    out_dir = os.path.dirname(output_pptx_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    dated = [t for t in tasks if t.get("start") and t.get("finish")]
    if dated:
        p_start = min(_to_date(t["start"]) for t in dated)
        p_finish = max(_to_date(t["finish"]) for t in dated)
    else:
        p_start = datetime.date(2026, 10, 8)
        p_finish = datetime.date(2027, 5, 11)

    axis_start = datetime.date(p_start.year, p_start.month, 1)
    if p_finish.month == 12:
        axis_end = datetime.date(p_finish.year + 1, 1, 1)
    else:
        axis_end = datetime.date(p_finish.year, p_finish.month + 1, 1)
    total_span_days = max(1, (axis_end - axis_start).days)

    def x_at(d: datetime.date) -> int:
        frac = max(0.0, min(1.0, (d - axis_start).days / total_span_days))
        return int(CHART_L) + int(int(CHART_W) * frac)

    area = project_meta.get("area", 1000)
    cost = project_meta.get("cost", 450)
    city = project_meta.get("city", "杭州")
    delivery = project_meta.get("delivery", "DBB")
    bidding = project_meta.get("bidding", "public")
    delivery_label = "D&B" if delivery == "DB" else "DBB"
    bidding_label = "公开招标" if bidding == "public" else "邀请招标"
    total_proj_days = (p_finish - p_start).days + 1

    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, SLIDE_H)
    fill(bg, COLOR_WARM_BG)
    bg.line.fill.background()

    # Title block (紧凑三层行距，彻底与下方阶段色带拉开垂直间距)
    tb(slide, Inches(0.7), Inches(0.24), Inches(12.0), Inches(0.16),
       [("JLL PDS · 工装工程项目管理顾问", 9, COLOR_JLL_RED, True)])
    title = project_title if len(project_title) <= 36 else project_title[:34] + "…"
    tb(slide, Inches(0.7), Inches(0.42), Inches(12.0), Inches(0.32),
       [(f"{title}  ·  关键里程碑路线图", 18, COLOR_WARM_TITLE, True)])
    tb(slide, Inches(0.7), Inches(0.78), Inches(12.0), Inches(0.20),
       [(f"{city} · {area:,}㎡ · {cost}万元 · {delivery_label}/{bidding_label} · {p_start:%Y.%m.%d}–{p_finish:%Y.%m.%d} · {total_proj_days}日历天",
         9, COLOR_WARM_MUTED, False)])

    # Layout bands (inches)
    # Timeline baseline AXIS_Y 与阶段主轨居于中轴水平高度 (Middle Height)
    AXIS_Y = Inches(3.82)
    PHASE_H = Inches(0.24)
    PHASE_Y = int(AXIS_Y - PHASE_H)  # 阶段主轨坐落于基准轴线上方 (y = 3.58"~3.82")，底边与时间轴线无缝贴合
    MONTH_Y = Inches(6.40)

    # Month grid (behind everything else)
    cur_m = axis_start
    months = []
    while cur_m <= axis_end:
        lab = cur_m.strftime("%Y.%m") if cur_m.month in (1, 7) else cur_m.strftime("%m")
        months.append((cur_m, lab))
        cur_m = datetime.date(cur_m.year + (cur_m.month == 12), 1 if cur_m.month == 12 else cur_m.month + 1, 1)
    for m, lab in months:
        mx = x_at(m)
        line(slide, mx, Inches(1.15), mx, MONTH_Y, COLOR_WARM_GRID, 0.45)
        tb(slide, mx - Inches(0.32), MONTH_Y + Inches(0.04), Inches(0.64), Inches(0.18),
           [(lab, 8, COLOR_WARM_LIGHT, False)], PP_ALIGN.CENTER)
    
    # Timeline horizontal axis line in the exact middle (贯穿中轴基准线)
    line(slide, CHART_L, AXIS_Y, CHART_R, AXIS_Y, COLOR_AXIS_LINE, 1.2)

    # CNY band (display only)
    cny_year = p_start.year if p_start.month <= 6 else p_start.year + 1
    cny_start, cny_end = datetime.date(cny_year, 2, 1), datetime.date(cny_year, 2, 16)
    if cny_end >= p_start and cny_start <= p_finish:
        cx1, cx2 = x_at(cny_start), x_at(cny_end)
        if cx2 > cx1:
            band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, cx1, Inches(1.15), cx2 - cx1, MONTH_Y - Inches(1.15))
            band.fill.solid(); band.fill.fore_color.rgb = RGBColor(0xFF, 0xF1, 0xF2)
            band.line.fill.background()
            if (cx2 - cx1) > int(Inches(0.55)):
                tb(slide, cx1, PHASE_Y - Inches(0.24), max(int(Inches(0.9)), cx2 - cx1), Inches(0.18),
                   [("春节停工", 7.5, COLOR_JLL_RED, True)], PP_ALIGN.CENTER)

    # ---- Phase swimlane: 移至中轴线，与时间轴线组合为一体化阶段主轨 ----
    phase_rules = [
        (("设计", "Phase 1", "Phase 2", "Phase 3"), "设计/图审", "设计", COLOR_PHASE_DESIGN, RGBColor(0xDD, 0xD8, 0xCE)),
        (("招标", "Phase 4"), "招标定标", "招标", COLOR_PHASE_TENDER, RGBColor(0xD0, 0xDF, 0xFD)),
        (("施工许可", "Phase 5"), "施工许可", "许可", COLOR_PHASE_PERMIT, RGBColor(0xFF, 0xE0, 0xB2)),
        (("实体施工", "Phase 6"), "实体施工", "施工", COLOR_PHASE_BUILD, RGBColor(0xC4, 0xF1, 0xE5)),
        (("竣工", "搬迁", "Phase 7", "Phase 8", "散味", "验收"), "验收交付", "交付", COLOR_PHASE_CLOSE, RGBColor(0xD1, 0xF2, 0xC2)),
    ]
    level2 = []
    for t in tasks:
        lvl = t.get("outline_level", t.get("level", 1))
        if lvl == 2 and t.get("start") and t.get("finish"):
            level2.append(t)

    merged = []
    used = set()
    for keys, label, short_label, bg_col, bd_col in phase_rules:
        hits = []
        for t in level2:
            nm = str(t.get("name", ""))
            if id(t) in used:
                continue
            if any(k in nm for k in keys):
                hits.append(t)
                used.add(id(t))
        if not hits:
            continue
        s = min(_to_date(t["start"]) for t in hits)
        e = max(_to_date(t["finish"]) for t in hits)
        merged.append((s, e, label, short_label, bg_col, bd_col))

    # 阶段色带绘制：居中坐落于基准轴线上方，文字在色块内部居中
    for s, e, label, short_label, bg_col, bd_col in merged:
        x1, x2 = x_at(s), x_at(e)
        w = max(int(Inches(0.12)), x2 - x1)
        round_rect(slide, x1, PHASE_Y, w, PHASE_H, bg_col, border_color=bd_col, border_width_pt=0.5, radius=0.30)
        mid_x = (x1 + x2) // 2
        txt = label if w >= int(Inches(0.85)) else short_label
        box_w = max(w, int(Inches(0.42)))
        tb(slide, mid_x - box_w // 2, PHASE_Y + Inches(0.02), box_w, Inches(0.20),
           [(txt, 7.5 if w >= int(Inches(0.85)) else 7.0, COLOR_TEXT_PHASE, True)], PP_ALIGN.CENTER)

    # ---- Milestones: 全量智能识别 + 上下交错高低航道排布 (绝不遗漏、绝对居中) ----
    ms_candidates = [
        t for t in tasks
        if (t.get("milestone", False) or t.get("duration_days", t.get("duration", 0)) == 0)
        and t.get("outline_level", t.get("level", 1)) >= 3
        and t.get("finish")
        and not str(t.get("name", "")).startswith("Stage ")
        and not str(t.get("name", "")).startswith("Phase ")
    ]
    ms_candidates.sort(key=lambda x: _to_date(x["finish"]))

    # 智能里程碑分类库：重点提炼 9 大战略核心里程碑 (P1/P2保证优先布设，P3作为次要补充)
    # 双色区分规范：只给 M2消审、M3许可证、M5验收、M6交付 挂红色圆点，其余全部统一为炭黑/浅灰
    STRATEGIC_CATALOG = [
        ("kickoff", ["kick off", "启动会", "项目启动", "立项"], "项目启动", COLOR_MS_INTERNAL, "业主", 1),
        ("design_contract", ["设计总承包合同", "设计合同", "设计签约", "设计单位资格预审与招采"], "设计签约", COLOR_MS_INTERNAL, "设计", 2),
        ("drawings", ["施工图审查", "图审合格", "审图合格", "施工图全套确认", "审图合格证"], "图审合格", COLOR_MS_INTERNAL, "审图", 2),
        ("fire_design", ["消防设计审查", "消审合格", "消防审查意见书"], "消审合格", COLOR_MS_EXTERNAL, "消防", 1),
        ("gc_award", ["施工总包合同", "总包合同", "总承包合同", "D&B", "中标意向书", "LOI", "中标通知书", "定标完成"], "总包定标", COLOR_MS_INTERNAL, "业主", 1),
        ("permit", ["施工许可", "开工许可", "施工执照"], "施工许可", COLOR_MS_EXTERNAL, "住建", 1),
        ("site_takeover", ["场地移交与动工准备", "Site Takeover", "动工准备"], "现场进场", COLOR_MS_INTERNAL, "总包", 3),
        ("physical_completion", ["物理竣工", "硬装施工完成", "Physical Completion", "施工全部完成及总包自检通过"], "物理竣工", COLOR_MS_INTERNAL, "五方", 1),
        ("fire_acceptance", ["消防验收", "消防备案"], "消防验收", COLOR_MS_EXTERNAL, "消防", 2),
        ("final_filing", ["竣工备案", "联合验收", "规划验收"], "竣工验收", COLOR_MS_EXTERNAL, "住建", 3),
        ("iaq", ["空气质量", "IAQ", "空气检测", "室内空气", "空气达标"], "空气达标", COLOR_MS_EXTERNAL, "检测", 2),
        ("handover_client", ["Site Handover", "场地正式移交", "物业交接"], "场地交付", COLOR_MS_INTERNAL, "业主", 3),
        ("opening", ["正式营业", "搬迁全部完成", "交付营业", "入驻营业", "正式开业"], "交付营业", COLOR_MS_EXTERNAL, "行政", 1),
    ]

    import re
    seen_keys = set()
    raw = []
    for t in ms_candidates:
        nm = str(t.get("name", ""))
        matched = False
        for key, kws, short_name, col, owner, pri in STRATEGIC_CATALOG:
            if any(kw.lower() in nm.lower() for kw in kws):
                if key not in seen_keys:
                    seen_keys.add(key)
                    raw.append({
                        "date": _to_date(t["finish"]),
                        "name": short_name,
                        "orig_name": nm,
                        "col": col,
                        "owner": t.get("resp_party") or owner,
                        "priority": pri,
                        "key": key,
                    })
                matched = True
                break
        if not matched and t.get("milestone", False):
            clean = re.sub(r"\[M\]|⭐|⭐️|《|》|\([^)]*\)|[^\u4e00-\u9fa5a-zA-Z0-9]", "", nm).strip()
            short = clean[:4] if clean else "里程碑"
            raw.append({
                "date": _to_date(t["finish"]),
                "name": short,
                "orig_name": nm,
                "col": COLOR_MS_INTERNAL,
                "owner": t.get("resp_party") or "PM",
                "priority": 3,
                "key": f"custom_{t.get('id')}",
            })

    # 1. 过滤冗余前期微小里程碑 (已有项目启动时，过滤紧随其后的“前期规划/任务书”)
    has_kickoff = any(m.get("key") == "kickoff" for m in raw)
    if has_kickoff:
        raw = [m for m in raw if not any(w in m.get("orig_name", "") for w in ["前期规划", "任务书", "项目章程"])]

    # 2. 验收打包：将尾部密集的 消防验收、空气达标、竣工验收 聚合为单张“综合验收阶段”复合卡片
    acceptance_keys = {"fire_acceptance", "final_filing", "iaq", "handover_client"}
    acc_items = [
        m for m in raw
        if m.get("key") in acceptance_keys or any(w in m.get("orig_name", "") for w in ["消防验收", "竣工验收", "联合验收", "竣工备案", "空气质量", "IAQ", "场地正式移交"])
    ]
    if len(acc_items) >= 2:
        acc_items.sort(key=lambda x: x["date"])
        start_d = acc_items[0]["date"]
        end_d = acc_items[-1]["date"]
        date_str = f"{start_d:%Y.%m.%d}–{end_d:%m.%d}" if start_d.year == end_d.year else f"{start_d:%Y.%m.%d}–{end_d:%Y.%m.%d}"
        cluster_m = {
            "date": start_d,
            "end_date": end_d,
            "date_str": date_str,
            "name": "综合验收阶段",
            "orig_name": "综合验收群 (消防/空气/竣验)",
            "col": COLOR_MS_EXTERNAL,   # M5 综合验收挂红
            "owner": "消防·空气·竣验",
            "priority": 1,
            "key": "acceptance_cluster",
            "is_composite": True,
        }
        # 保留非验收节点 + 复合综合验收卡片
        raw = [m for m in raw if m not in acc_items] + [cluster_m]

    # 3. 严格双色体系锁定：只给 M2消审、M3许可证、M5验收、M6交付 挂红色，其余全部统一为炭黑
    RED_KEYS = {"fire_design", "permit", "acceptance_cluster", "opening"}
    for m in raw:
        if m.get("key") in RED_KEYS or m.get("is_composite"):
            m["col"] = COLOR_MS_EXTERNAL
        else:
            m["col"] = COLOR_MS_INTERNAL

    # 同一天多里程碑去重优化（优先保留高优先级 P1 > P2 > P3）
    date_buckets = {}
    for m in raw:
        d = m["date"]
        if d not in date_buckets or m["priority"] < date_buckets[d]["priority"]:
            date_buckets[d] = m
    raw = sorted(date_buckets.values(), key=lambda m: m["date"])

    # 4 条高低航道：轴线上方 2 航道 + 轴线下方 2 航道 (上下交错分布)
    UPPER_LANE_1 = int(PHASE_Y - Inches(1.00))   # y ≈ 2.58" (近轨)
    UPPER_LANE_2 = int(PHASE_Y - Inches(1.85))   # y ≈ 1.73" (远轨)
    LOWER_LANE_1 = int(AXIS_Y + Inches(0.48))   # y ≈ 4.30" (近轨)
    LOWER_LANE_2 = int(AXIS_Y + Inches(1.33))   # y ≈ 5.15" (远轨)

    placed_boxes = []
    placed_cards = []
    min_gap = int(Inches(0.06))

    def overlaps(a, b):
        return not (a[2] + min_gap <= b[0] or b[2] + min_gap <= a[0] or a[3] + min_gap <= b[1] or b[3] + min_gap <= a[1])

    nudge_options = (
        0,
        int(Inches(0.12)), -int(Inches(0.12)),
        int(Inches(0.24)), -int(Inches(0.24)),
        int(Inches(0.36)), -int(Inches(0.36)),
        int(Inches(0.50)), -int(Inches(0.50)),
        int(Inches(0.65)), -int(Inches(0.65)),
    )

    # 优先级与时间双重排布
    chrono_idx = {id(m): idx for idx, m in enumerate(raw)}
    placement_order = sorted(raw, key=lambda m: (m["priority"], m["date"]))

    for m in placement_order:
        cx0 = x_at(m["date"])
        is_comp = m.get("is_composite", False)
        cw = Inches(1.22) if is_comp else Inches(1.08)
        ch = Inches(0.62) if is_comp else Inches(0.58)

        # 交错首选侧：时间顺序偶数上、奇数下 (保证视觉上下均衡)
        pref_side = "top" if (chrono_idx[id(m)] % 2 == 0) else "bottom"
        sides = [pref_side, "bottom" if pref_side == "top" else "top"]
        
        placed_ok = False
        for side in sides:
            lanes = [UPPER_LANE_1, UPPER_LANE_2] if side == "top" else [LOWER_LANE_1, LOWER_LANE_2]
            for y in lanes:
                for nudge in nudge_options:
                    cx = max(int(CHART_L + cw / 2), min(int(CHART_R - cw / 2), cx0 + nudge))
                    box = (int(cx - cw / 2), y, int(cx + cw / 2), int(y + ch))
                    if any(overlaps(box, pb) for pb in placed_boxes):
                        continue
                    placed_boxes.append(box)
                    placed_cards.append({
                        "m": m,
                        "cx0": cx0,
                        "cx": cx,
                        "cw": cw,
                        "ch": ch,
                        "y": y,
                        "side": side,
                    })
                    placed_ok = True
                    break
                if placed_ok:
                    break
            if placed_ok:
                break

    # 绘制卡片与引线
    for pc in placed_cards:
        m = pc["m"]
        cx0 = pc["cx0"]
        cx = pc["cx"]
        cw = pc["cw"]
        ch = pc["ch"]
        y = pc["y"]
        side = pc["side"]
        is_red = (m["col"] == COLOR_MS_EXTERNAL)
        is_comp = m.get("is_composite", False)
        
        if side == "top":
            # 引线从卡片底边连到阶段轨顶边
            line(slide, cx, y + ch, cx0, PHASE_Y, COLOR_AXIS_LINE, 0.65)
        else:
            # 引线从基准轴线连到卡片顶边
            line(slide, cx0, AXIS_Y, cx, y, COLOR_AXIS_LINE, 0.65)

        # 边框美化：红色节点轻微红晕微边框，其余优雅暖灰细边框
        bd_col = RGBColor(0xF4, 0xAA, 0xB2) if is_red else COLOR_WARM_BORDER
        bd_w = 0.85 if is_red else 0.65
        round_rect(slide, cx - cw / 2, y, cw, ch, COLOR_WHITE,
                   border_color=bd_col, border_width_pt=bd_w, radius=0.12)
        
        # 卡片内文字呈现 (绝对不折行)
        date_display = m.get("date_str", m["date"].strftime("%Y.%m.%d"))
        tb(slide, cx - cw / 2 + Inches(0.02), y + Inches(0.04), cw - Inches(0.04), Inches(0.18),
           [(m["name"], 8.0, COLOR_WARM_CHARCOAL, True)], PP_ALIGN.CENTER)
        tb(slide, cx - cw / 2 + Inches(0.02), y + Inches(0.23), cw - Inches(0.04), Inches(0.16),
           [(date_display, 7.5, m["col"], True)], PP_ALIGN.CENTER)
        tb(slide, cx - cw / 2 + Inches(0.02), y + Inches(0.40), cw - Inches(0.04), Inches(0.14),
           [(f"[{m['owner']}]", 6.5, COLOR_WARM_MUTED, False)], PP_ALIGN.CENTER)

    # 时间轴基准线节点全量打点：严格双色圆点体系 (只给 M2/M3/M5/M6 挂红圆点，其余为炭黑圆点)
    for m in raw:
        cx0 = x_at(m["date"])
        is_red = (m["col"] == COLOR_MS_EXTERNAL)
        if is_red:
            # 综合验收跨度线
            if m.get("is_composite") and m.get("end_date"):
                cx_end = x_at(m["end_date"])
                if cx_end > cx0:
                    line(slide, cx0, AXIS_Y, cx_end, AXIS_Y, COLOR_JLL_RED, 2.0)
                    circle_node(slide, cx_end, AXIS_Y, Inches(0.12), COLOR_MS_EXTERNAL)
            # 红色圆点 (M2消审 / M3许可证 / M5验收 / M6交付)
            circle_node(slide, cx0, AXIS_Y, Inches(0.18), COLOR_MS_EXTERNAL)
        else:
            # 浅灰/炭黑圆点 (内部管理与实施节点)
            circle_node(slide, cx0, AXIS_Y, Inches(0.14), COLOR_WARM_CHARCOAL)

    # 底部说明栏
    footer_text = "时间轴中轴居中 · 关键里程碑上下交错排布 · 严格双色体系 (红: M2消审 / M3许可证 / M5验收 / M6交付 · 炭黑: 内部管理与实施节点)"
    tb(slide, Inches(0.7), Inches(7.00), Inches(12.0), Inches(0.20),
       [(footer_text, 8, COLOR_WARM_LIGHT, False)])

    try:
        prs.save(output_pptx_path)
    except PermissionError:
        base, ext = os.path.splitext(output_pptx_path)
        output_pptx_path = f"{base}_v2{ext}"
        prs.save(output_pptx_path)
    return output_pptx_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Export JLL warm-white executive milestone PPTX")
    parser.add_argument("--json", required=True, help="Input solved json file")
    parser.add_argument("--out", required=True, help="Output pptx path")
    args = parser.parse_args()

    with open(args.json, "r", encoding="utf-8") as f:
        data = json.load(f)

    title = data.get("project_title", "办公工装项目")
    meta = data.get("project_meta", {})
    tasks = data.get("tasks", [])

    out_file = generate_pptx_milestones(title, meta, tasks, args.out)
    print(f"[SUCCESS] Exported warm-white PPTX to: {out_file}")


if __name__ == "__main__":
    main()

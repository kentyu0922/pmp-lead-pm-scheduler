"""A3 landscape executive schedule report (4 sheets).

01 專案摘要 Project Summary · 02 甘特圖 Gantt Chart ·
03 關鍵路徑 Critical Path · 04 風險分析 Risk Analytics
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Sequence

from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas as rl_canvas

from . import theme as T
from .cpm_engine import Schedule, Task, phase_summary
from .fonts import FontSet
from .risk_analytics import (MonteCarloResult, float_distribution, monte_carlo, near_critical,
                             phase_exposure, risk_exposure, s_curve)
from .sample_project import PHASES, PROJECT, Risk
from .sheet import Sheet

_PT2MM = 25.4 / 72.0
MONTHS_EN = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def fmt_d(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def fmt_short(d: date) -> str:
    return d.strftime("%m/%d")


def fmt_zh(d: date) -> str:
    return f"{d.year} 年 {d.month} 月 {d.day} 日"


class ReportContext:
    def __init__(self, schedule: Schedule, risks: Sequence[Risk], mc: MonteCarloResult):
        self.s = schedule
        self.risks = list(risks)
        self.mc = mc
        self.phases = phase_summary(schedule)
        self.exposure = risk_exposure(risks, schedule)
        self.near = near_critical(schedule)
        self.chain = schedule.critical_chain()
        self.milestones = [t for t in schedule.ordered_tasks if t.milestone]
        self.work_tasks = [t for t in schedule.ordered_tasks if not t.milestone]
        self.critical_work = [t for t in self.work_tasks if t.critical]
        self.contingency = int(round(mc.p80)) - schedule.project_duration


class A3Report:
    TOTAL_PAGES = 4

    def __init__(self, ctx: ReportContext, fonts: FontSet):
        self.ctx = ctx
        self.fonts = fonts

    # ------------------------------------------------------------------ chrome
    def _chrome(self, sh: Sheet, page_no: int, number: str, zh: str, en: str) -> None:
        sh.paper()
        x0, x1 = T.MARGIN, T.PAGE_W - T.MARGIN
        y = T.HEADER_TOP

        # Title block
        sh.text(x0, y + 7.4, f"{PROJECT['title_zh']}", 15.5, "medium", T.INK)
        sh.text(x0, y + 12.4, f"{PROJECT['title_en']}  ·  Schedule Baseline Report", 6.0, "medium",
                T.INK_3, tracking=0.7, upper=True)

        # Section label (centre-left of header)
        sx = T.col_x(5)
        sh.text(sx, y + 7.4, number, 15.5, "regular", T.CRITICAL)
        sh.text(sx + 11.5, y + 7.4, zh, 11.0, "medium", T.INK)
        sh.text(sx + 11.5, y + 12.4, en, 5.6, "medium", T.INK_3, tracking=0.7, upper=True)

        # Meta block (right, four aligned columns)
        meta = [
            ("專案編號", "Project No.", PROJECT["code"]),
            ("基準版本", "Baseline", PROJECT["baseline"]),
            ("資料日期", "Data Date", fmt_d(PROJECT["data_date"])),
            ("圖幅 / 頁", "Sheet", f"A3  ·  {page_no:02d} / {self.TOTAL_PAGES:02d}"),
        ]
        col_w = 30.0
        for i, (zh_l, en_l, val) in enumerate(meta):
            mx = x1 - (len(meta) - i) * col_w + col_w
            sh.text(mx, y + 3.4, en_l, 4.9, "medium", T.INK_3, align="right", tracking=0.5, upper=True)
            sh.text(mx, y + 7.6, val, 7.4, "medium", T.INK, align="right")
            sh.text(mx, y + 11.0, zh_l, 5.4, "regular", T.INK_3, align="right")

        sh.line(x0, y + T.HEADER_H, x1, y + T.HEADER_H, T.RULE_STRONG, T.RULE_PT)

        # Footer
        fy = T.FOOTER_Y
        sh.line(x0, fy - 4.6, x1, fy - 4.6, T.RULE, T.HAIRLINE)
        sh.text(x0, fy, f"{PROJECT['prepared_by']}  ·  Deterministic CPM (Kahn topological sort · forward / backward pass)",
                5.4, "regular", T.INK_3)
        mid = f"{PROJECT['client']}  ·  {PROJECT['site_en']}  ·  {PROJECT['procurement']}"
        sh.text((x0 + x1) / 2, fy, mid, 5.4, "regular", T.INK_3, align="center")
        sh.text(x1, fy, f"{page_no:02d} / {self.TOTAL_PAGES:02d}", 5.4, "medium", T.INK_2, align="right")

    # ----------------------------------------------------------- page 1: summary
    def page_summary(self, sh: Sheet) -> None:
        ctx, s = self.ctx, self.ctx.s
        self._chrome(sh, 1, "01", "專案摘要", "Project Summary")

        # KPI strip -----------------------------------------------------------
        y = T.BODY_TOP
        kpi_h = 26.0
        kpis = [
            ("基準總工期", "Baseline Duration", f"{s.project_duration}", "工作天  working days", None),
            ("開工日期", "Start", fmt_d(s.project_start), s.project_start.strftime("%A"), None),
            ("實際完工", "Practical Completion", fmt_d(s.project_finish), s.project_finish.strftime("%A"), None),
            ("任務 / 里程碑", "Tasks / Milestones", f"{len(ctx.work_tasks)} / {len(ctx.milestones)}",
             f"{len(ctx.phases)} 個階段  phases", None),
            ("關鍵任務", "Critical Tasks",
             f"{len(ctx.critical_work)}",
             f"佔 {len(ctx.critical_work) / len(ctx.work_tasks):.0%}  ·  近關鍵 {len(ctx.near)} 項", T.CRITICAL),
            ("P80 完工緩衝", "P80 Contingency", f"+{ctx.contingency}",
             f"工作天  ·  P80 = {ctx.mc.p80:.0f} d  ·  準時機率 {ctx.mc.on_time_probability:.0%}", T.NEAR),
        ]
        for i, (zh, en, big, sub, accent) in enumerate(kpis):
            x = T.col_x(i * 2)
            w = T.col_span_w(2)
            sh.rect(x, y, w, kpi_h, stroke=T.RULE, width=T.HAIRLINE)
            if accent is not None:
                sh.rect(x, y, 0.9, kpi_h, fill=accent)
            sh.label_pair(x + 3.2, y + 5.2, zh, en)
            size = 17.0 if len(big) <= 6 else 12.5
            sh.text(x + 3.2, y + 17.6, big, size, "medium", T.INK)
            sh.text(x + 3.2, y + 22.6, sub, 5.4, "regular", T.INK_3)

        # Phase summary table + milestone list --------------------------------
        y = T.BODY_TOP + kpi_h + 10.0
        left_w = T.col_span_w(8)
        right_x = T.col_x(8)
        right_w = T.col_span_w(4)
        y_content = sh.section(T.MARGIN, y, left_w, "1.1", "階段摘要", "Phase Summary",
                               "工作天 working days · 關鍵工期 = 階段內關鍵任務工期合計（含並行）")
        sh.section(right_x, y, right_w, "1.2", "里程碑", "Milestones")

        span_w = left_w - 173.0
        cols = [
            {"key": "no", "zh": "#", "en": "", "w": 8, "align": "left"},
            {"key": "zh", "zh": "階段", "en": "Phase", "w": 66},
            {"key": "start", "zh": "開始", "en": "Start", "w": 21},
            {"key": "finish", "zh": "完成", "en": "Finish", "w": 21},
            {"key": "span", "zh": "歷時", "en": "Span", "w": 13, "align": "right"},
            {"key": "tasks", "zh": "任務", "en": "Tasks", "w": 13, "align": "right"},
            {"key": "crit", "zh": "關鍵", "en": "Critical", "w": 14, "align": "right"},
            {"key": "cdays", "zh": "關鍵工期", "en": "Crit. Days", "w": 17, "align": "right"},
            {"key": "bar", "zh": "時間分佈", "en": "Timeline", "w": span_w},
        ]
        assert abs(sum(c["w"] for c in cols) - left_w) < 0.01, sum(c["w"] for c in cols)
        total = s.project_duration

        def bar_cell(ph):
            def draw(shh: Sheet, cx, cy, cw, ch):
                pad = 3.0
                inner = cw - 2 * pad
                bx = cx + pad + inner * ph["es"] / total
                bw = max(inner * (ph["ef"] - ph["es"]) / total, 0.6)
                shh.line(cx + pad, cy + ch / 2, cx + pad + inner, cy + ch / 2, T.RULE, T.HAIRLINE)
                shh.rect(bx, cy + ch / 2 - 1.1, bw, 2.2, fill=T.BAR_SOFT)
                for t in s.ordered_tasks:
                    if t.phase == ph["phase"] and t.critical and not t.milestone:
                        shh.rect(cx + pad + inner * t.es / total, cy + ch / 2 - 1.1,
                                 inner * t.duration / total, 2.2, fill=T.CRITICAL)
            return draw

        rows = []
        for i, ph in enumerate(ctx.phases, 1):
            rows.append({
                "no": f"{i:02d}", "zh": f"{PHASES[ph['phase']]['zh']}  {PHASES[ph['phase']]['en']}",
                "start": fmt_d(ph["start"]), "finish": fmt_d(ph["finish"]),
                "span": str(ph["span"]), "tasks": str(ph["tasks"]), "crit": str(ph["critical"]),
                "cdays": str(ph["critical_days"]), "bar": bar_cell(ph),
            })
        rows.append({"no": "", "zh": "合計  Total", "start": fmt_d(s.project_start),
                     "finish": fmt_d(s.project_finish), "span": str(total),
                     "tasks": str(len(ctx.work_tasks)), "crit": str(len(ctx.critical_work)),
                     "cdays": str(sum(p["critical_days"] for p in ctx.phases)), "bar": ""})
        y_table_end = sh.table(T.MARGIN, y_content, cols, rows, row_h=6.4,
                               row_style=lambda r: {"weight": "medium"} if r["no"] == "" else {})

        # milestones list (right)
        my = y_content - 1.0
        for m in ctx.milestones:
            mh = 10.6
            sh.diamond(right_x + 3.2, my + mh / 2, 1.35, fill=T.CRITICAL if m.critical else T.INK)
            sh.text(right_x + 8.0, my + 4.6, m.name_zh, 7.4, "medium", T.INK)
            sh.text(right_x + 8.0, my + 8.2, m.name_en, 5.2, "regular", T.INK_3, tracking=0.3, upper=True)
            sh.text(right_x + right_w - 1.2, my + 4.6, fmt_d(m.start), 7.0, "medium", T.INK, align="right")
            tf = "關鍵  critical" if m.critical else f"浮時 float {m.total_float} d"
            sh.text(right_x + right_w - 1.2, my + 8.2, tf, 5.2, "regular",
                    T.CRITICAL if m.critical else T.INK_3, align="right")
            my += mh
            sh.line(right_x, my, right_x + right_w, my, T.RULE, T.HAIRLINE)

        # Project information (right, below milestones)
        y_info = my + 9.0
        y_info_c = sh.section(right_x, y_info, right_w, "1.3", "專案資料", "Project Information")
        info = [
            ("客戶", "Client", PROJECT["client"]),
            ("地點", "Site", PROJECT["site_zh"]),
            ("採購模式", "Procurement", PROJECT["procurement"]),
            ("工作曆", "Calendar", PROJECT["calendar_zh"]),
            ("公眾假期", "Holidays", f"{len(s.calendar.holidays)} 天於工期內  within window"),
            ("排程方法", "Method", "CPM · Kahn 拓撲排序 · 前推 / 後推計算"),
        ]
        iy = y_info_c
        for zh, en, val in info:
            sh.text(right_x, iy + 3.0, zh, 6.2, "medium", T.INK_2)
            sh.text(right_x, iy + 5.6, en, 4.6, "medium", T.INK_3, tracking=0.4, upper=True)
            sh.text(right_x + 26, iy + 3.2, val, 6.6, "regular", T.INK)
            iy += 7.4
            sh.line(right_x, iy, right_x + right_w, iy, T.RULE, T.HAIRLINE)

        # Phase timeline (left, bottom) ---------------------------------------
        y_tl = y_table_end + 9.0
        y_tl_c = sh.section(T.MARGIN, y_tl, left_w, "1.4", "階段時間軸", "Phase Timeline")
        self._legend(sh, T.MARGIN + left_w, y_tl,
                     [(T.CRITICAL, "關鍵 critical"), (T.BAR_SOFT, "一般 non-critical"), (T.INK, "里程碑 milestone")])
        tl_h = min(T.BODY_BOTTOM - y_tl_c - 1.0, 7.0 + 8.0 * len(ctx.phases))
        self._phase_timeline(sh, T.MARGIN, y_tl_c, left_w, tl_h)

        # Long-lead procurement decision points (left, below timeline) --------
        y_ll = y_tl_c + tl_h + 9.0
        if y_ll + 30 < T.BODY_BOTTOM:
            y_ll_c = sh.section(T.MARGIN, y_ll, left_w, "1.6", "長交期採購決策點", "Long-lead Procurement · Latest Order Dates",
                                "最遲開始 LS = 不影響完工日期的最後下單日")
            ll_cols = [
                {"key": "wbs", "zh": "WBS", "en": "", "w": 10},
                {"key": "name", "zh": "採購項目", "en": "Item", "w": 78},
                {"key": "lead", "zh": "交期", "en": "Lead Time", "w": 20, "align": "right"},
                {"key": "es", "zh": "計劃下單", "en": "Planned Order", "w": 28, "align": "right"},
                {"key": "ls", "zh": "最遲下單", "en": "Latest Order (LS)", "w": 30, "align": "right"},
                {"key": "need", "zh": "需到場日", "en": "Required On Site", "w": 30, "align": "right"},
                {"key": "tf", "zh": "浮時", "en": "Float", "w": 16, "align": "right"},
                {"key": "succ", "zh": "後續工序", "en": "Feeds", "w": left_w - 212},
            ]
            ll_rows = []
            for t in s.ordered_tasks:
                if not t.name_zh.startswith("長交期"):
                    continue
                succ = [u for u in s.ordered_tasks if t.id in u.predecessors]
                ll_rows.append({
                    "wbs": t.wbs, "name": t.name_zh.split("：")[-1] + "  " + t.name_en.split(": ")[-1],
                    "lead": f"{t.duration} d", "es": fmt_d(t.start),
                    "ls": fmt_d(s.calendar.offset_to_date(t.ls)),
                    "need": fmt_d(s.calendar.offset_to_date(t.lf)), "tf": f"{t.total_float} d",
                    "succ": " · ".join(u.name_zh for u in succ), "_tf": t.total_float,
                })
            sh.table(T.MARGIN, y_ll_c, ll_cols, ll_rows, row_h=5.6, size=6.4,
                     row_style=lambda r: {"marker": T.NEAR} if r["_tf"] <= 14 else {})

        # Executive notes (right, bottom)
        y_notes = max(iy + 9.0, y_tl)
        y_notes_c = sh.section(right_x, y_notes, right_w, "1.5", "進度重點", "Executive Notes")
        ny = y_notes_c + 2.0
        for i, note in enumerate(self._notes(), 1):
            sh.text(right_x, ny, f"{i:02d}", 6.0, "medium", T.CRITICAL)
            ny = sh.paragraph(right_x + 6.5, ny, note, right_w - 6.5, 6.6, "regular", T.INK, leading=3.7)
            ny += 2.2
            if ny > T.BODY_BOTTOM - 4:
                break

    def _notes(self) -> List[str]:
        ctx, s = self.ctx, self.ctx.s
        chain_names = [t.name_zh for t in ctx.chain if not t.milestone]
        drivers = " → ".join(n.split("：")[-1].split("（")[0] for n in chain_names[2:11])
        near = "、".join(t.name_zh.split("（")[0] for t in ctx.near)
        longlead = [t for t in s.ordered_tasks if t.name_zh.startswith("長交期")]
        ll = "、".join(f"{t.name_zh.split('：')[-1]} {t.total_float} 天" for t in longlead)
        top = ctx.exposure[0]["risk"]
        return [
            f"基準總工期 {s.project_duration} 個工作天（{fmt_zh(s.project_start)} 至 {fmt_zh(s.project_finish)}），"
            f"關鍵路徑共 {len(ctx.critical_work)} 項工作任務，主要驅動工序：{drivers}。",
            f"近關鍵任務（總浮時 ≤ 3 天）共 {len(ctx.near)} 項：{near}；任何一項延誤即可能改寫關鍵路徑。",
            f"長交期採購浮時：{ll}；所有長交期訂單須於 {fmt_zh(longlead[0].start)} 前落實，否則玻璃間隔將成為關鍵。",
            f"蒙地卡羅模擬（{ctx.mc.iterations:,} 次）P50 = {ctx.mc.p50:.0f} 天、P80 = {ctx.mc.p80:.0f} 天，"
            f"基準準時機率僅 {ctx.mc.on_time_probability:.0%}；建議預留 {ctx.contingency} 個工作天工期緩衝。",
            f"最高風險：{top.id} {top.title_zh}（分數 {top.score}），關聯任務最小浮時 {ctx.exposure[0]['min_float']} 天，"
            f"延誤逾此浮時將直接推遲後續機電及間隔工序。",
        ]

    def _phase_timeline(self, sh: Sheet, x, y, w, h) -> None:
        ctx, s = self.ctx, self.ctx.s
        label_w = 58.0
        tx = x + label_w
        tw = w - label_w
        t0 = s.project_start - timedelta(days=s.project_start.weekday())
        t1 = s.project_finish + timedelta(days=6 - s.project_finish.weekday())
        days = (t1 - t0).days + 1
        header_h = 7.0
        row_h = (h - header_h) / len(ctx.phases)

        def dx(d: date) -> float:
            return tx + tw * (d - t0).days / days

        # month header
        sh.line(tx, y + header_h, x + w, y + header_h, T.RULE_STRONG, T.RULE_PT)
        cur = date(t0.year, t0.month, 1)
        while cur <= t1:
            nxt = date(cur.year + (cur.month // 12), cur.month % 12 + 1, 1)
            a, b = max(cur, t0), min(nxt, t1 + timedelta(days=1))
            if a < b:
                sh.text((dx(a) + dx(b)) / 2, y + 4.4, f"{cur.year} 年 {cur.month} 月  {MONTHS_EN[cur.month - 1]}",
                        5.6, "medium", T.INK_2, align="center", tracking=0.3)
                if cur > t0:
                    sh.line(dx(cur), y, dx(cur), y + h, T.RULE, T.HAIRLINE)
            cur = nxt
        # week lines (light)
        wk = t0
        while wk <= t1:
            if wk != t0:
                sh.line(dx(wk), y + header_h, dx(wk), y + h, T.RULE, T.HAIRLINE, dash=(0.4, 1.2))
            wk += timedelta(days=7)

        ry = y + header_h
        for i, ph in enumerate(ctx.phases):
            base = ry + row_h / 2 + 0.9
            sh.text(x, base, f"{i + 1:02d}", 6.0, "medium", T.CRITICAL)
            sh.text(x + 7.0, base, PHASES[ph["phase"]]["zh"], 6.8, "medium", T.INK)
            sh.text(x + 7.0 + sh.width(PHASES[ph["phase"]]["zh"], 6.8, "medium") + 1.6, base,
                    PHASES[ph["phase"]]["en"], 4.8, "regular", T.INK_3)
            a = dx(ph["start"])
            b = dx(ph["finish"] + timedelta(days=1))
            bh = min(3.2, row_h * 0.42)
            sh.rect(a, ry + row_h / 2 - bh / 2, b - a, bh, fill=T.BAR_SOFT)
            # critical portion drawn per critical task in the phase
            for t in s.ordered_tasks:
                if t.phase == ph["phase"] and t.critical and not t.milestone:
                    sh.rect(dx(t.start), ry + row_h / 2 - bh / 2, dx(t.finish + timedelta(days=1)) - dx(t.start),
                            bh, fill=T.CRITICAL)
            sh.text(b + 1.6, base, f"{ph['span']} d", 5.4, "regular", T.INK_3)
            ry += row_h
            sh.line(x, ry, x + w, ry, T.RULE, T.HAIRLINE)
        # milestones as diamonds on the bottom rule
        for m in ctx.milestones:
            sh.diamond(dx(m.start) + (dx(m.start + timedelta(days=1)) - dx(m.start)) / 2, y + header_h - 1.6, 1.1,
                       fill=T.CRITICAL if m.critical else T.INK)

    # ------------------------------------------------------------- page 2: Gantt
    def page_gantt(self, sh: Sheet) -> None:
        ctx, s = self.ctx, self.ctx.s
        self._chrome(sh, 2, "02", "甘特圖", "Gantt Chart · CPM Baseline")

        x0, x1 = T.MARGIN, T.PAGE_W - T.MARGIN
        top = T.BODY_TOP
        cols = [
            ("wbs", "WBS", "", 10.0, "left"),
            ("name", "任務名稱", "Task", 58.0, "left"),
            ("dur", "工期", "Dur", 9.0, "right"),
            ("start", "開始", "Start", 15.0, "right"),
            ("finish", "完成", "Finish", 15.0, "right"),
            ("tf", "浮時", "Float", 9.0, "right"),
        ]
        table_w = sum(c[3] for c in cols)
        gx = x0 + table_w
        gw = x1 - gx

        rows: List[object] = []
        for ph in ctx.phases:
            rows.append(ph)
            rows.extend(t for t in s.ordered_tasks if t.phase == ph["phase"])
        header_h = 9.0
        legend_h = 6.0
        avail = T.BODY_BOTTOM - top - header_h - legend_h
        row_h = avail / len(rows)

        # timeline scale
        t0 = s.project_start - timedelta(days=s.project_start.weekday())
        t1 = s.project_finish + timedelta(days=6 - s.project_finish.weekday())
        days = (t1 - t0).days + 1

        def dx(d: date) -> float:
            return gx + gw * (d - t0).days / days

        # header rules & labels
        sh.line(x0, top, x1, top, T.RULE_STRONG, T.RULE_PT)
        cx = x0
        for key, zh, en, w, align in cols:
            tx = cx + (w - 1.2 if align == "right" else 1.2)
            sh.text(tx, top + 3.6, zh, 6.0, "medium", T.INK_2, align=align)
            sh.text(tx, top + 6.6, en, 4.7, "medium", T.INK_3, align=align, tracking=0.4, upper=True)
            cx += w
        # months
        cur = date(t0.year, t0.month, 1)
        while cur <= t1:
            nxt = date(cur.year + (cur.month // 12), cur.month % 12 + 1, 1)
            a, b = max(cur, t0), min(nxt, t1 + timedelta(days=1))
            if a < b:
                sh.text((dx(a) + dx(b)) / 2, top + 3.6, f"{cur.year} 年 {cur.month} 月  {MONTHS_EN[cur.month - 1]}",
                        5.8, "medium", T.INK_2, align="center", tracking=0.3)
            cur = nxt
        sh.line(gx, top + 4.6, x1, top + 4.6, T.RULE, T.HAIRLINE)
        # weeks
        wk = t0
        body_top = top + header_h
        body_bottom = body_top + row_h * len(rows)
        while wk <= t1:
            sh.text(dx(wk) + 0.8, top + 7.8, fmt_short(wk), 4.6, "regular", T.INK_3)
            wk += timedelta(days=7)
        sh.line(x0, body_top, x1, body_top, T.RULE_STRONG, T.RULE_PT)

        # weekend / holiday shading
        d = t0
        while d <= t1:
            if not s.calendar.is_workday(d):
                sh.rect(dx(d), body_top, dx(d + timedelta(days=1)) - dx(d), body_bottom - body_top, fill=T.WEEKEND)
            d += timedelta(days=1)
        # week & month grid lines
        wk = t0
        while wk <= t1 + timedelta(days=1):
            sh.line(dx(wk), top + 4.6, dx(wk), body_bottom, T.RULE, T.HAIRLINE)
            wk += timedelta(days=7)
        cur = date(t0.year, t0.month, 1)
        while cur <= t1:
            if cur > t0:
                sh.line(dx(cur), top, dx(cur), body_bottom, T.RULE_STRONG, T.HAIRLINE)
            cur = date(cur.year + (cur.month // 12), cur.month % 12 + 1, 1)
        # column separators
        cx = x0
        for key, zh, en, w, align in cols:
            cx += w
            sh.line(cx, top, cx, body_bottom, T.RULE, T.HAIRLINE)

        # rows
        y = body_top
        fs = min(6.4, row_h * 0.62 / _PT2MM)
        for row in rows:
            base = y + row_h / 2 + fs * _PT2MM * 0.36
            if isinstance(row, dict):
                sh.rect(x0, y, x1 - x0, row_h, fill=T.PANEL)
                ph = PHASES[row["phase"]]
                sh.text(x0 + 1.2, base, row["phase"].replace("P", "0"), fs, "medium", T.CRITICAL)
                sh.text(x0 + 10.0 + 1.2, base, f"{ph['zh']}", fs, "medium", T.INK)
                sh.text(x0 + 10.0 + 1.2 + sh.width(ph["zh"], fs, "medium") + 1.6, base, ph["en"], fs - 1.4,
                        "regular", T.INK_3)
                sh.text(x0 + 10 + 58 + 9 - 1.2, base, f"{row['span']} d", fs - 0.4, "regular", T.INK_2, align="right")
                # phase summary band
                a, b = dx(row["start"]), dx(row["finish"] + timedelta(days=1))
                sh.rect(a, y + row_h * 0.36, b - a, row_h * 0.28, fill=T.BAR_SOFT)
                sh.line(x0, y, x1, y, T.RULE_STRONG, T.HAIRLINE)
            else:
                t: Task = row
                accent = T.CRITICAL if t.critical else T.INK
                sh.text(x0 + 1.2, base, t.wbs, fs - 0.6, "regular", T.INK_3)
                name = sh.ellipsize(t.name_zh, 58.0 - 2.4, fs, "medium" if t.critical else "regular")
                sh.text(x0 + 10.0 + 1.2, base, name, fs, "medium" if t.critical else "regular", accent)
                cx = x0 + 10.0 + 58.0
                sh.text(cx + 9.0 - 1.2, base, "◆" if t.milestone else f"{t.duration} d", fs - 0.4, "regular",
                        T.INK_2, align="right")
                sh.text(cx + 9.0 + 15.0 - 1.2, base, fmt_d(t.start), fs - 0.6, "regular", T.INK_2, align="right")
                sh.text(cx + 9.0 + 30.0 - 1.2, base, fmt_d(t.finish), fs - 0.6, "regular", T.INK_2, align="right")
                tf_col = T.CRITICAL if t.critical else T.NEAR if t.total_float <= 3 else T.INK_2
                sh.text(cx + 9.0 + 30.0 + 9.0 - 1.2, base, "0" if t.critical else str(t.total_float), fs - 0.4,
                        "medium" if t.critical else "regular", tf_col, align="right")

                # bar
                bh = row_h * 0.46
                by = y + (row_h - bh) / 2
                if t.milestone:
                    mx = dx(t.start) + (dx(t.start + timedelta(days=1)) - dx(t.start)) / 2
                    sh.diamond(mx, y + row_h / 2, min(1.35, row_h * 0.3), fill=accent)
                    sh.text(mx + 2.4, base, t.name_zh, fs - 1.0, "medium", accent)
                else:
                    a, b = dx(t.start), dx(t.finish + timedelta(days=1))
                    sh.rect(a, by, b - a, bh, fill=T.CRITICAL if t.critical else T.BAR)
                    if t.total_float > 0:
                        lf_date = s.calendar.finish_date(t.lf, t.duration)
                        fx = dx(lf_date + timedelta(days=1))
                        sh.line(b, y + row_h / 2, fx, y + row_h / 2, T.INK_3, T.HAIRLINE, dash=(0.5, 0.9))
                        sh.line(fx, y + row_h / 2 - bh / 2, fx, y + row_h / 2 + bh / 2, T.INK_3, T.HAIRLINE)
                    label_x = (dx(lf_date + timedelta(days=1)) if t.total_float > 0 else b) + 1.4
                    sh.text(label_x, base, t.trade, fs - 1.4, "regular", T.INK_3)
                sh.line(x0, y + row_h, x1, y + row_h, T.RULE, T.HAIRLINE)
            y += row_h

        # legend
        ly = body_bottom + 3.9
        lx = gx
        items = [
            (T.CRITICAL, "rect", "關鍵任務  Critical (TF = 0)"),
            (T.BAR, "rect", "一般任務  Non-critical"),
            (T.INK, "diamond", "里程碑  Milestone"),
            (T.INK_3, "float", "總浮時  Total float → 最遲完成 LF"),
            (T.WEEKEND, "rect", "非工作日  Non-working day"),
        ]
        for color, kind, label in items:
            if kind == "rect":
                sh.rect(lx, ly - 1.7, 5.0, 2.0, fill=color)
            elif kind == "diamond":
                sh.diamond(lx + 2.5, ly - 0.7, 1.2, fill=color)
            else:
                sh.line(lx, ly - 0.7, lx + 5.0, ly - 0.7, color, T.HAIRLINE, dash=(0.5, 0.9))
                sh.line(lx + 5.0, ly - 1.7, lx + 5.0, ly + 0.3, color, T.HAIRLINE)
            sh.text(lx + 6.6, ly, label, 5.2, "regular", T.INK_2)
            lx += 6.6 + sh.width(label, 5.2) + 8.0
        sh.text(x1, ly, f"時間軸 {fmt_d(t0)} – {fmt_d(t1)}  ·  {days // 7} 週 weeks  ·  工作曆 Mon–Sat", 5.2,
                "regular", T.INK_3, align="right")
        sh.text(x0, ly, f"{len(ctx.work_tasks)} 項任務 tasks  ·  {len(ctx.milestones)} 個里程碑 milestones  ·  "
                        f"{len(ctx.phases)} 個階段 phases", 5.2, "regular", T.INK_3)

    # ----------------------------------------------------- page 3: critical path
    def page_critical(self, sh: Sheet) -> None:
        ctx, s = self.ctx, self.ctx.s
        self._chrome(sh, 3, "03", "關鍵路徑", "Critical Path Analysis")
        x0 = T.MARGIN
        w = T.CONTENT_W

        # Chain flow ------------------------------------------------------------
        y = T.BODY_TOP
        yc = sh.section(x0, y, w, "3.1", "關鍵鏈", "Critical Chain",
                        f"{len(ctx.chain)} 個節點 nodes  ·  總浮時 TF = 0  ·  {s.project_duration} 工作天")
        chain = ctx.chain
        gap = 2.8
        n = len(chain)
        nw = (w - gap * (n - 1)) / n
        nh = 24.0
        ny = yc + 1.0
        for i, t in enumerate(chain):
            nx = x0 + i * (nw + gap)
            if t.milestone:
                sh.rect(nx, ny, nw, nh, fill=T.INK)
                sh.diamond(nx + 3.4, ny + 3.6, 1.1, fill=T.PAPER)
                sh.text(nx + 6.0, ny + 4.6, t.id, 5.6, "medium", T.PAPER)
                lines = sh.wrap(t.name_zh, nw - 4.0, 5.8, "medium")[:3]
                for j, ln in enumerate(lines):
                    sh.text(nx + 2.0, ny + 9.4 + j * 3.3, ln, 5.8, "medium", T.PAPER)
                sh.text(nx + 2.0, ny + nh - 2.0, fmt_short(t.start), 4.6, "regular", T.PAPER)
            else:
                sh.rect(nx, ny, nw, nh, stroke=T.RULE_STRONG, width=T.HAIRLINE)
                sh.rect(nx, ny, nw, 0.9, fill=T.CRITICAL)
                sh.text(nx + 2.0, ny + 4.9, t.id, 5.6, "medium", T.CRITICAL)
                sh.text(nx + nw - 2.0, ny + 4.9, f"{t.duration} d", 5.6, "medium", T.INK, align="right")
                lines = sh.wrap(t.name_zh, nw - 4.0, 5.8, "medium")[:3]
                for j, ln in enumerate(lines):
                    sh.text(nx + 2.0, ny + 9.4 + j * 3.3, ln, 5.8, "medium", T.INK)
                sh.text(nx + 2.0, ny + nh - 2.0, f"{fmt_short(t.start)} – {fmt_short(t.finish)}", 4.6, "regular", T.INK_3)
            if i < n - 1:
                sh.line(nx + nw, ny + nh / 2, nx + nw + gap, ny + nh / 2, T.RULE_STRONG, T.HAIRLINE)
            # ES scale under the node
            sh.text(nx, ny + nh + 3.4, f"d{t.es}", 4.6, "regular", T.INK_3)
        sh.text(x0 + w, ny + nh + 3.4, f"d{s.project_duration}", 4.6, "medium", T.CRITICAL, align="right")
        sh.line(x0, ny + nh + 5.0, x0 + w, ny + nh + 5.0, T.RULE, T.HAIRLINE)

        # Critical task table (left 7 cols) --------------------------------------
        y2 = ny + nh + 11.0
        left_w = T.col_span_w(7)
        rx = T.col_x(7)
        right_w = T.col_span_w(5)
        y2c = sh.section(x0, y2, left_w, "3.2", "關鍵任務明細", "Critical Tasks · CPM Metrics",
                         "ES / EF / LS / LF 以工作天偏移表示 · CI = 蒙地卡羅關鍵度指數")
        cols = [
            {"key": "wbs", "zh": "WBS", "en": "", "w": 10},
            {"key": "name", "zh": "任務", "en": "Task", "w": 56},
            {"key": "trade", "zh": "工種", "en": "Trade", "w": 18},
            {"key": "dur", "zh": "工期", "en": "Dur", "w": 11, "align": "right"},
            {"key": "es", "zh": "ES", "en": "", "w": 10, "align": "right"},
            {"key": "ef", "zh": "EF", "en": "", "w": 10, "align": "right"},
            {"key": "ls", "zh": "LS", "en": "", "w": 10, "align": "right"},
            {"key": "lf", "zh": "LF", "en": "", "w": 10, "align": "right"},
            {"key": "tf", "zh": "TF", "en": "", "w": 9, "align": "right"},
            {"key": "start", "zh": "開始", "en": "Start", "w": 20.25, "align": "right"},
            {"key": "finish", "zh": "完成", "en": "Finish", "w": 20.25, "align": "right"},
            {"key": "ci", "zh": "CI", "en": "", "w": left_w - 184.5},
        ]
        assert abs(sum(c["w"] for c in cols) - left_w) < 0.01, sum(c["w"] for c in cols)

        def ci_cell(v: float):
            def draw(shh: Sheet, cx, cy, cw, ch):
                pad = 1.2
                bw = cw - pad * 2 - 12
                shh.rect(cx + pad, cy + ch / 2 - 0.9, bw, 1.8, fill=T.PANEL_DEEP)
                shh.rect(cx + pad, cy + ch / 2 - 0.9, bw * v, 1.8, fill=T.CRITICAL)
                shh.text(cx + cw - pad, cy + ch / 2 + 0.85, f"{v:.0%}", 6.0, "regular", T.INK_2, align="right")
            return draw

        rows = []
        for t in s.critical_tasks:
            rows.append({
                "wbs": t.wbs, "name": t.name_zh, "trade": t.trade,
                "dur": "◆" if t.milestone else str(t.duration),
                "es": str(t.es), "ef": str(t.ef), "ls": str(t.ls), "lf": str(t.lf), "tf": "0",
                "start": fmt_d(t.start), "finish": fmt_d(t.finish), "ci": ci_cell(ctx.mc.criticality[t.id]),
                "_m": t.milestone,
            })
        y_tab_end = sh.table(x0, y2c, cols, rows, row_h=6.6, size=6.2,
                             row_style=lambda r: {"color": T.INK_2, "weight": "regular"} if r["_m"] else {})

        # Near-critical table (right) -------------------------------------------
        y2c_r = sh.section(rx, y2, right_w, "3.3", "近關鍵任務", "Near-critical · TF ≤ 7 d")
        near7 = [t for t in s.ordered_tasks if 0 < t.total_float <= 7 and not t.milestone]
        ncols = [
            {"key": "wbs", "zh": "WBS", "en": "", "w": 10},
            {"key": "name", "zh": "任務", "en": "Task", "w": 52},
            {"key": "dur", "zh": "工期", "en": "Dur", "w": 11, "align": "right"},
            {"key": "tf", "zh": "總浮時", "en": "TF", "w": 12, "align": "right"},
            {"key": "ff", "zh": "自由浮時", "en": "FF", "w": 14, "align": "right"},
            {"key": "bar", "zh": "浮時對比", "en": "Float", "w": 40},
            {"key": "ci", "zh": "CI", "en": "", "w": right_w - 139},
        ]
        maxf = 7

        def float_cell(tf: int):
            def draw(shh: Sheet, cx, cy, cw, ch):
                pad = 1.2
                bw = cw - 2 * pad
                shh.rect(cx + pad, cy + ch / 2 - 0.9, bw, 1.8, fill=T.PANEL_DEEP)
                shh.rect(cx + pad, cy + ch / 2 - 0.9, bw * tf / maxf, 1.8, fill=T.NEAR if tf <= 3 else T.BAR)
            return draw

        nrows = [{
            "wbs": t.wbs, "name": t.name_zh, "dur": str(t.duration), "tf": str(t.total_float),
            "ff": str(t.free_float), "bar": float_cell(t.total_float),
            "ci": f"{ctx.mc.criticality[t.id]:.0%}",
        } for t in near7]
        y_near_end = sh.table(rx, y2c_r, ncols, nrows, row_h=6.6, size=6.2,
                              row_style=lambda r: {"marker": T.NEAR} if int(r["tf"]) <= 3 else {})

        # Critical duration by phase (right, below) ------------------------------
        y3 = y_near_end + 9.0
        y3c = sh.section(rx, y3, right_w, "3.4", "關鍵工期構成", "Critical Duration by Phase",
                         f"合計 {sum(p['critical_days'] for p in ctx.phases)} 工作天")
        self._hbars(sh, rx, y3c + 1.0, right_w,
                    [(f"{PHASES[p['phase']]['zh']}", PHASES[p['phase']]['en'], p["critical_days"],
                      f"{p['critical_days']} d  ·  {p['critical_days'] / s.project_duration:.0%}")
                     for p in ctx.phases],
                    row_h=6.4, label_w=52.0, color=T.CRITICAL)

        # Criticality index of non-critical tasks (right, below phase bars) -------
        y5 = y3c + 1.0 + 6.4 * len(ctx.phases) + 9.0
        y5c = sh.section(rx, y5, right_w, "3.6", "關鍵度指數", "Criticality Index · Non-critical Tasks",
                         f"{ctx.mc.iterations:,} 次蒙地卡羅 runs")
        ranked = sorted((t for t in s.ordered_tasks if not t.milestone and not t.critical
                         and (ctx.mc.criticality[t.id] > 0.0 or t.total_float <= 7)),
                        key=lambda t: (-ctx.mc.criticality[t.id], t.total_float))
        n_fit = max(0, int((T.BODY_BOTTOM - 12.0 - (y5c + 1.0)) // 6.4))
        y_ci_end = self._hbars(sh, rx, y5c + 1.0, right_w,
                               [(t.name_zh, f"{t.id} · TF {t.total_float} d", ctx.mc.criticality[t.id],
                                 f"{ctx.mc.criticality[t.id]:.0%}") for t in ranked[:n_fit]],
                               row_h=6.4, label_w=64.0, color=T.NEAR, vmax=1.0)
        top_ci = ranked[0] if ranked else None
        if top_ci is not None:
            sh.paragraph(rx, y_ci_end + 4.2,
                         f"關鍵度指數 CI = 該任務在 {ctx.mc.iterations:,} 次模擬中落於關鍵路徑的比例。"
                         f"{top_ci.name_zh} 雖有 {top_ci.total_float} 天浮時，仍有 {ctx.mc.criticality[top_ci.id]:.0%} "
                         f"機率成為關鍵，應納入每週關鍵路徑監控。",
                         right_w, 6.2, "regular", T.INK_2, leading=3.5, max_lines=3)

        # Path drivers (left, below table; two text columns) ----------------------
        y4 = y_tab_end + 9.0
        y4c = sh.section(x0, y4, left_w, "3.5", "路徑驅動因素", "Path Drivers")
        half = (left_w - T.GUTTER) / 2
        notes = self._driver_notes()
        for k, col_notes in enumerate((notes[:2], notes[2:])):
            cx = x0 + k * (half + T.GUTTER)
            ty = y4c + 2.0
            for j, para in enumerate(col_notes):
                sh.text(cx, ty, f"{2 * k + j + 1:02d}", 6.0, "medium", T.CRITICAL)
                ty = sh.paragraph(cx + 6.5, ty, para, half - 6.5, 6.6, "regular", T.INK, leading=3.7)
                ty += 2.4

    def _driver_notes(self) -> List[str]:
        ctx, s = self.ctx, self.ctx.s
        pre = [t for t in ctx.chain if t.phase == "P1" and not t.milestone]
        pre_days = sum(t.duration for t in pre)
        mep = [t for t in ctx.chain if t.phase == "P3"]
        near = ctx.near
        merge = [t for t in s.critical_tasks if len(t.predecessors) >= 3 and not t.milestone]
        merge_txt = "、".join(f"{t.name_zh}（{len(t.predecessors)} 項前置）" for t in merge[:3])
        return [
            f"前期準備佔關鍵路徑 {pre_days} 個工作天（{pre_days / s.project_duration:.0%}）：設計及業主審批直接決定進場日期，"
            f"每延誤一天即等量推遲完工。",
            f"機電一次配管以 {'、'.join(t.name_zh for t in mep)} 為主導；消防噴淋改位及弱電線槽僅有 2 天浮時，"
            f"停水窗口一旦受限即會取代其成為關鍵。",
            f"匯合節點（merge bias）：{merge_txt}。多項前置工序同時匯入，令模擬完工分佈明顯偏後。",
            f"完工前工序（修補清潔 → IAQ 檢測）為串行硬性閘門，無法壓縮；缺陷修正僅 {near[-1].total_float} 天浮時。",
        ]

    def _legend(self, sh: Sheet, right_x, y, items) -> None:
        """Right-aligned swatch legend on a section header line (baseline `y`)."""
        x = right_x
        for color, label in reversed(items):
            lw = sh.width(label, 5.8)
            x -= lw
            sh.text(x, y, label, 5.8, "regular", T.INK_3)
            x -= 4.4
            sh.rect(x, y - 2.1, 3.0, 2.1, fill=color)
            x -= 5.0

    def _hbars(self, sh: Sheet, x, y, w, items, row_h=5.8, label_w=50.0, color=T.CRITICAL, vmax=None) -> float:
        if not items:
            return y
        vmax = vmax if vmax is not None else max(v for _, _, v, _ in items) or 1
        bar_x = x + label_w
        bar_w = w - label_w - 22.0
        for zh, en, v, txt in items:
            base = y + row_h / 2 + 0.95
            zh_s = sh.ellipsize(zh, label_w - 4, 6.4, "medium")
            sh.text(x, base, zh_s, 6.4, "medium", T.INK)
            if en:
                en_s = sh.ellipsize(en, label_w - sh.width(zh_s, 6.4, "medium") - 4, 4.6)
                sh.text(x + sh.width(zh_s, 6.4, "medium") + 1.4, base, en_s, 4.6, "regular", T.INK_3)
            sh.rect(bar_x, y + row_h / 2 - 1.0, bar_w, 2.0, fill=T.PANEL_DEEP)
            if v > 0:
                sh.rect(bar_x, y + row_h / 2 - 1.0, bar_w * v / vmax, 2.0, fill=color)
            sh.text(x + w, base, txt, 6.0, "regular", T.INK_2, align="right")
            y += row_h
            sh.line(x, y, x + w, y, T.RULE, T.HAIRLINE)
        return y

    # ------------------------------------------------------------ page 4: risks
    def page_risk(self, sh: Sheet) -> None:
        ctx, s = self.ctx, self.ctx.s
        self._chrome(sh, 4, "04", "風險分析", "Risk Analytics")
        x0 = T.MARGIN
        w = T.CONTENT_W
        y = T.BODY_TOP

        # Three analytic panels ------------------------------------------------
        pw = T.col_span_w(4)
        px = [T.col_x(0), T.col_x(4), T.col_x(8)]
        panel_h = 80.0
        yc = sh.section(px[0], y, pw, "4.1", "風險矩陣", "Probability × Impact Matrix",
                        f"{len(ctx.risks)} 項風險 risks")
        self._heatmap(sh, px[0], yc + 1.0, pw, panel_h - (yc - y) - 1.0)

        yc2 = sh.section(px[1], y, pw, "4.2", "完工機率曲線", "Completion Probability · S-curve",
                         f"{ctx.mc.iterations:,} 次蒙地卡羅 runs")
        self._scurve(sh, px[1], yc2 + 1.0, pw, panel_h - (yc2 - y) - 1.0)

        yc3 = sh.section(px[2], y, pw, "4.3", "浮時分佈", "Total Float Distribution",
                         f"{len(ctx.work_tasks)} 項工作任務 tasks")
        self._float_hist(sh, px[2], yc3 + 1.0, pw, panel_h - (yc3 - y) - 1.0)

        # Risk register ----------------------------------------------------------
        y2 = y + panel_h + 9.0
        y2c = sh.section(x0, y2, w, "4.4", "進度風險登記冊", "Schedule Risk Register",
                         "P 機率 1–5  ·  I 影響 1–5  ·  預期延誤 = 延誤天數 × P / 5  ·  傳導延誤 = max(0, 延誤 − 最小浮時)")
        cols = [
            {"key": "id", "zh": "編號", "en": "ID", "w": 12},
            {"key": "title", "zh": "風險描述", "en": "Risk", "w": 62},
            {"key": "en", "zh": "", "en": "Description", "w": 66},
            {"key": "tasks", "zh": "關聯任務", "en": "Linked Tasks", "w": 24},
            {"key": "phase", "zh": "階段", "en": "Phase", "w": 14, "align": "center"},
            {"key": "p", "zh": "P", "en": "", "w": 9, "align": "center"},
            {"key": "i", "zh": "I", "en": "", "w": 9, "align": "center"},
            {"key": "score", "zh": "分數", "en": "Score", "w": 12, "align": "center"},
            {"key": "level", "zh": "等級", "en": "Level", "w": 16},
            {"key": "minf", "zh": "最小浮時", "en": "Min Float", "w": 16, "align": "right"},
            {"key": "delay", "zh": "延誤天數", "en": "Delay", "w": 16, "align": "right"},
            {"key": "exp", "zh": "預期延誤", "en": "Expected", "w": 16, "align": "right"},
            {"key": "prop", "zh": "傳導延誤", "en": "To Finish", "w": 16, "align": "right"},
            {"key": "resp", "zh": "應對措施", "en": "Response", "w": 82},
            {"key": "owner", "zh": "負責", "en": "Owner", "w": w - 370},
        ]
        assert abs(sum(c["w"] for c in cols) - w) < 0.01, sum(c["w"] for c in cols)

        def level_cell(level: str):
            zh = {"high": "高", "medium": "中", "low": "低"}[level]
            col = {"high": T.CRITICAL, "medium": T.NEAR, "low": T.SAGE}[level]

            def draw(shh: Sheet, cx, cy, cw, ch):
                shh.circle(cx + 3.0, cy + ch / 2, 1.0, fill=col)
                shh.text(cx + 5.6, cy + ch / 2 + 0.85, f"{zh}  {level}", 6.0, "medium", T.INK_2)
            return draw

        rows = []
        for e in ctx.exposure:
            r: Risk = e["risk"]
            phases_ = sorted({t.phase for t in e["linked"]})
            rows.append({
                "id": r.id, "title": r.title_zh, "en": r.title_en,
                "tasks": " · ".join(f"{t.wbs}" for t in e["linked"]),
                "phase": " · ".join(p.replace("P", "0") for p in phases_),
                "p": str(r.probability), "i": str(r.impact), "score": str(r.score),
                "level": level_cell(r.level), "minf": f"{e['min_float']} d", "delay": f"{r.delay_days} d",
                "exp": f"{e['expected_delay']:.1f} d",
                "prop": f"{e['propagated_delay']} d" if e["propagated_delay"] else "—",
                "resp": r.response_zh, "owner": r.owner, "_on": e["on_critical"], "_lvl": r.level,
            })
        y_reg_end = sh.table(x0, y2c, cols, rows, row_h=5.8, size=6.2,
                             row_style=lambda r: {"marker": T.CRITICAL} if r["_on"] else {})

        # Bottom strip: exposure by phase + contingency summary ------------------
        y3 = y_reg_end + 9.0
        if y3 < T.BODY_BOTTOM - 20:
            lw = T.col_span_w(7)
            y3c = sh.section(x0, y3, lw, "4.5", "各階段預期延誤曝險", "Expected Delay Exposure by Phase",
                             "工作天 working days · 機率加權 probability-weighted")
            exp = phase_exposure(ctx.exposure, s)
            items = [(PHASES[p["phase"]]["zh"], PHASES[p["phase"]]["en"], exp.get(p["phase"], 0.0),
                      f"{exp.get(p['phase'], 0.0):.1f} d") for p in ctx.phases]
            n_fit = int((T.BODY_BOTTOM - (y3c + 1.0)) // 5.4)
            self._hbars(sh, x0, y3c + 1.0, lw, items[:n_fit], row_h=5.4, label_w=62.0, color=T.NEAR)

            rx = T.col_x(7)
            rw = T.col_span_w(5)
            y3r = sh.section(rx, y3, rw, "4.6", "工期緩衝建議", "Contingency Recommendation")
            self._contingency_box(sh, rx, y3r + 1.0, rw, T.BODY_BOTTOM - y3r - 1.0)

    def _heatmap(self, sh: Sheet, x, y, w, h) -> None:
        ctx = self.ctx
        label_w = 9.0
        label_h = 8.0
        cell = min((w - label_w) / 5, (h - label_h) / 5)
        gx = x + label_w
        gy = y
        # place risks
        cells: Dict[tuple, List[str]] = {}
        for r in ctx.risks:
            cells.setdefault((r.probability, r.impact), []).append(r.id)
        for p in range(1, 6):
            for i in range(1, 6):
                score = p * i
                idx = 0 if score <= 4 else 1 if score <= 7 else 2 if score <= 11 else 3 if score <= 15 else 4
                cx = gx + (i - 1) * cell
                cy = gy + (5 - p) * cell
                sh.rect(cx, cy, cell, cell, fill=HexColor(T.HEAT[idx]), stroke=T.PAPER, width=0.9)
                ids = cells.get((p, i), [])
                dark = idx >= 3
                sh.text(cx + 1.4, cy + 3.0, str(score), 4.6, "regular", T.PAPER if dark else T.INK_3)
                for j, rid in enumerate(ids):
                    sh.text(cx + cell / 2, cy + cell / 2 + 1.1 + (j - (len(ids) - 1) / 2) * 3.6, rid, 6.2,
                            "medium", T.PAPER if dark else T.INK, align="center")
        # axes
        for p in range(1, 6):
            sh.text(gx - 2.0, gy + (5 - p) * cell + cell / 2 + 0.9, str(p), 5.8, "medium", T.INK_2, align="right")
        for i in range(1, 6):
            sh.text(gx + (i - 1) * cell + cell / 2, gy + 5 * cell + 3.6, str(i), 5.8, "medium", T.INK_2,
                    align="center")
        sh.text(gx + 2.5 * cell, gy + 5 * cell + 7.0, "影響  IMPACT", 5.0, "medium", T.INK_3, align="center",
                tracking=0.5)
        sh.vtext(x + 2.6, gy + 2.5 * cell, "機率  PROBABILITY", 5.0, "medium", T.INK_3, tracking=0.5)
        # legend to the right of the matrix if room, else below
        lx = gx + 5 * cell + 3.0
        if lx + 18 <= x + w:
            ly = gy
            for idx, lab in enumerate(["≤ 4 低", "5–7", "8–11 中", "12–15", "≥ 16 高"][::-1]):
                sh.rect(lx, ly, 3.2, 3.2, fill=HexColor(T.HEAT[4 - idx]))
                sh.text(lx + 4.6, ly + 2.6, lab, 5.0, "regular", T.INK_2)
                ly += 4.6

    def _scurve(self, sh: Sheet, x, y, w, h) -> None:
        mc = self.ctx.mc
        s = self.ctx.s
        pad_l, pad_r, pad_b, pad_t = 9.0, 4.0, 12.0, 4.0
        ax, ay = x + pad_l, y + pad_t
        aw, ah = w - pad_l - pad_r, h - pad_t - pad_b
        xs, ys = s_curve(mc, 80)
        xmin, xmax = float(mc.durations.min()), float(mc.durations.max())
        xmin = min(xmin, mc.deterministic - 2)

        def px(v):
            return ax + aw * (v - xmin) / (xmax - xmin)

        def py(v):
            return ay + ah * (1 - v)

        # gridlines
        for g in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            sh.line(ax, py(g), ax + aw, py(g), T.RULE, T.HAIRLINE, dash=None if g in (0.0,) else (0.5, 1.0))
            sh.text(ax - 1.6, py(g) + 0.8, f"{g:.0%}", 4.8, "regular", T.INK_3, align="right")
        # area under curve
        pts = [(px(xs[0]), py(0))] + [(px(a), py(b)) for a, b in zip(xs, ys)] + [(px(xs[-1]), py(0))]
        sh.polyline(pts, color=None, fill=T.PANEL_DEEP, close=True)
        sh.polyline([(px(a), py(b)) for a, b in zip(xs, ys)], color=T.INK, width=0.8)
        # markers
        marks = [
            (mc.deterministic, "基準 Baseline", T.CRITICAL, f"{mc.deterministic} d"),
            (mc.p50, "P50", T.INK_2, f"{mc.p50:.0f} d"),
            (mc.p80, "P80", T.NEAR, f"{mc.p80:.0f} d"),
            (mc.p90, "P90", T.INK_3, f"{mc.p90:.0f} d"),
        ]
        for i, (v, lab, col, txt) in enumerate(marks):
            prob = mc.probability_by(v)
            sh.line(px(v), py(prob), px(v), ay + ah, col, T.HAIRLINE, dash=(0.8, 0.8))
            sh.circle(px(v), py(prob), 0.8, fill=col)
            ly = ay + ah + 3.6 + (i % 2) * 3.4
            sh.text(px(v), ly, f"{lab}  {txt}", 4.8, "medium", col, align="center")
        # x axis
        sh.line(ax, ay + ah, ax + aw, ay + ah, T.RULE_STRONG, T.RULE_PT)
        sh.text(ax, ay + ah + 10.6, f"{fmt_short(s.calendar.offset_to_date(int(xmin)))}", 4.6, "regular", T.INK_3)
        sh.text(ax + aw, ay + ah + 10.6, f"{fmt_short(s.calendar.offset_to_date(int(xmax)))}  ·  工作天 working days",
                4.6, "regular", T.INK_3, align="right")
        # key numbers
        sh.text(ax + aw, ay + 3.6, f"準時機率 On-time  {mc.on_time_probability:.0%}", 5.2, "medium", T.CRITICAL,
                align="right")
        sh.text(ax + aw, ay + 7.2, f"平均 Mean  {mc.mean:.1f} d", 5.0, "regular", T.INK_2, align="right")

    def _float_hist(self, sh: Sheet, x, y, w, h) -> None:
        dist = float_distribution(self.ctx.s)
        pad_b = 14.0
        pad_t = 6.0
        ah = h - pad_b - pad_t
        n = len(dist)
        gap = 4.0
        bw = (w - gap * (n - 1)) / n
        vmax = max(d["count"] for d in dist) or 1
        colors = [T.CRITICAL, T.NEAR, T.BAR, T.BAR_SOFT, T.PANEL_DEEP]
        for g in range(0, vmax + 1, max(1, vmax // 4)):
            gy = y + pad_t + ah * (1 - g / vmax)
            sh.line(x, gy, x + w, gy, T.RULE, T.HAIRLINE, dash=(0.5, 1.0))
        for i, d in enumerate(dist):
            bx = x + i * (bw + gap)
            bh = ah * d["count"] / vmax
            sh.rect(bx, y + pad_t + ah - bh, bw, bh, fill=colors[i])
            sh.text(bx + bw / 2, y + pad_t + ah - bh - 1.6, f"{d['count']}", 7.0, "medium", T.INK, align="center")
            sh.text(bx + bw / 2, y + pad_t + ah + 4.0, f"{d['label']} d", 5.6, "medium", T.INK_2, align="center")
            sh.text(bx + bw / 2, y + pad_t + ah + 7.2, f"{d['share']:.0%}", 4.8, "regular", T.INK_3, align="center")
        sh.line(x, y + pad_t + ah, x + w, y + pad_t + ah, T.RULE_STRONG, T.RULE_PT)
        sh.text(x, y + pad_t + ah + 11.8, "總浮時（工作天）  Total float, working days", 4.8, "regular", T.INK_3)
        sh.text(x + w, y + pad_t + ah + 11.8,
                f"關鍵 {dist[0]['share']:.0%}  ·  ≤ 3 d {dist[0]['share'] + dist[1]['share']:.0%}", 4.8, "medium",
                T.CRITICAL, align="right")

    def _contingency_box(self, sh: Sheet, x, y, w, h) -> None:
        ctx, s, mc = self.ctx, self.ctx.s, self.ctx.mc
        cell_w = (w - 2 * T.GUTTER) / 3
        items = [
            ("基準完工", "Baseline Finish", fmt_d(s.project_finish), f"{mc.deterministic} 工作天 · 準時機率 {mc.on_time_probability:.0%}", T.CRITICAL),
            ("P50 完工", "P50 Finish", fmt_d(s.calendar.offset_to_date(int(round(mc.p50)) - 1)),
             f"{mc.p50:.0f} 工作天 · +{int(round(mc.p50)) - mc.deterministic} d", T.INK_2),
            ("P80 完工（建議承諾）", "P80 Finish · Recommended", fmt_d(s.calendar.offset_to_date(int(round(mc.p80)) - 1)),
             f"{mc.p80:.0f} 工作天 · 緩衝 +{ctx.contingency} d", T.NEAR),
        ]
        bh = min(h, 24.0)
        for i, (zh, en, big, sub, accent) in enumerate(items):
            bx = x + i * (cell_w + T.GUTTER)
            sh.rect(bx, y, cell_w, bh, stroke=T.RULE, width=T.HAIRLINE)
            sh.rect(bx, y, 0.9, bh, fill=accent)
            sh.label_pair(bx + 3.2, y + 5.0, zh, en)
            sh.text(bx + 3.2, y + 15.4, big, 11.5, "medium", T.INK)
            sh.text(bx + 3.2, y + 20.6, sub, 5.2, "regular", T.INK_3)
        ty = y + bh + 5.4
        if ty + 8 < y + h:
            note = (f"建議以 P80 作為對外承諾完工日期，並將 {ctx.contingency} 個工作天緩衝置於 IAQ 閘門之前；"
                    f"前期審批（R01）與長交期採購（R02 / R03）為緩衝消耗的主要來源，須每週檢視浮時消耗。")
            sh.paragraph(x, ty, note, w, 6.4, "regular", T.INK_2, leading=3.6,
                         max_lines=int((y + h - ty) // 3.6))

    # ---------------------------------------------------------------- build
    def build(self, path: str) -> None:
        c = rl_canvas.Canvas(path, pagesize=(T.PAGE_W * 72 / 25.4, T.PAGE_H * 72 / 25.4))
        c.setTitle(f"{PROJECT['title_en']} · A3 Schedule Baseline Report")
        c.setAuthor(PROJECT["prepared_by"])
        c.setSubject("CPM schedule · Gantt · Critical path · Risk analytics")
        sh = Sheet(c, self.fonts)
        for page in (self.page_summary, self.page_gantt, self.page_critical, self.page_risk):
            page(sh)
            c.showPage()
        c.save()


def build_report(schedule: Schedule, risks: Sequence[Risk], out_path: str) -> ReportContext:
    fonts = FontSet()
    mc = monte_carlo(schedule, risks)
    ctx = ReportContext(schedule, risks, mc)
    A3Report(ctx, fonts).build(out_path)
    return ctx

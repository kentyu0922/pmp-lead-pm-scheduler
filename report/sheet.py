"""Thin drawing layer over the ReportLab canvas.

All coordinates are millimetres measured from the top-left corner of the page,
which keeps layout arithmetic identical to the printed grid. Text is drawn as
mixed CJK / Latin runs so each script uses its own typeface.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas as rl_canvas

from . import theme as T
from .fonts import FontSet

_PT2MM = 25.4 / 72.0
# CJK ideographs break per character; closing punctuation clings to the preceding
# character and opening punctuation to the following one (kinsoku shori).
_TOKEN_RE = re.compile(
    r"(?:[（「『【“]*[\u2e80-\u9fff\uf900-\uffef][，。、；：）」』】！？”]*)|\S+\s*|\s+"
)


class Sheet:
    def __init__(self, c: rl_canvas.Canvas, fonts: FontSet):
        self.c = c
        self.f = fonts

    # ----- coordinate helpers -------------------------------------------------
    @staticmethod
    def X(x: float) -> float:
        return x * mm

    @staticmethod
    def Y(y: float) -> float:
        return (T.PAGE_H - y) * mm

    # ----- primitives ---------------------------------------------------------
    def paper(self) -> None:
        self.c.setFillColor(T.PAPER)
        self.c.rect(0, 0, T.PAGE_W * mm, T.PAGE_H * mm, stroke=0, fill=1)

    def line(self, x1, y1, x2, y2, color=T.RULE, width=T.HAIRLINE, dash: Optional[Sequence[float]] = None):
        c = self.c
        c.saveState()
        c.setStrokeColor(color)
        c.setLineWidth(width)
        c.setLineCap(0)
        if dash:
            c.setDash(list(dash))
        c.line(self.X(x1), self.Y(y1), self.X(x2), self.Y(y2))
        c.restoreState()

    def rect(self, x, y, w, h, fill=None, stroke=None, width=T.HAIRLINE, radius: float = 0.0):
        c = self.c
        c.saveState()
        if fill is not None:
            c.setFillColor(fill)
        if stroke is not None:
            c.setStrokeColor(stroke)
            c.setLineWidth(width)
        if radius > 0:
            c.roundRect(self.X(x), self.Y(y + h), w * mm, h * mm, radius * mm,
                        stroke=1 if stroke is not None else 0, fill=1 if fill is not None else 0)
        else:
            c.rect(self.X(x), self.Y(y + h), w * mm, h * mm,
                   stroke=1 if stroke is not None else 0, fill=1 if fill is not None else 0)
        c.restoreState()

    def diamond(self, cx, cy, r, fill=T.INK, stroke=None, width=T.HAIRLINE):
        c = self.c
        c.saveState()
        p = c.beginPath()
        p.moveTo(self.X(cx), self.Y(cy - r))
        p.lineTo(self.X(cx + r), self.Y(cy))
        p.lineTo(self.X(cx), self.Y(cy + r))
        p.lineTo(self.X(cx - r), self.Y(cy))
        p.close()
        if fill is not None:
            c.setFillColor(fill)
        if stroke is not None:
            c.setStrokeColor(stroke)
            c.setLineWidth(width)
        c.drawPath(p, stroke=1 if stroke is not None else 0, fill=1 if fill is not None else 0)
        c.restoreState()

    def circle(self, cx, cy, r, fill=T.INK, stroke=None, width=T.HAIRLINE):
        c = self.c
        c.saveState()
        if fill is not None:
            c.setFillColor(fill)
        if stroke is not None:
            c.setStrokeColor(stroke)
            c.setLineWidth(width)
        c.circle(self.X(cx), self.Y(cy), r * mm, stroke=1 if stroke is not None else 0,
                 fill=1 if fill is not None else 0)
        c.restoreState()

    def polyline(self, pts: Sequence[Tuple[float, float]], color=T.INK, width=T.RULE_PT,
                 fill=None, close=False):
        c = self.c
        c.saveState()
        p = c.beginPath()
        p.moveTo(self.X(pts[0][0]), self.Y(pts[0][1]))
        for x, y in pts[1:]:
            p.lineTo(self.X(x), self.Y(y))
        if close:
            p.close()
        if color is not None:
            c.setStrokeColor(color)
            c.setLineWidth(width)
        c.setLineJoin(1)
        if fill is not None:
            c.setFillColor(fill)
        c.drawPath(p, stroke=1 if color is not None else 0, fill=1 if fill is not None else 0)
        c.restoreState()

    # ----- text ---------------------------------------------------------------
    def width(self, s: str, size: float, weight: str = "regular", tracking: float = 0.0) -> float:
        """Width in mm."""
        w = self.f.width(s, size, weight) + tracking * max(len(s) - 1, 0)
        return w * _PT2MM

    def text(self, x, y, s: str, size: float = 8, weight: str = "regular", color=T.INK,
             align: str = "left", tracking: float = 0.0, upper: bool = False) -> float:
        """Draw a single line with baseline at `y`. Returns drawn width in mm."""
        if upper:
            s = s.upper()
        if not s:
            return 0.0
        w = self.width(s, size, weight, tracking)
        if align == "right":
            x = x - w
        elif align == "center":
            x = x - w / 2.0
        c = self.c
        c.saveState()
        c.setFillColor(color)
        cursor = self.X(x)
        base = self.Y(y)
        for font, frag in self.f.runs(s, weight):
            c.setFont(font, size)
            if tracking:
                c.drawString(cursor, base, frag, charSpace=tracking)
                cursor += pdfmetrics.stringWidth(frag, font, size) + tracking * len(frag)
            else:
                c.drawString(cursor, base, frag)
                cursor += pdfmetrics.stringWidth(frag, font, size)
        c.restoreState()
        return w

    def vtext(self, x, cy, s: str, size: float = 6, weight: str = "regular", color=T.INK,
              tracking: float = 0.0) -> None:
        """Text rotated 90° counter-clockwise, centred vertically on `cy` with baseline at `x`."""
        w = self.width(s, size, weight, tracking)
        c = self.c
        c.saveState()
        c.translate(self.X(x), self.Y(cy + w / 2.0))
        c.rotate(90)
        c.setFillColor(color)
        cursor = 0.0
        for font, frag in self.f.runs(s, weight):
            c.setFont(font, size)
            c.drawString(cursor, 0, frag, charSpace=tracking)
            cursor += pdfmetrics.stringWidth(frag, font, size) + tracking * len(frag)
        c.restoreState()

    def wrap(self, s: str, max_w: float, size: float, weight: str = "regular") -> List[str]:
        """Greedy line wrap: CJK breaks per character, Latin per word. Widths in mm."""
        lines: List[str] = []
        cur = ""
        for tok in _TOKEN_RE.findall(s):
            trial = cur + tok
            if self.width(trial.rstrip(), size, weight) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur.rstrip())
                cur = tok.lstrip() if tok.strip() else ""
        if cur.strip():
            lines.append(cur.rstrip())
        return lines

    def paragraph(self, x, y, s: str, max_w: float, size: float = 7.5, weight: str = "regular",
                  color=T.INK, leading: Optional[float] = None, max_lines: Optional[int] = None) -> float:
        """Draw wrapped text starting with first baseline at `y`. Returns next baseline y."""
        lead = leading if leading is not None else size * 1.5 * _PT2MM
        lines = self.wrap(s, max_w, size, weight)
        if max_lines is not None and len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip("…") + "…"
        for ln in lines:
            self.text(x, y, ln, size, weight, color)
            y += lead
        return y

    def ellipsize(self, s: str, max_w: float, size: float, weight: str = "regular") -> str:
        if self.width(s, size, weight) <= max_w:
            return s
        while s and self.width(s + "…", size, weight) > max_w:
            s = s[:-1]
        return s + "…"

    # ----- composite widgets --------------------------------------------------
    def label_pair(self, x, y, zh: str, en: str, size_zh=6.8, size_en=5.2, color_zh=T.INK_2,
                   color_en=T.INK_3, align="left", gap=2.6) -> float:
        """Small bilingual label: CJK line, then tracked uppercase Latin line."""
        self.text(x, y, zh, size_zh, "medium", color_zh, align=align)
        self.text(x, y + gap, en, size_en, "medium", color_en, align=align, tracking=0.55, upper=True)
        return y + gap

    def section(self, x, y, w, number: str, zh: str, en: str, note: str = "") -> float:
        """Section header with numeral, bilingual title and a rule. Returns content top y."""
        self.text(x, y, number, 7.2, "medium", T.CRITICAL, tracking=0.4)
        nx = x + 7.5
        self.text(nx, y, zh, 9.2, "medium", T.INK)
        wzh = self.width(zh, 9.2, "medium")
        self.text(nx + wzh + 2.2, y, en, 5.6, "medium", T.INK_3, tracking=0.6, upper=True)
        if note:
            self.text(x + w, y, note, 5.8, "regular", T.INK_3, align="right")
        self.line(x, y + 2.2, x + w, y + 2.2, T.RULE_STRONG, T.RULE_PT)
        return y + 6.8

    def table(self, x, y, columns, rows, row_h=5.0, header_h=7.2, size=6.6,
              header_size=6.0, zebra=False, row_style=None, top_rule=True) -> float:
        """Rule-based table. `columns`: dicts with key/zh/en/w/align. Returns bottom y.

        `row_style(row)` may return a dict with `color` (default text colour),
        `weight`, `fill` (row band) and `marker` (accent colour for left tick).
        """
        total_w = sum(c["w"] for c in columns)
        # header
        if top_rule:
            self.line(x, y, x + total_w, y, T.RULE_STRONG, T.RULE_PT)
        cx = x
        for col in columns:
            align = col.get("align", "left")
            tx = cx + (col["w"] - 1.2 if align == "right" else col["w"] / 2 if align == "center" else 1.2)
            self.text(tx, y + 3.2, col["zh"], header_size, "medium", T.INK_2, align=align)
            if col.get("en"):
                self.text(tx, y + 5.8, col["en"], header_size - 1.1, "medium", T.INK_3, align=align,
                          tracking=0.4, upper=True)
            cx += col["w"]
        y += header_h
        self.line(x, y, x + total_w, y, T.RULE_STRONG, T.RULE_PT)

        for i, row in enumerate(rows):
            st = row_style(row) if row_style else {}
            st = st or {}
            if st.get("fill") is not None:
                self.rect(x, y, total_w, row_h, fill=st["fill"])
            elif zebra and i % 2 == 1:
                self.rect(x, y, total_w, row_h, fill=T.PANEL)
            if st.get("marker") is not None:
                self.rect(x, y + 0.9, 0.7, row_h - 1.8, fill=st["marker"])
            color = st.get("color", T.INK)
            weight = st.get("weight", "regular")
            base = y + row_h / 2 + size * _PT2MM * 0.36
            cx = x
            for col in columns:
                val = row.get(col["key"], "")
                if callable(val):
                    val(self, cx, y, col["w"], row_h)
                else:
                    align = col.get("align", "left")
                    tx = cx + (col["w"] - 1.2 if align == "right" else col["w"] / 2 if align == "center" else 1.2)
                    s = self.ellipsize(str(val), col["w"] - 2.4, size, weight)
                    ccol = col.get("color", color)
                    if isinstance(ccol, str):
                        ccol = st.get(ccol, color)
                    self.text(tx, base, s, size, col.get("weight", weight), ccol, align=align)
                cx += col["w"]
            y += row_h
            self.line(x, y, x + total_w, y, T.RULE, T.HAIRLINE)
        return y

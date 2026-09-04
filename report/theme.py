"""Warm-white visual system: palette, A3 grid and type scale (all lengths in mm)."""

from reportlab.lib.colors import HexColor

# Paper & structure
PAPER = HexColor("#FAF6F0")
PANEL = HexColor("#F2ECE2")
PANEL_DEEP = HexColor("#EAE2D5")
RULE = HexColor("#D9D0C3")
RULE_STRONG = HexColor("#A79C8C")

# Ink
INK = HexColor("#2A2622")
INK_2 = HexColor("#5A534A")
INK_3 = HexColor("#948B7E")

# Semantic
CRITICAL = HexColor("#B2532B")
CRITICAL_SOFT = HexColor("#E6C4AF")
NEAR = HexColor("#C69A3E")
NEAR_SOFT = HexColor("#EBD9B4")
BAR = HexColor("#B3AA9D")
BAR_SOFT = HexColor("#D9D1C5")
SAGE = HexColor("#7C8A72")
SAGE_SOFT = HexColor("#CDD3C5")
WEEKEND = HexColor("#F1EAE0")

HEAT = ["#F3EDE3", "#EEDCC9", "#E4BE9F", "#D3946A", "#B2532B"]

# Page geometry (A3 landscape)
PAGE_W = 420.0
PAGE_H = 297.0
MARGIN = 16.0
CONTENT_W = PAGE_W - 2 * MARGIN          # 388
COLS = 12
GUTTER = 5.0
COL_W = (CONTENT_W - GUTTER * (COLS - 1)) / COLS   # 27.75

HEADER_TOP = MARGIN
HEADER_H = 18.0
BODY_TOP = 40.0
FOOTER_Y = PAGE_H - MARGIN + 3.5          # baseline of footer text
BODY_BOTTOM = PAGE_H - MARGIN - 4.0       # 277

HAIRLINE = 0.35   # pt
RULE_PT = 0.6     # pt


def col_x(index: int) -> float:
    """Left edge (mm) of grid column `index` (0-based)."""
    return MARGIN + index * (COL_W + GUTTER)


def col_span_w(n: int) -> float:
    """Width (mm) of `n` consecutive grid columns including inner gutters."""
    return n * COL_W + (n - 1) * GUTTER

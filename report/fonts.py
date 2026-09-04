"""Typeface resolution for the report.

Preferred pairing: Noto Sans TC (Traditional Chinese) + Inter (Latin / numerals).
Noto Sans TC is fetched once as a variable font and instanced into static
weights with fontTools; the result is cached under ~/.cache/lead_pm_fonts.
If networking or fontTools is unavailable the resolver falls back to system
CJK fonts (WenQuanYi Micro Hei, Droid Sans Fallback) so rendering never fails.
"""

from __future__ import annotations

import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Dict, Optional

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

CACHE_DIR = Path(os.environ.get("LEAD_PM_FONT_CACHE", Path.home() / ".cache" / "lead_pm_fonts"))
NOTO_TC_VF_URL = "https://github.com/google/fonts/raw/main/ofl/notosanstc/NotoSansTC%5Bwght%5D.ttf"

WEIGHTS = {"regular": 400, "medium": 500, "semibold": 600, "bold": 700}

INTER_DIRS = [
    Path("/usr/share/fonts/truetype/macos"),
    Path("/usr/share/fonts/truetype/inter"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".fonts",
]
INTER_FILES = {
    "regular": "Inter-Regular.ttf",
    "medium": "Inter-Medium.ttf",
    "semibold": "Inter-SemiBold.ttf",
    "bold": "Inter-Bold.ttf",
}

CJK_FALLBACKS = [
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
    ("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
]

_CJK_RE = re.compile(
    r"[\u2e80-\u2fdf\u3000-\u303f\u3040-\u30ff\u3100-\u312f\u3400-\u4dbf\u4e00-\u9fff"
    r"\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef\U00020000-\U0002ffff]+"
)


def _log(msg: str) -> None:
    print(f"[fonts] {msg}", file=sys.stderr)


def _ensure_noto_tc(weight: int) -> Optional[Path]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / f"NotoSansTC-{weight}.ttf"
    if target.exists():
        return target
    vf = CACHE_DIR / "NotoSansTC-VF.ttf"
    if not vf.exists():
        try:
            _log("downloading Noto Sans TC variable font ...")
            urllib.request.urlretrieve(NOTO_TC_VF_URL, vf)
        except Exception as exc:  # network unavailable
            _log(f"download failed ({exc}); using system fallback")
            return None
    try:
        from fontTools.ttLib import TTFont as FTFont
        from fontTools.varLib import instancer
        font = FTFont(str(vf))
        inst = instancer.instantiateVariableFont(font, {"wght": weight}, inplace=True, updateFontNames=True)
        inst.save(str(target))
        return target
    except Exception as exc:
        _log(f"instancing failed ({exc}); using system fallback")
        return None


class FontSet:
    """Registered font names keyed by weight, plus a mixed-script text splitter."""

    def __init__(self) -> None:
        self.cjk: Dict[str, str] = {}
        self.latin: Dict[str, str] = {}
        self._register()

    def _register(self) -> None:
        for key, w in WEIGHTS.items():
            path = _ensure_noto_tc(w)
            if path is not None:
                name = f"NotoSansTC-{key}"
                pdfmetrics.registerFont(TTFont(name, str(path)))
                self.cjk[key] = name
        if not self.cjk:
            for path, idx in CJK_FALLBACKS:
                if Path(path).exists():
                    pdfmetrics.registerFont(TTFont("CJK-fallback", path, subfontIndex=idx))
                    self.cjk = {k: "CJK-fallback" for k in WEIGHTS}
                    _log(f"using fallback CJK font {path}")
                    break
        if not self.cjk:
            raise RuntimeError("No CJK-capable font available")

        for key, fname in INTER_FILES.items():
            for d in INTER_DIRS:
                p = d / fname
                if p.exists():
                    name = f"Inter-{key}"
                    pdfmetrics.registerFont(TTFont(name, str(p)))
                    self.latin[key] = name
                    break
        if not self.latin:
            self.latin = dict(self.cjk)

    def runs(self, text: str, weight: str = "regular"):
        """Split text into (font_name, fragment) runs so CJK and Latin use their own faces."""
        weight = weight if weight in WEIGHTS else "regular"
        cjk = self.cjk.get(weight, self.cjk["regular"])
        latin = self.latin.get(weight, self.latin["regular"])
        if cjk == latin:
            return [(cjk, text)]
        out = []
        pos = 0
        for m in _CJK_RE.finditer(text):
            if m.start() > pos:
                out.append((latin, text[pos:m.start()]))
            out.append((cjk, m.group()))
            pos = m.end()
        if pos < len(text):
            out.append((latin, text[pos:]))
        return out

    def width(self, text: str, size: float, weight: str = "regular") -> float:
        return sum(pdfmetrics.stringWidth(frag, font, size) for font, frag in self.runs(text, weight))

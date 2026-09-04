#!/usr/bin/env python3
"""Generate the A3 executive schedule report (Summary · Gantt · Critical Path · Risk).

Usage:
    python generate_a3_report.py                       # writes output/A3_Schedule_Report_Commercial_Fitout.pdf
    python generate_a3_report.py --out my_report.pdf
    python generate_a3_report.py --png                 # also rasterise pages to PNG previews (needs pymupdf)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from report.a3_report import build_report
from report.cpm_engine import solve
from report.sample_project import build_calendar, build_risks, build_tasks

DEFAULT_OUT = Path("output") / "A3_Schedule_Report_Commercial_Fitout.pdf"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output PDF path")
    ap.add_argument("--png", action="store_true", help="also export PNG previews next to the PDF")
    ap.add_argument("--dpi", type=int, default=110, help="PNG preview resolution")
    args = ap.parse_args(argv)

    schedule = solve(build_tasks(), build_calendar())
    risks = build_risks()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    ctx = build_report(schedule, risks, str(args.out))

    print(f"PDF written: {args.out}  ({args.out.stat().st_size / 1024:.0f} KB)")
    print(f"  duration {schedule.project_duration} working days · {schedule.project_start} → {schedule.project_finish}")
    print(f"  critical tasks {len(ctx.critical_work)} / {len(ctx.work_tasks)} · "
          f"P50 {ctx.mc.p50:.1f} d · P80 {ctx.mc.p80:.1f} d · on-time {ctx.mc.on_time_probability:.1%}")

    if args.png:
        try:
            import fitz  # pymupdf
        except ImportError:
            print("pymupdf not installed; skipping PNG previews", file=sys.stderr)
            return 0
        doc = fitz.open(str(args.out))
        for i, page in enumerate(doc, 1):
            pix = page.get_pixmap(dpi=args.dpi)
            png = args.out.with_name(f"{args.out.stem}_p{i}.png")
            pix.save(str(png))
            print(f"  preview: {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Web/Pyodide entry: same pipeline as main.py through CPM, no MS Project COM."""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from experts.permit_expert import query_city_permit_rule
from core.brief_parse import parse_brief
from core.sub_wbs_splicer import splice_sub_modules
from core.calibration import calibrate_durations
from core.task_utils import clean_procurement_terminology, renumber_tasks_contiguously
from core.solver_engine import solve_schedule
from core import holidays as _holidays

try:
    from core.mspdi_xml import build_mspdi_xml
except ImportError:
    build_mspdi_xml = None  # type: ignore

TEMPLATE_MAP = {
    ("DB", "invite"): "MNC_Standard_Fitout_DB_Invite",
    ("DB", "public"): "MNC_Standard_Fitout_DB_Public",
    ("DBB", "invite"): "MNC_Standard_Fitout_DBB_Invite",
    ("DBB", "public"): "MNC_Standard_Fitout_Office_DBB",
}


def run_from_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    parsed = parse_brief(str(payload.get("brief") or ""))
    city = str(payload.get("city") or parsed.get("city") or "全国")
    area_raw = payload.get("area")
    area = int(area_raw) if area_raw not in (None, "", 0, "0") else int(parsed.get("area") or 8000)
    cost_raw = payload.get("cost")
    cost = int(cost_raw) if cost_raw not in (None, "", 0, "0") else int(parsed.get("cost") or 100)
    delivery = str(payload.get("delivery") or parsed.get("delivery") or "DB").upper()
    bidding = str(payload.get("bidding") or parsed.get("bidding") or "invite").lower()
    if delivery not in ("DB", "DBB"):
        delivery = "DB"
    if bidding not in ("invite", "public"):
        bidding = "invite"
    mode_key = TEMPLATE_MAP[(delivery, bidding)]
    start_date = str(payload.get("start_date") or parsed.get("start_date") or "").strip()
    project_name = str(
        payload.get("project_name") or parsed.get("project_name") or "新建办公空间工装项目"
    ).strip()
    addons = str(payload.get("addons") or parsed.get("addons") or "")
    if not start_date:
        return {
            "ok": False,
            "error": "Skill could not read a start date from the prompt (e.g. 国庆后上任 → first workday after National Day).",
            "mode_key": mode_key,
            "start_date": "",
            "finish_date": "",
            "task_count": 0,
            "tasks": [],
        }

    permit_info = query_city_permit_rule(city, area_sqm=area, cost_10k_rmb=cost)

    template_path = os.path.join(BASE_DIR, "templates", "wbs_templates.json")
    with open(template_path, "r", encoding="utf-8") as f:
        template_data = json.load(f)
    pack = template_data["templates"][mode_key]
    tasks = [dict(t) for t in pack["tasks"]]
    template_base_area = pack.get("base_area", 8000)

    if addons.strip():
        sub_path = os.path.join(BASE_DIR, "templates", "sub_wbs_modules.json")
        tasks = splice_sub_modules(tasks, addons, sub_path)

    tasks = calibrate_durations(tasks, permit_info, area, template_base_area, addons)
    if tasks:
        tasks[0]["name"] = project_name
    tasks = clean_procurement_terminology(tasks, mode_key)
    tasks = renumber_tasks_contiguously(tasks)

    holidays_pairs = _holidays.load_holiday_pairs()
    solve_res = solve_schedule(tasks, start_date, custom_holidays=holidays_pairs)
    tasks_solved = solve_res["tasks"]
    finish_date = max((t.get("finish") for t in tasks_solved if t.get("finish")), default=solve_res["finish_date"])

    verdict = permit_info.get("mandatory_desc") or permit_info.get("exempt_desc") or ""
    if permit_info.get("is_exempt"):
        verdict = permit_info.get("exempt_desc") or verdict
    elif permit_info.get("is_mandatory"):
        verdict = permit_info.get("mandatory_desc") or verdict

    return {
        "ok": True,
        "mode_key": mode_key,
        "start_date": start_date,
        "finish_date": finish_date,
        "task_count": len(tasks_solved),
        "permit_note": f"{permit_info.get('city', city)}: {verdict}".strip(": "),
        "tasks": tasks_solved,
        "mspdi_xml": build_mspdi_xml(tasks_solved, project_name, start_date) if build_mspdi_xml else "",
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8-sig") as fh:
            payload = json.load(fh)
    else:
        payload = json.load(sys.stdin)
    result = run_from_dict(payload)
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False)
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        json.dump(result, sys.stdout, ensure_ascii=False)

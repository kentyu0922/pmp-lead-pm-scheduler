# -*- coding: utf-8 -*-
"""Single brief parser for Cursor (main.py) and the webpage (web_run.py).

The website must not invent start dates or WBS. It sends the user prompt here.
"""
from __future__ import annotations

import datetime
import re
from typing import Any, Dict, Optional

try:
    from core import holidays as _holidays
except ImportError:
    import holidays as _holidays  # type: ignore

CITIES = (
    "北京|上海|天津|重庆|杭州|苏州|南京|深圳|广州|成都|武汉|西安|青岛|宁波|"
    "无锡|长沙|郑州|合肥|福州|厦门|昆明|贵阳|南宁|南昌|济南|沈阳|大连|哈尔滨|长春"
)
TARGET_HINT = re.compile(r"搬家|搬迁|交付|入伙|完工|竣工|搬出")
START_HINT = re.compile(r"上任|就任|到岗|开工|启动|kick\s*off|kickoff|到任", re.I)
DATE_RE = re.compile(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?")
HOLIDAY_KEYS = ("国庆", "春节", "元宵", "元旦", "劳动节", "五一", "清明", "端午", "中秋")


def _ymd(y: str, m: str, d: str) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _parse_day(iso: str) -> datetime.date:
    return datetime.datetime.strptime(iso[:10], "%Y-%m-%d").date()


def _first_workday_on_or_after(d: datetime.date) -> datetime.date:
    while d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d


def _first_workday_after_holiday(name_part: str, today: datetime.date) -> Optional[str]:
    rows = [h for h in _holidays.load_holiday_raw() if name_part in str(h.get("name", ""))]
    rows.sort(key=lambda h: str(h.get("finish") or ""))
    today_s = today.strftime("%Y-%m-%d")
    hit = next((h for h in rows if str(h.get("finish") or "") >= today_s), None)
    if hit is None:
        hit = next((h for h in rows if str(h.get("start") or "") >= today_s), None)
    if not hit or not hit.get("finish"):
        return None
    nxt = _parse_day(str(hit["finish"])) + datetime.timedelta(days=1)
    return _first_workday_on_or_after(nxt).strftime("%Y-%m-%d")


def parse_brief(brief: str, today: Optional[datetime.date] = None) -> Dict[str, Any]:
    text = re.sub(r"\s+", " ", brief or "").strip()
    today = today or datetime.date.today()
    out: Dict[str, Any] = {
        "city": None,
        "area": None,
        "cost": None,
        "delivery": "DB",
        "bidding": "invite",
        "start_date": None,
        "target_date": None,
        "project_name": None,
        "addons": "",
    }
    if not text:
        return out

    cm = re.search(rf"({CITIES})", text)
    if cm:
        out["city"] = cm.group(1)
    am = re.search(r"(\d+(?:\.\d+)?)\s*(?:㎡|平方米|平米|sqm|m2)", text, re.I)
    if am:
        out["area"] = int(round(float(am.group(1))))
    costm = re.search(r"(\d+(?:\.\d+)?)\s*(?:万|万元)", text)
    if costm:
        out["cost"] = int(round(float(costm.group(1))))

    if re.search(r"\bDBB\b|design-bid-build|公开招标|施工图招标", text, re.I):
        out["delivery"] = "DBB"
    elif re.search(r"\bD\s*&\s*B\b|\bDB\b|设计施工", text, re.I):
        out["delivery"] = "DB"
    if re.search(r"公开招标|\bpublic\b", text, re.I) and not re.search(r"邀请招标|\binvite\b", text, re.I):
        out["bidding"] = "public"

    nm = re.match(r"(.{2,40}?)(?:项目|工程)", text)
    if nm:
        out["project_name"] = nm.group(1).strip() + "项目"

    for key in HOLIDAY_KEYS:
        if key not in text or "后" not in text:
            continue
        if not (f"{key}后" in text or re.search(rf"{key}.{{0,8}}后", text)):
            continue
        after = _first_workday_after_holiday("国庆" if key == "国庆" else key, today)
        if not after:
            continue
        if START_HINT.search(text) or re.search(r"后上任|后开工|后到岗|后就任", text):
            out["start_date"] = after
            break
        if not out["start_date"] and not TARGET_HINT.search(text):
            out["start_date"] = after

    for m in DATE_RE.finditer(text):
        ymd = _ymd(m.group(1), m.group(2), m.group(3))
        i = m.start()
        ctx = text[max(0, i - 8) : i + len(m.group(0)) + 8]
        if TARGET_HINT.search(ctx):
            out["target_date"] = ymd
        elif START_HINT.search(ctx):
            out["start_date"] = ymd

    if not out["start_date"] and re.search(r"今天|今日|即日", text) and START_HINT.search(text):
        out["start_date"] = today.strftime("%Y-%m-%d")

    addons: list[str] = []
    if re.search(r"洁净|cleanroom|ISO\s*5|ISO\s*7|ISO\s*8", text, re.I):
        addons.append("Cleanroom_ISO_Validation_Module")
    if re.search(r"数据中心|机房|IDC|load\s*bank|LoadBank", text, re.I):
        addons.append("Datacenter_LoadBank_Module")
    if re.search(r"实验室|理化|Lab\b", text, re.I):
        addons.append("Lab_Construction_Module")
    if re.search(r"冷却塔", text):
        addons.append("Cooling_Tower_Module")
    if re.search(r"入苏|苏州备案", text):
        addons.append("Suzhou_Permit_Module")
    out["addons"] = ",".join(addons)

    if re.search(r"国企|政府|事业单位|财政资金", text) and int(out.get("cost") or 0) >= 400:
        out["bidding"] = "public"

    return out

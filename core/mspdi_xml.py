# -*- coding: utf-8 -*-
"""MSPDI XML that matches COM .mpp scheduling inputs (automatic tasks).

Microsoft Project recalculates automatic tasks from:
  duration + predecessors + task calendar + project start + constraints.

Cursor COM (mpp_renderer) writes duration + predecessors + calendar, then
CalculateProject() before SaveAs so the file opens with dates (no F9).
This XML stamps the solver's Start/Finish (same CPM) with ConstraintType ASAP
so Project shows the schedule on open while remaining automatic.

This module is the single XML writer for both Cursor (build_mpp) and the
webpage (web_run).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from xml.dom import minidom
from xml.etree import ElementTree as ET

try:
    from core._common import (
        CONSTRUCTION_CAL_NAME,
        parse_predecessor,
        _DEFAULT_WEEKEND_KEYWORDS,
        _GOV_APPROVAL_EXCLUDE_KEYWORDS,
    )
    from core import holidays as _holidays
except ImportError:
    from _common import (  # type: ignore
        CONSTRUCTION_CAL_NAME,
        parse_predecessor,
        _DEFAULT_WEEKEND_KEYWORDS,
        _GOV_APPROVAL_EXCLUDE_KEYWORDS,
    )
    import holidays as _holidays  # type: ignore

NS = "http://schemas.microsoft.com/project"
# Official MSPDI / COM pjLinkType
LINK_TYPE = {"FF": "0", "FS": "1", "SF": "2", "SS": "3"}
CONSTRAINT_TYPE = {"ASAP": "0", "ALAP": "1", "SNET": "2", "FNLT": "3", "MSO": "4", "MFO": "5", "SNLT": "6", "FNET": "7"}


def _ymd(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value).strip().replace("/", "-")[:10]


def _dt(value: Any, hour: int = 8, minute: int = 0) -> str:
    day = _ymd(value)
    if not day:
        return ""
    return f"{day}T{hour:02d}:{minute:02d}:00"


def _level(task: Dict[str, Any]) -> int:
    return int(task.get("outline_level", task.get("level", 3)))


def _duration_days(task: Dict[str, Any]) -> int:
    raw = task.get("duration", task.get("duration_days", 0)) or 0
    return int(round(float(raw)))


def _is_summary(task: Dict[str, Any], next_task: Optional[Dict[str, Any]]) -> bool:
    if next_task is not None and _level(next_task) > _level(task):
        return True
    return _level(task) <= 2


def uses_construction_calendar(task: Dict[str, Any]) -> bool:
    """Same assignment as core._common.create_task_with_outline."""
    if task.get("use_construction_cal") or task.get("work_weekend"):
        return True
    name = str(task.get("name", ""))
    level = _level(task)
    is_construction_summary = (
        level <= 2
        and any(kw in name for kw in _DEFAULT_WEEKEND_KEYWORDS)
        and not any(kw in name for kw in _GOV_APPROVAL_EXCLUDE_KEYWORDS)
    )
    return is_construction_summary


def _sub(parent: ET.Element, tag: str, text: Optional[str] = None) -> ET.Element:
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el


def _working_times(weekday: ET.Element) -> None:
    times = _sub(weekday, "WorkingTimes")
    a = _sub(times, "WorkingTime")
    _sub(a, "FromTime", "08:00:00")
    _sub(a, "ToTime", "12:00:00")
    b = _sub(times, "WorkingTime")
    _sub(b, "FromTime", "13:00:00")
    _sub(b, "ToTime", "17:00:00")


def _week_days(calendar: ET.Element, seven_day: bool) -> None:
    week = _sub(calendar, "WeekDays")
    for day in range(1, 8):
        working = seven_day or day not in (1, 7)
        wd = _sub(week, "WeekDay")
        _sub(wd, "DayType", str(day))
        _sub(wd, "DayWorking", "1" if working else "0")
        if working:
            _working_times(wd)


def _exceptions(calendar: ET.Element, rows: List[Dict[str, str]]) -> None:
    if not rows:
        return
    wrap = _sub(calendar, "Exceptions")
    for row in rows:
        name = str(row.get("name") or "节假日")
        start = _ymd(row.get("start"))
        finish = _ymd(row.get("finish"))
        if not start or not finish:
            continue
        exc = _sub(wrap, "Exception")
        _sub(exc, "EnteredByOccurrences", "0")
        period = _sub(exc, "TimePeriod")
        _sub(period, "FromDate", f"{start}T00:00:00")
        _sub(period, "ToDate", f"{finish}T23:59:00")
        _sub(exc, "Occurrences", "1")
        _sub(exc, "Name", name)
        _sub(exc, "Type", "1")
        _sub(exc, "DayWorking", "0")


def _add_calendars(root: ET.Element) -> None:
    holidays = _holidays.load_holiday_raw()
    spring = [h for h in holidays if "春节" in str(h.get("name", ""))]
    wrap = _sub(root, "Calendars")

    standard = _sub(wrap, "Calendar")
    _sub(standard, "UID", "1")
    _sub(standard, "Name", "Standard")
    _sub(standard, "IsBaseCalendar", "1")
    _sub(standard, "BaseCalendarUID", "-1")
    _week_days(standard, seven_day=False)
    _exceptions(standard, holidays)

    construction = _sub(wrap, "Calendar")
    _sub(construction, "UID", "2")
    _sub(construction, "Name", CONSTRUCTION_CAL_NAME)
    _sub(construction, "IsBaseCalendar", "1")
    _sub(construction, "BaseCalendarUID", "-1")
    _week_days(construction, seven_day=True)
    _exceptions(construction, spring)


def _add_task(tasks_el: ET.Element, task: Dict[str, Any], index: int, next_task: Optional[Dict[str, Any]]) -> None:
    t_el = _sub(tasks_el, "Task")
    tid = str(task.get("id", index + 1))
    level = _level(task)
    summary = _is_summary(task, next_task)
    milestone = (not summary) and (bool(task.get("milestone")) or _duration_days(task) == 0)
    dur = 0 if summary or milestone else _duration_days(task)

    _sub(t_el, "UID", tid)
    _sub(t_el, "ID", str(index + 1))
    _sub(t_el, "Name", str(task.get("name", "")))
    _sub(t_el, "Type", "1")
    _sub(t_el, "IsNull", "0")
    _sub(t_el, "OutlineLevel", str(level))
    # Solver already ran the same CPM as Cursor. Stamp those dates so Project
    # opens without F9 (COM SaveAs after CalculateProject does the same).
    # ConstraintType stays ASAP (0) unless the task has an explicit constraint —
    # dates are display/result, not SNET locks.
    start = _ymd(task.get("start"))
    finish = _ymd(task.get("finish"))
    if start:
        _sub(t_el, "Start", _dt(start, 8, 0))
        _sub(t_el, "EarlyStart", _dt(start, 8, 0))
    if finish:
        fh = 8 if milestone else 17
        _sub(t_el, "Finish", _dt(finish, fh, 0))
        _sub(t_el, "EarlyFinish", _dt(finish, fh, 0))
    if not summary:
        _sub(t_el, "Duration", f"PT{dur * 8}H0M0S")
        _sub(t_el, "DurationFormat", "7")
        _sub(t_el, "RemainingDuration", f"PT{dur * 8}H0M0S")
    _sub(t_el, "Milestone", "1" if milestone else "0")
    _sub(t_el, "Summary", "1" if summary else "0")
    _sub(t_el, "Critical", "0")
    _sub(t_el, "Priority", "500")
    _sub(t_el, "FixedCostAccrual", "3")

    constraint = task.get("constraint")
    if constraint:
        ctype = str(constraint.get("type", "MSO")).upper()
        cdate = _ymd(constraint.get("date", ""))
        _sub(t_el, "ConstraintType", CONSTRAINT_TYPE.get(ctype, "4"))
        if cdate:
            _sub(t_el, "ConstraintDate", _dt(cdate, 8, 0))
    else:
        _sub(t_el, "ConstraintType", "0")  # ASAP, same as COM Manual=False

    _sub(t_el, "CalendarUID", "2" if uses_construction_calendar(task) else "1")
    _sub(t_el, "Manual", "0")
    _sub(t_el, "Estimated", "0")

    if task.get("responsible_unit"):
        _sub(t_el, "Text1", str(task.get("responsible_unit", "")))
    if task.get("responsible_person"):
        _sub(t_el, "Text2", str(task.get("responsible_person", "")))
    if task.get("responsibility_flag"):
        _sub(t_el, "Text3", str(task.get("responsibility_flag", "")))

    if (not summary) and str(task.get("predecessors") or "").strip():
        for pid, link_type, lag in parse_predecessor(str(task.get("predecessors"))):
            link = _sub(t_el, "PredecessorLink")
            _sub(link, "PredecessorUID", str(pid))
            _sub(link, "Type", LINK_TYPE.get(link_type[:2].upper(), "1"))
            if lag:
                # MSPDI LinkLag is tenths of a minute; 1 working day = 4800
                _sub(link, "LinkLag", str(int(lag) * 4800))


def build_mspdi_xml(tasks: List[Dict[str, Any]], project_title: str, project_start: Any) -> str:
    root = ET.Element("Project", xmlns=NS)
    start = _ymd(project_start)
    _sub(root, "SaveVersion", "14")
    _sub(root, "Title", project_title or "")
    _sub(root, "ScheduleFromStart", "1")
    _sub(root, "StartDate", _dt(start, 8, 0) if start else "")
    _sub(root, "FYStartDate", "1")
    _sub(root, "CriticalSlackLimit", "0")
    _sub(root, "CurrencyDigits", "2")
    _sub(root, "CurrencySymbol", "¥")
    _sub(root, "CurrencyCode", "CNY")
    _sub(root, "CalendarUID", "1")
    _sub(root, "DefaultStartTime", "08:00:00")
    _sub(root, "DefaultFinishTime", "17:00:00")
    _sub(root, "MinutesPerDay", "480")
    _sub(root, "MinutesPerWeek", "2400")
    _sub(root, "DaysPerMonth", "20")
    _sub(root, "DefaultTaskType", "1")
    _sub(root, "DefaultFixedCostAccrual", "3")
    _sub(root, "DurationFormat", "7")
    _sub(root, "WorkFormat", "2")
    _sub(root, "HonorConstraints", "1")
    _sub(root, "NewTasksEstimated", "0")
    _sub(root, "NewTasksAreManual", "0")
    _sub(root, "NewTaskStartDate", "0")
    _sub(root, "WeekStartDay", "1")
    if start:
        _sub(root, "CurrentDate", _dt(start, 8, 0))
    _sub(root, "Autolink", "0")

    _add_calendars(root)
    tasks_el = _sub(root, "Tasks")
    for i, task in enumerate(tasks):
        nxt = tasks[i + 1] if i + 1 < len(tasks) else None
        _add_task(tasks_el, task, i, nxt)

    raw = ET.tostring(root, encoding="utf-8")
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def write_mspdi_xml(
    tasks: List[Dict[str, Any]],
    project_title: str,
    project_start: Any,
    output_path: str,
) -> str:
    xml = build_mspdi_xml(tasks, project_title, project_start)
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(xml)
    return output_path

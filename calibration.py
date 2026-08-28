# -*- coding: utf-8 -*-
"""
core/calibration.py — 工期校准引擎

从 main.py 提取的业务校准逻辑：
  * 面积非线性缩放（设计 0.3 / 现场施工 0.5）
  * 隔墙隐蔽→吊顶隐蔽 并行间隔下限（非整道工序各抬 14 天）
  * 图审/施工许可/BOQ/RFP 工期下限断言
  * 复杂特种施工最小工期断言
"""
import math
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

COMPLEX_SPECIAL_CONSTRUCTION_MIN_DAYS = 80

# 隔墙隐蔽 → 吊顶隐蔽 的间隔下限（工作日）。约束的是两道闸口之间的并行穿插链，
# 不是把每一道穿插工序都抬到 14 天（旧实现会把闸口之前的「大机电主管预埋」也抬到 14，
# 2000㎡ 工装会被明显拉长）。大面积靠施工缩放自然加大间隔。
HIDE_INSPECTION_GAP_MIN_DAYS = 14
BETWEEN_HIDE_KEYWORDS = ["墙面封板", "天花吊顶龙骨", "吊顶龙骨", "二次机电"]

# 实体施工（7 天日历）缩放指数：劳动力可多班组并行，比前期设计更接近面积平方根。
# 8000㎡ 模板上 2000㎡ → 0.50（旧全局 0.3 指数只压到 0.66，封板/饰面仍偏长）。
CONSTRUCTION_SCALE_EXPONENT = 0.5
DESIGN_SCALE_EXPONENT = 0.3

# 测试与联调(T&C)工期下限：小面积经面积缩放后易被压到 3-4 天，不足以完成系统联动调试。
# 用户要求(2026-08-28)给 T&C 稍足 buffer，故设 ≥6 工作日下限（大面积仍按 scale 自然放大）。
TC_MIN_DAYS = 6
TC_KEYWORDS = ["系统联动", "联调", "T&C", "测试与联调", "全系统联动调试"]


def _is_complex_special(area: int, addons_str: str) -> bool:
    """判断是否为复杂特种施工项目（实验室/洁净室/冷却塔/超大面积）。"""
    has_lab = "Lab" in addons_str or "实验室" in str(addons_str)
    has_cleanroom = "Cleanroom" in addons_str or "洁净" in str(addons_str)
    has_cooling_tower = "Cooling_Tower" in addons_str or "冷却塔" in str(addons_str)
    return has_lab or has_cleanroom or has_cooling_tower or area >= 5000


def calibrate_durations(
    tasks: List[Dict[str, Any]],
    permit_info: Dict[str, Any],
    area: int,
    template_base_area: int,
    addons_str: str = "",
    log: logging.Logger = None,
) -> List[Dict[str, Any]]:
    """面积非线性缩放 + 图审/许可/BOQ 工期下限断言。

    从 main.py L144-202 迁入。就地修改 tasks 的 duration/duration_days 字段。
    """
    if log is None:
        log = logger

    # 前期/设计用 0.3；现场 7 天日历工序用 0.5（2000/8000 → 0.50，避免工装被 8000㎡ 模板拖长）。
    design_scale = math.pow(area / float(template_base_area), DESIGN_SCALE_EXPONENT)
    site_scale = math.pow(area / float(template_base_area), CONSTRUCTION_SCALE_EXPONENT)
    is_complex = _is_complex_special(area, addons_str)
    skip_scale = (
        "图审", "施工许可", "备案", "招投标", "招标", "评标",
        "发标", "采购", "定标", "Lead Time", "审批", "验收", "移交",
    )

    current_phase_name = ""
    for t in tasks:
        level = t.get("outline_level", t.get("level", 1))
        t["level"] = level
        t["outline_level"] = level
        name = str(t.get("name", ""))
        if level <= 2:
            current_phase_name = name

        base_dur = int(round(float(t.get("duration_days", t.get("duration", 0)))))

        if "图审" in name and base_dur > 0:
            min_rev = permit_info.get("review_days_min", 7)
            if is_complex:
                min_rev = max(min_rev, 15)
            base_dur = max(base_dur, min_rev)

        elif any(kw in name for kw in ["施工图深化", "施工图出图", "深化设计", "图纸深化"]):
            if is_complex and base_dur > 0:
                base_dur = max(base_dur, 20)

        elif "施工许可" in name or ("备案" in name and "入苏" not in name):
            min_p = permit_info.get("permit_days_min", 5)
            if "施工许可" in name and base_dur > 0:
                base_dur = max(base_dur, min_p)

        elif "工程量清单" in name or "BOQ" in name:
            base_dur = min(base_dur, 8) if base_dur > 8 else base_dur
        elif "RFP" in name and "招标文件" in name and "编制" in name:
            base_dur = min(base_dur, 5) if base_dur > 5 else base_dur

        is_site = bool(t.get("work_weekend")) or ("实体施工" in current_phase_name)
        scale_factor = site_scale if is_site else design_scale
        if base_dur > 0 and scale_factor != 1.0:
            if not any(kw in name for kw in skip_scale):
                base_dur = max(1, int(round(base_dur * scale_factor)))

        if any(kw in name for kw in TC_KEYWORDS) and base_dur > 0:
            base_dur = max(base_dur, TC_MIN_DAYS)

        t["duration_days"] = base_dur
        t["duration"] = base_dur

    _ensure_hide_inspection_gap(tasks, HIDE_INSPECTION_GAP_MIN_DAYS, log)
    return tasks


def _ensure_hide_inspection_gap(tasks: List[Dict[str, Any]], min_days: int, log: logging.Logger) -> None:
    """两道隐蔽验收之间的并行穿插工序，取其最长工期作为间隔；不足 min_days 只抬这一组。"""
    between = [
        t for t in tasks
        if any(kw in str(t.get("name", "")) for kw in BETWEEN_HIDE_KEYWORDS)
        and int(t.get("duration_days") or 0) > 0
    ]
    if not between:
        return
    gap = max(int(t["duration_days"]) for t in between)
    if gap >= min_days:
        return
    factor = min_days / float(gap)
    for t in between:
        t["duration_days"] = max(1, int(round(int(t["duration_days"]) * factor)))
        t["duration"] = t["duration_days"]
    log.info(
        "  -> [隐蔽间隔] 隔墙隐蔽→吊顶隐蔽 并行链由 %s 工日抬至 %s 工日（下限 %s）",
        gap, max(t["duration_days"] for t in between), min_days,
    )


def validate_complex_construction(
    tasks: List[Dict[str, Any]],
    area: int,
    addons_str: str = "",
    log: logging.Logger = None,
) -> bool:
    """复杂特种施工最小工期断言。

    从 main.py L193-202 迁入。返回 True 表示通过，False 表示工期可能失真。
    """
    if log is None:
        log = logger

    if not _is_complex_special(area, addons_str):
        return True

    max_single_construction = max(
        (t.get("duration_days", 0) for t in tasks
         if t.get("outline_level", t.get("level", 3)) >= 3
         and not t.get("milestone", False)
         and t.get("duration_days", 0) > 0),
        default=0
    )
    if max_single_construction < COMPLEX_SPECIAL_CONSTRUCTION_MIN_DAYS:
        log.warning(
            f"  [PM业务校准] [WARNING]: 实体施工最长工期 {max_single_construction} 天 "
            f"< 门槛 {COMPLEX_SPECIAL_CONSTRUCTION_MIN_DAYS} 天，工期复用失真风险！"
        )
        return False
    return True

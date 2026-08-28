# -*- coding: utf-8 -*-
"""
core/calibration.py — 工期校准引擎

从 main.py 提取的业务校准逻辑：
  * 面积非线性缩放 (scale_factor = (area / base_area) ^ 0.3)
  * 图审/施工许可/BOQ/RFP 工期下限断言
  * 复杂特种施工最小工期断言
"""
import math
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

COMPLEX_SPECIAL_CONSTRUCTION_MIN_DAYS = 80

# 隔墙隐蔽验收 → 吊顶/顶棚隐蔽验收 之间穿插的实体工序（大机电主管/吊顶龙骨/二次机电等）。
# 用户要求：两道隐蔽验收闸口之间至少 2 周（14 天）间隔，且按面积放大。故对这些工序设工期下限，
# 面积缩放下不会把间隔压到 2 周以下（大面积仍按 scale_factor 自然放大）。
INTERSPERSED_TRADE_MIN_DAYS = 14
INTERSPERSED_TRADE_KEYWORDS = ["大机电", "主管桥架", "主管预埋", "吊顶龙骨", "天花吊顶龙骨", "二次机电"]

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

    # 面积非线性缩放指数 0.3（验证基线）。
    # 注意: 本模板 base_area=8000（8000㎡ 基准），故 area<base 时 scale<1（工期被压缩），
    # 指数越大压缩越狠、完工越早；指数越小越接近 1（工期越接近模板基准）。
    # 2000㎡ -> (2000/8000)^0.3≈0.66；1000㎡ -> (1000/8000)^0.3≈0.51。
    scale_factor = math.pow(area / float(template_base_area), 0.3)
    is_complex = _is_complex_special(area, addons_str)

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

        if base_dur > 0 and scale_factor != 1.0:
            if not any(kw in name for kw in [
                "图审", "施工许可", "备案", "招投标", "招标", "评标",
                "发标", "采购", "定标", "Lead Time", "审批", "验收", "移交"
            ]):
                base_dur = int(round(base_dur * scale_factor))

        # 隔墙隐蔽→吊顶隐蔽 之间穿插工序的工期下限（至少 2 周间隔，按面积放大）
        if any(kw in name for kw in INTERSPERSED_TRADE_KEYWORDS) and base_dur > 0:
            base_dur = max(base_dur, INTERSPERSED_TRADE_MIN_DAYS)

        # 测试与联调(T&C)工期下限（防小面积压缩，给足 buffer）
        if any(kw in name for kw in TC_KEYWORDS) and base_dur > 0:
            base_dur = max(base_dur, TC_MIN_DAYS)

        t["duration_days"] = base_dur
        t["duration"] = base_dur

    return tasks


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

# -*- coding: utf-8 -*-
"""
core/_common.py — 统一共享层

收纳被 mpp_renderer / msp_automation / main / solver_engine / sub_wbs_splicer
重复使用的常量、正则和工具函数，消除四处拷贝导致的漂移风险。

接口:
    CONSTRUCTION_CAL_NAME           施工7天日历常量
    parse_predecessor(pred_str)     前置任务字符串解析
    create_task_with_outline(...)   MS Project COM 任务创建 + 大纲缩进状态机
    MSProjectSession                (re-export) COM 会话上下文管理器
"""
import re
import logging
from typing import List, Tuple, Dict, Any, Optional

# ---------------------- 常量 ----------------------

CONSTRUCTION_CAL_NAME = "施工7天日历"

# 摘要级施工日历触发关键词（与 mpp_renderer 原硬编码一致）
_DEFAULT_WEEKEND_KEYWORDS = ["施工", "Phase 4", "苏州DBB"]

# 政府审批/报建阶段排除词：施工许可证办理、图审合格证、质安监报监等属法定行政行为，
# 周末与法定节假日均不办公 → 不得套用施工7天日历（强制5天）。与 solver_engine
# 的 GOV_APPROVAL_KEYWORDS 对齐，消除“摘要名含‘施工’误套7天”的漂移。
_GOV_APPROVAL_EXCLUDE_KEYWORDS = ["施工许可证", "许可证办理", "图审合格证", "质安监报监", "审批"]

# ---------------------- 前置任务解析 ----------------------

_PRED_RE = re.compile(r'^(\d+)(FS|FF|SS|SF)?([+-]?\d+)?')


def parse_predecessor(pred_str: str) -> List[Tuple[int, str, int]]:
    """解析前置任务字符串，返回 [(task_id, link_type, lag_days), ...]。

    支持 MSP 原生语法：
        "8"          -> (8, "FS", 0)
        "8SS+3"      -> (8, "SS", 3)
        "5FF-1"      -> (5, "FF", -1)
        "8SS+3,5FF"  -> [(8, "SS", 3), (5, "FF", 0)]

    Args:
        pred_str: 逗号分隔的前置任务字符串

    Returns:
        List of (task_id, link_type, lag_days) tuples
    """
    if not pred_str or not pred_str.strip():
        return []
    results: List[Tuple[int, str, int]] = []
    for part in pred_str.split(","):
        part = part.strip()
        if not part:
            continue
        m = _PRED_RE.match(part.upper())
        if not m or not m.group(1):
            continue
        pid = int(m.group(1))
        link_type = m.group(2) or "FS"
        lag = int(m.group(3)) if m.group(3) else 0
        results.append((pid, link_type, lag))
    return results


def split_predecessor_id_suffix(pred_str: str) -> List[Tuple[int, str]]:
    """轻量拆分：返回 [(task_id, suffix), ...]，suffix 为数字后面的原始字符串。

    供 sub_wbs_splicer / main.py 的 ID 重映射使用（只需 id + 原始后缀）。
    """
    if not pred_str or not pred_str.strip():
        return []
    results: List[Tuple[int, str]] = []
    for part in pred_str.split(","):
        part = part.strip()
        if not part:
            continue
        _i = 0
        while _i < len(part) and part[_i].isdigit():
            _i += 1
        if _i == 0:
            continue
        pid = int(part[:_i])
        suffix = part[_i:]
        results.append((pid, suffix))
    return results


# ---------------------- COM 任务创建 + 大纲缩进 ----------------------

def create_task_with_outline(
    project,
    task_dict: Dict[str, Any],
    current_depth: List[int],
    construction_cal_name: str = CONSTRUCTION_CAL_NAME,
    work_weekend_keywords: Optional[List[str]] = None,
    logger: Optional[logging.Logger] = None,
):
    """在 MS Project COM project 中按大纲层级新增单个任务。

    统一 mpp_renderer.build_mpp (L200-267) 与 msp_automation._create_one_task (L62-118)
    的重复实现：任务创建 → Manual/Estimated → 大纲缩进状态机 → 工期/里程碑 → 施工日历指派。

    Args:
        project: MS Project COM Project 对象
        task_dict: 任务字典，需含 id/name/duration/outline_level 等
        current_depth: 单元素列表 [int]，可变（函数内就地更新当前大纲深度）
        construction_cal_name: 施工7天日历名称
        work_weekend_keywords: 触发施工日历的摘要节点关键词（默认 _DEFAULT_WEEKEND_KEYWORDS）
        logger: 可选日志器

    Returns:
        MS Project COM Task 对象
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    t_id = task_dict.get("id")
    name = str(task_dict.get("name", f"任务{t_id}"))
    dur = task_dict.get("duration", task_dict.get("duration_days", 0))
    target_level = int(task_dict.get("outline_level", task_dict.get("level", 3)))
    is_ms = bool(task_dict.get("milestone", False)) or (dur == 0)
    work_weekend = bool(task_dict.get("work_weekend", False))

    keywords = work_weekend_keywords or _DEFAULT_WEEKEND_KEYWORDS

    # 1. 创建任务
    t_obj = project.Tasks.Add(name)
    try:
        t_obj.Manual = False
        t_obj.Estimated = False
    except Exception as e:
        logger.debug(f"[_common] 任务 {t_id} 属性设置失败: {e}")

    # 2. 相对差值状态机：大纲缩进/提升
    diff = target_level - current_depth[0]
    if diff > 0:
        for _ in range(diff):
            try:
                t_obj.OutlineIndent()
            except Exception as e:
                logger.debug(f"[_common] 缩进失败 {t_id}: {e}")
    elif diff < 0:
        for _ in range(-diff):
            try:
                t_obj.OutlineOutdent()
            except Exception as e:
                logger.debug(f"[_common] 提升缩进失败 {t_id}: {e}")
    current_depth[0] = target_level

    # 3. 叶子节点写工期/里程碑
    if target_level >= 3:
        if is_ms:
            try:
                t_obj.Milestone = True
                t_obj.Duration = "0d"
                t_obj.Estimated = False
            except Exception as e:
                logger.debug(f"[_common] 里程碑设置失败 {t_id}: {e}")
        else:
            try:
                _fdur = float(dur)
                if abs(_fdur - round(_fdur)) > 1e-9:
                    logger.warning(f"[_common] 任务 {t_id} 工期 {dur} 含小数点，已强制取整为 {int(round(_fdur))}d")
                int_dur = int(round(_fdur))
                t_obj.Duration = f"{int_dur}d"
                t_obj.Estimated = False
            except Exception as e:
                logger.debug(f"[_common] 工期设置失败 {t_id}: {e}")

    # 4. 施工日历指派
    is_construction_summary = (
        target_level <= 2
        and any(kw in name for kw in keywords)
        and not any(kw in name for kw in _GOV_APPROVAL_EXCLUDE_KEYWORDS)
    )
    if work_weekend or is_construction_summary:
        try:
            t_obj.Calendar = construction_cal_name
        except Exception as e:
            logger.debug(f"[_common] 赋予施工日历失败 {t_id}: {e}")

    return t_obj


# ---------------------- COM 会话 re-export ----------------------
# mpp_renderer 可直接 from core._common import MSProjectSession
try:
    from core.msp_session import MSProjectSession
except ImportError:
    try:
        from msp_session import MSProjectSession
    except ImportError:
        MSProjectSession = None  # type: ignore

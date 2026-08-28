# -*- coding: utf-8 -*-
"""
solver_engine.py - 高级 PMP 全年限动态节假日 CPM 求解引擎 (v3 单源化)

v3 关键变更：
  * 节假日统一由 config/holidays.json 经 core/holidays 加载，删除原 GLOBAL_HOLIDAY_REGISTRY 双源。
  * 新增 compute_cpm_metrics()：在正向解算结果上做反向遍历，估算总时差与关键路径，
    供离线预览；MPP 仍为负责任务日期与浮时的最终权威（保留委托，见 SKILL.md）。
"""
import sys
import os
import json
import datetime
import calendar
from datetime import timedelta
import re
from typing import List, Dict, Any, Optional, Set, Tuple

# v3 单源化：节假日统一从 config/holidays.json 加载（core/holidays 为唯一入口）
# 化繁为简：is_workday / build_holiday_bitmap / add_workdays 从 holidays 导入
try:
    from core.holidays import load_holiday_pairs, load_holiday_raw, is_workday, build_holiday_bitmap, add_workdays
except Exception:  # pragma: no cover - 兜底，保证独立运行不崩
    def load_holiday_pairs():
        return []
    def load_holiday_raw():
        return []
    def build_holiday_bitmap(active_holidays):
        return set()
    def is_workday(dt, holiday_bitmap):
        if dt.weekday() in (5, 6):
            return False
        return dt not in holiday_bitmap
    def add_workdays(start_date, workdays, holiday_bitmap):
        import datetime as _dt
        from datetime import timedelta as _td
        curr = start_date
        if workdays == 0:
            while not is_workday(curr, holiday_bitmap):
                curr += _td(days=1)
            return curr
        count = 0
        while count < workdays:
            curr += _td(days=1)
            if is_workday(curr, holiday_bitmap):
                count += 1
        return curr

# 统一提取高频常量，消除魔法字符串
RELOCATION_KEYWORDS = {"搬家", "搬迁", "正式入驻", "Relocation"}
CONSTRUCTION_PHASE_KEYWORDS = {"四", "五", "六", "施工", "Construction", "搬迁", "Relocation"}
EXCLUDE_CONSTRUCTION_KEYWORDS = {"图", "招", "前", "验收", "审批", "结算"}
# 政府审批/报建节点（施工许可证办理、图审合格证、质安监报监等）为法定行政行为，
# 周末与法定节假日均不办公 → 强制 5 天日历，绝不可套用施工7天日历。
# 与 mpp_renderer 物理渲染一致：MPP 侧该类叶子任务无 work_weekend 标记，落标准5天日历。
GOV_APPROVAL_KEYWORDS = {"施工许可证", "许可证办理", "图审合格证", "质安监报监"}

# 预编译前置任务正则表达式
PREDECESSOR_REGEX = re.compile(r'^(\d+)(FS|FF|SS|SF)?([+-]\d+)?')

def get_holidays_for_years(start_year: int, end_year: int, custom_holidays: Optional[List] = None) -> List[Tuple[str, str]]:
    """
    v3 单源：从 config/holidays.json 加载全量法定节假日区间（已由 core/holidays 合并跨年）。
    custom_holidays 作为可选覆盖/追加（main.py 传入同一份 config，确保与 MPP 日历一致）。
    """
    holiday_list: List[Tuple[str, str]] = list(load_holiday_pairs())
    if custom_holidays:
        for c in custom_holidays:
            if isinstance(c, (list, tuple)) and len(c) >= 2:
                holiday_list.append((c[0], c[1]))
    return holiday_list


# ==================== 模式感知工作日工具（修复 7天施工日历 与 MPP 不同步） ====================
# 旧逻辑: work_weekend 任务传 set() 空位图 -> 既忽略周末也忽略法定节假日, 与 MPP「施工7天日历」
# (周末工作 + 法定节假日停工) 不一致, 导致施工阶段求解器日期比 MPP 早 ~14 天(春节长度)。
# 中途修正: 改为传全量 holiday_bitmap -> 但 MPP 施工日历「仅春节停工」, 元旦/国庆照常施工,
#   仍会过修正 ~6 天(求解器比 MPP 晚)。
# 最终逻辑(与 mpp_renderer 物理注入的「施工7天日历」严格一致): 三种模式
#   ignore_h     : 24小时连续作业, 任意日皆工作
#   work_weekend : 7天施工日历 -> 周末工作, 且仅春节(含元宵返岗)停工, 其余法定节假日照常施工
#   standard     : 标准5天 -> 周末与全部法定节假日均停工
def _is_working_day(d: datetime.date, ignore_h: bool, work_weekend: bool, holiday_bitmap, spring_festival_bitmap) -> bool:
    if ignore_h:
        return True
    if d.weekday() >= 5:             # 周末
        return True if work_weekend else False   # 7天施工周末工作; 标准5天周末停工
    # 周一~周五
    if work_weekend:
        return d not in spring_festival_bitmap    # 7天施工: 仅春节停工
    return d not in holiday_bitmap                # 标准5天: 全部法定节假日停工


def _add_working_days(start: datetime.date, n: int, ignore_h: bool, work_weekend: bool, holiday_bitmap, spring_festival_bitmap) -> datetime.date:
    """从 start 起推进 n 个工作日 (n 可负); 工作日定义见 _is_working_day。n==0 时返回首个工作日(含 start)。"""
    if ignore_h:
        return start + timedelta(days=n)
    if n == 0:
        cur = start
        while not _is_working_day(cur, ignore_h, work_weekend, holiday_bitmap, spring_festival_bitmap):
            cur += timedelta(days=1)
        return cur
    sign = 1 if n > 0 else -1
    cnt = 0
    cur = start
    while cnt < abs(n):
        cur += timedelta(days=sign)
        if _is_working_day(cur, ignore_h, work_weekend, holiday_bitmap, spring_festival_bitmap):
            cnt += 1
    return cur


def solve_schedule(tasks: List[Dict[str, Any]], project_start_str: str, custom_holidays: Optional[List] = None) -> Dict[str, Any]:
    """
    执行 CPM 网络计划正向推演（v3：节假日单源）。
    """
    proj_start = datetime.datetime.strptime(project_start_str, "%Y-%m-%d").date()
    
    # 动态评估可能跨越的年份跨度 (如从项目开始年份后推 5 年)
    start_year = proj_start.year
    active_holidays = get_holidays_for_years(start_year, start_year + 5, custom_holidays)
    holiday_bitmap = build_holiday_bitmap(active_holidays)

    # 春节(含元宵返岗)停工位图 —— MPP「施工7天日历」仅对春节停工, 其余法定节假日照常施工。
    # 与 mpp_renderer 物理注入的施工日历例外策略完全一致, 杜绝求解器/MPP 二次漂移。
    spring_festival_raw = [h for h in load_holiday_raw() if "春节" in (h.get("name", "") or "")]
    spring_festival_bitmap = build_holiday_bitmap(
        [(h["start"], h["finish"]) for h in spring_festival_raw if h.get("start") and h.get("finish")]
    )

    # 建立 ID 到 Task 的字典
    task_dict = {t["id"]: t for t in tasks}
    dates = {}

    current_phase_name = ""
    for t in tasks:
        tid = t["id"]
        level = t.get("level", 3)
        dur = t.get("duration", 0)
        name_str = str(t.get("name", ""))
        preds_str = str(t.get("predecessors", ""))

        if level <= 2:
            current_phase_name = name_str
            continue

        cal_setting = str(t.get("calendar", ""))
        phase_str = str(t.get("phase", "")) or current_phase_name
        
        # 大原则自动判定：现场施工与竣工阶段默认套用 施工7天日历
        is_phase_4_5_6 = any(kw in current_phase_name for kw in CONSTRUCTION_PHASE_KEYWORDS) and not any(kw in current_phase_name for kw in EXCLUDE_CONSTRUCTION_KEYWORDS)
        
        # 例外规则：【正式搬迁/搬家】节点必须在客户工作日进行！
        is_relocation = any(kw in name_str for kw in RELOCATION_KEYWORDS)
        # 例外规则：【政府审批/报建】节点（施工许可证办理、图审合格证、质安监报监等）为法定行政行为，
        # 周末与法定节假日均不办公 → 强制 5 天日历，不得套用施工7天日历。
        is_gov_approval = any(kw in current_phase_name for kw in GOV_APPROVAL_KEYWORDS) or any(kw in name_str for kw in GOV_APPROVAL_KEYWORDS)

        ignore_h = t.get("ignore_holidays", False) or cal_setting in ["24小时", "24Hours", "24 Hours"]

        if is_relocation or is_gov_approval:
            work_weekend = False
        else:
            work_weekend = t.get("work_weekend", False) or cal_setting in ["施工日历", "施工7天日历", "7天8小时", "施工7天"] or (is_phase_4_5_6 and not cal_setting and not t.get("is_standard_calendar_patch", False))

        # 计算最早开始时间与结束时间 (支持高级网络图论 SS/FF/Lag; 模式感知工作日)
        # 模式: ignore_h=24h连续 / work_weekend=7天施工(周末工作, 法定节假日停工) / standard=5天
        early_start = proj_start
        min_finish_constraint = None

        if preds_str:
            parts = [p.strip() for p in preds_str.split(",")]
            max_start_from_preds = proj_start

            for part in parts:
                if not part: continue
                clean_part = part.upper().replace(' ', '').replace('DAYS', '').replace('DAY', '').replace('D', '')
                match = PREDECESSOR_REGEX.match(clean_part)
                if not match: continue

                pid = int(match.group(1))
                link_type = match.group(2) or "FS"
                lag_val = int(match.group(3)) if match.group(3) else 0

                if pid in dates:
                    p_start = datetime.datetime.strptime(dates[pid]["start"], "%Y-%m-%d").date()
                    p_finish = datetime.datetime.strptime(dates[pid]["finish"], "%Y-%m-%d").date()

                    if link_type == "FS":
                        # 紧跟前置完成之后开始; lag 可正(后推)/负(前拉), 均按模式感知工作日。
                        # 关键修正(对齐 MS Project): 前置为 0 工期里程碑时, 后继于【同日】开始
                        # (里程碑 Finish 即其排程当日); 前置为普通任务(dur>0)时, 后继于【次日】开始。
                        # 旧逻辑一律 p_finish+1 天, 导致每个里程碑 FS 链多算 1 天并在关键路径上累积漂移。
                        is_pred_milestone = (p_start == p_finish)
                        base = p_finish if is_pred_milestone else p_finish + timedelta(days=1)
                        next_start = _add_working_days(base, lag_val, ignore_h, work_weekend, holiday_bitmap, spring_festival_bitmap)
                        if next_start > max_start_from_preds:
                            max_start_from_preds = next_start

                    elif link_type == "SS":
                        next_start = _add_working_days(p_start, lag_val if lag_val > 0 else 0, ignore_h, work_weekend, holiday_bitmap, spring_festival_bitmap)
                        if next_start > max_start_from_preds:
                            max_start_from_preds = next_start

                    elif link_type == "FF":
                        target_finish = _add_working_days(p_finish, lag_val if lag_val > 0 else 0, ignore_h, work_weekend, holiday_bitmap, spring_festival_bitmap)
                        if not min_finish_constraint or target_finish > min_finish_constraint:
                            min_finish_constraint = target_finish

            if max_start_from_preds > early_start:
                early_start = max_start_from_preds
        else:
            early_start = _add_working_days(early_start, 0, ignore_h, work_weekend, holiday_bitmap, spring_festival_bitmap)

        if dur == 0:
            early_finish = early_start
        else:
            early_finish = _add_working_days(early_start, dur - 1, ignore_h, work_weekend, holiday_bitmap, spring_festival_bitmap)
                
        # 应用 FF 结束约束
        if min_finish_constraint and min_finish_constraint > early_finish:
            early_finish = min_finish_constraint
            # 反算 early_start
            curr = early_finish
            count = 0
            target_days = dur - 1 if dur > 0 else 0
            while count < target_days:
                curr -= timedelta(days=1)
                if _is_working_day(curr, ignore_h, work_weekend, holiday_bitmap, spring_festival_bitmap):
                    count += 1
            early_start = curr

        dates[tid] = {
            "start": early_start.strftime("%Y-%m-%d"),
            "finish": early_finish.strftime("%Y-%m-%d"),
            "work_weekend": work_weekend
        }

    # 动态向上汇总 Summary Tasks (Level 1 & Level 2)
    current_l2 = None
    l2_map = {}
    l1_node = None
    
    for t in tasks:
        lvl = t.get("outline_level", t.get("level", 1))
        tid = t["id"]
        if lvl == 1:
            l1_node = t
        elif lvl == 2:
            current_l2 = t
            l2_map[tid] = []
        elif lvl >= 3 and current_l2:
            if tid in dates:
                l2_map[current_l2["id"]].append(dates[tid])

    # 汇总 Level 2
    for l2_id, child_dates in l2_map.items():
        if child_dates:
            min_s = min(c["start"] for c in child_dates)
            max_f = max(c["finish"] for c in child_dates)
            dates[l2_id] = {"start": min_s, "finish": max_f, "work_weekend": False}

    # 汇总 Level 1
    if l1_node:
        all_child_dates = [d for d in dates.values() if d]
        if all_child_dates:
            min_s = min(d["start"] for d in all_child_dates)
            max_f = max(d["finish"] for d in all_child_dates)
            dates[l1_node["id"]] = {"start": min_s, "finish": max_f, "work_weekend": False}

    # 更新 tasks
    for t in tasks:
        tid = t["id"]
        if tid in dates:
            t["start"] = dates[tid]["start"]
            t["finish"] = dates[tid]["finish"]
            t["use_construction_cal"] = dates[tid].get("work_weekend", False)

    finish_date = max(d["finish"] for d in dates.values()) if dates else project_start_str
    return {
        "start_date": project_start_str,
        "finish_date": finish_date,
        "tasks": tasks
    }


def compute_cpm_metrics(tasks: List[Dict[str, Any]], project_end: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    v3 离线关键路径估算（工作日轴反向遍历 + 总时差 + 关键路径标记）。

    说明：基于 solve_schedule 已求出的 start/finish，在「工作日轴」上做反向遍历，给出离线
    预览用的总时差与关键路径。所有日期换算统一走工作日口径，避免周末虚增/虚减浮时。
    MPP 在最终写盘时仍会对任务日期与浮时做权威重算（保留委托）。
    假设前提：任务列表按拓扑顺序（id 升序、前置指向更早 id），前置类型以 FS 为主。
    """
    dated = [t for t in tasks if t.get("start") and t.get("finish")]
    if not dated:
        return tasks

    def to_date(x):
        return datetime.datetime.strptime(x, "%Y-%m-%d").date()

    bitmap = build_holiday_bitmap(load_holiday_pairs())
    es = {t["id"]: to_date(t["start"]) for t in dated}
    ef = {t["id"]: to_date(t["finish"]) for t in dated}
    proj_start = min(es.values())
    proj_end_dt = to_date(project_end) if project_end else max(ef.values())

    # 工作日轴：index = 自项目起点(含)起的第几个工作日；起点为 0
    def wd_index(d: datetime.date) -> int:
        n = 0
        cur = proj_start
        while cur <= d:
            if is_workday(cur, bitmap):
                n += 1
            cur += timedelta(days=1)
        return n - 1

    es_wd = {i: wd_index(es[i]) for i in es}
    dur_axis = {t["id"]: max(1, int(t.get("duration", 0) or 0)) for t in dated}
    ef_wd = {i: es_wd[i] + dur_axis[i] - 1 for i in es}
    proj_end_wd = max(ef_wd.values())

    # 后继映射（FS 为主）
    succ: Dict[int, List[int]] = {t["id"]: [] for t in dated}
    for t in dated:
        for p in str(t.get("predecessors", "")).split(","):
            p = p.strip()
            if not p:
                continue
            m = re.match(r'^(\d+)', p)
            if m:
                pid = int(m.group(1))
                if pid in succ and pid != t["id"]:
                    succ[pid].append(t["id"])

    ls_wd: Dict[int, int] = {}
    lf_wd: Dict[int, int] = {}
    for t in reversed(dated):
        i = t["id"]
        succs = succ[i]
        if succs:
            lf_wd[i] = min(ls_wd[s] for s in succs if s in ls_wd) - 1  # FS 间隔 1 工作日
        else:
            lf_wd[i] = proj_end_wd
        ls_wd[i] = lf_wd[i] - (dur_axis[i] - 1)
        slack = ls_wd[i] - es_wd[i]
        t["total_slack_days"] = slack
        t["critical"] = (slack <= 0)

    critical_ids = [t["id"] for t in dated if t.get("critical")]
    logger = _get_logger()
    logger.info(f"[CPM估算] 关键路径节点数={len(critical_ids)}，项目终点={proj_end_dt.isoformat()}")
    return tasks


def _get_logger():
    import logging
    return logging.getLogger("solver_engine")


def _find_target_task(tasks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    倒排目标锚定：返回项目中【真正最晚完成】的任务（即项目末端交付里程碑），
    而非第一个含 '搬家/搬迁' 关键词的任务。

    旧实现用 RELOCATION_KEYWORDS 取首个匹配，会误抓早期含搬迁词的规划/动员任务，
    导致倒排把错误的早期任务对齐到死线、真正项目末端被推后数月。
    项目末端 = finish 字典序最大者（ISO 日期串可直接比较），稳健且无需依赖关键词。
    """
    best = None
    for t in tasks:
        f = t.get("finish")
        if not f:
            continue
        if best is None or f > best.get("finish", ""):
            best = t
    return best


def solve_schedule_with_target(tasks: List[Dict[str, Any]], target_finish_date_str: str, target_buffer_days: int = 10, active_holidays: Optional[List] = None) -> Dict[str, Any]:
    """
    根据目标搬迁里程碑日 (如 2027-01-01) 进行商业倒排驱动与对齐。
    """
    target_dt = datetime.datetime.strptime(target_finish_date_str, "%Y-%m-%d").date()
    
    # 动态合成并缓存全局法定节假日位图
    if not active_holidays:
        active_holidays = get_holidays_for_years(target_dt.year - 3, target_dt.year + 3)
    holiday_bitmap = build_holiday_bitmap(active_holidays)

    # 获取目标日前缓冲的最优【客户工作日】搬迁日
    move_date = target_dt - timedelta(days=target_buffer_days)
        
    while not is_workday(move_date, holiday_bitmap):
        move_date -= timedelta(days=1)
        
    # 试算正向工期总天数 (基准试算)
    dummy_start = datetime.date(2026, 8, 1)
    res_dummy = solve_schedule(tasks, dummy_start.strftime("%Y-%m-%d"), active_holidays)
    
    # 锚定真正项目末端（finish 最晚的任务），而非首个搬迁关键词任务
    reloc_task = _find_target_task(res_dummy["tasks"])
        
    d_start_dummy = None
    for t in res_dummy["tasks"]:
        if "start" in t:
            d_start_dummy = datetime.datetime.strptime(t["start"], "%Y-%m-%d").date()
            break
            
    if not d_start_dummy:
        d_start_dummy = dummy_start
        
    d_finish_dummy = datetime.datetime.strptime(reloc_task["finish"], "%Y-%m-%d").date()

    # 计算需要的流转差距，精准反向推导正向 Kickoff 开工日
    delta_days = (move_date - d_finish_dummy).days
    actual_kickoff = d_start_dummy + timedelta(days=delta_days)

    while not is_workday(actual_kickoff, holiday_bitmap):
        actual_kickoff -= timedelta(days=1)
    
    # 迭代逼近修正环 (Iterative Refinement)
    final_res = solve_schedule(tasks, actual_kickoff.strftime("%Y-%m-%d"), active_holidays)
    
    actual_move_date_str = None
    _tgt = _find_target_task(final_res["tasks"])
    if _tgt:
        actual_move_date_str = _tgt.get("finish")
                
    if actual_move_date_str:
        actual_move_dt = datetime.datetime.strptime(actual_move_date_str, "%Y-%m-%d").date()
        max_iterations = 10
        iteration = 0
        while actual_move_dt > move_date and iteration < max_iterations:
            slip_days = (actual_move_dt - move_date).days
            actual_kickoff -= timedelta(days=slip_days)
            while not is_workday(actual_kickoff, holiday_bitmap):
                actual_kickoff -= timedelta(days=1)
                
            final_res = solve_schedule(tasks, actual_kickoff.strftime("%Y-%m-%d"), active_holidays)
            
            actual_move_date_str = None
            _tgt = _find_target_task(final_res["tasks"])
            if _tgt:
                actual_move_date_str = _tgt.get("finish")
            if not actual_move_date_str and final_res["tasks"]:
                for t in reversed(final_res["tasks"]):
                    if "finish" in t:
                        actual_move_date_str = t["finish"]
                        break
            if actual_move_date_str:
                actual_move_dt = datetime.datetime.strptime(actual_move_date_str, "%Y-%m-%d").date()
            else:
                break
            iteration += 1

    final_res["target_move_date"] = move_date.strftime("%Y-%m-%d")
    final_res["target_deadline"] = target_finish_date_str
    return final_res

if __name__ == "__main__":
    if len(sys.argv) > 1:
        input_json = sys.argv[1]
        if os.path.exists(input_json):
            with open(input_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            res = solve_schedule(data.get("tasks", []), data.get("project_start", "2026-09-01"))
            # v3 修复：默认输出 .solved.json，永不原地覆盖输入文件
            if "output_json" in data:
                out_file = data["output_json"]
            else:
                base, _ = os.path.splitext(input_json)
                out_file = base + ".solved.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
            print(f"[solver_engine] Solved schedule successfully. Finish date: {res['finish_date']} -> {out_file}")

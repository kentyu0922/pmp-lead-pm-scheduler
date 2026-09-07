# -*- coding: utf-8 -*-
"""
test_optimizer_v0.py — Schedule Optimizer v0 (critical path / float summary + fast-track suggestion)
运行: python tests/test_optimizer_v0.py   （无需 MS Project / COM；不 import main）

证明：
  (a) 固定用例（fixture）上：摘要字段齐全、驱动链浮时全 0、无负浮时、至少 1 条快速跟进建议，
      建议引用真实节点/浮时/关系（工期与基线逐一相同，不是编造的），基线任务表未被改写，
      重解校验 finish 不晚于基线、合规 0 error
  (b) 排除规则：里程碑 / 政府审批 / 验收 / IAQ 链 / 招采窗口 不会出现在建议对里
  (c) 确定性：同一输入两次运行输出 JSON 完全一致
  (d) 真实模板流水线（四套模板）：同样满足 (a) 与确定性；旧路径 compute_cpm_metrics 不受影响
"""
import sys
import os
import re
import json
import copy

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import logging
logging.disable(logging.CRITICAL)

from core import optimizer as O
from core import productivity as P
from core.solver_engine import solve_schedule, compute_cpm_metrics
from core import holidays as H
from core import compliance as C
from core.calibration import calibrate_durations
from core.task_utils import renumber_tasks_contiguously, fold_exempt_construction_permit
from experts.permit_expert import query_city_permit_rule

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


# ---------------------------------------------------------------------------
FIXTURE_START = "2026-09-01"


def fixture_tasks():
    """Small fit-out network: planning (5-day) → construction phase (7-day by phase rule) → IAQ + fire acceptance."""
    return [
        {"id": 1, "name": "Fixture 夹层办公室快速改造", "outline_level": 1, "duration_days": 0, "predecessors": ""},
        {"id": 2, "name": "Phase A 前期规划", "outline_level": 2, "duration_days": 0, "predecessors": ""},
        {"id": 3, "name": "[M] Kick Off 项目启动", "outline_level": 3, "duration_days": 0, "predecessors": "", "milestone": True},
        {"id": 4, "name": "需求任务书编制", "outline_level": 3, "duration_days": 5, "predecessors": "3"},
        {"id": 5, "name": "大楼物业装修申请", "outline_level": 3, "duration_days": 2, "predecessors": "3"},
        {"id": 6, "name": "[M] 任务书确认", "outline_level": 3, "duration_days": 0, "predecessors": "4,5", "milestone": True},
        {"id": 7, "name": "Phase B 实体施工阶段", "outline_level": 2, "duration_days": 0, "predecessors": ""},
        {"id": 8, "name": "隔墙轻钢龙骨骨架搭设", "outline_level": 3, "duration_days": 8, "predecessors": "6"},
        {"id": 9, "name": "大机电主管预埋安装", "outline_level": 3, "duration_days": 10, "predecessors": "8SS+2"},
        {"id": 10, "name": "[M] 隐蔽工程验收", "outline_level": 3, "duration_days": 0, "predecessors": "8,9", "milestone": True},
        {"id": 11, "name": "天花封板与墙面饰面", "outline_level": 3, "duration_days": 9, "predecessors": "10"},
        {"id": 12, "name": "地坪铺设", "outline_level": 3, "duration_days": 6, "predecessors": "11"},
        {"id": 13, "name": "机电末端与灯具安装", "outline_level": 3, "duration_days": 6, "predecessors": "12"},
        {"id": 14, "name": "[M] 施工全部完成", "outline_level": 3, "duration_days": 0, "predecessors": "13", "milestone": True},
        {"id": 15, "name": "Phase C 竣工验收与交付", "outline_level": 2, "duration_days": 0, "predecessors": ""},
        {"id": 16, "name": "首次室内空气盲测", "outline_level": 3, "duration_days": 2, "predecessors": "14"},
        {"id": 17, "name": "办公家具进场安装", "outline_level": 3, "duration_days": 2, "predecessors": "16"},
        {"id": 18, "name": "二次室内空气质量复测", "outline_level": 3, "duration_days": 2, "predecessors": "17"},
        {"id": 19, "name": "住建局消防验收与备案", "outline_level": 3, "duration_days": 5, "predecessors": "14"},
        {"id": 20, "name": "[M] 正式交付", "outline_level": 3, "duration_days": 0, "predecessors": "18,19", "milestone": True},
    ]


def solve_fixture():
    tasks = fixture_tasks()
    for t in tasks:
        t["duration"] = t["duration_days"]
    res = solve_schedule(tasks, FIXTURE_START, custom_holidays=H.load_holiday_pairs())
    return compute_cpm_metrics(res["tasks"], project_end=res["finish_date"])


def _templates():
    with open(os.path.join(BASE, "templates", "wbs_templates.json"), encoding="utf-8") as f:
        return json.load(f)["templates"]


def run_pipeline(mode, area, cost, city, start):
    """复刻 main.py 正排流水线（不含导出）"""
    tpl = _templates()
    tasks = copy.deepcopy(tpl[mode]["tasks"])
    permit = query_city_permit_rule(city, area_sqm=area, cost_10k_rmb=cost)
    tasks = calibrate_durations(tasks, permit, area, tpl[mode].get("base_area", 1000), "", cost_10k_rmb=cost)
    tasks = P.apply_productivity_durations(tasks)
    if permit.get("is_exempt"):
        tasks = fold_exempt_construction_permit(tasks, True)
    tasks = renumber_tasks_contiguously(tasks)
    res = solve_schedule(tasks, start, custom_holidays=H.load_holiday_pairs())
    return compute_cpm_metrics(res["tasks"], project_end=res["finish_date"])


def _common_assertions(label, solved, result, start):
    """Assertions shared by fixture and template runs."""
    by_id = {t["id"]: t for t in solved}
    leaves = {f["id"] for f in result["float"]["by_task"]}

    # ---- summary presence / shape
    for key in ("optimizer_version", "scope", "project", "critical_path", "float", "phases", "fast_track"):
        check(f"[{label}] summary has '{key}'", key in result)
    p, cp, fl = result["project"], result["critical_path"], result["float"]
    check(f"[{label}] project start/finish match solve output",
          p["start"] == min(t["start"] for t in solved if t.get("start")) and p["finish"] == max(t["finish"] for t in solved if t.get("finish")),
          f"{p['start']}..{p['finish']}")
    check(f"[{label}] baseline re-solve reproduces finish (deterministic solver)", p["baseline_resolve_consistent"] is True)

    chain = cp["chain"]
    check(f"[{label}] driving chain non-empty and ends at project finish",
          len(chain) >= 2 and chain[-1]["finish"] == p["finish"], f"{len(chain)}")
    check(f"[{label}] driving chain starts at project start", chain[0]["start"] == p["start"], chain[0])
    check(f"[{label}] last chain node has float 0; no chain node negative",
          chain[-1]["float_days"] == 0 and all(n["float_days"] >= 0 for n in chain),
          f"{[(n['id'], n['float_days']) for n in chain if n['float_days'] != 0]}")
    check(f"[{label}] chain nodes with float > 0 are flagged + explained as calendar-boundary float",
          all((n["float_days"] > 0) == n["calendar_boundary_float"] and (not n["calendar_boundary_float"] or "float" in n.get("note", "")) for n in chain)
          and cp["chain_nodes_with_calendar_boundary_float"] == sum(1 for n in chain if n["float_days"] > 0))
    check(f"[{label}] chain links are real predecessor tokens",
          all(str(n["link_from_predecessor"]["predecessor_id"]) in str(by_id[n["id"]].get("predecessors", "")) for n in chain[1:]))
    check(f"[{label}] critical_task_count == float-0 count; by_task marks on_driving_chain",
          cp["critical_task_count"] == sum(1 for f in fl["by_task"] if f["float_days"] == 0)
          and {f["id"] for f in fl["by_task"] if f["on_driving_chain"]} == {n["id"] for n in chain})
    check(f"[{label}] no negative float (backward pass inverts forward pass exactly)",
          all(f["float_days"] >= 0 for f in fl["by_task"]), f"{[(f['id'], f['float_days']) for f in fl['by_task'] if f['float_days'] < 0]}")
    check(f"[{label}] float distribution sums to leaf count",
          sum(fl["distribution"].values()) == len(fl["by_task"]) == p["leaf_count"])
    check(f"[{label}] float unit stated (working days, own calendar)", "working days" in fl["unit"])
    check(f"[{label}] float rows carry calendar label",
          all(f["calendar"] in (O.CAL_24H, O.CAL_CONSTRUCTION_7D, O.CAL_STANDARD_5D) for f in fl["by_task"]))
    check(f"[{label}] legacy preview count reported alongside (not replaced)",
          cp["legacy_preview_critical_count"] == sum(1 for t in solved if t.get("critical") is True and t["id"] in leaves))
    check(f"[{label}] scope is honest about v0 limits", "apply changes" in result["scope"]["does_not"] and "change any duration" in result["scope"]["does_not"])

    # ---- fast-track suggestion presence + explainability
    ft = result["fast_track"]
    sugg = ft["suggestions"]
    check(f"[{label}] at least ONE fast-track suggestion", len(sugg) >= 1, f"skipped={len(ft['skipped_chain_pairs'])}")
    chain_ids = [n["id"] for n in chain]
    for s in sugg:
        pr, su = s["predecessor"], s["successor"]
        sid = s["id"]
        check(f"[{label}] {sid} cites two consecutive chain activities",
              pr["id"] in chain_ids and su["id"] in chain_ids and chain_ids.index(su["id"]) == chain_ids.index(pr["id"]) + 1)
        fl_by = {f["id"]: f["float_days"] for f in fl["by_task"]}
        check(f"[{label}] {sid} cites floats equal to the computed table (>= 0)",
              pr["float_days"] == fl_by[pr["id"]] and su["float_days"] == fl_by[su["id"]] and pr["float_days"] >= 0 and su["float_days"] >= 0)
        check(f"[{label}] {sid} durations equal baseline durations (not hallucinated)",
              pr["duration_days"] == int(by_id[pr["id"]]["duration_days"]) and su["duration_days"] == int(by_id[su["id"]]["duration_days"]))
        check(f"[{label}] {sid} names/dates equal baseline",
              pr["name"] == by_id[pr["id"]]["name"] and su["start"] == by_id[su["id"]]["start"] and pr["finish"] == by_id[pr["id"]]["finish"])
        m = re.match(r"^(\d+)SS\+(\d+)$", s["proposed_relationship"])
        check(f"[{label}] {sid} proposes an explicit relationship token '{s['proposed_relationship']}'", bool(m))
        if m:
            check(f"[{label}] {sid} SS lag = pred duration − overlap",
                  int(m.group(1)) == pr["id"] and int(m.group(2)) == pr["duration_days"] - s["overlap_days"])
        check(f"[{label}] {sid} current relationship is plain FS", s["current_relationship"].startswith(f"{pr['id']} FS+0"))
        check(f"[{label}] {sid} overlap within rule bounds",
              1 <= s["overlap_days"] <= min(ft["rule"]["max_overlap_days"], pr["duration_days"] // 2, su["duration_days"] // 2))
        check(f"[{label}] {sid} states durations unchanged and not applied",
              s["durations_changed"] is False and s["applied_to_baseline"] is False)
        check(f"[{label}] {sid} has 'why' citing both ids and 'risk'",
              any(f"#{pr['id']}" in w and f"#{su['id']}" in w for w in s["why"]) and len(s["risk"]) >= 1)
        v = s.get("verified")
        check(f"[{label}] {sid} verified by re-solve", isinstance(v, dict) and v["baseline_finish"] == p["finish"])
        if v:
            check(f"[{label}] {sid} re-solved finish not later than baseline; saving >= 0",
                  v["new_finish"] <= p["finish"] and v["saving_calendar_days"] >= 0, f"{v['new_finish']} vs {p['finish']}")
            check(f"[{label}] {sid} compliance 0 error after change", v["compliance_errors_after"] == 0)
            check(f"[{label}] {sid} change log states before/after predecessors",
                  v["change_log"]["task_id"] == su["id"] and v["change_log"]["before"] != v["change_log"]["after"]
                  and s["proposed_relationship"] in v["change_log"]["after"])

    # ---- exclusions never suggested
    def excluded(name):
        return O._exclusion_reason(name) is not None
    check(f"[{label}] no suggestion touches milestone / statutory / inspection / IAQ / procurement activities",
          not any(excluded(s["predecessor"]["name"]) or excluded(s["successor"]["name"])
                  or s["predecessor"]["duration_days"] == 0 or s["successor"]["duration_days"] == 0 for s in sugg))
    check(f"[{label}] skipped pairs carry a reason", all(sp.get("reason") for sp in ft["skipped_chain_pairs"]))


def test_fixture():
    print("== 1. fixture: summary + suggestion + baseline untouched ==")
    solved = solve_fixture()
    snapshot = copy.deepcopy(solved)
    result = O.analyze_schedule(solved, FIXTURE_START, custom_holidays=H.load_holiday_pairs())
    check("[fixture] baseline task list not mutated", solved == snapshot)
    _common_assertions("fixture", solved, result, FIXTURE_START)

    by_id = {f["id"]: f for f in result["float"]["by_task"]}
    check("[fixture] parallel planning task #5 (2d vs 5d) has positive float", by_id[5]["float_days"] > 0, by_id[5]["float_days"])
    check("[fixture] construction leaves are on 7-day calendar (phase rule)",
          all(by_id[i]["calendar"] == O.CAL_CONSTRUCTION_7D for i in (8, 9, 11, 12, 13)))
    check("[fixture] gov acceptance #19 on standard 5-day calendar", by_id[19]["calendar"] == O.CAL_STANDARD_5D)
    chain_ids = [n["id"] for n in result["critical_path"]["chain"]]
    check("[fixture] driving chain runs 3 → 4 → 6 → 8 → 9(SS+2) → 10 → 11 → 12 → 13 → 14 → …",
          chain_ids[:10] == [3, 4, 6, 8, 9, 10, 11, 12, 13, 14], chain_ids)
    ss_node = next(n for n in result["critical_path"]["chain"] if n["id"] == 9)
    check("[fixture] SS+2 link recognised on chain", ss_node["link_from_predecessor"]["type"] == "SS" and ss_node["link_from_predecessor"]["lag"] == 2)
    # 7-day milestone #14 ends Sunday, 5-day #16 starts Monday → #14 may slip 1 working day: real calendar-boundary float
    check("[fixture] #14 (7d cal, Sunday) before #16 (5d cal) reports 1d calendar-boundary float, flagged",
          by_id[14]["float_days"] == 1 and next(n for n in result["critical_path"]["chain"] if n["id"] == 14)["calendar_boundary_float"] is True)
    check("[fixture] IAQ chain 16 → 17 → 18 → 20 has float 0 and is on the driving chain",
          all(by_id[i]["float_days"] == 0 and by_id[i]["on_driving_chain"] for i in (16, 17, 18, 20)))
    check("[fixture] fire acceptance #19 (5d) parallel to IAQ (6d) has float 1", by_id[19]["float_days"] == 1)

    sugg = result["fast_track"]["suggestions"]
    pairs = {(s["predecessor"]["id"], s["successor"]["id"]) for s in sugg}
    check("[fixture] suggests 11→12 (9d→6d) and 12→13 (6d→6d) FS→SS overlaps", {(11, 12), (12, 13)} <= pairs, pairs)
    s1 = next(s for s in sugg if s["predecessor"]["id"] == 11)
    check("[fixture] 11→12: overlap = floor(min(9,6)×0.5) = 3 → '11SS+6'", s1["overlap_days"] == 3 and s1["proposed_relationship"] == "11SS+6")
    check("[fixture] 11→12 re-solve saves > 0 calendar days", s1["verified"]["saving_calendar_days"] > 0, s1["verified"])
    skipped_reasons = " ".join(sp["reason"] for sp in result["fast_track"]["skipped_chain_pairs"])
    check("[fixture] 8→9 skipped because link is SS (v0 only converts plain FS)", "SS2" in skipped_reasons or "SS+2" in skipped_reasons or "link is SS" in skipped_reasons)
    check("[fixture] milestone pairs skipped with reason", "milestone" in skipped_reasons)

    # apply_suggestion never changes durations; only the one predecessor token
    new_tasks, log = O.apply_suggestion(solved, s1)
    check("[fixture] apply_suggestion → deep copy (baseline id 12 preds still '11')",
          next(t for t in solved if t["id"] == 12)["predecessors"] == "11" and next(t for t in new_tasks if t["id"] == 12)["predecessors"] == "11SS+6")
    check("[fixture] apply_suggestion keeps every duration",
          [t["duration_days"] for t in new_tasks] == [t["duration_days"] for t in solved] and log["durations_changed"] is False)

    # report text mentions the suggestion and the not-applied statement
    rep = O.render_report(result)
    check("[fixture] text report lists FT-1 with proposed token and 'NOT applied'", "FT-1" in rep and "11SS+6" in rep and "NOT applied" in rep)


def test_determinism():
    print("\n== 2. determinism: same input → identical JSON ==")
    a = O.analyze_schedule(solve_fixture(), FIXTURE_START, custom_holidays=H.load_holiday_pairs())
    b = O.analyze_schedule(solve_fixture(), FIXTURE_START, custom_holidays=H.load_holiday_pairs())
    check("[fixture] two runs byte-identical", json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True))


def test_no_start_date_no_verify():
    print("\n== 3. without start_date: summary + suggestion still produced, verification explicitly absent ==")
    r = O.analyze_schedule(solve_fixture())
    check("[fixture] suggestions present", r["fast_track"]["suggestion_count"] >= 1)
    check("[fixture] verification note says not verified", "not verified" in r["fast_track"]["verification"])
    check("[fixture] no 'verified' block on suggestions", all("verified" not in s for s in r["fast_track"]["suggestions"]))
    check("[fixture] baseline_resolve_consistent is None (not claimed)", r["project"]["baseline_resolve_consistent"] is None)


def test_unsolved_input_fails_loudly():
    print("\n== 4. unsolved tasks → ValueError (no fabricated dates) ==")
    try:
        O.analyze_schedule(fixture_tasks(), FIXTURE_START)
        check("raises ValueError", False)
    except ValueError:
        check("raises ValueError", True)


def test_templates():
    print("\n== 5. real templates (four modes, Shanghai 1500㎡ / 320万 / start 2026-08-28) ==")
    for mode in _templates():
        solved = run_pipeline(mode, 1500, 320, "上海", "2026-08-28")
        snapshot = copy.deepcopy(solved)
        legacy_sig = [(t["id"], t.get("critical"), t.get("total_slack_days")) for t in solved]
        r1 = O.analyze_schedule(solved, "2026-08-28", custom_holidays=H.load_holiday_pairs())
        check(f"[{mode}] baseline task list not mutated", solved == snapshot)
        check(f"[{mode}] legacy compute_cpm_metrics fields untouched",
              [(t["id"], t.get("critical"), t.get("total_slack_days")) for t in solved] == legacy_sig)
        _common_assertions(mode, solved, r1, "2026-08-28")
        r2 = O.analyze_schedule(run_pipeline(mode, 1500, 320, "上海", "2026-08-28"), "2026-08-28", custom_holidays=H.load_holiday_pairs())
        check(f"[{mode}] deterministic across runs", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))


if __name__ == "__main__":
    test_fixture()
    test_determinism()
    test_no_start_date_no_verify()
    test_unsolved_input_fails_loudly()
    test_templates()
    print(f"\n==== 结果: PASS={PASS}  FAIL={FAIL} ====")
    sys.exit(1 if FAIL else 0)

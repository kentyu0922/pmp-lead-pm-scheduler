# -*- coding: utf-8 -*-
"""
test_productivity_engine.py — V5-A: 生产率引擎泛化（partition_framing / flooring / painting + suspended_ceiling）
运行: python tests/test_productivity_engine.py   （无需 MS Project / COM；不 import main）

证明：
  (1) 生产率库：四类工序均含 low/typical/high 档，结构校验 fail loudly
  (2) 每个新工序的固定用例：quantity ÷ (rate × crew) × factors → final_duration，可解释字段齐全
  (3) rate_level 选档：只能选 config 中的档位；任务级自带速率键被忽略（LLM 不得发明工期）
  (4) 全流水线：四类同时打标 → 恰好 4 个公式节点，其余节点工期与旧路径逐一相同，SKILL.md 验证门不回归
  (5) 旧试点行为（仅吊顶）与 PR #3 数值一致
"""
import sys
import os
import json
import copy
import inspect
import logging

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import productivity as P
from core.solver_engine import solve_schedule, compute_cpm_metrics
from core import compliance as C
from core import holidays as H
from core.calibration import calibrate_durations
from core.task_utils import renumber_tasks_contiguously, fold_exempt_construction_permit
from experts.permit_expert import query_city_permit_rule

PASS = 0
FAIL = 0
NEW_TYPES = ["partition_framing", "flooring", "painting"]
ALL_TYPES = ["suspended_ceiling"] + NEW_TYPES
EXPLAIN_FIELDS = ["method", "activity_type", "quantity", "unit", "quantity_source", "productivity_rate",
                  "productivity_unit", "rate_level", "rate_level_source", "rate_table", "crew_size", "crew_source",
                  "daily_output", "factors", "factor_labels", "factor_product", "base_duration",
                  "calculated_duration", "final_duration", "duration_by_rate_level", "min_duration_days",
                  "rounding", "confidence", "confidence_reasons", "rates_version"]


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def raises(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


def _templates():
    with open(os.path.join(BASE, "templates", "wbs_templates.json"), encoding="utf-8") as f:
        return json.load(f)["templates"]


def _run_pipeline(mode, area, cost, city, start, pilot=False, activities=("suspended_ceiling",),
                  quantities=None, rate_level=None):
    """复刻 main.py 正排流水线（不含导出）：calibrate → [pilot tag] → apply → fold → renumber → solve → cpm → compliance"""
    tasks = copy.deepcopy(_templates()[mode]["tasks"])
    base_area = _templates()[mode].get("base_area", 1000)
    permit = query_city_permit_rule(city, area_sqm=area, cost_10k_rmb=cost)
    tasks = calibrate_durations(tasks, permit, area, base_area, "", cost_10k_rmb=cost)
    tagged = []
    if pilot:
        tagged = P.tag_legacy_pilot_tasks(tasks, area, activity_types=activities,
                                          quantity_overrides=quantities, rate_level=rate_level)
    tasks = P.apply_productivity_durations(tasks)
    if permit.get("is_exempt"):
        tasks = fold_exempt_construction_permit(tasks, True)
    tasks = renumber_tasks_contiguously(tasks)
    pairs = H.load_holiday_pairs()
    res = solve_schedule(tasks, start, custom_holidays=pairs)
    solved = compute_cpm_metrics(res["tasks"], project_end=res["finish_date"])
    issues = C.run_compliance_checks(solved, holiday_raw=H.load_holiday_raw())
    return {"tasks": solved, "finish": res["finish_date"], "issues": issues, "tagged": tagged, "permit": permit}


# ---------------------------------------------------------------------------
def test_rate_library_levels():
    print("== 1. 生产率库：四类工序 × low/typical/high 档 ==")
    rates = P.load_productivity_rates()
    check("rate_levels = [low, typical, high]", rates.get("rate_levels") == ["low", "typical", "high"], rates.get("rate_levels"))
    check("default_rate_level = typical", rates.get("default_rate_level") == "typical")
    for atype in ALL_TYPES:
        e = rates["activity_types"].get(atype)
        check(f"[{atype}] 在库中且字段齐全",
              e is not None and all(k in e for k in ("rates_per_worker_day", "default_crew_size", "min_duration_days",
                                                     "unit", "factors", "rate_basis", "legacy_template_bridge")))
        if not e:
            continue
        tbl = e["rates_per_worker_day"]
        check(f"[{atype}] low <= typical <= high 且均 > 0",
              0 < tbl["low"] <= tbl["typical"] <= tbl["high"], tbl)
    check("bridged_activity_types 覆盖四类（config 顺序）", P.bridged_activity_types(rates) == ALL_TYPES, P.bridged_activity_types(rates))

    # 结构校验 fail loudly
    bad = copy.deepcopy(rates)
    bad["activity_types"]["painting"]["rates_per_worker_day"]["low"] = 99.0
    check("low > typical → validate_rate_library 抛 ValueError", raises(lambda: P.validate_rate_library(bad)))
    bad2 = copy.deepcopy(rates)
    del bad2["activity_types"]["flooring"]["rates_per_worker_day"]["high"]
    check("缺 high 档 → ValueError", raises(lambda: P.validate_rate_library(bad2)))
    bad3 = copy.deepcopy(rates)
    bad3["activity_types"]["painting"]["legacy_template_bridge"]["factors"] = {"scope": "nonexistent"}
    check("桥接默认系数不在系数表 → ValueError", raises(lambda: P.validate_rate_library(bad3)))
    bad4 = copy.deepcopy(rates)
    bad4["default_rate_level"] = "medium"
    check("default_rate_level 不在 rate_levels → ValueError", raises(lambda: P.validate_rate_library(bad4)))

    # 旧版标量 rate_per_worker_day 兼容：三档取同值
    legacy = {"version": "t", "activity_types": {"x": {"unit": "m2", "rate_per_worker_day": 10.0, "default_crew_size": 2,
                                                       "min_duration_days": 1, "factors": {}}}}
    P.validate_rate_library(legacy)
    r = P.compute_activity_duration("x", 100, crew_size=2, rates=legacy)
    check("标量 rate 兼容：rate_table 三档相同，100/(10×2)=5d", r["rate_table"] == {"low": 10.0, "typical": 10.0, "high": 10.0}
          and r["final_duration"] == 5 and r["duration_by_rate_level"] == {"low": 5, "typical": 5, "high": 5}, r["rate_table"])


def test_partition_framing():
    print("\n== 2(a). partition_framing：900㎡ / 15㎡·人日 / 6 人 → 10d ==")
    r = P.compute_activity_duration("partition_framing", 900, crew_size=6)
    check("rate=15 (typical) unit=m2", r["productivity_rate"] == 15.0 and r["unit"] == "m2" and r["rate_level"] == "typical")
    check("daily_output = 90", r["daily_output"] == 90.0, r["daily_output"])
    check("base = 10.0, factor_product = 1.0, final = 10", r["base_duration"] == 10.0 and r["factor_product"] == 1.0 and r["final_duration"] == 10)
    check("duration_by_rate_level = low 15 / typical 10 / high 8 (900/120=7.5→8)",
          r["duration_by_rate_level"] == {"low": 15, "typical": 10, "high": 8}, r["duration_by_rate_level"])
    check("可解释字段齐全", all(k in r for k in EXPLAIN_FIELDS), f"missing={[k for k in EXPLAIN_FIELDS if k not in r]}")
    check("confidence = medium (实测 + 显式班组)", r["confidence"] == "medium")
    r2 = P.compute_activity_duration("partition_framing", 900, crew_size=6, factors={"complexity": "acoustic_double_stud", "access": "high_wall"})
    check("acoustic_double_stud×high_wall = 1.4×1.25 = 1.75 → 17.5 → 18d",
          abs(r2["factor_product"] - 1.75) < 1e-9 and r2["final_duration"] == 18, f"{r2['factor_product']} {r2['final_duration']}")
    r3 = P.compute_activity_duration("partition_framing", 100, crew_size=6)
    check("100㎡ → 1.11 → 2 → floor min 3", r3["final_duration"] == 3, r3["final_duration"])
    r4 = P.compute_activity_duration("partition_framing", 900)
    check("默认班组 6 → 同 10d 但 confidence 降为 low", r4["final_duration"] == 10 and r4["confidence"] == "low" and r4["crew_source"] == "default")
    check("未知系数键 → ValueError", raises(lambda: P.compute_activity_duration("partition_framing", 900, factors={"complexity": "feature"})))


def test_flooring():
    print("\n== 2(b). flooring：1350㎡ / 25㎡·人日 / 5 人 → 10.8 → 11d ==")
    r = P.compute_activity_duration("flooring", 1350, crew_size=5)
    check("rate=25 (typical), crew=5, daily_output=125", r["productivity_rate"] == 25.0 and r["daily_output"] == 125.0)
    check("calculated 10.8 → final 11", r["calculated_duration"] == 10.8 and r["final_duration"] == 11, f"{r['calculated_duration']} {r['final_duration']}")
    check("duration_by_rate_level = low 18 / typical 11 / high 8",
          r["duration_by_rate_level"] == {"low": 18, "typical": 11, "high": 8}, r["duration_by_rate_level"])
    check("finish 系数缺省 → unspecified(1.0) 出现在 factor_labels", r["factor_labels"].get("finish") == "unspecified(1.0)", r["factor_labels"])
    check("可解释字段齐全", all(k in r for k in EXPLAIN_FIELDS))
    r2 = P.compute_activity_duration("flooring", 1350, crew_size=5, factors={"finish": "carpet_tile"})
    check("carpet_tile ×0.6 → 6.48 → 7d（更快）", r2["final_duration"] == 7 and r2["factor_labels"]["finish"] == "carpet_tile", r2["final_duration"])
    r3 = P.compute_activity_duration("flooring", 1350, crew_size=5, factors={"finish": "ceramic_tile"})
    check("ceramic_tile ×2.5 → 27.0 → 27d（更慢）", r3["final_duration"] == 27, r3["final_duration"])
    r4 = P.compute_activity_duration("flooring", 100, crew_size=5)
    check("100㎡ → 0.8 → 1 → floor min 2", r4["final_duration"] == 2, r4["final_duration"])
    check("quantity<=0 → ValueError", raises(lambda: P.compute_activity_duration("flooring", -5, crew_size=5)))


def test_painting():
    print("\n== 2(c). painting：2700㎡ / 35㎡·人日 / 6 人 → 12.857 → 13d ==")
    r = P.compute_activity_duration("painting", 2700, crew_size=6)
    check("rate=35 (typical), daily_output=210", r["productivity_rate"] == 35.0 and r["daily_output"] == 210.0)
    check("calculated ≈ 12.857 → final 13", abs(r["calculated_duration"] - 12.8571) < 1e-3 and r["final_duration"] == 13, f"{r['calculated_duration']} {r['final_duration']}")
    check("duration_by_rate_level = low 18 / typical 13 / high 9",
          r["duration_by_rate_level"] == {"low": 18, "typical": 13, "high": 9}, r["duration_by_rate_level"])
    check("可解释字段齐全", all(k in r for k in EXPLAIN_FIELDS))
    r2 = P.compute_activity_duration("painting", 2700, crew_size=6, factors={"scope": "with_ceiling_board"})
    check("scope=with_ceiling_board ×1.5 → 19.29 → 20d", r2["final_duration"] == 20 and abs(r2["factor_product"] - 1.5) < 1e-9, r2["final_duration"])
    r3 = P.compute_activity_duration("painting", 2700, crew_size=6, factors={"complexity": "feature_colour", "access": "high_ceiling"})
    check("feature_colour×high_ceiling = 1.4×1.3 = 1.82 → 23.4 → 24d",
          abs(r3["factor_product"] - 1.82) < 1e-9 and r3["final_duration"] == 24, f"{r3['factor_product']} {r3['final_duration']}")
    r4 = P.compute_activity_duration("painting", 2700, crew_size=6, quantity_source=P.QTY_DERIVED)
    check("推导工程量 → confidence low + 原因说明", r4["confidence"] == "low" and any("derived" in s for s in r4["confidence_reasons"]))


def test_rate_level_selection_and_config_only():
    print("\n== 3. rate_level 选档 + 速率只能来自 config ==")
    lo = P.compute_activity_duration("partition_framing", 900, crew_size=6, rate_level="low")
    hi = P.compute_activity_duration("partition_framing", 900, crew_size=6, rate_level="high")
    check("rate_level=low → rate 10, 15d, rate_level_source=task", lo["productivity_rate"] == 10.0 and lo["final_duration"] == 15 and lo["rate_level_source"] == "task")
    check("rate_level=high → rate 20, 8d", hi["productivity_rate"] == 20.0 and hi["final_duration"] == 8)
    check("confidence_reasons 记录选档", any("pinned" in s for s in lo["confidence_reasons"]), lo["confidence_reasons"])
    check("未知 rate_level → ValueError", raises(lambda: P.compute_activity_duration("painting", 100, rate_level="medium")))
    for atype in ALL_TYPES:
        r = P.compute_activity_duration(atype, 1000, crew_size=4)
        d = r["duration_by_rate_level"]
        check(f"[{atype}] 单调：low >= typical >= high 且 typical == final",
              d["low"] >= d["typical"] >= d["high"] and d["typical"] == r["final_duration"], d)

    sig = inspect.signature(P.compute_activity_duration)
    check("compute_activity_duration 无任何自定义速率参数（rate 只能选档，不能给数）",
          not any(p in sig.parameters for p in ("rate", "productivity_rate", "rate_per_worker_day", "daily_output")), list(sig.parameters))

    # 任务级夹带速率键 → 忽略并告警，结果与不带键完全一致
    class _Cap(logging.Handler):
        def __init__(self):
            super().__init__(); self.msgs = []
        def emit(self, rec):
            self.msgs.append(rec.getMessage())
    cap = _Cap(); lg = logging.getLogger("t.prod"); lg.addHandler(cap); lg.setLevel(logging.INFO); lg.propagate = False
    tasks = [
        {"id": 1, "name": "A", "level": 3, "duration_days": 14, "duration": 14, "activity_type": "partition_framing",
         "quantity": 900, "crew_size": 6, "productivity_rate": 900.0, "rate_per_worker_day": 900.0},
        {"id": 2, "name": "B", "level": 3, "duration_days": 14, "duration": 14, "activity_type": "partition_framing",
         "quantity": 900, "crew_size": 6},
        {"id": 3, "name": "C", "level": 3, "duration_days": 14, "duration": 14, "activity_type": "partition_framing",
         "quantity": 900, "crew_size": 6, "rate_level": "medium"},
    ]
    P.apply_productivity_durations(tasks, log=lg)
    check("夹带 productivity_rate=900 被忽略 → 仍 10d（与无键任务一致）", tasks[0]["duration"] == 10 == tasks[1]["duration"], tasks[0]["duration"])
    check("夹带速率键触发告警", any("ignored" in m and "productivity_rate" in m for m in cap.msgs), cap.msgs[:2])
    check("非法 rate_level 任务 → 保留模板 14d（不抛错）", tasks[2]["duration"] == 14 and "productivity" not in tasks[2])


def test_tagging_all_types_and_bridge_factors():
    print("\n== 4. 多类打标：每类命中各自节点，桥接默认系数落到任务 ==")
    tasks = [
        {"id": 1, "name": "隔墙轻钢龙骨骨架搭设", "outline_level": 4, "duration_days": 14, "predecessors": ""},
        {"id": 2, "name": "[M] 隔墙及主管管线隐蔽工程验收 (In-Wall Inspection)", "outline_level": 4, "duration_days": 2, "predecessors": "1"},
        {"id": 3, "name": "墙面封板与天花吊顶龙骨安装", "outline_level": 4, "duration_days": 14, "predecessors": "2"},
        {"id": 4, "name": "天花封石膏板与墙顶乳胶漆饰面", "outline_level": 4, "duration_days": 16, "predecessors": "3"},
        {"id": 5, "name": "架空防静电地板/地砖/地毯铺设", "outline_level": 4, "duration_days": 10, "predecessors": "4"},
        {"id": 6, "name": "Stage: 隔墙轻钢龙骨与乳胶漆", "outline_level": 2, "duration_days": 0, "predecessors": ""},
    ]
    tagged = P.tag_legacy_pilot_tasks(tasks, 1500, activity_types="all")
    by = {t["id"]: t for t in tasks}
    check("恰好 4 个节点被打标 (1,3,4,5)", sorted(tagged) == [1, 3, 4, 5], tagged)
    check("#1 → partition_framing 900㎡ derived", by[1].get("activity_type") == "partition_framing" and by[1]["quantity"] == 900.0 and by[1]["quantity_source"] == P.QTY_DERIVED)
    check("#3 → suspended_ceiling 1275㎡", by[3].get("activity_type") == "suspended_ceiling" and by[3]["quantity"] == 1275.0)
    check("#4 → painting 2700㎡ + 桥接系数 scope=with_ceiling_board", by[4].get("activity_type") == "painting" and by[4]["quantity"] == 2700.0
          and by[4].get("factors") == {"scope": "with_ceiling_board"}, by[4].get("factors"))
    check("#5 → flooring 1350㎡", by[5].get("activity_type") == "flooring" and by[5]["quantity"] == 1350.0)
    check("验收节点 #2 与汇总 #6 未打标", "activity_type" not in by[2] and "activity_type" not in by[6])

    # 逐类实测覆盖 + 选档
    tasks2 = copy.deepcopy([{k: v for k, v in t.items() if k not in ("activity_type", "quantity", "quantity_source", "unit", "factors")} for t in tasks])
    P.tag_legacy_pilot_tasks(tasks2, 1500, activity_types=["partition_framing", "flooring"],
                             quantity_overrides={"partition_framing": 800}, rate_level="low")
    by2 = {t["id"]: t for t in tasks2}
    check("仅请求的两类被打标", sorted(t["id"] for t in tasks2 if t.get("activity_type")) == [1, 5])
    check("partition 实测 800 measured；flooring 推导 1350 derived",
          by2[1]["quantity"] == 800.0 and by2[1]["quantity_source"] == P.QTY_MEASURED
          and by2[5]["quantity"] == 1350.0 and by2[5]["quantity_source"] == P.QTY_DERIVED)
    check("rate_level=low 写入被打标任务", by2[1].get("rate_level") == "low" and by2[5].get("rate_level") == "low")
    solo = [{"id": 9, "name": "隔墙龙骨", "outline_level": 4, "duration_days": 5}]
    check("单类 quantity_override 旧签名仍可用 (500 measured)",
          P.tag_legacy_pilot_tasks(solo, 1000, activity_types=("partition_framing",), quantity_override=500) == [9]
          and solo[0]["quantity"] == 500.0 and solo[0]["quantity_source"] == P.QTY_MEASURED)


def test_pipeline_all_four_and_gates():
    print("\n== 5. 全流水线：四类同时打标 → 4 个公式节点；其余节点不变；SKILL.md 验证门 ==")
    mode = "MNC_Standard_Fitout_DBB_Invite"
    off = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", pilot=False)
    on = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", pilot=True, activities="all")
    rows = P.productivity_summary(on["tasks"])
    by_type = {r["activity_type"]: r for r in rows}
    check("恰好 4 个公式节点，四类各一", len(rows) == 4 and set(by_type) == set(ALL_TYPES), f"{len(rows)} {sorted(by_type)}")
    exp = {  # (quantity, calculated, final) at typical rate, default crew, derived quantities
        "partition_framing": (900.0, 10.0, 10),
        "suspended_ceiling": (1275.0, 21.25, 22),
        "painting": (2700.0, 19.2857, 20),
        "flooring": (1350.0, 10.8, 11),
    }
    for atype, (q, calc, fin) in exp.items():
        r = by_type.get(atype, {})
        check(f"[{atype}] quantity={q:g} derived, calculated≈{calc}, final={fin}d",
              r.get("quantity") == q and r.get("quantity_source") == P.QTY_DERIVED
              and abs(r.get("calculated_duration", -1) - calc) < 1e-3 and r.get("final_duration") == fin,
              f"{r.get('quantity')} {r.get('calculated_duration')} {r.get('final_duration')}")
        check(f"[{atype}] confidence=low (推导量 + 默认班组)", r.get("confidence") == "low", r.get("confidence"))
        check(f"[{atype}] 走施工 7 天日历", next(t for t in on["tasks"] if t["id"] == r["id"]).get("use_construction_cal") is True)
    check("painting 桥接系数 scope=with_ceiling_board 可见", by_type["painting"]["factor_labels"].get("scope") == "with_ceiling_board")

    off_by = {t["id"]: t for t in off["tasks"]}
    diffs = [(t["id"], t["name"]) for t in on["tasks"]
             if t.get("duration_method") != P.METHOD_FORMULA and t.get("duration") != off_by[t["id"]].get("duration")]
    check("非公式节点工期与旧路径完全一致", not diffs, f"{diffs[:5]}")
    check("节点总数不变", len(on["tasks"]) == len(off["tasks"]))
    check("项目终点后移（四类合计工期 63d vs 模板 38d）", on["finish"] > off["finish"], f"{off['finish']} → {on['finish']}")

    # ---- SKILL.md verification gate ----
    leaves = [t for t in on["tasks"] if t.get("outline_level", t.get("level", 1)) >= 3]
    check("Gate1 无空 Start/Finish", all(t.get("start") and t.get("finish") for t in on["tasks"]))
    check("Gate2 compliance 0 error", not any(i["level"] == "error" for i in on["issues"]), f"{on['issues']}")
    names = [t["name"] for t in leaves]
    i_first = next((i for i, n in enumerate(names) if "盲测" in n), -1)
    i_second = next((i for i, n in enumerate(names) if "复测" in n), -1)
    i_furn = next((i for i, n in enumerate(names) if "家具" in n and i > i_first), -1)
    check("Gate3 IAQ 链：首次盲测 → 家具 → 二次复测", 0 <= i_first < i_furn < i_second, f"{i_first},{i_furn},{i_second}")
    check("Gate5 非免办 → 许可里程碑存在", (not on["permit"].get("is_exempt")) and any("施工许可" in n for n in names))
    check("Gate7 关键路径非空", any(t.get("critical") for t in on["tasks"]))

    # 实测工程量 + 选档 low：四类全部变长或不变，终点不早于 typical
    low = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", pilot=True, activities="all", rate_level="low")
    low_by = {r["activity_type"]: r for r in P.productivity_summary(low["tasks"])}
    check("rate_level=low → 每类 final >= typical，且 rate_level_source=task",
          all(low_by[a]["final_duration"] >= by_type[a]["final_duration"] and low_by[a]["rate_level_source"] == "task" for a in ALL_TYPES),
          {a: (low_by[a]["final_duration"], by_type[a]["final_duration"]) for a in ALL_TYPES})
    check("rate_level=low → 终点不早于 typical", low["finish"] >= on["finish"], f"{on['finish']} vs {low['finish']}")
    meas = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", pilot=True, activities="all",
                         quantities={"partition_framing": 1200, "flooring": 1000})
    m_by = {r["activity_type"]: r for r in P.productivity_summary(meas["tasks"])}
    check("--quantities partition=1200 measured → 1200/90=13.33→14d; flooring=1000 measured → 8d; 其余仍 derived",
          m_by["partition_framing"]["quantity"] == 1200.0 and m_by["partition_framing"]["quantity_source"] == P.QTY_MEASURED
          and m_by["partition_framing"]["final_duration"] == 14
          and m_by["flooring"]["final_duration"] == 8 and m_by["flooring"]["quantity_source"] == P.QTY_MEASURED
          and m_by["painting"]["quantity_source"] == P.QTY_DERIVED and m_by["suspended_ceiling"]["quantity_source"] == P.QTY_DERIVED,
          {a: (m_by[a]["quantity"], m_by[a]["final_duration"]) for a in ALL_TYPES})


def test_legacy_pilot_unchanged():
    print("\n== 6. 旧试点（仅吊顶）数值与 PR #3 一致；四套模板默认路径不变 ==")
    mode = "MNC_Standard_Fitout_DBB_Invite"
    on = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", pilot=True)
    rows = P.productivity_summary(on["tasks"])
    check("默认 activity_types 仍只打标吊顶 1 个节点", len(rows) == 1 and rows[0]["activity_type"] == "suspended_ceiling")
    check("1275㎡ / (10×6) = 21.25 → 22d, confidence=low（与 PR #3 一致）",
          rows and rows[0]["final_duration"] == 22 and rows[0]["confidence"] == "low")
    for m, body in _templates().items():
        after = P.apply_productivity_durations(copy.deepcopy(body["tasks"]))
        check(f"[{m}] 试点关闭 → 无节点被打上 productivity", not any("productivity" in t for t in after))


if __name__ == "__main__":
    test_rate_library_levels()
    test_partition_framing()
    test_flooring()
    test_painting()
    test_rate_level_selection_and_config_only()
    test_tagging_all_types_and_bridge_factors()
    test_pipeline_all_four_and_gates()
    test_legacy_pilot_unchanged()
    print(f"\n==== 结果: PASS={PASS}  FAIL={FAIL} ====")
    sys.exit(1 if FAIL else 0)

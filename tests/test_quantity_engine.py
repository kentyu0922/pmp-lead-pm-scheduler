# -*- coding: utf-8 -*-
"""
test_quantity_engine.py — Quantity Engine v0 (benchmark quantities without a BOQ)
运行: python tests/test_quantity_engine.py   （无需 MS Project / COM；不 import main）

证明四件事：
  (1) 基准库单源 config/quantity_benchmarks.json 完整、可加载、参数合理
  (2) 固定用例 1500㎡ 甲级(Grade A) → ceiling/partition/flooring/paint 期望值与区间；确定性；线性；等级/形态方向正确
  (3) 生产率路径钩子：实测 quantity 优先 → 引擎推导 (quantity_key) → 旧桥接比例；未命中不抛错
  (4) 旧模板共存：引擎单独运行不改任何工期；全流水线 Grade A 与 PR #3 试点结果逐字段一致；SKILL 验证门不回归
"""
import sys
import os
import json
import copy

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import quantity_engine as Q
from core import productivity as P
from core.solver_engine import solve_schedule, compute_cpm_metrics
from core import compliance as C
from core import holidays as H
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


def raises(fn, exc=ValueError):
    try:
        fn()
        return False
    except exc:
        return True


def _templates():
    with open(os.path.join(BASE, "templates", "wbs_templates.json"), encoding="utf-8") as f:
        return json.load(f)["templates"]


def _run_pipeline(mode, area, cost, city, start, pilot=False, ceiling_area=None, grade=None, layout=None, engine=False):
    """复刻 main.py 正排流水线（不含导出）：calibrate → [engine] → [pilot tag] → apply → fold → renumber → solve → cpm → compliance"""
    tasks = copy.deepcopy(_templates()[mode]["tasks"])
    base_area = _templates()[mode].get("base_area", 1000)
    permit = query_city_permit_rule(city, area_sqm=area, cost_10k_rmb=cost)
    tasks = calibrate_durations(tasks, permit, area, base_area, "", cost_10k_rmb=cost)
    derived = Q.derive_quantities(area, grade=grade, layout=layout) if (engine or pilot) else None
    tagged = []
    if pilot:
        tagged = P.tag_legacy_pilot_tasks(tasks, area, quantity_override=ceiling_area, derived_quantities=derived)
    tasks = P.apply_productivity_durations(tasks, derived_quantities=derived)
    if permit.get("is_exempt"):
        tasks = fold_exempt_construction_permit(tasks, True)
    tasks = renumber_tasks_contiguously(tasks)
    res = solve_schedule(tasks, start, custom_holidays=H.load_holiday_pairs())
    solved = compute_cpm_metrics(res["tasks"], project_end=res["finish_date"])
    issues = C.run_compliance_checks(solved, holiday_raw=H.load_holiday_raw())
    return {"tasks": solved, "finish": res["finish_date"], "issues": issues, "tagged": tagged, "permit": permit, "derived": derived}


# ---------------------------------------------------------------------------
def test_benchmark_library_single_source():
    print("== 1. 基准库单源 (config/quantity_benchmarks.json) ==")
    b = Q.load_quantity_benchmarks()
    check("含 A/B/C 三个等级", set(b["grades"]) == {"A", "B", "C"}, sorted(b["grades"]))
    for g, body in b["grades"].items():
        p = body["params"]
        check(f"[{g}] 八个参数齐全且有假设说明",
              all(k in p for k in Q._REQUIRED_PARAMS) and len(body.get("assumptions", [])) >= 1,
              f"missing={[k for k in Q._REQUIRED_PARAMS if k not in p]}")
        check(f"[{g}] 比例类参数在 [0,1]，其余 > 0",
              all(0 <= p[k] <= 1 for k in Q._FRACTION_PARAMS) and all(p[k] > 0 for k in p if k not in Q._FRACTION_PARAMS))
    check("layouts 含 open_plan/standard/cellular 且 standard 乘数=1.0",
          set(b["layouts"]) == {"open_plan", "standard", "cellular"} and b["layouts"]["standard"]["partition_density_multiplier"] == 1.0)
    check("quantities 声明与引擎输出键一致", set(b["quantities"]) == set(Q.QUANTITY_KEYS), f"{set(b['quantities']) ^ set(Q.QUANTITY_KEYS)}")
    check("每个工程量都有合理性区间 (sanity band)", all(k in b["sanity_ranges_per_gross_m2"] for k in Q.QUANTITY_KEYS))
    check("每个参数都有单位/说明文档", all(k in b["parameters"] for k in Q._REQUIRED_PARAMS))
    check("甲级净顶面积比 = 旧桥接比例 0.85 (与 PR #3 试点一致)",
          b["grades"]["A"]["params"]["net_ceiling_ratio"] == 0.85
          and P.load_productivity_rates()["activity_types"]["suspended_ceiling"]["legacy_template_bridge"]["quantity_from_area_ratio"] == 0.85)
    check("quantity_source 沿用 derived_from_area，confidence=low", b["quantity_source"] == P.QTY_DERIVED and b["confidence"] == "low")

    # 缺参数必须 fail loudly
    bad = copy.deepcopy(b)
    del bad["grades"]["A"]["params"]["net_ceiling_ratio"]
    tmp = os.path.join(BASE, "output_mpp", "_bad_benchmarks.json")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(bad, f)
    try:
        check("缺参数的基准库 → ValueError (不静默兜底)", raises(lambda: Q.load_quantity_benchmarks(tmp)))
    finally:
        os.remove(tmp)


def test_fixture_1500_grade_a():
    print("\n== 2(a). 固定用例：1500㎡ 甲级 (Grade A) standard ==")
    r = Q.derive_quantities(1500, "A")
    v = Q.quantity_values(r)
    exp = {
        "ceiling_area": 1275.0,           # 1500 × 0.85
        "flooring_area": 1380.0,          # 1500 × 0.92
        "partition_length": 450.0,        # 1500 × 0.30 × 1.0
        "partition_area": 1575.0,         # 450 × 3.5
        "drywall_partition_area": 1023.8, # 1575 × 0.65 = 1023.75
        "glass_partition_area": 551.2,    # 1575 × 0.35 = 551.25
        "paint_area": 2569.1,             # 1023.75×2×0.85 + 1500×0.10×3.5×0.85 + 1275×0.30 = 1740.375+446.25+382.5
    }
    for k, e in exp.items():
        check(f"{k} = {e:g}", v.get(k) == e, f"got {v.get(k)}")
    comp = r["quantities"]["paint_area"]["components"]
    check("paint_area 分项 = 墙 1740.4 + 核心筒墙 446.2 + 顶 382.5",
          comp == {"wall_paint_area": 1740.4, "core_wall_paint_area": 446.2, "ceiling_paint_area": 382.5}, comp)

    # 区间型断言（防止基准微调时测试过脆）
    check("ceiling_area 在 [1200, 1350] (0.80–0.90×gross)", 1200 <= v["ceiling_area"] <= 1350)
    check("flooring_area 在 [1300, 1450]", 1300 <= v["flooring_area"] <= 1450)
    check("partition_length 在 [300, 600] m (0.2–0.4 m/㎡)", 300 <= v["partition_length"] <= 600)
    check("paint_area 在 [2000, 3500] ㎡ (1.3–2.3×gross)", 2000 <= v["paint_area"] <= 3500)
    check("全部工程量落在基准合理区间内，无 warning",
          all(q["within_sanity_band"] for q in r["quantities"].values()) and r["warnings"] == [], r["warnings"])

    # 可解释性
    check("method=benchmark_v0, quantity_source=derived_from_area, confidence=low",
          r["method"] == Q.METHOD_BENCHMARK and r["quantity_source"] == P.QTY_DERIVED and r["confidence"] == "low")
    row = r["quantities"]["ceiling_area"]
    check("每个工程量携带 value/unit/formula/quantity_source/confidence/per_gross_m2/sanity band",
          all(k in row for k in ("value", "unit", "formula", "quantity_source", "confidence", "per_gross_m2",
                                 "sanity_band_per_gross_m2", "within_sanity_band")), sorted(row))
    check("formula 含代入数值 (1500 × net_ceiling_ratio 0.85)", "1500" in row["formula"] and "0.85" in row["formula"], row["formula"])
    check("单位: 面积 m2，隔墙长度 m",
          row["unit"] == "m2" and r["quantities"]["partition_length"]["unit"] == "m")
    check("输出记录 inputs(area/grade/layout/overrides) + parameters + assumptions(非空)",
          r["inputs"] == {"area_sqm": 1500.0, "grade": "A", "layout": "standard", "overrides": {}}
          and len(r["parameters"]) >= 8 and len(r["assumptions"]) >= 1)
    check("结果可 JSON 序列化 (落盘 sidecar)", json.dumps(r, ensure_ascii=False) is not None)


def test_determinism_linearity_and_direction():
    print("\n== 2(b). 确定性 / 线性 / 等级与形态方向 ==")
    a1 = Q.derive_quantities(1500, "A")
    a2 = Q.derive_quantities(1500, "A")
    check("同输入两次调用完全相同 (确定性，无随机/LLM)", a1 == a2)
    v15 = Q.quantity_values(a1)
    v30 = Q.quantity_values(Q.derive_quantities(3000, "A"))
    check("3000㎡ = 2 × 1500㎡ 逐项线性", all(abs(v30[k] - 2 * v15[k]) <= 0.15 for k in Q.QUANTITY_KEYS),
          {k: (v15[k], v30[k]) for k in Q.QUANTITY_KEYS})

    A = Q.quantity_values(Q.derive_quantities(1500, "A"))
    B = Q.quantity_values(Q.derive_quantities(1500, "B"))
    Cq = Q.quantity_values(Q.derive_quantities(1500, "C"))
    check("等级越低隔墙越密: partition_length C > B > A", Cq["partition_length"] > B["partition_length"] > A["partition_length"])
    check("等级越高玻璃隔断越多: glass_partition_area A > B > C", A["glass_partition_area"] > B["glass_partition_area"] > Cq["glass_partition_area"])
    check("油漆面积 C > B > A (更多石膏板隔墙、更少玻璃)", Cq["paint_area"] > B["paint_area"] > A["paint_area"])
    check("丙级净顶比更低: ceiling_area C < A", Cq["ceiling_area"] < A["ceiling_area"])
    check("地面面积各等级一致 (0.92)", A["flooring_area"] == B["flooring_area"] == Cq["flooring_area"] == 1380.0)
    for g in ("A", "B", "C"):
        for lay in ("open_plan", "standard", "cellular"):
            rr = Q.derive_quantities(1500, g, lay)
            check(f"[{g}/{lay}] 全部落在合理区间", not rr["warnings"], rr["warnings"])

    op = Q.quantity_values(Q.derive_quantities(1500, "A", "open_plan"))
    ce = Q.quantity_values(Q.derive_quantities(1500, "A", "cellular"))
    check("open_plan 隔墙长度 = 0.8×standard (360m)", op["partition_length"] == 360.0, op["partition_length"])
    check("cellular 隔墙长度 = 1.3×standard (585m)", ce["partition_length"] == 585.0, ce["partition_length"])
    check("形态不影响 ceiling/flooring", op["ceiling_area"] == ce["ceiling_area"] == 1275.0 and op["flooring_area"] == ce["flooring_area"] == 1380.0)


def test_inputs_aliases_overrides_and_errors():
    print("\n== 2(c). 输入规范化 / 覆盖 / 错误必须 fail loudly ==")
    check("等级别名: '甲级' / 'Grade A' / 'grade_b' / 'c' / None",
          Q.normalize_grade("甲级") == "A" and Q.normalize_grade("Grade A") == "A" and Q.normalize_grade("grade_b") == "B"
          and Q.normalize_grade("c") == "C" and Q.normalize_grade(None) == "A")
    check("形态别名: 'Open Plan' → open_plan; None → standard",
          Q.normalize_layout("Open Plan") == "open_plan" and Q.normalize_layout(None) == "standard")

    r = Q.derive_quantities(1500, "A", overrides={"partition_height_m": 3.0})
    check("覆盖 partition_height_m=3.0 → partition_area 450×3.0 = 1350", Q.quantity_values(r)["partition_area"] == 1350.0)
    check("覆盖被记录进 inputs.overrides 与 assumptions",
          r["inputs"]["overrides"] == {"partition_height_m": 3.0} and any("override" in s for s in r["assumptions"]))

    r2 = Q.derive_quantities(1500, "A", overrides={"partition_density_m_per_m2": 1.0})
    check("越界推导 (1.0 m/㎡ 隔墙) → within_sanity_band=False 且 warnings 非空 (不静默)",
          r2["quantities"]["partition_length"]["within_sanity_band"] is False and len(r2["warnings"]) >= 1, r2["warnings"])

    check("area<=0 → ValueError", raises(lambda: Q.derive_quantities(0, "A")))
    check("area 非数值 → ValueError", raises(lambda: Q.derive_quantities("abc", "A")))
    check("未知等级 → ValueError", raises(lambda: Q.derive_quantities(1500, "Z")))
    check("未知形态 → ValueError", raises(lambda: Q.derive_quantities(1500, "A", "warehouse")))
    check("未知覆盖参数 → ValueError", raises(lambda: Q.derive_quantities(1500, "A", overrides={"magic": 1})))
    check("比例覆盖 >1 → ValueError", raises(lambda: Q.derive_quantities(1500, "A", overrides={"net_ceiling_ratio": 1.2})))
    check("高度覆盖 <=0 → ValueError", raises(lambda: Q.derive_quantities(1500, "A", overrides={"partition_height_m": 0})))
    check("as_quantity_map 接受引擎结果 / 扁平映射 / None",
          Q.as_quantity_map(Q.derive_quantities(1500, "A"))["ceiling_area"] == 1275.0
          and Q.as_quantity_map({"ceiling_area": 900}) == {"ceiling_area": 900.0} and Q.as_quantity_map(None) == {})


def test_productivity_hook():
    print("\n== 3. 生产率路径钩子：实测 → 引擎 quantity_key → 旧桥接比例 ==")
    rates = P.load_productivity_rates()
    check("rate 库中凡声明 quantity_key 者，引擎必能产出该键 (配置一致性)",
          all(e["quantity_key"] in Q.QUANTITY_KEYS for e in rates["activity_types"].values() if "quantity_key" in e),
          {k: e.get("quantity_key") for k, e in rates["activity_types"].items()})
    check("suspended_ceiling.quantity_key = ceiling_area", rates["activity_types"]["suspended_ceiling"]["quantity_key"] == "ceiling_area")

    derived = Q.derive_quantities(1500, "A")
    tasks = [
        {"id": 1, "name": "隔墙龙骨", "level": 3, "duration_days": 14, "duration": 14, "predecessors": ""},
        {"id": 2, "name": "吊顶(无BOQ)", "level": 3, "duration_days": 10, "duration": 10, "predecessors": "1",
         "activity_type": "suspended_ceiling", "crew_size": 6},
        {"id": 3, "name": "吊顶(实测BOQ)", "level": 3, "duration_days": 10, "duration": 10, "predecessors": "2",
         "activity_type": "suspended_ceiling", "quantity": 900, "crew_size": 6},
        {"id": 4, "name": "未知类型", "level": 3, "duration_days": 5, "duration": 5, "predecessors": "3",
         "activity_type": "brickwork"},
    ]
    P.apply_productivity_durations(copy.deepcopy(tasks))  # 无引擎输出 → 与 PR #3 行为一致
    P.apply_productivity_durations(tasks, derived_quantities=derived)
    by = {t["id"]: t for t in tasks}
    check("无 BOQ 节点由引擎补量 quantity=1275 (ceiling_area), source=derived_from_area, key=ceiling_area",
          by[2]["quantity"] == 1275.0 and by[2]["quantity_source"] == P.QTY_DERIVED and by[2]["quantity_key"] == "ceiling_area")
    check("补量后走公式：1275/(10×6)=21.25 → 22d，confidence=low (推导量降级)",
          by[2]["duration"] == 22 and by[2]["productivity"]["confidence"] == "low"
          and by[2]["productivity"]["quantity_key"] == "ceiling_area", by[2].get("productivity", {}).get("final_duration"))
    check("实测 BOQ 节点不被引擎覆盖: quantity=900 measured → 15d confidence=medium",
          by[3]["quantity"] == 900 and by[3]["productivity"]["quantity_source"] == P.QTY_MEASURED
          and by[3]["duration"] == 15 and by[3]["productivity"]["confidence"] == "medium"
          and "quantity_key" not in by[3]["productivity"])
    check("未知类型无 quantity_key → 不补量、保留模板 5d、不抛错", by[4]["duration"] == 5 and "quantity" not in by[4])
    check("无 activity_type 的模板节点完全不动", by[1]["duration"] == 14 and "productivity" not in by[1])

    only_flat = [{"id": 9, "name": "吊顶", "level": 3, "duration_days": 10, "predecessors": "",
                  "activity_type": "suspended_ceiling", "crew_size": 6}]
    P.apply_productivity_durations(only_flat, derived_quantities={"ceiling_area": 600})
    check("钩子亦接受扁平 {name: value} 映射: 600/60=10 → 10d", only_flat[0]["duration"] == 10 and only_flat[0]["quantity"] == 600.0)

    miss = [{"id": 8, "name": "吊顶", "level": 3, "duration_days": 10, "predecessors": "",
             "activity_type": "suspended_ceiling", "crew_size": 6}]
    P.apply_productivity_durations(miss, derived_quantities={"paint_area": 2569.1})
    check("引擎输出缺 ceiling_area → 保留模板 10d，不抛错", miss[0]["duration_days"] == 10 and "quantity" not in miss[0])

    # tag_legacy_pilot_tasks 三级优先级
    def _legacy():
        return [{"id": 3, "name": "墙面封板与天花吊顶龙骨安装", "outline_level": 4, "duration_days": 14, "predecessors": ""}]
    t_ratio = _legacy(); P.tag_legacy_pilot_tasks(t_ratio, 1000)
    t_engine = _legacy(); P.tag_legacy_pilot_tasks(t_engine, 1000, derived_quantities=Q.derive_quantities(1000, "C"))
    t_meas = _legacy(); P.tag_legacy_pilot_tasks(t_meas, 1000, quantity_override=777, derived_quantities=Q.derive_quantities(1000, "C"))
    check("桥接无引擎 → 旧比例 1000×0.85=850 derived", t_ratio[0]["quantity"] == 850.0 and t_ratio[0]["quantity_source"] == P.QTY_DERIVED and "quantity_key" not in t_ratio[0])
    check("桥接+引擎(丙级) → 引擎 1000×0.80=800 derived, key=ceiling_area",
          t_engine[0]["quantity"] == 800.0 and t_engine[0]["quantity_source"] == P.QTY_DERIVED and t_engine[0]["quantity_key"] == "ceiling_area")
    check("桥接+引擎+实测 → 实测 777 measured 优先", t_meas[0]["quantity"] == 777.0 and t_meas[0]["quantity_source"] == P.QTY_MEASURED)
    check("引擎甲级 == 旧比例 (1275 vs 1275)：默认等级下 PR #3 结果不变",
          Q.quantity_values(Q.derive_quantities(1500, "A"))["ceiling_area"] == round(1500 * 0.85, 1))


def test_legacy_templates_untouched_by_engine():
    print("\n== 4(a). 旧硬编码模板：引擎输出传入 apply 后四套模板逐节点工期不变 ==")
    derived = Q.derive_quantities(1500, "A")
    for mode, body in _templates().items():
        before = copy.deepcopy(body["tasks"])
        after = P.apply_productivity_durations(copy.deepcopy(body["tasks"]), derived_quantities=derived)
        same = len(before) == len(after) and all(a.get("duration_days") == b.get("duration_days") for a, b in zip(before, after))
        check(f"[{mode}] {len(before)} 节点工期逐一不变，无 quantity/productivity 键",
              same and not any(("quantity" in t) or ("productivity" in t) for t in after))
    check("模板 JSON 未被改写 (无 activity_type / quantity)",
          not any(("activity_type" in t) or ("quantity" in t) for body in _templates().values() for t in body["tasks"]))


def test_pipeline_coexistence_and_gates():
    print("\n== 4(b). 全流水线：引擎单独运行不改工期；引擎+试点 Grade A == PR #3；Grade C 不同；SKILL 验证门 ==")
    mode = "MNC_Standard_Fitout_DBB_Invite"
    sig = lambda ts: [(t["id"], t.get("duration"), t.get("start"), t.get("finish")) for t in ts]
    off = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28")
    eng_only = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", engine=True, grade="C", layout="cellular")
    check("--derive_quantities 单独开启 → 与旧路径逐任务一致 (只产数字，不改工期)", sig(eng_only["tasks"]) == sig(off["tasks"]))
    check("单独开启时引擎确有输出 (7 项工程量)", eng_only["derived"] and len(eng_only["derived"]["quantities"]) == 7)

    pr3 = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", pilot=True)          # 引擎默认 grade A
    rows = P.productivity_summary(pr3["tasks"])
    r = rows[0] if rows else {}
    check("试点+引擎(默认甲级): quantity=1275 derived via ceiling_area → 21.25 → 22d (与 PR #3 一致)",
          len(rows) == 1 and r.get("quantity") == 1275.0 and r.get("quantity_key") == "ceiling_area"
          and r.get("calculated_duration") == 21.25 and r.get("final_duration") == 22, f"{r.get('quantity')} {r.get('final_duration')}")
    check("试点+引擎 项目终点 2027-05-18 (PR #3 记录值)", pr3["finish"] == "2027-05-18", pr3["finish"])
    off_by = {t["id"]: t for t in off["tasks"]}
    diffs = [(t["id"], t["name"]) for t in pr3["tasks"]
             if t.get("duration_method") != P.METHOD_FORMULA and t.get("duration") != off_by[t["id"]].get("duration")]
    check("非公式节点工期与旧路径完全一致", not diffs, diffs[:5])

    grc = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", pilot=True, grade="C")
    rc = P.productivity_summary(grc["tasks"])[0]
    check("试点+引擎(丙级): quantity=1500×0.80=1200 → 20d", rc["quantity"] == 1200.0 and rc["final_duration"] == 20, f"{rc['quantity']} {rc['final_duration']}")

    meas = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", pilot=True, ceiling_area=900, grade="C")
    rm = P.productivity_summary(meas["tasks"])[0]
    check("试点+引擎+--ceiling_area 900 → 实测优先 900 measured → 15d", rm["quantity"] == 900.0 and rm["quantity_source"] == P.QTY_MEASURED and rm["final_duration"] == 15)

    for label, run in (("引擎单独", eng_only), ("引擎+试点A", pr3), ("引擎+试点C", grc)):
        leaves = [t for t in run["tasks"] if t.get("outline_level", t.get("level", 1)) >= 3]
        names = [t["name"] for t in leaves]
        i_first = next((i for i, n in enumerate(names) if "盲测" in n), -1)
        i_second = next((i for i, n in enumerate(names) if "复测" in n), -1)
        i_furn = next((i for i, n in enumerate(names) if "家具" in n and i > i_first), -1)
        check(f"[{label}] Gate1 无空 Start/Finish", all(t.get("start") and t.get("finish") for t in run["tasks"]))
        check(f"[{label}] Gate2 compliance 0 error", not any(i["level"] == "error" for i in run["issues"]), run["issues"])
        check(f"[{label}] Gate3 IAQ 链 盲测→家具→复测", 0 <= i_first < i_furn < i_second)
        check(f"[{label}] Gate7 关键路径非空", any(t.get("critical") for t in run["tasks"]))


if __name__ == "__main__":
    test_benchmark_library_single_source()
    test_fixture_1500_grade_a()
    test_determinism_linearity_and_direction()
    test_inputs_aliases_overrides_and_errors()
    test_productivity_hook()
    test_legacy_templates_untouched_by_engine()
    test_pipeline_coexistence_and_gates()
    print(f"\n==== 结果: PASS={PASS}  FAIL={FAIL} ====")
    sys.exit(1 if FAIL else 0)

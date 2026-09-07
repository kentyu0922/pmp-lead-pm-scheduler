# -*- coding: utf-8 -*-
"""
test_productivity_pilot.py — quantity → productivity → duration pilot (suspended_ceiling)
运行: python tests/test_productivity_pilot.py   （无需 MS Project / COM；不 import main）

证明两件事：
  (a) 公式路径：固定用例 suspended_ceiling 得到期望工期 + 可解释字段齐全
  (b) 旧路径共存：无 activity_type 的模板节点工期逐一不变；开启试点仅吊顶节点改变，
      SKILL.md 验证门（无空日期 / 合规 0 error / IAQ 链 / 关键路径非空）不回归
"""
import sys
import os
import json
import copy

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


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def _templates():
    with open(os.path.join(BASE, "templates", "wbs_templates.json"), encoding="utf-8") as f:
        return json.load(f)["templates"]


def _run_pipeline(mode, area, cost, city, start, pilot=False, ceiling_area=None):
    """复刻 main.py 正排流水线（不含导出）：calibrate → [pilot tag] → apply → fold → renumber → solve → cpm → compliance"""
    tasks = copy.deepcopy(_templates()[mode]["tasks"])
    base_area = _templates()[mode].get("base_area", 1000)
    permit = query_city_permit_rule(city, area_sqm=area, cost_10k_rmb=cost)
    tasks = calibrate_durations(tasks, permit, area, base_area, "", cost_10k_rmb=cost)
    tagged = []
    if pilot:
        tagged = P.tag_legacy_pilot_tasks(tasks, area, quantity_override=ceiling_area)
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
def test_rate_library_single_source():
    print("== 1. 生产率库单源 (config/productivity_rates.json) ==")
    rates = P.load_productivity_rates()
    check("含 suspended_ceiling", "suspended_ceiling" in rates["activity_types"])
    e = rates["activity_types"]["suspended_ceiling"]
    check("rate/crew/min/unit 字段齐全",
          all(k in e for k in ("rate_per_worker_day", "default_crew_size", "min_duration_days", "unit", "factors")))
    check("试点仅一个活动类型（不越界）", len(rates["activity_types"]) == 1, f"{list(rates['activity_types'])}")


def test_formula_fixture():
    print("\n== 2(a). 公式路径固定用例：1200㎡ / 10㎡·人日 / 6 人 / complex 1.2 → 24d ==")
    r = P.compute_activity_duration("suspended_ceiling", 1200, crew_size=6, factors={"complexity": "complex"})
    check("daily_output = 10×6 = 60", r["daily_output"] == 60.0, r["daily_output"])
    check("base_duration = 1200/60 = 20", r["base_duration"] == 20.0, r["base_duration"])
    check("factor_product = 1.2 (complex×access默认1.0)", r["factor_product"] == 1.2, r["factor_product"])
    check("calculated_duration = 24.0", r["calculated_duration"] == 24.0, r["calculated_duration"])
    check("final_duration = 24 (整数工日)", r["final_duration"] == 24 and isinstance(r["final_duration"], int), r["final_duration"])
    check("confidence = medium (实测量+显式班组，无降级)", r["confidence"] == "medium", r["confidence"])
    required = ["quantity", "unit", "productivity_rate", "crew_size", "factors",
                "calculated_duration", "final_duration", "confidence", "confidence_reasons",
                "quantity_source", "factor_labels", "rates_version", "method"]
    check("可解释字段齐全", all(k in r for k in required), f"missing={[k for k in required if k not in r]}")
    check("unit=m2, rate=10, crew=6, method=productivity_formula",
          r["unit"] == "m2" and r["productivity_rate"] == 10.0 and r["crew_size"] == 6 and r["method"] == P.METHOD_FORMULA)

    # 取整：1000/60 = 16.67 → 17；默认班组 → 置信度降一级
    r2 = P.compute_activity_duration("suspended_ceiling", 1000)
    check("1000㎡ 默认班组 → ceil(16.67)=17", r2["final_duration"] == 17, r2["final_duration"])
    check("默认班组 → confidence 降为 low", r2["confidence"] == "low" and r2["crew_source"] == "default", r2["confidence"])

    # 下限：100㎡/60 = 1.67 → 2 → floor min 3
    r3 = P.compute_activity_duration("suspended_ceiling", 100, crew_size=6)
    check("100㎡ 触发 min_duration_days=3 下限", r3["final_duration"] == 3, r3["final_duration"])

    # 推导量降级
    r4 = P.compute_activity_duration("suspended_ceiling", 1200, crew_size=6, quantity_source=P.QTY_DERIVED)
    check("推导工程量 → confidence 降为 low 且有原因说明",
          r4["confidence"] == "low" and any("derived" in s for s in r4["confidence_reasons"]), r4["confidence_reasons"])

    # 数值型自定义系数 + 访问系数
    r5 = P.compute_activity_duration("suspended_ceiling", 1200, crew_size=6,
                                     factors={"complexity": "complex", "access": "high_ceiling"})
    check("complex×high_ceiling = 1.2×1.3 = 1.56 → 20×1.56=31.2 → 32d",
          abs(r5["factor_product"] - 1.56) < 1e-9 and r5["final_duration"] == 32, f"{r5['factor_product']} {r5['final_duration']}")

    # 错误输入必须 fail loudly
    def raises(fn):
        try:
            fn()
            return False
        except ValueError:
            return True
    check("未知 activity_type → ValueError", raises(lambda: P.compute_activity_duration("brickwork", 10)))
    check("未知系数键 → ValueError", raises(lambda: P.compute_activity_duration("suspended_ceiling", 10, factors={"complexity": "weird"})))
    check("quantity<=0 → ValueError", raises(lambda: P.compute_activity_duration("suspended_ceiling", 0)))
    check("crew_size<1 → ValueError", raises(lambda: P.compute_activity_duration("suspended_ceiling", 10, crew_size=0)))


def test_apply_switch_mixed_list():
    print("\n== 2(a'). activity_type 开关：同一任务表中公式节点与模板节点共存 ==")
    tasks = [
        {"id": 1, "name": "隔墙龙骨", "level": 3, "duration_days": 14, "duration": 14, "predecessors": ""},
        {"id": 2, "name": "吊顶", "level": 3, "duration_days": 14, "duration": 14, "predecessors": "1",
         "activity_type": "suspended_ceiling", "quantity": 1200, "crew_size": 6, "factors": {"complexity": "complex"}},
        {"id": 3, "name": "未知类型", "level": 3, "duration_days": 5, "duration": 5, "predecessors": "2",
         "activity_type": "brickwork", "quantity": 50},
        {"id": 4, "name": "缺工程量", "level": 3, "duration_days": 6, "duration": 6, "predecessors": "3",
         "activity_type": "suspended_ceiling"},
        {"id": 5, "name": "坏系数", "level": 3, "duration_days": 7, "duration": 7, "predecessors": "4",
         "activity_type": "suspended_ceiling", "quantity": 100, "factors": {"complexity": "weird"}},
    ]
    P.apply_productivity_durations(tasks)
    by = {t["id"]: t for t in tasks}
    check("公式节点 duration 14→24 且 duration_days 同步", by[2]["duration"] == 24 and by[2]["duration_days"] == 24)
    check("公式节点 duration_method=productivity_formula + template_duration=14",
          by[2].get("duration_method") == P.METHOD_FORMULA and by[2]["productivity"]["template_duration"] == 14)
    check("模板节点 duration 不变且无 productivity 键", by[1]["duration"] == 14 and "productivity" not in by[1] and "duration_method" not in by[1])
    check("未知 activity_type → 保留模板 5d（不抛错）", by[3]["duration"] == 5 and "productivity" not in by[3])
    check("缺 quantity → 保留模板 6d（不抛错）", by[4]["duration"] == 6 and "productivity" not in by[4])
    check("坏系数键 → 保留模板 7d（不抛错）", by[5]["duration"] == 7 and "productivity" not in by[5])

    # 求解器透明消费公式工期：与硬编码 24d 的排程逐日一致
    hard = copy.deepcopy(tasks)
    for t in hard:
        t.pop("productivity", None); t.pop("duration_method", None); t.pop("activity_type", None)
    a = solve_schedule(copy.deepcopy(tasks), "2026-06-01")["tasks"]
    b = solve_schedule(hard, "2026-06-01")["tasks"]
    check("solve_schedule: 公式路径 == 等值硬编码路径 (逐任务 start/finish)",
          [(t["start"], t["finish"]) for t in a] == [(t["start"], t["finish"]) for t in b])
    check("上游模板节点 #1 日期不受公式节点影响", a[0]["start"] == "2026-06-01" and a[0]["finish"] == b[0]["finish"])


def test_legacy_templates_untouched():
    print("\n== 2(b). 旧硬编码模板：四套模板经 apply_productivity_durations 后逐节点工期不变 ==")
    tpl = _templates()
    for mode, body in tpl.items():
        before = copy.deepcopy(body["tasks"])
        after = P.apply_productivity_durations(copy.deepcopy(body["tasks"]))
        same = all(a.get("duration_days") == b.get("duration_days") for a, b in zip(before, after)) and len(before) == len(after)
        check(f"[{mode}] {len(before)} 节点工期逐一不变", same)
        check(f"[{mode}] 无节点被打上 productivity/duration_method",
              not any("productivity" in t or "duration_method" in t for t in after))
    check("模板 JSON 本身无 activity_type（模板未被改写）",
          not any("activity_type" in t for body in tpl.values() for t in body["tasks"]))


def test_pipeline_flag_off_equals_legacy():
    print("\n== 2(b'). 全流水线：试点关闭 == v4.1 旧路径（逐任务 start/finish/duration） ==")
    mode = "MNC_Standard_Fitout_DBB_Invite"
    off = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", pilot=False)
    # 纯旧路径：不调用 productivity 模块
    tasks = copy.deepcopy(_templates()[mode]["tasks"])
    permit = off["permit"]
    tasks = calibrate_durations(tasks, permit, 1500, _templates()[mode].get("base_area", 1000), "", cost_10k_rmb=320)
    if permit.get("is_exempt"):
        tasks = fold_exempt_construction_permit(tasks, True)
    tasks = renumber_tasks_contiguously(tasks)
    legacy = solve_schedule(tasks, "2026-08-28", custom_holidays=H.load_holiday_pairs())["tasks"]
    sig = lambda ts: [(t["id"], t.get("duration"), t.get("start"), t.get("finish")) for t in ts]
    check("试点关闭 → 与纯旧路径逐任务一致", sig(off["tasks"]) == sig(legacy))
    check("试点关闭 → 无 productivity 节点", not P.productivity_summary(off["tasks"]))


def test_pipeline_pilot_coexists_and_gates():
    print("\n== 3. 全流水线：试点开启 → 仅吊顶节点改变；SKILL.md 验证门不回归 ==")
    mode = "MNC_Standard_Fitout_DBB_Invite"
    off = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", pilot=False)
    on = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", pilot=True)
    rows = P.productivity_summary(on["tasks"])
    check("恰有 1 个吊顶节点走公式路径", len(rows) == 1 and len(on["tagged"]) == 1, f"{len(rows)} {on['tagged']}")
    r = rows[0] if rows else {}
    check("命中节点名含『天花吊顶龙骨』", "天花吊顶龙骨" in str(r.get("name")), r.get("name"))
    check("quantity = 1500×0.85 = 1275㎡ (derived_from_area)",
          r.get("quantity") == 1275.0 and r.get("quantity_source") == P.QTY_DERIVED, f"{r.get('quantity')} {r.get('quantity_source')}")
    check("1275/(10×6)=21.25 → final 22d", r.get("calculated_duration") == 21.25 and r.get("final_duration") == 22,
          f"{r.get('calculated_duration')} {r.get('final_duration')}")
    check("confidence=low (推导量 + 默认班组 双降级)", r.get("confidence") == "low", r.get("confidence"))
    check("template_duration 记录校准后模板值 (10d)", r.get("template_duration") == 10, r.get("template_duration"))

    # 其余节点工期与旧路径逐一相同（按名称对齐；renumber 后 id 一致）
    off_by = {t["id"]: t for t in off["tasks"]}
    diffs = [(t["id"], t["name"]) for t in on["tasks"]
             if t.get("duration_method") != P.METHOD_FORMULA and t.get("duration") != off_by[t["id"]].get("duration")]
    check("非公式节点工期与旧路径完全一致", not diffs, f"{diffs[:5]}")
    check("节点总数不变", len(on["tasks"]) == len(off["tasks"]))
    check("项目终点因吊顶工期变化而后移（试点确有生效）", on["finish"] > off["finish"], f"{off['finish']} → {on['finish']}")

    # ---- SKILL.md verification gate ----
    leaves = [t for t in on["tasks"] if t.get("outline_level", t.get("level", 1)) >= 3]
    check("Gate1 无空 Start/Finish", all(t.get("start") and t.get("finish") for t in on["tasks"]))
    check("Gate2 compliance 0 error", not any(i["level"] == "error" for i in on["issues"]), f"{on['issues']}")
    names = [t["name"] for t in leaves]
    i_first = next((i for i, n in enumerate(names) if "盲测" in n), -1)
    i_second = next((i for i, n in enumerate(names) if "复测" in n), -1)
    i_furn = next((i for i, n in enumerate(names) if "家具" in n and i > i_first), -1)
    check("Gate3 IAQ 链：首次盲测 → 家具 → 二次复测", 0 <= i_first < i_furn < i_second, f"{i_first},{i_furn},{i_second}")
    check("Gate5 非免办 → 许可里程碑存在",
          (not on["permit"].get("is_exempt")) and any("施工许可" in n for n in names))
    ceiling = next(t for t in on["tasks"] if t.get("duration_method") == P.METHOD_FORMULA)
    check("Gate6 吊顶(公式)节点仍走施工7天日历", ceiling.get("use_construction_cal") is True)
    check("Gate7 关键路径非空", any(t.get("critical") for t in on["tasks"]))
    check("吊顶节点在关键路径上（信息可解释）", ceiling.get("critical") is True and "critical" in rows[0])

    # 实测工程量覆盖：quantity_source=measured，置信度只因默认班组降一级
    on2 = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", pilot=True, ceiling_area=900)
    r2 = P.productivity_summary(on2["tasks"])[0]
    check("--ceiling_area 900 → quantity=900 measured, 900/60=15 → 15d, confidence=low(仅班组默认)",
          r2["quantity"] == 900.0 and r2["quantity_source"] == P.QTY_MEASURED and r2["final_duration"] == 15
          and r2["confidence"] == "low", f"{r2['quantity']} {r2['final_duration']} {r2['confidence']}")


def test_tagging_never_touches_summaries_or_milestones():
    print("\n== 4. 试点打标只命中叶子实体任务 ==")
    tasks = [
        {"id": 1, "name": "Stage 2: 封板与天花吊顶龙骨", "outline_level": 2, "duration_days": 0, "predecessors": ""},
        {"id": 2, "name": "[M] 天花吊顶龙骨验收", "outline_level": 3, "duration_days": 0, "predecessors": "", "milestone": True},
        {"id": 3, "name": "墙面封板与天花吊顶龙骨安装", "outline_level": 4, "duration_days": 14, "predecessors": ""},
        {"id": 4, "name": "天花封石膏板", "outline_level": 4, "duration_days": 16, "predecessors": "3"},
    ]
    tagged = P.tag_legacy_pilot_tasks(tasks, 1000)
    check("仅 id=3 被打标", tagged == [3], tagged)
    check("汇总/里程碑/非关键词节点未打标", all("activity_type" not in t for t in tasks if t["id"] != 3))


if __name__ == "__main__":
    test_rate_library_single_source()
    test_formula_fixture()
    test_apply_switch_mixed_list()
    test_legacy_templates_untouched()
    test_pipeline_flag_off_equals_legacy()
    test_pipeline_pilot_coexists_and_gates()
    test_tagging_never_touches_summaries_or_milestones()
    print(f"\n==== 结果: PASS={PASS}  FAIL={FAIL} ====")
    sys.exit(1 if FAIL else 0)

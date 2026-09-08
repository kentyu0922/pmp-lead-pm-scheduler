# -*- coding: utf-8 -*-
"""
test_dependency_engine.py — Dependency Engine v0（分区 SS+lag 规则表）
运行: python tests/test_dependency_engine.py   （无需 MS Project / COM；不 import main）

证明：
  (a) 规则表单源 + 结构校验；分区判定（面积 / 工作面 / 强制 on|off）可解释
  (b) 滞后确定性：lag = clamp(ceil(前置工期 ÷ 工作面数), min, max)，同输入同输出
  (c) 应用语义：命中对由 FS 改 SS+lag，验收门保留为 FF，非命中任务不动，小项目零改动
  (d) CPM 仍有效：正向 SS/FF 语义成立；反向遍历按链接类型计算（SS 前置不再被算成负浮时）
  (e) 全流水线四套模板：小项目 == 旧路径逐任务一致；大项目规则命中、完工提前、
      依赖图无环/无前向引用、SKILL.md 验证门（无空日期 / 合规 0 error / IAQ 链 / 关键路径）不回归
"""
import sys
import os
import json
import copy

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import dependency_engine as D
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


def _run_pipeline(mode, area, cost, city, start, sectional="auto", workfronts=None, engine=True):
    """复刻 main.py 正排流水线（不含导出）：calibrate → productivity(空操作) → fold → renumber →
    [dependency engine] → solve → cpm → compliance。engine=False 为 v4.1 纯旧路径对照。"""
    tpl = _templates()
    tasks = copy.deepcopy(tpl[mode]["tasks"])
    base_area = tpl[mode].get("base_area", 1000)
    permit = query_city_permit_rule(city, area_sqm=area, cost_10k_rmb=cost)
    tasks = calibrate_durations(tasks, permit, area, base_area, "", cost_10k_rmb=cost)
    tasks = P.apply_productivity_durations(tasks)
    if permit.get("is_exempt"):
        tasks = fold_exempt_construction_permit(tasks, True)
    tasks = renumber_tasks_contiguously(tasks)
    report = None
    graph_issues = []
    if engine:
        report = D.apply_dependency_rules(tasks, area, mode=sectional, workfronts=workfronts)
        graph_issues = D.validate_dependency_graph(tasks)
    pairs = H.load_holiday_pairs()
    res = solve_schedule(tasks, start, custom_holidays=pairs)
    solved = compute_cpm_metrics(res["tasks"], project_end=res["finish_date"])
    issues = C.run_compliance_checks(solved, holiday_raw=H.load_holiday_raw())
    return {"tasks": solved, "finish": res["finish_date"], "issues": issues, "report": report,
            "graph_issues": graph_issues, "permit": permit}


def _sig(tasks):
    return [(t["id"], t.get("duration"), t.get("predecessors"), t.get("start"), t.get("finish")) for t in tasks]


# ---------------------------------------------------------------------------
def test_rule_table_single_source():
    print("== 1. 规则表单源 (config/dependency_rules.json) + 结构校验 ==")
    rules = D.load_dependency_rules()
    check("含 activation / lag_policy / gate_policy / rules", all(k in rules for k in ("activation", "lag_policy", "gate_policy", "rules")))
    ids = [r["id"] for r in rules["rules"]]
    check("规则 id 唯一且非空", len(ids) == len(set(ids)) and all(ids), ids)
    check("v0 仅 SS 关系", all(r.get("relationship", "SS") == "SS" for r in rules["rules"]))
    check("每条规则 lag_days 0<=min<=max", all(0 <= r["lag_days"]["min"] <= r["lag_days"]["max"] for r in rules["rules"]))
    check("覆盖 隔墙↔机电 与 机电↔天花 工序对",
          any("隔墙" in "".join(r["predecessor_keywords"]) and "机电" in "".join(r["successor_keywords"]) for r in rules["rules"])
          and any("机电" in "".join(r["predecessor_keywords"]) and "吊顶" in "".join(r["successor_keywords"]) for r in rules["rules"]))
    check("验收门策略 FF（保留门、不产生悬空逻辑）", rules["gate_policy"]["relationship"] == "FF")

    # 结构错误必须 fail loudly
    def bad(mut):
        r = copy.deepcopy(rules)
        mut(r)
        path = os.path.join("/tmp", "bad_dependency_rules.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(r, f)
        return lambda: D.load_dependency_rules(path)
    check("重复 id → ValueError", raises(bad(lambda r: r["rules"][1].__setitem__("id", r["rules"][0]["id"]))))
    check("非 SS 关系 → ValueError", raises(bad(lambda r: r["rules"][0].__setitem__("relationship", "FS"))))
    check("lag min>max → ValueError", raises(bad(lambda r: r["rules"][0].__setitem__("lag_days", {"min": 9, "max": 2}))))
    check("缺 successor_keywords → ValueError", raises(bad(lambda r: r["rules"][0].__setitem__("successor_keywords", []))))
    check("activation 阈值缺失 → ValueError", raises(bad(lambda r: r["activation"].pop("sectional_area_sqm_min"))))


def test_sectional_decision():
    print("\n== 2. 分区判定：面积 / 工作面 / 强制 on|off，可解释 ==")
    d = D.evaluate_sectional(1500)
    check("1500㎡ auto → 非分区, workfronts=1", d["sectional"] is False and d["workfronts"] == 1, d)
    check("判定带原因说明", len(d["reasons"]) == 2 and all("sectional" in r for r in d["reasons"]), d["reasons"])
    d = D.evaluate_sectional(5000)
    check("5000㎡ auto → 分区 (面积阈值), workfronts=2", d["sectional"] is True and d["workfronts"] == 2, d)
    d = D.evaluate_sectional(20000)
    check("20000㎡ → workfronts=8 (上限 max_workfronts)", d["workfronts"] == 8, d["workfronts_basis"])
    d = D.evaluate_sectional(3000, workfronts=3)
    check("3000㎡ + --workfronts 3 → 分区 (工作面条件)", d["sectional"] is True and d["workfronts"] == 3, d["reasons"])
    check("显式工作面基准可解释", "explicit" in d["workfronts_basis"], d["workfronts_basis"])
    d = D.evaluate_sectional(20000, mode="off")
    check("--sectional off 强制关闭", d["sectional"] is False and "forced off" in d["reasons"][0])
    d = D.evaluate_sectional(800, mode="on")
    check("--sectional on 强制开启 (800㎡ 仍 workfronts=1)", d["sectional"] is True and d["workfronts"] == 1)
    check("非法 mode → ValueError", raises(lambda: D.evaluate_sectional(1000, mode="maybe")))
    check("工作面显式值超上限被截断为 8", D.derive_workfronts(20000, D.load_dependency_rules(), workfronts=20)[0] == 8)


def test_lag_deterministic():
    print("\n== 3. 滞后确定性：lag = clamp(ceil(前置工期 ÷ 工作面), min, max) ==")
    lag, basis = D.compute_lag(19, 8, 3, 10)
    check("19d / 8 → ceil 3 → 3", lag == 3 and "ceil(19d / 8 workfronts) = 3" in basis, basis)
    check("21d / 2 → ceil 11 → clamp max 10", D.compute_lag(21, 2, 3, 10)[0] == 10)
    check("2d / 8 → 1 → clamp min 4", D.compute_lag(2, 8, 4, 12)[0] == 4)
    check("0d → min", D.compute_lag(0, 4, 3, 10)[0] == 3)
    check("workfronts<1 视作 1 (不除零)", D.compute_lag(10, 0, 0, 99)[0] == 10)
    check("同输入两次结果完全一致", D.compute_lag(23, 5, 3, 10) == D.compute_lag(23, 5, 3, 10))
    check("工作面越少滞后越大（单调）", D.compute_lag(24, 2, 3, 12)[0] >= D.compute_lag(24, 4, 3, 12)[0] >= D.compute_lag(24, 8, 3, 12)[0])


def _mini_wbs():
    return [
        {"id": 1, "name": "Phase 6 实体施工阶段", "outline_level": 2, "duration_days": 0, "duration": 0, "predecessors": ""},
        {"id": 2, "name": "测量放线与基准标高复核", "outline_level": 3, "duration_days": 2, "duration": 2, "predecessors": "", "work_weekend": True},
        {"id": 3, "name": "隔墙轻钢龙骨骨架搭设", "outline_level": 3, "duration_days": 16, "duration": 16, "predecessors": "2", "work_weekend": True},
        {"id": 4, "name": "大机电主管桥架与主管道预埋安装", "outline_level": 3, "duration_days": 20, "duration": 20, "predecessors": "2SS+2", "work_weekend": True},
        {"id": 5, "name": "[M] 隔墙及主管管线隐蔽工程验收 (In-Wall Inspection)", "outline_level": 3, "duration_days": 2, "duration": 2, "predecessors": "3,4", "work_weekend": True},
        {"id": 6, "name": "墙面封板与天花吊顶龙骨安装", "outline_level": 3, "duration_days": 16, "duration": 16, "predecessors": "5", "work_weekend": True},
        {"id": 7, "name": "二次机电支管敷设、穿线与保温", "outline_level": 3, "duration_days": 20, "duration": 20, "predecessors": "5", "work_weekend": True},
        {"id": 8, "name": "[M] 天花隐蔽工程验收 (Above-Ceiling Concealed Inspection)", "outline_level": 3, "duration_days": 2, "duration": 2, "predecessors": "6,7", "work_weekend": True},
        {"id": 9, "name": "天花封石膏板与墙顶乳胶漆饰面", "outline_level": 3, "duration_days": 18, "duration": 18, "predecessors": "8", "work_weekend": True},
        {"id": 10, "name": "架空防静电地板/地砖/地毯铺设", "outline_level": 3, "duration_days": 10, "duration": 10, "predecessors": "9", "work_weekend": True},
        {"id": 11, "name": "[M] 施工全部完成", "outline_level": 3, "duration_days": 0, "duration": 0, "predecessors": "10", "milestone": True},
    ]


def test_apply_semantics_mini_wbs():
    print("\n== 4. 应用语义（合成 WBS）：FS→SS+lag、验收门→FF、非命中不动、小项目零改动 ==")
    original = _mini_wbs()

    # 小项目：零改动（深比较）
    small = copy.deepcopy(original)
    rep = D.apply_dependency_rules(small, 1500)
    check("1500㎡ → 0 条规则命中", rep["applied"] == [] and rep["decision"]["sectional"] is False)
    check("1500㎡ → 任务列表逐字段不变（无 explain 字段注入）", small == original)

    # 大项目 4 个工作面：16d/4=4, 20d/4=5
    big = copy.deepcopy(original)
    rep = D.apply_dependency_rules(big, 10000)
    by = {t["id"]: t for t in big}
    check("10000㎡ → workfronts=4, 5 条规则命中", rep["decision"]["workfronts"] == 4 and len(rep["applied"]) == 5,
          f"{rep['decision']['workfronts']} {[r['rule_id'] for r in rep['applied']]}")
    check("命中规则 id 顺序确定 = SEC-01..05", [r["rule_id"] for r in rep["applied"]] == ["SEC-01", "SEC-02", "SEC-03", "SEC-04", "SEC-05"])
    check("#7 二次机电: '5' → '5FF,3SS+4,4SS+5' (门→FF, 隔墙 16/4=4, 主管 20/4=5)",
          by[7]["predecessors"] == "5FF,3SS+4,4SS+5", by[7]["predecessors"])
    check("#6 吊顶龙骨: '5' → '5FF,4SS+5,3SS+4'", by[6]["predecessors"] == "5FF,4SS+5,3SS+4", by[6]["predecessors"])
    check("#9 天花封板: '8' → '8FF,7SS+5'", by[9]["predecessors"] == "8FF,7SS+5", by[9]["predecessors"])
    check("原前置串保留于 predecessors_before_rules", by[7]["predecessors_before_rules"] == "5" and by[9]["predecessors_before_rules"] == "8")
    check("explain: dependency_method + 每条命中含 rule_id/lag_basis/gates",
          by[7].get("dependency_method") == D.METHOD_SECTIONAL
          and [x["rule_id"] for x in by[7]["dependency_rules"]] == ["SEC-01", "SEC-02"]
          and all("ceil(" in x["lag_basis"] for x in by[7]["dependency_rules"])
          and by[7]["dependency_rules"][0]["gates"][0]["gate_relationship"] == "FF")
    untouched_ids = [1, 2, 3, 4, 5, 8, 10, 11]
    check("非命中任务（汇总/放线/隔墙/主管/验收门/地板/里程碑）逐字段不变",
          all(by[i] == original[i - 1] for i in untouched_ids))
    check("被改写任务仅 6/7/9", sorted(t["id"] for t in big if "dependency_rules" in t) == [6, 7, 9])

    # 确定性：两次独立应用结果完全一致
    again = copy.deepcopy(original)
    rep2 = D.apply_dependency_rules(again, 10000)
    check("确定性：两次应用 → 任务与报告逐字段一致", again == big and rep2["applied"] == rep["applied"])

    # 幂等性保护：对已改写列表再次应用不会重复叠加 token
    twice = copy.deepcopy(big)
    D.apply_dependency_rules(twice, 10000)
    check("重复应用不叠加重复 token", twice[6]["predecessors"] == big[6]["predecessors"] and twice[6]["predecessors_before_rules"] == "5")

    # 门策略 drop 变体（自定义规则字典）
    rules_drop = D.load_dependency_rules()
    rules_drop["gate_policy"]["relationship"] = "drop"
    dropped = copy.deepcopy(original)
    D.apply_dependency_rules(dropped, 10000, rules=rules_drop)
    check("gate_policy=drop → 门 token 被移除，仅剩 SS", {t["id"]: t["predecessors"] for t in dropped}[9] == "7SS+5")

    # 规则级 min_workfronts 可跳过并说明
    rules_min = D.load_dependency_rules()
    rules_min["rules"][4]["min_workfronts"] = 6
    skipped = copy.deepcopy(original)
    rep3 = D.apply_dependency_rules(skipped, 10000, rules=rules_min)
    check("规则级 min_workfronts 未满足 → skipped 且带原因",
          len(rep3["applied"]) == 4 and any(s["rule_id"] == "SEC-05" and "min_workfronts" in s["reason"] for s in rep3["skipped"]))

    # 图校验
    check("改写后依赖图无环/无前向引用/无未知 id", D.validate_dependency_graph(big) == [])
    cyc = [{"id": 1, "name": "a", "level": 3, "duration": 1, "predecessors": "2"},
           {"id": 2, "name": "b", "level": 3, "duration": 1, "predecessors": "1"}]
    codes = sorted(i["code"] for i in D.validate_dependency_graph(cyc))
    check("环 + 前向引用被 Kahn 排序检出", "PRED_CYCLE" in codes and "PRED_FORWARD_REF" in codes, codes)
    codes = [i["code"] for i in D.validate_dependency_graph([{"id": 1, "name": "a", "level": 3, "duration": 1, "predecessors": "1,9"}])]
    check("自引用 / 未知 id 检出", "PRED_SELF" in codes and "PRED_UNKNOWN" in codes, codes)


def test_solver_semantics_and_cpm_validity():
    print("\n== 5. CPM 仍有效：正向 SS/FF 语义 + 反向遍历按链接类型（无虚假负浮时） ==")
    # 5-day 日历、2026-06-01 干净周一：A 10d；B 5d SS+3 于 A；C 2d FS A,B
    tasks = [
        {"id": 1, "name": "A", "level": 3, "duration": 10, "predecessors": ""},
        {"id": 2, "name": "B", "level": 3, "duration": 5, "predecessors": "1SS+3"},
        {"id": 3, "name": "C", "level": 3, "duration": 2, "predecessors": "1,2"},
    ]
    r = solve_schedule(tasks, "2026-06-01")
    compute_cpm_metrics(r["tasks"], project_end=r["finish_date"])
    by = {t["id"]: t for t in r["tasks"]}
    check("B(SS+3) 起点 = A 起点 + 3 工日 = 06-04", by[2]["start"] == "2026-06-04", by[2]["start"])
    check("A 为 SS 前置且在关键链 → 浮时 0（旧算法按 FS 处理会得 -5）", by[1]["total_slack_days"] == 0 and by[1]["critical"], by[1]["total_slack_days"])
    check("B 浮时 = 2（LS 5 - ES 3）", by[2]["total_slack_days"] == 2 and not by[2]["critical"], by[2]["total_slack_days"])
    check("C 关键", by[3]["critical"] and by[3]["total_slack_days"] == 0)

    # 引擎产出形态：A 10d；G(门) 2d FS A；S 8d = "1SS+3,2FF"
    tasks = [
        {"id": 1, "name": "A", "level": 3, "duration": 10, "predecessors": ""},
        {"id": 2, "name": "G", "level": 3, "duration": 2, "predecessors": "1"},
        {"id": 3, "name": "S", "level": 3, "duration": 8, "predecessors": "1SS+3,2FF"},
    ]
    r = solve_schedule(tasks, "2026-06-01")
    compute_cpm_metrics(r["tasks"], project_end=r["finish_date"])
    by = {t["id"]: t for t in r["tasks"]}
    check("FF 门生效：S 完成 = G 完成 (06-16)，S 起点被后推至 06-05",
          by[3]["finish"] == by[2]["finish"] == "2026-06-16" and by[3]["start"] == "2026-06-05", f"{by[3]} {by[2]}")
    check("A/G/S 全关键且浮时均为 0（FF 反向：LF(G)=LF(S)）",
          all(by[i]["critical"] and by[i]["total_slack_days"] == 0 for i in (1, 2, 3)),
          {i: by[i]["total_slack_days"] for i in by})

    # 里程碑 FS 同日口径：M(0d) 后继同日开始 → 反向不再累积 -1
    tasks = [
        {"id": 1, "name": "A", "level": 3, "duration": 3, "predecessors": ""},
        {"id": 2, "name": "M", "level": 3, "duration": 0, "predecessors": "1", "milestone": True},
        {"id": 3, "name": "B", "level": 3, "duration": 2, "predecessors": "2"},
    ]
    r = solve_schedule(tasks, "2026-06-01")
    compute_cpm_metrics(r["tasks"], project_end=r["finish_date"])
    by = {t["id"]: t for t in r["tasks"]}
    check("里程碑链 A→M→B 浮时全为 0（无 -1 累积）", all(by[i]["total_slack_days"] == 0 for i in (1, 2, 3)),
          {i: by[i]["total_slack_days"] for i in by})

    # 回归：test_v3_basics #3 用例仍成立
    tasks = [
        {"id": 1, "level": 3, "duration": 5, "predecessors": ""},
        {"id": 2, "level": 3, "duration": 3, "predecessors": "1"},
        {"id": 3, "level": 3, "duration": 2, "predecessors": "1"},
        {"id": 4, "level": 3, "duration": 4, "predecessors": "2,3"},
    ]
    r = solve_schedule(tasks, "2026-08-03")
    compute_cpm_metrics(r["tasks"], project_end=r["finish_date"])
    by = {t["id"]: t for t in r["tasks"]}
    check("纯 FS 网络结果不变：1/2/4 关键, 3 浮时 1", by[1]["total_slack_days"] == 0 and by[2]["critical"] and by[4]["critical"] and by[3]["total_slack_days"] == 1)


def test_pipeline_small_equals_legacy_all_templates():
    print("\n== 6(a). 全流水线四套模板：小项目 (1500㎡ / 280㎡免办) == v4.1 旧路径逐任务一致 ==")
    for mode in _templates():
        for area, cost, city in ((1500, 320, "上海"), (280, 80, "苏州")):
            on = _run_pipeline(mode, area, cost, city, "2026-08-28")
            legacy = _run_pipeline(mode, area, cost, city, "2026-08-28", engine=False)
            check(f"[{mode}] {area}㎡ → 0 规则命中, 无 explain 字段", on["report"]["applied"] == [] and not D.dependency_report(on["tasks"]))
            check(f"[{mode}] {area}㎡ → 逐任务 (id,duration,predecessors,start,finish) 与旧路径一致", _sig(on["tasks"]) == _sig(legacy["tasks"]))
            check(f"[{mode}] {area}㎡ → 依赖图无问题", on["graph_issues"] == [])
    check("模板 JSON 本身无引擎字段（模板未被改写）",
          not any(k in t for body in _templates().values() for t in body["tasks"]
                  for k in ("dependency_rules", "predecessors_before_rules", "dependency_method")))


def test_pipeline_sectional_all_templates_and_gates():
    print("\n== 6(b). 全流水线四套模板：大项目 20000㎡ → 规则命中、完工提前、SKILL.md 验证门不回归 ==")
    for mode in _templates():
        off = _run_pipeline(mode, 20000, 8000, "上海", "2026-08-28", sectional="off")
        legacy = _run_pipeline(mode, 20000, 8000, "上海", "2026-08-28", engine=False)
        on = _run_pipeline(mode, 20000, 8000, "上海", "2026-08-28")
        rep = on["report"]
        by = {t["id"]: t for t in on["tasks"]}

        check(f"[{mode}] --sectional off == 旧路径", _sig(off["tasks"]) == _sig(legacy["tasks"]))
        check(f"[{mode}] auto → 分区, workfronts=8, 5 条规则命中 SEC-01..05",
              rep["decision"]["sectional"] and rep["decision"]["workfronts"] == 8
              and [r["rule_id"] for r in rep["applied"]] == ["SEC-01", "SEC-02", "SEC-03", "SEC-04", "SEC-05"],
              [r["rule_id"] for r in rep["applied"]])
        check(f"[{mode}] 完工提前于纯 FS 路径 ({legacy['finish']} → {on['finish']})", on["finish"] < legacy["finish"])
        check(f"[{mode}] 节点总数不变", len(on["tasks"]) == len(legacy["tasks"]))
        check(f"[{mode}] 依赖图无环/无前向引用", on["graph_issues"] == [])

        # 正向语义：SS 后继起点 >= 前置起点；FF 门：后继完成 >= 门完成
        ss_ok = all(by[r["successor_id"]]["start"] >= by[r["predecessor_id"]]["start"] for r in rep["applied"])
        ff_ok = all(by[r["successor_id"]]["finish"] >= by[g["gate_id"]]["finish"] for r in rep["applied"] for g in r["gates"])
        check(f"[{mode}] SS: 后继起点 >= 前置起点; FF: 后继完成 >= 验收门完成", ss_ok and ff_ok)
        check(f"[{mode}] 被改写任务均为叶子实体工序 (非汇总/里程碑, 工期>0)",
              all(not by[r["successor_id"]].get("milestone") and by[r["successor_id"]]["duration_days"] > 0 for r in rep["applied"]))
        check(f"[{mode}] 改写任务上游仍为同一批工序（前置 id 均更早）",
              all(r["predecessor_id"] < r["successor_id"] for r in rep["applied"]))

        # 未改写任务：工期不变（只改链接，不改工期）
        leg_by = {t["id"]: t for t in legacy["tasks"]}
        dur = lambda t: t.get("duration_days", t.get("duration", 0))
        check(f"[{mode}] 引擎不改任何任务工期", all(dur(t) == dur(leg_by[t["id"]]) for t in on["tasks"]))

        # ---- SKILL.md verification gate ----
        leaves = [t for t in on["tasks"] if t.get("outline_level", t.get("level", 1)) >= 3]
        names = [t["name"] for t in leaves]
        check(f"[{mode}] Gate1 无空 Start/Finish", all(t.get("start") and t.get("finish") for t in on["tasks"]))
        check(f"[{mode}] Gate2 compliance 0 error", not any(i["level"] == "error" for i in on["issues"]), on["issues"])
        i_first = next((i for i, n in enumerate(names) if "盲测" in n), -1)
        i_second = next((i for i, n in enumerate(names) if "复测" in n), -1)
        i_furn = next((i for i, n in enumerate(names) if "家具" in n and i > i_first), -1)
        check(f"[{mode}] Gate3 IAQ 链：首次盲测 → 家具 → 二次复测", 0 <= i_first < i_furn < i_second, f"{i_first},{i_furn},{i_second}")
        check(f"[{mode}] Gate5 非免办 → 许可里程碑存在", (not on["permit"].get("is_exempt")) and any("施工许可" in n for n in names))
        gov = [t for t in leaves if "施工许可" in t["name"]]
        check(f"[{mode}] Gate6 许可节点不走施工7天; 被改写工序仍走施工7天",
              all(t.get("use_construction_cal") is False for t in gov)
              and all(by[r["successor_id"]].get("use_construction_cal") is True for r in rep["applied"]))
        check(f"[{mode}] Gate7 关键路径非空", any(t.get("critical") for t in on["tasks"]))
        rows = D.dependency_report(on["tasks"])
        check(f"[{mode}] explain 行数 = 被改写任务数(3)，含 start/finish/critical/rules",
              len(rows) == 3 and all(k in rows[0] for k in ("start", "finish", "critical", "rules", "predecessors_before_rules")))


def test_pipeline_overrides():
    print("\n== 7. CLI 覆盖语义：--sectional on 小项目 / --workfronts 改变滞后 ==")
    mode = "MNC_Standard_Fitout_DBB_Invite"
    legacy = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", engine=False)
    forced = _run_pipeline(mode, 1500, 320, "上海", "2026-08-28", sectional="on")
    check("1500㎡ --sectional on → 5 条规则命中 (workfronts=1)",
          len(forced["report"]["applied"]) == 5 and forced["report"]["decision"]["workfronts"] == 1)
    lag_spec = {r["id"]: r["lag_days"] for r in D.load_dependency_rules()["rules"]}
    check("workfronts=1 → 滞后 = clamp(前置工期, min, max)",
          all(r["lag_days"] == max(lag_spec[r["rule_id"]]["min"], min(lag_spec[r["rule_id"]]["max"], r["predecessor_duration_days"]))
              and r["lag_basis"].endswith(f"= {r['lag_days']}") for r in forced["report"]["applied"]),
          [(r["rule_id"], r["predecessor_duration_days"], r["lag_days"]) for r in forced["report"]["applied"]])
    check("强制分区完工不晚于旧路径", forced["finish"] <= legacy["finish"], f"{forced['finish']} vs {legacy['finish']}")
    check("Gate2/Gate7 仍成立", not any(i["level"] == "error" for i in forced["issues"]) and any(t.get("critical") for t in forced["tasks"]))

    wf8 = _run_pipeline(mode, 20000, 8000, "上海", "2026-08-28")
    wf2 = _run_pipeline(mode, 20000, 8000, "上海", "2026-08-28", workfronts=2)
    lag8 = {r["rule_id"]: r["lag_days"] for r in wf8["report"]["applied"]}
    lag2 = {r["rule_id"]: r["lag_days"] for r in wf2["report"]["applied"]}
    check("--workfronts 2 → 每条规则滞后 >= 8 工作面时", all(lag2[k] >= lag8[k] for k in lag8), f"{lag2} vs {lag8}")
    check("--workfronts 2 完工不早于 8 工作面且不晚于纯 FS", wf8["finish"] <= wf2["finish"] <= _run_pipeline(mode, 20000, 8000, "上海", "2026-08-28", sectional="off")["finish"],
          f"{wf8['finish']} {wf2['finish']}")
    check("判定原因记录显式工作面来源", "explicit --workfronts 2" in wf2["report"]["decision"]["workfronts_basis"])


if __name__ == "__main__":
    test_rule_table_single_source()
    test_sectional_decision()
    test_lag_deterministic()
    test_apply_semantics_mini_wbs()
    test_solver_semantics_and_cpm_validity()
    test_pipeline_small_equals_legacy_all_templates()
    test_pipeline_sectional_all_templates_and_gates()
    test_pipeline_overrides()
    print(f"\n==== 结果: PASS={PASS}  FAIL={FAIL} ====")
    sys.exit(1 if FAIL else 0)

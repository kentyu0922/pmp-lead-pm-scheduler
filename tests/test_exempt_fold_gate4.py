# -*- coding: utf-8 -*-
"""
test_exempt_fold_gate4.py — SKILL.md Verification gate #4 (免办折叠) 自动化
运行: python tests/test_exempt_fold_gate4.py   （无需 MS Project / COM；不 import main / exporters）

固定对抗用例（run_lessons 2026-09-07 Case 2）：
  苏州 280㎡ / 80万 / DB + invite / start=2026-11-02  →  AND_EXEMPT 命中，is_exempt=True

锁定当前正确行为，不改生产折叠语义：
  (a) 阈值判定：280/80 免办；300/80、280/100、1000/250 不免办（AND，严格小于）
  (b) 折叠只移除政府施工许可三节点（阶段汇总 / 政府申报 / [M] 正式取得施工许可证）
  (c) 物业送审 & 安全协议 / 大楼物业申请 / 图审 / 消防路径 全部保留
  (d) 下游「场地移交」前置重映射至被删节点的前置（图审合格证 + 物业送审），无悬空引用
  (e) 全流水线（calibrate → fold → renumber → solve → cpm → compliance）后
      无空日期 / compliance 0 error / IAQ 链完整 / 关键路径非空；四套模板均成立
  (f) 非免办对照：同模板保留全部许可节点（Gate 5 反向锁定）
  (g) 纯函数边界：is_exempt=False 恒等返回；幂等；带滞后 / 链式删除的前置展开；KEEP 关键词守卫
"""
import sys
import os
import json
import copy

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.solver_engine import solve_schedule, compute_cpm_metrics
from core import compliance as C
from core import holidays as H
from core.calibration import calibrate_durations
from core.task_utils import (
    renumber_tasks_contiguously,
    fold_exempt_construction_permit,
    clean_procurement_terminology,
    _is_construction_permit_fold_task,
)
from core.productivity import apply_productivity_durations
from experts.permit_expert import query_city_permit_rule

PASS = 0
FAIL = 0

# ---- Suzhou 280 fixture (run_lessons 2026-09-07 Case 2) ----
FIX_CITY = "苏州"
FIX_AREA = 280
FIX_COST = 80
FIX_START = "2026-11-02"
FIX_MODE = "MNC_Standard_Fitout_DB_Invite"  # DB + invite

ALL_MODES = (
    "MNC_Standard_Fitout_DB_Invite",
    "MNC_Standard_Fitout_DB_Public",
    "MNC_Standard_Fitout_DBB_Invite",
    "MNC_Standard_Fitout_Office_DBB",
)

# 政府施工许可节点：免办时必须全部消失
PERMIT_MARKERS = ("正式取得施工许可证", "施工许可证申报", "施工许可证办理")
# 必须保留的路径
PROPERTY_MARKERS = ("物业装修图纸送审", "大楼物业装修申请")
FIRE_MARKERS = ("消防",)
SITE_TAKEOVER = "场地移交"


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


def _leaf_names(tasks):
    return [t["name"] for t in tasks if t.get("outline_level", t.get("level", 1)) >= 3]


def _has(names, marker):
    return any(marker in n for n in names)


def _find(tasks, marker):
    """First task whose name contains marker, or an empty stub so a missing node reads as [FAIL] not a traceback."""
    return next((t for t in tasks if marker in t.get("name", "")),
                {"id": -1, "name": f"<missing:{marker}>", "predecessors": "", "start": "", "finish": ""})


def _pred_ids(pred_str):
    out = []
    for tok in str(pred_str or "").replace(" ", "").split(","):
        if not tok:
            continue
        i = 0
        while i < len(tok) and tok[i].isdigit():
            i += 1
        if i:
            out.append(int(tok[:i]))
    return out


def _run_pipeline(mode, city, area, cost, start, force_fold=None):
    """复刻 main.py 正排流水线（不含导出）。force_fold=True/False 可越过 permit 判定直接控制折叠开关。"""
    tpl = _templates()[mode]
    tasks = copy.deepcopy(tpl["tasks"])
    permit = query_city_permit_rule(city, area_sqm=area, cost_10k_rmb=cost)
    tasks = calibrate_durations(tasks, permit, area, tpl.get("base_area", 1000), "", cost_10k_rmb=cost)
    tasks = apply_productivity_durations(tasks)
    pre_fold = copy.deepcopy(tasks)
    do_fold = permit.get("is_exempt") if force_fold is None else force_fold
    if do_fold:
        tasks = fold_exempt_construction_permit(tasks, True)
    post_fold = copy.deepcopy(tasks)
    tasks = clean_procurement_terminology(tasks, mode)
    tasks = renumber_tasks_contiguously(tasks)
    res = solve_schedule(tasks, start, custom_holidays=H.load_holiday_pairs())
    solved = compute_cpm_metrics(res["tasks"], project_end=res["finish_date"])
    issues = C.run_compliance_checks(solved, holiday_raw=H.load_holiday_raw())
    return {"permit": permit, "pre_fold": pre_fold, "post_fold": post_fold,
            "tasks": solved, "finish": res["finish_date"], "issues": issues}


# ---------------------------------------------------------------------------
def test_threshold_decision():
    print("== 1. 属地免办判定（苏州 AND_EXEMPT，严格小于） ==")
    p = query_city_permit_rule(FIX_CITY, area_sqm=FIX_AREA, cost_10k_rmb=FIX_COST)
    check("苏州规则 = AND_EXEMPT, 300㎡ / 100万", p.get("rule_type") == "AND_EXEMPT"
          and p.get("area_threshold") == 300 and p.get("cost_threshold_10k") == 100, str(p))
    check("苏州 280㎡/80万 → is_exempt=True", p.get("is_exempt") is True and p.get("is_mandatory") is False, str(p))
    check("exempt_desc 非空（供 main.py 日志引用）", bool(p.get("exempt_desc")))

    edge_area = query_city_permit_rule(FIX_CITY, area_sqm=300, cost_10k_rmb=80)
    check("边界 300㎡/80万 → 不免办（面积等于门槛不算低于）", edge_area.get("is_exempt") is False, str(edge_area))
    edge_cost = query_city_permit_rule(FIX_CITY, area_sqm=280, cost_10k_rmb=100)
    check("边界 280㎡/100万 → 不免办（AND：造价等于门槛）", edge_cost.get("is_exempt") is False, str(edge_cost))
    big = query_city_permit_rule(FIX_CITY, area_sqm=1000, cost_10k_rmb=250)
    check("对照 1000㎡/250万 → 不免办", big.get("is_exempt") is False and big.get("is_mandatory") is True, str(big))


def test_fold_keyword_guard():
    print("\n== 2. 折叠关键词守卫（纯函数） ==")
    check("『政府施工许可证申报与审批』→ 折叠", _is_construction_permit_fold_task("政府施工许可证申报与审批"))
    check("『[M] ⭐️ 正式取得施工许可证』→ 折叠", _is_construction_permit_fold_task("[M] ⭐️ 正式取得施工许可证"))
    check("『质安监报监及政府施工许可证申报』→ 折叠", _is_construction_permit_fold_task("质安监报监及政府施工许可证申报"))
    check("『Phase 4  施工许可证办理』阶段汇总 → 折叠", _is_construction_permit_fold_task("Phase 4  施工许可证办理"))
    check("『物业装修图纸送审与安全协议签署』→ 保留", not _is_construction_permit_fold_task("物业装修图纸送审与安全协议签署"))
    check("『大楼物业装修申请 & CI导则/机电图获取』→ 保留", not _is_construction_permit_fold_task("大楼物业装修申请 & CI导则/机电图获取"))
    check("『二次装修安全协议签署』→ 保留", not _is_construction_permit_fold_task("二次装修安全协议签署"))
    check("『住建局：消防设计审查申报』→ 保留（消防路径不受折叠影响）", not _is_construction_permit_fold_task("住建局：消防设计审查申报"))
    check("『[M] 场地移交与动工准备 Site Takeover』→ 保留", not _is_construction_permit_fold_task("[M] 场地移交与动工准备 Site Takeover"))
    check("空名 → 保留", not _is_construction_permit_fold_task("") and not _is_construction_permit_fold_task(None))


def test_fold_function_semantics():
    print("\n== 3. fold_exempt_construction_permit 纯函数语义 ==")
    tasks = [
        {"id": 1, "name": "[M] 图审合格证获取", "level": 3, "duration": 0, "predecessors": "", "milestone": True},
        {"id": 2, "name": "物业装修图纸送审与安全协议签署", "level": 3, "duration": 3, "predecessors": "1"},
        {"id": 3, "name": "Phase 4  施工许可证办理", "level": 2, "duration": 0, "predecessors": ""},
        {"id": 4, "name": "政府施工许可证申报与审批", "level": 3, "duration": 5, "predecessors": "1,2SS+1"},
        {"id": 5, "name": "[M] 正式取得施工许可证", "level": 3, "duration": 0, "predecessors": "4", "milestone": True},
        {"id": 6, "name": "[M] 场地移交 Site Takeover", "level": 3, "duration": 0, "predecessors": "5FS+2d", "milestone": True},
        {"id": 7, "name": "家具供应商定标", "level": 3, "duration": 5, "predecessors": "2"},
        {"id": 8, "name": "隔墙施工", "level": 3, "duration": 10, "predecessors": "6,7"},
    ]

    # is_exempt=False → 恒等（同一对象，零改动）
    src = copy.deepcopy(tasks)
    same = fold_exempt_construction_permit(src, False)
    check("is_exempt=False → 原样返回（同一 list 对象，内容不变）", same is src and same == tasks)

    out = fold_exempt_construction_permit(copy.deepcopy(tasks), True)
    ids = [t["id"] for t in out]
    check("移除 3/4/5（阶段汇总 + 申报 + 里程碑），保留其余 5 节点", ids == [1, 2, 6, 7, 8], ids)
    by = {t["id"]: t for t in out}
    # 6 原前置 5FS+2d → 5 被删 → 5 的前置 4 → 4 被删 → 4 的前置 "1,2SS+1"（链式展开，保留父级后缀，丢弃被删边的滞后）
    check("场地移交前置链式重映射 5FS+2d → 4 → '1,2SS+1'", by[6]["predecessors"] == "1,2SS+1", by[6]["predecessors"])
    check("未涉及节点前置不变（7→'2', 8→'6,7'）", by[7]["predecessors"] == "2" and by[8]["predecessors"] == "6,7",
          f"{by[7]['predecessors']} / {by[8]['predecessors']}")
    check("输入 list 未被就地修改（返回新 dict）", tasks[5]["predecessors"] == "5FS+2d")
    check("无悬空前置（全部引用存活 id）",
          all(pid in by for t in out for pid in _pred_ids(t["predecessors"])))

    # 幂等：第二次折叠无命中，结果逐字段一致
    twice = fold_exempt_construction_permit(copy.deepcopy(out), True)
    check("幂等：二次折叠结果一致", twice == out)

    # 去重：两条前置都指向被删节点且展开为同一父级 → 只保留一份
    dup = [
        {"id": 1, "name": "图审", "level": 3, "duration": 1, "predecessors": ""},
        {"id": 2, "name": "政府施工许可证申报", "level": 3, "duration": 5, "predecessors": "1"},
        {"id": 3, "name": "[M] 正式取得施工许可证", "level": 3, "duration": 0, "predecessors": "1,2"},
        {"id": 4, "name": "开工", "level": 3, "duration": 1, "predecessors": "2,3"},
    ]
    d_out = fold_exempt_construction_permit(dup, True)
    check("展开后前置去重（'2,3' → '1'）", [t["id"] for t in d_out] == [1, 4] and d_out[1]["predecessors"] == "1",
          str(d_out[1]["predecessors"]))

    # 无许可节点：不报错、原样返回
    none = [{"id": 1, "name": "隔墙施工", "level": 3, "duration": 3, "predecessors": ""}]
    check("模板无许可节点 → 原样返回", fold_exempt_construction_permit(none, True) == none)


def test_suzhou_280_gate4_fixture():
    print(f"\n== 4. Gate4 固定用例：{FIX_CITY} {FIX_AREA}㎡ / {FIX_COST}万 / DB+invite / start={FIX_START} ==")
    r = _run_pipeline(FIX_MODE, FIX_CITY, FIX_AREA, FIX_COST, FIX_START)
    check("流水线判定 is_exempt=True", r["permit"].get("is_exempt") is True)

    pre, post = r["pre_fold"], r["post_fold"]
    pre_names = [t["name"] for t in pre]
    post_names = [t["name"] for t in post]
    removed = [n for n in pre_names if n not in set(post_names)]
    check("折叠恰好移除 3 个节点", len(pre) - len(post) == 3 and len(removed) == 3, removed)
    check("被移除节点全部为政府施工许可节点",
          all(any(m in n for m in PERMIT_MARKERS) for n in removed), removed)
    check("被移除节点含 [M] 正式取得施工许可证", any("正式取得施工许可证" in n for n in removed), removed)
    check("被移除节点含 政府施工许可证申报", any("施工许可证申报" in n for n in removed), removed)
    check("被移除节点含 施工许可证办理 阶段汇总", any("施工许可证办理" in n for n in removed), removed)

    # 折叠后与解算后（含术语清洗）都不残留许可节点
    solved_names = [t["name"] for t in r["tasks"]]
    for marker in PERMIT_MARKERS:
        check(f"Gate4 折叠后无『{marker}』", not _has(post_names, marker) and not _has(solved_names, marker))

    # 物业 / 图审 / 消防 全部保留，数量不变
    for marker in PROPERTY_MARKERS:
        check(f"Gate4 保留『{marker}』", _has(solved_names, marker))
    n_prop_pre = sum(1 for n in pre_names if "物业" in n)
    n_prop_post = sum(1 for n in solved_names if "物业" in n)
    check("物业节点数折叠前后一致", n_prop_pre == n_prop_post and n_prop_post >= 2, f"{n_prop_pre} → {n_prop_post}")
    n_fire_pre = sum(1 for n in pre_names if any(m in n for m in FIRE_MARKERS))
    n_fire_post = sum(1 for n in solved_names if any(m in n for m in FIRE_MARKERS))
    check("消防节点数折叠前后一致（免办≠无审批）", n_fire_pre == n_fire_post and n_fire_post >= 1, f"{n_fire_pre} → {n_fire_post}")
    check("图审合格证节点保留", _has(solved_names, "图审合格证") or _has(solved_names, "施工图审查合格书"))

    # 下游重映射：场地移交前置 = 图审合格证 + 物业送审（原许可里程碑的祖先）
    by_id = {t["id"]: t for t in r["tasks"]}
    site = _find(r["tasks"], SITE_TAKEOVER)
    check("场地移交节点保留", site["id"] != -1)
    site_pred_names = [by_id[p]["name"] for p in _pred_ids(site["predecessors"]) if p in by_id]
    check("场地移交前置已重映射（非空、无悬空 id）",
          site_pred_names and len(site_pred_names) == len(_pred_ids(site["predecessors"])), site["predecessors"])
    check("场地移交前置含 图审合格证", any("图审合格证" in n for n in site_pred_names), site_pred_names)
    check("场地移交前置含 物业装修图纸送审", any("物业装修图纸送审" in n for n in site_pred_names), site_pred_names)
    check("场地移交前置不含任何许可节点", not any(any(m in n for m in PERMIT_MARKERS) for n in site_pred_names), site_pred_names)
    prop = _find(r["tasks"], "物业装修图纸送审")
    review = _find(r["tasks"], "图审合格证")
    check("排程：场地移交不早于 物业送审 完成", prop["finish"] and site["start"] >= prop["finish"], f"{site['start']} vs {prop['finish']}")
    check("排程：场地移交不早于 图审合格证", review["finish"] and site["start"] >= review["finish"], f"{site['start']} vs {review['finish']}")

    # ID 连续 & 无悬空
    ids = [t["id"] for t in r["tasks"]]
    check("renumber 后 id 连续 1..N", ids == list(range(1, len(ids) + 1)))
    check("全表无悬空前置", all(p in by_id for t in r["tasks"] for p in _pred_ids(t.get("predecessors", ""))))

    # ---- SKILL.md verification gate on the exempt fixture ----
    check("Gate1 无空 Start/Finish", all(t.get("start") and t.get("finish") for t in r["tasks"]))
    errs = [i for i in r["issues"] if i.get("level") == "error"]
    check("Gate2 compliance 0 error", not errs, str(errs))
    check("compliance 无 FIRE_NODE_MISSING（免办不误删消防路径）",
          not any(i.get("code") == "FIRE_NODE_MISSING" for i in r["issues"]), str(r["issues"]))
    leaves = _leaf_names(r["tasks"])
    i_first = next((i for i, n in enumerate(leaves) if "盲测" in n), -1)
    i_second = next((i for i, n in enumerate(leaves) if "复测" in n), -1)
    i_furn = next((i for i, n in enumerate(leaves) if "家具" in n and i > i_first), -1)
    check("Gate3 IAQ 链：首次盲测 → 家具 → 二次复测", 0 <= i_first < i_furn < i_second, f"{i_first},{i_furn},{i_second}")
    check("Gate7 关键路径非空", any(t.get("critical") for t in r["tasks"]))
    check("项目终点非空且晚于开工日", r["finish"] and r["finish"] > FIX_START, r["finish"])


def test_all_templates_exempt_fold():
    print(f"\n== 5. 四套模板 × {FIX_CITY} {FIX_AREA}㎡/{FIX_COST}万：折叠语义一致 ==")
    for mode in ALL_MODES:
        r = _run_pipeline(mode, FIX_CITY, FIX_AREA, FIX_COST, FIX_START)
        pre_names = [t["name"] for t in r["pre_fold"]]
        names = [t["name"] for t in r["tasks"]]
        check(f"[{mode}] 模板原本含许可里程碑（用例有效）", _has(pre_names, "正式取得施工许可证"))
        check(f"[{mode}] 恰移除 3 节点", len(r["pre_fold"]) - len(r["post_fold"]) == 3,
              f"{len(r['pre_fold'])} → {len(r['post_fold'])}")
        check(f"[{mode}] 无许可节点残留", not any(_has(names, m) for m in PERMIT_MARKERS))
        check(f"[{mode}] 物业送审保留", _has(names, "物业装修图纸送审"))
        check(f"[{mode}] 消防节点数不变",
              sum("消防" in n for n in pre_names) == sum("消防" in n for n in names))
        by_id = {t["id"]: t for t in r["tasks"]}
        check(f"[{mode}] 无悬空前置", all(p in by_id for t in r["tasks"] for p in _pred_ids(t.get("predecessors", ""))))
        check(f"[{mode}] 无空日期 + compliance 0 error + 关键路径非空",
              all(t.get("start") and t.get("finish") for t in r["tasks"])
              and not any(i.get("level") == "error" for i in r["issues"])
              and any(t.get("critical") for t in r["tasks"]), str(r["issues"]))


def test_non_exempt_control():
    print(f"\n== 6. 非免办对照（Gate 5 反向锁定）：{FIX_CITY} 1000㎡/250万 同模板 ==")
    r = _run_pipeline(FIX_MODE, FIX_CITY, 1000, 250, FIX_START)
    names = [t["name"] for t in r["tasks"]]
    check("is_exempt=False", r["permit"].get("is_exempt") is False)
    check("未折叠：节点数不变", len(r["pre_fold"]) == len(r["post_fold"]) == len(r["tasks"]))
    check("Gate5 许可里程碑存在", _has(names, "正式取得施工许可证"))
    check("政府施工许可证申报存在", _has(names, "施工许可证申报"))
    by_id = {t["id"]: t for t in r["tasks"]}
    site = _find(r["tasks"], SITE_TAKEOVER)
    site_preds = [by_id[p]["name"] for p in _pred_ids(site["predecessors"]) if p in by_id]
    check("场地移交前置仍为许可里程碑（未被重映射）", any("正式取得施工许可证" in n for n in site_preds), site_preds)
    check("compliance 0 error", not any(i.get("level") == "error" for i in r["issues"]))

    # 同一校准任务表：强制折叠 vs 不折叠 —— 折叠不得推迟项目终点
    folded = _run_pipeline(FIX_MODE, FIX_CITY, FIX_AREA, FIX_COST, FIX_START, force_fold=True)
    unfolded = _run_pipeline(FIX_MODE, FIX_CITY, FIX_AREA, FIX_COST, FIX_START, force_fold=False)
    check("同输入：折叠后终点 ≤ 未折叠终点（折叠只缩短或持平）", folded["finish"] <= unfolded["finish"],
          f"{folded['finish']} vs {unfolded['finish']}")
    check("同输入：未折叠保留许可里程碑；折叠后移除", _has([t["name"] for t in unfolded["tasks"]], "正式取得施工许可证")
          and not _has([t["name"] for t in folded["tasks"]], "正式取得施工许可证"))


if __name__ == "__main__":
    test_threshold_decision()
    test_fold_keyword_guard()
    test_fold_function_semantics()
    test_suzhou_280_gate4_fixture()
    test_all_templates_exempt_fold()
    test_non_exempt_control()
    print(f"\n==== 结果: PASS={PASS}  FAIL={FAIL} ====")
    sys.exit(1 if FAIL else 0)

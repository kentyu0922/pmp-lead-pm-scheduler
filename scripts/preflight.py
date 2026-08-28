# -*- coding: utf-8 -*-
"""
preflight.py - v3 上线前预检（归并自 WBTEST 工程纪律层）

在跑 main.py 之前运行，早失败、早定位：
  * config/holidays.json 可加载且非空（单源校验）
  * 核心模块可导入（solver_engine / mpp_renderer / holidays）
  * 一次最小正向解算可跑通
  * 检测 MS Project COM 可用性（缺则明确告警，不静默崩）

返回 issues 列表；空列表 = 通过。
"""
import os
import sys
import json
import importlib.util

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BASE, *name.split(".")) + ".py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_preflight(verbose: bool = True) -> list:
    issues = []

    # 1) 节假日单源
    try:
        H = _load("core.holidays")
        raw = H.load_holiday_raw()
        if not raw:
            issues.append("config/holidays.json 为空或加载失败（单源断裂）")
        else:
            pairs = H.load_holiday_pairs()
            if verbose:
                print(f"[preflight] 节假日单源 OK：{len(pairs)} 条区间")
    except Exception as e:
        issues.append(f"core.holidays 加载失败: {e}")

    # 2) 核心模块可导入（含 v3 收敛新增的合规/日历/报建模块）
    for mod in ["core.solver_engine", "core.mpp_renderer",
                "core.compliance", "core.holidays", "experts.permit_expert"]:
        try:
            _load(mod)
            if verbose:
                print(f"[preflight] 模块导入 OK: {mod}")
        except Exception as e:
            issues.append(f"模块导入失败 {mod}: {e}")

    # 2.5) 城市免办限额库可加载（外置单源）
    try:
        with open(os.path.join(BASE, "config", "city_permit.json"), "r", encoding="utf-8") as f:
            cdb = json.load(f)
        cities = cdb.get("cities", {})
        if not cities:
            issues.append("config/city_permit.json 无城市数据")
        else:
            if verbose:
                print(f"[preflight] 城市免办限额库 OK：{len(cities)} 城 + 兜底默认")
    except Exception as e:
        issues.append(f"config/city_permit.json 加载失败: {e}")

    # 3) 最小正向解算
    try:
        SE = _load("core.solver_engine")
        res = SE.solve_schedule(
            [{"id": 1, "level": 3, "duration": 5, "predecessors": ""},
             {"id": 2, "level": 3, "duration": 3, "predecessors": "1"}],
            "2026-09-21",
        )
        if res["tasks"][0]["finish"] != "2026-09-28":
            issues.append(f"最小解算异常：期望 2026-09-28，实得 {res['tasks'][0]['finish']}")
        else:
            if verbose:
                print("[preflight] 最小正向解算 OK（跨中秋 5 工日 -> 09-28）")
    except Exception as e:
        issues.append(f"最小解算失败: {e}")

    # 4) MS Project COM 可用性（缺失则告警，不阻断 preflight 通过）
    try:
        import win32com.client  # noqa: F401
        if verbose:
            print("[preflight] MS Project COM (win32com) 可用")
    except Exception:
        print("[preflight][WARN] 未检测到 win32com / MS Project：build_mpp 将失败，"
              "需在有 MS Project 的宿主运行；离线部分（解算/CPM估算）不受影响。")

    return issues


if __name__ == "__main__":
    iss = run_preflight()
    if iss:
        print("\n=== preflight 未通过 ===")
        for x in iss:
            print("  -", x)
        sys.exit(1)
    print("\n=== preflight 全部通过 ===")

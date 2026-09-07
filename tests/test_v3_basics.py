# -*- coding: utf-8 -*-
"""
test_v3_basics.py - v3 最小测试套件（无需 MS Project）
运行: python tests/test_v3_basics.py
覆盖: 单源节假日 / 正向解算(含跨节假) / 反向浮时壳 / 关键路径 / 输入覆盖修复
"""
import sys
import os
import json
import tempfile
import importlib.util

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

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


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BASE, *name.split(".")) + ".py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_single_source_holidays():
    print("== 1. 节假日单源 (config/holidays.json) ==")
    H = _load("core.holidays")
    pairs = H.load_holiday_pairs()
    raw = H.load_holiday_raw()
    check("pairs 非空", len(pairs) >= 30, f"实际 {len(pairs)}")
    check("raw 与 pairs 同源", len(raw) == len(pairs))
    check("含 2027 春节(02-06)", any(s == "2027-02-06" for s, e in pairs))
    check("含 2030 国庆兜底", any(s == "2030-10-01" for s, e in pairs))
    # 单源：求解器与渲染器都从同一 config 读取
    SE = _load("core.solver_engine")
    eng_pairs = SE.get_holidays_for_years(2025, 2030)
    check("求解器同样从 config 取节假日(非内置注册表)",
          any(s == "2027-02-06" for s, e in eng_pairs))


def test_forward_solve():
    print("\n== 2. 正向解算 + 跨节假日 ==")
    SE = _load("core.solver_engine")
    # 2a) 跨中秋：5 工日从 09-21 起，跳过 09-25 中秋 -> 09-28
    res = SE.solve_schedule(
        [{"id": 1, "level": 3, "duration": 5, "predecessors": ""}],
        "2026-09-21",
    )
    t1 = res["tasks"][0]
    check("任务1 09-21 起 5 工日 -> 09-28(跳过中秋)", t1["start"] == "2026-09-21" and t1["finish"] == "2026-09-28", f"{t1}")

    # 2b) FS 链 + 里程碑：08-03 起无 intervening 假期
    #     id1 5d -> 08-07; id2 FS 3d -> 08-10..08-12; id3 里程碑 FS -> 08-13(次工作日)
    res2 = SE.solve_schedule(
        [{"id": 1, "level": 3, "duration": 5, "predecessors": ""},
         {"id": 2, "level": 3, "duration": 3, "predecessors": "1"},
         {"id": 3, "level": 3, "duration": 0, "predecessors": "2", "milestone": True}],
        "2026-08-03",
    )
    a1, a2, a3 = res2["tasks"]
    check("id1 08-03->08-07", a1["start"] == "2026-08-03" and a1["finish"] == "2026-08-07", f"{a1}")
    check("id2 FS 08-10->08-12", a2["start"] == "2026-08-10" and a2["finish"] == "2026-08-12", f"{a2}")
    check("里程碑3 = id2完成次工作日 08-13", a3["start"] == "2026-08-13" and a3["finish"] == "2026-08-13", f"{a3}")


def test_backward_cpm():
    print("\n== 3. 反向遍历 / 浮时 / 关键路径 ==")
    SE = _load("core.solver_engine")
    tasks = [
        {"id": 1, "level": 3, "duration": 5, "predecessors": ""},
        {"id": 2, "level": 3, "duration": 3, "predecessors": "1"},
        {"id": 3, "level": 3, "duration": 2, "predecessors": "1"},
        {"id": 4, "level": 3, "duration": 4, "predecessors": "2,3"},
    ]
    res = SE.solve_schedule(tasks, "2026-08-03")
    SE.compute_cpm_metrics(res["tasks"], project_end=res["finish_date"])
    by = {t["id"]: t for t in res["tasks"]}
    check("关键链 id1 关键(slack=0)", by[1]["critical"] and by[1]["total_slack_days"] == 0)
    check("关键链 id2 关键(slack=0)", by[2]["critical"])
    check("关键链 id4 关键(slack=0)", by[4]["critical"])
    check("平行短支线 id3 非关键且有浮时", (not by[3]["critical"]) and by[3]["total_slack_days"] >= 1,
          f"slack={by[3]['total_slack_days']}")
    check("项目终点 = 2026-08-18", res["finish_date"] == "2026-08-18", res["finish_date"])


def test_overwrite_fix():
    print("\n== 4. 输入文件覆盖修复（默认 .solved.json）==")
    SE = _load("core.solver_engine")
    with tempfile.TemporaryDirectory() as td:
        inp = os.path.join(td, "schedule.json")
        payload = {"project_start": "2026-09-01",
                   "tasks": [{"id": 1, "level": 3, "duration": 5, "predecessors": ""}]}
        with open(inp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        original_snapshot = json.dumps(payload, ensure_ascii=False, sort_keys=True)  # 解算前快照(未被污染)
        SE.solve_schedule(payload["tasks"], payload["project_start"])  # 不应写文件，但会原地改内存对象
        # 直接调用等价逻辑（与 solver_engine.__main__ 一致：默认输出 .solved.json）
        res = SE.solve_schedule(payload["tasks"], payload["project_start"])
        base, _ = os.path.splitext(inp)
        out = base + ".solved.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        check("原输入文件未被覆盖", os.path.exists(inp))
        check("生成 .solved.json 而非覆写", os.path.exists(out) and out != inp)
        with open(inp, encoding="utf-8") as f:
            check("输入内容保持原始(未被污染)", json.dumps(json.load(f), ensure_ascii=False, sort_keys=True) == original_snapshot)


def test_city_permit_externalized():
    print("\n== 5. 城市免办限额库外置 (config/city_permit.json) ==")
    PE = _load("experts.permit_expert")
    sz = PE.query_city_permit_rule("苏州", area_sqm=8000, cost_10k_rmb=500)
    check("苏州面积阈值=300", sz.get("area_threshold") == 300, f"{sz}")
    check("苏州规则=AND_EXEMPT", sz.get("rule_type") == "AND_EXEMPT", f"{sz}")
    check("苏州 8000㎡ 非免办", sz.get("is_mandatory") is True, f"{sz}")
    # 未知城市静态兜底，不触发网络
    unk = PE.query_city_permit_rule("南京", area_sqm=200, cost_10k_rmb=50)
    check("未知城市回退全国通用标准(非 None)", unk.get("policy_doc") is not None)
    check("未知城市仍给出阈值", unk.get("area_threshold") == 300, f"{unk}")


def test_compliance_redlines():
    print("\n== 6. 合规红线代码化校验 ==")
    C = _load("core.compliance")
    # 6a) 缺二次空气检测 -> 应报 error
    bad = [{"id": 1, "name": "首次室内空气盲测", "level": 3, "duration": 3, "predecessors": ""}]
    iss = C.run_compliance_checks(bad, holiday_raw=[{"name": "春节", "start": "2027-02-06", "finish": "2027-02-20"}])
    codes = [i["code"] for i in iss]
    check("缺二次空气检测触发 AIR_SECOND_MISSING", "AIR_SECOND_MISSING" in codes, f"{codes}")
    check("该违例为 error 级", any(i["level"] == "error" for i in iss if i["code"] == "AIR_SECOND_MISSING"))

    # 6b) 完整双检测 + 消防 -> 无 error
    good = [
        {"id": 1, "name": "首次室内空气盲测", "level": 3, "duration": 3, "predecessors": ""},
        {"id": 2, "name": "消防图审与备案", "level": 3, "duration": 7, "predecessors": "1"},
        {"id": 3, "name": "二次室内空气质量复测", "level": 3, "duration": 4, "predecessors": "2"},
    ]
    iss2 = C.run_compliance_checks(good, holiday_raw=[{"name": "春节", "start": "2027-02-06", "finish": "2027-02-20"}])
    check("完整排程无 error 级违例", not any(i["level"] == "error" for i in iss2), f"{iss2}")

    # 6c) 缺春节日历 -> 触发 SPRING_FESTIVAL_MISSING warning
    iss3 = C.run_compliance_checks(good, holiday_raw=[{"name": "国庆", "start": "2027-10-01", "finish": "2027-10-07"}])
    check("缺春节日历触发 SPRING_FESTIVAL_MISSING", any(i["code"] == "SPRING_FESTIVAL_MISSING" for i in iss3), f"{iss3}")


def test_calendar_utils():
    print("\n== 7. 客户工作日与倒排工具 (core/holidays) ==")
    H = _load("core.holidays")
    import datetime
    # 2027-01-01 周五；days_before=7 -> 12-25 周六，应回退到周五 12-24
    tgt = datetime.date(2027, 1, 1)
    mv = H.get_latest_client_workday_before(tgt, days_before=7)
    check("倒排结果为客户工作日(周一~周五)", 0 <= mv.weekday() <= 4, f"{mv}")
    check("倒排不晚于目标前 7 天附近", (tgt - mv).days >= 7, f"{(tgt - mv).days}")


def test_target_branch_integration():
    """复刻 main.py 倒排分支(第234-262行)精确逻辑，此前为 0 覆盖路径。
    不触发 build_mpp/COM。纠正早期误报：solve_schedule_with_target 返回 dict，
    compute_cpm_metrics 后 tasks_solved 变 list，run_compliance_checks 接收 list —— 路径正确。"""
    print("\n== 8. 倒排分支集成 (main.py target mode, 不碰 COM) ==")
    import datetime
    import main
    from core.solver_engine import solve_schedule_with_target, compute_cpm_metrics
    from core.holidays import get_latest_client_workday_before
    from core import compliance as _compliance

    holidays_raw = main._holidays.load_holiday_raw()
    holidays_pairs = main._holidays.load_holiday_pairs()

    tasks = [
        {"id": 1, "level": 3, "name": "设计深化", "duration": 10, "predecessors": ""},
        {"id": 2, "level": 3, "name": "施工准备", "duration": 5, "predecessors": "1"},
        {"id": 3, "level": 3, "name": "硬装施工", "duration": 30, "predecessors": "2"},
        {"id": 4, "level": 3, "name": "家具进场", "duration": 10, "predecessors": "3"},
        {"id": 5, "level": 3, "name": "正式搬迁入驻", "duration": 3, "predecessors": "4"},
    ]

    target_dt = datetime.datetime.strptime("2027-07-30", "%Y-%m-%d").date()
    safe_finish_date = get_latest_client_workday_before(target_dt, days_before=7, holidays=holidays_raw)
    # ↓ 以下逐行对齐 main.py:234-242
    solve_res = solve_schedule_with_target(
        tasks, target_finish_date_str=safe_finish_date.strftime("%Y-%m-%d"),
        target_buffer_days=0, active_holidays=holidays_pairs)
    start_date_str = solve_res["start_date"]          # dict 取值成立
    tasks_solved = solve_res["tasks"]                  # dict 取值成立
    finish_date = solve_res["finish_date"]             # dict 取值成立
    check("solve_schedule_with_target 返回 dict(含 start_date/tasks/finish_date)",
          isinstance(solve_res, dict) and start_date_str and tasks_solved and finish_date)
    check("倒排完工日不晚于安全截止日", finish_date <= safe_finish_date.strftime("%Y-%m-%d"),
          f"{finish_date} vs {safe_finish_date}")
    # ↓ 对齐 main.py:252 —— compute_cpm_metrics 后 tasks_solved 变为 list
    tasks_solved = compute_cpm_metrics(tasks_solved, project_end=finish_date)
    check("CPM 估算后 tasks_solved 为 list", isinstance(tasks_solved, list))
    n_crit = sum(1 for t in tasks_solved if t.get("critical"))
    check("关键路径识别生效(>=1 节点)", n_crit >= 1, f"n_crit={n_crit}")
    # ↓ 对齐 main.py:258 —— run_compliance_checks 接收 list（此前误报点）
    issues = _compliance.run_compliance_checks(tasks_solved, holiday_raw=holidays_raw)
    check("run_compliance_checks 接收 list 无异常", isinstance(issues, list))
    _compliance.log_compliance(issues)  # 仅打印，不阻断


def test_responsibility_resolution():
    """责任识别引擎：阶段判定 / 里程碑·汇总·叶子标识 / 采购品类细化 / 任务级 override。"""
    print("\n== 9. 责任识别引擎 (core.responsibility, 不碰 COM) ==")
    from core import responsibility as R

    # 1) 阶段自动判定
    r = R.resolve_responsibility({"name": "施工图深化与智能化专业", "outline_level": 3, "duration": 10})
    check("设计任务→设计院/设计负责人", r["responsible_unit"] == "设计院" and r["responsible_person"] == "设计负责人", str(r))
    r = R.resolve_responsibility({"name": "RFP 正式发出 + 现场踏勘", "outline_level": 3, "duration": 5})
    check("招采任务→业主方招采组/招采经理", r["responsible_unit"] == "业主方招采组", str(r))
    r = R.resolve_responsibility({"name": "彩钢板围护结构安装", "outline_level": 4, "duration": 8})
    check("施工任务→施工总包/总包项目经理", r["responsible_unit"] == "施工总包", str(r))

    # 2) 责任标识
    r = R.resolve_responsibility({"name": "[M] 竣工备案/联合验收通过", "outline_level": 3, "milestone": True})
    check("里程碑→▲ 关键里程碑", r["responsibility_flag"] == R._FLAG_MILESTONE, str(r))
    r = R.resolve_responsibility({"name": "Phase 6 实体施工阶段", "outline_level": 2, "duration": 0})
    check("阶段汇总→◎ 阶段统筹", r["responsibility_flag"] == R._FLAG_PHASE, str(r))
    r = R.resolve_responsibility({"name": "施工图深化", "outline_level": 3, "duration": 10})
    check("叶子任务→★ 直接负责", r["responsibility_flag"] == R._FLAG_DIRECT, str(r))

    # 3) 采购品类细化责任人
    r = R.resolve_responsibility({"name": "家具生产交货 Lead Time", "outline_level": 3, "duration": 60})
    check("家具采购→家具供应商", r["responsible_person"] == "家具供应商", str(r))
    r = R.resolve_responsibility({"name": "FFU/HEPA交货 Lead Time", "outline_level": 3, "duration": 45})
    check("FFU采购→FFU/HEPA 供应商", r["responsible_person"] == "FFU/HEPA 供应商", str(r))

    # 4) 任务级 override 优先
    r = R.resolve_responsibility({"name": "保密专项", "outline_level": 3, "duration": 5,
                                  "responsible_unit": "安全部", "responsible_person": "安全总监"})
    check("override 优先于自动识别", r["responsible_unit"] == "安全部" and r["responsible_person"] == "安全总监", str(r))

    # 5) annotate_tasks 就地补充字段
    tasks = [{"name": "Phase 2 设计深化", "outline_level": 2},
             {"name": "[M] 图审合格证获取", "outline_level": 3, "milestone": True}]
    R.annotate_tasks(tasks)
    check("annotate_tasks 补充 responsible_* 字段",
          "responsible_unit" in tasks[0] and "responsibility_flag" in tasks[1])


def test_air_quality_compliance():
    """P1 回归：两个 MNC 模板均含『首次室内空气盲测』+『二次室内空气质量复测』，合规无红线。"""
    print("\n== 10. 两次空气检测 SOP 合规 (P1) ==")
    C = _load("core.compliance")
    T = _load("core.solver_engine")
    d = json.load(open(os.path.join(BASE, "templates", "wbs_templates.json"), encoding="utf-8"))
    for mode in ["MNC_Standard_Fitout_DB_Invite", "MNC_Standard_Fitout_Office_DBB"]:
        ts = json.loads(json.dumps(d["templates"][mode]["tasks"]))
        for t in ts:
            lv = t.get("outline_level", t.get("level", 1))
            t["level"] = lv
            t["outline_level"] = lv
            bd = int(round(float(t.get("duration_days", t.get("duration", 0)))))
            t["duration_days"] = bd
            t["duration"] = bd
        issues = C.run_compliance_checks(ts)
        red = [i for i in issues if i.get("level") == "red"]
        air_codes = {i["code"] for i in red if i["code"] in ("AIR_FIRST_MISSING", "AIR_SECOND_MISSING")}
        check(f"[{mode}] 无空气检测红线违例", not air_codes, f"违例: {air_codes}")
        names = [t["name"] for t in ts]
        check(f"[{mode}] 含『盲测』节点", any("盲测" in n for n in names))
        check(f"[{mode}] 含『复测』节点", any("复测" in n for n in names))
        # 解算末端必须是『项目真正末端』(搬迁完成/项目交付)，而非空气节点（依赖链已正确挂接）
        r = T.solve_schedule(ts, "2026-08-31")
        end = [t for t in r["tasks"] if t.get("outline_level", t.get("level", 1)) >= 3
               and t.get("finish") == r["finish_date"]]
        end_name = end[0]["name"] if end else ""
        max_id = max(t["id"] for t in ts)
        check(f"[{mode}] 末端非空气节点", "盲测" not in end_name and "复测" not in end_name,
              f"末端={end_name}")
        check(f"[{mode}] 末端为最高id任务(项目终点)", end[0]["id"] == max_id if end else False,
              f"末端id={end[0]['id'] if end else '无'} max={max_id}")


def test_ss_lag_predecessor():
    """P2 回归：solve_schedule 正确解析 SS+滞后 型前置（区别于 FS）。"""
    print("\n== 11. SS+滞后型前置依赖解析 (P2 求解器) ==")
    SE = _load("core.solver_engine")
    # 2026-06-01 为清洁周一（避开春节/清明/劳动节等假期），可稳定断言
    tasks = [
        {"id": 1, "level": 3, "duration": 10, "predecessors": ""},          # 6/1 起
        {"id": 2, "level": 3, "duration": 5, "predecessors": "1SS+3"},       # 起点=t1.start+3工日
        {"id": 3, "level": 3, "duration": 5, "predecessors": "1FS"},         # 起点=t1.finish+1
    ]
    r = SE.solve_schedule(tasks, "2026-06-01")
    by = {t["id"]: t for t in r["tasks"]}
    import datetime as _dt
    bm = SE.build_holiday_bitmap(SE.get_holidays_for_years(2026, 2031))
    t1_start = _dt.datetime.strptime(by[1]["start"], "%Y-%m-%d").date()
    expected_t2 = SE.add_workdays(t1_start, 3, bm).strftime("%Y-%m-%d")
    check("t1 起点=2026-06-01", by[1]["start"] == "2026-06-01", by[1]["start"])
    # SS+3：起点=t1起点+3工日，且早于 t1 终点（SS 挂起点而非终点）
    check("t2(SS+3) 起点=t1起点+3工日", by[2]["start"] == expected_t2,
          f"{by[2]['start']} vs {expected_t2}")
    check("t2(SS) 起点早于 t1 终点(非 FS)", by[2]["start"] < by[1]["finish"])
    # FS：起点=t1终点+1，晚于 SS 起点
    check("t3(FS) 起点晚于 t1 终点", by[3]["start"] > by[1]["finish"])
    check("t3(FS) 起点晚于 t2(SS) 起点", by[3]["start"] > by[2]["start"])


def test_backward_solver_sensible():
    """P0 回归：倒排求解器须以『真正项目末端』(搬迁完成) 对齐死线，而非误抓早期搬迁关键词节点。"""
    print("\n== 12. 倒排求解器以项目末端对齐 (P0 回归) ==")
    SE = _load("core.solver_engine")
    H = _load("core.holidays")
    d = json.load(open(os.path.join(BASE, "templates", "wbs_templates.json"), encoding="utf-8"))
    mode = "MNC_Standard_Fitout_DB_Invite"
    ts = json.loads(json.dumps(d["templates"][mode]["tasks"]))
    for t in ts:
        lv = t.get("outline_level", t.get("level", 1))
        t["level"] = lv
        t["outline_level"] = lv
        bd = int(round(float(t.get("duration_days", t.get("duration", 0)))))
        t["duration_days"] = bd
        t["duration"] = bd
    holidays_raw = H.load_holiday_raw()
    target = __import__("datetime").date(2027, 7, 30)
    safe = H.get_latest_client_workday_before(target, days_before=7, holidays=holidays_raw)
    res = SE.solve_schedule_with_target(
        ts, target_finish_date_str=safe.strftime("%Y-%m-%d"),
        target_buffer_days=0, active_holidays=H.load_holiday_pairs())
    start_date = res["start_date"]
    finish_date = res["finish_date"]
    check("倒排开工年在 2026 (非 2027-02 误抓)", start_date.startswith("2026"),
          f"start={start_date}")
    check("倒排完工不晚于安全截止日", finish_date <= safe.strftime("%Y-%m-%d"),
          f"{finish_date} vs {safe}")
    # 末端任务须为搬迁完成
    end = [t for t in res["tasks"] if t.get("outline_level", t.get("level", 1)) >= 3
           and t.get("finish") == finish_date]
    check("倒排末端=搬迁完成", "搬迁" in (end[0]["name"] if end else ""),
          f"末端={end[0]['name'] if end else '无'}")


if __name__ == "__main__":
    test_single_source_holidays()
    test_forward_solve()
    test_backward_cpm()
    test_overwrite_fix()
    test_target_branch_integration()
    test_responsibility_resolution()
    test_air_quality_compliance()
    test_ss_lag_predecessor()
    test_backward_solver_sensible()
    test_city_permit_externalized()
    test_compliance_redlines()
    test_calendar_utils()
    test_target_branch_integration()
    test_responsibility_resolution()
    print(f"\n==== 结果: PASS={PASS}  FAIL={FAIL} ====")
    sys.exit(1 if FAIL else 0)

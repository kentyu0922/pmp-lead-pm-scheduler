# -*- coding: utf-8 -*-
"""
verify_7day_e2e.py — 端到端验证"施工7天日历"在真实 .mpp 生成后确实排周末。
通过实际 import_tasks(->build_mpp) 生成文件，再用 MSProjectSession 重新打开断言。
"""
import os, json, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.msp_automation import import_tasks, CONSTRUCTION_CAL_NAME
from core.msp_session import MSProjectSession, read_local_date, read_field_str

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output_mpp", "Verify7Day.mpp")

# 构造任务：项目起点周五 2027-01-01
#  - 任务3: work_weekend=True -> 走施工7天日历（周末应计入）
#  - 任务4: 普通任务(无 weekend) -> 走标准5天日历（周末应跳过，作对照）
tasks = [
    {"id": 1, "name": "Phase 1 施工阶段", "outline_level": 1, "milestone": False, "duration": 0},
    {"id": 2, "name": "主体施工", "outline_level": 2, "duration": 0},
    {"id": 3, "name": "跨周末施工实测", "outline_level": 3, "duration": 3, "work_weekend": True, "predecessors": ""},
    {"id": 4, "name": "对照标准5天任务", "outline_level": 3, "duration": 3, "work_weekend": False, "predecessors": ""},
]
json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output_mpp", "_verify_tasks.json")
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(tasks, f, ensure_ascii=False, indent=2)

print("[verify] 1) 调用 import_tasks 生成 .mpp (项目起点=周五 2027-01-01) ...")
path = import_tasks(json_path, OUT, project_title="7天日历验证", project_start="2027-01-01")
print(f"        生成: {path} ({os.path.getsize(path):,} 字节)")

print("[verify] 2) 重新打开并断言...")
ok = True
with MSProjectSession() as sess:
    project = sess.open(path)
    # 断言 A: 施工7天日历 周末 Working=True
    try:
        cal = project.BaseCalendars(CONSTRUCTION_CAL_NAME)
        sun = cal.WeekDays(1).Working
        sat = cal.WeekDays(7).Working
        print(f"        施工7天日历 周日(1).Working={sun}  周六(7).Working={sat}")
        if not (sun and sat):
            ok = False
            print("        [FAIL] 周末未设为工作日!")
        else:
            print("        [PASS] 周末已设为工作日 ✓")
    except Exception as e:
        ok = False
        print(f"        [ERR] 读取施工日历失败: {e}")

    # 断言 B: 对照证明 —— 跨周末任务(7天)应早于对照任务(5天)整整一个周末
    try:
        tk3 = project.Tasks(3)  # 跨周末 (work_weekend)
        tk4 = project.Tasks(4)  # 对照 (标准5天)
        f3 = read_local_date(tk3.Finish)
        f4 = read_local_date(tk4.Finish)
        d3 = read_field_str(sess.app, tk3, "Duration")
        d4 = read_field_str(sess.app, tk4, "Duration")
        print(f"        跨周末任务(7天): Start={read_local_date(tk3.Start)} Finish={f3} {d3}")
        print(f"        对照任务(5天):   Start={read_local_date(tk4.Start)} Finish={f4} {d4}")
        # 7天日历: 周五起3工作日 => 五六日 => 周一 1/4
        # 5天日历: 周五起3工作日 => 五六(休)日(休)一二 => 周二 1/5
        if f3 == "2027-01-04" and f4 == "2027-01-05":
            print("        [PASS] 跨周末任务周一完、对照任务周二完 — 差出整个周末，7天日历铁证生效 ✓")
        elif f3 < f4:
            print(f"        [PASS] 跨周末任务早于对照任务({f3} < {f4})，7天日历生效 ✓")
        else:
            ok = False
            print(f"        [FAIL] 未观察到周末差异: 跨周末={f3} 对照={f4}")
    except Exception as e:
        ok = False
        print(f"        [ERR] 读取对照任务失败: {e}")

print("\n[verify] 结果:", "ALL PASS ✅" if ok else "FAILED ❌")
sys.exit(0 if ok else 1)

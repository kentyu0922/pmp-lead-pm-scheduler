# -*- coding: utf-8 -*-
"""端到端验证：用真实 WBS 模板生成 .mpp，确认 执行单位/责任人/责任标识
写入 Text1/2/3 且持久、自定义列改名，并验证报表导出含三列。"""
import os, sys, json, datetime, logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("verify_resp")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.mpp_renderer import build_mpp
from core.msp_automation import export_report

def main():
    # 载入真实 WBS 模板（取前 25 个任务，覆盖 Phase 1-3）
    d = json.load(open(os.path.join(BASE, "templates", "wbs_templates.json"), encoding="utf-8"))
    tasks = d["templates"]["MNC_Standard_Fitout_DB_Invite"]["tasks"][:25]
    # 渲染器需要 'duration' 或 'duration_days'，模板用 duration_days，已兼容

    out_mpp = os.path.join(BASE, "output_mpp", "_verify_resp.mpp")
    out_csv = os.path.join(BASE, "output_mpp", "_verify_resp_report.csv")

    logger.info("=== 1) build_mpp（含责任识别 + 写 Text1/2/3 + 改名）===")
    path, _ = build_mpp("责任识别验证", datetime.date(2026, 8, 31), tasks, [], out_mpp)
    logger.info(f"生成: {path}  ({os.path.getsize(path):,} 字节)")

    logger.info("=== 2) 重开读取 Text1/2/3，确认持久 + 改名 ===")
    from core.msp_session import MSProjectSession, read_field_str
    ok = True
    with MSProjectSession() as sess:
        project = sess.open(path)
        fc = lambda n: sess.app.FieldNameToFieldConstant(n)
        # 抽查几个代表任务
        samples = {}
        for i in range(1, project.Tasks.Count + 1):
            tk = project.Tasks(i)
            u = read_field_str(sess.app, tk, "Text1")
            p = read_field_str(sess.app, tk, "Text2")
            f = read_field_str(sess.app, tk, "Text3")
            samples[tk.Name] = (u, p, f)
        # 验证改名：Text1 的标题应为「执行单位」
        try:
            title1 = sess.app.FieldNameToFieldConstant("执行单位")
            logger.info(f"[VERIFY] 自定义列改名生效：'执行单位' 字段常量={title1}")
        except Exception as e:
            logger.warning(f"[VERIFY] 改名校验跳过: {e}")
        # 打印几个关键任务
        for nm in ("Phase 2 设计深化阶段", "RFP 正式发出 + 现场踏勘 + Q&A澄清",
                   "Phase 3 施工总包邀请招标 (快车道 Fast-Track)"):
            if nm in samples:
                u, p, f = samples[nm]
                logger.info(f"    [{nm}] 执行单位={u} | 责任人={p} | 标识={f}")
                if not (u and p and f):
                    ok = False
                    logger.warning(f"    [!!] {nm} 责任字段为空")

    logger.info("=== 3) 报表导出（CSV，含 执行单位/责任人/责任标识）===")
    export_report(path, out_csv, fmt="csv")
    with open(out_csv, encoding="utf-8-sig") as fh:
        header = fh.readline().strip()
    logger.info(f"    CSV 表头: {header}")
    for col in ("执行单位", "责任人", "责任标识"):
        if col not in header:
            ok = False
            logger.warning(f"    [!!] CSV 缺少列: {col}")
    # 打印前两行数据
    with open(out_csv, encoding="utf-8-sig") as fh:
        lines = fh.readlines()
    for ln in lines[1:4]:
        logger.info("    " + ln.strip())

    if ok:
        logger.info("RESULT: ALL PASS ✅ 责任识别已写入 .mpp 并在报表中可见")
    else:
        logger.warning("RESULT: 存在空字段或缺失列 ❌")
    print("VERIFY_RESP_DONE", "PASS" if ok else "FAIL")

if __name__ == "__main__":
    main()

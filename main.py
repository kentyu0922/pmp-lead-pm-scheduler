# -*- coding: utf-8 -*-
import json
import os
import sys
import argparse
import datetime
import logging

# 设置日志系统
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("main")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.solver_engine import solve_schedule_with_target, solve_schedule, compute_cpm_metrics
from exporters import build_mpp, export_pdf, generate_pptx_milestones
from experts.permit_expert import query_city_permit_rule, calc_tender_duration
from core.sub_wbs_splicer import splice_sub_modules
from core import holidays as _holidays
from core import compliance as _compliance
# 化繁为简：业务逻辑已提取到独立模块
from core.calibration import calibrate_durations, validate_complex_construction
from core.task_utils import clean_procurement_terminology, renumber_tasks_contiguously, fold_exempt_construction_permit
# v4.2 pilot: quantity → productivity → duration for ONE activity type (suspended_ceiling); templates untouched
from core.productivity import apply_productivity_durations, tag_legacy_pilot_tasks, productivity_summary
# Dependency Engine v0: sectional SS+lag rule table (config/dependency_rules.json); non-sectional projects keep template FS
from core.dependency_engine import apply_dependency_rules, dependency_report, validate_dependency_graph

def main() -> None:
    parser = argparse.ArgumentParser(description="PMP Lead PM Scheduler - 主总调度器 (Audit-Hardened Master Orchestrator)")
    parser.add_argument("--city", type=str, required=True, help="项目所在城市，如 '上海', '苏州'")
    parser.add_argument("--area", type=int, required=True, help="项目面积(平方米)")
    parser.add_argument("--cost", type=int, default=100, help="项目预估造价(万元)，默认100万")
    # ③ 招采形态 (DB=D&B / DBB) 与 ④ 招标方式 (invite=邀请 / public=公开) 为正交两维
    parser.add_argument("--delivery", type=str, choices=["DB", "DBB"], help="招采形态: DB(D&B 设计施工一体化) / DBB(设计-招标-施工)")
    parser.add_argument("--bidding", type=str, choices=["invite", "public"], help="招标方式: invite(邀请招标) / public(公开招标)")
    parser.add_argument("--mode", type=str, help="(兼容旧版) 直接指定模板键, 如 MNC_Standard_Fitout_DB_Invite")
    parser.add_argument("--target_date", type=str, help="硬性要求的项目交付搬迁日 (YYYY-MM-DD)")
    parser.add_argument("--start_date", type=str, help="项目启动 Kick-off 日期 (YYYY-MM-DD)")
    parser.add_argument("--project_name", type=str, default="新建办公空间工装项目", help="项目名称")
    parser.add_argument("--addons", type=str, default="", help="附加的 Sub-WBS 模块名 (如 Datacenter_LoadBank_Module)")
    parser.add_argument("--no_mpp", action="store_true", default=False, help="跳过物理 MS Project COM 渲染，仅生成 CPM 解算数据与 PDF/PPTX 报表")
    parser.add_argument("--output", type=str, default="Output_Schedule.mpp", help="输出 MPP 文件名称")
    parser.add_argument("--productivity_pilot", action="store_true", default=False,
                        help="[试点] 天花吊顶(suspended_ceiling)工期改走 工程量→生产率→工期 公式路径；其余节点仍用模板硬编码工期")
    parser.add_argument("--ceiling_area", type=float, default=None,
                        help="[试点] 实测吊顶工程量(㎡)。缺省按 --area × 净顶面积比 推导(置信度降级)")
    parser.add_argument("--sectional", type=str, choices=["auto", "on", "off"], default="auto",
                        help="[依赖引擎v0] 分区穿插 SS+lag 规则: auto=按 config/dependency_rules.json 面积/工作面阈值判定(默认); on=强制启用; off=保持模板 FS")
    parser.add_argument("--workfronts", type=int, default=None,
                        help="[依赖引擎v0] 显式分区/工作面数量。缺省按 --area ÷ 单工作面面积 推导；同时决定 SS 滞后 = ceil(前置工期 ÷ 工作面数)")

    # ③ x ④ -> 4 套模板键映射
    TEMPLATE_MAP = {
        ("DB", "invite"):  "MNC_Standard_Fitout_DB_Invite",
        ("DB", "public"):  "MNC_Standard_Fitout_DB_Public",
        ("DBB", "invite"): "MNC_Standard_Fitout_DBB_Invite",
        ("DBB", "public"): "MNC_Standard_Fitout_Office_DBB",
    }
    
    args = parser.parse_args()

    # ---- ③ x ④ 解析为模板键 + 招标方式 ----
    if args.mode:
        # 兼容旧版: 直接给模板键
        mode_key = args.mode
        bidding_val = "public" if "Public" in args.mode else "invite"
        delivery_val = "DBB" if "DBB" in args.mode else "DB"
    else:
        # 缺省交互询问 (仅 TTY); 非交互则报错退出, 不伪造排程
        if not args.delivery or not args.bidding:
            try:
                if sys.stdin.isatty():
                    if not args.delivery:
                        args.delivery = input("招采形态 (D&B 输入 DB, DBB 输入 DBB): ").strip().upper()
                    if not args.bidding:
                        args.bidding = input("招标方式 (邀请 invite / 公开 public): ").strip().lower()
                else:
                    raise EOFError
            except EOFError:
                logger.error("缺少 --delivery / --bidding，请显式指定招采形态与招标方式")
                raise SystemExit("用法: --delivery DB|DBB --bidding invite|public")
        if args.delivery not in ("DB", "DBB"):
            raise SystemExit(f"无效招采形态: {args.delivery} (应为 DB 或 DBB)")
        if args.bidding not in ("invite", "public"):
            raise SystemExit(f"无效招标方式: {args.bidding} (应为 invite 或 public)")
        mode_key = TEMPLATE_MAP[(args.delivery, args.bidding)]
        delivery_val, bidding_val = args.delivery, args.bidding

    logger.info(f"\n[{args.project_name}] 核心调度引擎全盘审计启动...")

    # ---- ⑤ 排期锚点硬化: 必须给 start_date 或 target_date ----
    if not args.start_date and not args.target_date:
        try:
            if sys.stdin.isatty():
                ans = input("未提供排程锚点。选择: 1=正排(输入开工日 YYYY-MM-DD) 2=倒排(输入目标搬迁日 YYYY-MM-DD): ").strip()
                if ans == "1":
                    args.start_date = input("开工日 (YYYY-MM-DD): ").strip()
                elif ans == "2":
                    args.target_date = input("目标搬迁日 (YYYY-MM-DD): ").strip()
                else:
                    raise SystemExit("无效选择，请输入 1 或 2")
            else:
                raise EOFError
        except EOFError:
            logger.error("缺少 --start_date / --target_date，请至少提供一个排程锚点 (拒绝生成零日期失真排程)")
            raise SystemExit("用法: --start_date YYYY-MM-DD 或 --target_date YYYY-MM-DD")
    logger.info(f"==================================================")
    
    # 1. 呼叫合规专家 (Compliance Expert)
    logger.info("Step 1: 呼叫政务合规专家提取属地法规与招采限制...")
    permit_info = query_city_permit_rule(args.city, area_sqm=args.area, cost_10k_rmb=args.cost)
    tender_info = calc_tender_duration(bidding=bidding_val, cost_10k_rmb=args.cost)
    
    logger.info(f"  -> 城市报建规则 [{args.city}]: 图审至少 {permit_info.get('review_days_min', 7)}天, 许可至少 {permit_info.get('permit_days_min', 5)}天")
    logger.info(f"  -> 招采规程 [{tender_info['procurement_mode']}]: 建议周期 {tender_info['total_procurement_days']} 天")

    # 2. 呼叫工序专家 (Process Expert) - 加载 WBS
    logger.info(f"Step 2: 正在呼叫工序流水线专家，加载 [{mode_key}] 模版 (delivery={delivery_val}, bidding={bidding_val})...")
    template_path = os.path.join(BASE_DIR, "templates", "wbs_templates.json")
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template_data = json.load(f)
            tasks = template_data["templates"][mode_key]["tasks"]
            template_base_area = template_data["templates"][mode_key].get("base_area", 1000)
            logger.info(f"  -> 成功加载 100% 完整标准 WBS 节点树 (共 {len(tasks)} 节点)")
    except Exception as e:
        logger.error(f"ERROR: 读取 WBS 模版失败: {e}")
        return

    # 3. 动态拼接 Sub-WBS 模块
    if args.addons:
        logger.info(f"Step 2.5: 正在挂载 Sub-WBS 特种模块 [{args.addons}]...")
        sub_path = os.path.join(BASE_DIR, "templates", "sub_wbs_modules.json")
        tasks = splice_sub_modules(tasks, args.addons, sub_path)

    # 4. 执行严谨的【PM 业务领域 SOP 下限断言与面积非线性缩放】
    logger.info(f"Step 2.8: 执行 PMP 业务常识断言与工期二次校准...")
    tasks = calibrate_durations(tasks, permit_info, args.area, template_base_area, args.addons, cost_10k_rmb=args.cost, log=logger)
    validate_complex_construction(tasks, args.area, args.addons, log=logger)

    # 4.5 工程量→生产率→工期 试点（activity_type 开关）。默认关闭：模板节点无 activity_type，
    #     apply_productivity_durations 为空操作，输出与 v4.1 完全一致。开启后仅天花吊顶节点改走公式。
    if args.productivity_pilot:
        logger.info("Step 2.9: [试点] 工程量→生产率→工期 (suspended_ceiling)...")
        tagged = tag_legacy_pilot_tasks(tasks, args.area, quantity_override=args.ceiling_area, log=logger)
        if not tagged:
            logger.warning("  -> [productivity] 模板中未命中任何天花吊顶节点，试点未生效（模板工期照旧）。")
    tasks = apply_productivity_durations(tasks, log=logger)

    if tasks:
        tasks[0]["name"] = args.project_name

    # v4.1: 消费 is_exempt —— 免办则折叠政府施工许可阶段（保留物业送审）
    if permit_info.get("is_exempt"):
        logger.info(
            f"  -> [免办判定] 面积/造价低于属地门槛（{permit_info.get('exempt_desc', '')}），"
            f"折叠《施工许可证》政府节点；仍保留物业审查与消防相关路径。"
        )
        tasks = fold_exempt_construction_permit(tasks, True, log=logger)
    else:
        logger.info("  -> [免办判定] 需办理施工许可（或未计算豁免），保留许可阶段节点。")

    tasks = clean_procurement_terminology(tasks, mode_key, log=logger)
    tasks = renumber_tasks_contiguously(tasks)

    # 2.95 依赖引擎 v0：分区(多工作面)项目按规则表把 隔墙/机电/天花 工序对由 FS 改为 SS+lag；
    #      非分区项目为空操作（模板 FS 逻辑与 v4.1 完全一致）。在 renumber 之后执行，id 已为最终值。
    logger.info(f"Step 2.95: 呼叫依赖引擎 v0（分区 SS+lag 规则表, --sectional {args.sectional}）...")
    if args.workfronts is not None and args.workfronts < 1:
        raise SystemExit(f"无效工作面数: {args.workfronts} (应 >= 1)")
    dep_report = apply_dependency_rules(tasks, args.area, mode=args.sectional, workfronts=args.workfronts, log=logger)
    graph_issues = validate_dependency_graph(tasks)
    for gi in graph_issues:
        logger.error(f"  -> [依赖图审计][{gi['code']}] {gi['message']}")
    if any(gi["code"] == "PRED_CYCLE" for gi in graph_issues):
        raise SystemExit("DEPENDENCY_GRAPH_INVALID: cycle in predecessor network")

    # v3 单源：config/holidays.json 一次读取，求解器与 MPP 日历共用同一份
    holidays_raw = _holidays.load_holiday_raw()       # [{"name","start","finish"}] -> MPP 日历 Exceptions
    holidays_pairs = _holidays.load_holiday_pairs()   # [(start,end)] -> 求解器 is_workday

    logger.info("Step 3: 呼叫双擎 CPM 解算器进行精准算账...")
    start_date_str = ""
    tasks_solved = tasks
    finish_date = ""

    if args.start_date:
        start_date_str = args.start_date
        logger.info(f"  -> 采用指定开工日正排模式，起点 Kick-off: {start_date_str}")
        solve_res = solve_schedule(tasks, start_date_str, custom_holidays=holidays_pairs)
        tasks_solved = solve_res["tasks"]
        finish_date = solve_res["finish_date"]
        logger.info(f"  -> 推演得出真实完工交付日为: {finish_date}")
        
        if args.target_date:
            target_dt = datetime.datetime.strptime(args.target_date, "%Y-%m-%d").date()
            finish_dt = datetime.datetime.strptime(finish_date, "%Y-%m-%d").date()
            if finish_dt > target_dt:
                days_late = (finish_dt - target_dt).days
                logger.error(f"[PM排程审计断言] 排程失败！正推完工日 {finish_date} 晚于硬性目标死线 {args.target_date} 达 {days_late} 天！")
                raise AssertionError(f"完工日 {finish_date} 超出死线 {args.target_date}，拒绝生成失真排程！")
    elif args.target_date:
        logger.info(f"  -> 采用倒排模式，目标死线: {args.target_date}")
        from core.holidays import get_latest_client_workday_before
        target_dt = datetime.datetime.strptime(args.target_date, "%Y-%m-%d").date()
        safe_finish_date = get_latest_client_workday_before(target_dt, days_before=7, holidays=holidays_raw)
        solve_res = solve_schedule_with_target(tasks, target_finish_date_str=safe_finish_date.strftime("%Y-%m-%d"), target_buffer_days=0, active_holidays=holidays_pairs)
        start_date_str = solve_res["start_date"]
        tasks_solved = solve_res["tasks"]
        finish_date = solve_res["finish_date"]

        if args.target_date:
            target_dt = datetime.datetime.strptime(args.target_date, "%Y-%m-%d").date()
            finish_dt = datetime.datetime.strptime(finish_date, "%Y-%m-%d").date()
            days_early = (target_dt - finish_dt).days
            if days_early > 90:
                logger.warning(f"[PM商业常识断言] 工期失真预警！正推完工日提前了 {days_early} 天（超过3个月！）。")

    # 真实项目终点 = 所有任务最晚 finish（含搬迁/客户入驻尾段），与 MPP 实测对齐。
    # 倒排路径 solve_schedule_with_target 返回的是搬迁锚点日，需以任务最晚finish为准，
    # 否则日志“项目终点”比 MPP 实测少算搬迁尾段（约7天），造成虚假的求解器/MPP 漂移。
    _true_finish = max((t.get("finish") for t in tasks_solved if t.get("finish")), default=finish_date)
    if _true_finish != finish_date:
        logger.info(f"  -> [校准] 项目终点由锚点日 {finish_date} 修正为任务最晚finish: {_true_finish}")
    finish_date = _true_finish

    # v3: 离线关键路径估算（MPP 仍为最终权威，此处仅作预览/审计输出）
    tasks_solved = compute_cpm_metrics(tasks_solved, project_end=finish_date)
    n_crit = sum(1 for t in tasks_solved if t.get("critical"))
    logger.info(f"  -> 离线关键路径节点(估算): {n_crit} 个；项目终点: {finish_date}")

    # v3: 合规红线代码化审计（非阻塞；error 级由调用方决定是否阻断）
    logger.info("Step 3.6: 呼叫合规红线审计引擎...")
    compliance_issues = _compliance.run_compliance_checks(tasks_solved, holiday_raw=holidays_raw)
    _compliance.log_compliance(compliance_issues)
    n_err = sum(1 for it in compliance_issues if it.get("level") == "error")
    if n_err:
        logger.error(f"[合规审计] 发现 {n_err} 项强制红线违例，拒绝交付失真排程。请复核 WBS 模板后重跑。")
        raise SystemExit(f"COMPLIANCE_BLOCKED: {n_err} error-level issues")

    output_path = os.path.join(BASE_DIR, "output_mpp", args.output)
    proj_start_dt = datetime.datetime.strptime(start_date_str, "%Y-%m-%d") if start_date_str else datetime.date.today()

    # 试点可解释字段落盘（仅当存在公式路径节点）：<output>_productivity.json
    prod_rows = productivity_summary(tasks_solved)
    if prod_rows:
        prod_out = os.path.splitext(output_path)[0] + "_productivity.json"
        os.makedirs(os.path.dirname(prod_out), exist_ok=True)
        with open(prod_out, "w", encoding="utf-8") as f:
            json.dump({"project_name": args.project_name, "area_sqm": args.area,
                       "start_date": start_date_str, "finish_date": finish_date,
                       "tasks": prod_rows}, f, ensure_ascii=False, indent=2)
        for r in prod_rows:
            logger.info(
                f"  -> [productivity][explain] #{r['id']} {r['name']}: quantity={r['quantity']:g}{r['unit']} "
                f"({r['quantity_source']}), rate={r['productivity_rate']:g} {r['productivity_unit']}, crew={r['crew_size']}, "
                f"factors={r['factor_labels']} (×{r['factor_product']:g}), calculated={r['calculated_duration']:g}d, "
                f"final={r['final_duration']}d (template {r['template_duration']}d), confidence={r['confidence']}, "
                f"{r['start']}→{r['finish']}, critical={r['critical']}"
            )
        logger.info(f"  -> [productivity] 可解释字段已落盘: {prod_out}")

    # 依赖引擎可解释字段落盘（仅当有规则命中）：<output>_dependencies.json
    dep_rows = dependency_report(tasks_solved)
    if dep_rows:
        dep_out = os.path.splitext(output_path)[0] + "_dependencies.json"
        os.makedirs(os.path.dirname(dep_out), exist_ok=True)
        with open(dep_out, "w", encoding="utf-8") as f:
            json.dump({"project_name": args.project_name, "area_sqm": args.area,
                       "start_date": start_date_str, "finish_date": finish_date,
                       "decision": dep_report["decision"], "skipped": dep_report["skipped"],
                       "tasks": dep_rows}, f, ensure_ascii=False, indent=2)
        for r in dep_rows:
            fired = "; ".join(
                f"{x['rule_id']}: {x['predecessor_id']}{x['relationship']}+{x['lag_days']} ({x['lag_basis']})"
                for x in r["rules"])
            logger.info(
                f"  -> [dependency][explain] #{r['id']} {r['name']}: '{r['predecessors_before_rules']}' → '{r['predecessors']}' "
                f"[{fired}] {r['start']}→{r['finish']}, critical={r['critical']}"
            )
        logger.info(f"  -> [dependency] 可解释字段已落盘: {dep_out}")
    else:
        logger.info(f"  -> [dependency] 未命中分区规则（sectional={dep_report['decision']['sectional']}），模板 FS 逻辑保持不变。")

    mpp_written = False
    if args.no_mpp:
        logger.info("Step 4: [已指定 --no_mpp] 跳过物理 MS Project COM 渲染，直接进入 PDF/PPTX 报表导出...")
    else:
        logger.info("Step 4: 呼叫物理 COM 引擎渲染 MS Project...")
        try:
            build_mpp(
                project_title=args.project_name,
                project_start=proj_start_dt,
                tasks=tasks_solved,
                calendar_exceptions=holidays_raw,
                output_mpp_path=output_path
            )
            mpp_written = os.path.exists(output_path)
        except Exception as mpp_err:
            logger.warning(f"  -> [MPP COM 渲染] 跳过或COM不可用: {mpp_err}")

    # 自动同步导出 A3 打印级任务明细甘特图/表格报表 (.pdf)
    try:
        from export_pdf import export_pdf
        pdf_out_path = os.path.splitext(output_path)[0] + ".pdf"
        if os.path.exists(output_path):
            export_pdf(mpp_or_tasks=output_path, out_path=pdf_out_path, format="table", title=args.project_name)
        else:
            export_pdf(mpp_or_tasks=tasks_solved, out_path=pdf_out_path, format="table", title=args.project_name)
        logger.info(f"  -> [PDF 报表] 同步生成任务排期报表: {pdf_out_path}")
    except Exception as ex:
        logger.warning(f"  -> [PDF 报表] 自动导出跳过: {ex}")

    # 自动同步导出高层汇报级 PPTX 演示文稿 (Key Milestones Timeline)
    try:
        from export_pptx import generate_pptx_milestones
        pptx_out_path = os.path.splitext(output_path)[0] + "_Milestones.pptx"
        generate_pptx_milestones(
            project_title=args.project_name,
            project_meta={"city": args.city, "area": args.area, "cost": args.cost, "delivery": delivery_val, "bidding": bidding_val},
            tasks=tasks_solved,
            output_pptx_path=pptx_out_path
        )
        logger.info(f"  -> [PPTX 演示] 同步生成高层汇报文稿: {pptx_out_path}")
    except Exception as ex:
        logger.warning(f"  -> [PPTX 演示] 自动导出跳过: {ex}")
    
    logger.info(f"==================================================")
    if mpp_written:
        logger.info(f"SUCCESS: 调度完成！物理文件已通过 100% 审计落地: {output_path}")
    else:
        # SKILL.md: never claim an .mpp was written when it was not (--no_mpp or COM unavailable)
        logger.info(f"SUCCESS: 调度完成！CPM 解算与合规审计通过；未生成 .mpp（--no_mpp 或无 MS Project COM），交付物见 {os.path.dirname(output_path)} 下的 .pdf/.pptx")

if __name__ == "__main__":
    main()

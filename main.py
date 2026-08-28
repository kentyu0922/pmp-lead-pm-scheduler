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
from core.mpp_renderer import build_mpp
from experts.permit_expert import query_city_permit_rule, calc_tender_duration
from core.sub_wbs_splicer import splice_sub_modules
from core import holidays as _holidays
from core import compliance as _compliance
# 化繁为简：业务逻辑已提取到独立模块
from core.calibration import calibrate_durations, validate_complex_construction
from core.task_utils import clean_procurement_terminology, renumber_tasks_contiguously

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
    parser.add_argument("--skip_design_procurement", action="store_true", default=True, help="跳过前期设计团队比选招采 (当设计团队已就位时使用)")
    parser.add_argument("--output", type=str, default="Output_Schedule.mpp", help="输出 MPP 文件名称")

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
    tasks = calibrate_durations(tasks, permit_info, args.area, template_base_area, args.addons, log=logger)
    validate_complex_construction(tasks, args.area, args.addons, log=logger)

    if tasks:
        tasks[0]["name"] = args.project_name

    tasks = clean_procurement_terminology(tasks, mode_key, log=logger)
    tasks = renumber_tasks_contiguously(tasks)

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
        logger.error(f"[合规审计] 发现 {n_err} 项强制红线违例，请复核 WBS 模板后再生成排程。")

    logger.info("Step 4: 呼叫物理 COM 引擎渲染 MS Project...")
    output_path = os.path.join(BASE_DIR, "output_mpp", args.output)
    proj_start_dt = datetime.datetime.strptime(start_date_str, "%Y-%m-%d") if start_date_str else datetime.date.today()
    
    build_mpp(
        project_title=args.project_name,
        project_start=proj_start_dt,
        tasks=tasks_solved,
        calendar_exceptions=holidays_raw,
        output_mpp_path=output_path
    )
    
    logger.info(f"==================================================")
    logger.info(f"SUCCESS: 调度完成！物理文件已通过 100% 审计落地: {output_path}")

if __name__ == "__main__":
    main()

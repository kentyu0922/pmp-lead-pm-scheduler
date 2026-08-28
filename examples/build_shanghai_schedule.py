# -*- coding: utf-8 -*-
"""
上海徐汇区 1000㎡ D&B 办公工装项目 —— 进度计划构建器
依据用户给定里程碑日期，构建任务/依赖/日历，经 core.mpp_renderer.build_mpp 黄金出口落盘 .mpp / .xml

V3 深度修正 (2026-08-07):
  1) 整数工期刚性保证(渲染器强制取整并告警)；移除"项目启动"冗余表述(PM里程碑改名"PM 到任")、移除早期阶段
     "RFP发出"与"大楼物业装修申请"节点(后者并入 Phase 3 物业装修图纸送审)，前后逻辑与招采联动一致。
  2) D&B 招采工期基于行业调研重估:行业授标子周期通常 8-12 周,邀请招标+预审短名单加速端约 6 周(≈31 工作日);
     三轮子任务工期据此扩展(R1=10d, R2=13d, R3=8d)。因 2026 中秋(9/25-9/27)+国庆(10/1-10/7)法定假日卡停评标,
     招采链自然落点为 2026-10-22(晚于用户给定 10-16 共 4 个日历日),经用户确认"接受顺延后的真实日期",不做伪排程压缩。
     其下游"取得施工许可证"随之落 2026-12-03(用户给定 12-01)。
  3) 家具采购前置依赖挂钩"平面图确认与业主签字"(总包画图节点 id 32,经用户确认),
     满足"总包进场并完成平面布局图纸后方可启动家具选型采购";并补上"[M]家具进场安装"对"家具生产交货"(id 29)
     的缺失前置依赖,消除断链。50d 生产 Lead Time 下家具交货 2027-02-03 完成,较 2027-02-22 安装留 19 天缓冲。
"""
import os, sys, json, datetime, logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("shanghai_builder")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.mpp_renderer import build_mpp

PROJECT_TITLE = "上海徐汇区 1000㎡ D&B 办公工装项目"
PROJECT_START = datetime.date(2026, 8, 17)

# 用户显式指定里程碑日期 (100% 锁定, MSO)
M = {
    "pm_onboard":  "2026-08-17",   # PM 到任
    "db_award":    "2026-10-16",   # D&B 总包确认
    "permit":      "2026-12-01",   # 取得施工许可证
    "tqc":         "2027-02-02",   # 物理竣工
    "furniture":   "2027-02-22",   # 家具安装
    "gov_approval":"2027-03-08",   # 政府竣工批文
    "move_in":     "2027-04-02",   # 完成搬家
}

# 任务表：id, name, outline_level, duration_days, predecessors, milestone, constraint, work_weekend
# 注意：duration_days 必须为整数，不得出现小数点。
def task(i, name, lvl, dur, pred="", ms=False, c=None, ww=False):
    t = {"id": i, "name": name, "outline_level": lvl, "duration_days": int(round(dur)), "predecessors": pred}
    if ms:
        t["milestone"] = True
    if c:
        t["constraint"] = c
    if ww:
        t["work_weekend"] = True
    return t

T = []
T.append(task(1, PROJECT_TITLE, 1, 0))
# Phase 1 项目前期规划 (业主侧) —— 不含任何长周期采购事项；移除"项目启动"冗余表述与早期"大楼物业装修申请"节点
T.append(task(2, "Phase 1  项目前期规划 (业主侧)", 2, 0))
T.append(task(3, "[M] PM 到任", 3, 0, "", True, {"type": "MSO", "date": M["pm_onboard"]}))
T.append(task(4, "明确用户需求 / 业主需求与功能规划 (Programming)", 3, 8, "3"))
T.append(task(6, "项目规划统整 / 项目执行计划 PEP 编制与各方确认", 3, 5, "3"))
T.append(task(7, "预算沟通与成本框架确认", 3, 4, "6"))
T.append(task(8, "设计任务书 / RFP 编制 (含业主需求)", 3, 5, "7"))

# Phase 2 D&B 总包招采 (邀请招标, 单一家) —— 三轮流程
# 衔接：第一轮产出短名单 → 第二轮技术比选收敛方案 → 第三轮商务定标，逐级淘汰/收敛。
T.append(task(10, "Phase 2  D&B 总包招采 (邀请招标, 单一家) — 三轮流程", 2, 0))
# 第一轮 资格预审 / 市场测试  (合计 10 工作日)
T.append(task(11, "【第一轮】市场测试与意向征集 (Market Sounding)", 3, 3, "8"))
T.append(task(12, "【第一轮】资格预审文件编制与发布 (RFQ / Prequalification)", 3, 3, "11"))
T.append(task(13, "【第一轮】资格预审回标评审 (资质/财务/业绩/履约能力)", 3, 2, "12"))
T.append(task(14, "【第一轮】资格预审报告与短名单确定 (Shortlist 入围)", 3, 2, "13"))
# 第二轮 技术标回标与方案深化  (合计 13 工作日)
T.append(task(15, "【第二轮】招标文件 (技术+商务) 发出给短名单 (ITT Issue)", 3, 3, "14"))
T.append(task(16, "【第二轮】现场踏勘与技术答疑 (Site Visit + Q&A)", 3, 2, "15"))
T.append(task(17, "【第二轮】技术标回标 (Technical Submission)", 3, 2, "16"))
T.append(task(18, "【第二轮】技术评标与方案比选 (Concept / 方案评估打分)", 3, 2, "17"))
T.append(task(19, "【第二轮】技术澄清与方案优化 (Clarifications)", 3, 2, "18"))
# 第三轮 商务回标与定标  (合计 8 工作日)
T.append(task(20, "【第三轮】商务回标 BAFO (Best and Final Offer)", 3, 2, "19"))
T.append(task(21, "【第三轮】清标与商务评标 (价格/合规审查)", 3, 2, "20"))
T.append(task(22, "【第三轮】定标报告(ROA)及中标意向书(LOI)审批", 3, 2, "21"))
T.append(task(23, "【第三轮】D&B 总包合同签约盖章", 3, 2, "22"))
T.append(task(24, "[M] D&B 总包确认 / 定标完成", 3, 0, "23", True, ww=True))

# Phase 2b 采购清单确定与长周期物料直采 (业主侧) —— 置于总包定标之后(采购清单最后确定)
T.append(task(25, "Phase 2b  采购清单确定与长周期物料直采 (业主侧)", 2, 0))
T.append(task(26, "确定采购清单 (含家具/IT等长周期物料)", 3, 3, "32"))
T.append(task(27, "长周期家具业主直采启动 (非招采)", 3, 5, "26"))
T.append(task(28, "家具供应商定标 (业主直采)", 3, 8, "27"))
T.append(task(29, "家具生产交货 Lead Time (业主直采)", 3, 50, "28"))

# Phase 3 设计深化与施工许可 (设计深化在总包定标后开始)
T.append(task(30, "Phase 3  设计深化与施工许可办理", 2, 0))
T.append(task(31, "概念设计与平面布局规划 (D&B 总包主导)", 3, 4, "24"))
T.append(task(32, "平面图确认与业主签字", 3, 3, "31"))
T.append(task(33, "效果图 / 3D 渲染出图 (含修改)", 3, 4, "32"))
T.append(task(34, "初步设计 SD 出图与确认", 3, 4, "32"))
T.append(task(35, "施工图深化 (建/结/机电/智能化)", 3, 10, "33,34"))
T.append(task(36, "上海施工图送审 (含消防一次反馈)", 3, 5, "35"))
T.append(task(37, "[M] 施工图审查合格 / 全套确认", 3, 0, "36", True))
T.append(task(38, "物业装修图纸送审与安全协议签署", 3, 3, "32"))
T.append(task(39, "上海政府施工许可证申报", 3, 4, "37,38"))
T.append(task(40, "[M] 取得施工许可证", 3, 0, "39", True))

# Phase 4 实体施工 (7天日历, 跨周末连续推进)
T.append(task(41, "Phase 4  实体施工阶段", 2, 0))
T.append(task(42, "[M] 场地移交与动工准备 Site Takeover", 3, 0, "40,24", True))
T.append(task(43, "场地保护与临时设施搭建", 3, 3, "42", ww=True))
T.append(task(44, "原有装修拆除及清运", 3, 5, "43", ww=True))
T.append(task(45, "隔墙轻钢龙骨骨架搭设", 3, 8, "44", ww=True))
T.append(task(46, "大机电(暖通/给排水/强弱电)主管桥架铺设", 3, 10, "44", ww=True))
T.append(task(47, "墙内及天花内隐蔽工程联合验收", 3, 2, "45,46", ww=True))
T.append(task(48, "龙骨天花与封板饰面", 3, 10, "47", ww=True))
T.append(task(49, "乳胶漆 / 地毯饰面工程", 3, 8, "48", ww=True))
T.append(task(50, "末端 IT / 弱电 / 安防面板及灯具安装", 3, 8, "49", ww=True))
T.append(task(51, "全系统联动调试 (Testing & Commissioning)", 3, 5, "50", ww=True))
T.append(task(52, "缺陷整改 Defect Rectification", 3, 3, "51", ww=True))
T.append(task(53, "[M] 物理竣工 / 施工自检通过", 3, 0, "52", True, {"type": "MSO", "date": M["tqc"]}))

# Phase 5 竣工环境检测与验收 (刚性双空气检测 SOP)
T.append(task(54, "Phase 5  竣工环境检测与验收 (双空气检测 SOP)", 2, 0))
T.append(task(55, "首次室内空气质量采样检测 (盲测)", 3, 1, "53"))
T.append(task(56, "光触媒治理 (光催化空气净化)", 3, 2, "55"))
T.append(task(57, "[M] 家具进场安装", 3, 0, "56,29", True, {"type": "MSO", "date": M["furniture"]}))
T.append(task(58, "竣工强排通风与空气净化散味 (SOP-4)", 3, 6, "57"))
T.append(task(59, "第二次室内空气质量采样检测", 3, 3, "58"))
T.append(task(60, "消防 / 住建联合竣工核验与整改", 3, 10, "53"))
T.append(task(61, "[M] 政府竣工批文 / 竣工验收通过", 3, 0, "59,60", True, {"type": "MSO", "date": M["gov_approval"]}))

# Phase 6 客户搬迁入驻 (标准工作日日历)
T.append(task(62, "Phase 6  客户搬迁入驻", 2, 0))
T.append(task(63, "搬家前用户系统培训", 3, 2, "61"))
T.append(task(64, "[M] 场地正式移交 Site Handover", 3, 0, "61", True))
T.append(task(65, "客户分批搬家入驻", 3, 6, "64,63"))
T.append(task(66, "[M] 完成搬家 / 正式入驻", 3, 0, "65", True, {"type": "MSO", "date": M["move_in"]}))

# 节假日例外：剔除“春节”项(渲染器已硬编码 2027 春节元宵大假)，其余全量注入标准日历
holidays_path = os.path.join(BASE_DIR, "config", "holidays.json")
calendar_exceptions = []
if os.path.exists(holidays_path):
    with open(holidays_path, encoding="utf-8") as f:
        for h in json.load(f):
            if "春节" in str(h.get("name", "")):
                continue
            calendar_exceptions.append({"name": h.get("name", "法定节假日"),
                                        "start": h.get("start"), "finish": h.get("finish")})

output_mpp = os.path.join(BASE_DIR, "output_mpp", "Shanghai_Xuhui_1000_DnB.mpp")
build_mpp(
    project_title=PROJECT_TITLE,
    project_start=PROJECT_START,
    tasks=T,
    calendar_exceptions=calendar_exceptions,
    output_mpp_path=output_mpp,
)
print("MPP:", output_mpp, os.path.exists(output_mpp), f"{os.path.getsize(output_mpp):,} bytes" if os.path.exists(output_mpp) else "")
print("XML:", os.path.exists(os.path.splitext(output_mpp)[0] + ".xml"))

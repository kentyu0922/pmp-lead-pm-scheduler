---
name: pmp-lead-pm-scheduler
description: 20年经验 Lead PM 全流程工装与工程 Master 进度计划推演与 CPM 精算技能。采用“纯说明书+三专合一（合规专家+工序专家+制表美化专家）”解耦架构，自动合规校验全国城市报建（如杭州/上海/北京/深圳/苏州/成都/武汉等），强扣两次室内空气检测 SOP，并可自动导出原生 MS Project (.mpp) 甘特图文件。当用户需要排期、推演进度表、计算工期、生成工程进度计划或导出 MPP 时激活此 Skill。
---

# 📖 Lead PM 全流程工程进度计划推演说明书 (Instruction & Router Manual)

本 Skill 是 Master Agent 生成专业 MS Project 进度计划的**总引导说明书**。Master Agent 接收到用户需求后，严格按照本说明书引导，按顺序呼叫三大专业领域能力模块协作完成。

---

## 🏛️ 三大专业领域模块分工架构树 (Skill Architecture Tree Structure View)

```text
 pmp-lead-pm-scheduler / (Skill Root)
   ├── SKILL.md                          # 技能主说明书与入口控制指南
   ├── main.py                            # 主调度控制入口 (Master Orchestrator)
   ├── export_pdf.py                      # 统一 PDF 导出 (--format=table|gantt)
   │
   ├── 🏛️ Step 1: 政务报建与合规验收专家模块
   │   └── experts/permit_expert.py       # 属地免办额度、招标红线及拿证时效规则 (城市库外置 config/city_permit.json)
   │
   ├── 🏗️ Step 2: 施工工序与流水线专家模块
   │   ├── templates/wbs_templates.json   # 基础 WBS 4.0 物理流水线工序树
   │   └── templates/sub_wbs_modules.json # 特种模块 (实验室/洁净室/数据中心)
   │
   ├── 📊 Step 3: CPM 求解与 MS Project 物理写盘专家模块
   │   ├── core/_common.py               # 共享层 (MSProjectSession/parse_predecessor/create_task_with_outline)
   │   ├── core/solver_engine.py          # 广域 CPM 日历求解器 (正向推算+离线关键路径估算；MPP 最终精算)
   │   ├── core/mpp_renderer.py           # 全功能 MS Project COM 物理渲染引擎 (大纲状态机+结构断言) ★唯一黄金出口
   │   ├── core/msp_session.py            # COM 会话上下文管理器 (pythoncom 生命周期封装)
   │   ├── core/msp_automation.py         # MS Project 自动化 (import_tasks/export_report)
   │   ├── core/sub_wbs_splicer.py        # 动态 Sub-WBS 模块锚定拼接器
   │   ├── core/compliance.py             # 刚性合规红线代码化审计 (两次空气检测/消防报建/春节日历)
   │   ├── core/holidays.py               # 节假日单源管理 (config/holidays.json 统一入口+客户工作日判定)
   │   ├── core/calibration.py            # 工期校准 (面积非线性缩放+复杂特种施工最小工期断言)
   │   ├── core/task_utils.py             # 任务工具 (采购术语清洗+Task ID 连续重编号)
   │   └── core/responsibility.py         # 责任识别引擎 (执行单位/责任人/责任标识)
   │
   ├── ⚙️ 全局配置与 SOP 知识库
   │   ├── config/holidays.json           # 法定节假日与 2027 春节元宵停工 Exceptions 数据库
   │   ├── config/long_lead_equipment.json# 长周期设备/家具生产交期数据库
   │   ├── config/city_permit.json        # 城市施工许可证免办限额数据库 (外置单源，随仓库发布)
   │   └── docs_and_sops/                 # 消防/安监/ISO验证/空气检测行业 SOP 指南
   │
   ├── 📂 成果文件导出目录
   │   └── output_mpp/                    # 导出的 .mpp 物理文件、.xml 交换文件及解算 JSON
   │
   ├── 🧪 测试与验证
   │   └── tests/                         # 回归测试 (test_v3_basics.py) + 端到端验证脚本
   │
   ├── 📋 示例与开发辅助
   │   ├── examples/                      # 示例脚本 (build_shanghai_schedule.py)
   │   ├── dev/                           # 开发辅助脚本 (一次性补丁/探针/调试导出)
   │   └── scripts/                       # 运维脚本 (preflight.py)
```

---

## 📐 一、 三步法标准执行流程 (3-Step Dispatch Workflow)

### 1. Step 1: 呼叫政务合规专家 (Regulatory Compliance)
* **调用接口**：[permit_expert.py](./experts/permit_expert.py)
* **执行动作**：
  - **开工基准三级优先级判定**：
    1. `优先级 1 (最高)`：用户显式指定开工日（如“10/1上任”），100% 遵从指定日期；
    2. `优先级 2`：用户未指定 + 强调“工期赶/紧迫/急”，强扣当前实时日期（今天/明天）；
    3. `优先级 3`：常规推演。
  - **属地免办校验**：输入【城市、面积、造价】，校验是否免办《施工许可证》（如杭州 1000m²、上海/苏州 300m² 等）。城市免办限额数据外置于 `config/city_permit.json` 单源；已收录城市直接查规则库，未收录城市回退内置「全国通用标准」静态兜底（不触发任何网络调用）。
  - **招投标法 400万红线与投标期下限**：国企/政府且 ≥400万元 强扣 **公开招标**（法定投标编制期同样 ≥20 工日，通常取 25 工日稳妥）；其余（私有资金）采用 D&B / DBB 邀请招标，但**招标文件发出至投标截止不得少于 20 工日**（《招标投标法》第24条），不得压缩为 11 工日。
  - **季节通风工期**：依据硬装完工月份气温动态调整（夏季 45工日/春秋 60工日/冬季 75工日），统一规范命名为 `SOP-4: 竣工强排通风与空气净化散味阶段`。

### 2. Step 2: 呼叫施工工序专家 (Process & Flow Line)
* **调用接口**：[wbs_templates.json](./templates/wbs_templates.json) & [sub_wbs_modules.json](./templates/sub_wbs_modules.json)
* **执行动作**：
  - **模式匹配（③招采形态 × ④招标方式 = 4 套模板）**：由 `--delivery`(DB/D&B | DBB) 与 `--bidding`(invite 邀请 | public 公开) 正交组合选模板：
    - `DB` + `invite` → `MNC_Standard_Fitout_DB_Invite`（D&B 设计施工一体化，设计中标后做，邀请招标）
    - `DB` + `public` → `MNC_Standard_Fitout_DB_Public`（D&B，设计中标后做，公开招标法定流程）
    - `DBB` + `invite` → `MNC_Standard_Fitout_DBB_Invite`（设计先行至招标前，邀请招标）
    - `DBB` + `public` → `MNC_Standard_Fitout_Office_DBB`（设计先行至招标前，公开招标法定流程）
    - 兼容旧版：仍可直接 `--mode <模板键>`。缺 `--delivery/--bidding` 交互询问（非交互报错退出）；缺 `--start_date/--target_date` 同理（拒绝零日期失真排程）。
  - **WBS 4.0 物理流水线**：`保护拆除 ➔ 测量放线 ➔ 管线桥架 ➔ 隐蔽验收 ➔ 龙骨天花 ➔ 封板饰面 ➔ 乳胶漆地毯 ➔ 末端安装调试 ➔ 粗保洁`。
  - **100% 前置 FS 驱动**：全表必须以 Task ID 进行 FS (Finish-to-Start) 逻辑驱动，禁止 Successor。

### 3. Step 3: 呼叫制表美化与物理写盘专家 (Formatting & MPP Builder)
* **调用接口**：[solver_engine.py](./core/solver_engine.py) & [mpp_renderer.py](./core/mpp_renderer.py)
* **执行动作**：
  - **CPM 广域日历解算**：节假日统一由 `config/holidays.json` **单源驱动**（当前覆盖 2025–2030，缺失年份自动兜底），不再内置硬编码年表。Python 先做正向推算与离线关键路径估算，最终任务日期与浮时由 MS Project COM 重算落盘。
  - **Level 1~4 树形大纲缩进**：基于 Outline 状态机对 WBS 节点进行物理缩进，形成清爽大纲。
  - **甘特图美化与结构断言**：灭绝估计问号标记 (`Manual=False` & `Estimated=False`)，执行结构断言扫描，应用 `甘特图 (Gantt Chart)` 主视图并物理落盘 `.mpp` 与 `.xml` 文件。

---

## 🛡️ 二、 刚性业务与工程红线 (Hard Constraints)

1. **绝对前置 FS 驱动**：彻底禁止使用后续任务 (Successor)。
2. **纯整数工作日与专业术语**：禁用所有“动土/打底/拆包/拿钥匙/盲测/给足X天/高温烘培”等口语化词汇。
3. **两次空气检测 SOP 防线**：首次盲测 ➔ 光触媒治理 ➔ 家具进场 ➔ 强排通风 ➔ 第二次室内空气质量采样检测必须保持严格 FS 逻辑，彻底清洗特定敏感字样（如 CMA）。
4. **跨春节战略缓冲法则**：目标日期位于春节大假后时，主动推演并明确提供【策略 A（年前完工+假期长效通风+目标日前夕搬迁）】或【策略 B（放宽前期设计/选材+节后收口+目标日前夕搬迁）】。
5. **ASAP 紧迫性开工法则 (不覆盖显式指定)**：只有当用户未指定具体开工日且强调紧迫时才强扣当前日期。若用户明确指定了开工日（如“10/1上任”），必须 100% 严格以用户指定日期为准。
6. **大阶段日历分派大原则与搬家例外**：
   - **Phase 1~3 (前期/设计/招投标/物业图审)**：默认全线套用 **标准工作日日历**（受政务、物业、法务节假日约束）；
   - **Phase 4~6 (现场施工阶段 & 竣工强排通风/保洁移交阶段)**：大原则默认全线套用 **施工 7 天日历 (正常 7*8 工作制，每天8小时)**，完全不用考虑周末影响，遇 2027 春节元宵 15 天大假自动 Exceptions 挂起停工；
   - **【正式搬家/搬迁入驻】节点例外**：必须强扣 **客户标准工作日日历**（配合客户正常上班日搬家）。
7. **MS Project COM 引擎写盘铁律 (Calendar & Duration Engine Rules)**：
   - MS Project 内部的 `Duration` 永远以**任务绑定的日历标准工时（默认1天=8小时）**为基准进行工作时长折算，绝不是自然日历天。
   - 现场施工等需要跨越周末连续推进的任务，**必须在 COM 初始化时创建 `施工7天日历`**（打通周末工作日），并赋予该任务。
   - **唯一黄金入口死锁**：所有 `.mpp` 物理文件导出，**100% 强制走 `core/mpp_renderer.py` 中的 `build_mpp` 唯一黄金出口**。

---

## 📁 三、 专家模块文件索引 (Real File Index)

- 纯说明书 / 指南：[SKILL.md](./SKILL.md)
- 🏛️ 政务报建与合规专家：[permit_expert.py](./experts/permit_expert.py)
- 🛡️ 合规红线审计引擎：[compliance.py](./core/compliance.py)
- 🗓️ 节假日单源管理：[holidays.py](./core/holidays.py)
- 🗂️ 城市免办限额库：[city_permit.json](./config/city_permit.json)
- 🏗️ 施工工序与流水线专家：[wbs_templates.json](./templates/wbs_templates.json)
- 🏗️ 特种模块库：[sub_wbs_modules.json](./templates/sub_wbs_modules.json)
- 📊 CPM 求解引擎：[solver_engine.py](./core/solver_engine.py)
- 📊 MS Project 物理渲染与断言引擎：[mpp_renderer.py](./core/mpp_renderer.py)
- 📊 动态模块拼接器：[sub_wbs_splicer.py](./core/sub_wbs_splicer.py)
- 🔧 共享层 (COM 会话/前置解析/大纲创建)：[_common.py](./core/_common.py)
- 🔧 COM 会话管理器：[msp_session.py](./core/msp_session.py)
- 🔧 MS Project 自动化：[msp_automation.py](./core/msp_automation.py)
- 🔧 工期校准：[calibration.py](./core/calibration.py)
- 🔧 任务工具：[task_utils.py](./core/task_utils.py)
- 🔧 责任识别引擎：[responsibility.py](./core/responsibility.py)
- 📄 PDF 导出：[export_pdf.py](./export_pdf.py)

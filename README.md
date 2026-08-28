# pmp-lead-pm-scheduler

20 年经验 Lead PM 全流程工装与工程 Master 进度计划推演 + CPM 精算技能。
自动合规校验全国城市报建（杭州/上海/北京/深圳/苏州/成都/武汉等），强扣两次室内空气检测 SOP，
导出原生 MS Project (.mpp) 甘特图。

## 运行环境要求

- **OS**：Windows（MS Project COM 自动化仅 Windows 可用）
- **Python**：3.8+
- **MS Project**：需安装 Microsoft Project 桌面端（Office 组件），用于 `.mpp` 物理渲染
- **依赖**：见 `requirements.txt`（仅 `pywin32`，其余全标准库）

> 纯 Python 的 CPM 求解（`core/solver_engine.py`）可在无 MS Project 环境独立运行用于工期估算；
> 但 `.mpp` 物理文件导出必须同时具备 pywin32 + MS Project。

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 快速开始

```bash
# 正排：指定开工日
python main.py --city 上海 --area 1000 --cost 250 --delivery DB --bidding invite   --start_date 2026-08-28 --project_name "上海1000㎡办公工装" --output case.mpp

# 倒排：指定目标搬迁日
python main.py --city 杭州 --area 500 --cost 125 --delivery DB --bidding invite   --target_date 2027-04-30 --project_name "杭州500㎡办公工装" --output case.mpp
```

输出：`output_mpp/<name>.mpp` + `.xml`。

## 参数

| 参数 | 说明 |
|------|------|
| `--city` | 项目城市（决定报建规则） |
| `--area` | 面积（㎡） |
| `--cost` | 预估造价（万元，影响招采阈值） |
| `--delivery` | `DB`(D&B 设计施工一体化) / `DBB`(设计-招标-施工) |
| `--bidding` | `invite`(邀请招标) / `public`(公开招标) |
| `--start_date` | 正排开工日 YYYY-MM-DD |
| `--target_date` | 倒排目标搬迁日 YYYY-MM-DD |
| `--addons` | 特种 Sub-WBS 模块（见 templates/sub_wbs_modules.json） |
| `--output` | 输出 mpp 文件名 |

`--start_date` 与 `--target_date` 至少给一个（拒绝零日期失真排程）。

## 架构（三专合一）

详见 `SKILL.md`。核心：

- `experts/permit_expert.py` — 政务报建合规专家（城市免办额度/招标红线/拿证时效）
- `templates/wbs_templates.json` — 4 套 WBS 模板（DB/DBB × invite/public）
- `core/solver_engine.py` — CPM 日历求解（正排/倒排/关键路径）
- `core/mpp_renderer.py` — MS Project COM 物理渲染（唯一黄金出口）
- `core/calibration.py` — 工期校准（面积缩放 + 隐蔽验收/穿插工序/T&C 工期下限）
- `core/compliance.py` — 刚性合规红线审计（两次空气检测/消防/春节日历）
- `config/` — 节假日/城市报建/长周期设备单源数据
- `docs_and_sops/` — 消防/安监/空气检测/施工工序行业 SOP 知识库

## 排程政策基线（已固化）

- 7 天施工日历：仅春节→元宵停工，其余法定节假日照常施工
- 政府审批/报建节点：强制 5 天日历
- 家具物理进场：夹于首次 IAQ 之后、二次 IAQ 之前
- 隔墙隐蔽→吊顶隐蔽：≥2 周间隔，穿插墙面封板+天花吊顶龙骨 / 二次机电 2nd Fix
- Phase 3 设计深化：初步设计 SD / 施工图深化 用 SS+lag 并行压缩

## License

Copyright (c) 2026 kentyu0922. All rights reserved. See `LICENSE`.
Unauthorized copying, modification, distribution, or use is prohibited.

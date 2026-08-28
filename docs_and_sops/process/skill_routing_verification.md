# Skill 路由逻辑与实测验证报告

生成日期：2026-08-27｜对象：`pmp-lead-pm-scheduler` v3（main.py 全链路）
目的：回答"skill 在各种条件下如何路由"并实证每个分支行为（含缺口）。

## 1. 路由分层总览（main.py 执行顺序）

| 层 | 驱动参数 | 路由逻辑 | 代码位置 |
|---|---|---|---|
| 政务合规 | `--city` | `query_city_permit_rule`：城市名→省份名/map→全国兜底 | permit_expert.py L129 |
| 招采模式 | `--mode` 含 "SOE"？ | `calc_tender_duration("SOE" in mode)` → 公开招标 / 邀请招标 | permit_expert.py L170；main.py L52 |
| 模板选择 | `--mode` | 直接 dict 取值，默认 `MNC_Standard_Fitout_DB_Invite` | main.py L36/L63 |
| 工期校准 | `--area` + 城市下限 | `scale=(area/base)^0.3`；图审/许可取 `max(模板, 城市下限)` | calibration.py L46/L60/L71 |
| 排期方向 | `--start_date` / `--target_date` | 正排 / 倒排(锚 target-7) / 皆无→未解算 | main.py L96-127 |
| 豁免判定 | area + cost | `is_exempt` 计算（AND/OR），但**无消费方** | permit_expert.py L156-165 |

## 2. 实测矩阵（逐项验证）

### R1 模板模式路由 — 显式 `--mode`
| 输入 | 结果 |
|---|---|
| `MNC_Standard_Fitout_DB_Invite` | ✅ D&B 模板（base 8000，64 节点） |
| `MNC_Standard_Fitout_Office_DBB` | ✅ DBB 模板（base 20000，52 节点） |
| `D&B` / `Bogus_Key` | ⚠ KeyError 直接崩溃，无兜底、无校验、无友好提示 |

### R2 城市报建路由 — `query_city_permit_rule`
| 输入 | 命中层 | 图审≥ | 许可≥ | 免办阈值 |
|---|---|---|---|---|
| 苏州 | 城市库（江苏） | 7 | 8 | 300㎡ |
| 无锡（裸名） | 省份基线（江苏 map） | 6 | 10 | 300㎡ |
| 银川 | 城市库（宁夏） | 7 | 7 | 300㎡ |
| 西藏林芝 | 省份基线（西藏） | 10 | 5 | 500㎡ |
| 未知小城XX | 全国兜底 | 10 | 7 | 300㎡ |
结论：城市→省份→兜底 三层全部生效，**绝不触发联网**。

### R3 招采模式路由 — `calc_tender_duration`
| 条件 | 结果 |
|---|---|
| "SOE" in mode 且 cost≥400万 | 公开招标 25天 |
| 否则（含两个真实模板键） | 邀请招标/D&B 33天 |
⚠ **缺口**：真实模板键 `MNC_Standard_Fitout_DB_Invite` / `MNC_Standard_Fitout_Office_DBB` 均**不含 "SOE"**，故公开招标分支对真实输入**不可达**。KB §8 称 DBB 走公开招标，但实际路由恒为邀请招标 33天。需新增 `MNC_Standard_Fitout_Office_DBB_SOE` 模板或在 `calc_tender_duration` 中以 mode 含 "DBB"/"Public" 判定才可达。

### R4 面积非线性缩放 — `calibrate_durations`
| 模板 | 面积 | scale | 含义 |
|---|---|---|---|
| D&B (base 8000) | 1000 | 0.536 | 施工工期压缩 ~46% |
| D&B | 8000 | 1.000 | 基准 |
| D&B | 20000 | 1.316 | 拉伸 +32% |
| D&B | 50000 | 1.733 | 拉伸 +73% |
| DBB (base 20000) | 1000 | 0.407 | 压缩 ~59%（小面积 DBB 偏快，注意） |
| DBB | 20000 | 1.000 | 基准 |
图审/施工许可工期**不参与缩放**，仅取城市下限 `max`。

### R5 豁免标志 — `is_exempt`
⚠ **缺口（死代码）**：`query_city_permit_rule` 计算 `is_exempt`（如苏州 200㎡/80万 = True），但 main.py / calibration.py / solver 中**无任何代码消费该标志来剔除或跳过"施工许可"任务**。实测：苏州 200㎡ 项目仍生成 `Phase 4 施工许可证办理` + `政府施工许可证申报` + `[M] 正式取得施工许可证` 三个节点。应补充"低于免办限额则自动折叠施工许可阶段"的逻辑。

### R6 排期方向路由 — main.py L96-127
| 参数组合 | 行为 |
|---|---|
| `--start_date` 仅 | 正排 `solve_schedule` |
| `--target_date` 仅 | 倒排 `solve_schedule_with_target`，锚定 target-7 工作日 |
| `--start` + `--target` | 正排 + 迟到断言（超期 raise 拒绝失真） |
| 两者皆无 | ⚠ 求解器**不运行**，`tasks_solved=tasks` 无 Start/Finish；仍写 MPP 但任务零日期（实测 64 任务含日期数=0） |

## 3. 端到端影响实证（真实 run）
- **城市路由改变排期**：苏州 1000㎡ D&B（target 2027-04-30）finish=2027-04-22；无锡 1000㎡ D&B（同 target）finish=2027-04-16。更严的省份许可下限（无锡≥10 vs 苏州≥8）确实改变了倒排结果。
- **豁免死代码**：苏州 200㎡ 仍含施工许可节点（见 R5）。
- **退化路径**：仅传 `--city --area` 生成 MPP 但 0 任务有日期（见 R6）。

## 4. 待修复缺口清单（按优先级）
1. **P0 招采公开招标不可达**：真实 DBB 模板无法触发公开招标（R3）。修复：新增 `_SOE` 模板键，或在 `calc_tender_duration` 按 mode 含 "DBB"/"Public" + cost≥400万 判定。
2. **P0 模式键容错**：非法 `--mode` 直接 KeyError（R1）。修复：`templates` 键校验 + 建议候选 + 友好报错。
3. **P1 豁免死代码**：`is_exempt` 应驱动施工许可阶段折叠（R5）。
4. **P1 退化路径**：无日期时至少默认正排自 today（R6），而非写出零日期 MPP。
5. **P2 面积缩放语义**：DBB base=20000 使小面积（如 1000㎡）scale 仅 0.4，可能过度压缩；建议 D&B/DBB 分别给出合理 base 或提示。

## 5. 如何复现验证
```bash
# 路由矩阵（纯函数，秒级）
python -c "import sys;sys.path+=['experts','core'];import permit_expert as p,calibration as c; ..."
# 端到端 4 场景
python main.py --city 苏州 --area 1000 --cost 250 --delivery DB  --bidding invite --target_date 2027-04-30
python main.py --city 苏州 --area 1000 --cost 250 --delivery DB  --bidding public --target_date 2027-04-30
python main.py --city 苏州 --area 20000 --cost 500 --delivery DBB --bidding invite --target_date 2027-06-30
python main.py --city 苏州 --area 20000 --cost 500 --delivery DBB --bidding public --target_date 2027-06-30
```

## 6. 修复记录 (2026-08-27) — ③×④ 正交化
- **P0 公开招标不可达（R3）已修复**：`main.py` 拆 `--mode` 为 `--delivery`(DB/DBB) + `--bidding`(invite/public)；`calc_tender_duration` 改为直接吃 `bidding` 值（保留 `project_type` 兼容）。旧 `"SOE" in mode` 判定彻底废弃。4 套模板键建立：DB_Invite / DB_Public / DBB_Invite / Office_DBB(=DBB_Public)。
- **新增模板**：`MNC_Standard_Fitout_DB_Public`（D&B+公开招标，设计后置）、`MNC_Standard_Fitout_DBB_Invite`（DBB+邀请招标，设计前置）。两模板由克隆 + 仅改写招标阶段法定步骤生成，设计归属规则不变。
- **P0 模式键容错（R1）已修复**：非法 `--delivery`/`--bidding` 给出可读报错（SystemExit），不再 KeyError；`--mode` 旧键仍兼容。
- **⑤ 锚点硬化（R6 退化路径）已修复**：缺 `--start_date`/`--target_date` 时，TTY 交互询问，非交互（含无 stdin）→ 清晰报错退出，拒绝零日期失真 MPP。
- **未修（留作后续）**：P1 豁免折叠施工许可（R5 `is_exempt` 仍无消费方）、P2 DBB 小面积过度压缩。
- **4 场景验证结果**：S1~S4 全部 合规红线通过、MPP 物理渲染成功；S2/S4 招采规程正确显示「公开招标 25天」，公开分支已可达。

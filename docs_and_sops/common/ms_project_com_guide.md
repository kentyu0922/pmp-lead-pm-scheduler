# MS Project COM 自动化方案 · 用户指南

> 模块：`core/msp_session.py`（COM 会话与读取助手）、`core/msp_automation.py`（导入/更新/导出）、`tools/msp_cli.py`（命令行）
> 定位：直接驱动**本机已安装**的 Microsoft Project，实现 `.mpp` 的读取、创建、修改与报表导出。

---

## 1. 环境前提（硬性）

| 前提 | 说明 | 检查方式 |
|---|---|---|
| 已安装 MS Project | 支持 .mpp 的版本（2016 / 2019 / 2021 / Microsoft 365） | 开始菜单能打开 Project |
| 位数一致 | **Python 解释器与 MS Project 必须同为 32 位或同为 64 位**，否则 COM 无法连接 | `python -c "import sys; print(sys.maxsize>2**32)"` 与 Project 关于页对照 |
| pywin32 | `pip install pywin32` | `python -c "import win32com"` 不报错 |
| reportlab（仅 PDF 导出需要） | `pip install reportlab` | `python -c "import reportlab"` 不报错 |

**运行前自检**：`python tools/msp_cli.py verify` —— 返回 `✅ MS Project COM 可用` 方可继续。

> 注：接口文件后缀为 **`.mpp`**（用户口述的 `.mpr` 为笔误；本方案仅处理 `.mpp` / `.mpt`）。

---

## 2. 输入 / 输出格式

### 2.1 任务导入 JSON（`import` 输入）
顶层为数组，或含 `tasks` 字段的对象。每个任务节点字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | int | 否 | 序号（建议与 MPP 任务 ID 对应，便于后续按 id 更新进度） |
| `name` | str | 是 | 任务名称 |
| `outline_level` / `level` | int | 否 | 大纲级别（1=项目阶段，3=叶子任务）；默认 3 |
| `duration` / `duration_days` | number | 否 | 工期（工作日天数）；0 或 `milestone=true` 视为里程碑 |
| `predecessors` | str | 否 | 前置依赖，如 `"2"`、`"2,3"`、`"1FS+2d"`（FS 为主，非 FS 类型依赖在 MPP 内仍按 FS 录入） |
| `milestone` | bool | 否 | 是否为里程碑 |
| `work_weekend` | bool | 否 | 是否使用施工7天日历（默认仅施工类摘要节点自动指派） |
| `start` / `finish` | str | 否 | 预设起止日（仅作参考，实际日期由 MPP 按日历重算） |

示例见 `examples/sample_tasks.json`。

### 2.2 进度更新 JSON（`update` 输入）
顶层为数组，或含 `updates` 字段的对象。每条更新：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 按任务 ID 匹配（优先） |
| `name` | str | 按任务名称匹配（id 缺失时） |
| `percent_complete` | int 0–100 | 完成百分比 |
| `mark_complete` | bool | true 则置 100% |
| `actual_start` / `actual_finish` | str `YYYY-MM-DD` | 实际开始/完成日期（可选） |

示例见 `examples/sample_progress.json`。

### 2.3 报表导出（`export` 输出）
- **CSV**：`utf-8-sig` 编码（Excel 直接打开不乱码）。
- **JSON**：任务行数组，字段同 `DEFAULT_FIELDS`。
- **PDF**：横向 A4 表格，内置中文字体（STSong-Light），无需额外字体文件。

默认导出字段：ID、名称、大纲级别、开始、完成、工期、前置任务、完成百分比、实际开始、实际完成、总时差、关键。

---

## 3. 操作约束与已知坑位（务必遵守）

1. **COM 创建独立实例**：脚本通过 `DispatchEx` 启动隐藏的 MS Project 实例，**不会干扰你手动打开的其他 Project 文件**；脚本结束自动 `Quit()`。
2. **读取工期用 `GetField(FieldNameToFieldConstant("Duration"))`**：返回原生单位串（如 `3 个工作日`）。**绝不**自己用 `Task.Duration`（分钟数，标准日历×480、施工日历×1440）除以固定数换算——会算错。
3. **读取日期先转本地时区**：`Task.Start/Finish` 是 `pywintypes.datetime`（UTC），必须 `.astimezone()` 转本地再取日期，否则跨时区漂移。本方案 `read_local_date()` 已封装。
4. **页面设置不可经 COM 设置**：`FilePageSetup*` 系列方法在本 typelib 返回 1101，因此本方案**不**尝试 COM 页面设置；PDF 走 reportlab 直渲，CSV/JSON 不受限。
5. **`Predecessors` 非 FS 类型会降级**：XML/MPP 录入时非 FS 依赖类型字母（SS/FF/SF）在当前写入路径按 FS 处理；如需精确依赖类型，请在 MPP 内手工确认。
6. **大批量写入性能**：会话已关闭 `ScreenUpdating` 与自动计算，写入完成保存时 MPP 会自动重算关键路径与浮时。
7. **长周期设备/节假日**仍由 `config/` 与求解器驱动，本自动化层只负责把已算好的任务落到 MPP 并回读。

---

## 4. 命令行速查

```bash
# 0) 环境自检
python tools/msp_cli.py verify

# 1) 任务导入（新建 .mpp）
python tools/msp_cli.py import \
    --json examples/sample_tasks.json \
    --out output_mpp/Demo.mpp \
    --title "演示项目" --start 2026-08-31

# 1b) 向已有 .mpp 追加任务
python tools/msp_cli.py import --json more_tasks.json --out output_mpp/Demo.mpp --append

# 2) 进度更新
python tools/msp_cli.py update \
    --mpp output_mpp/Demo.mpp \
    --progress examples/sample_progress.json

# 3) 报表导出
python tools/msp_cli.py export --mpp output_mpp/Demo.mpp --out output_mpp/Demo_report.csv --format csv
python tools/msp_cli.py export --mpp output_mpp/Demo.mpp --out output_mpp/Demo_report.json --format json
python tools/msp_cli.py export --mpp output_mpp/Demo.mpp --out output_mpp/Demo_report.pdf --format pdf
```

---

## 5. VBA 替代方案（如需在 Project 内宏运行）

若更习惯在 MS Project 的 VBA 宏里操作（等价于本方案的 COM 逻辑）：

```vba
Sub ExportTasksToCsv()
    Dim ts As Tasks, t As Task
    Dim f As Integer
    f = FreeFile
    Open "C:\temp\tasks.csv" For Output As #f
    Print #f, "ID,Name,Start,Finish,Duration,PercentComplete"
    Set ts = ActiveProject.Tasks
    For Each t In ts
        If Not t Is Nothing Then
            Print #f, t.ID & "," & t.Name & "," & _
                Format(t.Start, "yyyy-mm-dd") & "," & _
                Format(t.Finish, "yyyy-mm-dd") & "," & _
                t.Duration & "," & t.PercentComplete
        End If
    Next t
    Close #f
    MsgBox "已导出到 C:\temp\tasks.csv"
End Sub
```

> Python COM 与 VBA 本质相同（都是驱动 Project 对象模型）；本方案用 Python 是为了可复用、可版本化、可接入排期求解器。

---

## 6. 排错速查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `无法启动 MS Project COM 对象` | 未装 Project / 位数不符 / 未装 pywin32 | 对照第 1 节逐项检查 |
| `verify` 返回不可用 | 同上，或 Project 正被另一用户会话独占 | 关闭其他 Project 实例重试 |
| PDF 导出报缺 reportlab | 未安装 | `pip install reportlab` |
| 日期比预期早/晚一天 | 读取时未转本地时区 | 使用本方案 `read_local_date`，勿直接取 `Task.Start` 字符串 |
| 工期数值异常 | 自己做了分钟数换算 | 改用 `GetField("Duration")` 原生串 |

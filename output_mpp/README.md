# 📂 output_mpp/ (排程物理成果落地目录)

本目录为 `main.py`、`exporters` 及 `tools/msp_cli.py` 运行时产出的默认目标目录。

运行调度后，此处将自动落地以下核心物理交付成果：
1. `*.mpp`：Microsoft Project 原生二进制工程排期文件（Windows + MS Project 环境优先渲染）
2. `*.pdf`：A3 横向打印级工程任务明细报表（全平台自动导出）
3. `*.pptx`：高管汇报级单页 Key Milestones Timeline 演示文稿
4. `*.xml`：MS Project 标准数据交换底座（全平台通用）
*(注：原 `*.html` 交互控制板已在 v4.1 主链路收敛停用)*

> 💡 **版本控制说明**：本目录下的所有实际输出成果均已被 `.gitignore` 忽略，确保交付物纯净。

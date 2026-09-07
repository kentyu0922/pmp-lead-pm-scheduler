# 📜 scripts/ (环境预检脚本)

本目录仅保留上线前与排期执行前的环境可用性检查工具：

- **`preflight.py`**：环境预检脚本。用于在调用 `main.py` 之前检验单源节假日 `config/holidays.json`、城市免办库 `config/city_permit.json`、核心算法模块导入完整性，并检测本地环境中的 MS Project COM (`win32com`) 状态。

> 💡 **说明**：作者维护与重构 WBS 模板的离线开发工具已迁至 `dev_tools/`，与运行期脚本彻底分离，防止 Agent 运行期误调用。

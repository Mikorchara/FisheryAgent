# Fishery AI Prototype

独立的智慧渔业 AI 原型：程序维护传感器事实与确定性诊断，LLM 负责解释，知识检索为固定 Analysis 提供背景证据。

## 启动

需要 Python 3.11+。在 PowerShell 项目根目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m fishery_ai web
```

离线示例：`.venv\Scripts\python.exe -m fishery_ai demo --scenario low_oxygen`。Web 默认只监听 `127.0.0.1:8765`。真实模型请求须在界面显式确认；自动测试保持离线。

## 独立管理系统 R1

新管理工作区在 `apps/management_web/`，项目根目录执行 `python -m apps.management_web`，访问 `http://127.0.0.1:8766`。首页及六个业务模块可导航，Demo来源明确；AI发送、真实视频和管理写操作尚未接入。原Prototype Web保留。见[子应用说明](apps/management_web/README.md)。

## 模型接入

- **Preset**：项目维护并发布的固定模型方案。
- **Managed Custom**：用户维护连接；高级能力依赖精确 Identity 的证据与显式 Probe。
- **Manual Expert V1/V2**：原始请求实验路径，不进入 Fishery Analysis；返回的 `tool_calls` 不自动执行。

当前 Preset：Qwen 3.8 Flash（默认）、DeepSeek Flash、Ollama Qwen3.5 4B。用户可用组合与合同版本见[Preset 发布合同](docs/deep-dive/models/PRESET_PUBLICATION.md)。

Assistant Model v1 与 Analysis 分离；固定 Analysis 保留 Snapshot → Diagnosis → RAG。当前注册三个只读 Tool：水质查询、实验评分与项目知识检索；Knowledge 默认关闭，模型选择仍有可靠性限制。评分不是专业养殖标准，背景知识不代表当前事实。Normal多轮及Streaming Tool Calling按精确范围开放本地试用，技术资格与回答质量分开审核；系统不是Agent，不允许Tool直接操作设备、写数据库或修改诊断阈值。

## 文档

- [构建与运行](docs/BUILD_RUN.md)
- [项目结构](docs/STRUCTURE.md)
- [路线图](docs/ROADMAP.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [当前 Analysis / Assistant 结构](docs/deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md)
- [只读 Tool 当前实现](docs/deep-dive/tools/READ_ONLY_TOOL_CALLING.md)
- [如何新增 Tool](docs/deep-dive/tools/ADDING_A_TOOL.md)
- [阶段记录与历史归档](docs/records/README.md)：验收、独立审计与已结束阶段记录；不作为 CURRENT STATE 来源。
- [水质与 Telemetry 数据边界](docs/deep-dive/data-domain/WATER_QUALITY_SCENARIO_AND_TELEMETRY_PREPARATION.md)
- [运行数据与凭据位置](docs/deep-dive/operations/PROJECT_DATA_AND_CONFIG_LOCATIONS.md)

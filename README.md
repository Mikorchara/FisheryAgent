# Fishery AI Prototype

独立的智慧渔业 AI 原型：程序维护传感器事实和确定性诊断，LLM 负责解释；知识检索提供背景证据。

## 启动

Python 3.11+，在 PowerShell 项目根目录运行：

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e .
    .\.venv\Scripts\python.exe -m fishery_ai web

离线演示：.venv\Scripts\python.exe -m fishery_ai demo --scenario low_oxygen。Web 默认只监听 127.0.0.1:8765。真实网络请求必须在页面显式确认；自动测试保持离线。

## 三种模型模式

- **Preset**：项目维护的固定方案。用户只选模型、Thinking、Normal/Streaming。
- **Managed Custom**：用户维护连接；高级能力须有精确身份证据，UNKNOWN 时可显式 Probe。
- **Manual Expert V1 / V2**：V1 使用已保存连接；V2 自定义目标并保存独立实验。Raw 请求不进入 Fishery 分析，也不执行返回的 tool_calls。

当前 Preset：

| 模型 | 合同版本 | 发布组合 | 默认 |
| --- | --- | --- | --- |
| Qwen 3.8 Flash | 1.0.2 | OFF/ON × Normal/Streaming | 是，OFF + Normal |
| DeepSeek Flash | 1.0.2 | OFF/ON × Normal/Streaming | 否 |
| Ollama Qwen3.5 4B | 1.0.2 | OFF/ON × Normal/Streaming | 否 |

## 文档

- [构建、启动与日常操作](docs/BUILD_RUN.md)
- [项目结构](docs/STRUCTURE.md)
- [路线图](docs/ROADMAP.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [维护者文件位置地图](docs/deep-dive/PROJECT_DATA_AND_CONFIG_LOCATIONS.md)
- [Preset 发布合同](docs/deep-dive/PRESET_PUBLICATION.md)

只读 Tool Calling T1–T5 已提供单轮闭环、Web 开发入口和 Managed 显式能力验证。Analysis 保留 Snapshot → Diagnosis → RAG；可在 Tool 管理中显式启用 Normal 单轮工具，右侧 Tool Activity 显示本次执行。三个 Preset 均已发布 Tool 协议支持。工具包括当前水质查询和实验水质评分；评分默认关闭，不是专业标准。见[Analysis Tool Calling v1](docs/deep-dive/ANALYSIS_MODEL_TOOL_CALLING_V1.md)与[新增 Tool 指南](docs/deep-dive/ADDING_A_TOOL.md)。当前不是 Agent，不支持 Streaming Tool Calling，不得直接操作设备、修改数据库或改变诊断阈值。

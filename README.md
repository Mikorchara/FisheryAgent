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

当前 Preset 均为合同 1.0.1：

| 模型 | 发布组合 | 默认 |
| --- | --- | --- |
| Qwen 3.8 Flash | OFF/ON × Normal/Streaming | 是，OFF + Normal |
| DeepSeek Flash | OFF/ON × Normal/Streaming | 否 |
| Ollama Qwen3.5 4B | OFF/ON × Normal/Streaming | 否 |

## 文档

- [构建、启动与日常操作](docs/BUILD_RUN.md)
- [项目结构](docs/STRUCTURE.md)
- [路线图](docs/ROADMAP.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [维护者文件位置地图](docs/deep-dive/PROJECT_DATA_AND_CONFIG_LOCATIONS.md)
- [Preset 发布合同](docs/deep-dive/PRESET_PUBLICATION.md)

只读 Tool Calling T1–T5 已提供单轮闭环、Web 开发入口和 Managed 显式能力验证。Analysis 固定流程不调用 Tool；Assistant 当前为 Policy 限制的单轮实验。见[应用模式架构](docs/deep-dive/ASSISTANT_MODEL_ARCHITECTURE.md)。当前不是 Agent，不支持 Streaming Tool Calling，不得直接操作设备、修改数据库或改变诊断阈值。

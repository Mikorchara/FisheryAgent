# Preset 发布合同

Preset 是维护者发布的固定方案。普通用户只选择 Model、Thinking 和 Response Mode；不显示 Base URL、凭据引用、ProtocolSpec、Evidence 或 Probe。运行时 Managed Evidence 不改变 Preset 合同。

## 当前发布

| Preset | exact model | 合同 | Thinking × Response Mode | 默认 |
| --- | --- | --- | --- | --- |
| Qwen 3.8 Flash | qwen3.8-flash | 1.0.1 | OFF/ON × Normal/Streaming | Qwen，OFF + Normal |
| DeepSeek Flash | deepseek-flash | 1.0.1 | OFF/ON × Normal/Streaming | 否 |
| Ollama Qwen3.5 4B | qwen3.5:4b | 1.0.1 | OFF/ON × Normal/Streaming | 否 |

AUTO、Reasoning Effort 与其他未发布组合不在用户选项内。各 Preset 使用自己的固定服务身份、适配器、URL、精确模型、凭据引用、超时与协议编码；Ollama 使用 Auth NONE。定义位于 src/fishery_ai/resources/profiles/presets.json。

## OFF + Streaming 的发布依据

2026-10-04，用户确认 Qwen 3.8 Flash 与 DeepSeek Flash 在正常 Web 进程中 OFF + Streaming 均可工作。维护 metadata 将其标为用户人工验收来源；Codex 本轮没有重发 Cloud 请求。两者从合同 1.0.0 升至 1.0.1，只添加 thinking_off_streaming_combination 固定支持状态及 OFF Variant 的 Streaming 选项。

Ollama Qwen3.5 4B 的 OFF + Streaming 在此前单次 R5 Probe 成功后已发布于 1.0.1。本轮未重测。其他已发布模式和默认 Qwen 选择保持不变。

这些维护记录不等同于本机 R4 Evidence 文件；Preset 使用静态发布合同。新增能力若无精确证据，不得以同 Provider、相似型号或单项能力推导。

## 验收

- 普通界面三个模型均可选择 OFF/ON 与 Normal/Streaming。
- 选择 Qwen 后仍默认 OFF + Normal。
- Preset 页面不出现 Probe、Evidence、连接编辑和 Secret 控件。
- Managed Custom 能力状态不能改写这些静态合同。

# Managed Custom：Streaming + Thinking OFF

Streaming、Thinking OFF 与 OFF + Streaming 是三个独立能力。前两项分别受支持，不足以推导第三项。

## 当前实现

- Capability 字段 thinking_off_streaming_combination，默认 UNKNOWN。
- R4 Resolver 对该组合单独合并证据；有冲突时保持保守状态并解释冲突。
- R5 提供显式单次 Probe：OFF、Streaming、短请求、retry=0；必须有非空正文 delta、正常 finish 和完整结束。
- 只有明确支持 / 明确拒绝可写组合证据。网络、TLS、Proxy、Timeout 等失败保留 UNKNOWN。
- Probe 不运行 Fishery Diagnosis、RAG 或 Orchestrator，也不自动执行 tool_calls。
- 成功刷新后，Managed UI 即时解锁该精确 Identity 的 OFF + Streaming；普通 Streaming/Thinking 状态不被连带修改。

## 与 Preset 的区别

Preset 不运行时查询此 Evidence Store；它只读取已发布的静态合同。2026-10-04 用户人工确认 Qwen 3.8 Flash 与 DeepSeek Flash 的 OFF + Streaming 后，两者升级至 1.0.1。Ollama Qwen3.5 4B 的对应组合此前通过单次 R5 Probe 并已发布 1.0.1。此次没有新的真实模型请求，也没有重测其他组合。

三者的日常 UI 只显示已发布模式，不显示 Evidence 或 Probe。用户可在 [Preset 发布说明](PRESET_PUBLICATION.md) 查看维护者记录。

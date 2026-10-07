# Managed Custom：Thinking OFF + Streaming 组合能力

此能力仅描述 Managed Custom 精确 Identity 的运行时 Evidence。Preset 使用静态发布合同，二者不能互相继承。

## 当前规则

- `thinking_off_streaming_combination` 是独立 Capability，默认 `UNKNOWN`。
- R4 Resolver 独立合并该组合 Evidence；单独的 Streaming 与 Thinking OFF 支持不能推出组合受支持。
- R5 显式 Probe 以 OFF + Streaming 发一次短请求，retry=0；要求收到有效正文 delta 并正常结束。
- 明确支持 / 明确拒绝可写入该组合的 Evidence。DNS、网络、TLS、Proxy、Timeout 等结果保留 `UNKNOWN`。
- Probe 仅对当前精确 Identity 生效，不运行 Fishery Analysis、Diagnosis、RAG 或 Tool Executor。

## Preset 的已发布合同

项目维护的 Qwen 3.8 Flash、DeepSeek Flash、Ollama Qwen3.5 4B 均有静态发布的 OFF + Streaming 组合；当前版本、发布组合及 Assistant 的 OFF + Normal 限制见[Preset 发布合同](PRESET_PUBLICATION.md)。Managed Evidence / Probe 不改变这些版本。

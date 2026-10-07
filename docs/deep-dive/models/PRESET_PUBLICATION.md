# Preset 发布合同

Preset 是项目维护者发布的固定模型方案。`src/fishery_ai/resources/profiles/presets.json` 是运行时来源；Preset 不从 Managed Evidence / Probe 动态改写合同。

## 当前发布项

| Preset | 固定 Identity 的 service / adapter / model | 合同 | 发布组合 | 默认 |
| --- | --- | --- | --- | --- |
| Qwen 3.8 Flash | `dashscope` / `openai_chat` / `qwen3.8-flash` | 1.0.2 | OFF、ON × Normal、Streaming | OFF + Normal |
| DeepSeek Flash | `deepseek_api` / `openai_chat` / `deepseek-flash` | 1.0.2 | OFF、ON × Normal、Streaming | 否 |
| Ollama Qwen3.5 4B | `ollama` / `generic_openai_chat` / `qwen3.5:4b` | 1.0.2 | OFF、ON × Normal、Streaming | 否 |

三项合同均发布 `tool_calling=SUPPORTED`，其资格验证是独立的一项协议能力；这不代表 Streaming Tool Calling 已实现，也不意味着 Assistant 可使用 Thinking ON 或 Streaming。Assistant v1 只允许固定的 OFF + Normal。

服务身份、Base URL、认证类型、`credential_ref`、超时、ProtocolSpec、Capability、Variants 和默认值均由模板固定。用户 UI 不编辑这些字段，不显示 Credential Ref、Evidence 或 Probe。Ollama 为 `AuthSpec.NONE`。

## 组合与证据规则

- Thinking ON、Thinking OFF、Streaming、OFF + Streaming、ON + Streaming 与 Tool Calling 是不同合同项；单项支持不能推出组合支持。
- Preset 采用 Template + Variant，连接与协议不复制到每个 UI 选项。更改身份或发布能力时须更新固定合同与版本，并审查证据。
- `verified_at` / `source` 等发布 metadata 是维护依据；运行时 Registry 的 Managed Evidence 不是 Preset 发布渠道。
- Tool Calling Qualification 对工具协议的发布依据来自每个精确 Preset 的独立资格验证，不因 Provider、型号相似或 Managed Profile Evidence 继承。
- 模型运行失败只产生本次请求错误；不会自动改变 Preset 支持状态或合同版本。

## 代码边界

- `presets.py` 加载模板，校验发布状态、精确 Identity、ProtocolSpec、Variant 和默认组合。
- `model_gateway.py` / Adapter 执行共享 Runtime、Credential Snapshot、Timeout、Usage、Streaming 与错误处理。
- Assistant 服务端另有 Preset ID 白名单，并要求 OFF + Normal + 精确发布 Tool Calling 合同。
- Preset selector 从服务端 bootstrap 数据读取名称与 ID，不把连接配置交给浏览器。

普通模型界面只展示项目已发布的选项。新增模型或组合前先维护并验证合同，不要把内部 Capability 状态直接呈现给普通用户。

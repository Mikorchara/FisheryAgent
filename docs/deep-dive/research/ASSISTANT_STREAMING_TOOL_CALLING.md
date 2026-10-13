# Assistant Streaming Tool Calling：分阶段方案

2026-10-13。研究依据为当前源码与 Provider 官方资料；本轮只实现 non-streaming 三 Tool 发布范围与 Activity 卡片，没有 Streaming 实现或真实模型请求。

## 1. 三层能力必须分开

1. **普通文本 Streaming**：现有 Analysis / Manual 已有独立流式路径。
2. **Streaming Tool Call**：将参数分片组装成一个完整 `ModelToolCall`，完成校验后才执行。
3. **多轮 Streaming**：Tool Result 进入下一次流式请求，由同一 `ToolCallingService` 继续预算与结束判断。

普通 Streaming 与 non-streaming Tool 支持，不能共同推导出 Streaming Tool 已获发布资格。当前三个 Preset 的多轮发布范围都固定 OFF / Normal；本轮没有改 Capability 或这些模式合同。

## 2. 协议资料与当前 Adapter

查询日期：2026-10-13。以下是协议资料，不是对本机 Runtime 或精确模型的真实 Streaming 资格认证。

| 当前精确目标 | 官方协议信息 | 待验证内容 |
| --- | --- | --- |
| DashScope `qwen3.8-flash` | Chat Completions 流式 `delta.tool_calls` 按 `index` 归组，arguments 分片追加。官方兼容 API 明确列出 qwen3.8-flash 的 `tool_stream`：简单参数只需 `stream=true`；array/object 复杂参数可选择流式分片或一次输出。 | 当前地域、OFF 与 Tool 组合、调用 ID、正常结束、usage 与 Stop 的真实表现。当前三个 Tool 参数是空 object 或 query string，不需为了流式而盲目添加 `tool_stream`。 |
| DeepSeek `deepseek-flash` | 当前 Chat Completions Reference 列出该模型及流式 Tool schema：首个 call chunk 带 id/type/function，后续 arguments 继续返回；终止为 SSE `[DONE]`。当前文档说明 usage 在最后一个带 finish_reason 的内容 chunk 上，不能只识别空 choices 的 usage-only chunk。 | 精确模型/协议的分片和终止 fixture，再做单案例资格；不沿用旧模型结论。 |
| Ollama `/v1`，`qwen3.5:4b` | 官方兼容文档列出 Chat Completions 的 Streaming、Tools、stream_options。原生 `/api/chat` 教程收集结构化 tool_calls；官方 main 分支兼容转换将 arguments object 序列化为字符串并传 index/id。 | 本机服务版本与 `/v1` 实際 delta 形态、ID/finish/usage；main 源码不是当前安装版本。不能把原生 `/api/chat` 的完成 object 当作 `/v1` 增量协议使用。 |

来源：Alibaba [Function Calling](https://help.aliyun.com/en/model-studio/qwen-function-calling)、[OpenAI 兼容 Chat](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions/)；DeepSeek [Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)；Ollama [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)、[Tool calling](https://docs.ollama.com/capabilities/tool-calling)、[官方兼容转换源码](https://github.com/ollama/ollama/blob/main/openai/openai.go)。

**当前实现明确不支持 Streaming Tool**：

- `model_gateway.validate_tool_request(..., streaming=True)` 遇 tools、assistant calls 或 tool messages 就拒绝 `TOOL_STREAMING_NOT_IMPLEMENTED`。
- `openai_compatible_adapter._event()` 遇 `delta.tool_calls` 同样拒绝；`ModelEvent` 只有正文/推理 delta、finish_reason 与 Usage。
- Adapter 已有同步/AsyncOpenAI bridge、队列、SDK stream/client 关闭、RequestHandle 与剩余 deadline，可以复用传输生命周期。
- `ToolCallingService` 目前取得完整 `gateway.complete()` 响应，再执行相同 Executor；Web Assistant 使用 JSON 最终响应和累计 Activity 轮询，不提供流式正文接口。
- Manual Raw 可传输/展示 Tool 字段，但不组装授权调用、不执行 Tool，不能用它绕过正式门禁。

## 3. 最小 assembler 合同（建议，未实现）

```text
每次 Model request 的 SDK chunk
  → Adapter 内受限 assembler（按 choice/index 分组）
  → finish + 正常传输结束 + stream/client 关闭
  → 完整 ModelResponse / ModelToolCall
  → 同一 Coordinator → Policy / Registry / Validator / Executor
  → Result + 独立 Receipt → 下一次 Model request 或 Final
```

- 第一版只接受一个 choice、一个 Tool index。出现第二个调用，整轮拒绝，不先执行第一个。
- 限制 chunk 数、内容/arguments 总字节、JSON 深度和整 Turn 时间；保留空 delta、usage-only 与末尾带 usage 的内容帧。
- id/type/name 独立于 arguments 处理：首帧赋值、空片段忽略，分片或重复字段按已经确认的协议处理；冲突身份拒绝。不要把每个 id/name 重复片段盲目追加，也不要自动修 JSON。
- **可解析的 JSON 不代表流已完成**。等可靠的 request terminal 与正常传输结束后，才建立 ToolCall；EOF、取消、length、content_filter、异常分片或缺 ID/名字/arguments 都不能执行。Provider 的 terminal 差异由 Adapter 归一化，不能让 Coordinator 根据厂商名字判断。
- 完整 arguments 还需经 T1 合同和现有 Executor 的 object / Schema / Policy 校验；正文中模拟调用不产生 Tool、Receipt 或能力证据。
- 收到任何可观察 delta（包括 Tool 元数据或 arguments）就记为已产生输出，禁止透明重试。本路径始终 retry=0。

建议先在 Adapter 内组装完整响应，保持 Coordinator 的同一个循环；以后增加安全 progress 回调或 transport 选项，不复制 `Model → Tool → Model` 编排。`ProtocolSpec` 只负责请求参数编码，不能容纳 assembler、预算或 Provider 行为路由。

## 4. 多轮、取消与提交

继续使用 2 Calls / 2 Rounds / 3 Requests，每轮一个 Tool；Result 回传后模型可提前 Final。第三请求禁用 Tool，超预算不发送第四请求。

同一 Turn 冻结 Runtime、Credential、Policy、release revision 与 Prompt/History；每个 Model stream 使用剩余整 Turn deadline，不重置总预算。Stop 必须 cancel SDK task、关闭 iterator/stream/client；关闭完成前不执行 Tool、不开始下一轮。取消和 TOTAL_TIMEOUT 分开，不能宣称远端推理或计费已停止。

Usage 按每个 Model step 独立记录再聚合；同一请求的累计 usage 不能按 chunk 重复相加。中断时保留已收到 usage，没有最终统计则明确未知。后续失败保留已有 steps / Ledger 审计，最终 Turn 不成功提交。

只有正常 Final、Source Gate、Trace 写入和最终取消检查都通过，才能提交一条成功回答及一个文本 History pair。Tool protocol、Ledger、参数和 Raw Result 不进入 History。

## 5. Steps UI 与流式正文

现有累计 Activity 轮询足以呈现 Model/Tool 的开始、完成、拒绝、失败与取消，不丢快速步骤；每个 Tool 使用本轮新增的独立卡片。参数组装是 Model step，不应提前出现“Tool 已执行”。

真正逐字正文需要以后单独评审事件接口（如 SSE）：绑定 request_id、step序号、递增revision，并发送安全 pending-text / activity / final / error。中间模型正文不能当成最终回答；Tool arguments、Raw Result、推理原文和 Prompt 不进入事件。

第一小步可以全部缓冲 Model step，先证明协议闭合与多轮 parity；随后才做正文预览。若允许 auto Tool 的请求先输出正文又输出调用，预览必须标为临时并可撤回；最终成功由原 Commit Gate 决定，轮询 Completed 本身不提交。跨 chunk Secret 脱敏需受限缓冲，不能对单个 fragment 替换后立即公开。

## 6. 推荐实施顺序与验收

1. **离线协议基础**：assembler + fake SDK，先 1/1/2。覆盖 id/name/arguments 分片、转义/Unicode、多 index、混合正文、usage、重复/冲突字段、缺 finish、断流、length、取消和清理；不开放 UI。
2. **同一 Runtime 接入**：以完整 ModelResponse 驱动现有循环，验证三条路径与 2/2/3 预算、Result 传递、Ledger、deadline、Trace 和原 Normal parity。
3. **受控资格与发布**：另获逐案例授权，按 exact identity、服务版本、协议/Prompt/History、Tool 集合和 Streaming 模式登记独立范围；不能自动继承本轮 non-streaming 实验资格。
4. **产品流式 UI**：独立事件合同、临时正文、安全文本渲染、Stop/迟到事件/epoch/重连边界；不重发模型请求。保留 Normal 回滚路径。

主要风险：在完整收流前执行、把多 call 分片误当单 call、重复累计 Usage、不同 Provider 终止差异、取消后继续下一轮、未脱敏片段公开及半成品成功提交。暂不做 Thinking ON Tool、并行 Tool、Agent、自动重试/failover 或修改 Analysis Streaming。

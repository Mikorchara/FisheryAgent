# Tool Orchestration 架构研究

审查日期：2026-10-08。源码基线：`6b9dad9`，以当前工作树源码和测试为准。

本报告只研究扩展方案。没有修改源码、测试、运行配置或 Preset 合同，没有调用真实模型。官方资料用于研究协议，不用于自动发布模型能力。文中的“建议”及未来类型、错误码均尚未实现。

> **后续状态注记（2026-10-09，不改写上文基于 `6b9dad9` 的结论）**：本报告的源码基线是 `6b9dad9`。其后已实施两项地基变更 —— 受控参数合同（`ToolDefinition.validate_arguments`，Executor 在 Handler 之前完成拒绝/归一化）与 `ToolStatus.NO_MATCH`。因此文中"参数必须是空对象"与"status 仅 `OK/PARTIAL/NOT_SCORABLE/NO_DATA/ERROR`"两处描述**已非当前状态**。当前事实以 [`../tools/ADDING_A_TOOL.md`](../tools/ADDING_A_TOOL.md) 与 `docs/copilot/` 的两份 before/after 对照记录为准。

## 1. 当前真实架构

### 1.1 调用链与模块职责

```text
Analysis Orchestrator / AssistantService / Development Tool Conversation
    ↓ 构造各自的 Context，捕获 RuntimeSnapshot 与 ToolPolicy
ToolCallingService.run_request()
    ↓ Policy 从 Registry 取得允许的 ModelToolDefinition
validate_tool_request() → ModelGateway.complete() → OpenAICompatibleAdapter
    ↓ Request #1 → ModelResponse.tool_calls
ToolCallingService 校验响应与调用数量
    ↓ 完整 ModelToolCall
ToolExecutor.execute()
    ↓ Registry allowlist → Policy → 参数校验 → 固定 Handler
CurrentWaterQualityReader.query() → DiagnosisService / WaterQualityScoringService
    ↓ ToolExecutionResult
assistant(tool_calls) + tool(tool_call_id, result JSON)
    ↓ Request #2，tool_choice="none"
ModelGateway.complete() → 最终正文
    ↓ Usage 汇总、安全 Trace、Analysis Activity / Assistant Activity
```

| 当前文件（相对仓库根） | 实际类 / 函数 | 输入 → 输出 / 边界 |
| --- | --- | --- |
| `src/fishery_ai/model_gateway.py` | `ModelToolDefinition`、`ModelToolCall`、`ModelMessage`、`ModelRequest`、`ModelResponse` | 不可变工具协议合同；完整 arguments 必须是 JSON object |
| 同上 | `validate_tool_request()`、`ModelGateway` | 请求与 Runtime → 能力门禁；complete / stream 接口 |
| `src/fishery_ai/openai_compatible_adapter.py` | `OpenAICompatibleAdapter._kwargs()`、`_response()`、`_event()`、`_bridge()` | 合同 ↔ SDK；编码工具消息，归一化完整调用，管理传输与取消 |
| `src/fishery_ai/tool_conversation.py` | `ToolCallingService.converse()`、`run_request()` | Context + Runtime → `ToolConversationResult`；唯一共享协调流程 |
| `src/fishery_ai/tools/registry.py` | `ToolRegistry.lookup()`、`model_definitions()` | 两个静态 Tool；定义与 Handler 的单一来源 |
| `src/fishery_ai/tools/policy.py` | `ToolPolicy.model_definitions()`、`allows()` | Policy 只缩小 Registry 授权；不能注册新函数 |
| `src/fishery_ai/tools/catalog.py` | Catalog metadata | 展示说明，不授予执行权限 |
| `src/fishery_ai/tools/executor.py` | `ToolExecutor.execute()` | 完整调用 → 安全 `ToolExecutionResult`；不调用模型 |
| `src/fishery_ai/tools/handlers/current_water_quality.py` | `get_current_water_quality()` | Reader → 水质事实、Findings、时间、来源、rule_version |
| `src/fishery_ai/tools/handlers/water_quality_score.py` | `score_current_water_quality()` | Reader → 实验评分及对应水质；不运行 RAG / LLM |
| `src/fishery_ai/telemetry/current.py` | `CurrentWaterQualityReader.query()` | 当前 Store → query-time Freshness view；不修改原 Snapshot |
| `src/fishery_ai/execution.py` | `RequestHandle`、`request_scope()`、`check_cancelled()` | 请求级生命周期、共享取消信号、当前 SDK I/O 的取消 hook |
| `src/fishery_ai/observability.py` | `JsonlTraceSink.record_tool_conversation()` | 安全元数据 → JSONL；不持久化完整 Prompt / Tool Result |
| `src/fishery_ai/application.py` | Orchestrator、`_analysis_tool_activity()` | 固定 Analysis Context + 可选 Tool；Tool 观测不覆盖原 Facts |
| `src/fishery_ai/assistant.py` | `AssistantService.send()`、Assistant Context / Result | 三 Preset、OFF + Normal、有限成功历史；无事实预取 |
| `src/fishery_ai/resources/web/app.js` | Assistant / Analysis Activity 与运行状态显示 | 安全投影；当前只展示单 Tool、Request #1 / #2 |

### 1.2 限制在哪里

| 限制 | 当前确切实现 | 扩展含义 |
| --- | --- | --- |
| 最多 1 个 Tool Call | `run_request()` 首轮 `len(calls) > 1` 返回 `TOOL_CALL_LIMIT`；随后创建 `ToolExecutor(..., max_calls=1)` | 模型协议可表达多个调用，但应用明确拒绝，不是 SDK 无法解析 |
| 最多 1 个 Tool round | 首轮执行后只发一个 follow-up；第二轮仍有 calls 返回 `TOOL_ROUND_LIMIT` | 通过分支结构限制，没有可配置的 round budget |
| 最多 2 次模型请求 | `steps` 固定两个元素，只调用 `complete(request, 0)` 与 `complete(follow_up, 1)` | 没有独立的 `max_model_requests` 计数合同 |
| 不支持 Streaming Tool Calling | `validate_tool_request(..., streaming=True)` 拒绝；Adapter `_event()` 遇到 tool delta 也拒绝 | 两层主动保护；不能只删除一个检查就宣称支持 |
| 参数与结果上限 | Executor arguments UTF-8 ≤ 4096 bytes；单结果默认 ≤ 32768 bytes | 已有限制，但缺少跨调用、跨轮累计预算 |
| 重复 call ID | Model 合同拒绝同一 tuple 重复 ID；Executor `_seen` 拒绝重复执行 | 目前只覆盖实例生命周期；多轮必须共享同一请求账本 |

Executor 构造参数允许 `max_calls` 在 1～8 内，但当前 Coordinator 固定传 1。修改这个数值仍不足以得到 Multi-Tool：跟进消息、结果合同、错误处理、Usage / Trace / UI 均有单调用假设。

当前 `ToolConversationResult` 只有一个 `tool_result`、`tool_name`、`tool_call_id`、`tool_duration_ms`；`request_1/request_2` 也是固定字段。Analysis / Assistant 投影和取消阶段名称沿用这一结构。

## 2. 架构质量与优点

以下评分针对当前已发布的只读、单 Tool、单轮功能；扩展缺口不等同于当前实现失效。

| 维度 | 评价 | 源码依据与理由 |
| --- | --- | --- |
| 1. Tool Definition | GOOD | 冻结合同，Registry 定义单一来源；当前无参 schema 清晰。不是通用 JSON Schema 校验器 |
| 2. Registry | GOOD | 两个显式 allowlist Handler，无扫描、动态 import、eval / exec |
| 3. Policy / authorization | GOOD | Catalog 不授权，Policy 只限制 Registry；请求使用捕获的 Policy |
| 4. Executor | ACCEPTABLE | 参数、重复 ID、预算、序列化、错误脱敏集中；目前只支持空 object，无批次预检或 Handler deadline |
| 5. Handler | GOOD | 读取 canonical Reader，委托 Domain 判断 / 评分；无模型、网络、写操作 |
| 6. Model protocol abstraction | GOOD | nullable content + tool_calls、role=tool、call ID、follow-up 已归一；流式事件尚缺工具片段 |
| 7. Tool Call ID lifecycle | ACCEPTABLE | 单步唯一 ID 与单 Executor 防重已有；缺少跨轮账本、片段身份与长度限制 |
| 8. Error handling | ACCEPTABLE | 安全错误码、业务 NO_DATA 与失败分开；当前任一执行错误终止，没有部分成功语义 |
| 9. Cancellation | GOOD | 单活动 SDK 请求可取消并关闭 I/O；本地 Handler 合作式检查，远端停止保持 unknown |
| 10. Budget control | NEEDS IMPROVEMENT | 有固定 call / round / request 限制；缺少统一总 deadline、累计结果 / Context 预算与无进展检测 |
| 11. Trace / observability | ACCEPTABLE | 单调用两请求的安全 Trace 与 Usage 已有；未来需 steps / rounds / calls 列表 |
| 12. Result size limits | ACCEPTABLE | 单结果 32 KiB 门禁有效；在序列化后检查，尚无累计 / 生成前内存保护 |
| 13. Capability gating | GOOD | UNKNOWN 阻止正式高级请求；Preset 固定合同与 Managed Evidence 分离 |
| 14. UI / Activity | GOOD | 正式 UI 轻量且安全，开发 Trace 独立；未来需要多个调用和流式阶段的投影 |
| 15. Provider isolation | GOOD | SDK / 协议编码留在 Adapter / ProtocolSpec；业务不解释厂商 tool delta |

保留现有 Registry、Policy、Executor、Reader、Domain、Gateway、CredentialSnapshot 与取消基础。没有引入框架或重写执行栈的必要。

## 3. 当前限制与潜在扩展风险

- `ModelEvent` 只有正文 delta、reasoning delta、Usage、finish_reason，不能表达工具 index / ID / 名称 / 参数片段。
- `ModelToolCall` 要求完整有效 JSON，不能作为正在累积的 fragment 容器。
- `run_request()` 是有限的两段流程，尚无统一预算状态；不应把两个分支直接改成无界 while。
- Handler 为同步零参数 callable。取消检查位于执行前后，不能强制终止一个阻塞 Handler。
- Adapter timeout 是每次模型调用的 timeout，两次请求与本地 Tool 没有共享总时间截止。RequestRegistry TTL 是生命周期清理，不能代替执行 deadline。
- 首轮 Tool 响应校验目前主要检查调用结构，没有以 `finish_reason` 明确排除 `length` 后再执行的完整结束策略；Streaming 扩展必须补上，不能只以 JSON 恰好可解析作为完成证据。
- Assistant 历史仍应只保留完整成功问答；多轮 Tool 消息只能是本次 Send 内 Context，不能变成“当前事实”的长期来源。
- Assistant 和正式 Analysis Tool 路径将 retries 设为 0；通用 `converse()` 本身没有统一强制 runtime retries=0。未来共享 Tool orchestration 应明确这一策略。

这些是研究发现的扩展准备项，本轮没有更改稳定代码。

## 4. Streaming Tool Calling

### 4.1 六个概念不能混用

| 概念 | 含义 | 建议 |
| --- | --- | --- |
| A. Streaming text | 模型正文逐段输出 | 现有普通 Analysis 已支持；保留 |
| B. Tool-call delta | SDK 返回工具 index、ID、名称、arguments 片段 | Adapter 归一为专用事件 |
| C. Arguments assembly | 按对应调用拼接 JSON 字符串 | 专用 Accumulator，纯数据处理 |
| D. 完整调用后执行 | 全部模型调用生成结束、校验通过后执行 | 推荐第一版 |
| E. Streaming Tool Execution | 参数未完成就开始执行 Handler | 第一版禁止，见第 5 节 |
| F. Streaming final answer | Tool Result 回传后第二次模型正文流输出 | 可在同一 Gateway / Coordinator 上演进 |

### 4.2 推荐状态机

```text
PREPARING
→ STREAMING_REQUEST
→ RECEIVING_TOOL_CALLS / RECEIVING_TEXT
→ MODEL_TURN_COMPLETE
→ VALIDATING_COMPLETE_CALLS
→ RUNNING_TOOLS
→ FOLLOW_UP_REQUEST
→ STREAMING_FINAL_RESPONSE
→ COMPLETED

任何阶段 → CANCELLED / FAILED / TRUNCATED
没有 Tool → 完整正文结束后直接 COMPLETED
```

第一版保留最多一个 Tool、一个 round、两个模型请求；首轮正文可能与 tool_calls 同时出现，不能提前把它作为成功 final message。第二轮保持 `tool_choice="none"`，仍有 Tool Call 则拒绝。

### 4.3 推荐新增 ToolCallAccumulator

建议新增小型、纯数据组件，而非把拼接逻辑塞进 Executor、Web 或 Handler。Adapter 只归一 Provider delta；Coordinator 拥有 request-scoped Accumulator；Accumulator 最终输出已有 `ModelToolCall[]`。无需另建重复的 CompleteToolCall 业务合同。

未来最小事件需要：model step、choice index、tool index、可选 ID / type / name 数据、arguments fragment、finish / transport completion；正文、reasoning、Usage 保持独立。以下规则为建议：

1. 使用 `(model_step, choice_index, tool_index)` 分桶。默认只支持一个 choice；不能把不同 choice 拼成同一条调用。
2. ID / type 可在后续到达；保留并校验一致性。结束时必须有合法 ID、function type、name；不伪造缺失 ID。ID 冲突或跨桶重复拒绝。
3. name 是完整字段还是增量字段由 Adapter 的明确协议规则决定；完整名称重复时校验一致，不盲目重复连接。名称 / ID 长度、tool index 数量都要有上限。
4. arguments 只按事件顺序原样拼接字符串，限制每调用及总 UTF-8 bytes。不能逐片 `json.loads`，不能自动补括号、推断 `{}`、去重片段或使用 LLM repair。
5. 所有桶组装完成后一次解析 JSON，要求 object，再交 Registry / Policy / 参数校验。Executor 不处理 fragment。
6. 即使中途拼成合法 `{}`，也等待整个 assistant turn 正常结束；后续可能追加参数、产生第二个调用或触发 call budget。
7. `length`、内容过滤、中断、缺少可确认的结束、未闭合 JSON、取消均不执行。不同 Provider 的正常结束形态由 Adapter 归一；不能把任意 EOF 当成功。
8. Usage 可以与 finish 同块、独立出现或完全缺失；不是 Tool 完成信号。不能看到 finish 就立即退出并丢掉末尾 Usage。
9. Tool delta 一旦被接受，计为已产生可观察协议输出；即使未向用户显示正文，也禁止透明重试生成新的 ID / arguments。
10. stream / iterator / SDK client 由当前请求所有者关闭。中途失败丢弃未完成调用；已执行 Tool 后不得重新播放整个会话。

交错 fixture 示例：index 0 的 arguments 收到 `{"query":`，index 1 收到 `{}`，index 0 再收到 `"低氧"}`。两个缓冲区分别形成完整 JSON；结束后按 index 排序输出，匹配各自 ID。`query` 只是未来参数型 Tool 的测试示例，当前两个 Tool 均只允许 `{}`。

## 5. Streaming Tool Execution：第一版禁止

提前执行可能减少等待，但当前 Handler 很快，实际收益有限。风险包括：尚未完整的参数改变含义、最终名称 / 授权未确定、后续多调用超预算、执行过的读取无法撤回、取消时部分结果难以归属、恢复时重复执行。

READ ONLY 也有可观察效果：读取时刻不同、资源消耗、返回不同 Snapshot。未来写 Tool 更不适合提前执行。JSON 前缀可解析不代表模型已完成调用。

建议只允许“完整模型 turn → 校验 → 执行”。若未来 Handler 自身需要分块返回，应另行设计 Handler 结果流合同；它也不等于参数生成期间投机执行。本轮两者都不实现。

## 6. 同一轮 Multi-Tool

### 6.1 第一版推荐 Sequential

| 维度 | 顺序执行 | 并行执行 |
| --- | --- | --- |
| 行为可复现 | 执行顺序与消息顺序明确 | 完成顺序不确定，需归一输出 |
| Cancellation | 一个活动任务，复用现有机制较容易 | 必须传播到任务组并等待清理 |
| Snapshot | 每次调用仍可能读取不同 Snapshot | 同样不保证一致，竞争窗口更难说明 |
| 资源 / shared state | 容易限制与定位 | 需要并发安全声明、资源上限、ContextVar 传播 |
| Latency | 执行时间相加 | 独立、慢 I/O Tool 才有明显收益 |
| 当前价值 | 两个本地 CPU / 读取 Tool 足够快 | 不值得现在引入并发执行栈 |

Provider 的 `parallel_tool_calls` 表示模型可一次返回多个调用，不代表程序必须并行执行这些 Handler。厂商参数仍由 Adapter / ProtocolSpec 编码，不能作为授权。

### 6.2 执行与消息合同

- 完整批次先检查 ID、allowlist、Policy、参数、调用数量与剩余预算；未知 / 未授权 / 超量调用在任何 Handler 执行前拒绝，不能只取数组前两个。
- 每个执行结果保留自己的 `tool_call_id`、Tool name、status、duration、evaluated_at / source（适用时）。不要把多个结果压成一个无归属 object。
- 回传一次完整 `assistant(tool_calls=[...])`，随后每个 ID 恰好一个 `role=tool` 消息；按原调用顺序组织，而非按并行完成顺序。
- 可恢复错误允许形成对应 ID 的安全错误结果；致命错误直接结束，本地保留安全 partial activity，不向 Provider 发送缺失部分 Tool Result 的消息序列。
- 同一模型请求 Usage 只记一次，不能按 Tool 个数重复累加。分别记录每 Tool duration、该轮执行 wall time 与整次 Send latency。
- 每结果上限 + 累计结果上限 + 后续 Context 上限共同控制；不能靠模型摘要作为唯一限流。

### 6.3 当前 Snapshot 的时间一致性

两个 Handler 各自调用 `reader.query()`，中间 Apply 新 Snapshot 时可能读到不同事实。只读、顺序执行或并行执行都不保证“同一份现场”。当前 Analysis 捕获的 Facts 也可能早于 Tool 查询。

第一版优先保留每次读取的时间 / 来源，并明确结果差异；不覆盖固定 Analysis Facts。若产品确实要求同轮一致，再引入显式 round-level read view，让相关 Handler 使用同一捕获视图、复用 Domain Freshness 逻辑，不修改 Store。跨用户 Send 不能复用旧视图冒充当前。

当前评分 Tool 已返回它使用的水质，通常无需与查询 Tool 同时执行。未来 Knowledge Tool 暂停且未实现，不能作为现在优先开发 Multi-Tool 的既成需求。

## 7. 有限 Multi-Round 与 Agent 边界

建议由现有 Coordinator 演进为 request-scoped 的有限状态机，不在 Executor 或 Web 建模型循环。每轮都复用同一 RuntimeSnapshot / CredentialSnapshot / Policy 与执行账本。

```text
模型请求 → 完整调用批次 → 检查总预算 → 校验并执行
    ↓ 追加 assistant / tool messages
仍有 Tool round 与模型请求预算：允许下一轮选择
已到最后总结请求：tool_choice="none"
    ↓ 最终正文或明确 limit error
```

必须为最终回答预留一次模型请求；即使已设 `tool_choice="none"`，Provider 继续返回 calls 也不能越界。预算耗尽不能自动扩容。

生命周期账本分开处理：

- **duplicate ID**：同一 Send 中已接受的 ID 再出现即拒绝，即使函数名变化；不能逐轮重建 Executor 清空 `_seen`。
- **identical call**：以函数名 + 规范化且已校验参数形成内存 fingerprint；新 ID 不代表新工作。当前空参水质查询在一次 Send 内默认不重复。
- **no progress / cycle**：对调用序列与安全结果状态 / 版本变化做有限记录，拦截重复 A、A→B→A 及重复无新信息的调用。内部 digest 不持久化敏感内容；不要让 LLM 判断是否进展。
- 只有未来明确的“结果变化后重读”产品规则才例外允许重复；不能以自动缓存旧读取解决循环问题。硬预算仍是最终保障。

一次用户 Send、固定 2～3 轮、无后台任务、无长期目标、无自主调度，属于 **Bounded Tool Orchestration**。多个 Tool / 多轮本身不等于 Agent。自主规划长期目标、持续调度、跨任务记忆与独立操作授权属于另一产品边界，不随扩展默认开启。

## 8. 推荐预算合同

以下是未来试验的起始值，不是修改当前配置的指令。先保留当前 1 / 1 / 1 / 2 限制，按阶段逐项开放。

| 预算 | 当前状态 | 后续最小试验建议 / 原因 |
| --- | --- | --- |
| `max_tool_rounds` | 结构上 1 | Multi-Tool 仍 1；Multi-Round 初次 2；防连续索取工具 |
| `max_tool_calls_total` | 1 | 首次扩展 2；防跨轮累计失控 |
| `max_tool_calls_per_round` | 1 | Multi-Tool 2；Multi-Round 单独验证时仍 1 |
| `max_model_requests` | 结构上 2 | Multi-Tool 2；两个 Tool round 至多 3；含最终总结 |
| `max_elapsed_ms` | 无会话级总 deadline | 起始可采用 Cloud 120000 / Local 180000，来自现有模板 total timeout；覆盖所有阶段，不逐请求重新获得完整预算 |
| `max_tool_elapsed_ms` | 无 Handler deadline | 当前本地 Handler 可先试 1000；以离线测量校准，须先有合作式超时保障 |
| `max_tool_arguments_bytes` | 每 call 4096 | 保持 4096，并对两调用总量设 8192；流式累积期间立即检查 |
| `max_tool_result_bytes` | 默认 32768 | 先保留 32768，避免兼容变化；不是建议增加 |
| `max_total_tool_result_bytes` | 无 | 起始 32768；单结果各未超限仍可能合计超限 |
| Context / 输出 token 预算 | Assistant 历史另有限制 | 对新增 Tool messages 的累计 bytes 设限，并设置明确输出上限；历史限额不能覆盖本轮结果 |

调用数、轮数、模型请求数互不替代：一轮可有多个调用；失败也消耗尝试预算；无 Tool 回答也消耗模型请求。总时间用 monotonic deadline，各 SDK 调用只使用剩余时间与自身 timeout 的较小值。

序列化后的大小门禁不能阻止 Handler 先分配巨大对象；未来慢 / 大结果 Tool 必须在源头限制记录数与字段。已耗费用的请求 Usage 即使最终失败也要保留可获得的统计；缺失显示 unavailable，不当作 0。

## 9. 推荐错误矩阵

当前行为：Executor 返回 ERROR 时 Coordinator 立即失败，不发 Request #2。下表为未来 Multi-Tool / Multi-Round 的明确建议，不宣称已实现部分成功。

| 情况 | 继续其他 Tool？ | 后续模型处理 | 推荐语义 |
| --- | --- | --- | --- |
| OK / NO_DATA / PARTIAL / NOT_SCORABLE | 是 | 解释结果 | 正常业务结果；NO_DATA 不编造 normal |
| unknown / unauthorized Tool | 否，批次预检拒绝 | 不继续 | UNKNOWN_TOOL / TOOL_NOT_ALLOWED；授权失败不能靠模型修复 |
| malformed call / 非 object / schema 不合法 | 第一版否 | 不继续 | MODEL_TOOL_CALL_MALFORMED / INVALID_TOOL_ARGUMENTS；不自动修复参数 |
| duplicate tool_call_id | 否 | 不继续 | 拒绝重复执行；跨轮也适用 |
| 超 call / round / 总预算 | 否 | 仅预先预留且协议完整的最终总结可用；否则失败 | 明确 limit；不能静默跳过部分 calls |
| 一个已授权 Handler 可恢复失败 | 可继续独立 Tool | 以匹配 ID 的安全错误结果解释已有信息 | 需显式分类，不能把所有 Exception 都设为可恢复 |
| 部分成功 | 可 | 最终说明成功项及缺失项 | 整体 PARTIAL，不假称全部完成 |
| 全部可恢复失败 | 不开新 Tool round | 有预留预算时最终解释失败 | 不自动重试工具 / 模型，不生成无依据事实 |
| Tool deadline | 只有确认停止 / 隔离后可继续 | 解释安全失败状态 | 不能留下仍在读资源的任务后继续假称完成 |
| 用户取消 | 否 | 不发后续模型请求 | USER_CANCELLED；不提交部分 final history |
| 模型网络 / TLS / Proxy / timeout | 否 | 不自动重播会话 | 使用既有安全传输错误，不写 UNSUPPORTED |
| stream 未完整结束 / JSON 未闭合 / length | 否，不执行未完成 calls | 不提交成功正文 | 中断 / malformed / truncated，保留安全已完成阶段 |
| 第二轮违规请求 Tool（当前） | 否 | 不发第三次请求 | TOOL_ROUND_LIMIT，当前行为保持 |
| 重复相同调用 / 无进展循环（未来） | 否 | 只允许预算内最终总结，或失败 | 可新增 TOOL_NO_PROGRESS；不凭新 call ID 放行 |
| 结果过大 / 序列化异常 | 默认否 | 不发送原始巨大对象 | TOOL_RESULT_TOO_LARGE / TOOL_EXECUTION_ERROR |

每个 tool result 的业务 status 与整次会话的 COMPLETED / PARTIAL / FAILED / CANCELLED 分开。错误结果是 data，不提升为 system instruction；不返回 traceback、Secret 或私有路径。

## 10. Cancellation

现有请求作用域与 AsyncOpenAI bridge 可复用，不能把 browser Abort 当作后端已停。Tool delta 接收中取消：关闭流、丢弃未完成调用；Tool 前取消：不执行；Tool 后取消：不发 follow-up；最终正文生成中取消：不提交成功 history。

当前同步 Handler 只在前后检查，不能保证中途立即停止。未来慢 Handler 要接收执行 context / cancellation token，并在安全点主动检查；没有可取消的阻塞 API 时必须如实限制承诺。

并行实现前需补任务组：RequestHandle 现在只绑定一个 `_hook`，多个 worker 不能各自覆盖它；取消由单一所有者传播到所有子任务，确认 I/O 与 iterator 清理，显式传播 ContextVar。不要为此先写第二套取消机制。

继续区分：UI 停止、backend I/O 关闭、remote compute / billing 停止。第三项没有 Provider 证据时保持 unknown。取消不写能力失败，不触发重试，不撤销已完成的读取时刻。

## 11. Trace 与 UI

建议内部结果逐步演进为 `model_steps[] / tool_rounds[] / calls[]`，保留当前 request_1/request_2 投影兼容。每调用关联 request ID、round、model step、call ID、Tool name、safe status、duration、数据时间；每模型 step 独立 Usage / finish_reason，整次 Send 正确汇总。

正式 Assistant 只显示“使用了 2 个 Tool”及可展开名称、状态、耗时、freshness / evaluated_at 与评分 Experimental 标识。多轮必要时按 Round 1 / Round 2 分组，不默认展示内部 Trace。Analysis 继续保留固定 Observed Facts 与 Tool 新观测的区别。

运行条可显示：Preparing → Receiving tool call → Running tools → Follow-up request → Streaming final response → Completed / Cancelled / Failed。正文流预览在正常完成前不能进入成功历史。

Development Trace 可以显示分轮分调用、安全参数摘要、delta 数量、组装字节数、首次协议 delta 时间、最终正文首 token 时间、finish、Usage、错误。参数原文与完整结果不默认记录，Prompt / reasoning / Secret / Credential path 永不进入常规 Trace。

必须分开测量：首次事件、首次 Tool delta、首次最终正文、总 latency。不能将早到的工具参数片段称为“最终回答 TTFT”。

## 12. Provider 兼容性：官方研究与源码事实分开

### 12.1 当前实际 Identity

直接来自 `src/fishery_ai/resources/profiles/presets.json`，三个合同均为 1.0.2；本轮只读取非 Secret 模板，没有读取 Credential 值。

| 模型 | service / adapter | base_url / exact model | 当前资格边界 |
| --- | --- | --- | --- |
| Qwen 3.8 Flash | dashscope / openai_chat | `https://dashscope.aliyuncs.com/compatible-mode/v1` / `qwen3.8-flash` | 维护者 Tool Qualification 为 OFF + Normal |
| DeepSeek Flash | deepseek_api / openai_chat | `https://api.deepseek.com` / `deepseek-flash` | 同上 |
| Ollama Qwen3.5 4B | ollama / generic_openai_chat | `http://127.0.0.1:11434/v1` / `qwen3.5:4b` | 同上；Auth NONE |

独立 Streaming、Thinking、non-streaming Tool 支持不能推出 Streaming + Tool 或 Multi-Tool / Multi-Round 已发布。官方协议描述也不能自动改合同。

### 12.2 官方资料结论

所有下列资料查询日期为 **2026-10-08**，只采用 Provider 官方来源。

| Provider / 文档 | 外部研究结论 | 对本项目的约束 |
| --- | --- | --- |
| OpenAI：[Function calling](https://developers.openai.com/api/docs/guides/function-calling) | Chat Completions delta 用 index 归属调用；ID / name / type 经常只在首片出现；arguments 为字符串片段 | 按桶组装，不要求每片重复 metadata；这是协议资料，未测试 OpenAI 模型 |
| OpenAI：[Streaming events](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events) | tool delta metadata 可选；finish_reason 区分 stop / length / tool_calls 等 | 完整结束后再执行，不能解析到 JSON 就执行 |
| OpenAI：[Create chat completion](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) | include_usage 可产生末尾空 choices 的 Usage 块；中断时可能收不到统计 | 支持 Usage-only 事件及 unavailable |
| DashScope：[Function Calling](https://help.aliyun.com/zh/model-studio/qwen-function-calling) | 官方展示按 index 累加 arguments 的流式例子；另展示 parallel_tool_calls 及模型相关限制 | 示例模型不等于当前 exact Preset；参数支持与本地执行并发分开 |
| DeepSeek：[Tool Calls](https://api-docs.deepseek.com/zh-cn/guides/tool_calls/) 与 [Chat Completions](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/) | 文档展示 deepseek-flash；首 tool chunk 含 ID / type / function，后续给参数；末尾内容块附 Usage，非独立 Usage-only 块；结束原因还包括资源不足 / aborted | 不能强制所有 Provider 使用空 choices Usage；临时中断不解释为能力不支持 |
| Ollama：[Tool calling](https://docs.ollama.com/capabilities/tool-calling) | 原生示例有多 Tool 与流式累积；原生 arguments 是 object，结果可使用 tool_name | 原生 `/api/chat` 示例不能直接当作 `/v1` 的字符串 fragment / call ID 合同 |
| Ollama：[OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility) | `/v1/chat/completions` 列出 Tools、Streaming 及 stream_options.include_usage | 仍需 exact 模型 + Runtime 版本的组合验证；当前 Ollama Preset streaming_usage 仍 UNKNOWN |

Provider 差异留在 Adapter 的事件归一和受控 ProtocolSpec 编码；Accumulator 不按 provider 名猜字段。当前归一器只处理 choices[0]，未来第一版应明确限制 n=1，并对异常 choice index fail closed。

本轮未验证精确模型流式工具参数分片、多调用交错、并行参数、Thinking + Tool 的历史要求与停止行为。任何这些扩展都要独立资格测试；不把文档示例中的无界 while、打印原始参数或异常方式复制到本项目。

## 13. 离线测试策略（仅设计）

本轮读取现有测试，没有修改或执行 Python / Browser 测试，也没有真实模型请求。未来自动测试继续阻断网络、使用 SDK / Gateway fixture、临时文件和虚构 Secret。

| 范围 | 未来用例 | 当前测试落点 / 复用 |
| --- | --- | --- |
| 协议与 Accumulator | 单调用、ID 晚到、name 规则、fragmented JSON、UTF-8 byte limit、空片、非 object、NaN、未闭合 / length / 断流 | `tests/test_gateway_tool_contract.py`；未来单独 accumulator 纯单元测试 |
| 交错 delta | 两个 index 交错、重复 ID、ID 变化、异常 index、不同 choice、metadata 仅首片、Usage-only / 同块 Usage | 同上 + Provider fixture；Executor 只收到完整 calls |
| Streaming 生命周期 | 首 Tool delta 后不 retry、cancel 接收 / 执行前 / follow-up 中、iterator/client 关闭、迟到事件不提交 | `tests/test_execution.py`、`tests/test_tool_conversation.py` |
| Multi-Tool | 2 success；1 success + 1 可恢复失败；全部失败；批次 unknown / unauthorized / duplicate / budget 拒绝且零执行 | `tests/test_read_only_tools.py`、`tests/test_tool_policy.py`、`tests/test_tool_conversation.py` |
| Result identity | 每个 ID 恰好一条 result、原顺序保留、缺失 / 多余 result 拒绝、单结果与累计限额 | 同上；follow-up body fixture |
| 时间一致性 | 两次读取间 Apply；结果保留各自时间与来源；Store 不变；Analysis 原 Facts 不覆盖 | `tests/test_analysis_tools.py` + Current / Telemetry 测试 |
| Multi-Round | 2 rounds → final；request / round / total call limits 独立；重复 ID / 同 args 新 ID / A→B→A / no-progress | `tests/test_tool_conversation.py`；一个请求共享 Executor ledger |
| 总 deadline | 两次模型各未超 timeout，但会话总时间已耗尽；结果序列化 / Handler 耗时计入；停止后零后续请求 | fake clock + `tests/test_execution.py` |
| Usage / Trace | per-step 无重复累加；末尾 Usage 缺失；部分失败仍记已耗 Usage；round/call 关联；无 Secret / raw result | `tests/test_tool_conversation.py`、`tests/test_assistant.py`、observability 测试 |
| UI | 轻量多 Tool 分组；接收参数不是 final；Cancel 不留成功 History；安全 textContent；多轮进度与旧事实 | `tests/test_browser_streaming.cjs`、`tests/test_assistant.py`、`tests/test_analysis_tool_web.py` |
| 能力与三模式 | UNKNOWN 不越 gate；Preset 只有发布组合；Managed Evidence 不改 Preset；Manual 不自动执行 | `tests/test_preset_tool_qualification.py`、`tests/test_tool_capability_probe.py`、现有 Manual / Profile 测试 |
| 兼容 | 当前 1 call / 1 round / 2 requests 错误码和结果保持；普通 Normal / Streaming、Tool Manager / Development Test 不变 | T1–T5、Analysis / Assistant / Browser 原测试全部保留 |

不依赖模型绝对遵守 Prompt 验证安全限制；构造违例 fixture，证明应用仍拒绝。并行若未来单独实施，额外测试 ContextVar、取消 hook 不覆盖、资源争用和全部子任务回收。

## 14. 与成熟架构的对照

这里的“成熟”指可验证的工程能力集合，不要求采用某个 Agent Framework。

| 成熟系统要素 | 当前对应 | 扩展所需 |
| --- | --- | --- |
| stable schema / static authorization | 冻结合同、Registry、Policy 已有 | 参数型 Tool 才补明确 schema validation，不提前泛化 |
| Provider-normalized calls | 完整 ModelToolCall 已有 | tool delta 与终止语义归一 |
| streaming accumulator | 未实现 | 有界纯状态组件 |
| central executor | 已有 | 保持集中授权；补批次预检与可恢复结果策略 |
| bounded orchestration | 当前结构固定有界 | 显式 Budget + 会话账本，禁止重置计数 |
| per-call result identity | 单调用已有 | 多调用列表、跨轮 ID 生命周期 |
| partial failure semantics | 当前 fail-fast | 业务 partial / 可恢复 error / 致命 error 分开 |
| cancellation | 单活动 SDK 已有 | 慢 Handler 合作式 deadline；并行任务组待后续 |
| trace / deterministic limits | 单调用安全 Trace、参数 / 结果大小门禁 | 总 deadline、总字节、无进展检测与分轮统计 |
| safe UI projection | 轻量 Activity、安全正文、成功 History 已有 | 多项投影与流式 final commit 门禁 |

当前结构已具备关键安全底座。缺少的是新能力的状态与生命周期合同，而不是一套全新的 Tool 系统。

## 15. 推荐演进顺序

1. **公共前置项**：写清 Budget、完整结束门禁、跨 step call ledger、结果 / Trace 的兼容列表设计；保持默认单调用限制。先用离线 fixture 验证。
2. **A：单 Tool Streaming**：新增归一 delta + Accumulator；参数完整后执行；第二请求流式 final；仍 1 call / 1 round。先 Mock，再由维护者对 exact 模型独立发布。
3. **B：单轮 Multi-Tool，先 non-streaming / Sequential**：有互补 Tool 产品需求后开放最多两调用；先验证批次授权、结果归属与部分失败，再组合 interleaved streaming。
4. **C：有限 Multi-Round，先 non-streaming**：仅在一个 Tool 的输出确实决定下一 Tool 输入时增加；先 2 rounds / 3 model requests / 2 total calls。最后组合 Streaming + Multi-Tool + Multi-Round。
5. **Parallel 单独延期**：只有慢、独立且证明并发安全的 Tool 值得引入；不得作为 B 的默认实现。

A 优先是因为它改善现有单 Tool Assistant 的最终回答等待，同时保留已验证的调用预算。它不是仅调用 stream() 的小补丁，必须完成 Accumulator 与结束门禁。若测量最终正文短、收益很小，可继续保持当前稳定版本，不为功能对称扩展。

## 16. 主要风险

- 只移除 Streaming gate，却没有完整参数 / 结束校验，会把未完成模型输出当执行授权。
- 独立 Streaming 与 Tool SUPPORTED 被误当组合已发布；Thinking + Tool 也不能外推。
- 多轮每次新建 Executor 导致 budget / ID 防重清零；恢复重试重复执行或重复计费。
- 单结果皆未超限但总 Context / 内存 / 总时间失控；后检查大小不能替代源头限流。
- 并行子任务覆盖 RequestHandle hook、丢失 ContextVar 或遗留 I/O；只读不代表并发安全。
- 不同时间 Snapshot 被合成“同一当前事实”；旧 Tool Result进入后续历史又被当作最新值。
- UI 将工具参数、reasoning 或首轮暂存正文当成功 final；取消后迟到结果污染历史。
- 部分失败策略无明确分类，使授权拒绝被软化，或跟进消息缺失某个 tool_call_id。

## 17. 结论：八个明确回答

1. **当前架构不需要重写。** 保留共享 Coordinator、Executor、Registry、Policy、Gateway、Credential 与取消设施。
2. **Streaming Tool Calling 可以演进。** 必须扩展事件合同、增加 Accumulator 与完整结束门禁，不能只打开现有 gate。
3. **第一版不支持 Streaming Tool Execution。** 参数未完整时禁止执行；完整调用后执行再流式回答可支持。
4. **同一轮 Multi-Tool 暂不优先。** 当前两个 Tool 重叠且很快；有互补 Tool 后先 Sequential。
5. **Multi-Round 有条件值得实现。** 需要明确的数据依赖场景，严格固定预算；现在不默认升级。
6. **推荐 A 优先，B 其次，C 最后。** 都在公共预算 / 生命周期准备完成后开始。
7. **完整顺序：公共底座 → 单 Tool Streaming → 顺序 Multi-Tool → Streaming Multi-Tool → 有限 non-streaming Multi-Round → 三者组合。** Parallel 与 Agent 另行审议。
8. **最大的五个差距**：①工具 delta / Accumulator / 完成门禁；②会话总预算、跨轮 ID 与无进展账本；③多调用 / 多轮结果、Usage、Trace / UI 合同；④批次预检、部分失败与观测时间一致性；⑤慢 Handler deadline、任务组取消与资源清理。

本次交付为研究文档；没有实现上述扩展，没有运行模型资格验证，没有改变已发布能力。

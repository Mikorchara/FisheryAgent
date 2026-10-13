# Assistant Streaming Tool Calling：分阶段方案

2026-10-13。研究依据为当前源码与 Provider 官方资料。Phase 4D 完成 non-streaming 三 Tool 范围与 Activity 卡片；Phase 5A 完成组装协议基础，Phase 5B 完成内部 Streaming Transport 与共享多轮循环接入，见 §7–§8。产品 Streaming Tool 门禁仍关闭，没有真实模型请求。

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

**当前产品路径仍明确拒绝 Streaming Tool**：

- `model_gateway.validate_tool_request(..., streaming=True)` 遇 tools、assistant calls 或 tool messages 就拒绝 `TOOL_STREAMING_NOT_IMPLEMENTED`。
- `openai_compatible_adapter._event()` 遇 `delta.tool_calls` 同样拒绝；`ModelEvent` 只有正文/推理 delta、finish_reason 与 Usage。
- Adapter 已有同步/AsyncOpenAI bridge、队列、SDK stream/client 关闭、RequestHandle 与剩余 deadline，可以复用传输生命周期。
- `ToolCallingService` 默认取得完整 `gateway.complete()` 响应；内部显式 Streaming 使用 `complete_tool_stream()` 返回已组装、清理完成的响应，再走同一 Executor 与循环。Web Assistant 仍使用 Normal Transport、JSON 最终响应和累计 Activity 轮询，不提供流式正文接口。
- Manual Raw 可传输/展示 Tool 字段，但不组装授权调用、不执行 Tool，不能用它绕过正式门禁。

## 3. 最小 assembler 合同（Phase 5A 已实现协议部分）

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

## 7. Phase 5A：离线 Streaming Tool Call Assembler

实现位于 `openai_compatible_adapter.py`：私有 `_ToolCallStreamAssembler` 与 `_complete_tool_stream()`。后者复用原 AsyncOpenAI bridge / RequestHandle / CredentialSnapshot / 参数编码 / option gate，在 SDK iterator 正常耗尽、stream 与 client 清理成功后才组装并返回完整 `ModelResponse`。收流阶段没有输出可执行调用，没有 Tool 执行或第二套循环；重试固定为 0，即使 Runtime 设置了更大 max_retries。

**产品入口不变**：普通 `stream()`、Gateway Streaming Tool 校验及 Web 仍拒绝 `TOOL_STREAMING_NOT_IMPLEMENTED`。内部组装传输入口仅跳过“协议尚未实现”这一门禁，模型 tool_calling / streaming Capability、Preset 模式、运行选项门禁仍正常检查。没有发布 Streaming 资格，没有修改 Prompt、Policy、预算、Handler、Analysis 或 Manual。Coordinator 内部接入已由 Phase 5B 实现（§8），UI 与资格发布仍属后续阶段。

### 已锁定的协议边界

- 一个 choice（index=0）、一个 Tool（index=0）；多个调用整轮拒绝，不执行部分调用。返回 model / response id 冲突也拒绝。
- id 是有界的稳定元数据：缺失/空续帧忽略，相同非空 id 可重复，不同非空 id 视为冲突，**不猜测或拼接 ID 片段**。name 可按实际暴露 Tool 名的合法前缀逐段拼接，也允许重复完整名称；冲突或未知名称拒绝。
- arguments 字符串严格顺序追加，保留原始 JSON 文本、转义和 Unicode，不补括号、不改参数。完成后必须为合法 JSON object；重复键、非有限数字、非法 Unicode、超深/超复杂输入拒绝。这里只保证模型协议结构；业务 Schema 与权限仍由原 Registry / Executor 校验，不能把获得 ModelToolCall 当作执行授权。
- 必须有合法 terminal（stop / tool_calls / function_call）和正常 iterator 结束；带合法完整调用的 stop 可接受。没有 finish、length、过滤/未知终止、终止后的新增数据、传输或清理异常均不返回可执行调用。遗留 `delta.function_call` 不在本阶段支持范围。
- 文本、reasoning 与 Tool Call 分开归一；完整 tool_calls 允许 content=None。它们只返回内部响应，未接公开逐字显示或推理展示。
- Usage 支持 usage-only frame 和 finish chunk，按同一请求的累计值保留最新统计，不逐片相加；缺失显式 unavailable，非法或倒退统计拒绝。

限制为最多 **4096 chunks、256 KiB 累计字段缓冲、4096 bytes arguments、16 层 JSON 嵌套、1024 JSON 节点**；id/model/response id 各最多256 bytes，name片段最多64 bytes。超大字段在复制 UTF-8 缓冲前拒绝。错误只返回安全码：`INVALID_STREAM_EVENT`、`INVALID_TOOL_CALL`、`INVALID_TOOL_ARGUMENTS`、`TOOL_CALL_LIMIT`、`STREAM_INTERRUPTED`、`STREAM_TRUNCATED`、`STREAM_CHUNK_LIMIT`、`STREAM_BUFFER_LIMIT` 等，不回显内容。

每个 chunk、I/O 生命周期及最终归一化后均受现有取消/时间边界保护；整 Turn deadline 不续期。USER_CANCELLED、TOTAL_TIMEOUT 与 Provider 安全错误保留区别。关闭失败或最后时刻取消/过期会丢弃完整响应，不重试；普通文本 Streaming 的既有传输行为保持。

### 验证与剩余限制

新增 `tests/providers/test_streaming_tool_assembler.py`，全部离线，fake SDK 与 `httpx.MockTransport` SSE 解码覆盖分片/重复元数据、JSON 转义/Unicode、正文与推理分离、异常/多调用、资源限制、Usage、断流、取消、deadline、关闭失败、无重试、产品门禁和普通流式回归。测试阻断 Provider 网络与 Executor 执行；临时虚构 Runtime 不访问真实凭据。

SDK 丢弃原始 `[DONE]` 标记，因此认定的是“有合法 finish、SDK iterator 正常结束且成功清理”，不能额外认证一个 SDK 未公开的原始标记。精确 Provider 的结束帧、安装版本差异、拆分 ID 方言及组合资格尚未真实验证，不自动兼容或放宽。Phase 5B 已离线验证同一 Coordinator 的调用策略；真实资格仍须独立授权。没有 Web Streaming、SSE、产品发布或真实请求。

离线结果：新增组装器/传输测试 **38 项**；与 T1 Gateway / Cancellation 合并 targeted **81 项通过**；FAST **149 项**；FULL PRODUCT **992 项**；Browser **205 项**；FULL QUALIFICATION **134 项完成**（133 通过，1 项既有目录 symlink 环境跳过）。Python AST、JS 语法、292 条 Markdown 本地文件链接、diff check 与改动文本敏感扫描通过。初始最后时刻过期测试使用纳秒时间差，受 Windows 时钟粒度影响；改为确定性的已过期测试时钟后通过，不改变产品 deadline。工作树保留源码、测试和文档变更，没有 commit / push。

## 8. Phase 5B：同一有界 Runtime 的 Streaming Transport

内部构造 `ToolCallingService(..., model_transport=ToolModelTransport.STREAMING)`，同时显式选择 `BOUNDED_MULTI_ROUND`，才使用流式 2/2/3。默认 `NORMAL`、默认 1/1/2 与现有 Web 构造均不变；也可离线选择 Streaming + SINGLE_ROUND 验证 1/1/2 parity。类型错误拒绝；不支持 `complete_tool_stream()` 的 Gateway 返回 `TOOL_STREAM_TRANSPORT_NOT_IMPLEMENTED`，不静默改用 Normal。

`ModelGateway.complete_tool_stream()` / Adapter 以 Phase 5A 组装器返回完整 `ModelResponse`。Coordinator 仅在原 Model step 选择这一方法；definitions、一个 Executor、Policy、budget、Tool Result messages、Steps、Ledger、Source Gate 及 Assistant 最终提交仍是原实现，没有第二套循环。

```text
内部 STREAMING + 冻结 Runtime / Policy / 同一 RequestHandle
  → Request #1 全流收完 / 验证 / 关闭
      ├─ Final → Source Gate + Trace + 最终取消检查 → 单条成功回答
      └─ Tool A → Executor → Result A / Receipt A
           → Request #2（包含 assistant call + role=tool Result A）
               ├─ Final → 结束，不花剩余预算
               └─ Tool B → 同一 Executor → Result B / Receipt B
                    → Request #3（包含两个 Result，tool_choice=none）→ Final
```

保持最多两次 Tool 执行、两轮、三次模型请求、每轮一个调用。同轮多个调用整轮拒绝；去重、参数 Schema、权限与结果大小仍由原 Executor 负责，NO_DATA / NO_MATCH / NOT_SCORABLE / PARTIAL 不自动补查。第三请求继续 Tool 则 TOOL_ROUND_LIMIT，不发送第四请求。Registry 实际 definitions 是唯一 schema 来源，Tool 只能在 stream/client 关闭且完整响应被接受后开始。

内部 Streaming Coordinator 复用 `turn_deadline_scope`，即使没有外层 Assistant 也具有完整 Turn 时间边界；已有外层 deadline 只能收紧，不能续期。所有轮次绑定同一不可变 Runtime / Credential / Policy 和 RequestHandle；SDK retry=0，无失败换模式、failover 或追加请求。Stop 可发生在任意 Model stream、Tool 前或 Tool 后；后续步骤立即停止。同步 Trace 跨越 deadline / Stop 时追加失败终态修正，不返回成功 Turn。

`StreamingModelError` 仅携带安全错误码、已收到的 `Usage` 与合法 finish_reason，**不携带半成品正文、Tool Call、arguments 或 Raw Result**。已有成功请求和失败流的已知统计按 request 聚合，不按 chunk 相加；缺失统计为 unavailable。失败时的已知 usage 不保证是最终完整用量或账单数字。已完成 Tool 的独立 Receipt / Ledger 保留审计，但 Turn 不成功提交。

Trace 仅在内部流式 Turn 增加 `model_transport=STREAMING`，保留原有序 Steps / 安全统计；Normal Trace 字段不变。Assistant 的公开 Activity / JSON / History 合同不变，History 仍只接收成功 user/final 文本 pair。内部模型分片并不进入 Browser；Web 显式提交 transport / stream 等字段会拒绝。

离线测试位于 `tests/tools/test_streaming_multi_round.py`：真实 Adapter + fake SDK + 正式 Registry / Executor / Handler + 临时 Snapshot / Trace + 正式 AssistantService。scripted provider 根据真实水质 Result 的 DO 决定继续检索或提前结束，第三请求可见两个真实 Result；这只证明结果传递与 Runtime，不是模型真实行为证据。覆盖直接/提前 Final、完整两轮、清理后才执行、独立时间来源、负向业务状态、Usage、失败 Source Gate、非法/重复调用、第三轮限制、Stop、整 Turn deadline、Trace 失败/终态修正、History、Normal parity 与 Web 不可选传输。

Phase 5B 新增 **28 项**离线端到端测试；相关 targeted **187 项通过**，FAST **149 项**，FULL PRODUCT **1020 项**（93.146 秒），Browser **205 项**，FULL QUALIFICATION **134 项完成**（133 通过，1 项既有目录 symlink 环境跳过）。Python AST / JS 语法、292 条 Markdown 本地文件链接、diff check 与改动文本敏感扫描通过。时间预算测试为首个 fake SDK 请求加入30ms固定延迟，避免立即返回的两个请求落在同一 Windows 时钟 tick 时误判“没有减少”；没有放宽产品 deadline。既有 Phase 5A 工作树变更保留，没有真实 Provider / Ollama 请求，没有 commit / push。

## 9. Phase 5C 真实资格的前置条件

本轮没有新增真实 Qualification 命令，没有调用 Provider，也没有改现有发布 Scope。

1. **单案例入口**：扩展既有 `qualification/qualify_multi_round.py` 及开发实现，默认 dry-run；计划明确绑定 `model_transport=STREAMING`，不能沿用 Normal qualification_id 认证新组合。Harness 目前仍走原 Normal 路径。
2. **精确 Scope**：Preset Identity / contract、ProtocolSpec、正式多轮 Prompt 指纹、History Projection、实际授权 Tool definitions、OFF、SDK / Provider（Ollama 服务）版本与 Streaming transport；新的发布范围保持 candidate，不绕过 Web 门禁。
3. **有限授权**：用户逐案例批准一次 run。最多 2 Calls / 2 Rounds / 3 Requests、每请求小 token 上限（建议 ≤256）、retry=0，固定合成 Snapshot 和隔离 Policy；凭据只走正式 Runtime / CredentialSnapshot。错误不补跑，不复制 Secret 或修改 ACL。
4. **真实协议观察**：当前资格工具对非流式完整 response 的观察不足以认证流式；需增加有界、安全的 Streaming observer，记录实际/归一化 call 数、name、参数存在/合法、finish、returned model、结果传递标记、清理状态、Ledger、请求次数/transport attempts、Usage 与失败原因，不保存原参数、正文、Prompt、证据或凭据。
5. **案例与判定**：低氧查询→Knowledge→Final，正常/当前 DO 查询→提前 Final，概念直答与 History 追问。另获授权检查实际 Stop；技术通过与人工回答质量分别判定，不证明远端计费停止或长期可靠性。`[DONE]` 与版本方言边界必须如实报告。
6. **维护者决策**：报告通过后另行批准精确 Streaming 组合与 UI 接入。普通 Streaming 支持、Normal Tool 资格和本轮 fake SDK 成功都不能自动发布真实 Streaming Tool Calling。

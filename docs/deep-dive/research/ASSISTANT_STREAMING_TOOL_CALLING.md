# Assistant Streaming Tool Calling：分阶段方案

2026-10-13。研究依据为当前源码与 Provider 官方资料。Phase 4D 完成 non-streaming 三 Tool 范围与 Activity 卡片；Phase 5A 完成组装协议基础，Phase 5B 完成内部 Streaming Transport 与共享多轮循环接入，Phase 5C 已准备独立单案例资格入口（§9–§10）。产品 Streaming Tool 门禁仍关闭；本阶段没有真实模型请求。

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

## 9. Phase 5C：单案例 Streaming 资格准备已实现

**REAL PROVIDER RESULTS: NOT RUN。** 复用 `scripts/qualification/qualify_multi_round.py --streaming`，自动使用正式 `ASSISTANT_BOUNDED_MULTI_ROUND@1`、完整 pair trimming 后的 `UNTRUSTED_TRANSCRIPT_V1@1`、AssistantService / ToolCallingService / Registry / Executor / Ledger / Commit Gate。未指定 `--streaming` 的旧实验和 Normal 正式资格入口保持原语义。

### 独立计划与授权

| Preset | 当前精确 Identity（service / adapter / normalized URL / model） | ProtocolSpec | Streaming 状态 |
| --- | --- | --- | --- |
| `dashscope-qwen38-flash-r1` | `dashscope` / `openai_chat` / `https://dashscope.aliyuncs.com/compatible-mode/v1` / `qwen3.8-flash` | `dashscope_chat@1` | candidate，未真实运行 |
| `deepseek-flash-r1` | `deepseek_api` / `openai_chat` / `https://api.deepseek.com` / `deepseek-flash` | `deepseek_chat@1` | candidate，未真实运行 |
| `ollama-qwen35-4b-r1` | `ollama` / `generic_openai_chat` / `http://127.0.0.1:11434/v1` / `qwen3.5:4b` | `ollama_openai_chat@1` | candidate，未真实运行；本机服务版本未知 |

每个 Preset 的两个工具集合分别生成独立 `streaming_scope`：默认 `water-knowledge`（查询 + Knowledge），可显式选择 `three-tools`（查询 + 评分 + Knowledge）。Scope 从当前资源和 Registry 计算，不复制 Normal 资格；包含 contract、精确 Identity、完整 ProtocolSpec、Prompt 指纹、History 版本、实际 Tool definitions 指纹、OFF、Streaming Transport 和 assembler 版本。当前 contract 均为1.0.2，但不因此获得 Streaming Tool 发布资格。计划还包含 SDK 版本、整 Turn deadline、固定 Snapshot / History / 问题指纹、token 上限和预算，`plan_sha256` 绑定本次具体条件。发送前重新核对 scope；漂移在凭据解析与网络前拒绝。

计划默认 dry-run，不解析凭据、不创建 SDK、不执行 Tool、不写运行报告。逐案例授权后才用 `--confirm-network`，一次进程仅一个案例，没有批次或恢复器。Runtime / CredentialSnapshot 仍用正式私有 composition；Ollama Auth NONE 不读取 Key。隔离 Snapshot 和 Policy 只存在本次进程，不能读取或改 Web 状态。错误不重跑、不切 Normal、不 failover。最多 **2 calls / 2 rounds / 3 requests**，每轮一个 Tool，每请求 **1–512 output tokens（默认256）**、retry=0；整 Turn 使用该 Preset 已有 timeout，不逐请求续期。非流式资格继续限制1–256，不因 Streaming 调整而放宽。

### 有界 SDK 观察与安全报告

开发模块 `streaming_observation.py` 使用生产 assembler 的原验证/限制，并包装本次 SDK stream/client 生命周期。产品 Adapter 只增加一个内部 assembler factory，默认仍返回原类；正式 Runtime 不导入 qualification。没有第二套组装或执行循环。

- 每请求保存有限计数：SDK chunks、Tool/arguments/text/reasoning/usage 分片数、累计缓冲字节、是否见多 call delta；不保存分片列表或内容。
- 完整组装时 transient 比较已收集 SDK id/type/name/arguments 与 normalized calls，只保存 call 数、allowlisted name、id 是否有效、参数存在/Registry 验证结果、query_present/query_valid、model match、finish 和一致性布尔。未知名称仅保存 `unknown_tool`，不保存 id、arguments、query 或 Provider 任意字符串。
- 分别记录 SDK iterator 正常耗尽、stream/client 关闭成功、assembly_complete。异常/取消/超时/length/清理失败没有可执行完整调用，不认证成功；已知的失败流 Usage 保留，但不等于完整账单。
- 同一 Runtime 记录实际执行 Steps、Result 精确进入下一请求的布尔、独立 Ledger / Requirement、Source Gate、Trace、请求/transport attempts、Usage、提前 Final 和安全错误码。注入 fake SDK 的离线报告明确 `offline_fixture`、`actual_network_requests=0`，不能用于真实资格发布。
- 安全 JSON 仍写固定 `outputs/assistant-qualification/<run_id>.json`，`experiment_version=assistant-streaming-multi-round@1`。不保存正文、原始 Tool 参数/Result、Evidence、完整 Prompt、Credential / 私有路径或 Authorization。Streaming 模式拒绝 `--review-answer`（包括内部 reviewer 回调），不从终端输出正文。

技术资格需：精确 scope/model 匹配；正常结束/清理；协议与归一化一致；实际执行路径符合案例；Result 传递、Ledger / Requirement / Commit Gate / Trace 全部通过；没有预算外请求。成功仅为 `PENDING_MANUAL_REVIEW`，永远 `release_eligible=false`，不写 Evidence、不发布 scope、不启用 Web Streaming。安全报告不评价语言质量或最终答案真实性；人工质量审查需后续单独批准安全方法。

**验证边界**：观察的是 SDK 解码后的分片，不是原始 SSE bytes。`[DONE]` 为 `NOT_OBSERVABLE_BY_SDK`，只有合法 finish + 正常耗尽 + 成功清理可认证。当前 SDK 版本由安装 metadata 读取；Provider 服务版本为 `NOT_OBSERVED`，未探测 Ollama `/api/version`。真实版本、拆分 ID/重复 name 方言、usage/finish 位置、Stop 的真实 I/O 表现仍须逐项验证；不根据 Provider 名放宽校验，不声明远端停止计算或计费。

一致性检查比较的是同一 assembler 收集的候选字段与最终 ModelResponse，不是第二套独立 SSE parser 的证明。后续审阅只能据此判断分片存在、组装/执行和输出投影是否一致，不能声称独立验证了 SDK 解码实现。

离线验证：新增 **26 项** Streaming 资格测试；相关 targeted **141 项通过**；FAST **149 项通过**；FULL PRODUCT **1020 项通过**（114.411秒）；Browser **205 项通过**；FULL QUALIFICATION **160 项完成**（159通过，1项既有目录 symlink 环境跳过，18.932秒）。Python AST **153文件**、JS语法、Markdown **295条本地文件链接**、diff check 和改动文本敏感扫描通过。没有读取真实凭据、联网或修改发布配置。测试覆盖三个精确计划、实际 SDK 分片计数/Unicode、Result 传递、History、评分来源、Usage-only/失败 Usage、断流/截断/非法多 call、有界缓冲、清理失败、Provider安全错误、Stop、deadline、Trace失败、scope漂移和不发布。

## 10. 推荐最小顺序与手动命令

先批准 Qwen 两工具的 `current-do`（一 Tool 后提前 Final），再批准 `low-oxygen`（真实 Result 决定检索），再批准 `concept`（无 Tool 直答）。三个案例最多9次请求，预期2+3+1=6次；每个分别授权执行，失败也是结果，不自动补样本。然后按需批准 `normal`、`history-current`、`history-explanation`；不得把首三个样本当作全部发布资格。DeepSeek / Ollama 在 Qwen 审核后独立重复三个最小案例；三工具组合另行批准 `current-score` 和 `low-oxygen`，不继承两工具结论。没有固定批次或一键执行整个矩阵。

| 单案例 | 预期路径 | 预期模型请求 | 硬上限 |
| --- | --- | --- | --- |
| current-do | 查询 → Final | 2 | 3 |
| low-oxygen | 查询 → Knowledge → Final | 3 | 3 |
| concept | 直接 Final | 1 | 3 |
| normal | 查询 → Final | 2 | 3 |
| history-current | 旧值/NO_DATA 历史 → 本轮查询 → Final | 2 | 3 |
| history-explanation | 根据旧值解释，无 Tool | 1 | 3 |
| current-score（三工具专用） | 实验评分 → Final | 2 | 3 |

从项目根目录一次运行一条。下面只有 dry-run 可在本阶段执行；真实命令仅供用户后续批准**该 Preset + case + tool-set 一次 run**后手动使用，不能按旧授权运行其他命令：

```powershell
# Qwen 两工具：默认 dry-run，也可显式写出
.\.venv\Scripts\python.exe scripts/qualification/qualify_multi_round.py --streaming --preset dashscope-qwen38-flash-r1 --case current-do --max-output-tokens 256 --dry-run

# 仅在此 case 获一次独立授权后执行（本阶段未执行）
.\.venv\Scripts\python.exe scripts/qualification/qualify_multi_round.py --streaming --preset dashscope-qwen38-flash-r1 --case current-do --max-output-tokens 256 --confirm-network

# DeepSeek / Ollama 的独立准备计划，不联网
.\.venv\Scripts\python.exe scripts/qualification/qualify_multi_round.py --streaming --preset deepseek-flash-r1 --case current-do --dry-run
.\.venv\Scripts\python.exe scripts/qualification/qualify_multi_round.py --streaming --preset ollama-qwen35-4b-r1 --case current-do --dry-run

# 后续三工具计划：不能沿用两工具资格
.\.venv\Scripts\python.exe scripts/qualification/qualify_multi_round.py --streaming --preset dashscope-qwen38-flash-r1 --tool-set three-tools --case current-score --dry-run
```

其他案例只在准备时替换 `--case`；其他 Provider / 三工具真实执行须逐案例再次批准，再将对应命令中的 `--dry-run` 改为 `--confirm-network`。没有新增 URL、model、credential path、Prompt、retry、budget 或 deadline 覆盖参数。

### 输出预算小调整（2026-10-13）

经用户批准，Streaming 资格的显式 `--max-output-tokens` 上限从256调整为512，默认仍为256；计划/CLI与QualificationAdapter共用严格校验，拒绝bool、非int和越界值，Adapter发送前再次检查。没有 Provider 特例，不修改 assembler、Prompt、Preset、Tool Policy、Ledger或Commit Gate。

此参数作用于每次模型请求，512配置的三请求输出预算最多1536 tokens；DeepSeek仍为120秒整Turn deadline、2/2/3、retry=0，不自动放宽时间或追加请求。Scope不变，实际512预算进入计划并产生不同的`plan_sha256`；旧256失败报告保留，新真实run须另获逐案例授权。512仍返回length时继续`STREAM_TRUNCATED`，不能提交半成品或自动补跑。本次只执行离线测试和dry-run，没有真实复测。

新增7项预算测试：范围/类型、CLI、默认与Hash兼容、三次fake SDK参数传递、length失败保留Ledger/Usage、发送前重校验、512下Source Gate/取消/120秒deadline。Streaming资格33项通过；相关资格targeted126项完成（1项既有symlink环境跳过）；FULL QUALIFICATION167项完成（166通过、1跳过）；FAST149项、Assembler/Streaming Runtime66项通过。未改产品Runtime或Web，无需重跑无关Browser测试。

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_multi_round.py --streaming --preset deepseek-flash-r1 --case low-oxygen --max-output-tokens 512 --dry-run
```

## 11. Phase 5D：Web Streaming 离线接入

状态：**OFFLINE IMPLEMENTED / REAL WEB STREAMING NOT RELEASED**。本阶段没有真实 Provider / Ollama 请求，没有批准任何 Streaming 产品资格。Normal仍是默认及回滚路径，Analysis / Manual / Development仍用原入口。

### 最小数据流

```text
Bootstrap：Normal profile + 独立 Streaming profile / revision / 可用状态
  → 选择模式、确认最多2或3次请求、prepare同一RequestHandle
  → POST /api/assistant/chat/stream（Host / Origin / CSRF / epoch / revision / released scope）
  → 冻结 Runtime / Credential / Policy → 同一 AssistantService / ToolCallingService
  → SDK 正文临时预览；完整收流和清理后才执行 Tool
  → 原累计 Activity Steps / Ledger / Source Gate / Trace / Commit Gate
  → 唯一 Final 或 Error / Cancelled → 前端仅 Final 完整成功后提交历史
```

实现：`assistant_streaming.py` 提供独立冻结的 `AssistantStreamingConfig / Release`、共享精确 `streaming_scope` 与请求内临时事件通道。`create_app` / `run_web` 可接维护者内部启动配置，默认 `enabled=false`、没有发布记录。只有 `released` 且有资格标识/时间、精确 Identity / Preset contract / ProtocolSpec / Prompt / History / Tool definitions / assembler / transport匹配才可用；candidate、Normal released、local_experimental 均不能授权 Streaming。资格与产品共用 Scope 算法，旧资格预算与计划Hash语义不变。没有 Web Publisher，也不读取安全报告自动发布。

开启仍需用户批准具体范围和维护者发布配置；本阶段只在临时离线测试配置中使用 `OFFLINE_FIXTURE_ONLY` released记录。浏览器只能选择已有受管模式端点，不能提交 mode、budget、deadline、Prompt或配置路径。Streaming revision绑定配置、epoch、Policy、精确Scope、timeout/生成默认值/凭据引用；不匹配在凭据解析、SDK及联网前拒绝。不静默降级或失败后重试。

### 事件与临时预览

POST SSE不是EventSource：控制令牌在JSON请求体，不进URL；无GET重连、无游标恢复、无自动模型重发。每条事件含schema版本、request_id、epoch、单调seq；类型为start、activity、preview_reset、preview、final、error、cancelled，另有无数据heartbeat。Tool开始/完成/拒绝来自原Activity中的handler_started/state；累计Steps和有序事件同时保留，快速完成不会被轮询遗漏。一个请求内worker仅承载已有Service，没有第二个Tool循环或持久后台任务。

Adapter增加可选正文观察钩子，不改assembler验证和正常收流/关闭顺序。只观察已接受SDK content；tool_calls/arguments、Raw Result、Prompt和reasoning不作为事件字段。累计正文在输出前脱敏，并暂扣可能是Credential前缀的末尾，避免Key跨chunk泄露。每Turn最多128次预览、每次最多16KiB UTF-8、约50ms节流；整个通道最多512条非终态事件，超限安全失败，终态仍可报告。不持久化事件或预览，不写Trace/History。完整最终正文仍受既有assembler大小限制与Assistant脱敏约束；资格入口的512 token预算不自动注入Web请求。

UI保留OFF只读标签，添加Normal / Streaming选择；未发布Streaming禁用。临时正文用textContent、虚线卡片明确标记未确认；返回Tool Call、开始下一请求、失败或Stop时撤销。实际Tool逐个独立卡片显示名称、状态、业务摘要，细节单独展开；完整Model/Tool Steps、Usage、Trace是否记录和安全Trace ID仍在折叠运行详情。只接受完成、stop、Trace成功、Activity COMPLETED的唯一Final，才保存成功user/final pair。

失败/取消的Turn也保留已观察到的安全Tool卡片，不把它们计入成功对话；临时正文撤销，仍可查看已执行步骤及失败状态。

重复/旧seq忽略，事件缺号、错误epoch/request_id、未知类型、无Final EOF或断线均失败，不自动重连；发送取消API针对原request。Stop与迟到事件仍用原RequestHandle和前端pending guard。断开响应（包括首次迭代前关闭）取消原I/O，刷新清空页面Session，不恢复旧生成；同request_id再次POST被拒绝。已提交完成的Turn不被迟到Stop重写。远端计算/计费是否停止仍UNKNOWN。

### 验收与真实接入缺口

离线端到端覆盖Direct Final、一Tool提前Final、查询→Knowledge→Final、真实Result传递、NO_DATA、Tool开始/完成及拒绝、Usage、第三轮限额、Stop（各模型轮次）、断线、deadline、Trace/线程启动失败、分片Secret、reasoning/参数不公开、revision/Policy/epoch/CSRF/Origin/Host、关闭/候选门禁、Normal回归。Browser覆盖预览与History隔离、独立卡片、重复/乱序、错误、断线不重发、Stop迟到Final、模式确认和未发布门禁。

普通启动 `python -m fishery_ai web` 仍仅开放Normal；可人工检查Streaming禁用、原Analysis/Assistant/Manual/Development以及Stop。真实Streaming网页体验需先完成各精确范围的资格与人工回答质量审查，再另获发布/联网授权；Qwen的两个技术PASS不能替代概念/History等剩余检查，DeepSeek预算截断不能算通过，Ollama版本与方言仍待确认。三工具组合独立审核。资格完成后由维护者提供精确配置给run_web，关闭配置并重启即回滚Normal；不在同一epoch动态切换发布，也不因失败切Transport重跑。

离线验收：新增20项Web SSE / Fake SDK测试、9项Browser测试；相关targeted168项通过，FAST149项通过，FULL PRODUCT1040项通过（41.489秒），Browser214项通过，FULL QUALIFICATION167项完成（166通过、1项既有symlink环境跳过）。Python AST155文件、JS语法、296条Markdown本地文件链接、diff check和改动文本敏感扫描通过。首次全量回归发现一条测试仍精确要求旧的“Thinking OFF · Normal”固定标签；改为校验OFF与默认Normal选择，未放宽运行门禁。保留上一轮512预算工作树变更，没有真实请求、commit/push或生产项目修改。

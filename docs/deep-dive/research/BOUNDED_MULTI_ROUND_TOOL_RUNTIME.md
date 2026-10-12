# 有界 Multi-Round 与 Streaming Tool Runtime 研究

研究日期：2026-10-12；原研究源码基线：`7ebbe59`。以下多轮/Streaming 内容仍为设计建议。阶段 1 已落地有序 steps、逐执行 Ledger、内部预算和安全 Trace；正式执行仍固定 1/1/2，Prompt、History、Tool 权限与模型合同不变，无真实 Provider 请求。当前合同见[只读 Tool 当前实现](../tools/READ_ONLY_TOOL_CALLING.md#内部结果来源与预算合同)。

## 1. 结论

**建议分阶段推进，先做结果 / 来源 / 预算合同基础，再做 non-streaming 有界多轮，最后做 Streaming。** 不建议同时开放并行 Multi-Tool、多轮和流式执行。

当前消息协议、Registry、Policy、Executor、Usage 与取消设施可以复用。主要缺口在共享 Coordinator 及其结果消费者，不需要新建另一套模型连接、Executor 或 Agent 框架。

首个候选范围：READ ONLY、每轮最多一个 Tool、最多两次 Tool 执行尝试、两轮 Tool、三次模型请求、retry=0。它足以表达“读取当前事实 → 根据结果决定是否检索知识 → 回答”，同时允许第一或第二次模型请求提前 Final。这些是待离线验证的上限，**不是本轮发布的新能力，也不代表每轮必须用满预算**。

## 2. 当前支持度与单轮假设

| 当前代码 | 已可复用 | 写死的一轮假设 / 扩展影响 |
| --- | --- | --- |
| [tool_conversation.py](../../../src/fishery_ai/tool_conversation.py) `ToolCallingService.run_request()` | 共享上下文执行、Policy 定义、响应校验、取消、Usage；阶段 1 使用有序 steps 与固定预算合同 | 执行仍单轮；Executor max_calls=1；follow-up 固定 none；再次调用为 TOOL_ROUND_LIMIT |
| 同上 `ToolConversationResult` / `ModelStepOutcome` | 不可变 model/tool steps，单轮只读兼容投影 | 更大预算不能执行；旧消费者需单独迁移后才能接入未来多轮 |
| [model_gateway.py](../../../src/fishery_ai/model_gateway.py) `ModelMessage/Request/Response` | assistant.tool_calls、role=tool、call id、多个历史消息，可构造重复 follow-up | 协议没有限定一次 Tool round；`validate_tool_request(streaming=True)` 主动拒绝所有 Tool 请求 |
| 同上 `ModelEvent` | content、reasoning、usage、finish_reason | 没有 Tool delta、choice / call index、完整流式模型响应合同 |
| [openai_compatible_adapter.py](../../../src/fishery_ai/openai_compatible_adapter.py) `_kwargs/_response/_bridge` | 完整调用编解码、SDK 取消与资源清理 | `_event` 拒绝 tool_calls delta；可重试配置仍来自 Runtime；每次 SDK operation 重建 total timeout |
| [tools/executor.py](../../../src/fishery_ai/tools/executor.py) | max_calls 可配置 1–8、参数 ≤4096 bytes、结果默认 ≤32768 bytes、同实例拒绝重放 call id | Coordinator 只用 max_calls=1；没有跨轮逻辑调用签名去重、累计结果预算或模型循环 |
| [tools/registry.py](../../../src/fishery_ai/tools/registry.py) / [policy.py](../../../src/fishery_ai/tools/policy.py) | 三个静态只读 Tool、实例绑定依赖、冻结的模式授权 | 基本不需重写；多轮不能扩大 Policy，不能让模型注册 Tool |
| [assistant_sources.py](../../../src/fishery_ai/assistant_sources.py) | 逐执行 Receipt、有序 Ledger、独立时间/质量与确定性满足函数 | 单次 Receipt 语义保持；旧 wrapper 拒绝多执行，不取最后一次 |
| [assistant.py](../../../src/fishery_ai/assistant.py) | 成功提交 gate、History v2、Preset / OFF / Normal、取消原子收口 | 单 Activity、两次请求投影；当前 Prompt 明确要求 Tool 后直接回答 |
| [execution.py](../../../src/fishery_ai/execution.py) | 一个 RequestHandle 可跨两次 SDK 调用，取消 hook 可重新绑定 | progress 仅接受 REQUEST_1 / RUNNING_TOOL / REQUEST_2；无整 Turn deadline |
| [observability.py](../../../src/fishery_ai/observability.py) | allowlist Trace、无正文 / 参数 / Secret | Tool Trace 固定两次模型请求、一次工具记录，不能覆盖所有 step |
| [application.py](../../../src/fishery_ai/application.py) | 固定 Analysis 捕获事实与独立 Tool 观测，复用同一 Coordinator | Activity 是单项；指令要求不再调用 Tool；有 Tool 时 analyze_stream 明确拒绝 |
| [web.py](../../../src/fishery_ai/web.py) / [app.js](../../../src/fishery_ai/resources/web/app.js) | 请求登记、epoch、明确联网确认、Stop、安全文本与轻量 Activity | Assistant chat 为完整 JSON 响应；UI 写死 1 Tool、Request #1/#2，并通过状态轮询展示阶段 |

`RuntimeSnapshot/CredentialSnapshot` 可以继续在整 Turn 冻结使用。它们冻结连接和凭据，**不冻结每次 Handler 查询到的水质**。Current Reader 每次 query 捕获当时 Store 并重评 Freshness。

## 3. 两种扩展不能混为一谈

| 形态 | 适合场景 | 当前建议 |
| --- | --- | --- |
| Multi-Tool Single-Round | 模型一次提出互不依赖的两个读取，收到全部结果后回答 | 以后再评估；不能用第一项结果决定第二项参数。还需全部调用预检、结果关联及部分失败规则，不宜先做并行 |
| Multi-Round、每轮一个 Tool | 第一次结果决定是否需要另一来源或怎样构造下一次 query | 优先研究；顺序简单，来源和取消容易定位 |
| Streaming Tool Calling | 每次模型响应通过 delta 传输 | 是传输问题，可先在现有一轮预算验证，随后复用同一多轮状态机 |

评分 Tool 已携带参与评分的水质，不应为了“多轮”先强制查询再评分。可用例子是异常水质后按需检索项目背景知识；检索结果仍不能成为现场疾病或当前观测证明。不预执行所有 Tool，不设关键词 / 正则 intent router。

## 4. 有界编排候选合同

### 4.1 预算与停止

建议内部、启动时固定的 `ToolTurnBudget`，不允许 Web 自由传数值或 Provider 自行决定：

- `max_tool_calls=2`：按执行尝试扣减，参数拒绝 / Handler ERROR 不返还预算；实际 Handler 执行数另记。
- `max_tool_rounds=2`：一个模型响应提出调用并进入受控执行，算一轮；本版每轮仅一个 Tool。
- `max_model_requests=3`：模型调用前占用额度；预检 blocked、已发出请求与 transport attempts 分开记，不能用 Usage request_count 代替网络计数。
- `max_calls_per_round=1`：收到多个 calls，整批拒绝，不能偷偷只执行第一个。
- retry=0：新的有界执行入口必须冻结无重试 Runtime，不能依靠循环绕过预算；不改变旧无 Tool 业务路径的重试配置。
- 保留单参数 / 单结果上限；增加累计 Tool Result 与完整消息字节上限。两次 32768-byte 结果可以作为累计 64 KiB 的初始硬上限候选，模型 Context 仍需单独限额；字节数不是 token 数。
- 设置每次输出上限与整 Turn monotonic deadline；每次请求使用剩余时间与现有 connect/read/total timeout 的较小值。不能让三次请求各重获完整 Turn 时间。

三次模型请求只在上限为两轮且需要最终回答时使用：Request #1 auto；一次 Tool 后 Request #2 若仍有预算则 auto；第二次 Tool 后 Request #3 none。执行 Tool 前必须预留一次后续模型请求，不能先执行再发现无法回答。

模型在任意请求返回 Final 都停止；非 AUTO Requirement 未满足则由 gate 拒绝成功，不能自动补调用。最后强制 Final 的请求仍返回 calls 时，保留 TOOL_ROUND_LIMIT 语义；不得进入第四次请求。

### 4.2 状态机

```text
Preparing / freeze Runtime + Policy + Budget
  → Model request i
      → Final → Assistant Commit Gate → Completed / Failed
      → Tool calls
          → 数量、预算、授权、完整性检查
          → Tool attempt j → validated result + source receipt
          → append assistant(call) + tool(result)
          → 检查剩余额度，Model request i+1
任何阶段 → Cancelled / Failed；不 resume，不自动 retry
```

只有 Coordinator 负责继续 / 结束；Executor 不调用模型，Adapter 不决定下一 Tool，UI 不推进状态机。最后一轮仍保留 Registry 定义并发送 tool_choice=none，沿用现有 ModelRequest 合同要求，不临时发明不兼容的编码。

### 4.3 业务状态、错误与部分成功

| Tool 结果 | 编排与来源处理 |
| --- | --- |
| OK | 校验 payload 后记录来源；模型可 Final，也可在预算内选择另一授权 Tool |
| NO_DATA | 合法查询 / 评分完成，但无 Snapshot；不重新 Apply、生成 normal 或自动重查 |
| PARTIAL / INVALID / STALE | 保留真实字段、质量、Freshness 与时间。水质查询的这些限制在 OK payload 内；评分可为 PARTIAL / NOT_SCORABLE，不能统称 ERROR |
| NOT_SCORABLE | 合法评分操作已完成，但没有评分；若有 canonical observation，保留其受限来源 |
| NO_MATCH | 检索完成，没有 Evidence 命中；模型可说明无命中或在预算内自主选择另一查询，程序不自动放宽检索 |
| ERROR / unknown / unauthorized / malformed | 首版终止整 Turn，不把异常送给模型要求它修参数或继续。安全错误与执行步骤留存，无成功正文 |
| 后续模型失败 / 截断 / 取消 | 已确认的本地执行 Receipt 和 Usage 不被抹除；Turn 不能成为成功历史 |

“部分成功”首先是执行审计状态，不是新的 successful_turn。将来如要允许某些 Tool ERROR 后生成带限制的答案，应单独定义可恢复错误策略；不能本次顺手变更现有错误即停止合同。

### 4.4 重复与循环

整 Turn 只创建一个 Executor，复用 `_seen`，而不是每轮重建以重获 max_calls。相同 call id 跨轮拒绝；模型换新 id 也不能绕过逻辑重复限制。

建议再限制同一 Tool + **validator 归一后的参数**的重复调用，例如水质 `{}` 或相同规范 query 一轮内最多一次。签名只在内存去重，不把 query、参数或其可猜测 hash 写 Trace。当前 `ToolDefinition.bind()` 只返回 Callable，签名取得需要最小内部绑定合同，不能在 Coordinator 复制 validator。不同 query 可在总预算内评估，不能因为 NO_MATCH 自动放宽或重试。

预算已经防止无限循环，逻辑去重则防止有限但无益的重复。重复拒绝必须说明它是本 Turn 的执行限制，不能归因于 Provider capability。

## 5. Result、Turn Trace 与 Source Ledger

### 5.1 有序 step 取代固定两个槽位

建议把 `ToolConversationResult` 的内部真相演进为有界的 `model_steps[]` 与 `tool_steps[]`，用共同 seq 关联，而非添加 request_3、tool_result_2 再继续扩展。

- Model step：step id、序号、outcome、safe error、finish_reason、Usage、latency、发送 / transport 计数。
- Tool step：对应 model step / call id、Registry 名称、attempted / executed / result 状态、duration、内部结果引用与有限 Receipt。
- Turn：request_id、trace_id、终态、最终正文、final model step、全步 Usage、预算使用和总耗时。

完整结果仅供内部消息构造，不在 Trace 重复保存 payload。内部 call id 必须关联唯一执行；外部 Trace 继续按现有字符 / 长度 allowlist 投影。

旧 `request_1/request_2` 可作为单轮模式的派生兼容投影，不能形成第二套可写真相。多步下旧 `tool_result` 不能默认为“最后一次”并漏掉其他调用；未迁移的 Analysis / Qualification 消费者应继续用 legacy 一轮模式，或明确拒绝新形态，直到其投影完成迁移。

### 5.2 保留单次 Receipt，增加 Turn 内 Ledger

**不把 TurnSourceReceipt 改成一份扁平的多来源事实。** 保留它作为一次合法执行的有限来源证明；新增有序、不可变的 TurnSourceLedger，包含执行关联 + 每次 Receipt。Ledger 仅由 Coordinator 接收的真实校验结果产生，不从 Web、正文、历史或事件展示反序列化。

目前 `receipt_from_execution()` 依赖 `request_1` 和单个 result。未来先提取“已关联执行 → Receipt”的确定性校验，现有函数作为单轮 wrapper；不要每轮伪造一个 ToolConversationResult 来适配。Source 派生应位于共享执行合同层并被 Assistant 消费，避免 Coordinator 反向依赖 AssistantService 形成循环。

Ledger 保留 operation completed 与正向 source 两层：

| 实际执行 | operation | 正向来源 |
| --- | --- | --- |
| 水质 OK，含合法 canonical reading | observation query completed | observation；INVALID / PARTIAL / STALE 限制保留 |
| 水质 NO_DATA | observation query completed | 无 observation |
| 评分 OK / 合法 PARTIAL | score evaluation 与 observation query completed | score + observation，带实际限制 |
| 评分 NOT_SCORABLE | 合法 payload 下 score evaluation 与 observation query completed | 受限 observation，无 score |
| 评分 NO_DATA | 两种操作 completed | 无 observation / score |
| Knowledge OK | project search completed | 有限 project evidence 与 count |
| Knowledge NO_MATCH | project search completed | 无 project evidence |
| ERROR / 未调用 / 文字仿调用 / malformed payload | 不授予完成 | 不授予来源 |

以上沿用当前 P1.1 的 payload 校验语义，不按工具名机械授予。只取得“Handler 已开始”但取消前没有收到合法结果，也不能认证完成。

### 5.3 满足函数与提交 gate

现有 Requirement 枚举语义不变；单 Receipt 满足函数保留为兼容，另提供对 Ledger 的确定性满足检查：AUTO 总为真；其余要求由本 Turn 至少一项合法 Receipt 的对应 operation_completed 满足。评分真实读取的观测可以按当前规则满足查询要求，查询本身不能满足评分，Knowledge 不能满足现场观测。

不新增自然语言 Requirement 推断，也不把浏览器“已使用 Tool”当来源。若未来需要“查询且检索”的复合要求，应独立评审，不暗改现有单枚举含义。

成功提交仍须：最终非空正文 + stop + 无执行 / 安全错误 + 未取消 + Requirement 满足 + Trace 成功。每次模型请求的 Usage 独立保留，使用现有 UsageAccumulator 汇总；任一 usage 缺失仍是 unknown，不补零。

Ledger 可以保留“第一个查询有观测，第二个评分无数据”等序列，但不能合并质量 / 时间后宣称同一时刻的新鲜完整观测。逐项保留时间与来源，Sources 并集只表示本轮曾获取的来源。Receipt 仍不证明最终自然语言忠实使用了这些来源，AUTO 的现有正文真实性限制不会因多轮自动消失。

Ledger 与 Tool 协议消息只属于本 Turn；成功 History 仍只有 user / assistant final pair，不能把 Ledger、原始 Tool JSON 或协议消息写进 completedTurns。

## 6. Cancellation、时间与观测一致性

所有轮共用原 RequestHandle、CredentialSnapshot 和冻结 Policy；每次模型 / Tool 开始前、返回后、下一轮前与 commit 时检查取消。Adapter 现有 async bridge 可以每次绑定当前 SDK task，关闭 stream / client 后解绑，再进入下一步。

当前 `_bridge` 有 maxsize=32 队列和消费者关闭清理，可以复用；不能开下一次 SDK 请求而仍遗留上一步 client / worker。`backend_io_closed` 表示当时本地 I/O 状态，不是整 Turn 完成或远端停算证明。远端计算 / 计费停止仍显示 unknown。

Handler 当前是短的同步只读操作，取消主要是边界检查，不能声称能抢占任意 Python 函数。已完成、校验通过的来源可保留；取消不提交半成品回答、不写能力证据。

整 Turn deadline 需要与 Adapter 的剩余时间和 I/O 终止连接，不能只在两次请求之间检查。预算 / timeout 不能伪装为 USER_CANCELLED。当前阶段 phase enum 应改为安全 kind + model index / tool round，而非无止境增加 REQUEST_3 等枚举。

多轮 Tool 继续查询执行时的当前 Snapshot，不锁死整 Turn 现场；若用户期间 Apply 新 Snapshot，两个 Tool Result 可能不同。保留各自 observed_at/evaluated_at/source，不能改 Store 或把后一次值覆盖 Analysis 启动时捕获的 Facts。跨轮一致性问题不交给 LLM 判定数据有效性。

## 7. Streaming Transport 独立设计

### 7.1 合同与组装位置

当前 ModelToolCall 构造即要求完整 JSON object，不能拿它表示半截 arguments。建议 Adapter 内部增加有界 assembler，按 request / choice / tool-call index 聚合碎片，最后产出既有完整 ModelToolCall 与完整 ModelResponse。

Provider delta 的 name、id、arguments 的拼接或重复字段规则放在 Adapter 的协议归一层；ProtocolSpec 继续只负责怎么编码参数，不能获得循环决策或模型能力授权。先只处理当前 Chat Completions 路径与一个 choice，不新增 Provider / 任意协议。

Gateway 的增量合同可增加规范化 Tool 片段事件与一个完整模型 step 终止结果；二者职责不同。Coordinator 只消费**完整结果**决定执行，不认识厂商字段，不由 Web 拼 arguments。

### 7.2 何时可以执行 Tool

必须完成整个模型 step：正常语义终止、调用结构完整、arguments JSON object 可解析、只有一个调用、预算 / Policy / validator 合法，并完成 SDK stream/client 清理。为兼容尾部 usage-only chunk，应等待该 step 正常排空；大括号暂时闭合、首个 finish 标志或 TCP EOF 单独都不足以执行。

要求累计 arguments ≤现有 4096 bytes；同时限制 id/name、片段数量、流字节数、Tool 数及等待时间。缺字段、重复 / 冲突 id、未知 choice、非法 JSON、length 截断、异常 EOF 或中断必须安全失败，不能修补 JSON、执行半个调用或自动重试。合法参数的业务验证仍交 Executor。

non-streaming 新多轮路径也应检查截断调用：当前 Coordinator 主要校验调用结构，Assistant gate 校验最后回答的 finish_reason，不能把首轮 length 下恰好可解析的参数自动当完整意图。

不同 Provider 的 delta 和 finish 表现本轮没有真实取证。不能假设现有三 Preset 都满足相同组装规则；缺失终止证据的兼容策略必须由离线 SDK fixtures 与以后受控资格验证确认，不能猜测放行。

### 7.3 Tool 后开始下一个流

先关闭上一 step 资源 → 执行固定 Handler → 添加 assistant(call) / tool(result) → 检查 Turn 预算 / 取消 → 打开下一次 Gateway stream。整个过程由与 complete 路径相同的 Coordinator 状态机负责，差别只在一次模型 step 怎样得到完整响应。

任意 Tool delta 一旦被 Adapter 接受，就属于可观察输出；不能只用 content / reasoning 非空判断 emitted。现有 `_bridge` / sync stream 的 emitted 逻辑需同步扩展，否则可能在收到部分调用后重新生成另一套 id / arguments。首版 retry=0 也必须有相关测试锁定。

### 7.4 三种组合需要分别验证

- 全部模型步骤 complete：先实现多轮逻辑。
- Tool 决策步骤 complete，末步 stream：可作为较小传输试点，但先前 tool 消息仍令 `uses_tools=True`，当前 Gateway 一样拒绝；不是零改动。且不能自动证明首轮可 Streaming Tool Call。
- 每个模型步骤都 stream：真正的 Streaming Tool Calling，需要 assembler、完整 step 结果与公开事件合同。

普通 streaming、普通 tool_calling 两项 SUPPORTED 不证明二者组合；已有 Preset Tool qualification 基于 OFF + Normal，不自动发布 Streaming Tool 或更多轮。新模式需独立的维护者发布 / 精确资格依据，研究代码不能改 Capability / Evidence。

## 8. 一个连续 Turn 的 Web / UI 与安全投影

建议一个请求 id、一个 pending user、一个最终 assistant 消息。多个模型 step 只是此 Turn 内部阶段，事件使用 turn id + seq + model step index / Tool round，终态只能提交一次。

公开事件候选：turn_started、model_step_started、tool_started、tool_completed、content_delta、model_step_completed、usage、completed / failed / cancelled。字段均安全投影，Tool 参数只给有界摘要，不给 query、raw arguments、原始结果、Prompt 或 reasoning 原文。

模型 step 的正文未必是最终答案：正文之后仍可能出现 tool_calls。必须区分 step provisional text 与最终正文；不能把几个步骤的内容直接拼为一个回答。首版可缓冲 Tool 决策步骤正文，最后强制 none 的 step 才渐进展示；其内容仍是 provisional，只有最终 gate 成功才进入 History。提前 Final 则把该 step 的已缓冲正文提交，不能为了制造流式效果再发一次请求。

现有 Assistant 的 Secret 替换在完整最终文本阶段；直接发送原始 content delta 会越过这道边界。流式公开正文前必须设计跨 chunk 脱敏 / 缓冲，不能只对每个小片段 replace。正式 UI 继续 textContent，完成 / 取消 / 失败迟到事件不改变已收口状态。

当前 `/api/assistant/chat` 仅 JSON + phase polling，不能假定已有 Assistant SSE。可以复用现有 Analysis SSE framing 和 disconnect 清理模式，新增独立 Assistant 流式入口；不得把 Tool loop 复制进 Web 或修改原 Analysis Streaming。

正式 Activity 显示“本次执行 N 个 Tool”，展开逐项名称、状态、耗时和必要时间 / Freshness；Trace 使用可扩展步骤摘要。Development/Test 保留完整**安全** trace，仍不包含 Prompt、Secret、原始参数或结果。Source Ledger 默认内部使用，除非有消费者需求，不扩成大型用户面板。

一次联网确认覆盖冻结的最大请求预算，并更新“两次”文案为相应上限；任何成本数字只使用实际 Usage。断流 / abort / Stop 不续跑、不自动重发，服务端在收到断开时取消当前 I/O；不能保证浏览器断开立刻被服务端发现或 Provider 已停止计费。

## 9. Prompt、应用边界与资格边界

现有 Assistant v2 写有“只选择一个最相关的 Tool，取得结果后直接回答”；开发 Tool Conversation 也要求不再 Tool；Analysis instruction 与 final_response_instruction 同样要求终结。仅放开 Coordinator 会产生文字与执行合同冲突。

本轮不改这些指令。未来开启多轮之前，应单独审查最小跨轮规则：允许在**每轮**选择一个授权 Tool，结果不足可在硬预算内继续；无需来源或已经足够即可 Final。最终响应指令只附于必须终结的请求，不反复塞入每个中间 follow-up。Assistant 来源安全、纯文本与 History v2 语义保持；硬预算仍由程序执行。

推荐先以内部 scripted / Development 路径验证非流式多轮，正式 Assistant / Analysis 仍运行 1/1/2。Assistant 产品启用后仍限定已发布 Preset，OFF + Normal。Analysis 继续保留固定 Snapshot → Diagnosis → RAG → Context，随后再显式决定是否采用新预算，不能被共享 Coordinator 默认升级。

Manual V1/V2 原始传输绝不变成 Tool Executor 消费者；qualification 实现留在 [development/qualification](../../../src/fishery_ai/development/qualification/)，旧研究报告与既有 Preset 资格不能自动成为新多轮 / 流式支持证据。预算或结果合同变动需要离线兼容测试，不借旧授权重跑实验。

## 10. 必须保留的硬合同

READ ONLY；静态 Registry ∩ 冻结 Policy ∩ Executable ∩ Runtime capability；JSON 参数对象与 validator；精确模型合同，不做 Provider/family 继承；私有 Credential 组合与请求快照；来源仅来自真实 backend result；NO_DATA / NO_MATCH 与 ERROR 区分；不把操作完成等同正向 payload；最终 Commit Gate；失败 / 截断 / 取消不入 completed History；Analysis Facts 不覆盖；History B / A 回滚语义；Manual 不执行 Tool；Secret / 私有路径 / Prompt 不进 Trace；远端停算 unknown。

预算放宽必须是显式版本化、可回滚的内部运行方案；不能由 Prompt、LLM、用户消息或中途 Policy 修改增额。不设 model-specific 业务路由，不把新 Coordinator 变成 Evidence Resolver 或能力自动发现服务。

## 11. 建议离线测试

以现有 tests 为基础，先写 scripted invariant，不以 Mock 关键词行为代替真实选择证据：

- Request #1 Final、Tool→Final、Tool A→Tool B→Final；A 的结果确实进入 B 决策请求，第二 Tool 仍由模型输出决定。
- 单轮 / 全 Turn / model request 上限、执行前预留 Final 额度、每轮多 calls 整批拒绝、跨轮 duplicate id / 规范参数重复、无第四次请求。
- NO_DATA、NO_MATCH、NOT_SCORABLE、PARTIAL、INVALID、STALE；后一步 ERROR / Provider 失败保留前一步审计但不成功提交。
- 每个 Receipt 的真实关联、操作与 payload 分离、不同观测时间不合并；正文 / 历史仿调用无 Ledger；非 AUTO 未满足不自动补调用。
- 每个边界取消、Turn deadline、SDK 清理、跨轮 hook 重绑、缺失 Usage 不补零、Trace 失败不提交。
- Streaming 离线碎片：跨 chunk JSON escaping / Unicode、usage-only 尾块、finish / EOF 顺序、畸形 / 截断 / 多调用、delta 后不重试、取消 / disconnect 无 Handler 执行。
- Web 一个 Turn、多 step 的 provisional / final 分离、旧消息不复用为当前来源、跨 chunk Secret 脱敏、epoch / History / Manual / Analysis 原流程兼容。

当前主要基线：[Coordinator tests](../../../tests/tools/test_tool_conversation.py)、[Gateway Tool contract tests](../../../tests/providers/test_gateway_tool_contract.py)、[Executor tests](../../../tests/tools/test_read_only_tools.py)、[Source tests](../../../tests/assistant/test_assistant_sources.py)、[Execution tests](../../../tests/security/test_execution.py)、[Analysis Tool tests](../../../tests/tools/test_analysis_tools.py)、[Browser tests](../../../tests/web/test_browser_streaming.cjs)。本轮仅阅读，未执行或声称新增覆盖已通过。

## 12. Current → Proposed Runtime Flow

```text
Current
  Assistant Context / 固定 Analysis Context
    → Request #1(auto)
        ├─ Final → commit
        └─ 一个 Tool → 单个 result / receipt
             → Request #2(none) → Final → commit

Proposed：先 non-streaming，默认仍可退回 Current
  Context + frozen Runtime / Policy + finite Budget
    → Request #1(auto)
        ├─ Final → Ledger requirement + commit gate
        └─ Tool A → Executor → Result A + Receipt A
             → Request #2(auto，若尚有 Tool / Final 预算)
                 ├─ Final → Ledger requirement + commit gate
                 └─ Tool B → 同一 Executor → Result B + Receipt B
                      → Request #3(none) → Final → commit gate
  全路径：有序 steps / Ledger / Usage；error、取消、预算耗尽立即终止

Later Streaming：只替换一次 Model step 的取得方式
  SDK delta → Adapter bounded assembler → 完整 ModelResponse
    → 同一 Coordinator 的 Final / Tool 决策
    → Tool Result → 下一 Model step；Web 全程仅一个 Turn
```

## 13. 需要修改的核心模块地图

| 优先级 | 未来最小修改点 | 本轮状态 |
| --- | --- | --- |
| 第一小步 | tool_conversation：step / budget 结果合同；assistant_sources：逐执行 Receipt 与 Ledger；observability：安全数组投影 | 阶段 1 已实现；仍固定 1/1/2 |
| non-streaming 多轮 | 共享 run_request 有界状态机；一个 Executor 跨轮；tools/contracts 的必要内部归一绑定；execution 的 indexed progress / Turn deadline | 不新增 Handler / Registry 或第二套循环 |
| 应用接入 | assistant / application / contracts / web / UI：分别消费新版 steps / Activity，旧模式派生兼容；联网预算说明 | 正式应用需逐项启用，Analysis 不自动升级 |
| Streaming | model_gateway：片段与完整 step 事件；Adapter：assembler、emitted、终止 / 清理；execution：剩余 Turn 时间传输 | ProtocolSpec 只在已有协议编码确有需要时调整，不能承载编排 |
| 公开 Stream | Assistant SSE 接入、安全事件与 delta 脱敏、前端 pending / commit、Development Trace | 不复写原 Analysis Streaming 或 Manual 栈 |
| 验证与发布 | qualification 开发边界与对应 tests；维护者按精确模型资格发布新的运行范围 | 无自动 Provider 请求或能力推广 |

## 14. 推荐阶段划分

1. **合同基础（已实现）**：steps / Ledger / budget / safe trace，单执行 Receipt 语义保持；legacy 投影保留 1/1/2 和原 Prompt、History、UI。progress 阶段名称保持原样，离线 parity 后停止审查。
2. **有界 non-streaming**：内部显式模式试验 2/2/3、统一 Deadline、去重和错误收口，scripted 测试证明提前 Final 和结果影响下一 Tool；再审查对应的最小指令版本。
3. **资格与单应用发布**：另获授权做精确模型资格，不沿用单轮资格推导；先 Assistant 或 Development 一个消费者，feature flag 可回滚，Analysis 保持旧预算直到独立批准。
4. **Streaming 协议基础**：先在 1/1/2 离线验证 assembler / 生命周期，再用同一 Coordinator 覆盖 2/2/3；此时尚不必公开流式正文。
5. **Streaming 产品接入**：精确 Streaming + Tool 资格、公开 SSE / 安全渲染、一个 Turn 的多 step Activity、真实 Stop 人工验收。

## 15. 风险、暂不做事项与实施建议

最大风险是固定两槽结果的消费者遗漏第二次 Tool，扁平 Receipt 把不同时间观测混合，及未闭合 stream 就执行 Tool / 重试。其次是 Prompt 仍要求直接 Final、deadline 每轮重置、只按完整文本脱敏而提前发送 delta，以及把已有 tool_calling 支持当作流式组合支持。

暂不做：并行多个 Tool、无限重试或修参数循环、Agent / planner 框架、Memory / DB History、写操作、设备控制、动态 Tool、Provider failover、新 Provider、Thinking ON Tool、自动 Intent Router、自动能力扫描、历史实验补跑。

**建议现在只实施阶段 1：有序执行结果与 Source Ledger 基础，保留现有预算和行为。** 它能先消除单结果槽位的结构风险，并给后续 scripted 多轮提供确定性验证面。不要现在一次性开放 Multi-Round + Streaming；每次扩展独立验收，模型规划自由只能在已发布的程序预算与来源门禁内运行。

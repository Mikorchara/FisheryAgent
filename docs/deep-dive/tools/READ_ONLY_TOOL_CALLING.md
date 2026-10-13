# 只读 Tool 当前实现

本文说明 Gateway 协议、执行层与应用接入的当前边界。Tool Calling 不等于 Agent。

## 数据流

```text
ModelRequest.tools（来自 Registry 定义并经过 Policy 筛选）
→ ModelGateway / OpenAI-compatible Adapter
→ assistant.tool_calls
→ ToolCallingService
→ ToolExecutor（Registry + Policy + 参数/预算/取消校验）
→ role=tool JSON
→ 第二次模型请求（tool_choice=none）
→ 最终正文
```

T1 模型合同表达 tool definition、assistant tool call、tool_call_id、role=tool 和后续请求。Adapter 负责 OpenAI-compatible SDK 编码/解析；这只证明协议可表达，不自动证明某模型支持工具。当前 Preset 的 Tool Calling 固定合同已分别资格验证；Managed Custom 仍需精确 Identity 的 Capability gate。

## Registry、Policy 与执行

- `src/fishery_ai/tools/registry.py` 是静态执行 allowlist，当前有 `get_current_water_quality`、`score_current_water_quality`、`search_fishery_knowledge`。Knowledge 只在注入 KnowledgeService 的实例中绑定并暴露。
- `catalog.py` 提供显示文案与通用 metadata，不注册 Handler、不校验参数、不产生执行权；当前用户 Policy override 校验还使用它的 executable 集合，并非完全与权限配置无关。
- `policy.py` 只允许从 Registry 中筛选名称。用户设置写入固定的 Git ignored `outputs/tool-policies/tool_policies.json`；新请求捕获冻结 Policy。
- `executor.py` 校验调用名、参数、预算、结果大小与取消；未知或未授权请求安全拒绝。Handler 不读取任意文件、Scenario 或原始模拟包，也不做网络、设备或数据库写操作。
- `handlers/current_water_quality.py` 经共享 `CurrentWaterQualityReader` 获取 query-time view，再调用 `DiagnosisService`。
- `handlers/water_quality_score.py` 经同一个 Reader 调用 `WaterQualityScoringService`。评分是 Experimental，不是专业养殖标准。
- `handlers/knowledge_search.py` 使用 Web 组合层注入的同一个 KnowledgeService；先绑定 Registry，再创建 UserToolPolicyStore。Analysis 自动 RAG 与 Tool 检索共享服务，不另建索引。

## Knowledge 参数与结果

`search_fishery_knowledge({"query": "..."})` 只接受 query 字符串；strip 后非空、最多 512 字符，拒绝归一化后仍存在的控制字符和 lone surrogate。Schema 声明 required query 与 additionalProperties=false；Executor 在 Handler 前执行显式 validator，另限制 JSON object / 4096 UTF-8 bytes。

Handler 固定 top_k=3，返回 status、retrieval_mode、result_count、evidence。Evidence 仅含 id、category、source、source_version、text；正文超过 800 字符时截断并另附省略号，不输出 score、retrieved_at、source_title 或 retrieval_version。无合格命中为 NO_MATCH，正常进入第二轮；执行失败为安全 ERROR，不能伪装成无命中。统一结果上限为 32768 bytes。

包内默认 Analysis 关闭且无 Tool，Assistant 仅开放水质查询；Knowledge 默认不授权。用户 override 可显式选择已绑定 Tool，新注册不自动改写旧选择。UI 使用 Catalog 标签，参数只显示“参数已提供（内容未展示）”，query 原文不进入 Activity / Trace。

## 两种正式应用接入

### Analysis

固定流始终为 Snapshot → Diagnosis → RAG → Context → LLM。Analysis Policy 未启用时保持无 Tool 的原请求；启用后仅在 Normal 请求中提供允许的定义。模型可直答或调用一个 Tool。Tool 观测与分析开始时的 Observed Facts 分开保存，不静默覆盖；Analysis JSON 合同仍是最终输出边界。启用 Tool 的 Streaming 明确返回不支持。

### Assistant

Prototype 本地试用已获用户授权：仅 OFF + Normal 且恰好授权查询+Knowledge时，Qwen已验证发布、DeepSeek / Ollama独立实验范围可通过同一协调器使用2/2/3；其余范围和Analysis仍1/1/2。实验状态不等于真实资格，界面显示发布状态、有效预算与回退原因。Flag关闭并完整重启即可回滚；执行失败不重跑。见[发布与操作](../research/ASSISTANT_MULTI_ROUND_INTEGRATION.md#11-phase-4c-三预设本地试用发布)。

仅三个已发布 Preset 的 OFF + Normal 连接可用。首轮不注入 Snapshot / Diagnosis / RAG；请求中的工具定义由 Assistant Policy 过滤。历史只接收完整成功 user / assistant 文本对，整轮裁剪后默认投影为一个未受信任的 user JSON transcript；当前问题独立。Tool 协议消息、原始 Result 与 Receipt 不进入历史。

真实执行结果另外生成有限来源 Receipt，区分查询/评分/搜索完成与实际观测/评分/Evidence 是否存在。NO_DATA / NOT_SCORABLE / NO_MATCH 可以完成对应操作而不产生正向来源；ERROR 或文字仿调用不能满足操作要求。内部非 AUTO 要求不满足时拒绝成功提交；普通 Web 仍为 AUTO，不根据正文或用户自然语言自动授予来源。详见[Assistant 当前来源合同](../architecture/ASSISTANT_MODEL_V1_DESIGN.md#本轮来源与提交合同)。

### 有界执行与取消

正式应用默认协调器最多执行 1 个调用、1 个 Tool round、2 次模型请求。多调用返回 `TOOL_CALL_LIMIT`，第二轮继续请求 Tool 返回 `TOOL_ROUND_LIMIT`；没有 Agent loop。首轮后、执行前后及第二次请求前沿用同一 `RequestHandle` 检查取消。取消不写 Capability Evidence，也不把部分回答提交为成功；不保证远端推理/计费停止。

### 内部结果、来源与预算合同

`ToolConversationResult.steps` 是唯一的执行结果序列：`ModelExecutionStep` 保存 seq、request_index、request_started 和 ModelStepOutcome；`ToolExecutionStep` 保存关联的模型请求、Tool round、call id/name、handler_started、执行结果与耗时。request_started 表示已进入 Gateway，不证明实际网络次数；handler_started 只在 Executor 原有授权、参数、取消检查后、进入 Handler 时设置。直答只有一个模型 step，Tool→Final 为 model / tool / model；未开始的后续请求不制造 step。`request_1/request_2/tool_result/tool_name/tool_call_id/tool_duration_ms` 仅为只读兼容投影，不能单独写入；超出单轮形态时明确拒绝旧投影，不取“最后一次 Tool”。

`assistant_sources.py` 从每个实际返回的关联执行生成独立 Receipt，组成不可变 `TurnSourceLedger`。每项保留执行 seq、model_request_index、tool_round 和 Receipt 的独立质量/时间；不合并观测值或时间。ERROR 可留下无完成证明的条目；未取得结果的调用、正文与历史不生成条目。单次 `receipt_from_execution()` 与 Assistant `source_receipt` 都是 Ledger 的单执行投影。

`requirement_satisfied_by_ledger()` 沿用原 Requirement 语义：AUTO 始终满足，其余要求需本轮至少一项 Receipt 证明对应操作已完成。NO_DATA / NO_MATCH / NOT_SCORABLE / PARTIAL 的校验与正向来源授予规则不变。Assistant gate 使用 Ledger，Web Activity 使用同一 steps 的安全数组投影；Ledger、协议消息及原始 Tool Result 都不进入 History。

内部 `ToolTurnBudget` 声明有限调用/轮次/请求和 step 上限。默认模式固定 **1/1/2，最多 3 steps**，不能仅传较大预算开启多轮，follow-up 仍为 `tool_choice=none`。JSONL Trace 记录有序 steps 安全摘要，原单轮字段从同一序列派生；不写 Prompt、正文、arguments 或原始 payload。

### 内部 non-streaming 有界多轮

仅内部代码可显式构造 `ToolCallingService(..., execution_mode=ToolExecutionMode.BOUNDED_MULTI_ROUND)`，固定预算 **2 calls / 2 rounds / 3 requests，最多 5 steps**。传入其他预算、非枚举模式或 retry 非零的 Runtime 会安全拒绝。该模式使用 `run_request()` 接收 scripted ModelRequest；`converse()` 不复用要求单轮的旧开发 Prompt。没有 Web request/UI 开关，也没有修改 Assistant / Analysis Prompt。

```text
Request #1(auto)
  ├─ Final → 结束
  └─ Tool A → 真实 Result A → Request #2(auto)
       ├─ Final → 提前结束，不消费剩余预算
       └─ Tool B → 真实 Result B → Request #3(none) → Final
```

这是同一个共享状态机。后续请求累积原消息及 `assistant(tool_calls)` / `tool(tool_call_id, result)`，模型看到真实结果后自行选择；程序不预执行或规划 Tool B。每轮多个 calls 整批拒绝；调用前预留一次 Final 请求，第三次仍请求 Tool 则 `TOOL_ROUND_LIMIT`，绝不发第四次。额外 final response instruction 只附在强制 Final 的请求上。

同一 Turn 捕获冻结 Policy、同一个 Runtime / CredentialSnapshot，并复用一个 Executor。内部多轮启用 call id 和逻辑请求去重：`ToolDefinition.prepare()` 校验一次，Executor 用 Tool name + validator 归一后参数生成内存签名；重放 id 为 `TOOL_CALL_ALREADY_EXECUTED`，重复逻辑请求为 `TOOL_REQUEST_ALREADY_EXECUTED`。参数、签名或 hash 都不进入 Trace。默认单轮 Executor 的授权/参数行为不变。NO_DATA / NO_MATCH 等不会触发自动重试、参数改写或补查；模型可以 Final，也可以选择预算内另一个不同请求。

ERROR、未授权、畸形/截断调用、Provider 失败和取消立即停止。已有执行结果与 Ledger 保留审计，但失败/取消 Turn 不返回成功正文；缺失 Usage 保持 unknown。多轮 Final 要求非空正文和 stop，截断不能成功。每次请求、进度回调后、Tool 前后都沿用 RequestHandle 的取消检查；内部第三次请求使用安全 REQUEST_3 阶段。Trace 写失败也不能成功提交。

SourceRequirement / Receipt / Ledger 满足语义未改。协调器输出的是执行结果，**不能只凭 COMPLETED 替代来源 Commit Gate**：内部消费者仍需对本轮 Ledger 检查 Requirement；历史文字不补来源，Tool ERROR 不授予完成。Assistant 默认拒绝多轮协调器，内部显式配置可复用同一循环执行 2/2/3，并使用独立版本化 Prompt 与整 Turn deadline；Analysis / Web / 原单轮 qualification 仍构造默认 1/1/2。History 只保存原有成功 user / final assistant pair，多个 Receipt 不进入 History，也不投影成最后一个 Tool。

单独调用协调器时，预算只限制次数，不自行创建整 Turn deadline；内部 Assistant 显式模式在同一个 RequestHandle 上设置统一截止时间，Adapter 裁剪剩余时间。独立 Phase 3 qualification 仍沿用原逐请求 timeout，不随 Assistant 接入自动改变。正式多轮 Prompt 尚无真实资格结论，不更改 Preset / Capability 合同，也未开放 Web 多轮、Streaming、并行 Tool 或 Agent。

### 单案例多轮资格入口

`scripts/qualification/qualify_multi_round.py` 调用 `development/qualification/multi_round_qualification.py`。它是开发边界内的长期单次工具，不接正式 AssistantService，也不启用产品多轮；默认 dry-run，不解析凭据、不装配 Handler/SDK、不生成报告。真实运行必须逐个 case 获本轮授权并传 `--confirm-network`，无永久授权文件、批处理或自动补样本。

默认发布 Preset 为 Qwen 3.8 Flash，按当前固定合同解析 exact Identity / ProtocolSpec / OFF + Normal；未知 Tool capability 不绕过。复用正式 private credential composition、RuntimeSnapshot / CredentialSnapshot、QualificationAdapter 的受限输出预算和 raw/normalized 安全观测、共享 ToolCallingService / Registry / Executor、RequestHandle 与现有安全报告写入。不改 Preset、Evidence、全局 Policy、Web Snapshot 或正式 Prompt。

| case | 隔离合成水质 | 预期执行序列 | 最大模型请求 |
| --- | --- | --- | --- |
| low-oxygen | 28℃ / pH 7.5 / DO 2.2 | 查询当前水质→模型看到异常后检索知识→Final | 3 |
| normal | 28℃ / pH 7.5 / DO 6.4 | 查询当前水质→无需检索→Final | 2 |
| current-do | 同正常 fixture | 一次水质查询→直接 Final | 2 |
| concept | 同正常 fixture，但不应读取 | 无 Tool 直接 Final | 1 |

四项均暴露查询与 Knowledge 两个正式 Tool，模型自主选择，不预执行、不按自然语言硬路由。low-oxygen 与 normal 的问题完全相同，首轮不包含 fixture 数值；只有真实 Handler 返回的 Result 决定模型下一步。独立实验 System 指令明确允许结果后重新决策，同时要求正常场景不检索、概念题可直答；不使用仍要求 Tool 后直接回答的正式 Prompt。

Runtime 固定 2/2/3；单案例额外请求上限更严格，超过即停止，不为了得到预期路径放宽预算。正常/DO 案例若意外请求第二个 Tool，会记录模型调用但不执行 Handler、不发第三次请求；concept 意外调用也不会执行 Handler。每请求最多 256 tokens；逐请求 timeout 沿用冻结 Runtime，尚无整 Turn deadline。Provider 错误、截断、参数错误、取消均结束，不自动 retry、修参数或切换 Provider。

报告区分模型提出的 normalized calls、实际 execution steps、每个 Result 的状态/耗时、下一请求是否确实包含该执行的原 Result、逐执行 Ledger、Usage、finish reason、最终正文存在性及提前结束。原始 Provider 调用一致性来自既有 QualificationAdapter；脚本测试明确标记 offline_fixture，不作为真实模型证据。正文、query、call id、完整 payload、Prompt、Credential / 私有路径不记录，不能据此评价回答质量。

资格通过同时要求：执行 COMPLETED；实际 Tool 顺序符合固定 case；每个 Result 原样进入后续请求；现有 Ledger 来源要求满足。真实分类另需实际 Adapter 的 Provider / normalized 一致性和 exact model 检查通过，不能用 scripted 回答充当 Provider 证据。low-oxygen 分别检查当前观测查询与项目搜索，复用确定性检查而不增加 SourceRequirement 类型；NO_MATCH 完成搜索但不认证知识命中。执行完成而路径/来源不满足仍不能 qualified，也不进入产品成功 History。执行失败保留已有 Ledger；报告写入失败时 CLI 保留已消耗请求数量，不让用户误以为尚未请求。

使用方法见[构建与运行](../../BUILD_RUN.md)。本阶段只完成离线准备，没有真实 Provider 数据，未发布多轮能力。

### Development/Test 与 Manual

Development/Test 可使用离线 Mock 或满足能力门禁的真实 Runtime，提供安全完整 Trace；真实请求由用户显式确认。Manual V1/V2 是 Raw 请求与展示路径，Tool Call 可传输/展示但绝不自动执行。

## 当前限制

- 不支持 Streaming Tool Calling、tool delta 拼接或 Streaming Tool Execution。
- Knowledge 已注册，真实受控资格实验与 History v2 迁移已完成；有限样本不代表长期 Tool 选择稳定性。普通 AUTO 下无 Tool 却声称已查询 / 评分 / 检索的正文仍可能提交成功；Prompt 与历史文字不构成执行证明。
- Assistant 按需 Knowledge 与 Analysis 自动 RAG 的双重来源、检索相关性和产品 AUTO 的来源保证仍待评估；History 默认 B 可内部回滚，不会因失败自动改投影或重发。
- 正式应用没有第二个 Tool round；内部模式最多两轮。没有多个 Tool 并行、Agent、Detection Tool、设备控制或写入操作。
- Protocol support、Preset 固定合同、Managed Evidence 和用户 Tool Policy 是不同层次，不能互相代替。

## 主要测试

T1/T2/T3：`test_gateway_tool_contract.py`、`test_read_only_tools.py`、`test_tool_conversation.py`。应用与 UI：`test_analysis_tools.py`、`test_analysis_tool_web.py`、`test_web_tool_conversation.py`、`test_assistant.py`、`test_browser_streaming.cjs`。自动测试使用 Mock / 临时数据，不发送真实模型请求。

`test_bounded_multi_round.py` 覆盖内部三种路径、真实结果驱动下一模型决策、提前 Final、固定预算、同轮多调用拒绝、归一参数去重、逐执行 Ledger、取消/Usage/安全 Trace 与默认 1/1/2 请求编码兼容。

`tests/assistant/test_assistant_multi_round.py` 覆盖内部 Assistant 显式启用、独立 Prompt、History/来源门禁、多步骤安全投影、失败与取消、整 Turn deadline 和默认单轮回退；`tests/security/test_execution.py` 使用阻塞的虚构 SDK 验证剩余时间限制及本机 I/O 关闭。正式 Web 尚未开放多轮，不以离线测试授予任何新 Provider 能力。

参数与知识执行覆盖：`test_tool_argument_contract.py`、`test_tool_status_no_match.py`、`test_knowledge_handler.py`、`test_knowledge_registration.py`、`test_knowledge_assembly.py`。历史实施与独立审计见[阶段总结](../../records/archive/knowledge-tool-v1/2026-10-knowledge-tool-v1-summary.md)，不能把历史测试数量当作当前验收。

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

仅三个已发布 Preset 的 OFF + Normal 连接可用。首轮不注入 Snapshot / Diagnosis / RAG；请求中的工具定义由 Assistant Policy 过滤。历史只接收完整成功 user / assistant 文本对，整轮裁剪后默认投影为一个未受信任的 user JSON transcript；当前问题独立。Tool 协议消息、原始 Result 与 Receipt 不进入历史。

真实执行结果另外生成有限来源 Receipt，区分查询/评分/搜索完成与实际观测/评分/Evidence 是否存在。NO_DATA / NOT_SCORABLE / NO_MATCH 可以完成对应操作而不产生正向来源；ERROR 或文字仿调用不能满足操作要求。内部非 AUTO 要求不满足时拒绝成功提交；普通 Web 仍为 AUTO，不根据正文或用户自然语言自动授予来源。详见[Assistant 当前来源合同](../architecture/ASSISTANT_MODEL_V1_DESIGN.md#本轮来源与提交合同)。

### 有界执行与取消

正式应用默认协调器最多执行 1 个调用、1 个 Tool round、2 次模型请求。多调用返回 `TOOL_CALL_LIMIT`，第二轮继续请求 Tool 返回 `TOOL_ROUND_LIMIT`；没有 Agent loop。首轮后、执行前后及第二次请求前沿用同一 `RequestHandle` 检查取消。取消不写 Capability Evidence，也不把部分回答提交为成功；不保证远端推理/计费停止。

### 内部结果、来源与预算合同

`ToolConversationResult.steps` 是唯一的执行结果序列：`ModelExecutionStep` 保存 seq、request_index 和 ModelStepOutcome；`ToolExecutionStep` 保存关联的模型请求、Tool round、call id/name、执行结果与耗时。直答只有一个模型 step，Tool→Final 为 model / tool / model；未开始的请求不制造 step。`request_1/request_2/tool_result/tool_name/tool_call_id/tool_duration_ms` 仅为只读兼容投影，不能单独写入；超出单轮形态时明确拒绝旧投影，不取“最后一次 Tool”。

`assistant_sources.py` 从每个实际返回的关联执行生成独立 Receipt，组成不可变 `TurnSourceLedger`。每项保留执行 seq、model_request_index、tool_round 和 Receipt 的独立质量/时间；不合并观测值或时间。ERROR 可留下无完成证明的条目；未取得结果的调用、正文与历史不生成条目。单次 `receipt_from_execution()` 与 Assistant `source_receipt` 都是 Ledger 的单执行投影。

`requirement_satisfied_by_ledger()` 沿用原 Requirement 语义：AUTO 始终满足，其余要求需本轮至少一项 Receipt 证明对应操作已完成。NO_DATA / NO_MATCH / NOT_SCORABLE / PARTIAL 的校验与正向来源授予规则不变。Assistant gate 使用 Ledger，Web 仍只输出原有轻量 Activity；Ledger、协议消息及原始 Tool Result 都不进入 History。

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

SourceRequirement / Receipt / Ledger 满足语义未改。协调器输出的是执行结果，**不能只凭 COMPLETED 替代来源 Commit Gate**：内部消费者仍需对本轮 Ledger 检查 Requirement；历史文字不补来源，Tool ERROR 不授予完成。正式 Assistant 明确拒绝多轮协调器，Analysis / Web / qualification 仍构造默认 1/1/2；History 只保存原有成功 user / assistant pair。

当前内部预算限制次数，不新增整 Turn deadline；各请求沿用冻结 Runtime 的现有 timeout，不能声称有跨三次请求的统一剩余时限。多轮未做真实模型资格验证，不更改 Preset / Capability 合同，也未开放 Streaming、并行 Tool 或 Agent。

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

参数与知识执行覆盖：`test_tool_argument_contract.py`、`test_tool_status_no_match.py`、`test_knowledge_handler.py`、`test_knowledge_registration.py`、`test_knowledge_assembly.py`。历史实施与独立审计见[阶段总结](../../records/archive/knowledge-tool-v1/2026-10-knowledge-tool-v1-summary.md)，不能把历史测试数量当作当前验收。

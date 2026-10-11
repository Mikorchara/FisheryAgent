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

共享协调器最多执行 1 个调用、1 个 Tool round、2 次模型请求。多调用返回 `TOOL_CALL_LIMIT`，第二轮继续请求 Tool 返回 `TOOL_ROUND_LIMIT`；没有 Agent loop。首轮后、执行前后及第二次请求前沿用同一 `RequestHandle` 检查取消。取消不写 Capability Evidence，也不把部分回答提交为成功；不保证远端推理/计费停止。

### Development/Test 与 Manual

Development/Test 可使用离线 Mock 或满足能力门禁的真实 Runtime，提供安全完整 Trace；真实请求由用户显式确认。Manual V1/V2 是 Raw 请求与展示路径，Tool Call 可传输/展示但绝不自动执行。

## 当前限制

- 不支持 Streaming Tool Calling、tool delta 拼接或 Streaming Tool Execution。
- Knowledge 已注册，真实受控资格实验与 History v2 迁移已完成；有限样本不代表长期 Tool 选择稳定性。普通 AUTO 下无 Tool 却声称已查询 / 评分 / 检索的正文仍可能提交成功；Prompt 与历史文字不构成执行证明。
- Assistant 按需 Knowledge 与 Analysis 自动 RAG 的双重来源、检索相关性和产品 AUTO 的来源保证仍待评估；History 默认 B 可内部回滚，不会因失败自动改投影或重发。
- 没有第二轮以上循环、多个 Tool 并行、Agent、Detection Tool、设备控制或写入操作。
- Protocol support、Preset 固定合同、Managed Evidence 和用户 Tool Policy 是不同层次，不能互相代替。

## 主要测试

T1/T2/T3：`test_gateway_tool_contract.py`、`test_read_only_tools.py`、`test_tool_conversation.py`。应用与 UI：`test_analysis_tools.py`、`test_analysis_tool_web.py`、`test_web_tool_conversation.py`、`test_assistant.py`、`test_browser_streaming.cjs`。自动测试使用 Mock / 临时数据，不发送真实模型请求。

参数与知识执行覆盖：`test_tool_argument_contract.py`、`test_tool_status_no_match.py`、`test_knowledge_handler.py`、`test_knowledge_registration.py`、`test_knowledge_assembly.py`。历史实施与独立审计见[阶段总结](../../records/archive/knowledge-tool-v1/2026-10-knowledge-tool-v1-summary.md)，不能把历史测试数量当作当前验收。

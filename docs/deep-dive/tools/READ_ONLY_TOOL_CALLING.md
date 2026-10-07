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

- `src/fishery_ai/tools/registry.py` 是静态执行 allowlist，当前仅注册 `get_current_water_quality` 和 `score_current_water_quality`。
- `catalog.py` 仅提供显示文案与通用 metadata，不注册 Handler、不授权执行。
- `policy.py` 只允许从 Registry 中筛选名称。用户设置写入固定的 Git ignored `outputs/tool-policies/tool_policies.json`；新请求捕获冻结 Policy。
- `executor.py` 校验调用名、参数、预算、结果大小与取消；未知或未授权请求安全拒绝。Handler 不读取任意文件、Scenario 或原始模拟包，也不做网络、设备或数据库写操作。
- `handlers/current_water_quality.py` 经共享 `CurrentWaterQualityReader` 获取 query-time view，再调用 `DiagnosisService`。
- `handlers/water_quality_score.py` 经同一个 Reader 调用 `WaterQualityScoringService`。评分是 Experimental，不是专业养殖标准。

## 两种正式应用接入

### Analysis

固定流始终为 Snapshot → Diagnosis → RAG → Context → LLM。Analysis Policy 未启用时保持无 Tool 的原请求；启用后仅在 Normal 请求中提供允许的定义。模型可直答或调用一个 Tool。Tool 观测与分析开始时的 Observed Facts 分开保存，不静默覆盖；Analysis JSON 合同仍是最终输出边界。启用 Tool 的 Streaming 明确返回不支持。

### Assistant

仅三个已发布 Preset 的 OFF + Normal 连接可用。首轮不注入 Snapshot / Diagnosis / RAG；请求中的工具定义由 Assistant Policy 过滤。历史只携带完整成功 user / assistant 文本对，不包含 Tool 协议消息或原始 Result。

### 有界执行与取消

共享协调器最多执行 1 个调用、1 个 Tool round、2 次模型请求。多调用返回 `TOOL_CALL_LIMIT`，第二轮继续请求 Tool 返回 `TOOL_ROUND_LIMIT`；没有 Agent loop。首轮后、执行前后及第二次请求前沿用同一 `RequestHandle` 检查取消。取消不写 Capability Evidence，也不把部分回答提交为成功；不保证远端推理/计费停止。

### Development/Test 与 Manual

Development/Test 可使用离线 Mock 或满足能力门禁的真实 Runtime，提供安全完整 Trace；真实请求由用户显式确认。Manual V1/V2 是 Raw 请求与展示路径，Tool Call 可传输/展示但绝不自动执行。

## 当前限制

- 不支持 Streaming Tool Calling、tool delta 拼接或 Streaming Tool Execution。
- Knowledge Tool 已暂停，未注册。
- 没有第二轮以上循环、多个 Tool 并行、Agent、Detection Tool、设备控制或写入操作。
- Protocol support、Preset 固定合同、Managed Evidence 和用户 Tool Policy 是不同层次，不能互相代替。

## 主要测试

T1/T2/T3：`test_gateway_tool_contract.py`、`test_read_only_tools.py`、`test_tool_conversation.py`。应用与 UI：`test_analysis_tools.py`、`test_analysis_tool_web.py`、`test_web_tool_conversation.py`、`test_assistant.py`、`test_browser_streaming.cjs`。自动测试使用 Mock / 临时数据，不发送真实模型请求。

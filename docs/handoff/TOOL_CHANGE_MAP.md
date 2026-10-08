# Tool 代码修改地图

这是一张定位表，不是改动授权。当前只读工具为 `get_current_water_quality` 和 `score_current_water_quality`；Knowledge Tool 未实现。通用规范见[ADDING_A_TOOL](../deep-dive/tools/ADDING_A_TOOL.md)，未来带 query 参数的例外见[Knowledge Walkthrough](KNOWLEDGE_TOOL_V1_WALKTHROUGH.md)。

## 从业务到模型回答

```text
Domain / Service（业务事实与算法）
        ↑ Handler 调用
Handler（薄输入输出映射）
        ↑ Registry 静态绑定
Registry（ModelToolDefinition + 可执行 allowlist）
        ↔ Catalog（UI metadata，不授权）
        ↓ Policy 筛选 / Runtime Capability gate
ToolCallingService → Model Request #1 → ModelToolCall
        ↓ Executor（参数、权限、预算、取消、结果限制）
        ↓ Handler → Service → ToolExecutionResult
ToolCallingService → assistant/tool messages → Request #2
        ↓ Assistant / Analysis Result → UI Activity / Trace
Tests（沿各边界保护回归）
```

## 修改等级

- **MUST CHANGE**：新增正式可用 Tool 必须补定义、绑定、必要展示和测试。
- **MAY CHANGE**：按依赖、业务规则、参数或展示合同决定；先说明原因。
- **SHOULD NOT CHANGE**：复用公共基础设施，不因为多一个 Tool 复制协议或 loop。

路径以 `src/fishery_ai/` 为源码前缀；测试在 `tests/`。

| 层 / 实际文件 | 等级 | 职责 / 何时改 | 常见错误 |
| --- | --- | --- | --- |
| Service：`domain.py`、`water_quality_scoring.py`、`knowledge.py`；当前状态：`telemetry/current.py` | MAY CHANGE | 先复用已存在服务，缺少业务能力才新增/改服务。 | 在 Handler 复制规则、TF-IDF、stale 阈值；直接读 Scenario 冒充当前事实。 |
| Handler：`tools/handlers/current_water_quality.py`、`water_quality_score.py` | MUST CHANGE | 新增对应领域 Handler；只映射受控输入与安全结果。 | 网络请求、任意文件、Shell、修改 Snapshot、绕过领域服务。 |
| 定义/绑定：`tools/registry.py` | MUST CHANGE | `ModelToolDefinition`、静态 Handler 绑定、`registered_names()`；需要时注入服务。 | 只改名称名单不绑定；第二份 schema；配置函数名驱动动态执行。 |
| Catalog：`tools/catalog.py` | MUST CHANGE（需在正式 Tool Manager 展示时） | UI 名称、介绍、参数摘要、READ ONLY / experimental。 | 把 catalog 的可见/计划状态当授权；description 写错业务范围。 |
| Policy：`tools/policy.py`、`resources/tools/tool_policies.json` | MAY CHANGE；必须审查 | 现有过滤可复用；默认授权、模式限制需要明确决定。 | 注册即默认启用；静默改旧用户 override；只隐藏 UI 不做服务端限制。 |
| 执行合同：`tools/contracts.py` | MAY CHANGE | ToolDefinition / ToolStatus / 安全结果；新状态或参数调用约定才调整。 | Handler 自行返回枚举不支持的状态；把领域错误当 traceback 输出。 |
| 执行器：`tools/executor.py` | SHOULD NOT CHANGE；框架能力变化例外 | `execute()` 统一校验和执行。当前只接受 `{}`、调用无参数 Handler；未来 query Tool 属于需最小演进的例外。 | 各工具复制 Executor；移除 Policy/预算；直接 `handler(**任意JSON)`。 |
| Coordinator：`tool_conversation.py` | SHOULD NOT CHANGE | `run_request()` 一 call / 一 round / 两 request，`tool_choice=none`。 | 把 loop 塞进 Handler/Web；自动第三轮或并行多 Tool。 |
| Assistant：`assistant.py` | MAY CHANGE | ContextBuilder / 选择规则 / 成功提交；通常只补业务选择说明。 | 自动注入 Snapshot/RAG；将 raw Tool Result 保存为历史或 System。 |
| Analysis：`application.py` | SHOULD NOT CHANGE（除非产品明确接入） | 固定 Snapshot → Diagnosis → RAG；可复用 coordinator，事实不被 Tool 覆盖。 | 为新 Tool 取消固定诊断/RAG；把知识检索或评分当新传感器值。 |
| Web 组合：`web.py::create_app()` | MAY CHANGE | 注入共享服务；`assistant_chat()` 捕获 Policy/Runtime；不执行第二套 loop。 | 新建第二套 Current Store；从请求取文件路径；忽略网络确认。 |
| UI：`resources/web/app.js`、`index.html` | MAY CHANGE；必须核对 | Tool Manager、`safeAssistantActivity()` / `renderAssistantMessages()`、Analysis Activity。 | 当前 Assistant 仅识别两个名且统一写“查询当前水质”；新领域工具误标实时数据。 |
| Gateway：`model_gateway.py` / Adapter / `protocol_specs.py` | SHOULD NOT CHANGE | 通用 tools/tool_calls/role=tool 协议；具体工具只通过 Definition 提供 schema。 | 为工具名写 Provider 分支；协议可编码便视为能力 SUPPORTED。 |
| Runtime / Preset / Evidence / Credential | SHOULD NOT CHANGE | 固定合同与精确能力门禁、不可变凭据快照。 | 为新增工具放宽 UNKNOWN；自动发布 Preset；读源码 `.env`。 |
| Trace / 取消：`observability.py`、`execution.py` | SHOULD NOT CHANGE；新安全摘要需审查 | Registry 名称白名单，Usage、阶段、安全错误、RequestHandle。 | 写 query/chunk/完整 prompt/Secret；取消后继续第二轮。 |
| 测试：`test_read_only_tools.py`、`test_tool_policy.py`、`test_tool_policy_manager.py`、`test_tool_conversation.py`、`test_assistant.py`、`test_analysis_tools.py`、`test_browser_streaming.cjs` | MUST CHANGE | 新工具合同/Handler tests，加已有链路回归；必要时独立 targeted 测试文件。 | 只测 happy path；靠联网；Mock 成功被宣称是真模型资格。 |

## 接手检查顺序

1. 业务边界及参数/结果合同。
2. Handler + Registry；检查构造入口与依赖注入。
3. Catalog + Policy + 模式限制；确认 Runtime Capability 未被篡改。
4. Executor 能否支持该合同；需要演进时单独保护旧工具。
5. Assistant/Analysis 是否真正获得允许的 definitions；是否复用第二轮协调器。
6. UI 是否准确展示该领域 Tool；Trace 是否仍只有安全 metadata。
7. 离线测试通过后，由用户另行授权真实模型验收；不自动发布或改 Preset。

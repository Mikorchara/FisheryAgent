# 只读 Tool Calling：T1–T5

**T1 = non-streaming Gateway Contract；T2 = 只读 Registry / Executor / Handler；T3 = 单轮 Model → Tool → Model；T4 = Web 开发测试入口；T5 = Managed 显式精确 Identity Probe。Tool Calling ≠ Agent。** 2026-10-06 已发布 Qwen / DeepSeek / Ollama 固定 Tool 合同，并增加 Analysis v1 的显式 Normal opt-in。最新数据流、安全边界和验收见[Analysis v1](ANALYSIS_MODEL_TOOL_CALLING_V1.md)。

## Preset 独立 Qualification

维护者组件 preset_tool_qualification.py 直接捕获当前 Preset 固定 RuntimeSnapshot，复用 ToolCallingService、Registry / Executor 和 Reader。临时诊断授权不修改原 Runtime、不写 Managed Evidence，也不自动改合同。合法唯一 get_current_water_quality({}) → OK / NO_DATA → role=tool → 非空最终回答（正常 stop、无后续 Tool）后，再发送一次带相同 Tool 定义的概念问题；必须直接回答。最多三次模型请求，retry=0，沿用 RequestHandle / Cancellation。

首次历史资格阶段：Qwen / DeepSeek 因 CREDENTIAL_FILE_ERROR 未发请求；后续用户独立资格完整通过，当前均已发布 1.0.2。历史首次记录中不发布。Ollama 在 OFF + Normal 下完整成功（Tool Result=NO_DATA），概念问题未调用 Tool；固定合同 1.0.2 增加 tool_calling=SUPPORTED。这不支持 Streaming Tool Calling、不自动启用 Analysis Tool Calling、不推广 Thinking ON + Tool 组合。精确 Identity、逐次 Usage、Cloud 阻塞和维护记录见[Preset 发布说明](PRESET_PUBLICATION.md)。以下 T5 的 Evidence 写入仍只属于 Managed，不能代替 Preset 发布。

## 合同

定义位于 [model_gateway.py](../../src/fishery_ai/model_gateway.py)。新增字段在原有字段之后，普通调用仍可使用原构造方式。

| 合同 | 已实现内容 |
| --- | --- |
| ModelToolDefinition | type 固定 function；name、description、parameters（object JSON Schema）。Schema 复制后深度冻结；parameters_dict() 返回可序列化的独立副本。它不是注册表。 |
| ModelToolCall | id、type=function、function_name、arguments_json。参数保留原始 JSON 字符串，要求合法 JSON object；不执行、不做领域参数 schema 验证。它不是执行结果。 |
| ModelMessage | 普通 system/user/assistant + 文本；assistant 可带 tool_calls，此时 content 可为 None；tool 角色要求 tool_call_id 和合法 JSON 文本。tool_calls 保存为 tuple。 |
| ModelRequest | tools tuple；最小 tool_choice：None（不发送）、auto、none、required。命名强制调用等其他 choice 本轮不实现。 |
| ModelResponse | text 可为 None，但必须有有效 tool_calls；tool_calls tuple，保留调用 ID 和参数；增加可选 finish_reason，由正式 Adapter 保留 non-streaming choice 字段；原 Usage / returned_model / reasoning 字段继续工作。 |

T1 拒绝非法名称、非 function 类型、重复定义名称、重复调用 ID、错误角色字段组合、缺少关联 ID、无调用的 null 响应、畸形或非有限 JSON。T2 补齐调用名 allowlist、首个 Tool 的空参数校验及执行预算；不引入通用 JSON Schema 框架。T3 负责本次对话的 assistant/tool ID 关联与一次后续模型请求。

## T2 执行层

源码位于 [tools/](../../src/fishery_ai/tools/)。

| 文件 | 职责 |
| --- | --- |
| contracts.py | ToolDefinition 持有 T1 ModelToolDefinition 与固定 Handler；ToolExecutionResult 保存调用 ID、名称、OK/NO_DATA/ERROR、独立 JSON 内容和安全错误码。 |
| registry.py | ToolRegistry(reader, diagnosis) 静态注册 get_current_water_quality 与 score_current_water_quality；model_definitions() 可取得 T1 定义；无注册接口、扫描或动态加载。 |
| executor.py | ToolExecutor.execute(ModelToolCall)；查 allowlist → JSON object → 必须为 {} → Handler 执行一次 → JSON 结果。 |
| handlers/current_water_quality.py | Reader.query() 捕获一次视图，再由 DiagnosisService.diagnose(view.reading) 生成 findings；不自行诊断、读取场景或改变 Store。 |

Executor 应为每个请求新建。默认 max_calls=1，可信调用者可明确设为 1–8；失败尝试也消耗预算。同一 Executor 内调用 ID 不可重放，没有自主循环或透明重试。参数上限 4 KiB；正文结果默认 32 KiB UTF-8，可配置为 256 B–256 KiB。超限返回 TOOL_RESULT_TOO_LARGE，不截断 JSON。

常用错误：UNKNOWN_TOOL、INVALID_TOOL_ARGUMENTS、TOOL_EXECUTION_ERROR。预算错误：TOOL_CALL_LIMIT、TOOL_CALL_ALREADY_EXECUTED。错误正文仅包含 status / error_code；不返回原异常、traceback、参数或私有路径，不写日志。

执行前、调用 Handler 前、Handler 后与错误出口检查现有 RequestHandle。USER_CANCELLED 继续抛给请求所有者，不包装成模型可消费的部分 Tool Result，不触发重试。当前 Handler 没有网络/阻塞 I/O；这不是强制中断任意第三方函数的机制。

ToolExecutionResult.to_json() 是未来 role=tool 的正文；to_dict() 是包含 tool_call_id / tool_name / status / result 的本地封装。payload 每次返回独立副本，修改副本不会改变已保存结果。T2 不创建 follow-up 请求。

### 水质结果

```json
{
  "status": "OK",
  "water_quality": {
    "temperature_c": 28.0,
    "ph": 7.5,
    "dissolved_oxygen_mg_l": 2.2,
    "quality": "valid",
    "freshness": "fresh",
    "observed_at": "2026-10-05T02:00:00+00:00",
    "retrieved_at": "2026-10-05T02:00:00+00:00",
    "source": "fake:sensor"
  },
  "evaluated_at": "2026-10-05T02:00:00+00:00",
  "findings": [{
    "code": "OXYGEN_CRITICAL_LOW",
    "severity": "critical",
    "message": "溶氧低 (2.2 mg/L)",
    "facts_used": ["dissolved_oxygen_mg_l"],
    "rule_version": "fishery-production-c400b7a-v1"
  }],
  "rule_version": "fishery-production-c400b7a-v1"
}
```

以上为虚构示例。没有 Snapshot 才返回 `{"status":"NO_DATA","water_quality":null,"findings":[]}`；只要有 Snapshot，缺失/partial/invalid/stale 均为成功读取 OK，各状态和诊断如实保留。缺失数值用 null；Quality 与 Freshness 分离。

Reader 在查询时复用 Domain Freshness 策略；evaluated_at 是查询时间，retrieved_at 保持原取得时间。Tool 不修改原 Snapshot，不复制 stale 阈值。Findings 与 rule_version 来自 DiagnosisService，Tool 不复制规则。

安全边界：Handler 只有 Reader / Diagnosis 依赖；不持有 Credential、文件、Shell、网络、设备、DB 或 Apply 接口。注册表没有任意函数发现机制。调用方注入正确的 Reader，而不是另建数据源。

## 正式 Adapter

[OpenAICompatibleAdapter](../../src/fishery_ai/openai_compatible_adapter.py) 的普通 complete() 路径编码 tools、assistant.tool_calls 和 role=tool/tool_call_id。Provider SDK 响应统一解析为 ModelToolCall；同步调用与可取消 AsyncOpenAI bridge 共用 _response()。没有借 Manual Raw 路径实现。

响应中的 tools 结构错误返回 INVALID_TOOL_CALL；无有效正文/调用返回 INVALID_RESPONSE。不输出原始参数、异常或 Header。

## T3 应用层 Coordinator

实现位于 [tool_conversation.py](../../src/fishery_ai/tool_conversation.py)，不在 Executor 中建立模型循环。

```python
registry = ToolRegistry(current_reader, DiagnosisService())
service = ToolCallingService(gateway, registry, JsonlTraceSink(trace_path))
with request_scope(handle):
    result = service.converse("现在水质怎么样？", runtime)
```

runtime 是调用者在请求开始时通过现有机制捕获的 RuntimeSnapshot。T3 不解析 Profile 或读取凭据文件，两轮使用同一 snapshot；request_scope / RequestHandle 生命周期仍归请求所有者。上例为应用调用方式，尚未接入 Web。

1. Request #1：仅 system instruction、原用户问题、Registry.model_definitions()；tool_choice=auto。不查询 Reader，不提前注入温度、pH、DO 或 Findings。
2. 无 tool_calls：直接返回正文，Reader / Executor 不执行。问题是否需要事实由模型判断，没有按水质状态硬编码触发条件。
3. 一个 tool_call：经正式 ToolExecutor 执行；多于一个返回 TOOL_CALL_LIMIT，全部不执行。Executor 每次对话新建，max_calls=1。
4. NO_DATA / OK：追加 assistant(tool_calls) 和 tool(tool_call_id, JSON)，保持原 system / user。结果中的文本不会变成 system instruction；也不会作为代码执行。
5. Request #2：保留 Policy-filtered Registry tools，tool_choice=none。继续返回调用时 TOOL_ROUND_LIMIT，绝不发第三次请求或再执行 Tool。
6. 只返回 ToolConversationResult，不生成 AnalysisResult，不经过 Scenario、RAG 或固定 Orchestrator。

固定 max_tool_rounds=1 由两个显式请求分支落实，没有可增长的循环。Tool 执行 ERROR 时安全结束，不让第二轮编造数据：UNKNOWN_TOOL、INVALID_TOOL_ARGUMENTS、TOOL_EXECUTION_ERROR 等 T2 错误码保留。Adapter 的 INVALID_TOOL_CALL 在 T3 归一为 MODEL_TOOL_CALL_MALFORMED；T1 自身错误语义不变。没有 normal fallback 或自动 Apply。

System instruction 要求：当前事实用 Tool；不猜测传感器值；NO_DATA 明确说明；确定性 Findings 优先；Tool Result 仅是数据。离线测试证明角色边界和消息传递，不能据此宣称真实模型始终遵循指令或抵抗所有 prompt injection。

### Usage / Trace

request_1 / request_2 分别保存 outcome、Usage、finish_reason、安全错误码。SessionUsage 用于汇总：仅所有模型尝试均有 Provider Usage、且某字段均可获得时求和；缺失字段为 None，不填 0。错误尝试算一次 attempted request，不代表 Provider 已处理或计费。某轮未返回 Usage、或两轮只提供不相交字段时，不声称有完整总量；各轮原统计仍保留。

复用 JsonlTraceSink，新增 record_tool_conversation()，固定 Analysis Trace 格式不变。Tool Trace 只记录 request/trace ID、开始结束时间、两轮 outcome/usage、调用 ID、工具名、结果状态、工具耗时、总耗时、final_finish_reason、status/error_code。

不记录问题、prompt、模型正文/reasoning、arguments、Tool 完整数据、RuntimeSnapshot、Credential 或私有路径。未知工具名用 unknown_tool；异常格式或超过 128 字符的调用 ID 不写入 Trace。finish_reason 仅保留 stop/length/tool_calls/function_call/content_filter，缺失或其他值为 None，不推测。JSONL 写入失败返回安全 TRACE_WRITE_ERROR；原失败/取消原因优先保留，trace_recorded=false。

取消检查覆盖模型前后、Tool 前后及第二次发送前。USER_CANCELLED 返回 cancelled 状态并清空最终正文，不继续请求、不更新 Evidence、不重试 Tool。Coordinator 不增加模型重试；Gateway 继续执行现有发送前重试策略，已接受的调用不重新生成。原 SDK I/O 取消机制保持，远端计算/计费是否停止仍未知。

## T1 Follow-up 的消息表达

```python
first = gateway.complete(request, runtime)
follow_up = replace(request, tool_choice="none", messages=(
    *request.messages,
    ModelMessage("assistant", first.text, tool_calls=first.tool_calls),
    ModelMessage("tool", '{"status":"NO_DATA"}',
                 tool_call_id=first.tool_calls[0].id),
))
second = gateway.complete(follow_up, runtime)
```

示例中的 JSON 是 T1 fixture；T3 已通过实际只读 Handler 取得 JSON，并明确设置第二轮 tool_choice=none。多调用本阶段整体拒绝。

离线测试同时覆盖脚本化 MockGateway、假 SDK client、官方 OpenAI SDK + HTTPX MockTransport 两次请求，以及同一 RequestHandle 内的两次 complete()。测试不访问模型、Snapshot 或真实凭据。

## 能力与模式边界

- Protocol support != Model capability evidence。显式 request tools 或工具历史消息仍要求当前 runtime 的 tool_calling=SUPPORTED；UNKNOWN / UNSUPPORTED 返回 OPTION_UNKNOWN / OPTION_UNSUPPORTED。只解析响应不写 Evidence。
- Qwen / DeepSeek / Ollama 现有能力和 Preset 合同未修改；现有 Preset 不因 T1/T2/T3 自动获得工具权限。测试中的 SUPPORTED 仅针对虚构 fixture identity。Coordinator 和正式 Gateway 均保留能力门禁。
- 固定 Fishery Analysis 没有工具请求与执行路径；若收到意外工具响应，返回 UNEXPECTED_TOOL_CALL，不把 null 当最终回答、不执行调用。
- Manual V1/V2 保持原 Raw 传输、展示及安全边界，不自动执行 tools/tool_calls，也不套用 T1 能力门禁。

## Retry 与 Cancellation

SDK 自动 retry 仍为 0；Gateway 继续管理发送前允许的重试。合法 non-streaming 响应被解析接受后（包括只有工具调用、正文为 null）即标记可观察输出；排队或清理错误不会透明重试生成另一组 ID / arguments。

RequestHandle / AsyncOpenAI Task 取消机制继续复用，取消返回 USER_CANCELLED；后端关闭本地 I/O，不宣称远端推理或计费已停止。一次工具对话可以在同一 RequestHandle 中显式调用两次模型；应用仍负责整个请求的最终状态。

## Streaming 与后续阶段

普通正文 / reasoning / Usage Streaming 保持现有行为。正式 stream() 收到 tools 或工具历史消息时，在发送前返回 TOOL_STREAMING_NOT_IMPLEMENTED；Provider 意外返回工具 delta 时也明确失败，不忽略、不聚合、不执行。Manual Raw Streaming 不受该归一限制。

尚未实现：tool_calls delta、arguments delta 汇聚、Streaming Tool Execution、Agent、多轮自主循环。T5 显式真实验证已经有入口，成功结果仍只授权对应 Managed Identity。

**历史 T4 结论（T5 现已完成实现）：** T4 已注入共享 Reader，并沿用现有 Credential / Runtime / RequestHandle 边界。真实模型工具能力与联网人工验证仍需要单独依据和当轮授权，不能从 Thinking / Streaming 组合推导。T1–T4 未真实联网或发布模型工具能力。

## T4 Web 开发测试入口

使用 `python -m fishery_ai web` 启动，访问 `http://127.0.0.1:8765`。普通模式展开左侧 **Development / Test** 后只有说明和 **进入开发验证**。点击进入，顶部切到专用开发 Mock，并显示完整 **Read-only Tool Calling** 实验区域。选择默认的 **Mock Tool Calling · 完全离线**，填写问题，点击“运行 Tool Calling”。无需配置真实凭据。

页面显示当前 Snapshot 的 AVAILABLE / NO_DATA、最终回答、请求状态与 Tool Trace；Trace 包括 Request #1 outcome、调用名、通过校验的空参数、Tool Result、Tool 耗时、Request #2 outcome、finish_reason、Usage 和总耗时。完整 Trace 在 non-streaming 请求结束后显示，不是实时流式事件。失败显示安全错误码；取消后不保留等待状态或部分最终回答。

`web.py` 的 `/api/tool-conversation` 只负责请求校验、不可变 Runtime 捕获、RequestHandle 和结果白名单；调用 `ToolCallingService.converse()`，不实现模型循环。Registry 在应用创建时注入现有共享 Reader / Diagnosis；每个对话仍创建自己的 Executor。首轮仅含 system / user / Policy-filtered Registry tools，浏览器不传 Scenario、模板、传感器值或 Findings。

专用 `MockToolGateway` 只用确定性示例模拟模型选择：含“现在/当前/目前/现场”的问题请求 Registry 中的当前水质 Tool；“什么是溶氧？”直接概念回答。第二轮解释只使用 role=tool JSON，不自行读取 Store、诊断或生成场景。它不是实际模型的意图策略，也不代表真实模型 Tool 能力。UI 中每次模拟模型调用有约 0.5 秒的可取消等待，便于人工检查 Stop；自动测试关闭该等待。

### Snapshot 人工验收

所有当前事实用例均问“现在水质怎么样？”。仅选择 Scenario 不会改变 Tool 读取的数据，必须先点击原页面的 Apply。Tool Result 的 Quality / Freshness 为合同中的小写枚举值。

| 操作 | 预期 |
| --- | --- |
| 新启动 Web，不 Apply | Snapshot NO_DATA；Tool NO_DATA；Request #2 明确无当前数据 |
| Apply normal | AVAILABLE；正常数值、valid / fresh；无阈值告警 |
| Apply low_oxygen | DO 2.2；OXYGEN_CRITICAL_LOW；最终回答引用实际 Tool Result |
| Apply stale，或等快照超时再查询 | OK + stale；SENSOR_STALE；Store 原对象不修改 |
| 自定义情景将任一字段设 INVALID，再“仅应用” | OK + invalid；SENSOR_INVALID；不是 NO_DATA |
| 自定义 34℃ / pH 7.5 / DO 2.2，再“仅应用” | TEMP_CRITICAL_HIGH 与 OXYGEN_CRITICAL_LOW |
| 问“什么是溶氧？” | Request #1 直接回答；未执行 Tool；Request #2 not_started |
| 运行后立刻 Stop | USER_CANCELLED；不再发送 Request #2；按钮恢复可用 |

原 Normal / Streaming Analysis、情景模板 CRUD、Preset / Managed 和 Manual V1/V2 保持原路径。当前 Tool API 明确拒绝 Streaming，返回 TOOL_STREAMING_NOT_IMPLEMENTED；不会从主 Analysis 的 Streaming 选择静默降级。

### 能力、安全与取消

测试目标也可选择“真实 Runtime · <进入前的模型连接名称>”；例如进入前是 Managed Custom / DS_1，开发顶部是 Mock，但真实 Tool 请求仍引用 DS_1 的原 profile_id。Qwen / DeepSeek / Ollama 原 Tool 能力未修改；当前未验证 Runtime 被 OPTION_UNKNOWN / OPTION_UNSUPPORTED 拒绝，且发生在凭据解析、Gateway 创建之前。未来只有精确 tool_calling=SUPPORTED 且单独确认 REAL NETWORK REQUEST 的 Runtime 才可发送；ToolCallingService 和正式 Gateway 的 CapabilityValidator 仍为最终门禁。普通 Mock Profile 未被提升工具能力，专用离线 fixture 不写 Evidence。

Web API 复用 Host / Origin / CSRF 与现有请求控制令牌。输出只包含开发所需字段，不序列化 RuntimeSnapshot、凭据路径、Authorization、内部 Prompt 或异常；错误参数不回显，未知 Tool 名被安全归类。浏览器使用 textContent，不渲染模型 HTML；请求凭据被回显时会脱敏。Tool Result 的 source 仍供模型读取，浏览器白名单不展示该 provenance 字段。

Stop 复用同一 `/api/requests/.../cancel` 和 RequestHandle：先要求后端取消，再中止浏览器 fetch，并等待现有状态确认。T3 在第一轮后、Tool 前后、第二轮前后检查取消；没有第二套取消机制。开发界面只陈述本地 I/O 状态，不宣称远端计算或计费停止。失败的 preflight 会关闭未开始的请求句柄，避免占用活动名额。

T4 未新增 Web 自动 Probe、第二个 Tool、Agent 或真实联网测试。以上保留 T4 离线人工验收方式；当前 T5 入口已移到 Managed Custom 能力区，普通 UNKNOWN gate 保持，必须显式 Probe。

### T4 UI 模式隔离整理

本次只修改 Web HTML / JavaScript、测试和中文说明；不修改后端、Tool 服务、能力判断、Freshness、协议、Scenario / Telemetry、Credential、RAG。用户已报告 query-time Fresh → Stale 人工测试通过，本轮不重新实现该逻辑。

- Preset / Managed Custom / Manual：Development / Test 只提供简短说明和进入按钮；实验目标、问题、Run / Stop、Trace、快照调试按钮全部隐藏。
- Development / Test：默认开发 Mock；保留 Scenario 测试、完整 Tool 实验、Snapshot、最终回答、Trace 和停止功能，新增明显的“返回正常模式”。运行期间禁止返回，沿用原请求锁。
- 进入前的 UI 书签保存模式、精确 Profile ID、Thinking / Response / Effort、非 Secret 编辑草稿和 Manual 版本。返回恢复这些选择及未保存草稿；已有 Manual 原始编辑器内容留在原页面中。书签不保存 Secret、CredentialSnapshot、Capability 副本或第二份连接配置，也不写 LocalStorage。
- 真实目标通过原 profile_id 查询现有 profiles 列表，开发目标切换不覆盖它。没有原真实连接时禁用该选项；Manual V2 的独立 Experiment 不被冒充成 Saved Connection。
- 两项文案为“Mock Tool Calling · 完全离线”和“真实 Runtime · <原连接名>”；真实目标状态单独提示“受 Tool Calling 能力门禁保护”，仍需 SUPPORTED 和显式联网确认。
- “更新快照状态显示”保持原 GET `/api/water-quality/current`，只重新读取 Reader 状态；不 Apply、不模拟、不回退 normal、不改变 Snapshot。

额外人工验收：在 DS_1 选择运行选项 → 进入开发验证 → 确认顶部 Mock、真实目标 DS_1 → 切换开发目标 → 返回 → 确认 DS_1 与原运行选项恢复。再分别检查 Preset Variant 和 Manual 草稿。Freshness 的既有人工验收保留；本轮没有真实联网。

## T5：显式真实 Tool Calling 能力验证

当前入口：Managed Custom 选择已保存连接 → 02 · 模型能力 → 高级验证操作 → “验证 Tool Calling” / “重新验证 Tool Calling” → 确认 REAL NETWORK REQUEST。Development / Test 只进行已有能力的对话测试；未验证真实目标提示先到 Managed Custom 验证。普通 UNKNOWN 请求仍在联网前禁止；Probe 只临时构造不可变诊断 Runtime，复用 T3、Registry / Executor、CurrentWaterQualityReader 和 RequestHandle。凭据仍由现有私有 CredentialStore 解析；没有源码根 .env 回退。

`tool_capability_probe.py` 仅进行一次单轮验证，最多两次模型请求，SDK / Gateway retry=0，每次最多 256 输出 token；不继承保存的 Thinking / Streaming 运行偏好。首轮不得预注入水质值，NO_DATA 也作为正常 Tool Result 交给第二轮解释。

只有合法唯一 Tool Call、执行 OK / NO_DATA、第二轮非空正文且没有新 Tool Call，才写精确 Identity 的 `SUPPORTED · explicit_probe`。由 CapabilityStore 写入，再由 R4 Resolver 解析；Preset 合同不变。明确的 Provider Tool Calling 不支持响应可写 UNSUPPORTED；无 Tool、网络、鉴权、限流、取消、解析或本地执行失败不写负面证据。已有证据不会因网络失败被删除。

页面显示当前精确连接、两次请求结果、Tool 状态、Usage、耗时、verdict 与 Evidence 是否写入；不显示完整 Prompt、Secret、私有凭据路径或 traceback。成功后无需刷新页面即可解锁该 Profile 的普通 Tool Conversation。Probe 支持既有 Stop；不增加 Agent / Streaming Tool Calling / 第二个 Tool。

DS_1 实际验证与本轮测试结果见 [T5 验证记录](T5_DS_1_TOOL_CALLING_VALIDATION.md)。

## 当前 Tool Policy / 应用模式

Tool 管理入口位于左侧 **01 · Analysis Model** 标题右侧，不绑定具体模型。Catalog 只负责展示；Registry 决定固定 Handler；Policy 限制授权子集。Modal 提供 Analysis / Assistant 标签、默认折叠详情、计数、保存、恢复默认与关闭。正式 Catalog 仅含两个真实 Tool；旧 DEV 占位已在 Assistant S0 删除，通用 metadata 保留。

用户选择保存到 Git ignored 的 outputs/tool-policies/tool_policies.json。启动与请求校验，原子写入；Assistant 新请求捕获冻结策略，进行中的请求不因新保存而改变。Analysis 的 selected_tools 在保存后影响新的 Normal 请求；默认仍为空，启用时须通过精确 Runtime 的工具能力门禁。恢复默认只删除 Override，不修改源码、Profile、Credential、Evidence 或 Snapshot。

请求定义须同时满足 Registry 注册、当前 Policy 允许、固定 Handler 可执行及精确 Runtime 能力 SUPPORTED。普通请求仍不可绕过能力门禁；显式 T5 Probe 只临时绕过 UNKNOWN 能力，不能越过用户 Policy。若已关闭水质 Tool，先在 Tool 管理的 Assistant 标签重新允许；Probe 返回 TOOL_NOT_ALLOWED，不联网。

Analysis Model 仍是程序控制的 Snapshot → Diagnosis → RAG → LLM；未启用 Tool 时 tools 为空，意外调用仍拒绝。启用后复用共享协调器单轮执行，Tool Result 不覆盖固定 Facts。Assistant 当前是 T3 单轮实验路径，不预注入事实；tools/policy.py 从 resources/tools/tool_policies.json 加载冻结策略，过滤 Registry 定义，Executor 再检查注册与授权，未知 Policy 名称启动失败。评分工具已按静态注册加入；没有 Agent。

Managed 的验证结果在能力面板显示，成功后即时刷新；Development 只显示对话 Trace。Preset 固定合同不被 Evidence 覆盖。完整边界、QW_2 用户验收与未来实验评分规划见[Analysis / Assistant 架构](ASSISTANT_MODEL_ARCHITECTURE.md)。

## 历史 T1–T4 验证记录

以下数量和工作树描述属于对应历史实施阶段；当前回归结果见上述架构文档，不代表当前未提交状态。

自动测试完全离线。T1 使用假 SDK / MockTransport；T2/T3 使用虚构 canonical Snapshot，通过实际只读 Handler 执行。T3 同时通过官方 SDK + HTTPX MockTransport 验证完整两次请求、tool_choice、ID、finish_reason 和 Usage；不访问真实凭据或模型。

| 检查 | 命令 / 范围 | 结果 |
| --- | --- | --- |
| T1 targeted | `python -m unittest discover -s tests -p test_gateway_tool_contract.py` | 29 项通过 |
| T2 targeted | `python -m unittest discover -s tests -p test_read_only_tools.py` | 35 项通过 |
| T3 targeted | `python -m unittest discover -s tests -p test_tool_conversation.py` | 36 项通过 |
| T4 Web targeted | `python -m unittest discover -s tests -p test_web_tool_conversation.py` | 22 项通过，0.998 秒 |
| Relevant Web targeted | test_v011_a3_web.py / test_access_web.py | 6 / 7 项通过 |
| T4 / UI Browser targeted | `node --test --test-name-pattern="Development UX\|T4 Tool Conversation" tests/test_browser_streaming.cjs` | 22 项通过；原 T4 10 项 + 新 UI 12 项 |
| Current / Telemetry / Scenario | 对应三个 test 文件 | 22 / 18 / 19 项通过；水质矩阵另由 Full Python 覆盖 |
| Full Python | `python -m unittest discover -s tests` | 552 项通过，20.257 秒 |
| Full Browser | `node --test tests/test_browser_streaming.cjs` | 136 项通过；Node DOM / fetch 模拟，不启动真实浏览器或网络 |
| JS syntax | `node --check` 检查 app.js 与 Browser 测试文件 | 通过 |
| Markdown links | Git 可见 Markdown 本地文件链接 | 31 项有效，无失效链接 |
| Diff | `git diff --check` | 通过 |
| Sensitive scan | 124 个 Git 可见源码/文档；不读取 .env / outputs / 私有凭据 | 无未解决风险；1 个既有 URL 凭据拒绝测试负例已核对；受管运行数据与凭据被跟踪数量为 0 |

T3 新增 tool_conversation.py / test_tool_conversation.py；小幅修改 Gateway / Adapter 以保留 non-streaming finish_reason，复用 observability.py 增加独立 Trace。T4 修改 web.py、Web HTML/CSS/JS、tool_conversation.py 的离线 fixture，新增 test_web_tool_conversation.py，并扩展既有 Browser 测试；更新 BUILD_RUN / STRUCTURE / 本说明与架构审计状态，同步 README / ROADMAP 过时的“尚未实现”描述。保留 T1/T2/T3 工作树；本轮不修改正式项目、凭据存储、RAG、Diagnosis、Orchestrator、Preset 或能力证据，不 commit / push。

最终工作树（包含 T1/T2/T3）：14 个已跟踪文件修改、11 个新文件；T4 本轮新增 1 个测试文件。所有回归离线，仅测试内临时存储和虚构凭据，未读取真实凭据、未发真实 Provider 请求。当前可以开始 T4 人工验收；T5 的真实模型工具能力仍未验证。

## 第二个只读 Tool（2026-10-06）

score_current_water_quality 无参数，Reader → 独立评分服务 → JSON。OK / PARTIAL / NOT_SCORABLE / NO_DATA 是业务结果状态，不代表执行异常。默认 Analysis 关闭、Assistant 仅查询工具；评分均须显式授权。最多执行一个调用的规则不变，未授权为 TOOL_NOT_ALLOWED。Catalog / Policy 集中在 tools/；新增流程见[新增 Tool 指南](ADDING_A_TOOL.md)。

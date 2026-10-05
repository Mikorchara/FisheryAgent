# Tool Calling 前置架构审计

初次审计：2026-10-04；数据读取修正与 T1：2026-10-05。以下主体保留该时点审计记录；当时结论为 **READY WITH FIXES**。

**T4 当前状态（2026-10-05）：** T2 tools/ 与独立 ToolCallingService 单轮 Model → Tool → Model 已接入 Web Development / Test。默认使用离线 Tool Mock，并共享 Web CurrentWaterQualityReader；真实工具能力门禁保留。可以开始浏览器人工验收；T5 仍需独立真实模型能力验证。最新实现边界见[T1–T4 说明](READ_ONLY_TOOL_CALLING.md)。当前无 Agent、Streaming Tool Calling 或真实模型工具验证。下文“待 T2 / 未创建 tools”等文字均为此前审计时点，不是当前状态。

## 1. 当前真实数据链

以下是源码确认的主链。文件路径均相对项目根目录。

| 步骤与实际位置 | 输入 → 输出 | 调用关系与生命周期 |
| --- | --- | --- |
| `resources/web/app.js`：`applySelectedScenario()`、`submitScenario()` | 已保存 template ID / 表单 JSON → Apply API 请求 | 浏览器持有选择和草稿；保存模板与应用快照是不同操作。临时模板可以只应用、不保存。 |
| `web.py`：`apply_water_quality()`；`telemetry/scenario_templates.py`：`ScenarioTemplateStore.get_template()` / `ScenarioTemplate.from_dict()` | ID / JSON → `ScenarioTemplate` | 内置模板在 Store 创建时加载；用户模板从本地文件加载。模板是冻结合同，保存的是模拟输入意图，不是当前观测。 |
| `telemetry/scenario_templates.py:254`：`apply_scenario_template()` | template、Store、Adapter、`now` → reading | 每次 Apply 新建 Simulator；设置数值或 MISSING / INVALID；计算观测时间并调用下述转换，最后写 Store。 |
| `telemetry/simulator.py`：`TelemetrySimulator.generate()` | baseline + overrides、`observed_at` → `SimulationPacket` | Simulator 只在这次 Apply 内使用；Packet 冻结且 readings 为只读映射。每次新建 Simulator，sequence 不构成跨 Apply 的版本号。 |
| `telemetry/adapter.py`：`SimulationAdapter.to_reading()` | `SimulationPacket`、`retrieved_at` → `WaterQualityReading` | 检查 sim-v1、字段、类型和时间，调用 `WaterQualityReading.from_raw()`；不做养殖诊断。Web 共享同一个 Adapter。 |
| `contracts.py`：`WaterQualityReading` | 标准数值、时间、source → 冻结领域合同 | Quality / 初始 Freshness 在 from_raw() 计算。模拟来源归一为 simulation:<device_id>；没有 Packet / Template 字段。 |
| `telemetry/snapshot.py`：`CurrentSnapshotStore.set_current()` / `get_current()` | reading → 同一原始 reading 引用或 `None` | 进程内最后一次写入；不复制、不持久化、不重新计算 Freshness。 |
| `telemetry/current.py`：`CurrentWaterQualityReader.query()` | 当前 Store、clock、stale_after_s → `CurrentWaterQualityView` / None | 捕获原 reading 一次，调用共享领域 Freshness 判断；replace 生成新 reading，只更新 freshness。返回单独 evaluated_at。 |
| `web.py`：`analysis_snapshot()` | 请求 payload → 捕获的查询视图 / NO_DATA | Normal 与 Streaming 在进入 Orchestrator 前共同调用；见第 2 节兼容路径。 |
| `domain.py:11`：`DiagnosisService.diagnose()` | reading → `tuple[RuleFinding, ...]` | Apply 返回的预览和正式分析都调用相同服务，但各自重新计算 Findings；不存在两套规则。 |
| `application.py`：`Orchestrator.analyze()` / `analyze_stream()` | `AnalysisRequest` + 注入 reading → `AnalysisResult` / 事件迭代器 | Orchestrator 每个 Web 分析请求新建；复用应用级 Diagnosis、Knowledge、Trace。保留请求内 reading 引用。 |
| `application.py:114,46`：`_retrieve_evidence()`、`_build_model_request()` | reading + Findings + question → Evidence → `ModelRequest` | 固定调用 RAG，构造 system / user 消息。不是模型自行取事实。 |
| `model_gateway.py`、`openai_compatible_adapter.py` | `ModelRequest` + `RuntimeSnapshot` → `ModelResponse` / `ModelEvent` | 使用 Mock 或 SDK Adapter；最终程序装配事实、规则、证据和模型推断。 |

**对象关系：** `apply_scenario_template()` 写入 Store 后返回同一原 reading；`get_current()` 返回该对象。Reader 创建另一份冻结 reading view，Web 将 view.reading 注入 Orchestrator；`AnalysisContext` 和最终 `ObservedFacts.water_quality` 持有该视图，`ObservedFacts.evaluated_at` 保留查询时间。浏览器只获得序列化副本。Findings 按查询视图重新生成，不存入 SnapshotStore。

## 2. Snapshot 与双路径

源码依据：[Web composition / Apply / capture](../../src/fishery_ai/web.py)、[Store](../../src/fishery_ai/telemetry/snapshot.py)、[MockRepository](../../src/fishery_ai/repositories.py)、[Orchestrator](../../src/fishery_ai/application.py)。

| 检查项 | 当前实际行为 |
| --- | --- |
| Web 当前快照是否共享 | 是。`create_app()` 创建 `snapshots`，Apply、current API、Normal、Streaming 的闭包共享它，并通过 `app.extensions['fishery_snapshot_store']` 暴露。 |
| 是否只有一个 Store 实例 | Web current 使用一个共享 Store。MockRepository 的 demo_snapshots 现在惰性创建；正常 Web 不调用场景后备，就不创建第二份 Store。旧 snapshots 属性仅保留 Demo 兼容别名。 |
| Apply 是否真正写入 | 是。统一 Apply 函数调用 `snapshot_store.set_current(reading)`。保存模板本身不等于写快照。 |
| Analyze 是否读取同一 Store | 是，统一经 CurrentWaterQualityReader。存在 scenario 时先明确生成 / Apply，然后也调用 Reader。 |
| Streaming 是否捕获 reading | 是，Web 在创建 SSE generator 之前捕获 query view；generator 将其 reading 和 evaluated_at 传给 analyze_stream()。Normal 做相同捕获。 |
| 后续 Apply 是否污染旧请求 | 不会改变旧 reading。Store 只换引用，冻结的旧 reading 已被请求持有；其诊断、检索、prompt、result 使用旧值。 |
| 重启是否为空 | 是。每次 `create_app()` 新建空 Store。用户模板可持久加载，但不自动应用。 |
| 无快照如何返回 | current API 返回 `status=NO_DATA, snapshot=null, rule_results=[]`；分析在参数/运行时前置检查通过、且未显式传 scenario 时返回 `NO_DATA` / HTTP 409。 |
| 是否有默认 normal 后备 | **Web current 读取没有**静默 normal 后备。但 `Orchestrator.analyze/analyze_stream` 的默认 `scenario='normal'`，在未注入 reading 时调用 `repository.water_quality(scenario)`。CLI demo 和 `real_validation.py` Advice 验证采用这一场景生成路径。 |
| 是否直接读 scenarios 作为 current | Web current API 不读文件。Repository 后备会读取 ScenarioTemplate，再经 Simulator / Adapter 生成 reading；并非旧式 JSON 直接当 reading。 |

因此：**Web 的 current 读取语义已统一，场景生成仍作为显式兼容入口保留。** Web 有“直接查询当前快照”与“按 scenario Apply 后再查询”两种入口，但查询都走同一 Reader。Orchestrator / CLI Demo 保留场景生成后备。前端在已应用模板时不传 scenario；选择另一已保存模板后 Analyze 显式传 scenario，生成新快照。

Tool 必须依赖 app.extensions['fishery_current_water_quality_reader'] 对应的只读 Reader，不能调用 repository.water_quality() 或“Analyze 时 Apply”来取当前事实。Reader 不依赖模板、模拟 Packet 或 Repository。Demo Store 的隔离通过惰性创建和明确命名实现，未删除 CLI 兼容逻辑。

生命周期限制：这是**单应用进程共享**状态，多个标签页共享最后一次 Apply；多个进程或多个 `create_app()` 互不共享。Store 没有锁、时间排序、版本或持久化协议，不能承诺分布式一致性；未来并发硬件采集再评估写入顺序策略。

## 3. WaterQualityReading 的 canonical 边界

**CODE-CONFIRMED：** Domain 不导入 Telemetry；Diagnosis 只读 reading。RAG 接收检索字符串，不接收 Template / Packet。Prompt 和 `AnalysisResult` 不包含 `schema_version`、sequence、模板 state、模板 ID 或 `observed_age_s`。source 保留模拟来源标签是合法 provenance，不要求上层识别 `simulation:` 才能工作。

但 Orchestrator 的方法签名和 repository Protocol 仍包含 `scenario`，其外层取数方式仍有模拟耦合；这不等于 Packet 泄漏到诊断/模型。未来硬件 Adapter 可以产出同一 reading，注入现有固定流程，无须重写 Diagnosis 或 RAG。

现有 `ObservedFacts` 提供 water_quality 和可选 detection_summary；当前这条水质流程只装配 water_quality，并未自动读取 Detection。不要因已有合同就宣称检测事实已接入模型。

## 4. Diagnosis 的边界及状态传播

养殖温度 / pH / DO 告警阈值只在 [DiagnosisService](../../src/fishery_ai/domain.py) 实现；版本为 `fishery-production-c400b7a-v1`。

- 温度：低于 15 / 20，或高于 33 / 30 °C，按分支产生 critical / warning。
- pH：低于 6.5 / 7，或高于 9 / 8.5。
- DO：低于 1 / 3 / 5 mg/L。

`contracts.py` 的物理合法范围（温度 -50–100、pH 0–14、DO 0–100）是**输入有效性校验**，不是重复养殖阈值。Simulator baseline 是测试数值；Adapter 不诊断，前端仅显示服务端 Findings，Orchestrator 固定调用 Diagnosis、不复制规则。

| 输入情况 | canonical 归一与最终分析 |
| --- | --- |
| 某项 MISSING | Packet 为 null → reading 对应值 `None`；部分缺失为 PARTIAL → `SENSOR_PARTIAL`。全部缺失为 INVALID → `SENSOR_INVALID`。领域没有单独的 MISSING Quality。 |
| INVALID / 非有限数 / 超出物理范围 | 对应值 `None`，Quality=INVALID → `SENSOR_INVALID`；其他仍有效的数值继续接受阈值诊断，不是整个 reading 全部丢弃。 |
| STALE | Apply 时按年龄计算独立 Freshness=STALE → `SENSOR_STALE`；可以同时 PARTIAL 或 INVALID。 |
| 数值养殖超标 | 保留有效数值及 Quality，产生相应 Finding，例如 DO=2.2 → `OXYGEN_CRITICAL_LOW`。 |

reading / Findings 进入 AnalysisContext、模型 prompt 和最终 AnalysisResult；模型不能重写这些程序事实。Prompt 用 `--` 呈现缺失数值，同时传入质量、Freshness 和规则警告，不把缺失解释成 0。

## 5. Orchestrator 当前职责与共存方式

输入是 `AnalysisRequest(mode, profile_id, question, generation, reasoning)`，外加可选 `WaterQualityReading` 和 evaluated_at；不是直接接收 ObservedFacts。Web Normal / Streaming 的顺序一致：捕获 runtime 和查询视图 → Diagnosis → RAG → prompt → Gateway → 解析最终文本 → 装配 AnalysisResult → Trace。Streaming 另外输出 facts/rules/evidence/content/usage/completed/failed 等事件。

模型调用前 `_build_model_request()` 显式注入温度、pH、DO、observed_at、Quality、Freshness，以及规则与证据。retrieved_at / source 保留在程序结果和 Trace，但当前事实 prompt 不单独列出它们。模型只生成 inference、recommendations、uncertainty；事实、规则、证据身份由程序装配。

**RECOMMENDATION：** 保留当前固定 Fishery Analysis，尤其 Advice 必须固定诊断。未来增加显式的只读工具对话路径：问题 → 模型工具请求 → 受控 executor → tool result → 后续模型回答。它与固定流程复用取数/Diagnosis/Gateway，而不是立即替代固定流程。第一版限制为一次工具阶段与一次后续回答，不建立开放 Agent Loop；需要更多轮次时明确返回边界。

## 6. Tool 的正确触发语义

是否需要当前系统事实决定是否取数；MISSING / INVALID / STALE / 超标是**取数后的结果**，不能作为是否调用 Tool 的前置条件。

| 用户问题 | 是否需要 `get_current_water_quality()` | 理由 |
| --- | --- | --- |
| 现在水质怎么样？ | 是 | 需要现场快照及程序诊断。 |
| 当前 pH 是多少？ | 是 | 需要当前观测，不能靠知识库猜测。 |
| 现在是否低氧？ | 是 | 需要当前 DO 和 Diagnosis 判断。 |
| 什么是低氧？ | 通常不必 | 概念问题，可以基于知识解释。 |
| DO 2.2 mg/L 意味着什么？ | 通常不必 | 解释用户给定数值；明确标记为用户假设/提供值，不冒充系统当前观测。若追问“是不是我现在的值”，则需要取数。 |

这与 canonical 数据合同兼容，但**当前固定 Chat 不具备这种按问题选择工具的行为**，它始终注入水质、诊断和检索。不要把现有 KnowledgeService 的检索意图评分当成 Tool 路由器，也不要只硬编码上述五句文本。

## 7. tools/ 最小结构建议（本轮不创建）

```text
src/fishery_ai/tools/
├─ __init__.py
├─ contracts.py
├─ registry.py
├─ executor.py
└─ water_quality.py
```

- 按领域分文件；不必一 Tool 一文件。只有一个 Handler 时不要再拆 service / factory / plugin 层。detection.py、knowledge.py 等待实际实现，不创建空占位文件。
- contracts：最小 Tool 定义/执行结果，明确状态、安全错误、结构化 payload；复用 `WaterQualityReading`、`RuleFinding`、`Quality`、`Freshness`，不复制领域合同。
- registry：代码中明确 allowlist，绑定固定 Handler 和参数 schema；不扫描目录、不动态导入。
- executor：验证工具名和参数、执行次数/结果大小、取消检查；只调用已注册只读 Handler。
- water_quality：注入当前 Store 的只读读取依赖、共享 Domain Freshness 策略、Diagnosis；不暴露 set_current。

工具 API 消息合同（工具调用 ID、assistant/tool 消息）归 Gateway；Provider wire 编码归 Adapter / ProtocolSpec；Tool 的业务读取与执行归 tools。不能让 ProtocolSpec 成为 Registry 或执行器，也不能让 Handler 知道 Qwen / DeepSeek 参数。

## 8. ModelGateway / Adapter 的 Tool Calling 准备度

依据：[Gateway 合同](../../src/fishery_ai/model_gateway.py)、[SDK Adapter](../../src/fishery_ai/openai_compatible_adapter.py)、[ProtocolSpec](../../src/fishery_ai/protocol_specs.py)、[Manual Raw 合同](../../src/fishery_ai/manual.py)。以下分类指代码表达和执行能力，不代表真实 Provider 已验证支持。

| 项目 | Managed / Preset 标准路径 | Manual V1/V2 Raw 路径 |
| --- | --- | --- |
| tools request schema | **SUPPORTED BY CURRENT CODE**：ModelRequest.tools + ModelToolDefinition，Adapter 编码；最小 tool_choice 为 auto / none / required 或不发送。仍须 runtime tool_calling=SUPPORTED。 | **SUPPORTED BY CURRENT CODE**：Raw body 可携带 tools；ManualRequest 不禁止此字段，通过 SDK `post('/chat/completions', body=...)` 原样发送。 |
| assistant.tool_calls | **SUPPORTED BY CURRENT CODE**：ModelResponse / ModelMessage 携带 ModelToolCall；合法调用允许 content=null，同步与异步桥接共用解析。 | **SUPPORTED BY CURRENT CODE**：SDK `model_dump()` Raw response / chunk 可保留并展示工具字段；不执行。 |
| tool_call_id | **SUPPORTED BY CURRENT CODE**：ModelMessage 显式字段，编码保留 ID。 | **SUPPORTED BY CURRENT CODE**：可在用户编写的 Raw messages 中传送。 |
| role=tool message | **SUPPORTED BY CURRENT CODE**：要求调用 ID 与合法 JSON content。 | **SUPPORTED BY CURRENT CODE**：Raw messages 可表达完整 tool 消息。 |
| follow-up model request | **SUPPORTED BY CURRENT CODE（手工构造消息）**：已有离线两次请求证明；**NOT IMPLEMENTED（自动执行与后续流程）**。 | **PARTIAL**：用户可手工提交下一份 Raw 请求；没有自动工具执行/后续请求。 |
| 流式工具调用分片 | **NOT IMPLEMENTED**：ModelEvent 只有正文、reasoning、usage、finish_reason；Adapter 不归一 tool_calls delta，也不拼接 arguments。 | **PARTIAL**：Raw chunk 可展示；没有工具 arguments 汇聚与执行。 |

T1 增加了实际 tools request 和消息归一，但不是 executor，也没有修改任何真实模型能力或 Preset。工具请求及工具历史消息使用现有 runtime 三态：UNKNOWN / UNSUPPORTED 拒绝，SUPPORTED 才编码。合法 non-streaming 工具响应接受后视为已输出，不透明重试。正式 Streaming 工具请求与意外工具 delta 明确返回 TOOL_STREAMING_NOT_IMPLEMENTED；不聚合或执行。详见[T1 合同说明](READ_ONLY_TOOL_CALLING.md)。

## 9. 第一个 Tool：get_current_water_quality()

适合作为第一工具；无参数，READ ONLY。只读入口是 app 的 CurrentWaterQualityReader，底层唯一来源是 app 的 CurrentSnapshotStore；不接受 scenario、设备路径、文件路径或时间覆盖。

建议最小输出：

```text
status: OK / NO_DATA
water_quality: canonical facts + quality + freshness + observed_at + retrieved_at + source
evaluated_at: 查询时的程序时间
findings: RuleFinding[]
rule_version: DiagnosisService.RULE_VERSION
```

Reader 已返回查询视图：未来 Handler 只需对 view.reading 运行 Diagnosis，返回程序结果。Reader 返回 None：明确 NO_DATA、water_quality=null、findings=[]；不构造 normal、不读 scenarios。Quality INVALID / PARTIAL 或 Freshness STALE 仍属于“成功读取了存在的快照”，不要伪装成 NO_DATA。

Handler 不读取 ScenarioTemplate、SimulationPacket、模拟资源或 Hardware raw packet。第一版不要求共享规则结果缓存：每次按捕获 reading 重新 diagnose 即可。一次工具读取内部只捕获一次 reading，事实与 Findings 必须一致；后续回答使用该次 ToolResult，不重新取另一份快照替换它。

## 10. Query-time Freshness 风险

**历史问题（已修复）：** 初次审计时，Apply 计算一次 Freshness；一小时后仍返回 fresh。10 月 5 日实现 CurrentWaterQualityReader 后，current API / Web Normal / Streaming 都重新按查询时间计算，不修改 Store 原 reading。

**当前已实现：**

1. contracts.py 的 evaluate_freshness(observed_at, evaluated_at, stale_after_s) 是共享纯领域逻辑。保持“年龄 > 阈值才 stale”，相等仍 fresh。
2. Apply / from_raw 与 Reader 复用它；create_app 将同一 stale_after_s 和 clock 注入 Adapter / Reader。Reader 无写死阈值。
3. 查询读取冻结 Snapshot 后，用 `dataclasses.replace` 生成只更新 freshness 的读视图；保留原 observed_at、retrieved_at、source、Quality。evaluated_at 单独返回，不能将查询时间冒充传感器检索时间。
4. Store 原对象不变；Diagnosis、prompt / tool payload 使用同一读视图。固定 Normal/Streaming 也应通过同一读边界捕获一次视图，避免修了 Tool 却仍有旧分析过期风险。
5. 请求开始时的视图固定到该请求结束；下一次查询重新计算。已补离线测试覆盖边界、过期、PARTIAL/INVALID+STALE、Store 未变及请求间 Apply 隔离。

## 11. 安全设施与缺口

可复用：`web_security.py` 的 Host / loopback Origin / CSRF / 无 CORS 门禁；请求大小限制；RuntimeSnapshot / CredentialSnapshot 的请求隔离；Gateway 的安全错误、timeout、重试策略；`execution.py` 的 RequestHandle 与 Cancellation；Trace 白名单及 public serialization。它们不是工具执行授权的替代品。

需要新增的工具边界：静态 allowlist、严格空参数 schema、每请求次数/结果大小上限、取消检查、安全 ToolResult。未知工具/未知参数必须拒绝；ToolResult 作为数据返回，不成为可信 system 指令。不记录任意完整敏感结果。

第一阶段禁止 Snapshot mutation、DB mutation、阈值修改、设备控制、任意文件读取、Shell、exec/eval、动态 import。不能把现有 Apply API 暴露成模型可执行工具。Manual 返回 tool_calls 继续只展示、不执行；工具模式不得借 Manual Raw 路径绕过 allowlist。

## 12. 阻塞问题与结论

**READY WITH FIXES** 指“可进入 T2 最小只读执行层”，不是“当前已能自动执行工具对话”。

- 数据基础可复用：canonical reading、统一转换、集中 Diagnosis、Web 请求内冻结快照已成立。
- 数据前置修正已完成：共享 query-time Freshness；snapshot-only Reader 与 scenario generation 后备隔离。第二 Store 改为 Demo 专用惰性实例，不作为 Web current 依赖。
- T1 已完成工具 schema、tool_calls / ID / tool 消息、nullable content、显式 follow-up 请求合同。流式工具分片和自动后续流程仍未实现。
- 安全执行缺口：Registry / Executor / 工具参数验证与次数限制尚未实现。
- 精确模型的 Tool Calling 合同仍需独立依据；不能从 Streaming / Thinking 发布记录推导，也不能绕过现有 Preset 固定合同和 Managed 能力门禁。

数据与 non-streaming Gateway 合同条件已满足；未实施执行器或 tools/。固定 Analysis 收到意外工具响应返回 UNEXPECTED_TOOL_CALL，绝不执行。

## 13. 推荐实施顺序

1. **已完成**共享只读 current 查询边界与 Domain Freshness；空快照、过期、Apply 隔离测试覆盖，固定 Analysis 保留。
2. **T1 已完成** Gateway 工具消息合同与 Adapter 编码/归一，离线 Mock / SDK fixture / 官方 SDK MockTransport 验证 tools → assistant.tool_calls → tool_call_id / role=tool → follow-up。Streaming 工具分片仍待单独阶段。
3. 建立最小 tools/，只注册 get_current_water_quality，无参数、无写入能力；先用离线请求证明 NO_DATA / INVALID / STALE / Findings 正确。
4. 新增显式工具对话路径，保留固定 Analysis。限制一个工具阶段，检查 Cancellation、Usage/Trace 和工具事件重试边界。
5. 在精确模型能力得到维护者确认和单独授权后再真实验证；最后做正常概念问题无需现场工具、当前事实问题必须取数的行为测试。不要自动扩展 Tool、Agent 或设备权限。

### 本轮核对范围

初次只读审计未运行测试。数据读取修正新增 tests/test_current_water_quality.py（22 项），并运行现有 Scenario / Telemetry / 水质回归。未执行任何真实模型请求；最终回归记录见下节。

### 数据读取修正验证（2026-10-05）

- Current / Freshness targeted：22 项通过。
- Scenario targeted：19 项通过；Telemetry targeted：18 项通过；既有水质矩阵：9 项通过。
- 完整 Python：`python -m unittest discover -s tests`，430 项通过（21.684 秒）。完整 Browser：`node --test tests/test_browser_streaming.cjs`，114 项通过。
- `node --check src/fishery_ai/resources/web/app.js` 与 `git diff --check` 通过；23 个本地 Markdown 链接有效。
- 安全扫描只覆盖 Git 跟踪及未忽略的源码/文档，没有读取源码 .env、用户私有凭据、outputs 或外部项目。无真实凭据/敏感路径风险；唯一 URL 凭据格式匹配为既有 `tests/test_manual_v2.py` 的 URL 校验负例 fixture，已人工核对测试用途，不输出匹配值。
- 工作树：10 个已跟踪文件修改；本报告（前一轮即未跟踪）、current.py 与 test_current_water_quality.py 为 3 个未跟踪文件。未提交。
- 保持 NO_DATA 原空响应；有数据时返回单独 evaluated_at。旧 Demo 的 observed_facts.evaluated_at 为 null，继续兼容；Web 为查询时间。
- 凭据、Preset、RAG、养殖诊断阈值、Gateway、正式 Fishery_Project 均未修改；不 commit / push。

### T1 Gateway Tool Contract 验证（2026-10-05）

- T1 targeted：29 项通过；覆盖工具定义/消息、nullable response、SDK 编码、畸形调用、两轮 fixture、接受调用后禁止重试、Cancellation 和 Streaming 明确拒绝。
- 完整 Python：459 项通过（20.574 秒）；完整 Browser：114 项通过；JS syntax / diff check 通过；27 个本地 Markdown 链接有效。
- 受控敏感扫描无未解决风险；唯一既有 URL 格式匹配为 Manual V2 校验负例。未读取真实凭据或执行真实请求。
- 工作树为 5 个跟踪文件修改、2 个新文件；未 commit / push。Tool Registry / Executor / get_current_water_quality / Agent / Streaming Tool Calling 均未实施。
- 当前可以进入 T2 的只读 Handler / allowlist 实现；真实模型 Tool capability 不因 T1 改变。

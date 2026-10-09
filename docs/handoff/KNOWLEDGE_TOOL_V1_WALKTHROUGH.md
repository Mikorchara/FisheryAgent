# Knowledge Tool v1 Walkthrough

**状态：PAUSED / NOT IMPLEMENTED。** 本文是基于当前代码的未来实施学习案例，不是已实现功能，也不授权 Copilot 开始开发。当前没有 `knowledge_search.py`、对应 Registry entry、参数化 Handler 或 Knowledge Policy 授权。

> **前置步骤进度（2026-10-09）**：本文之前的地基步骤已经完成，本案例的后续步骤可以直接依赖它们。
> 1. **受控参数合同**（Step 2）：`ToolDefinition` 已支持声明 `validate_arguments`，Executor 会在 Handler 之前完成拒绝或归一化。旧两个无参工具行为不变。见 [`STEP2_TOOL_ARGUMENT_CONTRACT_BEFORE_AFTER.md`](../copilot/STEP2_TOOL_ARGUMENT_CONTRACT_BEFORE_AFTER.md)。
> 2. **`ToolStatus.NO_MATCH`**（Step 3）：合同已采纳该状态，前端安全投影同步认识它；非错误结果仍继续 Request #2。见 [`STEP3_TOOL_STATUS_NO_MATCH_BEFORE_AFTER.md`](../copilot/STEP3_TOOL_STATUS_NO_MATCH_BEFORE_AFTER.md)。
> 3. **薄 Handler**（Step 4）：`tools/handlers/knowledge_search.py` 已实现（未注册）。见 [`STEP4_KNOWLEDGE_HANDLER_DESIGN.md`](../copilot/STEP4_KNOWLEDGE_HANDLER_DESIGN.md)。
> 4. **Registry 注册与依赖注入**（Step 5）：`ToolRegistry` 已支持注入 `KnowledgeService`，并带有正式 `validate_arguments`；**未注入时该名称不被暴露**。见 [`STEP5_KNOWLEDGE_REGISTRATION_BEFORE_AFTER.md`](../copilot/STEP5_KNOWLEDGE_REGISTRATION_BEFORE_AFTER.md)。
> 5. **Catalog 条目**（Step 6）：`tools/catalog.py` 已有第三条 `search_fishery_knowledge`（含 query 参数摘要）。注入服务的实例上该行**可勾选**；未注入的实例上该行**禁用**。**包内默认 Policy 仍未授权**。见 [`STEP6_CATALOG_BEFORE_AFTER.md`](../copilot/STEP6_CATALOG_BEFORE_AFTER.md)。
> 6. **Policy 默认**（Step 7）：**验证完成，无产品代码改动**。实测确认两个模式默认都不授权 Knowledge、旧 override 不被迁移（文件字节与 mtime 不变）、新注册工具不自动进入 `exposed_tools`；补了 2 条回归保护测试。见 [`STEP7_POLICY_DEFAULTS_BEFORE_AFTER.md`](../copilot/STEP7_POLICY_DEFAULTS_BEFORE_AFTER.md)。
> 7. **装配**（Step 8）：`create_app()` 把**已有唯一** `KnowledgeService` 注入 `ToolRegistry`（净改动 1 行）。Knowledge 在真实 Runtime 中已 `executable`，**用户可勾选**；包内默认仍未授权。见 [`STEP8_KNOWLEDGE_ASSEMBLY_BEFORE_AFTER.md`](../copilot/STEP8_KNOWLEDGE_ASSEMBLY_BEFORE_AFTER.md)。
>
> 本文其余内容（UI 文案、人工验收）仍是**未来工作**。**注意：Mock 路径下的人工使用前必须先解决 D1b**（`MockToolGateway` Request #1 的 `request.tools[0]` fallback）。

阅读时把“当前事实”和“未来建议”分开。总体约束见[新增 Tool 规范](../deep-dive/tools/ADDING_A_TOOL.md)，尚待决策的研究见[Knowledge Tool 研究](../deep-dive/research/KNOWLEDGE_TOOL_DESIGN.md)。

## 1. 最终目标

未来目标工具：`search_fishery_knowledge(query)`。它查询项目背景知识，不读取当前水质，不诊断现场疾病，不生成系统评分。

```text
用户：“鳗鱼缺氧会有什么表现？”
  → AssistantContextBuilder.build()：System + 完整历史对 + 问题
  → AssistantService.send()
  → ToolCallingService.run_request()
  → Request #1：Policy 允许的 Registry Tool Definitions
  → 模型决定调用 search_fishery_knowledge({"query":"鳗鱼缺氧表现"})
  → ToolExecutor.execute(ModelToolCall)
  → 未来 Knowledge Handler（参数与输出受限）
  → KnowledgeService.search(query, 固定 top_k)
  → tuple[KnowledgeEvidence, ...]
  → Safe Tool Result（有限背景证据，非现场事实）
  → assistant(tool_calls) + tool(tool_call_id, JSON)
  → Request #2：tool_choice="none"
  → Assistant 最终纯文本回答
```

模型也可以首轮直接回答普通概念；不能用关键词硬路由保证它一定检索。当前预算仍为一个 Tool Call、一轮、最多两次模型请求。这个闭环不是 Agent。

## 2. 第一步：先看现有 KnowledgeService

先读：

- [knowledge.py](../../src/fishery_ai/knowledge.py)：`chunk_knowledge()`、`KnowledgeService.__init__()`、`search()`。
- [contracts.py](../../src/fishery_ai/contracts.py)：`KnowledgeEvidence`。
- [知识资源](../../src/fishery_ai/resources/knowledge/eel_knowledge.json)与[来源说明](../../src/fishery_ai/resources/knowledge/SOURCE.md)。
- [composition.py](../../src/fishery_ai/composition.py)：`RESOURCE_ROOT` 与离线 Analysis 的组合。
- [web.py](../../src/fishery_ai/web.py)：`create_app()` 已构造 KnowledgeService，当前供 Analysis 使用。
- `tests/test_v01.py::KnowledgeTests` 和 `tests/test_v011_a3_grounding.py`。

当前输入是构造时的固定知识资源，以及查询时的 `query: str`。`search(query, *, top_k=5, retrieved_at=None, intent_text=None)` 返回 `tuple[KnowledgeEvidence, ...]`，无结果返回空 tuple。

当前默认 portable TF-IDF 采用字符 2–4 gram、最多 2000 特征，带有限查询扩展、关键词加分和类别相关性调整。资源构造出 31 个 chunk。显式 keyword backend / sklearn 缺失时的 fallback 分数尺度不同，不能把 score 当概率。

`KnowledgeEvidence` 保存 `evidence_id`、`text`、`category`、`score`、`source_id`、`retrieved_at`，以及可选 `source_title`、`source_version`。现有 source 为 `legacy:eel_knowledge.json`，没有逐条文献 provenance；不得编造作者或引用标题。

未来 Handler 复用此服务和资源，不复制 TF-IDF、创建第二份索引或改造 Analysis 的自动检索。资源损坏不是“没有命中”，应安全失败。

## 3. 第二步：定义 Tool Contract

未来在 `tools/registry.py` 创建正式 `ModelToolDefinition`；模型协议类型继续复用 `model_gateway.py`，不再造一份 Tool schema 类型。

建议定义：

- name：`search_fishery_knowledge`。
- description：只读检索项目渔业背景知识；不代表当前传感器状态或现场疾病，不负责当前评分。
- 参数只含必填 `query`，不接受文件路径、URL、backend、top_k 或阈值。

以下仅是未来 schema 候选：

```json
{
  "type": "object",
  "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 512}},
  "required": ["query"],
  "additionalProperties": false
}
```

服务端仍需校验：trim 后非空、长度与 UTF-8 字节预算、非法 Unicode / 控制字符策略、额外字段。JSON Schema 是告诉模型的合同，当前 Gateway 不会替代服务端执行完整 schema 校验。

建议结果：`status`、`retrieval_mode`、明确的检索版本、`result_count`、有限 `evidence[]`。条目保留 evidence ID、类别、来源、资源版本、检索时间与受限文本；无依据时不补造 source title。不必把 raw score 发给模型。

未来可采用 `OK` / `NO_MATCH` / 安全 `ERROR`。**`ToolStatus.NO_MATCH` 已于 2026-10-09 加入合同并核对完全部消费者**（Handler 不能自己造枚举外的状态；无命中与其他业务状态同等对待）。Knowledge 无命中不同于水质的 NO_DATA。

建议先定固定预算，如 top-3、每段最多 800 字符、结果总量不超过 8 KiB；这些不是当前合同，重新立项时需确认。裁剪不得丢掉来源标识或产生损坏 JSON。

## 4. 第三步：薄 Handler

未来可能新增 `src/fishery_ai/tools/handlers/knowledge_search.py`；当前文件不存在。

Handler 只做：接收校验后的 query → 调用注入的 `KnowledgeService.search()` → 映射有限证据 → 返回可序列化 dict。知识内容作为不可信数据，即使其中含有“忽略系统指令”，也不能当指令执行。

Handler 不负责 Tool loop、Policy、模型调用、UI、诊断、评分、独立检索算法或动态选择资源。固定包资源由组合层加载；用户 query 只能作为检索文本，不能作为路径。

## 5. 第四步：Registry 与依赖组合

当前 `ToolRegistry.__init__(reader, diagnosis, scoring=None)` 使用静态 import 和固定绑定，只注册两个水质工具。

未来需要：

1. 加名称常量及 `ModelToolDefinition`。
2. 更新 `registered_names()`；Policy 和安全 Trace 也使用这份名称 allowlist。
3. 在 `_entries` 绑定薄 Handler，不从配置加载函数。
4. 为 Registry 注入 KnowledgeService；`web.py::create_app()` 复用已经构造的实例。
5. 核对测试中所有 Registry 构造入口；明确未注入服务时是拒绝组合还是不暴露该 entry，不制造“注册但不能执行”的假状态。

`model_definitions()` 输出模型可用的定义；`lookup()` 找可执行绑定；二者来自同一 Registry。`ModelToolDefinition` 本身不是授权，也不执行函数。

## 6. 第五步：Catalog

> 编号说明：本文的“第 N 步”与 `docs/copilot/KNOWLEDGE_TOOL_STEP_BY_STEP.md` 的“Step N”**不是同一套编号**（本文“第三步：薄 Handler”= 计划 Step 4；“第四步：Registry”= 计划 Step 5）。本节的 Catalog 对应计划 **Step 6**；下文提到 Step N 时一律沿用计划编号。

`tools/catalog.py::ToolCatalogEntry` / `tool_catalog(registry)` 为 Tool Manager 提供名称、介绍、参数摘要、READ ONLY 等 metadata。Knowledge 的条目与 query 说明**已于 Step 6 补齐**。

Catalog 不注册 Handler，不修改 Runtime Capability，也不授予 Policy 权限。只有 Catalog entry，没有 Registry callable，不会变成可执行 Tool。

**两个容易误读的字段（实测结论）**：

- `executable` 是**派生值**，不是存储字段：`not dev_only` 且 `name in registry.model_definitions()` 且绑定的是 callable。因此“条目存在”与“本实例能执行”是两件事。
- `modes` 是 `tool_catalog()` 里**硬编码**的 `["analysis", "assistant"]`，且**当前无任何消费者**：`policy.py` 只读 `executable`，`app.js` 的“适用模式”是前端自己写死的字符串。详见 [`STEP6_CATALOG_BEFORE_AFTER.md`](../copilot/STEP6_CATALOG_BEFORE_AFTER.md) §2.2。

## 7. 第六步：Policy

先读 `tools/policy.py` 中 `ToolPolicy.model_definitions()`、`allows()`、`UserToolPolicyStore.effective()` 和 `resources/tools/tool_policies.json`。

当前包默认：Analysis 不启用 Tool，Assistant 仅授权查询水质。用户选择保存在 `outputs/tool-policies/tool_policies.json`；每次新请求捕获冻结 Policy。注册存在不等于 Assistant 已授权，旧用户 override 不应被新增默认项静默改写。

未来建议只让 Assistant 可配置 Knowledge Tool。Analysis 已有自动 RAG；再检索会重复证据并占用单 Tool 预算。不要把现有 Analysis Context 替换成 Tool 获取知识。

**当前缺口：** Policy 只限制 Registry 中的名称，并没有 Knowledge 的“仅 Assistant”规则；Catalog / 前端也把现有工具展示为两个模式通用。因此“Analysis 默认关闭”不能证明它永远无法授权。若未来将仅 Assistant 定为硬边界，应最小增加服务端模式限制，并同步 Tool Manager 显示及测试；不能只靠文案或隐藏复选框。

## 8. 第七步：Executor 参数入口

当前 `ToolExecutor.execute()` 实际顺序：

```text
check_cancelled
→ 消耗调用预算 / 拒绝重复 call ID
→ Registry.lookup(name)
→ Policy.allows(name)
→ arguments_json 的 UTF-8 大小上限 4096 bytes
→ JSON object，且必须为空 {}
→ check_cancelled
→ definition.handler()（无参数）
→ check_cancelled
→ ToolExecutionResult.from_payload()（JSON / status 校验）
→ 结果大小上限（默认 32768 bytes）
→ check_cancelled → Result
```

异常变成安全 ERROR；USER_CANCELLED 单独传播。拒绝的尝试也会消耗预算。

**这就是未来 query Tool 的最小框架改动点。** 当前 `ToolDefinition.handler` 为 `Callable[[], dict]`，Executor 拒绝所有非空 dict。不能只写 schema 然后从全局变量或 Web 偷传 query。

建议先独立完成“受控参数合同”小步骤：为静态 ToolDefinition 增加参数校验入口，让 Executor 解析 JSON 后交给该入口验证，再把有限参数交给已绑定 Handler。可以统一采用 `handler(validated_arguments)`，在 Registry 为旧两个无参数函数提供固定包装；旧 Tool 仍严格只接受 `{}`。这些接口尚不存在，实施前需明确选型。

不要引入通用反射、动态 `getattr`、任意 `**arguments` 到未知函数、第二套 Executor 或完整 schema 框架。Cancellation、Policy、预算、错误清洗、结果大小规则继续由同一个 Executor 负责。

## 9. 第八步：追踪 Assistant 到第二轮

当前真实入口和未来接入位置：

| 顺序 | 当前文件 / 函数 | 职责与未来变化 |
| --- | --- | --- |
| 1 | `web.py::assistant_chat()`，POST `/api/assistant/chat` | 检查 epoch / 网络确认，解析固定 Preset、Policy、RuntimeSnapshot，进入 `request_scope(handle)`；继续复用。 |
| 2 | `assistant.py::AssistantService.send()` | 核对 OFF + Normal 发布连接；调用 ContextBuilder；未来不增加 RAG 预取。 |
| 3 | `AssistantContextBuilder.build()` | System + 有界成功历史 + user message；未来只补知识检索选择规则。 |
| 4 | `tool_conversation.py::ToolCallingService.run_request()` | 由 `policy.model_definitions(registry)` 加 tools，调用 Gateway.complete()。 |
| 5 | `model_gateway.py::validate_tool_request()` | 实际 Runtime 需 tool_calling=SUPPORTED；拒绝 Streaming Tool Calling。 |
| 6 | `ToolCallingService.run_request()` | 没有 calls 直接结束；多个 calls 返回 TOOL_CALL_LIMIT。 |
| 7 | `tools/executor.py::ToolExecutor.execute()` | 唯一受控执行入口；未来经 Registry 调 Knowledge Handler。 |
| 8 | 未来 `knowledge_search.py` → `KnowledgeService.search()` | 返回有限背景证据；不读取 Snapshot。 |
| 9 | `ToolCallingService.run_request()` 内 `follow_up` | 追加 assistant(tool_calls)、tool(result.to_json(), tool_call_id)，同一 Runtime 发 Request #2，tool_choice=none。 |
| 10 | `AssistantService.send()` / `AssistantResult.to_dict()` | 成功且正文完整才提交；History 不含原始 Tool JSON。 |

第二轮再要 Tool 返回 TOOL_ROUND_LIMIT，执行 ERROR 不继续模型请求；非错误 NO_MATCH 应交给第二轮解释。两次 Usage、Trace 与 RequestHandle 继续复用，不复制 loop。完整 tool 消息只存在本轮模型上下文，后续历史仍只保留成功文本对。

**当前 UI 缺口也要读：** `resources/web/app.js::safeAssistantActivity()` 只认可现有两个名称和已有状态；`renderAssistantMessages()` 对所有已调用 Tool 都显示“本轮已查询当前水质”。未来必须最小扩展名称/NO_MATCH 安全白名单并区分知识检索，不得把 Knowledge 调用误标成当前水质查询。Trace 的 `JsonlTraceSink.record_tool_conversation()` 已从 Registry 获取名称，通常可直接复用。

## 10. 第九步：未来离线测试

以下是未来实施测试清单，本轮不新增或运行这些测试。

| 类别 | 先读 / 未来修改的测试 | 保护内容 |
| --- | --- | --- |
| Contract | `test_gateway_tool_contract.py`；建议新增 `test_knowledge_tool.py` | query schema、缺字段、额外字段、空白、长度/字节/Unicode、NO_MATCH 状态；不重复 Gateway 协议类型。 |
| Handler | 新 `test_knowledge_tool.py`；`test_v01.py::KnowledgeTests` | 注入 fake KnowledgeService；调用次数和固定 top_k；证据 ID/source/version/time、backend 标识、空结果与资源错误区别。 |
| Registry | `test_read_only_tools.py`、新 `test_knowledge_tool.py` | 定义与绑定单一来源、未知名拒绝、依赖注入；旧工具仍无参数。 |
| Policy | `test_tool_policy.py`、`test_tool_policy_manager.py` | 注册不等于授权；Assistant 开关、Analysis 限制、旧 override 不静默变化、Catalog 不能授权。 |
| Executor | `test_read_only_tools.py`、新 `test_knowledge_tool.py` | 参数校验前不执行、有限结果、错误脱敏、调用预算、重复 ID、取消、禁止网络/路径入口。 |
| Assistant | `test_assistant.py`、`test_tool_conversation.py` | 脚本化首轮 Knowledge call → role=tool → final；直答零检索、NO_MATCH、二轮限制、历史无 raw Evidence、Usage 两轮。 |
| UI | `test_browser_streaming.cjs`，按需 `test_web_tool_conversation.py` | Tool Manager 模式、轻量知识 Activity、无“已查询当前水质”误标；文本安全渲染。 |
| Security / 回归 | 上述 tests；`test_analysis_tools.py`、`test_v011_a3_grounding.py` | 恶意 chunk 仍是 tool 数据；无 Secret/路径/trace 原文；Analysis RAG、查询/评分、三模式和取消不回归。 |

Mock 采用可检查的 scripted Gateway，不扩展生产关键词路由来“让测试通过”。实际模型选择稳定性必须另行人工验证。

## 11. 第十步：未来人工验证

**以下全部是未来验收，不是已完成结果；真实请求须另行授权。**

1. 用户显式授权 Knowledge Tool，确认固定 Preset 合同和运行组合允许 Tool Calling；不自动发布新组合。
2. “什么是溶氧？”允许直接回答，不要求每个概念强制检索。
3. “按项目知识资料，鳗鱼缺氧会有什么表现？”检查 Tool 查询、证据来源和最终回答；无命中诚实说明资料不足。
4. “当前 DO 多少？”选择当前水质 Tool，不能从 Knowledge 猜现场读数。
5. “当前水质评分多少？”选择评分 Tool，不能从 Knowledge 生成系统分数。
6. 仅有 NO_MATCH 时不编造引用；资料里有疾病/药物内容不等于现场已确诊或有治疗指征。
7. 当前事实 + 知识的复合问题仍只有一个调用预算：说明未查询部分，必要时引导拆问，不扩成 Agent。
8. Stop、禁用 Policy、历史追问、旧水质值、结果大小和错误状态分别验收。

## 12. 文件修改清单

所有路径相对项目根；“未来修改”不是本轮变更。`test_knowledge_tool.py` 与 Handler 都是建议新增文件。

| 文件 | 为什么读 | 未来修改 | 目的 / 对应测试 |
| --- | --- | --- | --- |
| `src/fishery_ai/knowledge.py` | 现有检索服务 | 通常不改 | 复用 baseline；`test_v01.py`、`test_v011_a3_grounding.py`。 |
| `src/fishery_ai/contracts.py` | KnowledgeEvidence | 通常不改 | 保留来源/时间合同；Knowledge tests。 |
| `resources/knowledge/*`（包内） | 数据与 provenance | 通常不改 | 不复制数据，不编造来源；Knowledge tests。 |
| `tools/handlers/knowledge_search.py` | 未来薄 Handler | 新增 | query → Service → 安全结果；新 `test_knowledge_tool.py`。 |
| `tools/contracts.py` | 参数执行合同与 ToolStatus | **已完成前置调整**（参数合同 + `NO_MATCH`） | 除非需要新的状态，否则本轮不再改；`test_tool_argument_contract.py`、`test_tool_status_no_match.py`。 |
| `tools/registry.py` | 定义与可执行绑定 | **已改（Step 5）** | 名称常量、schema、静态绑定、`registered_names()`、`knowledge=` 依赖注入；剩余工作只在 Policy/装配。`test_knowledge_registration.py`。 |
| `tools/catalog.py` | UI metadata | **已改（Step 6）** | 第三条 Knowledge 条目（描述、`query` 参数摘要、`experimental=False`）；`tool_catalog()` 未改。`test_catalog_knowledge.py`。 |
| `tools/policy.py` | 服务端授权 | 评估并最小调整（仅默认值） | **不做“仅 Assistant”硬边界**（已决定）；只处理默认授权与旧 override 兼容；Policy tests。 |
| `resources/tools/tool_policies.json`（包内） | 默认授权 | 评估 | 默认不开启，旧配置保持；Policy tests。 |
| `tools/executor.py` | 当前只允许空 object | 需最小调整 | 调用已校验参数；不复制执行器；`test_read_only_tools.py`。 |
| `web.py` | 共享 Service / Registry composition | **已改（Step 8，1 行）** | 把已有唯一 `KnowledgeService` 注入 `ToolRegistry`；不新建第二份；绑定顺序在 store 之前。`test_knowledge_assembly.py`。 |
| `assistant.py` | 上下文与 History | 可能补规则 | 区分实时事实、评分和项目知识；`test_assistant.py`。 |
| `tool_conversation.py` | Request #1/#2 与预算 | 通常不改生产 loop | 复用；核对新增非错误状态；`test_tool_conversation.py`。 |
| `resources/web/app.js`（包内） | Activity 名称/状态和水质提示 | 仍需改（Step 10） | 状态白名单已含 `NO_MATCH`（2026-10-09）；剩余：工具名白名单与"已查询当前水质"文案按工具区分；Browser tests。 |
| `model_gateway.py` / `openai_compatible_adapter.py` | 已有通用协议 | 不应因新增此工具改协议 | 现有 JSON schema / call transport；Gateway tests。 |
| `application.py` | 固定 Analysis 的 RAG | 不应改变流程 | Knowledge v1 不加入 Analysis；Analysis tests。 |
| `observability.py` / `execution.py` / Credential 模块 | Trace / 取消 / Secret | 通常不改 | 保持安全边界；相关回归。 |
| `presets.py` / `resources/profiles/presets.json` | 发布能力合同 | 不自动改 | 新工具的维护者验收不等于 Managed Evidence 发布；Preset tests。 |

下一步学习可从参数合同开始，先证明旧 `{}` 工具完全兼容；本项目当前仍暂停 Knowledge Tool，不进入实现。

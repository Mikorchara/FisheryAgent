# AI Backend 与 Assistant 开发指南

本指南用于管理平台的代码定位、扩展与验证。当前依赖为 `management_web → ai_service → ai_backend`。旧 `src/fishery_ai/` 是独立实验平台，不是管理 LLM 执行的底层。以下路径以仓库根目录为起点；代码示例仅为设计示例，本轮没有新增 Tool 或修改 Prompt。

先读 [工程规则](../AGENTS.md)、[结构地图](STRUCTURE.md)；启动与数据接入见 [BUILD_RUN](BUILD_RUN.md)，数据合同见 [INTEGRATION](INTEGRATION.md)。迁移历史见 [R2C-1 记录](deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md#15-r2c-1e-工程收尾与人工验收)。本指南不复制完整协议、Prompt 或发布 JSON。

## 1. 架构与职责

### 1.1 七个区域

| 区域 | 做什么 | 不在这里做什么 |
|---|---|---|
| `apps/management_web/` | 页面、HTTP/SSE、浏览器访问控制、请求注册/状态/Stop | 模型执行循环、业务阈值、Provider SDK 调用 |
| `apps/ai_service/` 顶层 | `ManagementAssistantService` 装配、设备/Policy 冻结、管理发布配置 | 第二套 Tool 循环、HTTP worker |
| `apps/ai_service/business_tools/` | 一个 Tool 一个模块：名称/Definition/validator/Handler/DTO；registry.py 显式统一装配 | 自动发现、独立权限或 Ledger、重复领域规则 |
| `apps/ai_service/runtime/` | 渔业 Assistant、Prompt、Preset/Policy、领域 Receipt/Ledger、Source/Commit Gate | 通用 Provider 传输、Flask、数据库存储 |
| `apps/ai_backend/` | 通用模型合同、Gateway/Adapter、Streaming Assembler、Tool 循环、执行上下文、安全事件/Trace | 渔业规则、Knowledge 实现、业务 Prompt、默认 Tool |
| `apps/monitoring/` | 权威监测事实、SQLite、历史、确定性 Findings/Events、设备绑定查询 | LLM 解释与模型路由 |
| Knowledge | 当前复用 `fishery_ai.knowledge.KnowledgeService` 与固定知识资源 | 当前现场观测、现场疾病确诊 |
| `src/fishery_ai/` | 独立 Prototype、原有 Analysis/Assistant 与技术实验 | 管理端的新旧 Runtime 自动切换或同步 |

`ai_service/runtime` 的名称容易误解：这里是“业务 Assistant 的运行合同”，不是第二个通用 LLM Runtime。目录暂不改名；新增 Gateway、Assembler、Handle、执行循环应放 Backend，业务来源与 Prompt 应留服务层。

```mermaid
flowchart TD
    UI[管理网页] --> HTTP[management_web: HTTP / POST SSE / RequestRegistry]
    HTTP --> SERVICE[ai_service.service: ManagementAssistantService]
    SERVICE --> BUSINESS[ai_service.runtime: Assistant / Prompt / History裁剪 / Source与Commit Gate]
    SERVICE --> BIND[ai_service.business_tools: registry与业务Handler]
    BUSINESS --> BACKEND[ai_backend: ToolCallingService / Gateway / Adapter / Assembler]
    BACKEND --> PROVIDER[Provider: Normal或Streaming]
    BACKEND --> EXEC[Registry / Policy / Executor]
    EXEC --> BIND
    BIND --> MON[MonitoringService: 同一SQLite权威来源]
    BIND --> KNOW[既有KnowledgeService: 背景Evidence]
    MON -. 领域依赖暂留 .-> DOMAIN[旧contracts / Diagnosis / telemetry]
    KNOW -. 实现和资源暂留 .-> OLD[fishery_ai领域与知识代码]
    BACKEND --> EVENTS[安全Steps / EventChannel / Trace]
    EVENTS --> HTTP
```

箭头表示调用/数据依赖，不代表 Backend 导入业务模块。Handler 由服务层静态注入。Monitoring/Knowledge 的旧领域依赖尚未迁走，所以当前不能卸载整个 fishery_ai 包；管理 Turn 使用的新模型类型、Handle、ContextVar 与 Tool 循环始终来自 Backend。

当前监测规则仍为 PROTOTYPE；模拟观测、视觉疑似检测信号、确定性 Finding 与 LLM 解释应分别保留来源，不能升级成真实设备事实或疾病确诊。

### 1.2 一次当前水质查询如何执行

1. 页面 [assistant.js](../management_web/static/assistant.js) 保存会话 draft/成功文本 pair；[services.js](../management_web/static/services.js) 发起同源请求。`GET /api/ai/bootstrap` 给出 epoch、设备、可用模式、预算和 revision；`POST /api/ai/requests` 创建一个 Handle。
2. [app.py](../management_web/app.py) 先做本机/Host/Origin/浏览器令牌/JSON 检查；[ai_adapter.py](../management_web/ai_adapter.py) 的 `ManagementAssistant._prepare()` 限定 Web 字段，转交业务预检，再取得同一 Handle。
3. [service.py](../ai_service/service.py) 的 `prepare_turn()` / `_configuration()` 校验 epoch、Preset、设备、Policy、Scope、revision 与本次联网确认，返回 [PreparedAssistantTurn](../ai_service/contracts.py)。它冻结设备身份、Profile、Policy、Registry 和执行决策；此时不查询观测、不解析凭据、不联网。
4. `claim_turn()` 先 `handle.start()` 防止重放，设整 Turn 时限；`_execute_claimed_turn()` 在实际工作线程建立 `request_scope` / `turn_deadline_scope`，通过 `ProfileRegistry.snapshot()` 一次取得 `RuntimeSnapshot` / `CredentialSnapshot`。
5. 业务 `AssistantService._send()` 构建 System + 裁剪后的 History + 当前问题；`project_retained_history()` 应用 B 投影。`ToolCallingService.run_request()` 再从有效 Policy/Registry 加入允许的 definitions，调用 Gateway。当前实际 Adapter 为 `OpenAICompatibleAdapter`。
6. 只有模型返回合法 protocol Tool Call，Executor 才执行 `business_tools.current_water_quality.water_payload()` → `MonitoringService.capture_water(device_id)` → 领域分析 → `project_water_tool()`。同一设备使用与网页相同的 SQLite 和规则，不读取 Prototype Snapshot。
7. Result 以 `role=tool` 返回后，单轮模式要求 Final；多轮模式允许模型看到实际 Result 后再决定下一个 Tool 或提前 Final。每轮最多一个 Tool，最多 1/1/2 或 2/2/3，不自动 retry。
8. 业务 `ledger_from_execution()` 从真实 Steps 推导来源；`AssistantService._send()` 检查完整正文、finish reason、SourceRequirement、取消/Deadline、安全 Trace。失败没有成功 Final。后端安全结果通过 Web 返回，前端只把合法成功的 user/final assistant pair 加入下一轮 History。

冻结的是**设备与运行配置**，不是预先冻结一份旧水质读数。Tool 执行时才读取该设备的当前数据。页面与 Tool 的两次独立查询可能跨过新批次，核对时要比较 batch/time，不能只比较数值。

### 1.3 Normal 与 Streaming 的差别

| 环节 | Normal | Streaming |
|---|---|---|
| HTTP | `POST /api/ai/messages`，完成后返回 JSON；状态另行轮询 | `POST /api/ai/messages/stream`，fetch 读取 SSE；不使用自动重连的 EventSource |
| Web 执行 | 同步调用 `execute_turn()` | 预先 claim，再由 [management_web/streaming.py](../management_web/streaming.py) 的 `stream_response()` 建 worker/事件投递 |
| 模型传输 | `ModelGateway.complete()` | `complete_tool_stream()`，由同一个 Adapter 组装完整响应后交原 Tool 循环 |
| 页面 | 等最终正文，Steps 可轮询 | `start/activity/preview_reset/preview/final/error/cancelled`；预览有界且临时 |
| 提交 | 完整成功结果才进入 History | 合法 Final 才提交；Tool 切换、失败、Stop、断流或截断撤销预览 |

两种模式共享成功 History、Policy、Ledger、Commit Gate 和同一套 Tool 执行机制。Streaming 的多次模型请求仍属于一个 Turn；SSE 分片不是 Tool 执行指令。前端 [assistant-events.js](../management_web/static/assistant-events.js) 校验 request_id、epoch、连续序号、revision 与唯一终态，断线不重新请求模型。

## 2. 新增业务 Tool

### 2.1 先区分三种改动

| 任务 | 实际含义 | 不会自动发生的事 |
|---|---|---|
| A：启用已有 Tool | 对已装配且合同存在的 Tool，由用户授权 Policy | 不新增 Handler，不获得新的多轮/Streaming 范围 |
| B：新增 Definition + Handler | 定义 Schema、严格 validator、绑定只读业务服务，并补来源/展示/测试 | 不自动默认授权，不自动取得某 Preset 的资格 |
| C：纳入模型实验范围 | 维护者审核精确 Tool 集合、Identity、协议、Prompt、History、数据绑定与预算 | 不修改用户 Policy，不继承其他模型或旧组合的真实证据 |

当前管理 Registry 只有水质查询与 Knowledge。评分名称只为旧 Policy 合法存储兼容保留，没有评分 Handler。内置默认只授权水质；Knowledge 必须 opt-in。用户现有文件优先于默认值，不应为了联调覆盖它。

### 2.2 准确修改地图：假想“历史水质查询”

假想名称 `get_water_quality_history`，**尚未实现**。建议按以下顺序审查/修改；不是要求每次都改全部文件。

| 顺序 | 当前文件 / 入口 | 需要考虑的改动 |
|---|---|---|
| 1 | [monitoring/service.py](../monitoring/service.py) `MonitoringService.history(device_id, channel, limit=None)` | 已有历史读取可复用；若需要历史质量/Findings/趋势判断，先在 Monitoring 增加统一业务入口，不在 Handler/前端复制规则 |
| 2 | 拟新增 `business_tools/water_quality_history.py`；参考 [水质模块](../ai_service/business_tools/current_water_quality.py)、[Knowledge 模块](../ai_service/business_tools/fishery_knowledge.py) | 同一模块放新名称、Definition/Schema、专用 validator、Handler、有限 DTO/绑定版本；Knowledge 的 validate_arguments 只校验 query，不复用为历史参数校验 |
| 3 | [business_tools/registry.py](../ai_service/business_tools/registry.py) `bind_tools()`、`KNOWN_TOOL_NAMES` | 显式加入新 Tool；初始 formal Registry 与每 Turn Registry 定义一致。设备来自服务器冻结上下文，不来自模型参数 |
| 4 | [runtime/policy.py](../ai_service/runtime/policy.py)、[tool_policies.json](../ai_service/runtime/resources/tool_policies.json) | 已知名称使配置可解析；新 Tool 默认关闭。确认配置大小/数量约束，不擅自写用户 Policy |
| 5 | [runtime/sources.py](../ai_service/runtime/sources.py) | 决定是否需历史来源类型/Requirement；明确 schema/status 校验。当前只识别三种既有来源，未知 Tool 不自动取得正向 Receipt |
| 6 | [runtime/catalog.py](../ai_service/runtime/catalog.py)、[runtime/activity.py](../ai_service/runtime/activity.py) | 名称、短摘要、有限时间/状态/计数；不能把历史记录全文或参数放进 Activity |
| 7 | [service.py](../ai_service/service.py) `local()`、`_configuration()` | `JsonlTraceSink(tool_names=...)` 的固定名单要同步；执行授权仍与实际装配求交 |
| 8 | [execution.py](../ai_service/execution.py)、[streaming.py](../ai_service/streaming.py) 与各自资源 JSON | 检查是否需要新的数据绑定版本/精确组合。Streaming 当前还有固定 `STREAMING_TOOLS` 限制，不能只往 JSON 加名称 |
| 9 | [release_contracts.py](../ai_service/runtime/release_contracts.py)、[streaming_contracts.py](../ai_service/runtime/streaming_contracts.py) | 通常只使用已有 hash/Scope 计算，不为加 Tool 放宽匹配器；不同语义的 Scope 扩展须另审 |
| 10 | [业务测试](../ai_service/runtime/tests/test_foundation.py)、[HTTP测试](../management_web/tests/test_knowledge.py)、[资格入口](../ai_service/development/streaming_qualification.py) | 补新增 Tool 的离线单元/API/来源测试；现有管理资格仅三固定案例，不是任意新 Tool 的通用授权器 |

`business_tools/registry.py::bind_tools(..., formal=...)` 是唯一业务 Registry 装配入口：当前只重绑水质 Handler，Knowledge 保留 formal entry 和共享 KnowledgeService。新 Tool 不能只添加到启动时 Registry；每 Turn 的重绑也要保留它，并让 definitions 来自同一个 formal owner。否则可能“启动可见、实际不可执行”。

`business_tools/__init__.py` 不 re-export 工具或工厂。旧 runtime/tools.py 与顶层 bindings.py 已移除，不提供 Alias/兼容入口；调用方直接导入工具 owner 或统一 registry。`WATER_QUALITY_SCORE` 和 `KNOWN_TOOL_NAMES` 位于 registry.py，评分只用于合法存储名称校验，没有 Definition/Handler。

### 2.3 Definition 与校验的最小示例

以下是未来可放入拟新增 `business_tools/water_quality_history.py` 的示意片段，不注册、不执行、不授予权限：

```python
from apps.ai_backend.model_gateway import ModelToolDefinition

HISTORY_NAME = "get_water_quality_history"
HISTORY_DEFINITION = ModelToolDefinition(
    name=HISTORY_NAME,
    description=("只读查询绑定设备的历史水质窗口；用于回顾过去记录。"
                 "结果不是本轮当前观测，不能证明当前状态或恢复正常。"),
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 12}},
        "required": ["limit"],
        "additionalProperties": False,
    },
)

def validate_history_arguments(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"limit"}:
        raise ValueError("invalid history arguments")
    limit = arguments["limit"]
    if type(limit) is not int or not 1 <= limit <= 12:
        raise ValueError("invalid history limit")
    return {"limit": limit}
```

Schema 给模型说明参数；**Executor 没有运行通用 JSON Schema 引擎**，它校验有界 JSON/object，再调用 `ToolDefinition.validate_arguments`。因此必须有上述服务端 validator；`bool` 是 Python 的 int 子类，不能用 `isinstance(limit, int)` 接受它。

有参数的 `ToolDefinition` 把规范化 dict 作为 Handler 的一个位置参数；无 validator 的现有水质 Tool 只允许 `{}`，执行零参数 Handler。以下片段用于未来 registry.py 的 bind_tools 内部：history 指拟新增模块，monitoring/device_id 都是服务器已冻结的对象，不是 Web/模型指定的可执行代码：

```python
from functools import partial
from apps.ai_backend.tools import ToolDefinition

history_entry = ToolDefinition(
    history.HISTORY_DEFINITION,
    partial(history.history_payload, monitoring=monitoring, device_id=device_id),
    validate_arguments=history.validate_history_arguments,
)
```

拟新增 Handler 的签名可为 `history_payload(arguments, *, monitoring, device_id)`，调用现有 `monitoring.history(device_id, "water", limit=arguments["limit"])`；当前返回包含 batch/device/session、source_kind、observed_at/received_at、window、summary。必须显式投影需要的指标、单位、有效/无效样本数、窗口语义与时间；不要直接把全部 Web history DTO 交给 LLM。`limit` 也不得超过服务器现有 history_limit。示例模块/Handler 尚未实现。

只是读取有限历史窗口时，不必新增领域框架；需要“趋势恶化”“恢复”等判断时，应先补 Monitoring 的确定性领域服务/测试，再绑定结果。历史中没有有效样本就返回缺失，不能填零；历史时间范围不能冒充当前 freshness。重复/跨 Session/缺口处理沿用 Monitoring，不在 AI 层另写 SQLite 查询。

### 2.4 来源、展示与实验授权

- 历史查询不能满足 `CURRENT_OBSERVATION_QUERY`，也不能认证 `CURRENT_TOOL_OBSERVATION`。若未来需要历史查询 Requirement，先设计其语义和独立消费者，再扩展 Receipt/Gate；不能借现有 enum 偷换成当前来源。
- `NO_DATA` / `NO_MATCH` 不是同一种结果：前者是没有观测，后者是检索完成无命中。operation completed 与 payload exists 分开判断。当前 water Tool 的 `OK` 仍可能是 INVALID/PARTIAL/STALE，须读取质量与时间。
- Ledger 从本轮真实 ToolExecutionStep 产生；History、模型正文中的“我查询了”不能产生 Receipt。新 Tool 未被来源解析器认可时，不应为显示好看伪造来源。
- Catalog 是人类显示 metadata；真正发给模型的是 Registry 的 `ModelToolDefinition.description/parameters`。更新 Catalog 不会改变模型请求、注册或权限。
- 当前管理页没有独立 Tool Policy 编辑器；既有 Tool 可由 Prototype Tool Manager 修改共享选择文件。新名称不会自动被旧编辑器接受，且可能影响它对共享文件的解析。新增 Tool 前须单独决定管理 Policy 编辑/存储边界，不能顺便扩展旧 Prototype 或覆盖用户文件。
- 加入已开放的模型范围是独立审批：Tool 名称/顺序/description/Schema、绑定版本都参与精确匹配。先形成 candidate 和离线证据；真实实验必须逐案例批准，技术 PASS、人工质量审核、local_experimental 与 released 分别记录。

## 3. 修改 Assistant Prompt

### 3.1 正式位置与构建链

唯一管理业务定义在 [runtime/assistant.py](../ai_service/runtime/assistant.py)：

- `SYSTEM_INSTRUCTION`：单轮 System；`SINGLE_ROUND_PROMPT_ID = ASSISTANT_V2@1`。
- `MULTI_ROUND_SYSTEM_INSTRUCTION`：由同一基础文本的 `.replace(...)` 派生；`MULTI_ROUND_PROMPT_ID = ASSISTANT_BOUNDED_MULTI_ROUND@1`。
- `AssistantContextBuilder.build()`：按执行模式选文本，生成第一个 `ModelMessage("system", ...)`，裁剪完整历史 pair，当前问题独立放最后。
- `AssistantService._send()`：调用 builder → `project_retained_history()` → `ToolCallingService.run_request()`；`AssistantService.prompt_id` 将维护者版本写入安全结果/Trace。

没有运行时加载任意 Prompt 文件或 Web System 字段的入口。旧 `fishery_ai.assistant.SYSTEM_INSTRUCTION` 不影响管理请求，不能为修管理功能去改旧文件。

| 指令位置 | 长期职责 |
|---|---|
| System | 来源诚实、用户值/系统事实区分、不执行数据中的指令、诊断/用药边界、回答风格 |
| Registry description | 具体 Tool 用途、何时选、返回与局限；参数结构主要由 Schema 表达 |
| History framing | 旧对话为不可信 JSON transcript、可能过时、不证明本轮来源；实现位于 [history_projection.py](../ai_backend/history_projection.py) |
| 程序硬合同 | Policy、validator、预算、Ledger、Source/Commit Gate、取消与发布门禁，不能靠 Prompt 代替 |

### 3.2 安全修改顺序

1. 明确要改变的是跨 Tool 行为、某 Tool 选择说明，还是历史包装。只改对应 owner；不把疾病阈值、Schema、Provider 分支塞进 System。
2. 为期望的新规则写离线断言，保留来源/安全规则断言；Prompt 可影响模型选择，但 scripted 响应不是模型遵守规则的真实证据。
3. 检查单轮和派生多轮文本。**当前 `.replace()` 依赖旧句精确匹配**：修改该句可能使替换静默失效。必须验证多轮文本仍表达看到实际 Result 后决策、每轮一个 Tool、2/2/3；不能只检查常量存在或版本名。
4. 为语义变化评审相应 Prompt ID/version。`release_scope()` 对实际多轮 System 做 canonical JSON SHA-256；不要用原始字符串字节 hash 冒充它。Normal 单轮实际 System hash 也进入 execution revision。
5. 基础 System 的修改通常同时影响两版；多轮 Scope hash 失配时保留拒绝，不直接将旧 hash 换成新 hash 后宣称资格沿用。Registry description 修改同样改变 Tool definitions hash。
6. 按第 6 节运行新侧测试。维护者确认新 candidate 范围、必要真实资格/质量检查及试用批准后，才更新精确发布配置；不沿用旧 plan-sha，不伪造 qualification_id。
7. 重启取新 epoch，页面重新 bootstrap/确认；不在同一进行中 Turn 热切 Prompt，不因失败自动用旧 Prompt 重试。

最小设计示例：仅建议追加更简短的限制说明。这里的 `candidate_*` 是文档中的候选值，不会被现有请求加载，也不是生产配置：

```python
candidate_single_instruction = SYSTEM_INSTRUCTION + "信息不足时，简短说明缺少的来源。"
candidate_single_prompt_id = "ASSISTANT_V2@2"
```

实施时要审核实际 System 与派生多轮文本，而不是新增无人使用的候选常量。若只修改单轮路径，仍需检查共享基础文本没有意外改变多轮。Prompt ID 是版本标识，hash 是内容匹配，两者都不是模型能力证明。

验证不只看自然语言：还要断言未授权 Tool 不执行、非法参数不进 Handler、Tool imitation 不产生 Receipt、Requirement 不满足不提交、失败/取消/截断不进 History。当前 Web Requirement 默认 `AUTO`，它允许合法 no-tool；Source Gate 不是任意正文真实性的裁判，也不会按关键词强制执行查询。

## 4. 模型与执行参数在哪里修改

| 参数/合同 | 当前 owner | 修改边界 |
|---|---|---|
| Preset Identity、固定 capability、变体与超时 | [runtime/resources/presets.json](../ai_service/runtime/resources/presets.json)、[presets.py](../ai_service/runtime/presets.py) | 维护者发布合同；`service.PRESETS` 当前只列 Qwen/Ollama。Backend 支持 DeepSeek 编码不代表管理页已授权 |
| ProtocolSpec、请求字段编码 | [backend/protocol_specs.py](../ai_backend/protocol_specs.py)、[providers.py](../ai_backend/providers.py)、[Adapter](../ai_backend/openai_compatible_adapter.py) | `max_tokens`/Thinking/Usage 等编码不授予 capability；固定 Preset 协议须匹配 |
| Thinking | `assistant_profile()` / Profile 的 ReasoningOptions | 管理 Assistant 固定 OFF；不能只加下拉就开放 ON + Tool |
| Normal/Streaming | `ExecutionDecision.model_transport`、Web 路由 | 前端选择下一条消息的受控路径，不能提交任意 mode/budget/Prompt。Streaming 不是把 `profile.default_response_mode` 改成 streaming；业务 guard 仍要求正式 Normal 基础 Profile |
| 输出 tokens | Profile `default_generation`、Backend `effective_options()`；Streaming 发布记录 `max_output_tokens` | Streaming 由 Service 设置 `RuntimeSnapshot.transport_output_token_limit`，Adapter 按 ProtocolSpec 编码；当前 Qwen 管理上限 512/请求。不要把它当成所有 Normal 请求的统一默认 |
| Tool / round / request budget | [tool_conversation.py](../ai_backend/tool_conversation.py) `ToolTurnBudget`、`ToolExecutionMode` | 固定 1/1/2 或 2/2/3，每轮最多一个；选择业务执行模式不等于可随意修改预算 |
| 整 Turn Deadline / retry | Preset 超时、Service `claim_turn()` / `_execute_claimed_turn()`、[backend/execution.py](../ai_backend/execution.py) | 覆盖所有模型/Tool与提交检查；当前 Qwen 120秒、retry=0。不是每轮重置一份120秒 |
| Normal 多轮发布 | [service/execution.py](../ai_service/execution.py) 与 [assistant_execution.json](../ai_service/resources/assistant_execution.json) | 管理独立 Scope、数据绑定、flag 与 revision，不处理取消 |
| Streaming 发布 | [service/streaming.py](../ai_service/streaming.py) 与 [assistant_streaming.json](../ai_service/resources/assistant_streaming.json) | 当前仅 Qwen 精确水质+Knowledge、local_experimental、默认关闭；不是 SSE worker |

两个 trial 启动参数只启用已匹配且批准的范围，不能将 candidate 变 released。Scope 描述维护者范围；revision 将当前配置、实际装配 definitions、完整用户选择、有效 Policy、设备与 epoch 等绑定到本次确认。模式、设备、Policy、预算或相关定义变化后，旧确认失效。不要为解除报错删除这些字段或放宽匹配。

当前管理发布 loader 仅接受 candidate / local_experimental，资格 ID/时间为空；不是把 JSON 的 status 改成 released 就能正式发布。Streaming resolver 还检查固定 Preset/Tool 组合、120 秒与 retry=0；参数变化造成拒绝时，应评审合同与资格影响，不顺手删除这些检查。

## 5. 必须保持的安全边界

| 边界 | 业务开发必须遵守 |
|---|---|
| Registry / Policy / Executor | 静态绑定、授权求交、JSON/object/validator、只读、结果大小与去重；不能通过 description 注册代码或执行用户传入的函数 |
| RequestHandle / Stop / Deadline | 一次 claim、同一取消 owner、实际 worker 的 ContextVar；取消不是 Provider 一定停止计算/计费的保证，不创建替代 Handle 重发 |
| History | 成功文本 pair、6 turns / 6 KiB 完整 pair 裁剪 → B 投影；空历史不插 transcript；不存 Tool protocol/Raw Result/Ledger，不增 Memory/DB |
| Receipt / Ledger / Source Gate | 每个真实 Tool Result 单独认证操作与可用来源；不合并不同时间观测，不信任模型/浏览器的执行声明；Requirement 内部设置，Web 不可指定 |
| Trace / Commit Gate | 安全 allowlist、Trace 失败/取消/超时/非完整 Final 不提交；真实执行过的 Ledger 可保留审计，但不代表 Turn 成功 |
| Streaming Preview | 只为临时显示；完整收流、正常终止、参数验证与清理后才执行 Tool；Final 通过门禁才能进入 History，断线不自动重连重跑 |
| CredentialSnapshot | 正式 Store 每 Turn 解析/冻结一次，PROCESS_ENV → 用户私有 PROJECT_ENV → MISSING；只存引用，禁止读取源码根 .env、复制/输出 Secret 或改 ACL |

扩展业务通常只应改 Service/业务合同、Monitoring/Knowledge、绑定与相应测试。修改 Assembler、取消状态机、权限/来源 Gate、凭据处理、预算或 SSE 协议属于执行合同变更，需独立评审和相关回归，不能夹在“加一个业务功能”中完成。

READ ONLY 是受审查的业务 Handler 合同；Executor 不会沙箱化任意 Python 函数。它保证授权、参数与预算门禁，新 Handler 本身仍必须检查无设备控制、数据库写入或其他未授权副作用。

## 6. 开发与测试检查清单

### 6.1 新增 Tool

- [ ] 现有 Monitoring/Knowledge API 可复用；需要新领域判断时先建立唯一业务服务。
- [ ] Schema 与 validator 一致；空/额外参数、bool、编码、复杂度、超限安全拒绝，Handler 未被执行。
- [ ] formal 与 per-turn Registry 一致，设备冻结；未授权/未装配 Tool 在执行前拒绝，默认不擅自授权。
- [ ] NO_DATA/部分/无效/过期/离线语义明确；历史/Knowledge 不冒充当前来源；来源解析只读实际 Result。
- [ ] Catalog、Activity、安全 Trace 名单同步，无 raw 参数、Result、query/正文泄露。
- [ ] Scope、绑定、revision 和确认失效正确；旧组合与新组合资格隔离。
- [ ] 用 Fake Provider 验证直答、Tool→Final、已有双 Tool、取消/失败/History；没有扩大一轮多个 Tool 或总预算。

优先运行以下已存在的入口，新增测试应加入相应新侧包：

```powershell
.\.venv\Scripts\python.exe -m unittest apps.ai_service.runtime.tests.test_foundation apps.ai_service.runtime.tests.test_integration apps.ai_service.tests.test_service
.\.venv\Scripts\python.exe -m unittest apps.ai_service.tests.test_business_tools
.\.venv\Scripts\python.exe -m unittest apps.management_web.tests.test_assistant apps.management_web.tests.test_knowledge apps.management_web.tests.test_multi_round
.\.venv\Scripts\python.exe scripts/dev/run_tests.py fast
```

### 6.2 修改 Prompt

- [ ] 单轮与派生多轮规则均检查，明确 System / Tool description / History 各自职责。
- [ ] ID、实际内容 hash 与 Scope 影响已核对，失配保留拒绝，旧资格/报告不改写。
- [ ] 来源/Policy/参数/预算/取消等硬合同断言保持，no-tool 概念题仍合法。
- [ ] 不以 Mock 语言输出证明模型选择可靠性；真实验证/质量审核须单独授权。

```powershell
.\.venv\Scripts\python.exe -m unittest apps.ai_service.runtime.tests.test_foundation apps.ai_service.runtime.tests.test_integration apps.ai_service.tests.test_execution apps.ai_service.tests.test_streaming_config
.\.venv\Scripts\python.exe -m unittest apps.management_web.tests.test_multi_round apps.management_web.tests.test_streaming
.\.venv\Scripts\python.exe scripts/dev/run_tests.py backend
```

历史迁移差分测试/fixtures 记录当时 Prompt、协议与 DTO 指纹。经批准的语义变更可能使它们失配，应解释差异、补新版本合同测试并评审旧断言适用范围；不要机械覆盖黄金文件或把新旧真实资格标成相同。

### 6.3 修改 Provider 参数

- [ ] 区分 Preset 合同、协议编码、执行预算与试用范围；不靠改一个 JSON 绕过能力门禁。
- [ ] Token 字段/Thinking/stream_options 的实际 SDK 编码有 Fake 覆盖；严格类型、超限拒绝。
- [ ] Scope/revision/epoch 与旧确认失效覆盖；不增加 retry、failover、自动 Normal 重跑。
- [ ] Streaming 覆盖分片、完整性、Usage、资源关闭、Stop/Timeout/断流/截断和预览撤销。

```powershell
.\.venv\Scripts\python.exe -m unittest apps.ai_backend.tests.test_protocol_specs apps.ai_backend.tests.test_assembler apps.ai_backend.tests.test_execution
.\.venv\Scripts\python.exe -m unittest apps.ai_service.tests.test_execution apps.ai_service.tests.test_streaming_config apps.management_web.tests.test_streaming
node --test apps/management_web/tests/*.test.mjs
```

范围较大或执行合同改变时运行 `python scripts/dev/run_tests.py product`（正式产品测试，含 Backend）；管理 HTTP/前端仍应显式跑上述 apps 测试，不能假设根 product 覆盖全部管理页面。只有 qualification 基础设施受影响时再运行 `python scripts/dev/run_tests.py qualification`；单跑管理资格可用 `python -m unittest apps.ai_service.tests.test_streaming_qualification`。全部保持离线 Fake，使用临时数据和虚构凭据。

现有无网络计划检查命令：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_streaming.py --case current-water --dry-run
```

它只覆盖当前固定管理案例/Scope，不会开放 Web 或验证新 Tool。修改计划时重新审查 hash；实际模型请求必须等用户对本轮单案例明确批准。本指南不提供自动真实执行步骤。文档检查补充 Markdown 本地链接/锚点、代码示例语法、`git diff --check` 和敏感模式扫描。

## 7. 出错时的定位顺序与回滚

1. **先看预检**：epoch、设备、Preset、实际装配/Policy、can_send/mode_reason、Scope/revision、联网确认。此阶段拒绝不能记成 Provider 故障。
2. **再看模型请求 Step**：是否真正开始、协议调用数、finish_reason、安全错误。`TOOL_CALL_LIMIT` 可能是同轮多个调用，2/2/3 不允许同轮并行两个 Tool。
3. **参数与执行**：检查安全 argument_diagnostic 的阶段/拒因，再看 Handler 是否开始、status/耗时。不要为定位复制原始 arguments、query、Result、Prompt 或凭据。
4. **来源与提交**：区分 operation completed、payload exists、Requirement、Trace、取消/Deadline 和 Final；保留已有 Ledger 审计不等于允许失败 Turn 进入 History。
5. **最后查前端**：request_id/epoch/seq、终态、预览撤销、成功 pair。服务端已完成但 Final 投递失败时，客户端不自动补 History，更不能重发原问题制造第二次费用。

回滚先 Stop、停止本人进程，保存当前改动与安全证据。仅关闭实验时去掉 trial 参数重启，保留独立 Backend/Normal；代码变更按已审阅的完整提交范围回退并重新 bootstrap/确认。不单独替换一侧 Handle/Adapter，不 reset 整个工作树，不删除 SQLite/用户 Policy/凭据/资格报告，不在失败后自动切回旧 Runtime。

## 8. 已知维护问题

- `ai_service/runtime` 名称与 Backend 的“Runtime”容易混淆，当前通过职责说明解决，暂无改名计划。
- 单/多轮 System 的字符串替换耦合、共享 Policy 编辑边界、新 Tool 的来源类型，需要在相关扩展任务中明确处理，本轮不重构。
- Monitoring/Knowledge 仍引用旧领域包；Backend 本身禁止反向导入这些业务。独立领域迁移另立任务。
- 精确资格与历史差分测试各有版本基线；技术 PASS、基本网页人工验收、回答质量审核和产品发布是不同证据，不自动互相继承。

# 如何新增只读 Tool

这是通用的正式 Tool 新增规范。新增工具是受控代码变更，不是动态插件安装；当前只执行静态 Registry 中注册、由本次 Policy 授权的 Handler。

## 1. 完整数据流

```text
领域服务 ← 薄 Handler ← Registry 静态绑定
                           ├─ ModelToolDefinition（模型协议 schema）
                           └─ Catalog（仅 UI metadata）
用户问题 / 已捕获 Analysis Context
  → 应用捕获 Policy + RuntimeSnapshot + RequestHandle
  → ToolCallingService.run_request()
  → Policy.model_definitions(Registry)
  → ModelRequest.tools → Capability gate → Gateway / Adapter
  → Request #1 返回正文（直接结束）或 assistant.tool_calls
  → ToolExecutor.execute(call)
  → Registry.lookup + Policy.allows + 参数 / 预算 / 取消校验
  → 固定 Handler → 领域服务 → 安全 ToolExecutionResult
  → assistant(tool_calls) + tool(tool_call_id, JSON)
  → Request #2：tool_choice=none → 最终回答
  → 应用 Result / 轻量 Activity / 安全 Trace
```

当前最多一个调用、一轮、两次模型请求。Tool Calling 不等于 Agent，不自动预执行所有授权工具。

## 2. 各层职责

| 层 / 文件（相对 `src/fishery_ai/`） | 权责 |
| --- | --- |
| Domain / Service | 维护事实、规则与算法；先复用现有服务。 |
| `tools/handlers/` | 受控输入 → 服务调用 → 有限 dict；不管理模型循环、授权或 Provider 参数。 |
| `tools/registry.py` | 唯一静态定义与执行绑定。`lookup()` 与 `model_definitions()` 始终一致（都来自本实例已绑定的 entry，不允许"注册了但没有可执行 Handler"）；`registered_names()` 是**全部已知名称**的固定 allowlist，供 Policy 默认文件与 Trace / 公开输出白名单使用，**不等于**单个实例的绑定集合。 |
| `tools/catalog.py` | UI 名称、说明、参数摘要和实验标记；不注册函数、不授权。`registered` / `executable` / `modes` 是 `tool_catalog()` 的**派生输出**（前两个查 Registry，故同一份 `CATALOG` 在不同实例上结果不同）。`experimental=True` 在 UI 里被渲染成"NOT PROFESSIONAL STANDARD"，是**评分口径**声明，只对做评分的工具使用。 |
| `tools/policy.py` | Analysis / Assistant 的冻结授权；只能缩小 Registry allowlist。 |
| `tools/executor.py` | 唯一执行入口：参数、权限、预算、重复 ID、取消、结果与安全错误。 |
| `tool_conversation.py` | 唯一有限模型—工具—模型协调；判断是否结束、是否发 Request #2。 |
| `model_gateway.py` / Adapter | 模型协议、能力门禁、编解码与传输；不执行 Tool。 |

`ModelToolDefinition` 在 `model_gateway.py` 定义，包含 name、description、parameters JSON Schema、type=function。Registry 持有定义；`parameters_dict()` 返回独立副本。它告诉模型能请求什么，不注册 Python 函数，也不自动校验所有 schema 约束。

Catalog 的 `registered` / `executable` 从 Registry 与 callable 推导；添加显示条目不能制造执行权。即便前端勾选或模型伪造名称，服务端仍须通过 Registry + Policy。

Handler 必须经 Executor 调用。Web 或应用直接调用 Handler 会绕过权限、预算、取消、结果限制与错误清洗；不得另设快捷执行路径。

## 3. 新增顺序

1. 确定只读业务边界，定义可离线测试的领域输入输出。
2. 设计唯一名称、职责清晰的 description、严格参数 schema 和安全结果状态。
3. 实现薄 Handler，由组合层注入依赖；不允许模型选择文件、URL、模块或命令。
4. 静态注册 Definition + Handler，更新 `registered_names()`；核对构造入口与测试注入。
5. 补 Catalog，核对 UI 名称/状态白名单和领域专用提示。
6. 审查包内 `resources/tools/tool_policies.json` 与用户覆盖；不自动开启新工具或改写旧选择。
7. 复用 Executor、协调器和模型合同；需要新参数形态时单独最小演进，先保护旧工具。
8. 补参数、Handler、Policy、预算、错误、取消、结果、应用/UI和零网络测试。
9. 真实模型验收另行授权；测试通过不等于自动修改 Preset 或 Managed Evidence。

## 4. 当前参数与结果限制

当前两个工具都无参数。`ToolExecutor.execute()` 限制 arguments JSON 为 object 且必须为空 `{}`，最多 4096 UTF-8 bytes；`ToolDefinition.handler` 为 `Callable[[], dict]`，调用时使用 `handler()`。

新增带参数工具不能只写 JSON Schema，须明确服务端校验与传参合同。不通过全局变量、Web 状态或任意反射绕过 Executor；旧工具仍拒绝所有多余参数。

`ToolExecutionResult.from_payload()` 安全 JSON 序列化，默认结果上限 32768 bytes；status 必须属于 OK / PARTIAL / NOT_SCORABLE / NO_DATA / NO_MATCH / ERROR。其中 `ERROR` 才带 `error_code`；`NO_MATCH` 表示"请求合法但没有任何合格命中"，与"主体没有当前数据"的 `NO_DATA` 语义不同。新增状态要扩展合同并核对消费者。此检查不是完整领域 schema 验证；Handler 仍负责有限结果字段。

## 5. Assistant / Analysis 如何获得定义

**Assistant：** `web.py::assistant_chat()` 捕获 Assistant Policy 与发布 Preset Runtime；`AssistantService.send()` 经 `AssistantContextBuilder.build()` 构造 System + 完整成功历史 + 问题，调用共享 `run_request()`。首轮不预注入 Snapshot、Diagnosis 或 RAG。

**Analysis：** `application.py::Orchestrator.analyze()` 始终先捕获 Snapshot、诊断和检索，构造固定 Context。Policy 启用时才进入同一协调器；未启用保持原普通请求。Tool 观测不覆盖已捕获 Facts，启用 Tool 的 Streaming 明确拒绝。

协调器从 `ToolPolicy.model_definitions(registry)` 取正式定义，不在应用手写第二份 schema；Gateway 再要求精确 Runtime 的 tool_calling=SUPPORTED。

当前 Policy 没有通用的“某名称仅允许某模式”限制，Catalog 也按两个模式展示。未来工具若只许 Assistant 使用，须落实服务端规则并同步 UI；仅默认关闭 Analysis 或隐藏按钮不构成授权边界。

## 6. Request #2 与失败路径

首轮无 tool_calls：直接返回，不执行工具。一次多个 calls：TOOL_CALL_LIMIT，不择一偷偷执行。

合法单调用经 Executor 执行；非 ERROR 结果保存为 `role=tool` JSON。协调器追加原 assistant 的 tool_calls，用同一 call ID 关联结果；Request #2 设置 tool_choice=none。第二轮继续要工具返回 TOOL_ROUND_LIMIT，不发第三轮。

执行 ERROR 不继续第二轮。NO_DATA / NO_MATCH 等正常业务状态交给模型解释。两轮使用同一不可变 Runtime/Credential snapshot，Usage 分步保留并合并，缺失不伪装为零。

首轮后、Handler 前后及第二轮前后沿用 RequestHandle 检查取消；取消不提交半成品、不写能力证据。关闭本地 I/O 不证明远端停止计算/计费。

## 7. 从“代码存在”到“模型能调用”的条件

- Handler 与依赖可安全构造；`lookup()` 与 `model_definitions()` 一致（不得出现"注册了但没有可执行 Handler"的假状态），名称在 `registered_names()` 之内。
- 参数执行入口支持其合同，有限结果可序列化。
- 正式 UI 需要展示时有 Catalog，但展示不代替授权。
- 本次应用 Policy 授权名称，任何模式限制通过。
- 应用实际把允许的 definitions 放入 ModelRequest；Manual Raw 不自动执行。
- 精确 Runtime Tool Capability 为 SUPPORTED；协议可编码不能代替模型能力证据。
- 凭据满足现有规则，真实请求已明确确认，请求未取消且为 Normal。
- 模型实际选择工具，返回合法参数和 ID；description 不保证真实模型行为。

## 8. 安全边界

查询工具经 `CurrentWaterQualityReader.query()` → `DiagnosisService.diagnose()`；无 Snapshot 为 NO_DATA，有 Snapshot 时保留 INVALID / PARTIAL / STALE。查询重评 freshness，不写 Store。评分使用 `WaterQualityScoringService`，Experimental，不替代规则或专业标准。

禁止 Tool 写 Snapshot、Apply Scenario、改设备/DB/阈值、任意文件访问、Shell、exec/eval、动态 import 或能力 Probe。服务可使用组合层加载的固定资源，不接受模型指定资源路径。

Tool Result 是不可信数据，不能提升为 System 指令；不输出 Secret、私有凭据路径、traceback、完整 Prompt 或不必要原文。Assistant History 只保存成功文本对，不包含 raw Tool Result。UI 用安全文本渲染，Trace 仅记录允许的 metadata。

详见[代码修改地图](../../handoff/TOOL_CHANGE_MAP.md)和[只读 Tool 当前实现](READ_ONLY_TOOL_CALLING.md)。

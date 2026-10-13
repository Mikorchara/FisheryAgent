# Assistant 有界多轮接入与交互设计

状态：2026-10-13，Phase 4C Qwen 六案例真实技术资格通过，用户已批准三 Preset 本地多轮试用。Prototype Flag 开启；Qwen 为 released，DeepSeek / Ollama 为 local_experimental（无真实多轮资格证据）。仅 OFF + Normal + 查询/Knowledge精确组合启用2/2/3，否则1/1/2；Analysis不变。当前操作与回滚见 §11，§7–§10保留各阶段当时状态。

依据当前 `assistant.py`、`tool_conversation.py`、`assistant_sources.py`、`execution.py`、`web.py`、`observability.py`、`resources/web/app.js` 及对应测试。[内部 Runtime](../tools/READ_ONLY_TOOL_CALLING.md)、[当前 Assistant 架构](../architecture/ASSISTANT_MODEL_V1_DESIGN.md)提供现有合同，本文件不替代它们。

## 1. 当前缺口与资格证据边界

下表是接入前的设计基线，非当前缺陷清单；阶段 A 收口见 §7，内部后端收口见 §8，Web 门禁与确认收口见 §9。该接入基线的资格与发布进展见 §11。

| 当前实现 | 接入缺口 |
| --- | --- |
| Coordinator 有固定 2/2/3、逐轮 auto/none、提前 Final、去重、共享 Executor 和有序 steps | 不需要重写循环；正式 AssistantService 构造器明确拒绝多轮 |
| Assistant.send 已从真实执行生成 Ledger，以 Ledger 检查 Requirement | 来源 gate 可复用；`source_receipt` 单项兼容投影在多个结果时会拒绝，不可取最后一项替代 |
| AssistantResult.to_dict 读取 `tool_result/tool_name/request_1/request_2` | 多轮会触发旧投影异常；必须改为从 steps 产生数组，不能只移除构造器门禁 |
| Prompt v2 写明“只选择一个 Tool，取得结果后直接回答” | 与多轮冲突；实验 Prompt 不等于正式 Prompt 的已验证多轮版本 |
| Web 每 Turn 冻结 Runtime/Credential/Policy，使用同一 RequestHandle | chat 固定构造单轮；bootstrap/确认文案未表达有效预算和发布范围 |
| RequestHandle 仅保存当前 phase；JS 每 350ms 轮询 | 很快的 Tool 会被漏过；只有 RUNNING_TOOL，不能区分第几步、开始/完成或是否真正进入 Handler |
| app.js Activity 为单对象，摘要固定“1 个 Tool”，运行详情固定 Request #1/#2 | 需通用 step 列表；JS 尚未映射 REQUEST_3，不能追加第二个固定显示槽位 |
| Adapter 每个请求重建 total timeout；取消 hook 已支持跨请求重绑 | 缺少整 Turn deadline；不得把每轮 timeout 当作整轮时间上限 |

目前 Qwen 3.8 Flash 的两个真实样本：low-oxygen（`0f1c8ffb43bb49918fc19c7d01d6522e`）走查询→知识→Final，3 次请求；normal（`bab05ccb92104f038fdeba4525d58c03`）查询后在 `auto` 下直接 Final，2 次请求。Result 传递、Ledger 和 Provider/normalized 检查均通过。

这些只支持**实验指令、空 History、查询+Knowledge 工具组合**的 smoke 结论：不证明正式 Prompt、多轮 History、评分组合或长期可靠性；低氧末轮 `none` 是强制收口。DeepSeek/Ollama 的单轮资格不授予多轮资格。Qwen 应作为首个接入候选，不能直接全量发布。

## 2. 推荐架构与 Feature Flag

```text
启动配置：flag（默认 false）+ 维护者多轮发布记录
    ↓ 根据固定 Preset identity / 发布范围 / 当前 Policy 决定有效模式
Assistant Request（浏览器不能选择 mode/budget/prompt）
    ↓ 冻结 Runtime、Credential、Policy、模式与 deadline
completed pairs → 原裁剪 → 原 History Projection → 模式对应的 System
    ↓ 同一个 ToolCallingService
Request #1 → Final 或 Tool A
    → 原 Executor → Result A → Request #2(auto)
        → Final 或 Tool B → Result B → Request #3(none) → Final
    ↓ steps → Ledger → 原 Requirement / 最终正文 / Trace / 取消提交门禁
仅成功提交一条 Assistant 回答及一对 History
    └─ 同一 steps 的安全投影 → 既有 status 轮询 / 最终 chat response
```

### 启用与发布范围

- 建议启动配置 `assistant_multi_round_enabled=False`，仿照已有 `assistant_history_projection` 从 `create_app/run_web` 传入；配置在 app/epoch 内固定，无用户 UI 开关、无 Web mode/budget 参数。
- 维护者记录多轮发布范围：preset_id、contract version、exact service/adapter/normalized URL/model、ProtocolSpec version、OFF+Normal、允许的工具组合、预算、Prompt variant version、资格依据。它是应用运行范围授权，不是 Managed Evidence，也不能由 `tool_calling=SUPPORTED` 自动推导。
- 第一候选仅 Qwen 查询+Knowledge 组合；记录先为 candidate，产品 Prompt/History 与预算确认的资格通过并获批准后才改为 released。评分、多 Provider、Thinking ON、Streaming 均不继承。
- 有效模式为 flag ∩ released 范围 ∩ 固定 Preset 支持 ∩ 当前授权工具组合。若范围未发布，**在发请求前**明确展示仍为 1/1/2；不隐藏已授权评分 Tool 来伪造已验证组合，不修改用户 Policy。未知配置或 identity/version 不匹配 fail closed。
- 进入 2/2/3 后任何失败都不能回退 1/1/2 重跑；回滚是关闭启动 flag 并重启，生成新 epoch，未提交历史不自动续接或 resend。保留原单轮实现及回归合同。

### Prompt、History 与来源

- 保留单轮 Prompt v2 原行为；未来多轮采用明确版本化的 Assistant v2 multi variant，仅替换单轮编排句：每轮一个相关 Tool，读结果后决定继续或 Final，信息足够时尽早结束，预算耗尽时说明未获得的来源。不能追加相互矛盾的 System，也不能复制实验中的固定“异常必检索”规则作为所有产品问题的规则。
- 来源分层、历史不可信、Tool Result 是数据、只读与疾病/用药限制全部保留；Tool description、Policy/Executor 和 Source Contract 不变。新 Prompt 需独立资格，不以实验成功代替。
- ContextBuilder 最小增加内部 Prompt variant 选择，完整 pair 裁剪与 B/A projection 不动；同一 epoch 不临时切换指令/投影。History 始终只保存成功 user/final assistant 文本对，不含 steps、Tool 协议、Ledger 或 Result。
- 每次真实执行保留独立 Receipt 和时间；使用现有 `requirement_satisfied_by_ledger`，不把两个时点合并为一个现场事实。不增加自动 Intent Router，Web 仍为 AUTO；AUTO 的成功正文不等于应用认证了所有来源声明。

### Deadline 与 Stop

产品启用前建议补齐整 Turn 时间上限；初始可沿用该 Runtime 的 total_timeout_s 作为多轮 Turn cap，准确值由维护配置/验收确定，不简单乘以三。时钟从执行 claim/start 后、上下文与模型工作开始前使用 monotonic 捕获；不从 prepared handle 创建时间计费，也不由浏览器指定。

同一 RequestHandle 保存可选 deadline，默认单轮不改。Coordinator 在模型/Tool 前后及提交前检查；Adapter 每次采用 `min(原请求 timeout, Turn 剩余时间)` 限制 SDK 和 Async bridge，不能仅在返回后检查。冻结 Runtime/Credential 不改写，只传递执行范围剩余时间。

复用原取消 hook，跨模型请求解绑/重绑；用户 Stop 始终为 USER_CANCELLED，deadline 为 TOTAL_TIMEOUT/失败，不能调用用户 cancel 后把 timeout 误标为取消。现有 bridge 的 consumer cleanup 路径也需审查这一差异。同步本地 Handler 无法强行抢占：执行后过期即拒绝继续/提交，不能声称瞬时中止 Python Handler。Cleanup 可有有限 grace，但不得再开始新请求；远端计算/计费是否停止仍 UNKNOWN。

## 3. Web API 与安全 Activity 合同

保留同步 `POST /api/assistant/chat`、prepare/cancel API 与现有 `POST /api/requests/<id>/status`。**轮询足够，无需现在新增 SSE、任务服务或后台 worker。**改为累积安全快照，轮询漏过开始瞬间也能恢复已完成步骤。

建议 bootstrap 为每个 Preset 返回有效模式、预算及非敏感 `execution_profile_revision`；确认文案从其 max requests 生成。chat 只增加该 revision 的一致性检查，不接受客户端要求的预算/模式。若另一标签页改变 Policy 或发布配置使预算变化，在联网前拒绝、刷新计划并重新确认，不能在“最多两次”的旧确认下发送第三次请求。

实施选择：单轮与多轮统一要求匹配的 revision，旧页面缺少 revision 也会联网前拒绝并要求刷新重新确认；不保留绕过确认的一套旧 Web 合同。Assistant 后端内部调用仍保持原合同。不能因客户端省略该字段自动放宽到三次请求。

status / 最终 result 共用同一安全投影器，推荐结构：

```text
activity_schema_version: 2
request_id, revision, state, phase, current_step_seq
execution_mode, budget: {tool_calls, tool_rounds, model_requests}
counts: {model_requests_started, tool_attempts, tools_executed}
steps: [
  {seq, kind:model, request_index, state, outcome, safe_error_code,
   finish_reason, usage},
  {seq, kind:tool, model_request_index, tool_round, tool_name,
   display_name, state, handler_started, result_status, duration_ms,
   safe_error_code, quality?, freshness?, observed_at?, evaluated_at?,
   evidence_count?, experimental?}
]
total_latency_ms, aggregate_usage
```

- 所有字段由服务端 allowlist 生成；不传 raw arguments、query、raw Result、Evidence 正文、Prompt、Reasoning、Credential/path/headers 或模型提供的标签。名称/说明来自 Registry/Catalog，时间/质量/命中摘要来自实际 Result/Receipt；不直接 `asdict` 内部 steps 或公开 Ledger 全对象。
- 数组是有序 steps 的投影，预算最多 5 steps；revision 单调递增。RequestHandle 可缓存有限安全快照，不另存 Tool payload/Receipt 真相；最终响应重新投影相同执行序列，不能拼出另一套可写结果。
- Coordinator 在 step 追加、模型返回、Tool 返回与终止时发布更新。现有 RUNNING_TOOL 在 Executor 校验前：只代表调用尝试。若 UI 要统计“真正执行”，需 Executor 增加默认无副作用的内部 observer，在权限/参数/取消检查通过、进入固定 Handler 时通知；不移动或放宽校验。拒绝调用显示 Rejected，不能算已执行。
- 未完成 step 在终止时标为 Cancelled/Failed；成功 Tool 为 Completed，具体 NO_DATA/NO_MATCH/NOT_SCORABLE 是业务 Result status，不伪装成 ERROR。已有完成步骤不因下一步失败消失，也不授予失败 Turn 成功提交。
- 单轮最终响应可保留旧单 Tool/request_1/request_2 派生字段；多轮标记 legacy projection 不可用，不取最后一个 Tool 填旧槽。新前端统一消费数组；薄旧数据→数组兼容仅在 schema v1 时使用。
- 运行态快照只说明执行，不决定 successful_turn；status 的 Completed 不代替 chat 最终正文与 Commit Gate。当前 Assistant 在最终 Trace 前调用 handle.finish，后续 Trace 失败仍可能改为失败；接入时需收口 Finalizing→最终门禁/Trace→终态发布顺序，不能让轮询抢先提交聊天回答。

## 4. 通用 UI 与交互

沿用现有顶栏、Preset selector、OFF · Normal、Tool Manager、输入框与 Send/Stop。不新增多轮开关，不增加第二个固定 Tool 槽。

```text
Assistant Model       [Qwen 3.8 Flash ▼]  OFF · Normal  [Tool]

用户：现在水质怎么样？如有异常请说明相关知识。
  本次运行：Request #2 · Qwen · 已执行 1 Tool · 2 Requests ▸
  [展开]
    #1 模型请求       已完成 · tool_calls
    #2 当前水质查询   已完成 · OK · Fresh · 数据时间…
    #3 模型请求       运行中
    （只添加实际开始的步骤，不预造 Tool B）

Assistant：仅最终成功后出现一条自然语言正文。
  使用了 2 个 Tool ▸
    当前水质查询 · OK · Fresh · evaluated_at… · duration…
    项目知识检索 · OK · 3 条命中 · duration…

本次运行：Completed · Qwen · 2 Tools · 3 Requests · 3.9s ▸
[输入框]  [Send] [Stop]       REAL NETWORK REQUEST：最多 3 次
```

- 输入附近运行条逐步更新；折叠显示当前 phase / 实际计数，展开按 seq 显示轻量模型与 Tool 步骤。最终回答下面只列实际 Tool Activity，详细 Request/Usage 在“本次运行”中，完整开发 Trace 仍仅 Development/Test。
- 提前 Final：立即结束，仅显示实际 1 或 3 个 steps，没有“未执行第二 Tool”的空占位。无 Tool 显示“未调用 Tool”。一个 Turn 一条最终回答，中间 assistant 正文、Tool 调用意图和模型重规划文本不渲染为答案。
- Failed/Cancelled/Timeout：保留已执行步骤，显示安全状态卡，不添加成功 assistant 文本或 completed pair；未开始后续请求不显示为已发送。NO_DATA 与检索无命中如实展示，Knowledge 不标为实时观测；评分未来获多轮发布后仍标 Experimental。
- 前端按 request_id + pendingRequest + epoch 接收更新，忽略旧 revision、迟到响应和旧 epoch；所有文本继续 textContent，未知字段丢弃。轮询只提供约 350ms 加网络延迟的观察，不保证看见每个运行中瞬间；短步骤从累积快照恢复。观察失败保留旧快照、提示进度暂不可用，不作为模型失败或自动 resend 的理由。Stop 后保持取消中直至安全确认，不让随后 polling/chat 覆盖取消状态；取消时尽量从原 status 取得最终安全步骤。
- 完成或停止后才能切工作区、Clear 或切模型；沿用当前 Analysis/Assistant 状态隔离。Clear 只清 Assistant Session。模型切换确认后清 History；app 重启/回滚 epoch 变化清 completed history、保留 draft，重新 bootstrap，不自动 resend。页面刷新不保证服务端请求取消，也不能凭 Abort 声称远端停止；沿用显式 Stop。
- 为未来 Streaming 保留相同 turn/request/step 标识及状态；将来 delta 只属于 pending model step，最终提交仍独立。本阶段不提供 delta、不实现 assembler/SSE/Streaming Tool。

## 5. 最小实施阶段与模块地图

| 阶段 | 最小修改范围 | 完成标准 |
| --- | --- | --- |
| A：安全投影和进度，flag 仍关闭 | assistant.to_dict、execution 快照、Coordinator/Executor 可选 observer、observability、Web status、app.js 通用数组 | 默认 1/1/2 parity；快速完成步骤不丢；尝试≠实际执行；无敏感输出 |
| B：内部 Assistant 接入，尚不发布 | AssistantService 显式模式校验、ContextBuilder Prompt variant、启动配置与发布 allowlist、bootstrap/revision/网络预算、整 Turn deadline/Adapter 时间裁剪 | 离线 2/2/3、Ledger gate、单条 Final、History 不变量、取消/timeout/Trace 终态一致 |
| C：候选资格及小范围启用 | qualification 开发边界验证正式 multi Prompt / History / 有效工具组合，再批准 Qwen released | 分别复核低氧继续、正常/DO 提前结束、概念直答、历史追问；本阶段另获真实请求授权 |
| D：后续独立工作 | 其他工具组合/模型资格或 Streaming transport | 不由 Qwen smoke、单轮支持或通用数组自动授予 |

不重写 Tool Loop，不改 Analysis/RAG/Knowledge Handler，不建新 Agent、任务队列、DB Session、intent router、自动 retry 或并行执行。正式应用依旧不依赖 development/qualification；资格报告是维护者发布依据，不是运行时读取的授权源。

## 6. 风险、测试与验收

优先风险：旧投影触发序列化失败；Prompt 单/多轮冲突；未验证工具组合被扩大；phase 覆盖导致遗漏；授权失败被误计实际执行；整 Turn timeout 被误标用户取消；Trace/取消/最终提交竞态；多个观测被混为当前事实。

离线测试至少包括：

- flag off 的 Assistant/Analysis/Web 1/1/2 parity；eligible/ineligible Preset、contract/identity/工具组合失配；Web 不能覆盖模式、预算、Prompt；旧确认 revision 不能扩大联网次数。
- direct Final、Tool→Final、Tool A→B→Final；结果确实进入下一请求、无预执行；重复逻辑请求、同轮多个 calls、第三轮调用和第四次请求均拒绝。
- NO_DATA/NO_MATCH/PARTIAL/NOT_SCORABLE/INVALID/STALE 的 Receipt 不变；逐执行时间隔离；后一步失败保留 Ledger但不提交；AUTO 与非 AUTO 门禁原样；缺失 Usage 不补零。
- 模型/Tool 各边界 Stop、SDK cleanup、deadline 在请求中真正终止本机 I/O、用户取消与 TOTAL_TIMEOUT 区分、Finalizing/Trace 失败和迟到成功不提交；不声称远端停止。
- polling 一次越过多个步骤仍恢复完整列表；revision 乱序、预检拒绝、短 Handler、提前 Final、终止步骤、单轮兼容；脱敏/HTML 安全；History/Clear/模型切换/epoch/Analysis 状态不回归。

实现阶段先 targeted，稳定后 FULL PRODUCT + Browser，qualification 合同变更时加离线 FULL QUALIFICATION；语法、链接、diff 与敏感检查。人工验收只在单独授权后使用正式 multi Prompt 和实际预算确认，核对一个 Turn 一条回答、即时 Stop、每个 Tool 时间/状态与真实日志一致。

Web 发布门禁现已接入但默认关闭。不能仅凭这两个实验样本直接开放多轮；正式多轮 Prompt 资格与维护者发布范围仍需审核。本阶段未执行真实请求。

## 7. 阶段 A 实施结果

- 新增 `assistant_activity.py`：以 Runtime steps 为唯一执行真相，统一生成最终响应、Trace 与 status 的 schema v2 安全投影。RequestHandle 缓存的是脱敏元数据快照，revision 单调递增，快步骤不会因轮询漏看而丢失。
- Coordinator 可选 steps observer 与 Executor Handler-entry observer 复用原执行栈；新增 request_started / handler_started 观测标记。尝试、授权拒绝与真正执行明确区分，执行权限和调用预算不变。
- 前端使用通用有序 Model / Tool 列表；只添加实际步骤。保留单轮旧响应兼容，支持未来五步数据的离线渲染，不开放多轮请求。运行失败/取消保留步骤，迟到/旧 revision/错误 request id 不覆盖当前执行。
- Assistant 在 FINALIZING 后将 Trace 写入与取消提交串行化，再发布终态；Trace 失败不能发布成功。轮询 Completed 仅等待最终 gated chat 响应，不提交 History。一轮仍只有一条成功最终回答。
- Prompt、History Projection、Source/Receipt/Ledger/Commit Gate 判定、Analysis、Provider、Handler 与 Policy 权限不变。正式 Assistant 的 multi-round gate 仍关闭，保持 1/1/2；未新增启用开关、deadline、SSE 或 Streaming。
- FULL PRODUCT 首轮暴露 Phase 3 既有测试清单遗漏：独立 `development/qualification/multi_round_qualification.py` composition root 未列入 KnowledgeService 构造位置测试。仅补充该明确路径，仍锁定每个 root 一次构建及 Web 单实例共享，无 Knowledge 行为修改。

离线验证：受影响 Python targeted 254 项通过；FAST 149 项通过；FULL PRODUCT 901 项通过；Browser 196 项通过；额外 FULL QUALIFICATION 116 项完成（1 项既有条件跳过）。新 Activity 合同覆盖 19 项 Python / Web 测试及 8 项 Browser 测试。Markdown 本地链接、Python / JS 语法、diff 与改动文本敏感模式检查通过。未执行真实 Provider 请求。

## 8. Phase 4B-1 内部后端实施记录

- 复用同一个 `ToolCallingService.run_request`，没有第二套循环。构造器默认仍为 SINGLE_ROUND，协调器与 `AssistantService` 必须同时显式选择 `ToolExecutionMode.BOUNDED_MULTI_ROUND`；预算由协调器固定为 2 calls / 2 rounds / 3 requests。仅增加协调器而未显式配置 Assistant 仍拒绝。
- 多轮 Prompt 版本为 `ASSISTANT_BOUNDED_MULTI_ROUND@1`。原 `SYSTEM_INSTRUCTION` 文本不变；新版本只替换单轮规划句，允许依据真实结果继续选择或提前 Final。来源、数据非指令、疾病/药物边界与纯文本原则全部保留。安全 Assistant Trace 记录版本标识，不记录 Prompt。
- 同一 Turn 继续冻结 Runtime/Credential/Policy，复用同一个 Executor。有序 steps 是执行真相；每个返回结果保留独立 Receipt。Ledger gate 检查全部实际来源，失败/取消不提交。两个 Tool 时旧 `request_1/request_2/tool_activity` 投影为空且不可用，不能把最后一个 Tool 当作唯一来源；公开 Activity 只包含 allowlist 摘要。
- 原完整 pair 裁剪与 History Projection 不变；一轮只提交一个成功 user/final assistant pair，Tool protocol、Ledger、失败或中间文本不进入后续 History。Web 没有 mode/budget/Prompt/deadline 输入，未改启动配置、bootstrap 或网络确认预算；Analysis 仍固定单轮。

内部配置示意（不是 Web 开关，也不授予 Provider 真实资格）：

```python
mode = ToolExecutionMode.BOUNDED_MULTI_ROUND
coordinator = ToolCallingService(gateway, registry, traces,
    policy=frozen_assistant_policy, execution_mode=mode)
service = AssistantService(coordinator, execution_mode=mode, turn_timeout_s=60)
result = service.send(request, frozen_runtime)
```

### 整 Turn deadline 与终态

- 从 `send` 执行开始计时，覆盖身份校验、Context/History、模型、Tool、来源门禁及最终 Trace。默认总预算为冻结 Runtime 的 `total_timeout_s`，内部 `turn_timeout_s` 只能收紧，不能把三次请求分别算成三个总预算；准备 request 的等待时间不计入。复用原 RequestHandle；无外部 handle 的内部调用也会建立相同 scope。
- Adapter 将 SDK/异步操作 timeout 限制到同一绝对截止时间。模型请求之间不续期；正常 Provider 错误保留 HTTP 等安全码，截止时间耗尽为 `TOTAL_TIMEOUT`，用户 Stop 为 `USER_CANCELLED`（Stop 已发生时优先）。超时清理只 abort I/O，不设置用户取消标志；最多 5 秒已有 SDK 清理宽限不增加生成预算，不能证明远端计算/计费停止。
- 同步只读 Handler 与同步文件 Trace 写入不能强制抢占；检查前后边界与最终提交，逾期不发后续请求、不返回成功正文。若 Assistant Trace 写入跨越截止时间，追加同 id 的失败终态修正，最后的 `assistant_turn` 为提交结果；若修正写入也失败，`trace_recorded=false` 且仍返回失败。此前 Coordinator Trace 是执行记录，不能当作最终成功提交凭证。
- 取消、来源要求不满足、模型/Tool 错误、Trace 失败、超时均保留已完成 steps/Receipt/Usage 供审计，不提交成功 History，不自动重试、补 Tool 或切换模式。

离线验证：新增 20 项内部 Assistant 测试与 5 项执行安全测试；主要 targeted 83 项通过，Assistant 分组 140 项、Tool 分组 268 项通过；FAST 149 项通过；FULL PRODUCT 926 项通过（32.6 秒）；FULL QUALIFICATION 116 项完成（115 通过、1 项既有目录 symlink 环境条件跳过）；Browser 196 项通过。覆盖 direct Final、Tool 后提前 Final、完整两轮及真实结果传递、独立 Ledger、单次最终提交、History、去重/轮次限制、Provider/Tool/Trace 错误、取消和 deadline。147 个 Python 文件 AST、JS 语法、286 条 Markdown 本地文件链接、diff 与改动文本敏感模式检查通过；核对原单轮 System Prompt 与 HEAD 文本完全一致。未执行真实 Provider，未 commit/push。

4B-1 完成时的剩余集成项：exact 发布范围、正式 Prompt+History 的真实资格、启动 flag/epoch、联网确认 revision。4B-2 已接入后三项的运行门禁与预算确认，真实资格和正式发布仍未批准，见下节；不扩大 Qwen/DeepSeek/Ollama 的已发布能力。

## 9. Phase 4B-2 Web 接入记录

### 发布范围与有效执行模式

新增产品模块 `assistant_execution.py`，只负责启动配置、精确范围匹配和确认 revision，没有 Tool Loop 或 qualification 开发依赖。固定资源 `resources/profiles/assistant_execution.json` 在 `create_app` 时加载为不可变配置，同一 epoch 不热切换。内部构造参数可注入类型明确的配置用于离线测试，浏览器不能配置路径、Flag、mode、budget、deadline 或 Prompt。

配置当前只有 `qwen38-water-knowledge-multi-v1` **candidate**，`multi_round_enabled=false`。它绑定：

- Qwen Preset `dashscope-qwen38-flash-r1`，OFF Variant，contract `1.0.2`；exact identity 为 dashscope / openai_chat / `https://dashscope.aliyuncs.com/compatible-mode/v1` / `qwen3.8-flash`。
- 完整 ProtocolSpec（含 id/version/编码字段）、`ASSISTANT_BOUNDED_MULTI_ROUND@1` 及指令指纹、History 投影 id/version。
- 实际可执行的 Tool definitions **精确集合**：查询 + Knowledge，以及名称、description、Schema 的整体指纹。多选评分、少选一个或改了 Schema 都不匹配；不为匹配范围自动修改 Policy。
- released 必须显式具有资格记录 id 和带时区的验证时间。这是维护者审批记录，不是运行时自动读取 Evidence 或实验结果。

只有 Flag 开启且全部 scope 与 **released** 记录相等，才构造同一个 `ToolCallingService` / `AssistantService` 的 2/2/3 模式。未匹配范围继续显示并执行 1/1/2；损坏配置启动时安全失败。当前真实配置没有任何 released 多轮范围，`presets.json` 和原 Tool capability 合同未改。

### Bootstrap、确认与冻结

每个 bootstrap Preset 增加 `execution_profile={mode,max_model_requests,revision}`；不公开完整发布 scope、Prompt 或连接细节。revision 绑定 epoch、启动配置、精确 scope、当前 Assistant Policy、实际 System 与 Runtime 偏好/超时。chat 回传确认 revision；缺失/失配为 `ASSISTANT_EXECUTION_PROFILE_CHANGED`，epoch 失配仍为 `ASSISTANT_SESSION_EXPIRED`，两者都在凭据解析和 Gateway I/O 前拒绝。

前端确认文案根据选中 Preset 显示最多两次或三次请求。成功保存/恢复 Tool Policy 后刷新 bootstrap、清除旧勾选；其他标签页改变 Policy 时服务端拒绝旧确认，UI 刷新预算并保留输入/成功历史，要求重新确认，不自动 resend。应用重启沿用原 epoch 清理语义。已接受的 Turn 使用同一冻结 Runtime、CredentialSnapshot、Policy、Executor 和 RequestHandle，后续 Policy 修改只影响下一 Turn。

### 执行与通用 UI

没有改执行循环、Prompt、Handler、Source Contract 或 Analysis。Web 使用已有整 Turn deadline、Ledger、Commit Gate 和 safe Activity；status 与最终结果投影同一组 steps。完整两轮只产生 Model #1 → Tool A → Model #2 → Tool B → Model #3 五步；提前 Final 只展示实际步骤。一轮只提交一条最终回答及一个成功文本 pair；失败/取消/超时/Trace 失败不提交。多结果不能套用单 Tool 兼容槽位，现有 UI 已读取通用数组。

离线 Web fixture 通过实际 Flask `/api/assistant/chat` 发起双 Tool Turn，使用临时 Store、虚构 Credential 和 Scripted Gateway；核对 Result A 进入 Request #2、两项结果进入 Request #3、末轮 `none`、五步累积状态及冻结 Runtime。Browser 再把这些真实安全 HTTP 结果/轮询快照送入原 UI，验证 Request #3、两个 Tool 和单次最终 History 提交。不是仅用手写的未来 UI fixture，也不是真实模型资格证据。

### 下一阶段资格与手动启用

1. 先单独批准有限真实 Qwen qualification，覆盖候选 scope 的**正式多轮 Prompt、正式 History Projection、实际两 Tool 定义**，至少验证低氧两 Tool、正常提前 Final、知识概念直接 Final；若要发布带 History 的范围，需补相应当前追问/历史解释样本。保留真实步骤、Ledger/Usage、预算、取消与 safe report；不把 scripted 结果当真实资格。
2. 不带 `--assistant-product` 的 `scripts/qualification/qualify_multi_round.py` 保留独立实验指令，两个既有 smoke 只能作参考，不能据此发布当前正式 Prompt。4B-2 当时未修改 Harness；4C 已复用同一入口加入正式 product-scope qualification，见 §10。均未执行新的真实请求。
3. 资格通过且维护者明确批准后，核对冻结 scope 与验证配置完全一致，填写 `qualification_id` / `validated_at`，将 candidate 改为 released，再将 `multi_round_enabled` 改为 true；完整重启 Web。在既有 Assistant Tool Manager 手动选择查询+Knowledge，bootstrap 应显示最多三次请求，再重新勾选确认。无需修改 Preset capability 或 Credential，不自动更改用户 Policy。
4. 回滚只需设 Flag=false 并完整重启；新 epoch 使旧 Session/确认失效，页面回到两请求预算。失败不自动切回单轮、不补跑、不 failover。关闭 Flag 后可保留 released 维护记录。

离线验证：相关 Python targeted **195 项通过**（新增发布/确认/Web 集成测试 18 项）；FAST **149 项通过**；FULL PRODUCT **944 项通过**（34.8 秒）；FULL QUALIFICATION **116 项完成**（115 通过、1 项既有目录 symlink 环境条件跳过）；Browser **201 项通过**（新增 5 项，含实际 Flask 双 Tool response/status → 原 UI 的离线端到端验证）。覆盖启动冻结/回滚、candidate 不发布、精确范围/版本/Schema 失配、Policy 修改与重新确认、未经授权 Tool/并行 calls/第四次请求拒绝、每次 Request Stop、整 Turn timeout、Trace 失败以及单轮/Analysis/History 回归。149 个 Python 文件 AST、JS 语法、288 条 Markdown 本地文件链接、diff 与 14 个改动文本路径敏感模式检查通过；Git 未跟踪凭据或 outputs。未运行真实 Provider，未改正式 Preset 合同或用户 Policy，未 commit/push。

## 10. Phase 4C 正式 Assistant 资格准备

**准备阶段当时：REAL PROVIDER RESULTS: NOT RUN。** 后续六份真实报告与本地发布见 §11；本节只准备 Qwen 3.8 Flash / OFF / Normal / 查询+Knowledge 的逐案例取证，不发布候选范围。

### 最小复用与安全边界

同一 `scripts/qualification/qualify_multi_round.py` 新增 `--assistant-product` 模式；开发实现仍在 `multi_round_qualification.py`。没有新 runner、manifest 矩阵或执行循环。旧实验默认路径和报告版本保留，新版本为 `assistant-product-multi-round@1`，不能将旧 smoke 混作正式 Prompt 证据。

正式模式直接构造 `AssistantRequest` → `AssistantService(BOUNDED_MULTI_ROUND)` → 原 `ToolCallingService` / Registry / Executor：使用未修改的 `ASSISTANT_BOUNDED_MULTI_ROUND@1`、原完整 pair 裁剪和 `UNTRUSTED_TRANSCRIPT_V1@1`。每次发送前核对 System 精确文本；每个案例检查当前 Qwen maintainer scope（Identity、contract、完整 ProtocolSpec、Prompt / History 版本及两 Tool 定义指纹）。失配时停止，不改 Scope 或恢复旧实验指令。

隔离的 Store 每次建立一份合成 Snapshot（温度28℃、pH7.5、DO见下表），固定 query clock，不读取 Web Snapshot、Scenario 或用户历史。历史都是固定合成文本。局部 `ToolPolicy` 只授权两 Tool，不读取/修改用户 Policy；资格内部显式 2/2/3 不通过 Web，因此不绕过或修改 Web candidate 门禁。正式 Credential composition、冻结 Runtime / CredentialSnapshot、retry=0、单一 RequestHandle、整 Turn deadline、Ledger、提交与 Trace 合同全部复用。

### 案例、标准与预算

建议每次只批准表中 **1 个 case × 1 run**，取到报告后停止审阅，再批准下一项。六项均批准时理论上限18模型请求、每请求最多256输出 tokens；预期路径合计11请求。没有本轮真实授权，也没有自动批次或补跑。

| 建议顺序 / case | 合成场景与问题 | 预期实际 Tool 顺序 / 请求数 | 确定性来源标准 |
| --- | --- | --- | --- |
| 1 `low-oxygen` | DO2.2；“请查询当前水质，若有异常再检索相关项目知识，最后简短说明。” | 查询→模型看到异常后选择Knowledge→Final / 3 | 当前查询完成 + 项目搜索完成 |
| 2 `normal` | DO6.4；与低氧相同问题 | 查询→在 `auto` 下提前Final / 2 | 当前查询完成；不得为对称而预执行Knowledge |
| 3 `current-do` | DO6.4；“现在溶氧是多少？请查询后直接简短回答，不需要检索知识。” | 查询→Final / 2 | 当前查询完成 |
| 4 `concept` | “什么是溶氧？请用一两句话解释这个概念，不需要当前现场数据。” | 无Tool直接Final / 1 | AUTO；无本轮Receipt也可成功 |
| 5 `history-current` | 旧DO2.2→旧NO_DATA；新Snapshot为DO6.4；“那现在溶氧是多少？…” | 本轮重新查询→Final / 2 | 新查询Receipt；历史文字不能产生来源 |
| 6 `history-explanation` | 旧DO2.2；“刚才2.2 mg/L是什么意思？请解释旧值，不需要当前现场数据。” | 无Tool直接Final / 1 | AUTO；允许历史解释，记录不必要查询为路径失配 |

**每个案例的真实 Runtime cap 都是 2 calls / 2 rounds / 3 requests**，不会按预期1/2请求提前把 `tool_choice` 改为 none，也不会为概念题强行屏蔽 Tool 执行。不必要 Tool 或未提前 Final 是实际观测结果，判为该案例路径不符合，不自动纠正或重试。首轮没有 Tool 也不补发；一轮多个调用、未授权评分、非法参数、重复查询、第三个 Tool/第四次请求仍按硬合同拒绝。

技术检查需要：精确 Identity / returned model 一致、Provider 原始与 normalized 调用/元数据一致、Tool 权限与参数合法、实际结果带同 call id 进入下一请求、预期 Tool 顺序、完整最终 stop 正文、Ledger 来源要求、Product Commit Gate / Trace / deadline / Cancellation 都通过。每次实际执行保留独立 Receipt 和时间，不合并水质与知识为一个当前现场事实。

资格 scripted request 使用既有内部 SourceRequirement 检查当前查询或 AUTO，低氧另外通过同一 Ledger 满足函数检查 Knowledge 操作；这没有改变普通 Web 的 AUTO 或新增自然语言路由。`product_commit_gate_passed` 与资格技术 verdict 分开：例如低氧查询后直接 Final 可通过查询 Gate，但仍因缺少项目搜索而不符合本案例。NO_MATCH 证明搜索完成，不认证证据命中；NO_DATA 同样不认证有效观测。技术步骤通过不等于回答真实、相关或安全。

### 安全报告与人工质量检查

JSON 固定写到 `outputs/assistant-qualification/<run_id>.json`，独占创建、不覆盖旧报告。记录 case/plan hash、精确 scope、实际 Request/tool_choice、Provider/normalized 安全摘要、Steps、实际执行与 Result 状态/传递布尔、Ledger、Requirements、Usage、请求/attempt数量、最终 finish 和安全错误。记录 History 收到/保留/裁剪数量，不记录历史原文；不保存回答正文、System、query、Tool payload、Credential、Authorization 或私有路径。

`success/technical_success=true` 只代表技术标准通过，仍为 `qualification_verdict=PENDING_MANUAL_REVIEW`、`release_eligible=false`。离线注入明确标记 `offline_fixture`、actual_network_requests=0，不作为 Provider 证据。真实错误/未查询/错误 Tool/路径不符/截断都保留为结果，不补跑。

可选 `--review-answer` 仅在终端 stderr 预览 Assistant Gate 后的完整最终正文：复用 Assistant Secret 脱敏，过滤终端控制字符，JSON stdout 与安全文件没有正文。预览标记 PREVIEWED_NOT_APPROVED；不自动判断语言质量或发布。不要开启 PowerShell transcript、重定向该预览或截图记录秘密。失败/取消/截断不预览部分正文；报告中的 `final_answer_present` 不代替人工检查。

人工核对：

- 低氧按本轮DO2.2与确定性状态回答，项目知识只作背景，不能据此诊断现场疾病或给出药物/剂量；检索未命中时诚实说明。
- 正常和单DO查询没有多余检索，正确说明当前查询不等于新采样。
- 当前追问使用新DO6.4，不能复用旧2.2或旧NO_DATA；历史解释明确旧值，不伪称本轮已查询。
- 概念直答不编造“已查询/检索/评分”；最终正文简洁纯文本，无 Raw JSON、Prompt、工具内部指令或敏感信息。

只有对应真实报告技术通过 **且** 用户完成质量/安全审阅，才可讨论该精确范围的 maintainer 发布。一次/案例是有限 smoke，不证明长期可靠性；长History、评分、多Provider、Thinking ON、Streaming不获资格。

### 手动 PowerShell 命令

在项目根目录使用已安装项目的 venv。先只 dry-run；`--case` 可选择表中六项，每个进程只处理一个：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_multi_round.py --assistant-product --case low-oxygen --dry-run
```

**以下只在用户明确批准该 case 一次真实 run 后使用**；其他 case 须分别批准、分别替换 case，不能粘成批次：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_multi_round.py --assistant-product --case low-oxygen --confirm-network --review-answer
```

默认每请求256 tokens，可通过 `--max-output-tokens` 收紧，不能超过256。核对 dry-run 的 case、plan_sha256、scope 后再确认；代码/计划变动必须重新审阅授权。遇到凭据文件错误立即停止：保留0-request报告，不改ACL、不复制Key、不读源码 `.env`，由用户正常PowerShell处理正式Credential路径。任何真实结果产生后停止，不自动启动下一项、重试或 failover。

准备阶段离线验证：相关 targeted **137 项通过**；FAST **149 项通过**；FULL QUALIFICATION **134 项完成**（133 通过，1 项既有目录 symlink 环境条件跳过）。本入口保留原 23 项测试，新增 18 项正式产品资格测试；覆盖正式 Prompt / History parity、结果传递、提前 Final、来源与提交门禁、权限/预算、取消/整 Turn deadline、Trace 失败、脱敏预览及旧实验兼容。149 个 Python 文件 AST、现有 JS 语法、290 条 Markdown 本地文件链接、diff check 和 18 个改动文本路径敏感模式扫描通过；Git 未跟踪凭据或 outputs。实际 CLI dry-run 返回正式 Prompt、精确 Qwen scope、candidate、3 请求上限和0网络请求。本轮没有修改产品/UI执行路径，未重复无关 FULL PRODUCT / Browser；其既有 4B-2 结果见 §9。Web Flag 仍为 false，Qwen仍为 candidate；没有真实Provider请求，没有 commit/push。



## 11. Phase 4C 三预设本地试用发布

2026-10-13 用户明确批准本地 Prototype 三模型试用；本轮没有 Provider / Ollama 请求。包内 `multi_round_enabled=true`，不影响 `D:\Fishery_Project` 或 Analysis；类构造的安全默认值仍是 false，未登记范围不能凭 Flag 获得多轮。

| Preset / exact model | 发布状态 | 本轮资格依据 |
| --- | --- | --- |
| `dashscope-qwen38-flash-r1` / `qwen3.8-flash` | `released` | 六案例真实技术资格通过，用户批准本地发布 |
| `deepseek-flash-r1` / `deepseek-flash` | `local_experimental` | 用户明确批准未验证的本地实验；qualification_id / validated_at 均 null |
| `ollama-qwen35-4b-r1` / `qwen3.5:4b` | `local_experimental` | 用户明确批准未验证的本地实验；qualification_id / validated_at 均 null |

三份 Scope 分别由各自当前正式 Preset生成：service/adapter/normalized URL/exact model、contract 1.0.2、完整ProtocolSpec、OFF/Normal、`ASSISTANT_BOUNDED_MULTI_ROUND@1` 及指纹、`UNTRUSTED_TRANSCRIPT_V1@1`、查询+Knowledge两项实际Tool definitions指纹。两个实验模型不能继承Qwen的资格；实验记录如果含资格编号或验证时间，加载时安全拒绝。未修改 `presets.json`、Provider Capability 或正式凭据。

Qwen维护记录 `phase4c-qwen38-six-cases-20261013` 对应以下现存安全报告（`outputs/assistant-qualification/`，Git ignored）：

- low-oxygen：e54054aba9204d78bad4cb1c4e6c8b8b，查询→Knowledge→Final，3请求。
- normal：647df8796458484396f1692fd9daeb48，查询→提前Final，2请求。
- current-do：a412202b64cf490f9d057a9627b6df21，查询→Final，2请求。
- concept：b32a45baae2d45fd841974259ef666cc，直接Final，1请求。
- history-current：37d49ded924d41ba93ef17edaa9fe9fa，本轮重新查询→Final，2请求。
- history-explanation：264c1d1f00624bf79eee62dca8a53f40，历史解释直接Final，1请求。

合计6runs/11真实请求，Provider归一化一致、Result传递、Ledger、Requirement、Commit Gate及Trace全部通过，最终stop；最后报告完成时间作为validated_at。它们仍保留当时 `PREVIEWED_NOT_APPROVED` 的原记录，不回写报告或伪造人工内容结论。发布是后续用户维护者决策；有限技术样本不认证回答全部真实、检索相关性或长期稳定性。

### Web 使用与回滚

1. 在项目根目录运行 `.\.venv\Scripts\python.exe -m fishery_ai web`，浏览器打开 `http://127.0.0.1:8765`。已启动Web需完整重启以加载发布配置和新epoch。
2. Analysis Apply低氧场景，切到Assistant选择三个Preset之一；Tool按钮→Assistant标签，仅选 `get_current_water_quality` 与 `search_fishery_knowledge`，取消评分。保存才更新Policy；程序不代用户改设置。
3. UI应显示有界多轮2/2/3；Qwen显示“已验证资格”，另外两个显示“本地实验试用 · 尚无真实多轮资格证据”。Cloud确认最多三次真实请求；Ollama为最多三次本地模型请求，不是Mock。
4. 手工勾选本次确认并提问：“请查询当前水质，若有异常再检索相关项目知识，最后简短说明。” Steps可出现Model→查询→Model→Knowledge→Model。模型也可提前Final；试用不强制双Tool，不预执行，不补跑。
5. 少选Tool、多选评分、身份/协议/Prompt/History/Tool指纹失配时显示单轮和原因。配置/Policy变化导致revision失配时，联网前拒绝、刷新预算、取消旧确认；不能沿用旧勾选强行执行。
6. 回滚：编辑 `src/fishery_ai/resources/profiles/assistant_execution.json`，仅把 `multi_round_enabled` 改为 false，完整重启Web。保留三份发布记录；新epoch拒绝旧Session，新请求均显示1/1/2。无需改Policy、Preset或Credential。

共用原AssistantService / ToolCallingService / RequestHandle / Steps；每轮最多一个Tool、最多2calls/2rounds/3requests，整Turn deadline、Stop、Ledger、来源门禁和成功文本pair History保持。真正执行失败、取消或超时不切回单轮、不重试、不failover。Web不能提交release_status、mode、预算、deadline或Prompt。正式Web仍AUTO来源要求，允许模型自由选择，不是自然语言强路由。

### 离线验证

离线 targeted 228项通过（Web/qualification 65项，Assistant/Tool 163项），Security执行14项通过；FAST149项通过；FULL PRODUCT950项通过；Browser203项通过；FULL QUALIFICATION134项完成（133通过，1项既有目录symlink环境条件跳过）。新增6项Python测试及2项Browser测试，覆盖三模型实际Flask双Tool路径、独立发布状态/精确范围、未授权组合单轮回退、确认revision、实验标签及回滚。149个Python文件AST、JS语法、291条本地Markdown链接、diff和15个改动文本敏感扫描通过；没有凭据或outputs被Git跟踪。

首次及串行复核FULL PRODUCT均暴露既有50ms阻塞SDK测试对Windows事件循环启动速度的假设；单项通过。只把该测试的I/O启动窗口改为500ms，保留TOTAL_TIMEOUT、实际close、非用户取消与一次attempt全部断言；未修改Adapter / Cancellation / 产品deadline。修改后Security14项及完整950项通过。

两个实验模型的真实多轮表现、实际延迟及正文安全性均等待用户网页体验，不宣称已验证；长历史、评分Tool组合、Thinking ON、Streaming不在发布范围。本轮无真实Provider或Ollama推理请求，未commit/push。

# Assistant 有界多轮接入与交互设计

状态：设计，尚未实施。2026-10-12。默认产品仍为 **1 Tool / 1 round / 2 requests**；本方案仅研究 Assistant 可控启用 **2/2/3、每轮一个 Tool、non-streaming**。

依据当前 `assistant.py`、`tool_conversation.py`、`assistant_sources.py`、`execution.py`、`web.py`、`observability.py`、`resources/web/app.js` 及对应测试。[内部 Runtime](../tools/READ_ONLY_TOOL_CALLING.md)、[当前 Assistant 架构](../architecture/ASSISTANT_MODEL_V1_DESIGN.md)提供现有合同，本文件不替代它们。

## 1. 当前缺口与资格证据边界

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

单轮旧客户端可继续省略 revision 并保持旧合同；多轮必须携带匹配的 revision，否则联网前拒绝。不能因客户端省略该字段自动放宽到三次请求。

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

建议：**可以开始阶段 A（安全投影与通用 UI），默认 flag 关闭。**不能仅凭这两个实验样本直接开启正式多轮；正式 Prompt 资格、整 Turn deadline、发布范围与终态一致性应在启用前完成。本轮仅写设计，不做实现或真实请求。

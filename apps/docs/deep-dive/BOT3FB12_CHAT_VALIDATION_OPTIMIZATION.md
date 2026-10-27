# BOT-3F-B1/B2：聊天展示与 QQ 同边界校验复用

日期：2026-10-27。项目：Fishery_AI_Prototype；开始 HEAD：`c3745d29eeffe83ad4b99fa8c35f64a938c1a5b7`，开始工作树干净。本轮没有真实 QQ/Qwen 请求、真实凭据读取、Management 同步或提交。

## 1. 当前行为与边界

新 `SessionTrialRun` 默认 Chat；FAST、TwoTurn、普通 QQ CLI、Fake-only SessionRun 和原 `render_channel_reply()` 继续原语义。Detailed 的完整 A/B/C 保留，没有新增群聊切换指令或自然语言意图。

Chat 使用同一份本轮 SourceSummary、原封闭解释合同 `qq-water-explanation@1` 和服务器授权快照中的 focus。它不再次查询 DB、不再次调用模型、不展示自由文本，也不把聊天历史读数当作当前观测。

| 本机选择 | 行为 |
|---|---|
| `Test-QQConversation.ps1 -Mode Session -Check` | 默认 Chat；只读配置/Scope 检查，不打开业务库、读 Key、联网或消费批准 |
| `-Mode Session -Presentation detailed -Check` | 检查独立 Detailed Scope；完整 A/B/C |
| 不指定 Mode 的旧入口 | 仍为 TwoTurn；逐 Turn 批准，原展示不变 |
| TwoTurn 显式指定 Presentation | 拒绝，避免将新持续会话参数混入旧合同 |

模式被绑定到 Scope、计划和 RunConsent；审批后修改模式会使 Run 失效。Chat 与 Detailed 都仍需新的当前进程审批，不能复制另一模式或旧 Scope 的批准。

## 2. 展示实现与合成样例

`apps/ai_service/channel_chat_presentation.py` 是纯展示分支；`ai_delivery.py` 只在精确的 SessionQQTransport 且模式为 Chat 时使用它。旧 renderer 及其默认参数没有改变。

Chat 按 focus 选取有效指标；同时保留所有规则命中、未询问的缺测/无效指标及整体限制。无效指标不显示其数值。stale、offline、never_received、unknown 各自准确表达，未知不写成离线。时间由实际字段转为北京时间 UTC+08；缺失、无时区或无效时间显示未知，不补当前时间。

以下仅是合成 SourceSummary 的离线样例：

```text
SIMULATOR 模拟数据 · sim-pond-1
溶解氧：6.5 mg/L
本窗口未触发水质实验规则，不等于专业健康判断。
AI 建议（已校验，未执行）：请人工核对后续观测。
观测 2026-10-26 08:00:00；评估 2026-10-26 08:00:02（北京时间 UTC+08）。
评估时：有效/新鲜/在线；查询未重新采样。
```

同一输入的 Detailed 原样例（保留旧时间及字段格式）：

```text
A. 系统事实（可信 Monitoring Tool）
本轮只读事实 · synthetic-instance · sim-pond-1 · SIMULATOR
观测 2026-10-26T00:00:00+00:00 / 接收 2026-10-26T00:00:01+00:00 / 评估 2026-10-26T00:00:02+00:00
质量 valid / 新鲜度 fresh / 连接 online
以下为留存窗口值，不是重新采样或实时状态保证。
水温：25.0 °C（valid）
pH：7.0 （valid）
溶解氧：6.5 mg/L（valid）
合成观测仅用于测试；查询不等于重新采样。模型自由文本尚未核验，不直接展示；解释另经合同校验。
B. 模型解释（AI 解释要点，经程序校验与渲染）
以下说明仅对应本次评估窗口，不代表发送时重新测得的水质。
溶解氧存在有效的留存窗口记录，触发情况以业务规则为准。
pH存在有效的留存窗口记录，触发情况以业务规则为准。
建议（未执行）：建议人工核对后续观测；本次查询没有重新采样。
C. 来源与限制
SIMULATOR 是合成观测，非真实硬件采样；规则为本地实验规则，不能替代专业判断。
质量、新鲜度及连接状态均为上述评估时刻的判断；发送时未重新采样。
```

若问水温而存在严重低氧，仍显示水温和“系统实验规则：溶氧低……（严重）”；若只问溶解氧但 pH 缺测，另显示“pH：数据不足（缺测）”及“当前状态不能完整确认”。过期/离线数据先提示“以下仅为留存读数”。

AI 建议只来自原校验通过的封闭建议代码，经程序生成中文；规则是系统事实，建议标明已校验且未执行。无效模型计划退回事实与必要限制；完整安全文本放不下时拒绝，不截断规则、来源或时效提示。Detailed 仍调用原函数输出完整 A/B/C。

API 接受后仍传递实际最终发送文本；原 PassiveReplyOwner 计算其 SHA-256，ConversationStore 再核对哈希和 revision 后保存安全文本。没有把旧 Detailed 文本、渲染前文本或原始模型正文写入成功记忆。未知送达、撤权和报告故障不补发、不补推理。

## 3. B2 实际消除的重复路径

没有修改 Agent、Tool Calling、SDK Adapter、共享 Policy Store、Monitoring 规则或 Schema。新复用工具 `apps/ai_service/channel_validation.py` 仅服务 QQ 渠道校验：

- 一次同步校验调用拥有私有 ContextVar 快照，绑定 Boundary 对象和线程；嵌套同 owner 才可复用，退出即清空，异常同样清空。
- 没有 Run 全程缓存、mtime 缓存、TTL、后台刷新或跨线程复用。复制 Context 到其他线程也不能继承已验证结果。
- 缓存的是本次配置/Scope 验证的成功结果，以及重复读取的实现文件 SHA；不缓存水质、用户权限对象、Tool 结果、Ledger 余额或 SDK 资源状态。
- 原始 Scope 仍用本次实际 profile / policy / registry 计算，实际 Tool Definition 变更仍拒绝；只复用同一次校验中已读的实现文件字节摘要。

| 校验入口 | 原重复与现在的复用 | 保留的检查 |
|---|---|---|
| SessionTrialQwenTurn.check | RunAuthorization 与 validate 闭包都触发 Run 静态配置/Scope；本次成功证据只算一次 | 每次身份、Ledger/期限/所有权、SDK、内存权限比较及 Lease/历史快照检查 |
| history_decision | 自身 check 与实际 registry Scope 重读相同实现文件 | 实际定义/Policy/Profile 重新核对，历史 ticket、revision 和绑定不缓存 |
| Coordinator.conversation_context | 权限检查和会话 Scope 构造重复读同一实现文件 | 当前成员/群/设备、Policy 和 generation 检查 |
| validate_plan | 服务授权与历史决策内再次复核相同 Run | watchdog 每次调用仍开启新快照，不跨监督轮次复用 |
| validate_delivery_candidate | 同一纯校验调用中的服务/历史/Run 嵌套复核 | SDK 关闭、任务结果身份、Source/Commit、release status、Scope、期限和授权 |

`SessionRun._check_configuration()` 只是从原方法提取的钩子；Fake-only Run 默认仍完整检查。仅 typed SessionTrialRun 在当前校验区间内复用该结果。

### 不允许跨过的边界

没有装饰整个 `execute()`、`deliver()`、模型调用或 Handler。校验区间必须在以下操作前结束：

1. 原子额度预留/账本写入。
2. Monitoring 实际查询。
3. SDK Client/模型 I/O。
4. QQ HTTP POST。
5. ConversationStore.commit。

发送前校验、token 刷新后的 before_post 和历史提交前校验分别新开区间。watchdog 的频率、任务期限及撤权取消逻辑未变；不能用上一个区间的成功证明继续执行。

这仍是安全边界上的快照，不宣称多个磁盘文件形成原子文件系统事务；原方案也存在检查与使用之间的并发窗口。复用区间中没有业务/网络 I/O；下一关键边界读取真实当前内容。未来若在这些校验函数中加入业务 I/O/await，必须移出区间并重新审计。

## 4. 安全验证

新增 28 项测试覆盖展示与词法区间，包含：

- 可信 focus、跨指标严重命中、缺测/无效/过期/离线、无数据、时间未知、自由文本拒绝及完整长度限制。
- 原 Detailed A/B/C、两个模式的独立 Scope 和离线 Check。
- 同区间配置只查一次，后续区间重新读取；相同长度且恢复原 mtime 的绑定变化仍能检出。
- 授权对象克隆拒绝、区间内 SDK 隔离和到期仍立即拒绝、复制 Context 到其他线程不复用。
- 第一模型响应后撤权阻止 Tool/后续请求；token 刷新时撤权阻止 POST；API 接受后撤权不提交历史、不重发。
- 在真实类型化 Fake 链上断言：额度 reserve、Tool、SDK、QQ HTTP 和 History Commit 时均没有活动校验快照。
- Chat 保存实际 API 接受的完整文本及匹配 SHA；模式在审批后改变立即失效。

原有 RunConsent、并发、未知交付、Scope/设备变化、跨进程所有权和最后一个已预留 Turn 的测试继续执行。对所有失败保持原预算不退款、零重试和 SDK sticky 隔离。

验证结果：

- QQ 专项 **512/512**，303.446 秒。
- 完整管理 Python **1105/1105**，376.842 秒；Node **116/116**，零失败。
- 原性能工具测试 **14/14** 通过；原测量脚本没有修改。
- PowerShell Core Smoke **16 个正式样本成功**；随后完整 Benchmark **600/600 正式样本成功**，连同预热/探针/冷执行共 **740/740 记录成功**，无残留 Scheduler/SDK 工作线程。
- Python/PowerShell AST 与差异检查通过；上述结果不等于真实网络验收。
- 另用临时合成配置实际执行 PowerShell Chat / Detailed 两种 `-Check`，均退出 0；旧 TwoTurn 显式混入 Presentation 参数正确拒绝。没有读取用户的现有 request 或业务实例。

证据目录：`outputs/performance/bot3fb12-20261027T100158Z/`，其中 `full-regression.log`、`presentation_examples.json`、`comparison.json`、`frozen_code.json` 分别记录回归、合成展示、对照数据及采样期源码身份。没有保存真实聊天、模型原始正文或真实批准。

## 5. 性能对照

优化前基线使用 [BOT-3F-B0](research/BOT3FB0_WEB_QQ_PERFORMANCE_BASELINE.md) 的完整 30 样本数据。实施前已核对：原 382 个生产文件及三个测量脚本与该基线完全一致；HEAD 的差异仅为已提交文档和测量工具。

本轮读取项目 venv 配置、实际 sys.version，并在新 PowerShell 进程运行同一 venv 核对，均为 **Python 3.12.14**；不与不同解释器作加速比较。普通用户若使用不同环境，需在其目标环境复跑。本轮不修改 venv。

先经原 PowerShell Smoke，再用未修改的 `Compare-WebQQPerformance.ps1` 完整 Benchmark；同一 Fake 响应、问题、合成数据、参数与单轮预算。每条件至少 30 正式样本；保留失败、冷执行、预热和观察器探针，不挑最快数据。Chat/Detailed 不额外调用模型或查询数据。

基线目录：`outputs/performance/webqq-20261027T085904Z-ba6c457b/`；优化后：`outputs/performance/webqq-20261027T102330Z-56d06de4/`。两个目录均保留 JSON、CSV、阶段明细和样本状态。600 对正式记录的合成来源摘要、模型请求数、模型输入/工具定义/预算摘要和历史条件逐项相同，**0 项不匹配、0 个失败样本**。采样前后冻结的源码摘要一致。

### 同核心对照：QQ

单位 ms；每行优化前后各 30 个正式样本。两次模型调用均为内存 HTTP，不代表真实 Qwen 时延。

| 数据条件 | 中位数：前 → 后 | P95：前 → 后 | 中位数变化 |
|---|---:|---:|---:|
| 有效、新鲜 | 2307.295 → 1048.973 | 2468.143 → 1146.998 | −54.5% |
| 低氧 | 2386.079 → 1001.951 | 2841.691 → 1098.123 | −58.0% |
| 部分缺测 | 2363.816 → 1032.100 | 2543.647 → 1085.395 | −56.3% |
| 过期/离线 | 2373.752 → 1072.389 | 2547.501 → 1402.299 | −54.8% |

### 实际入口：QQ

| 条件 | 中位数：前 → 后 | P95：前 → 后 | 解释 |
|---|---:|---:|---|
| 当前水质 | 2205.225 → 1054.750 | 2378.714 → 1335.265 | AI；−52.2% |
| 溶解氧 | 2358.342 → 1044.538 | 2968.804 → 1416.957 | AI；−55.7% |
| pH/部分缺测 | 2302.946 → 1420.436 | 2917.154 → 1945.630 | AI；−38.3% |
| 数据可靠吗 | 204.080 → 246.384 | 226.862 → 311.129 | 原澄清模板，零模型；变慢 20.7% |
| 已交付历史后的水温追问 | 3328.761 → 1630.175 | 4301.547 → 2199.864 | AI；−51.0% |
| 低氧风险 | 356.709 → 246.263 | 431.228 → 355.233 | 原澄清模板，零模型；不可当作 AI 提速 |

问题文本、数据和 history_before 摘要均与基线一致。追问使用同进程内由 API 接受后提交的历史，不构造虚假的成功 Turn。模板条件保留在数据中，不能把它和两次模型请求的工作负载混排。

### 重复校验与阶段开销

以下为同核心 fresh QQ 的中位数。调用次数是顶层/指定函数统计，不是工具或模型请求数。

| 观察项 | 优化前 → 优化后 |
|---|---:|
| 顶层 Scope 构建次数 | 151 → 76 |
| 配置 inputs_snapshot 次数 | 132 → 57 |
| Management Policy 快照次数 | 288 → 138 |
| Shared Policy 加载次数 | 421 → 196 |
| 共享核心前的混合区间 | 724.028 → 448.738 ms |
| 共享核心执行混合区间 | 476.658 → 238.579 ms |
| 核心后的混合区间 | 1073.489 → 360.718 ms |
| Scope 区间并集 | 1884.357 → 754.129 ms |
| 配置/Policy 区间并集 | 566.202 → 255.724 ms |

优化后同条件：两次 Fake HTTP 中位数约 0.094 / 0.290 ms，Monitoring 实际查询约 1.541 ms；整个 Tool 区间约 75.705 ms，包含 Handler 权限复核。SDK close 约 0.006 ms、join 约 2.306 ms；QQ 交付混合区间约 274.742 ms，其中 Mock HTTP 约 0.049 ms；History Commit 本体约 0.109 ms。耗时仍主要是本地校验，不能把“交付区间”全部归因于 QQ 网络。

这些是嵌套、跨线程的区间统计，Scope/Policy/核心与交付存在重叠；**不能把各行相加**。单独阶段的中位数也不必相加等于总体中位数。原始明细保留完整重叠信息。

### Web 对照及不利结果

| 同核心 Web 条件 | 中位数：前 → 后 | P95：前 → 后 |
|---|---:|---:|
| 有效、新鲜 | 16.801 → 17.174 | 21.527 → 24.033 |
| 低氧 | 18.336 → 16.457 | 22.951 → 21.267 |
| 部分缺测 | 17.176 → 16.939 | 24.311 → 22.569 |
| 过期/离线 | 18.047 → 17.091 | 24.059 → 26.270 |

主 Benchmark 的 Web 实际入口六个条件中位数分别为：16.902→18.198、18.011→18.661、18.300→20.660、17.377→22.911、19.421→22.350、23.054→25.936 ms，增加约 1.3～5.5 ms。**保留这组不利结果，不宣称 Web 零性能变化**。

为判断是否存在持续的大幅退化，另做同参数 Web-only 复测，各 2 次预热、30 次正式样本：当前水质中位数 17.406 / P95 20.160 ms，可靠性条件 19.269 / P95 24.633 ms，全部成功；详见 `web_control.json`。Web/Backend/Monitoring 共享核心源码摘要与基线相同，完整功能回归通过；当前没有发现持续的大幅 Web 退化，但几毫秒变化与主机波动尚不能严格分离。真实目标环境仍应复测，不替换主 Benchmark 的原始结果。

### 展示对照

相同合成 SourceSummary 与封闭解释要点：溶解氧 Chat/Detailed 为 172/555 字符，pH 缺测为 174/577，未询问的严重低氧为 189/655，过期条件为 180/580。来源、时间、限制和全部规则命中保留；没有增加模型请求或 Monitoring 查询。该组字符长度是同输入的渲染对照，不是用户可读性的主观评分。

结论：当前可验证的收益是 **QQ 专用本地重复复核减少**，AI 条件中位数下降约 38%～58%；真实 Qwen 的两次网络请求和 QQ 客户端延迟本轮没有测量，也没有减少请求数。

## 6. Scope、兼容性和剩余开销

原模型输出合同、Prompt、当前水质 Definition、工具循环 1/1/2、512 Token、90 秒、零重试、费用预留与 Run 上限都没改变。

新增 `qq-current-chat-presentation@1` 和 `qq-lexical-validation-snapshot@1` 的实际实现绑定；持续会话 Scope 包含模式、渲染源码和验证实现。只刷新维护者 candidate 准备资源，所有 qualification_id 仍 null；没有修改历史批准、used 或真实回执。

| 范围 | 当前 SHA-256 / 状态 |
|---|---|
| 新持续会话 Chat | `cef647bcd2c43f8bf8b9da7a1e2e3104c8fac56204c3b1e070cd95a3938cd4d0`，candidate |
| 新持续会话 Detailed | `9efcfe531a865208e8321c6fc28ea8cf1814b6f1763d9c674d83d0f7abe2287a`，独立 candidate |
| Fake-only SessionRun | `6f7c091770a32e6be4d4de334555eb32fb878e2521f5923a850b5829b732418c`，仍 Fake-only |
| 旧 TwoTurn 当前实现 | `d880a00c8636f90ff2914847b41a5cde9c3d12144b1f26a65deb4eaafd36cb07`，candidate |
| Monitoring-only 基础准备 | `2d89b74fe451f793c09e21fff90dc624d9fd2ee34a02c393284f2e61066350be`，未变，candidate |

之前持续会话为 `e92595b351669bfb8fe5e0be87f0a6cbfaf7463803e93b0b982b1d7f31427ef2`。此轮实现和展示变化使它失效；没有改写旧批准使其适配新 Scope。维护资源另包含更新后的 Fake Conversation 候选，所有资格仍未提升。

旧 FAST、双轮和持续会话批准不能作为新源码执行许可；即使使用 Detailed 也需重新计划/审批。普通 QQ CLI 的 AI_DISABLED 不变。Web 默认 Prompt、Service、SDK Adapter、Knowledge/Monitoring 和 DTO 没有改动，相关回归及对照独立验证。

剩余：不同时间边界仍完整重建 Scope、读取配置/Policy；实际 Tool 定义与权限必须复核，watchdog 仍运行。本轮没有改变 SDK Client 复用、资源关闭或线程机制；不合作线程不能强停、远端计算/计费未知的风险保留。真实网络和 QQ 客户端显示延迟没有测量，不能由 Fake 的加速百分比保证实际体验。

“现在的数据可靠吗？”、“有没有低氧风险？”仍是原澄清路由，零模型请求，不在本轮扩展；其意图覆盖与收费准入另立任务。

### 修改文件范围

| 类别 | 文件及用途 |
|---|---|
| 新展示与校验工具 | `apps/ai_service/channel_chat_presentation.py`、`channel_validation.py`：纯渲染、仅同步校验区间的临时证据 |
| QQ 渠道 Scope/授权 | `channel_conversation.py`、`channel_conversation_trial.py`、`channel_session_run.py`、`channel_session_trial.py`、`channel_trial.py`：实现绑定、独立模式 Scope、typed check 区间 |
| QQ 接入 | `apps/qq_bot/ai_coordinator.py`、`ai_delivery.py`、`session_run.py`、`session_run_trial.py`、`session_run_trial_cli.py`：校验钩子、模式选择和计划绑定 |
| 准备资源 | `qq_conversation_candidate.json`、`qq_conversation_trial.json`、`qq_session_run_candidate.json`、`qq_session_run_trial.json`，新增 `qq_session_run_trial_detailed.json`；均在 `apps/ai_service/resources/` |
| 测试 | `apps/qq_bot/tests/test_chat_presentation.py`、`test_validation_boundary.py`、`test_session_validation_integration.py` |
| 本机入口 | `scripts/dev/Test-QQConversation.ps1`：仅 Session 接受 Presentation，旧模式默认不变 |
| 文档 | 本报告及 `apps/docs/README.md`、`BUILD_RUN.md`、`ROADMAP.md`、`STRUCTURE.md` |

共 26 个新增/修改文件，未提交。没有改动共享 Web Service、Backend/SDK Adapter、Monitoring、性能测量工具或其他项目。最终校验清单见证据目录 `final_verification.json`，含文件身份、当前候选 Scope、语法和文档链接核验。

## 7. 下一次真实体验验收（必须另行批准）

1. 审阅本报告、代码 diff、新 Scope 和费用合同；先确认实际终端解释器/依赖。
2. 明确仍用原批准的隔离 SIMULATOR 实例、设备、群和成员，不能自动选择新实例。
3. 可先执行只读 Check：

```powershell
.\scripts\dev\Test-QQConversation.ps1 -Mode Session -Check
.\scripts\dev\Test-QQConversation.ps1 -Mode Session -Presentation detailed -Check
```

4. 取得本轮之后的真实网络授权，再生成新的当前进程 RunConsent；不使用旧批准或回执。短验收可限制 2 Turn、300 秒、总预算 3.21 元（保守预留最低 3.205530 元），单独核对 Provider/模型、披露范围和 SDK 线程风险。
5. 在同一成员会话测试问候、当前水质、单指标追问；人工检查 Chat 重点、严重异常/缺测提示及北京时间。Detailed 使用独立 Run 测试完整 A/B/C；不新增群聊切换命令。
6. 检查每轮 2 请求/1 Tool、SDK CLOSED、一次 API 接受、实际客户端显示、History Commit 及最终报告；未知发送不重试。到期或 Ctrl+C 后核对 RAM 清理和进程退出。

本轮仅离线实施，到此停止；不自动开展以上联网步骤。

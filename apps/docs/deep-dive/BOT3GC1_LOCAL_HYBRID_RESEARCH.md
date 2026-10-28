# BOT-3G-C1：本地 Qwen Hybrid 研究实验

核验日期：2026-10-28。仅 Prototype。本轮完成入口、题库、统计和离线验证，**没有调用真实 Qwen 或 QQ，没有读取真实密钥或现有业务库**。真实 General 仅允许在后续操作者新审批后保存到本机研究目录，不获得 QQ 自动发布资格。

## 1. 使用范围与装配

```text
Test-HybridProvider.ps1 → hybrid_research_cli
  → 完整实验计划 / 本机一次挑战确认（明确列出每个独立 Run）
  → HybridResearchRun / 原 RunLedger、RunOwner、TurnLease
  → 每 Turn 独立 ManagementAssistantService / ResearchHybridTurn
  → 原 AssistantService / ToolCallingService / TrialQwenAdapter / SDK 资源门禁
  → General：无 Tool 的结构化本地答复
     Water：实际当前水质 Tool → 同轮 SourceSummary → 原封闭解释
  → 受保护的本地 review + 捕获检查点 → 本地 RAM 研究历史
```

没有新 Agent、HTTP 服务、聊天数据库、Provider 或 Tool。没有 QQ Gateway、QQ 发送或 QQ Delivery 装配。本地研究路径用现有 `ChannelAuthorization`、历史快照、Source/Commit Gate 与业务 Policy 交集；不把本地写盘伪装成 QQ API 接受。

General 的程序检查仍是有限的结构、长度及显式危险断言防护，**不是通用事实核验器**。本地捕获或合同通过不能证明一般知识答复正确。Water 的事实必须来自实际执行步骤和 Receipt，模型的 `kind` 不能修改分支。有 Tool 却输出 General 时只保留可信事实降级；没有 Tool 却输出现场断言时执行原拒绝。所有结果保留 `can_deliver=false`；普通 QQ CLI、旧 FAST、TwoTurn、Session 不切换为 Hybrid。

基线 Prompt 继续使用 [QQ_HYBRID_DIALOGUE@1](../../ai_service/channel_hybrid.py)。本轮没有新 Prompt 候选，也没有用离线脚本的成功率推断真实 Qwen 已稳定。

## 2. 修改文件

| 文件 | 职责 |
|---|---|
| [channel_hybrid_research.py](../../ai_service/channel_hybrid_research.py) | 独立本地 Scope、身份型授权、provider 阶段 Turn、原 SDK Adapter 的计时观察、实际步骤投影 |
| [hybrid_research.py](../../qq_bot/hybrid_research.py) | 配置核查、独立 Run、只读实例、权限监督、受保护捕获、混合研究历史、CSV/统计 |
| [hybrid_research_cli.py](../../qq_bot/hybrid_research_cli.py) | Check/Run、批量审批、串行独立 Run、异常停止、最终报告 |
| [hybrid_research_suite.py](../../qq_bot/hybrid_research_suite.py) | 题库校验、分组/重复、对话原子分配与 Decimal 总预算 |
| [hybrid_research_questions.json](../../qq_bot/resources/hybrid_research_questions.json) | 48 条可复现问题、预期分支和人工判读要求 |
| [Test-HybridProvider.ps1](../../../scripts/dev/Test-HybridProvider.ps1) | PowerShell 7 薄入口，不复制授权或模型循环 |
| [local_hybrid_research_trial.json](../../ai_service/resources/local_hybrid_research_trial.json) | 新 candidate 准备记录；不含运行批准 |
| [test_hybrid_research.py](../../qq_bot/tests/test_hybrid_research.py) | 合成 SQLite、真实 SDK 类与内存 HTTP、本地批量及故障回归 |

[service.py](../../ai_service/service.py) 仅增加精确 `ResearchHybridTurn` 类型装配、原 Hybrid Prompt/结果路径及只读执行元数据观察。没有改原 Agent 循环、SDK、Monitoring、Web 配置或规则。更新受影响的公开 candidate 实现指纹和文档索引；不改历史批准或真实回执。

## 3. 题库与研究指标

| 类别 | 数量 | 预期及评价 |
|---|---:|---|
| A 一般知识 | 10 | 通常 General；不冒充项目知识库或现场证据 |
| B 当前监测 | 12 | 本轮当前 Tool；质量、时效、来源、连接和规则均来自本轮 |
| C 模糊问题 | 6 | 记录实际分支与澄清，不自动评成“选对” |
| D 多轮 | 10 | 两组完整五轮：概念→追问→当前水质→可靠性/话题切换 |
| E 边界/对抗 | 10 | 越权设备、写操作、伪造读数/Receipt、指令注入、诊断等 |

默认运行全部 48 题；`-Category`、`-CaseId` 可选择子集，`-Repeat 1..5` 重复完整样本块。五轮对话不得只选部分题，也不拆到不同 Run。每个独立题开始清空该研究会话，只有同一五轮链保留前文；重复实验使用新的链。总样本最多 250，独立 Run 最多 50，原单 Run 仍最多 5 Turn。

默认题库均为需要研究 Agent 行为的付费候选问题。固定命令、问候等免费分支不由本地实验强制送模型；尝试加入这种案例会被拒绝，原 QQ 程序分支保持原样。

三类指标分开：

1. **行为是否符合预期**：分别记录首个模型选择 `model_route` 和实际 Tool 步骤归类 `actual_branch`。后者本身不代表 Backend 完成；网络失败没有模型选择时记为无法判断，不误算为正确 General。Water 达标还必须有授权 Handler 执行；C 类不计入自动正确率。权限/执行失败与单纯路由选择的因果须结合 `backend_error` / `tool_results` 判读。E 类只是预期标签，安全拒绝是否恰当仍需按 rubric 人工判读。
2. **输出合同是否通过**：JSON 语法、外层结构、General 防护、Water 闭合计划分别观察。Backend 失败而没有最终输出，不冒充 JSON 格式错误样本。合同失败保留失败记录，不自动重试同题。
3. **回答质量是否正确**：`answering_quality_correct=null`；历史是否真正帮助理解为 `context_understanding_correct=null`。`history_attached=true` 只表示提供了经过授权的前文，不等于模型理解正确。

`manual-review.json` 为新建的人工评分模板，不自动给一般知识打正确标签。完整问题与 rubric 见题库，实际安全答复见受保护的 `review`。没有通用逐句事实验证，也不能统计有限规则未识别的隐含现场断言为“已阻止”。

## 4. 规模与费用

保持原 Run 合同：最多五 Turn、每轮最多两请求、每请求 512 输出 Token、每轮 90 秒、零重试、每 Run 最长 1800 秒。General 通常一次请求，但仍保守预留整轮额度，未使用请求不转为新 Turn。

| 选择 | Turn | 独立 Run | 原始保守预留 | 各 Run 预算向上取整后的合计 |
|---|---:|---:|---:|---:|
| 默认全题库一次 | 48 | 10 | 76.932720 元 | 76.99 元 |
| 同题库三次 | 144 | 30 | 230.798160 元 | 230.97 元 |
| 同题库五次 | 240 | 50 | 384.663600 元 | 384.95 元 |

因此全题库一次可明确批准 `-TotalBudgetCny '80'`，三次例如 `'240'`，五次例如 `'400'`。这是操作者设定的实验预算示例，**不是实际费用预测或云平台账单硬上限**。不足时拒绝计划，不缩减为两轮。预算算术用 Decimal。总预算还需独立显式填写；Check 未填时只计算所需最低预算，Run 不允许据此自动批准。

一次本机挑战同时列出并批准每个独立 Run 的题号、轮数、请求数、期限及预算；随后各 Run 分别持有原进程 nonce、独占 `.used` 声明、fsync 账本和内部 TurnLease。没有导入/恢复批准文件的接口；复制 JSON 不会产生内存授权。父实验声明与批准摘要也在逐轮权限/I/O边界检查，不只在两轮之间检查。

失败、取消、未知费用和拒绝不退额度；同题重复记录拒绝覆盖和重复消费。重启后旧余额不可恢复，也不重放旧消息。手动另起实验必须使用新目录、新计划、新审批；需要补测时显式选择题号，不能当作自动恢复。

静态单价沿用当前合同：北京区输入 0.8 元/百万 Token、输出 2.7 元/百万 Token，输入按每请求 100 万 Token 保守预留。**本轮未联网核价**；批准前须由操作者复核 Scope 和云平台报价。Usage 是观测估算，缺失或失败时保留 `usage_complete=false`、远端停止/计费未知。

## 5. 停止、资源与数据保护

- 串行研究控制器只调用原 Service 一次执行接口，不复制模型/Tool 循环。每 Turn 一个私有 Service、Session、RequestHandle；监督线程非 daemon，结束后有界 join。
- 只接受 request 明确绑定的 `bot2c-instance`，或人工创建并明确指定的 `outputs/hybrid-research-instances/...` 隔离目录。额外要求 CLI 的实例根、实例 ID、设备 ID 与配置逐项一致；不扫描实例，不回退工作区，不打开 Management。
- Check 只读指定配置/Policy/Scope 元数据，不 stat/open 监测库、不解析密钥、不建输出目录。Run 的完整本机批准后才创建 Run 并只读打开实例；另做 SIMULATOR/NO_DATA 预检，不把该预检当作某题的 Tool 证据。
- 实际查询继续使用 `InstanceMonitoring`、SQLite `mode=ro/query_only` 与原 MonitoringService。无数据、过期或离线如实保留，不改采样时间来伪装新鲜。
- JSON/合同拒绝是研究结果：记录且不提交不安全 General 历史；资源与权限安全时可继续下一道不同题，不是对失败题重试。Water 解释失败可保存可信事实降级，合同成功率仍记失败。
- Provider/SDK/权限/Scope/所有权/必要捕获/历史提交异常立即停止整个批次的新请求。未执行题单独统计。SDK 清理未确认时不能本地接受成功、提交历史或继续请求。
- Ctrl+C 发出取消并走原 SDK 清理，停止后保存部分结果和剩余未执行数量。不能保证突然关窗、强杀或断电时最后报告一定写完；已经落盘的逐题捕获/结果和账本保留，禁止自动重跑。
- 必要检查点失败停止新请求；最终 CSV/评分模板失败时，仍尝试保存明确失败的最终结果。最终 JSON 写入失败通过退出码和终端报告 `report_saved=false`，不覆盖已有文件。
- 不声称本地取消能停止远端模型或计费。原线程无法强制终止的剩余风险保留，不恢复已删除的进程隔离草稿。

## 6. 报告与时延证据

默认唯一目录 `outputs/hybrid-research/experiment-<UTC>-<随机ID>/`：新建目录使用现有私有文件 API 设置当前用户/SYSTEM 访问；不修改父目录 ACL，已有目录权限不符合时拒绝。目录中的全部文件都不应加入 Git。

```text
plan.json / approval.json / run-*.used    # 当前进程完整计划及批准声明，非可导入许可
run-001/...                              # 独立额度账本、逐题结果与脱敏 Trace
run-001/review/case-*.json                # 本机供人工审阅的安全文本、来源、哈希
run-001/case-*.capture.json               # 本地捕获检查点，不是QQ Receipt
result.json                              # 全实验结果、逐题行、未执行数量与统计
results.csv                              # 仅编号/数值/状态，无问题正文或模型正文
manual-review.json                       # 质量与上下文人工评分模板
```

逐题包含类别/预期/实际分支、模型请求与实际 HTTP 计数、Tool Handler/结果/耗时、JSON/合同判定、前文数量、本地捕获/历史状态、Usage/估算费用、SDK CLOSED/线程退出及失败代码。真实 SDK 路径的 HTTP 计数由原请求 hook 记录；自定义内存工厂的 HTTP 计数可能为 0，应同时看 `offline_test` 和 SDK 尝试数，不能把它当作真实联网样本。

`total_ms` 是本题准入到本地捕获/历史处理的单调时钟区间，尚不包含其后结果行的最终落盘；不含操作者审批和 Run 初始化。`adapter_total_ms` 嵌套于该区间，混合了权限校验、SDK I/O 和清理，**不能当纯 Qwen HTTP 延迟，也不能与 total_ms 相加**。原循环提供 Tool 时长。`http_only_ms=null`，真实响应头/体独立耗时尚未添加，不能猜测。每个分布提供 N/中位数/范围；少于 30 样本不输出 P95。费用、Token、类别选择、JSON 错误与代表失败题号分别汇总。

默认不保存原始模型 JSON/正文，仅保存实际本地安全展示文本供人工审阅；不保存 HTTP 原始响应或请求。若另行明确启用 `-SaveRaw`，最多在受保护 review 中保存 32768 字节模型输出；超限只记大小和哈希，不保存截断正文。普通日志/CSV/Trace 从不输出完整消息、模型正文、Key、Token 或完整平台身份。

## 7. Scope 与旧资格

新合同为 `local-qwen-hybrid-research@1`，准备资源仍为 **candidate**，`qualification_id=null`，QQ 发布未授权。只有当前进程中匹配新计划、原子账本和精确类型的 ResearchAuthorization 才能派生实际执行；没有修改 candidate 的布尔值来开启网络。

新 Scope 绑定实际 Prompt、Tool、SDK资源合同、预算、历史投影、本地捕获规则、题库与入口实现。旧 Fake Hybrid 保持 Fake-only。共享 `service.py` 的精确类型接入改变了旧试用实现指纹，所以重新生成相关公开 candidate 摘要；不提升资格，不改历史批准/used/Provider回执，旧批准不能授权本次代码。

本轮最终本地 Scope：`6c4cd366fb0531e13556224ccd41ac3244686c22c4b0ecf1c3eccc1c260a40cd`。后续以 Check 重新计算值及实际源码为准，不能复制这个摘要代替批准。

## 8. 离线验证记录

新增 **41 项专项全部通过**：General 1/0、Water 2/1、真实 SDK 类+MockTransport、混合链每轮新查询、旧值隔离、缺测/过期无假HIT、无Tool断言/伪造JSON、五轮/多Run/预算不足、重复/BUSY、撤权/Scope/SDK隔离、取消、账本与fsync失败、捕获/历史/最终报告失败、PowerShell Check 零网络/零凭据/零数据库。额外验证网络失败不算正确General、多Tool选择失败不冒充General、原文保存必须有独立且绑定的批准选项。

最终同版本回归：**Python 1202/1202（649.313秒，含609项QQ Bot），Node 116/116（11文件）**。包含全部 QQ Bot、Monitoring、Simulator、Knowledge、Web HTTP、AI Service Normal/Streaming 与 Backend 相关回归。解释器为本项目 `.venv` 实际 Python 3.12.14，OpenAI 2.54.0 / httpx 0.28.1。

最终48题脚本化 Mock：48行全部记录，67次模拟模型请求、19次Handler调用；29个General输出中28个通过，19个Water输出全部通过，刻意注入的E07“无Tool现场正常断言”被拒绝并保留失败行。六个模糊题不纳入自动选择正确率；其余42个均按脚本指定分支执行。合成库文件SHA-256不变、资源全部安全关闭、RAM已清空、无遗留监督线程、最终报告成功保存。**这些分支/Token都是夹具脚本安排，不是Qwen正确率、实际费用或真实网络时延。**

Mock耗时记录用于验证计时和分布输出，不与旧Web/QQ性能数据作加速比较。真实Qwen成功率、实际Token、延迟和费用均**尚无本阶段真实样本**。

证据位于 `outputs/test-tmp/bot3gc1-20261028T094735Z-f4c0d801/`：`targeted-final-code.log`、`full-final.log`、`mock48-final-evidence.json`、`mock48-final/result.json`、`verification.json`。测试期间冻结的283份代码/资源未改变；受保护的 Backend/SDK、Monitoring、Web、Simulator、Knowledge 与任务开始时一致。174条文档链接、语法和diff空白核查通过。HEAD保持 `a8470a2258c1e0684cde3688ebea9fce509dbd87` / main，原有未提交改动保留，本轮没有提交或推送。

现有 `outputs/qq-bot/conversation.request.json` 也通过了新PowerShell入口的实际离线Check：`qwen3.8-flash` / `bot2c-isolated` / `sim-pond-1`，48题/10Run，最低Run预算76.99元、明确总预算80元；`credentials_read=false`、`database_opened=false`、`network_requests=0`、`approval_created=false`。证据 `local-config-check.log`。这没有验证密钥可用性或监测数据新鲜度，后续Run仍须新人工批准。

## 9. 后续人工真实执行

在普通 PowerShell 7 中，先进入 Prototype。以下 request 已存在，但本轮没有读取其所指的私有密钥或监测库；Check 将复核当前配置，失败即停止，不能自动修复或换实例。

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
.\scripts\dev\Test-HybridProvider.ps1 -Check -RequestFile '.\outputs\qq-bot\conversation.request.json' -InstanceRoot 'D:\CodexProject\Fishery_AI_Prototype\outputs\bot2c-instance' -TotalBudgetCny '80'
```

只有在本轮离线结果经审阅、操作者决定批准真实 Provider 和模拟数据披露后，亲自执行：

```powershell
.\scripts\dev\Test-HybridProvider.ps1 -Run -RequestFile '.\outputs\qq-bot\conversation.request.json' -InstanceRoot 'D:\CodexProject\Fishery_AI_Prototype\outputs\bot2c-instance' -TotalBudgetCny '80'
```

启动后复核完整模型/Scope/静态价格、实例/设备、身份摘要、十个独立 Run、96 请求上限和 80 元预算，输入本次随机 `APPROVE <摘要>`。Enter 取消，Ctrl+C 停止。脚本不逐 Turn 询问，也不连接 QQ。凭据仍由原 Prototype 私有 CredentialStore 在批准后延后解析；缺失或权限错误直接失败，不迁移、不重存密钥。

| 可选参数 | 用途 |
|---|---|
| `-Category A,B,C` | 分组；例如先做一般知识或当前水质研究 |
| `-CaseId B03,B05` | 单独选择关键题；同样需新预算/新审批 |
| `-Repeat 3` | 重复所选完整样本/对话块；全题库三次可用总预算 240 元 |
| `-ExperimentSeconds 18000` | 调整整个实验期限；各 Run 仍最长 1800 秒，单 Turn 仍 90 秒 |
| `-InstanceId` / `-DeviceId` | 必须与显式 request 一致，不从题目读取 |
| `-Suite` | 明确选择本机题库文件；其内容哈希进入计划，Schema/对话链校验仍执行 |
| `-ReportRoot` | 仅本项目 outputs 下的新建/可信私有目录，拒绝覆盖 |
| `-SaveRaw` | 明确同意最小化保存模型输出到私有 review；默认关闭 |

没有 `Resume`、自动补跑、自动重试或真实 QQ 参数。预计大批量需要足够运行时间，默认总期限 7200 秒；到期未完成样本仍计为未执行，不能用实际费用低为理由恢复已消费批准。

人工验收应分别核对：实际 Tool 选择、JSON/解释合同、现场与一般知识区分、混合对话理解、失败安全降级、资源关闭和 Usage。至少抽查 E 类全部题；General 的隐含现场保证可能越过有限保护，发现时记录失败并提出独立版本 Prompt/Scope 候选，不能运行中暗改基线。未完成这些判读前不得据此开放真实 QQ General 自动发布。

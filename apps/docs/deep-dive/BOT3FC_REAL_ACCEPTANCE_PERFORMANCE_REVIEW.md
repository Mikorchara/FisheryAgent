# BOT-3F-C：真实双轮验收与性能复核

核验日期：2026-10-28（北京时间）。真实实验日期：2026-10-27。项目：Fishery_AI_Prototype；核验 HEAD：`a8470a2258c1e0684cde3688ebea9fce509dbd87`，开始工作树干净。

## 1. 验收结论与证据范围

**本次受控 QQ + Qwen 双轮 Chat 试用通过。** 两轮均完成 Backend、两次模型请求、一次当前水质 Tool、受限解释、QQ API 接受和 History Commit；最终正常到期、报告落盘、RAM 清空。用户另行确认 QQ 客户端实际显示，两类证据分别记录。

本轮只读既有脱敏报告、Trace、公开 Scope 和源码，新增本文及文档入口；没有重新连接 QQ/Qwen、读取密钥/业务数据库、修改批准/used/历史报告或生产代码。没有重新运行完整业务回归，也不将上一阶段的回归计数写成本轮实测。

证据根目录（以下 E1～E5 均在此目录）：

`outputs/qq-bot/test-runs/test-20261027T154702Z-573fe6d676bb4d1aacebfe0e56d7358f/`

| 证据 | 内容与用途 |
|---|---|
| E1：`result.json`、`summary.json` | Run、额度、停止原因与最终状态 |
| E2：`turn-1.result.json`、`turn-2.result.json` | Backend、模型请求、Usage、SDK、解释与历史状态；与 E1 内两条 Turn 逐项一致 |
| E3：`turn-1.delivery.json`、`turn-2.delivery.json` | API 接受时刻、实际发送文本 SHA-256、交付检查点 |
| E4：两份 `turn-N.trace.jsonl` | 每份各一条 Agent 与 Assistant 记录；步骤、耗时、质量、时效和历史大小 |
| E5：`session.json` | Chat 模式与实现 Scope；47 个实现摘要条目与本轮源码一致 |
| H1：用户本轮提供的 QQ 回复转录与显示确认 | 问题、实际回复、客户端整秒时间；不记录昵称或个人身份 |

批准、used 及原目录其他文件仅作字节摘要保护检查，不解析其批准正文；未修改任何原件。研究不扫描其他试用目录或数据实例。

运行 Scope：`cef647bcd2c43f8bf8b9da7a1e2e3104c8fac56204c3b1e070cd95a3938cd4d0`；展示合同 `qq-current-chat-presentation@1`，模式 `chat`。这是一份既有实验验收记录，不提升 candidate/released 资格，也不生成下一次执行许可。

## 2. Backend、SDK、交付与额度核对

| 项目 | 第一轮 | 第二轮 | 依据 |
|---|---|---|---|
| 问题主题 | 整体水质 | 溶解氧追问 | H1 |
| `verified` / `backend_completed` | true / true | true / true | E2 |
| 模型执行序列 | Tool Calls → Final Answer | Tool Calls → Final Answer | E4；各 2 次模型请求、1 次 Tool |
| Tool | `get_current_water_quality`，OK | 同左，OK | Assistant activity 的实际 Tool 名称与状态 |
| Source / Commit | 完成，未见来源/提交错误 | 同左 | E4 `completed`、`error_code=null`，结合下述代码门禁；未独立持久化每道 Gate 的布尔值 |
| 解释 | `EXPLANATION_CONTRACT_VALID` | 同左 | E2/E3；`explanation_in_payload=true` |
| SDK 最终状态 | CLOSED，线程退出、local I/O 已关 | 同左 | E2；`task_done=true`、`cleanup_error=null`、未隔离 |
| 实际 SDK / HTTP 请求 | 2 / 2 | 2 / 2 | E2；合计 4 次，未见额外尝试 |
| QQ 平台交付 | `QQ_REPLY_API_ACCEPTED` | 同左 | E2/E3；不代表程序看见客户端 |
| 客户端显示 | 用户人工确认 | 用户人工确认 | H1；程序 `client_display_confirmed=false` 保持原状 |
| 历史 | `HISTORY_COMMITTED` | 同左 | E2；第二轮执行时收到并投影 1 条历史、467 字节 |

**Gate 的证据层级：** [AssistantService._send](../../ai_service/runtime/assistant.py) 在成功提交前检查 Source Ledger；[RequestHandle.finalize_result](../../ai_backend/execution.py) 在 Commit 前检查资源已关闭；[SourceSummary.from_result](../../ai_service/channel.py) 只从本轮实际 Tool Step/Receipt 构造来源，要求 SIMULATOR 和匹配的设备；[DeliveryOwner](../../qq_bot/ai_delivery.py) 在发送前重新验证。这些已核对的代码路径与成功记录共同支持 Gate 通过，不能把它表述成 Trace 另有一套逐 Gate 审计或逐请求关闭计时。

Source Gate 的 `CURRENT_OBSERVATION_QUERY` 表示本轮查询已完成，**不保证观测新鲜、不表示硬件重新采样，也不表示水质正常**。见 [sources.requirement_satisfied](../../ai_service/runtime/sources.py)。

两份较底层 Tool Trace 将工具名投影为 `unknown_tool`，这是 [JsonlTraceSink](../../ai_backend/observability.py) 的名称 allowlist 脱敏分支；Assistant activity 明确记录实际名称、`handler_started=true`、`used_tool=true` 和 OK，不能据此误判调用了未知工具。可作为以后观测一致性的小项，不在本轮改代码。

E3 的 `history_code=null` 是**先保存交付检查点、后提交历史**的正常顺序；E2/E1 保存后续 `HISTORY_COMMITTED`。两者没有冲突。History Commit 表示 API 接受后的程序提交；用户是否阅读另属人工事实。

Run 最终为 `SESSION_TRIAL_STOPPED` / `QQ_RUN_DURATION_REACHED`，`completed=true`、`report_saved=true`、`ram_cleared=true`、`delivery_unknown_turns=0`；没有未知交付重发。SDK 的 `remote_compute_stopped=unknown` 保持如实记录，不能由本地关闭推断云端停算或账单状态。

| 预算/Usage | 核对结果 |
|---|---|
| 批准上限 | 2 Turn、4 次模型请求、总预算 3.21 元 |
| 已保守预留 | 2 Turn、4 请求、3.205530 元，每轮 1.602765 元；Run CLOSED、不恢复余额 |
| 第一轮 Usage | 输入 3472、输出 104 Token；估算 0.0030584 元 |
| 第二轮 Usage | 输入 4006、输出 58 Token；估算 0.0033614 元 |
| 合计 | 输入 7478、输出 162 Token；Usage 估算 **0.0064198 元** |
| 账单边界 | 两轮 `usage_complete=true`、`billing_confirmed=false`；估算不是已确认账单，也不替代保守许可扣减 |

## 3. 实际响应时间：可测区间与缺口

H1：第一轮 23:47:41→23:47:48，约 **7 秒**；第二轮 23:48:04→23:48:10，约 **6 秒**。这是用户客户端的整秒时间，两条样本不能产生稳定均值/P95或长期性能结论。

以下为 E4/E3 的服务器侧记录；北京时间 UTC+08。毫秒耗时优先采用 Trace 记录的 elapsed，总区间起止和 API 间隔采用其现有墙钟；精度、舍入与时钟来源不完全相同，不强行让所有数字相加。

| 区间/时刻 | 第一轮 | 第二轮 |
|---|---:|---:|
| Assistant 开始 | 23:47:42.617 | 23:48:05.669 |
| Assistant 已记录总耗时 | 4.828 s | 3.359 s |
| 内嵌 Agent 总耗时 | 4.781 s | 3.312 s |
| 内嵌 Tool 步骤 | 0.172 s | 0.188 s |
| Tool 评估时刻（非开始/结束） | 23:47:45.289 | 23:48:07.039 |
| Assistant 结束 | 23:47:47.444 | 23:48:09.022 |
| 本地 API 接受回执时刻 | 23:47:49.006 | 23:48:10.320 |
| Assistant 结束→API 接受 | 1.562298 s | 1.298011 s |
| Assistant 开始→API 接受 | 6.388625 s | 4.651790 s |

Assistant 包含 Agent，Agent 包含 Tool；三者不能累加。Tool 包含 Handler/权限/参数校验，**不是纯 SQLite 查询时间**。Agent 减去 Tool 得到 4.609 / 3.124 秒混合余量，仍含模型 SDK、权限及其他执行开销，不能把它命名为“两次 Qwen 网络耗时”。

API 的 `accepted_at` 是本地发送调用成功返回后记录的时刻，不是平台生成的消息显示时间。第一轮客户端转录为 23:47:48，而本地回执为 23:47:49.006；客户端显示可能早于本地收到 HTTP 响应，且两端未校准、转录仅到秒，不能相减当作传输延迟或据此断言交付时间错误。

| 希望拆分的阶段 | 本次能否单独量化 |
|---|---|
| Gateway 接收、准入、排队 | 没有各自起止；不能用客户端发送→Assistant 开始代替排队时间 |
| Scope / Policy / 权限复核次数及耗时 | 真实 Trace 未记计数或跨度；只能引用前轮独立离线基线 |
| Qwen HTTP①、HTTP② | 有请求次数、Usage、outcome，没有各自起止；不能分摊或认定占比最大 |
| Tool / Monitoring | Tool 为 172/188 ms；Monitoring DB 读取未单独计时 |
| SDK close / join | 有最终资源状态，没有独立阶段耗时 |
| 解释校验、Chat 渲染 | 有合同通过结果，没有独立耗时 |
| 发送前校验、Token、QQ HTTP、检查点 | 共同落在部分收尾混合区间，不能把 1.562/1.298 秒当作 QQ RTT |
| History Commit | 有成功状态、没有独立开始/结束；发生在 API 接受后，不属于上述“结束→API接受”区间 |

没有使用文件 mtime 反推阶段耗时；没有为补计时重新调用 Provider。

## 4. 两轮 Chat 文本与可读性

H1 转录去掉平台昵称/@前缀，按现有 renderer 的行界还原为下面两条正文；UTF-8 SHA-256 **分别与 E3 的 `text_sha256` 完全一致**。这是已接受发送正文的核验，不是用新读到的数据重建历史回答，也没有展示模型原始正文。

第一轮，222 字符：

```text
SIMULATOR 模拟数据 · sim-pond-1
当前状态不能完整确认。
数据过期、设备离线；以下仅为留存读数。
水温：26.5 °C
pH：数据不足（缺测）
溶解氧：2.2 mg/L
AI 建议（已校验，未执行）：请人工核对后续观测。建议检查模拟数据上报、质量和时间。
观测 2026-10-25 02:55:28；评估 2026-10-27 23:47:45（北京时间 UTC+08）。
评估时：部分有效/过期/离线；查询未重新采样。
```

第二轮，211 字符：

```text
SIMULATOR 模拟数据 · sim-pond-1
当前状态不能完整确认。
数据过期、设备离线；以下仅为留存读数。
溶解氧：2.2 mg/L
pH：数据不足（缺测）
AI 建议（已校验，未执行）：请人工核对后续观测。建议检查模拟数据上报、质量和时间。
观测 2026-10-25 02:55:28；评估 2026-10-27 23:48:07（北京时间 UTC+08）。
评估时：部分有效/过期/离线；查询未重新采样。
```

第一轮正文 SHA：`3e569b5eeb4a6cab20afce6725d1f52b89e2c4df1c5f1c14069c55c53f01e47f`；第二轮：`b36dd69a73c5cd0fd86d38f66cdb2531ecba4a3f10d32678c2ed763e72736fb8`。哈希一致证明转录还原对应 API 接受的正文；客户端显示仍由 H1 人工证据支持。

评价：整体问答列出三指标；溶解氧追问删去无关水温、首先展示溶解氧，同时保留未询问的 pH 缺测。两轮都保留 SIMULATOR、北京时间、观测/评估区别、留存值限制及“已校验、未执行”的建议边界，没有把旧值称为实时状态。

仍有简化空间：两条安全提示、末行状态摘要反复表达未知/过期；两条建议部分重复。两轮有 7 行完全相同，第二轮仅比第一轮短 11 字符（约 5%），表明这组受限数据中固定提示占比较大。以后可合并“过期/离线/缺测/当前不能确认”为紧凑状态句，建议保留一个行动重点；**每条仍需独立包含来源、时效和不确定性，不能依赖上一条消息补齐限制**。本轮只提出方案，没有改模板或 Scope。

## 5. 低氧规则：为何没有显示当前命中

两轮 E4 均为 `quality=partial`、`freshness=stale`；观测时间均为 **2026-10-25 02:55:28（北京时间）**。第一轮评估时相距 247936.981 秒，即约 2 天 20 小时 52 分钟；第二轮约 247958.730 秒。第二轮重新查询并在 23:48:07 评估，但库中仍是同一个留存观测，**新查询不等于新观测**。

按 [Monitoring rules.assess_channel](../../monitoring/rules.py)：只有存在数据、`freshness=='fresh'` 且 `connectivity=='online'` 才进入当前水质风险评估。已确认的 stale 足以令 `current=False`，各 WATER_RISK 为 `NOT_EVALUATED`，原因 `STALE_OR_OFFLINE`；不会因数值 2.2 自动产生当前低氧 HIT。用户正文同时确认了离线与 pH 缺测。

[当前水质 Tool](../../ai_service/business_tools/current_water_quality.py) 直接投影领域 findings；SourceSummary 仅收集 `kind=WATER_RISK && state=HIT`。Chat 的 `source.rule_hits` 非空时才列出规则；本次不满足当前风险证据条件，因此**没有当前低氧规则文字符合现有合同，不属于隐藏已证实的 HIT**。不能反过来说“没有低氧风险”或“规则已消退”；本次文本确实没有这些断言。

证据限制：脱敏 Trace 没有保存完整 findings/SourceSummary，无法直接列出当时每条规则的原始 payload；上述状态判断是“真实 stale 记录 + 同一实现调用链”的可复核推导，而不是从 2.2 mg/L 猜测阈值。也不等同于查询曾存在的活动低氧事件；当前水质 AI Tool 没有兼任事件历史查询。

本次只验收了过期/缺测/离线分支，**未实测新鲜低氧 HIT 的真实群展示**。上一阶段离线测试已覆盖未询问严重 HIT 不得隐藏；若需补真实覆盖，必须另行批准新的合成新鲜观测及试用，不能改写本次历史时间或规则结果。

## 6. 剩余开销与下一阶段优先级

前轮 [B1/B2 离线对照](BOT3FB12_CHAT_VALIDATION_OPTIMIZATION.md) 在相同 Python 3.12.14、Fake HTTP、每条件 30 样本下，fresh QQ 中位数约 2307→1049 ms，Scope 151→76 次；600 对工作负载一致。stale 核心条件约 2374→1072 ms。结论是 QQ 专用本地重复计算已显著减少。

本次真实数据为 stale/partial、真实网络与 Windows 人工运行条件，**不能用 6～7 秒减去离线 1.049 秒，就把差值称作网络耗时**；不能将旧研究的另一组真实 Trace 和本次当成严格前后对照。两次模型请求串行存在，但没有独立 HTTP 跨度，不足以确认网络是最大瓶颈。

当前证据仍显示约 1.30～1.56 秒“Assistant结束→API接受”的混合区间，值得以后观测；它不证明某段重复校验可安全删除，更不能承诺节省同样秒数。两轮样本没有泄漏、未知交付或 SDK 关闭失败的记录，但不构成长时运行/高并发可靠性证明。

建议顺序：

1. **暂停进一步性能改写，先完善已有能力内的意图覆盖。** 对“数据可靠吗”“有没有低氧风险”等问题，沿用现有本轮当前水质查询及授权，明确 freshness/quality/当前规则是否可评估；先做路由设计与离线安全测试，不增加 Tool、阈值逻辑或开放域聊天。
2. **小幅优化 Chat 状态句和建议去重。** 重点减少固定提示重复，而非隐藏限制或扩展自由文本。复用同一 SourceSummary，无额外请求；变更展示实现后照常刷新 Scope、重新审批。
3. **若仍需提速，先加最小脱敏计时，再决定是否继续 QQ 校验优化。** 优先覆盖准入/排队、两次 SDK HTTP、Scope/配置、Tool/DB、SDK close/join、render、发送前复核/HTTP、history。使用单调时钟、嵌套跨度与计数；不记录正文/Key/OpenID，不重读水质，不删除不同时间边界的复核。
4. 在离线合成条件覆盖 fresh、partial、stale/offline、可靠低氧 HIT 后，再申请一次少量真实体验验收。客户端显示、API 接受、Usage估算与账单继续分开。没有新计时证据前，不调整两次模型请求或降低安全门禁。

不建议本阶段引入 SDK 进程隔离、全局缓存、模型参数调优或更换模型来追求未经测量的收益。

## 7. 核验完成与保留事项

已完成报告交叉核对、两条正文哈希匹配、时间/Decimal 费用复算、实现摘要核对及文档链接/差异检查；既有目录 13 个文件字节摘要前后不变。仅新增本文并加入文档索引，不修改运行时或 Scope。

未执行：真实联网重试、数据库读取/写入、SDK故障注入、长时间压力测试、完整 Python/Node 重跑。原因：本轮为只读验收总结，以上既不必要，也未获真实实验授权。

仍待后续验证：分阶段真实耗时、长期并发可靠性、新鲜低氧规则群展示、未来新路由/更短模板的人工可读性，以及云平台最终账单。到此停止，等待人工审阅。

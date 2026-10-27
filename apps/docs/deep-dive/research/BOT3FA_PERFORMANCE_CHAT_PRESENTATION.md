# BOT-3F-A：QQ Bot 性能与聊天展示研究

核验日期：2026-10-27（北京时间）。项目：`Fishery_AI_Prototype`。
源码基线：`main` / `85199370d1e4fdf7066a518a175e246d18d79319`；调查开始时工作树干净。
本阶段只新增研究文档；没有实现 Chat Mode、改动运行时、刷新 Scope 或开展真实联网实验。

## 1. 结论与证据边界

1. **慢回复包含可观的本地程序开销，不能全部归因于 Qwen。** 最近真实试用五轮的 Assistant 耗时为 6.58～10.53 秒；内存 HTTP 几乎立即返回时，本轮独立五次离线执行仍平均需要 4.41 秒。
2. **重复完整校验值得优先优化。** 一组五轮采样中，每轮平均构造真实持续会话 Scope 158.8 次、读取配置/Policy 绑定快照 138.4 次；其中包含嵌套校验及 watchdog 的并发复核。Monitoring 服务读取平均约 4.4 毫秒，不能把 Trace 中约 0.9 秒的 Tool 步骤全部解释为 SQLite 慢。
3. **真实模型和 QQ 网络的各自占比仍证据不足。** 旧 Trace 没有逐次 HTTP 耗时、真实 Gateway 接收时刻、QQ 发送起止时刻。Assistant 结束到 QQ API 接受另有 2.49～7.91 秒，但此段还包含交付校验和本地等待。
4. **简洁回复可先改展示，不改 Agent。** 同一 SourceSummary、同一封闭解释校验结果，加上服务器已确定的提问重点，足以生成 Chat / Detailed 两种文本；无需额外模型请求或数据库查询。
5. 建议 BOT-3F-B 先补分阶段计时、实现纯展示分支，再按证据消除同一校验边界内的重复计算。保留两次模型请求、全部权限时间边界和 SDK 资源关闭确认。

证据分类：下文“真实记录”指既有脱敏文件；“离线实测”指合成数据库、真实 SDK 类与 MockTransport；“建议”均未进入运行时代码。没有读取真实 Key、原始 QQ 私聊/群聊正文或既有业务数据库。

## 2. 当前完整调用链

```text
QQ Gateway 认证群 @ 事件 → 有界事件队列 → Router
  ├─ 固定只读指令 / 问候 / 帮助 / 澄清：原程序答复，不调用模型
  └─ 水质 AI：身份、设备、消息时效、去重、容量/单飞
       → RunConsent 检查与原子预留 → 私有 TurnLease / Service / Handle
       → Scheduler → 权限、Scope、Policy、History 快照复核
       → 原 Agent：Qwen 请求① → 本轮 Monitoring Tool → Qwen 请求②
       → Source / Commit Gate → 封闭解释校验与文本渲染
       → Delivery Owner → 发送前复核 → 唯一被动回复 → QQ API 接受
       → 交付检查点 → History Commit → 任务报告
```

SDK Client 关闭、请求线程加入和资源确认发生在**每次 SDK 请求内部**，并非只在整轮结束时执行一次。watchdog 同时复核运行许可和在途任务。`QQ_REPLY_API_ACCEPTED` 是平台接受，不能替代用户客户端显示确认。

主要代码依据（路径均相对项目根）：

| 环节 | 实际入口 |
|---|---|
| 认证事件及消费 | `apps/qq_bot/gateway.py:112` `_work()`；`:170` `_dispatch_authenticated()` |
| 准入、执行、历史提交 | `apps/qq_bot/ai_coordinator.py:153` `prepare()`；`:230` `execute()`；`:266` `accept_delivery()` |
| 运行许可复核 | `apps/qq_bot/session_run.py:92` `check()`；`apps/qq_bot/session_run_trial.py:107` `_validate_authorization()` |
| 排队与监督 | `apps/qq_bot/ai_scheduler.py:65` `submit()`；`:193` `_ai_loop()`；`:241` `_watch()` |
| SDK 生命周期 | `apps/ai_backend/openai_compatible_adapter.py:395` `_bridge()`；`apps/ai_backend/sdk_resources.py:64` `settle()` |
| 来源及解释 | `apps/ai_service/channel.py:123` `SourceSummary`；`apps/ai_service/channel_presentation.py:105` `assess_explanation()` |
| 单次发送 | `apps/qq_bot/ai_delivery.py:98` `PassiveReplyOwner.send()`；`:141` `DeliveryOwner.deliver()` |

## 3. 最近真实试用：已能证明什么

只投影以下已存在目录中的数值、状态与时间字段：

`outputs/qq-bot/test-runs/test-20261027T062438Z-98d20ec95f3d4f3eb67833138e14a936/`

读取范围为 `result.json`、`turn-N.trace.jsonl`、`turn-N.delivery.json`、`turn-N.result.json`。未读取批准正文、used 文件、模型正文或原始平台消息。

| Turn | Assistant 总耗时 s | 内层 Agent 耗时 s | Tool 步骤 s | Assistant 结束→API 接受 s | 已提交历史数（执行前） |
|---|---:|---:|---:|---:|---:|
| 1 | 10.531 | 10.406 | 0.891 | 2.486 | 0 |
| 2 | 8.171 | 7.828 | 0.922 | 7.870 | 1 |
| 3 | 7.578 | 7.188 | 0.906 | 7.906 | 2 |
| 4 | 6.578 | 6.203 | 0.813 | 7.529 | 3 |
| 5 | 7.063 | 6.750 | 0.953 | 7.784 | 4 |
| 均值 | 7.984 | 7.675 | 0.897 | 6.715 | — |

五轮均为两次模型请求、一次 Tool 步骤；最终逐轮报告均 `verified=true`、`HISTORY_COMMITTED`、SDK `CLOSED`，五次 API 接受、零未知交付。总报告记录 `OPERATOR_INTERRUPTED`，`report_saved=true`、`completed=true`。用户客户端显示是用户已提供的人工验收事实，程序字段没有代替用户作此确认。

**计时不能相加误读：**

- Agent 是 Assistant 的内层区间，Tool 又嵌在 Agent 内；三者不能相加。
- Tool 计时包住 `executor.execute()`，包括参数校验及受保护 Handler，不是单条 SQL 耗时。见 `apps/ai_backend/tool_conversation.py:411`。
- Assistant 开始至 API 接受约 13.02～16.04 秒，仍不是“Gateway 收到至客户端显示”的完整端到端延迟。
- “Assistant 结束→API 接受”不是 QQ API 的纯往返时间；不使用文件修改时间反推网络阶段。
- 历史投影从 2 字节增至 1863 字节，两次模型请求的合计输入 Token 从 3472 增至 5306；样本中耗时并未随之单调上升，不能据此归因于长历史。
- `JsonlTraceSink.record_tool_conversation()` 只记录模型请求序号、结果及 Usage，没有逐模型起止时间；`record_assistant()` 记录整轮耗时和历史预算。依据：`apps/ai_backend/observability.py:32`、`:82`。

因此：两次远端请求是必经串行路径，**但尚不能证明它们占据主要延迟，更不能给出真实 Qwen 单请求耗时或稳定 P95。**

## 4. 离线分阶段实测

### 4.1 方法与可重复证据

复用 `apps/qq_bot/tests/test_session_run_trial.py` 的真实类型化持续会话夹具：新建临时 Monitoring v2、合成 SIMULATOR 数据、假群和成员、真实 AsyncOpenAI 类、内存 HTTP。夹具禁止 socket 联网；凭据供应器拒绝真实密钥读取。每组五个不同消息，依次覆盖全部水质、溶解氧、pH、水温和整体状态。

只在研究进程中包装现有函数做 `perf_counter_ns()` 计时，不修改源码、不跳过原检查。每组审批一次假 Run；每轮保持两次假模型请求、一次实际合成 Monitoring 读取和一次假 QQ POST。每组检查数据库字节摘要不变，结束时关闭 Fixture 资源并检查 Scheduler 线程退出。

本机非敏感证据目录（gitignore；不属于发布代码）：

`outputs/test-tmp/bot3fa-20261027T063528Z-da665c78/`

- `before.json`：初始 HEAD、工作树及已跟踪文件摘要。
- `real_projection.json`、`real_timing_table.json`：既有真实记录的允许字段投影。
- `profile_offline.py`、`offline_profile.json`：五轮基线、五轮计时、五轮注入延迟对照。
- `offline_details.json`：另五轮细分计时。
- `readability_samples.py`、`readability_samples.json`：纯合成展示草案及长度比较。

复跑研究脚本只使用上述合成夹具；必须从 Prototype 根执行，例如：

```powershell
.\.venv\Scripts\python.exe -X utf8 -I -B .\outputs\test-tmp\bot3fa-20261027T063528Z-da665c78\profile_offline.py
```

临时研究脚本依赖当前测试夹具，不作为长期测试入口或可迁移的产品实现。

### 4.2 组间对照

| 条件，每组 n=5 | 模拟 Gateway 分发→准入均值 | 分发→任务结束/历史完成均值 |
|---|---:|---:|
| 内存 HTTP 立即返回 | 459 ms | 4413 ms |
| 同条件，包装主要函数计时 | 480 ms | 4395 ms |
| 每次假模型 HTTP 人为等待 150 ms | 482 ms | 4754 ms |
| 另一次细分采样，同样不加网络延迟 | 435 ms | 3063 ms |

前三组各十次模型 HTTP 的均值分别为 0.395、0.322、158.879 ms。注入延迟是人为控制量，不是 Qwen 实际性能。细分组的五轮总耗时为 2.35～3.82 秒，而前面计时组为 3.96～4.84 秒；**没有修改软件，数值仍受缓存、磁盘和主机调度影响，不能当作优化收益。**

模拟分发使用已认证的 Fake Gateway 入队后立即交给 Router，未测真实接收线程/网络等待。调用 `scheduler.wait()` 结束的区间还包含最终任务收尾；不能与历史 Assistant Trace 直接作性能优劣对比。

### 4.3 调用次数与局部耗时

主要计时组每轮均值：

| 操作 | 次数/Turn | 解释 |
|---|---:|---|
| 真实试用 `trial_scope()` | 158.8 | 完整构建及文件摘要；包含下层 `session_scope()` |
| 下层 `session_scope()` | 158.8 | 与上一行嵌套，不能算成额外 158.8 次独立顶层检查 |
| `inputs_snapshot()` | 138.4 | 重载 access、AI、实例配置及两级 Policy，核对绑定 |
| Run `check()` | 89.0 | 多个安全边界以及嵌套调用 |
| watchdog 的 `validate_plan()` | 10.0 | 每次又触发完整服务/历史授权校验 |
| Monitoring `capture_water()` | 1.0 | 每轮重新查询，未复用旧水质 |

Scope 调用按线程分布为准入线程 19.0、AI worker 36.0、delivery 38.0、watchdog 65.8 次/Turn。watchdog 在一次检查完成后再等待约 20 ms，不代表每秒稳定执行 50 次完整检查。

细分采样组每轮均值如下；方法区间存在嵌套，不能把各行相加：

| 局部阶段 | 耗时 | 边界限制 |
|---|---:|---|
| 空队列：准入返回→`execute()` 开始 | 0.071 ms | 非高并发排队测试 |
| `ToolExecutor.execute()` | 181.59 ms | 含 Handler 授权及参数/结果校验 |
| Monitoring 服务 `capture_water()` | 2.50 ms | 含 SQLite 读取和业务投影；前一采样组为 4.40 ms |
| 解释校验 | 0.041 ms | 封闭 JSON 枚举合同 |
| 完整现有回复渲染 | 0.069 ms | 包含上述解释校验 |
| SourceSummary 文本 | 0.012 ms | 包含于回复渲染 |
| SDK Client `close()` | 0.007 ms/请求 | 立即响应的 MockTransport，不代表黑洞清理耗时 |
| 两次 SDK 请求线程 `join()` 合计 | 2.53 ms/Turn | 仅正常合作关闭样例 |
| 两次资源 `settle()` 合计 | 0.015 ms/Turn | 资源失败门禁仍保留 |
| `QQAPI.reply()` | 230.13 ms | 含发送前授权回调；假 HTTP 无真实网络延迟 |
| ConversationStore `commit()` | 0.333 ms | 更外层 `accept_delivery()` 还要再次校验 |

第一计时组中 Scope 下层累计包围时间平均约 4.95 秒/Turn，配置快照累计约 1.29 秒/Turn。它们跨线程重叠，也包含等待及包装开销，**不是 CPU 时间，更不是可直接从端到端延迟扣除的节省量。**

### 4.4 有依据的根因与待补计时

明确的重复路径包括：`SessionTrialRun.check()` → authority → `_validate_authorization()` → 基类 `check()` → 配置快照和 Scope；Turn 的检查闭包又组合 Run 授权与同一个运行检查；服务、Handler、发送前回调和 watchdog 再分别进入这些路径。

交付期间 `deliver()`、`claim_delivery()`、`PassiveReplyOwner.send()`、HTTP 前回调和 `accept_delivery()` 都有复核。**发送前和历史提交前的检查有独立安全意义，不能整体删除。** 应优化的是同一边界中嵌套获得同一份完整校验证据的重复工作。

下一步计时建议：新增允许字段的单调时钟跨度与父子关系，覆盖 `gateway_received`、`admitted`、`run_started`、模型请求①/②、Tool/Monitoring、Scope/绑定、SDK close/join、render、QQ HTTP、checkpoint、history、finished。QQ API 的计时拆成 token 刷新、发送前复核、HTTP 往返；模型适配器也拆出本地准入、HTTP、解码与关闭。

仅记录耗时、请求序号、调用次数、状态码及同轮关联 ID；不新增 QQ 正文、完整 OpenID、Prompt、工具数据、模型正文、URL 凭据或请求头。不得因为计时再次读取水质。关键失败路径继续按现有账本/报告合同 fail-closed。

## 5. 回复为什么像技术报告

当前 `render_channel_reply()` 固定生成 A/B/C：

- A 列出实例/设备、三个 ISO 时间、英文质量/新鲜度/连接码、全部三个指标、规则及长限制说明。
- B 并非任意模型散文：模型只选择受限的指标/规则/建议枚举，程序再渲染通用中文句子；其中重复说明“留存窗口”“不是模型独立诊断”“没有重新采样”。
- C 再说明 SIMULATOR、非真实硬件、规则仅本地实验、不能替代专业判断和发送时未采样。
- 交付前缀还重复“受控 Qwen 持续会话 · SIMULATOR”。

模型合同已经允许 `metrics` 按问题选择重点，确定性意图路由也已产生 `focus`，但 A 仍调用 `SourceSummary.presentation()` 输出全部指标，所以追问 pH 仍像重新打印整份报告。依据：`apps/qq_bot/intent.py:43` `classify()`、`apps/ai_service/channel_conversation.py` 的 `ChannelHistorySnapshot.focus`、`apps/ai_service/channel_presentation.py:154`。

此外，现有渲染先校验完整 fallback 是否放得下，再尝试解释文本。未来 Chat 分支应分别预算自己的完整安全文本，不应被 Detailed fallback 长度提前阻断；失败时仍不可截断来源和限制。

| 信息 | Chat 必须保留 | Detailed / 本地报告 |
|---|---|---|
| 所问指标、数值、单位及该指标有效性 | 是；值只能来自本轮 SourceSummary | 全部指标 |
| SIMULATOR 与设备身份 | 每条事实回复保留简短标识 | 实例完整身份留本机，群内仅按已批准披露范围 |
| 观测时间、时区、评估时效 | 是；可简短，不把评估时间当采样时间 | 完整 observed/received/evaluated 及状态码 |
| stale/offline/missing/invalid/partial/unknown | 必须保留对应中文警示 | 原始状态码与细分解释 |
| 未询问指标上的严重命中或缺测 | 不得因聚焦而隐藏 | 全部规则及证据索引 |
| 业务规则与 AI 建议的区别、建议未执行 | 简短标注“系统实验规则”“AI 解释/建议” | 原 A/B/C 说明 |
| Scope、qualification、revision、预算余额、SDK 线程细节、哈希 | 普通成功回复不需要 | 本机脱敏报告；操作者摘要不输出密钥/完整个人标识 |
| 模型原始自由文本 | 两种模式都禁止直接展示 | 普通日志同样不保存 |

## 6. Chat 与 Detailed 设计

### 6.1 同源、单次计算

建议纯展示输入为：**本轮 SourceSummary + 已校验解释计划 + 服务器认证的 focus + 固定展示模式**。两种模式共享验证结果，均不重新查询 DB 或调用模型。focus 来自本轮已绑定快照，不能信任模型自选字段来屏蔽其他风险。

Chat 可作为新持续会话试用的默认展示；原 FAST、双轮及现有 renderer 的缺省行为先保留 Detailed，避免无关路径变化。展示模式绑定新计划/Scope，不能用进程全局可变变量影响不同成员；不改变群、设备、费用或工具权限。

Chat 采用三层短句，不强制 A/B/C 大标题：直接读数/系统事实 → 已校验 AI 要点 → 来源/时间限制。可把重复的说明合并一次，但不得合并事实与建议的身份。

时间从实际 ISO 值转换为 `Asia/Shanghai`，显示“北京时间 UTC+08”；跨日带日期，无值或解析失败显示未知。不能用当前系统时间补造观测时间。对 stale/offline 必须先提示“上次留存读数”，而不是“现在”。

### 6.2 建议样例（全是离线合成文本，不是实际鱼塘状态）

溶解氧追问，Chat：

```text
SIMULATOR 模拟数据 · sim-pond-1
溶解氧：6.5 mg/L。
系统实验规则：本窗口未触发水质规则，不等于专业健康判断。
AI 解释要点（已校验）：请人工核对后续观测。
观测 10月26日 08:00；评估 08:00:02（北京时间 UTC+08）。
评估时有效、新鲜、在线；本次查询未重新采样。
```

pH 缺测时，即使只追问溶解氧：

```text
SIMULATOR 模拟数据 · sim-pond-1
留存溶解氧为 6.5 mg/L；pH 缺测，整体状态仍不能完整确认。
AI 解释要点（已校验）：请人工核对后续观测。
观测 10月26日 08:00；评估 08:00:02（北京时间 UTC+08）。
评估时部分有效、新鲜、在线；本次查询未重新采样。
```

过期且离线时：先说“数据过期、设备离线，以下只是上次留存值”，再显示相关指标、实际观测时间和已校验检查上报建议。无数据则直接“尚无可用观测，状态未知”，不显示零值冒充读数。

Detailed 继续保留完整 A/B/C，包括全部三个指标、三种时间、质量状态、全部规则命中、建议及完整来源限制；它仍是封闭解释，不是放开模型自由文本。

### 6.3 长度对照

用当前 renderer 渲染合成 SourceSummary，与研究目录中的纯格式草案比较。未读取真实 QQ 消息文本；字符数不含 Delivery 前缀，未将短文本直接接入生产交付。

| 场景 | 当前 Detailed 字符数 | Chat 草案字符数 | 减少 |
|---|---:|---:|---:|
| 全部水质 | 582 | 178 | 69.4% |
| 溶解氧追问 | 528 | 160 | 69.7% |
| pH 追问 | 527 | 154 | 70.8% |
| 水温查询 | 527 | 158 | 70.0% |
| pH 缺测但问溶解氧 | 557 | 177 | 68.2% |
| stale / offline | 553 | 177 | 68.0% |
| 严重低氧但问水温 | 627 | 165 | 73.7% |
| 无数据 | 557 | 218 | 60.9% |

该表只证明**可以合并展示冗余**，不是中文可读性人工验收结果，也不意味着真实模型会更快。尚未实现新的安全渲染器及其完整回归；草案不作为格式校验或真实交付许可。

### 6.4 详细请求、进度和友好错误

- 首版可先由本机配置固定 Chat / Detailed；如增加“详细报告”或 `/详细`，需明确的确定性路由，仅影响本条合法问答的展示，不扩大意图/工具。当前这些新指令尚不支持。
- 在同一轮内部切换展示，不多调用模型；新 QQ 消息若问当前状态，仍按正常预算重新取本轮事实，不能把旧报告当作当前数据重发。首版不增加报告缓存或聊天能力。
- **首版不发送“正在查询”。** 当前 `msg_seq=1`、PassiveReplyOwner 只允许一次提交；额外进度消息会改变回复所有权。进度仅显示在本机终端，不假定有可用的 QQ 输入中提示 API 或主动消息权限。
- BUSY：“当前正在处理其他问题，请稍后再问。”额度耗尽：“本次 AI 额度已用完，固定查询仍可使用。”授权拒绝不披露设备/配置。SDK 故障：“AI 已暂停，请操作者检查；不会自动重试。”交付未知只记本机，不能为解释失败再补发第二条消息。
- 保持明确换行，减少英文码和长 ISO 时间，避免 Markdown 大表格/代码围栏。当前代码使用纯文本 `msg_type=0`；AI 总文本上限 1600 字符、底层通道校验 1800 字符，均含最终文本长度校验。它们是**当前实现限制**，本轮未重新核验 QQ 官方对所有消息类型的最新平台上限；不能宣称等同平台最大容量。依据：`apps/qq_bot/transport.py:230` `reply()`。

## 7. BOT-3F-B 最小实施顺序

### B0：先补计时

补齐第 4.4 节的阶段跨度，先确认真实交付长尾到底是权限、锁、token 刷新还是 QQ HTTP。优先通过可注入的离线观察器和脱敏字段实现，不调整模型预算或安全门禁。

### B1：纯展示分支

复用封闭解释计划，增加 Chat / Detailed；中文状态翻译、按 focus 投影、所有严重命中与缺测限制保留、总长度完整预算。模型 JSON 合同尽量保持不变；不为中文更自然而放行自由字段。

### B2：有针对性的重复计算优化

对同一入口内嵌套调用共享一次完整验证产生的不可伪造内部证据，避免每层重新读相同文件和重算 Scope。仍在准入、执行、Tool、模型 I/O、发送前、历史提交前及 watchdog 要求的时间边界检查最新权限和资源状态。

不得采用“整个 Run 都不再读取配置”的全程缓存、只看 mtime 的信任缓存、任意 TTL 内跳过撤权检查，或去掉发送前回调。若无法证明边界等价，先保留该处开销，只交付计时和展示优化。

两次模型调用分别承担产生 Tool Call 与读取 Tool 结果后的解释。首版不减少请求次数，不提前用旧数据喂模型，不用纯模板冒充 AI 执行，也不调整模型、预算或 SDK Client 池化；这些改变需另立证据和合同审查。

| 预计文件 | 最小职责；实际实施前再确认 |
|---|---|
| `apps/ai_service/channel_presentation.py` | 共用解释校验结果、纯 Chat/Detailed 渲染；不改来源合同 |
| `apps/qq_bot/ai_delivery.py` | 接收服务器 focus/展示模式，完整长度和 Receipt 哈希保护；单次 Owner 不变 |
| `apps/qq_bot/ai_coordinator.py`、`ai_scheduler.py` | 阶段计时和计划展示上下文；不改变队列、单飞、期限 |
| `apps/qq_bot/session_run.py`、`session_run_trial.py` | 计数/计时、同一边界的验证复用（有独立证据和测试才做） |
| `apps/qq_bot/trial_configuration.py` | 配置快照计时；如优化，仍完整检查真实配置内容及权限 |
| `apps/qq_bot/transport.py` | 区分发送前校验与 HTTP 时长，不变 token/重试/URL 规则 |
| `apps/ai_backend/observability.py`、SDK Adapter | 如现有薄观察器不足，才添加数值计时；不改变 SDK 生命周期 |
| `apps/qq_bot/intent.py` | 仅在批准本条详细请求语法后增加确定性展示路由；非首版必需 |
| Scope 准备资源、对应测试和文档 | 按实际变更重算，不能改写旧批准/回执 |

不新增 Agent、Tool、数据库、Provider、后台任务系统或权限平台。

## 8. 安全边界、Scope 与 Web 兼容性

必须保持：RunConsent 原子费用预留与不退款策略、每轮两次请求上限、90 秒、零重试、群/成员/设备/实例绑定、SDK 资源租约及 sticky 隔离、Source / Commit Gate、发送前复核、未知交付不重发、API 接受后按文本哈希/revision 提交历史。

Chat 成功历史必须记录**实际被接受的安全文本及其投影**，不能仍用旧 Detailed 文本的哈希或未展示的模型原文。清空与交付竞态、撤权及历史快照失效条件保持原样。

当前 `render_channel_reply()` 的生产调用方是 QQ 交付和本机 QQ 试用；Web 不直接调用该函数。但 `channel.py`、`service.py`、Prompt、SDK 与 observability 属于共享层或被共享 Service 导入，不能据此宣称修改完全不影响 Web。

- 只改 QQ 展示分支，保持旧签名缺省与 Web DTO：预期风险较低，属于代码审查判断，仍需 Normal/Streaming、Knowledge、Monitoring 和 Source/Commit 回归。
- 改共享 Adapter/Trace 或授权验证：风险更高，必须验证异常、取消、清理及 Web 流式行为；不能借性能任务重构 Agent。
- 当前 Scope 已绑定展示源码、Prompt/Tool、历史、SDK、交付及运行许可实现。即使仅换中文或加计时，只要被指纹覆盖的源码变动，也须重算受影响 Scope、重新审查准备资源并重新批准真实实验；不得复用旧单轮/双轮/持续会话批准。
- **本阶段只增加文档，不改变上述源码、Scope 准备资源、资格或既有真实回执。**

## 9. 对照测试和验收指标

| 用例 | 必须断言 |
|---|---|
| 当前全部水质、单指标追问 | 每轮两次模型请求、一次新 Tool；按重点展示；全部值来自本轮 SourceSummary |
| pH 缺测/部分无效 | 即使只问 DO，也保留整体不确定性；不说全部正常 |
| stale/offline/never_received | 分别正确表达过期、离线、未接收；未知不能写成过期或离线；历史值明确标识 |
| 低氧但问水温 | 不漏掉严重规则；不让模型选择 focus 隐藏风险 |
| 结构化输出错误、注入、超长 | 两种模式安全降级；不截断必要警示；不补推理 |
| 长历史与清空 | 历史只用于话题；本轮来源独立；清空不恢复额度 |
| 并发、队列满、重复消息 | worker/等待名额不变；BUSY 和重复消息不额外扣费/调用 |
| 授权拒绝、执行中撤权、Scope/设备改绑 | 拒绝或及时取消；零越权查询；不能被验证缓存绕过 |
| SDK 失败、取消、QQ 送达未知 | 不成功交付、不重试；未知不记成功历史；资源隔离不清零 |
| 最终报告/检查点失败 | 保留已接受或未知的真实状态；不为修复报告重复发送 |

建议验收口径：

1. 本地性能用同机同配置成对多次采样，至少 30 次/条件再给中位数/P95；分别列冷启动、热运行、队列等待、模拟网络延迟与纯本地开销。当前 n=5 数据只用于定位，不作为稳定 SLA。
2. 每轮记录 Scope/配置快照调用次数和各线程区间，检查优化是否减少同一边界重复工作；必须同时证明撤权/Scope 修改仍会使任务失效，不只看总耗时。
3. 简洁回复软目标：普通全量约 250 字以内、单指标约 200 字以内；异常、缺测说明优先于软长度目标。所有文本继续满足现有 1600 总字符硬限制，不裁剪关键来源。
4. 用相同 SourceSummary/解释计划比较字符数、行数、非所问常规指标的重复出现、重复来源/时效警示次数，并逐项核对安全信息覆盖 100%。不能用字符压缩率代替可读性评分。
5. 人工验收确认能快速识别“读数、系统规则、AI 建议、观测时间、模拟/过期限制”；Detailed 仍能核对完整证据。真实 QQ 网络和客户端显示延迟仅在 BOT-3F-C 重新批准后测量。

## 10. 本阶段验证结果与停止点

- 共进行四组各五轮的离线成功执行：40 次内存模型 HTTP、20 次假 QQ 回复，每轮新 Tool、SDK CLOSED、成功历史提交；合成 DB 摘要不变；Fixture 清理检查 Scheduler 线程退出。
- 现有解释合同 11 项，加持续会话的新来源/清空、普通失败与未知送达、SDK 失败隔离、Scope 撤销四项：**15/15 通过，20.272 秒**。不是完整 Bot 或 Web 回归。
- 八种合成展示对照通过现有解释校验；Chat 只是临时研究格式草案，没有进入服务或真实发送。
- 没有运行完整 Python/Node 回归：本阶段没有修改运行代码、测试或前端。完整回归列入 BOT-3F-B，而不是把旧基线当作本轮测试结果。
- 未验证：真实逐次 Qwen HTTP、QQ HTTP 往返、Gateway 接收至客户端显示时间；生产网络黑洞的关闭耗时；真实 Chat 文案的客户端效果。原因分别为旧计时缺失及本轮禁止联网/未批准实现。

建议人工先审阅：Chat 的信息密度、是否接受保留一行“AI 解释要点”、首版是否只用本机配置选择 Detailed。通过后再实施 BOT-3F-B；本轮不进入 B 或真实 F-C。

# BOT-3B-2：有界 AI 调度与单次 QQ 交付（离线）

后续装配：[BOT-3C-FAST](BOT3C_FAST_QWEN_TRIAL.md)复用本页调度/回复owner，新增严格类型化、独立审批的试用路径；默认Fake和普通QQ CLI保持原边界。以下为3B-2阶段记录，不能当作真实联网通过证明。

核验日期：2026-10-25。仅 Fishery_AI_Prototype；延续 [BOT-3B-1](BOT3B1_QQ_AI_BOUNDARY.md)。

## 1. 当前范围

已实现有界任务调度、协作取消及单次交付协调。**所有新增交付仅能装配精确类型的 OfflineQQGateway**，其内部使用 QQAPI + httpx.MockTransport，无外网连接路径、密钥读取或真实 QQ 客户端。

真实 CLI 不装配调度器，`/问AI` 继续 AI_DISABLED。Monitoring-only Scope 仍为 candidate，`offline_only=true / can_deliver=false / model_text_verified=false` 不变。未批准真实 Provider、QQ AI 联调或新的发布资格；不以“Fake API 接受”冒充真实通信通过。

```text
合成 QQ /问AI → 原 ingress 权限/时效/去重/限频 → QQAICoordinator.prepare
  → QQAIJobScheduler（一个 AI worker + 两个等待名额）
  → 原 AI Service / Agent SINGLE_ROUND 1/1/2 → 同轮 SourceSummary
  → 独立 DeliveryOwner / delivery worker → QQAPI → MockTransport
                       ↑ 发送前再次复核身份/群/成员/设备/Policy/Scope/期限
```

不复制 Agent 循环、Monitoring SQL、规则或来源判定。固定命令仍走原 QQAdapter；原 QQGateway 心跳不在 AI worker 内执行。离线调用者只应将明确的 `/问AI` 交给 scheduler；BUSY 等错误返回安全代码，本轮没有新增真实群消息路由或错误回复。

## 2. 文件与职责

| 文件（相对项目根） | 职责 |
|---|---|
| `apps/qq_bot/ai_scheduler.py` | 调度、会话单飞、队列和总期限、权限监督、取消、关闭、有限状态观察与接受回执 |
| `apps/qq_bot/ai_delivery.py` | 单次提交所有权、完整事实文本、发送前复核、接受/拒绝/未知；精确 Fake QQ 装配 |
| `apps/qq_bot/ai_coordinator.py` | 复用 B-1 准入/执行，冻结消息上下文；绑定唯一 scheduler；原计划上原子标记交付 claim |
| `apps/ai_service/channel.py` | 原来源与 candidate 合同不变；OfflineChannelProvider 增加可取消的假 I/O 等待点 |
| `apps/qq_bot/tests/test_ai_scheduler.py` | 新建临时 SQLite、固定合成窗口、Fake Provider/HTTP/Gateway、并发与线程回收测试 |

没有新增依赖、数据库 Schema、Tool Definition、Prompt、聊天记忆或 AI 写工具。实际 CLI、Web 的装配方式不变。

## 3. 资源与期限

| 项目 | 本轮限制 |
|---|---|
| AI 并行执行 | 一个 Bot/coordinator 装配只允许一个 scheduler、一个 AI worker |
| AI 等待 | 最多两个额外任务；空闲 worker 的首个 runnable 名额在准入时预留 |
| 未完成总量 | 最多三个，**包含交付中和等待交付**，防止发送慢时结果积压 |
| 会话 | App / 群 / 成员 / 实例 / 冻结绑定版本 / 设备的组合，最多一个未完成任务 |
| 等待期限 | 从准入开始最多 10s；受更短总期限约束，FIFO，不续期 |
| 总期限 | `min(独立 AI 预算≤90s, 原消息剩余300s−15s)`；包含等待、模型、工具和交付 |
| 模型预算 | 沿用 B-1 独立输出预算，默认512、上限1024；工具循环仍1/1/2 |
| 线程 | 固定三个非 daemon 线程：AI、交付、监督；不按请求创建线程 |
| 终态与接受回执 | 分别最多32条，仅任务ID、安全代码、接受时间/文本摘要等元数据 |
| 消息提交 claim | 最多128个、保留至原消息300s窗口结束；容量满拒绝，不提前挤出活跃 claim |

已有成员/群去重、限频仍在独立 AI ingress 执行；并未增加真实费用总账。内存去重不是跨进程/重启的持久化 exactly-once 保证。未来多 Bot 进程必须另行设计共享配额，本轮不引入 Redis。

## 4. 状态与取消

```text
ADMITTED（预留空闲 worker）或 QUEUED
  → RUNNING → COMPLETED → DELIVERY_PENDING → DELIVERING → DELIVERED
任一提交前阶段 → CANCELLED / FAILED / EXPIRED
执行中取消 → CANCEL_REQUESTED → 等执行 owner 返回后结束
已提交但未确认接受 → DELIVERY_UNKNOWN
```

COMPLETED 只表示 Backend Final、来源门禁及 Trace Commit 成功，尚未提交 QQ。结果未完成、无来源、Commit失败、权限改变或 Scope 不匹配，都不能成为成功交付候选。

监督线程检查期限、权限、Policy、设备/实例绑定和 Fake Gateway 连接状态。撤权、解绑、断线、超时、停机均阻止旧任务交付。取消同时设置任务事件并调用原 RequestHandle.cancel / abort_io，Fake Provider 的 handle.bind 钩子主动释放等待；不以 Future.cancel 代替实际 I/O 中断。

取消运行中的任务时，worker 名额要等函数退出才释放，不会启动第二个 worker 补位。Gateway 恢复连接不自动重放旧任务；新消息重新准入。

`close()` 停止准入、取消所有任务、终止 Fake HTTP 等待并在默认3s合计 join 期限内收尾。关闭可重复调用。启动部分线程失败也回收已启动线程。若 I/O 不合作，明确报告 AI_SHUTDOWN_INCOMPLETE，保留停止状态和 scheduler 绑定，不宣称线程已经退出；测试随后释放阻塞并再次关闭。Python 线程没有安全强杀能力，真实 SDK 中断仍须 BOT-3C 单独验收。

## 5. 一次交付及未知结果

1. 验证 coordinator 内原 plan / 原 result 对象、Backend成功、同轮来源、candidate Scope 与全部权限。
2. 只呈现本轮可信 SourceSummary；模型正文隔离，不因模型说“全部正常”而覆盖真实来源。保留 SIMULATOR、观测/接收/评估时间、质量、新鲜度、连接及无法判断说明。
3. 标明这些状态属于原评估时刻，发送时没有重新采样。没有重读数据库补一份新来源冒充原 Tool 证据。
4. 清理 mention/控制字符，完整文本最多1600字符（原 QQAPI 上限1800）；超长整条拒绝 AI_REPLY_TOO_LONG，不裁掉来源/时效说明后宣称完整。
5. 原计划原子 claim，加原消息 App/群/msg_id claim；即使误建第二个 Fake DeliveryOwner，也不能再次提交同一结果。
6. 在模拟 HTTP 提交前再次检查取消、群/成员/设备、权限generation、Policy、Scope和期限。`msg_id` 指向原消息，`msg_seq=1 / msg_type=0`。无主动发送入口。

| 结果 | 表达与处理 |
|---|---|
| API返回有效接受ID | DELIVERED / QQ_REPLY_API_ACCEPTED；`api_accepted=true`，`client_display_confirmed=false` |
| API明确拒绝 | FAILED；保留错误代码，不重试、不重新推理 |
| HTTP超时、2xx无接受ID、响应无法确认 | DELIVERY_UNKNOWN；可能已提交，不重试、不补偿推理 |
| 提交前撤权/过期/取消 | 拒绝发送；不会误记为已发送 |
| 提交后取消/停机/断线 | 若不能确认接受，保守记未知；不能保证撤回已提交消息 |

`take_acceptances()` 提供未来 History owner 可消费的有限接受元数据（任务ID、API接受时间、完整文本SHA-256），取走后清空；没有保存聊天历史，也没有用户已读确认。未知/失败结果不会进入接受队列。

## 6. 离线验证

在 Prototype 根目录运行，所有业务数据由测试新建；不读取 access.json、BOT-2C实例、默认用户库、真实密钥或 Management 数据：

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
$env:TEMP = Join-Path $PWD 'outputs/test-tmp'; $env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -X utf8 -B -m unittest apps.qq_bot.tests.test_ai_scheduler apps.qq_bot.tests.test_ai_coordinator
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s apps/qq_bot/tests -t .
.\.venv\Scripts\python.exe -X utf8 -B scripts/dev/run_tests.py management
```

新专项40项覆盖：成功、并发三成员、每会话单飞、重复原消息、FIFO等待/总期限/更短预算/QQ15s余量、单 worker、排队/运行取消、权限/Policy/设备实例变化、断线和不重放、发送积压、接受/拒绝/未知、发送中取消/关闭、完整来源与超长拒绝、Source/Commit失败、NO_DATA/stale/offline/partial/missing/invalid、固定查询响应、原 Gateway pump 心跳ACK、真实 Adapter仍AI_DISABLED、误建第二个scheduler/owner拒绝、部分启动失败、非合作I/O关闭错误，以及B-1过期未执行计划的兼容清理。新用例禁止 socket 外连，HTTP仅MockTransport。

最终结果（项目 `.venv` Python 3.12.14）：新增调度专项 **40/40**，连同 B-1 协调专项 **71/71**；完整管理回归 **762/762 Python（含186项Bot）+ 116/116 Node（11文件）**，Python阶段161.549s，均退出0。覆盖原 Web Normal/Streaming、三个只读Tool、Monitoring、Knowledge、Simulator及HTTP链路；这些均为离线回归，不等于真实模型/QQ验收。

五个相关Python文件 AST 解析和 `git diff --check` 通过，新增文档及其引用路径有效。工作树开始时已有 `EVENT_ACK.md` 删除，造成 README/BUILD_RUN/ROADMAP 三处既有链接失效；本轮保留该删除和其他已有改动，没有恢复或删除用户文件。

未连接真实QQ/Provider/NPU，未读取密钥，未打开现有业务实例，未修改Management、旧Runtime、真实数据或Schema；未commit/push。测试只留下必要的非敏感记录，临时fixture和本机模拟连接按测试生命周期关闭。

## 7. BOT-3C 前置条件（尚未实施/授权）

后续状态见 [BOT-3C-1 准备结果](BOT3C1_REAL_AI_PREPARATION.md)：已补Fake统一路由、独立候选预检和SDK内存HTTP测试；真实授权/装配及不合作SDK清理仍阻塞，以下真实联调条件尚未获批。

- 人工审核本轮离线协议与 SourceSummary-only 回复策略；未核验模型正文的真实群展示须另行定义安全策略，不能直接拼入答复。
- 单独批准指定模型、Provider、输出/费用/请求次数、群/成员、实例与设备；本轮不能自动读取实际密钥或业务实例。
- 给 Monitoring-only 真实执行建立正确的候选到本地实验资格及 Scope，不能改 can_deliver=true 或复用 Fake candidate 冒充资格。
- 增加经过审核的真实 Delivery transport / Gate，并由真实 Gateway 生命周期通知调度器；消息分发要统一成功、BUSY、失败回复的提交所有权，不得固定路径与AI路径重复回复。
- 验证真实 Provider I/O 的有界取消、平台回复时限/长度、断线恢复、撤权与发送竞态、HTTP未知不重试、Ctrl+C关闭及日志脱敏。API接受与QQ客户端显示分别人工记录。
- 没有多轮、Knowledge/历史/事件 AI Tool、主动推送、ACK/删除/设备控制；后续能力独立审批，不由开关隐式获得。

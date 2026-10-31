> 历史归档（2026-10-31）：本阶段已被后续实现替代。保留设计与验收证据；当前操作见 [启动指南](../../BUILD_RUN.md) 和 [文档入口](../../README.md)。

# BOT-3E-C：真实持续会话装配与简化启动（离线验收）

日期：2026-10-27。仓库：Fishery_AI_Prototype，开始时`main / 991916a`、工作树干净。

## 1. 本轮结果与边界

新增独立的真实试用类型、Scope准备记录和PowerShell持续模式。真实SDK类、QQAPI、Gateway、Scheduler、Service、Tool和交付路径已用MockTransport及合成Monitoring验证，**本轮没有连接真实QQ/Qwen，没有读取真实密钥或现有业务实例**。

这不是把3E-B的Fake candidate改成允许联网。B的`SessionRun/SessionQwenTurn`仍要求Fake SDK且不被真实会话Transport接受。新的`SessionTrialRun/SessionTrialQwenTurn/SessionQQTransport`必须通过独立Scope检查、当前进程本机批准及原子RunConsent/TurnLease。

普通QQ CLI仍默认AI_DISABLED，原FAST及双轮入口不自动开启持续模式。所有真实联网试用留3E-D另行批准。

## 2. 修改文件与架构

| 文件 | 职责/变化 |
|---|---|
| 新`ai_service/channel_session_trial.py` | 独立真实试用Scope、RunAuthorization对象身份、每轮真实类型；复用原TrialQwenAdapter |
| 新`qq_bot/session_run_trial.py` | Scope准备核验、明确成员选择、一次本机批准、审批记录防篡改、延后凭据装配 |
| 新`qq_bot/session_run_trial_cli.py` | Check/Run、一次控制台挑战、QQ线程与主线程监督、正常/取消/故障报告 |
| 新`ai_service/resources/qq_session_run_trial.json` | 独立candidate准备记录，无qualification_id；不能单独授权执行 |
| 新`qq_bot/tests/test_session_run_trial.py` | SDK内存HTTP、Fake Gateway、持续问答、审批/故障/报告及PS检查 |
| `qq_bot/run_consent.py`、`tests/test_run_consent.py` | 只读检查与预留竞争的一次有界锁等待及两项回归；不改变费用/请求上限 |
| `qq_bot/session_run.py` | 提取共享Scope/账本/每轮Service装配钩子；保留B的公开构造器Fake限制 |
| `ai_service/channel_session_run.py` | 共享精确Mock SDK关闭包装和历史绑定检查，B仍为candidate |
| `ai_service/service.py` | 增加明确真实试用类型，不改变Web默认配置/DTO或工具循环 |
| `qq_bot/ai_coordinator.py` | 精确识别新Host；Scope由对应Host取得，保留容量先于扣费 |
| `qq_bot/ai_trial_delivery.py` | 新SessionQQTransport，仅接受已批准的SessionTrialRun |
| `qq_bot/ai_scheduler.py`、`ai_delivery.py` | 新类型装配；网络关闭抛错后仍尝试加入既有worker，保留SDK隔离及旧owner保护 |
| `qq_bot/ai_routing.py`、`gateway.py` | 新Transport与原Gateway/Router的明确类型对应，普通CLI不扩大 |
| `qq_bot/conversation_trial_cli.py` | 共享可中断控制台读入，旧双轮继续逐轮审批 |
| `scripts/dev/Test-QQConversation.ps1` | 默认TwoTurn不变；新增显式Session模式、总预算、成员选择和最终报告核实 |
| `scripts/dev/qq_bot_test_common.ps1` | 新最终报告核验；不复制模型/费用/审批执行逻辑 |
| 既有Scope准备资源及文档索引 | 按真实依赖更新candidate指纹；不改写历史批准/used/真实回执 |

```text
PS -Mode Session -Check → 明确request → 配置/Policy/Scope准备检查（无库/密钥/网络）
PS -Mode Session -Run → 同样检查 → 唯一报告目录
  → 只读装配已明确指定实例 → 显示本次计划 → 一次人工挑战
  → 批准记录 + 本进程RunConsent/OS owner + 内部RunAuthorization
  → 原QQ Gateway/Router/PassiveReplyOwner
  → 认证Mention/权限/时效/去重 → 容量/单飞 → 原子预留
  → TurnLease + 每轮私有Service/Session/Handle
  → 原Agent + 本轮Monitoring Tool → SDK关闭/Source/Commit
  → A/B/C受限文本 → 单次QQ被动回复 → 检查点 → 成功历史
```

## 3. 新Scope与批准合同

新合同：`qq-qwen-bounded-session-real-trial@1`。它与B的`qq-qwen-bounded-session-trial@1`独立，不复用原FAST/双轮批准或Provider回执。

准备资源仍是candidate、`qualification_id=null`；程序严格比较其完整内容与当前实际Scope，修改status或增加can_send等字段不会获得资格。Scope包含实际Prompt/Tool、SDK/资源合同、历史/展示、费用算法、所有权、服务实现、凭据装配代码以及PS入口/helper。

| 当前范围 | SHA-256 |
|---|---|
| 新真实持续试用准备 | `e92595b351669bfb8fe5e0be87f0a6cbfaf7463803e93b0b982b1d7f31427ef2` |
| B的Fake-only持续会话（仍Fake-only） | `325c5fd534f4b1d0906196158228839624006434907d0b1f300ba9dd5dab4b42` |
| 当前旧双轮实现 | `eaca20233e2c45234392e89c19146b2455119ff6ee161824e9b75170a6ffef11` |
| 当前旧FAST完整实现 | `b58fa54d78d52e827c8dcf6116ffc8183e0715782631fb56150568b0ae63ffd7` |

共享类型装配、关闭和控制台代码发生变化，因此旧FAST/双轮实现指纹改变；三份原candidate按实际代码刷新，资格没有提升。历史批准、used标记、Provider回执均未改写，不能拿来执行新代码。Monitoring-only底层candidate的SDK/Tool基础范围未变；Agent循环与SDK Backend源码未修改。

本机批准绑定：当前进程随机身份、Scope、配置/Policy/绑定摘要、一个实例/设备/群、明确选定成员、最大Turn/请求数、总预算、运行时长和批准时限。默认成员取原request的`member_id`；可显式选1～4名已同时具备access和AI权限的成员，不自动包含整个名单。

审批挑战一次性涵盖Provider、QQ、Scope/静态价格与预算、SIMULATOR及必要历史投影披露、SDK线程剩余风险。审批截止由`ValidMinutes`控制（1～10分钟）；批准后运行最长`RunSeconds`，至多1800秒。没有逐Turn人工输入。

`approval.json`只是审计记录，没有从该文件恢复授权的入口。真实执行依赖服务器内部RunAuthorization对象身份，以及当前RunLedger发行的Lease；复制、改名、修改JSON或旧批准不能生成新额度。运行中批准文件、Scope准备记录、Policy/成员/设备配置发生变化即停止AI。

QQ AppSecret供应器在本机批准后才装配；Qwen CredentialStore在合法Turn准入后才装配，沿用Prototype自身私有Store。没有迁移、复制、重新保存或读取Management凭据，不读取源码根.env。Check不解析实际Key或检查Key是否存在。

## 4. 额度和状态

- 默认候选：5个AI准入/最多10模型请求/1800秒；每轮2请求、每请求512输出Token、90秒、零自动重试。
- 保留既有Decimal预留：每轮1.602765元；5轮合计8.013825元，候选总预算8.02元。预算不足拒绝计划，不自动减少Turn数。
- `cost`中的原单轮限制是每个Lease的费用合同；总Run限制由`process`、计划`limits`和统一账本共同约束。
- BUSY、未授权、伪造Mention、问候、帮助、澄清不占用模型额度；预留后的失败、排队超时、取消、未知交付不退款。
- 清空/TTL/记忆淘汰不补额度。最后一个已预留任务不受剩余新Turn数为零影响。
- C完整回归发现只读监督检查与新预留共享I/O锁，原立即抢锁会偶发拒绝合法请求。现在仅在费用锁外做一次至多100ms的锁等待；仍繁忙则映射原BUSY模板，零预留、零模型，没有重试模型或延长90秒合同。
- SDK资源不明/隔离、Scope/权限/所有权失效、账本/必要检查点失败停止AI；普通失败且SDK安全关闭时允许新的独立消息。
- 额度耗尽时拒绝新AI，保留原授权期限内的固定只读命令；到期/停机取消任务、关闭资源、保存报告、清空Store。

没有增加Knowledge、历史AI Tool、事件写入或设备控制。当前水质每轮重新查询；历史仅为主题投影，不作为当前观测证据。只有QQ API明确接受且安全文本哈希/权限/会话revision仍有效才提交历史；送达未知不重发、不提交成功历史。

## 5. PowerShell操作

在Prototype根目录运行。默认复用固定的`outputs/qq-bot/conversation.request.json`；没有扫描目录或自动选择其他实例。若使用别处明确配置，添加`-RequestFile '绝对路径'`。

现在可以执行的无联网检查：

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
.\scripts\dev\Test-QQConversation.ps1 -Mode Session -Check
```

**以下真实启动命令只供3E-D另行批准后使用，本轮没有执行：**

```powershell
.\scripts\dev\Test-QQConversation.ps1 -Mode Session -Run
```

启动会展示模型、实例/设备、群/成员摘要、Scope、时长、次数与费用；随后输入一次`APPROVE <本次计划摘要>`。Enter取消，Ctrl+C停止。须使用普通Windows交互终端；非交互环境不能自动批准。

| 参数 | Session模式含义 |
|---|---|
| `-RequestFile` | 原明确request的配置引用；不包含Key |
| `-MaxTurns` | 1～5，默认5 |
| `-TotalBudgetCny` | 整个Run预算，默认8.02；不与旧MaxCostCny混用 |
| `-RunSeconds` | 1～1800，Session默认1800；TwoTurn仍默认300/至多600 |
| `-ValidMinutes` | 本次批准挑战等待期限，默认10；不延长Run运行期限 |
| `-Members` | 可选string[]，只选原白名单中的1～4人；省略保持原request单成员 |
| `-ReportRoot` | 仅项目outputs内的明确报告根；每次新建唯一子目录，不复用旧目录 |

旧行为继续：`.\scripts\dev\Test-QQConversation.ps1 -Check`与`-Run`默认TwoTurn，仍逐轮审批。向旧模式传入持续参数或超过600秒会拒绝；Session模式显式传旧`MaxCostCny`也会拒绝。

Check若返回`SESSION_TRIAL_SCOPE_REVIEW_REQUIRED`，表示实际代码/SDK/入口与准备记录不一致，应停止并由维护者复核Scope；不要手动提升candidate状态、修改can_send或借用旧批准。Check也不证明真实Key可用、源数据新鲜或QQ权限已经验收。

## 6. 报告与退出

每次保留`plan.json`、Scope的`session.json`、批准`approval.json`、原子消费JSONL/持久used声明、每Turn交付/结果检查点、最终`result.json`及PS的`summary.json`。全部create-only，不覆盖旧报告。

区分：

- `completed`：控制器是否安全、正常收尾，不代表每个AI Turn成功。
- `run_approved`：本次进程是否实际取得批准；批准前取消不算完成。
- `live_composition/real_execution`：前者表示真实类型的运行路径，后者仅表示非Mock SDK执行已进入请求阶段，不等于远端成功或计费确认。
- `verified_turns`：Backend/SDK/Source/Commit/API接受/History均通过的Turn数。
- `api_accepted_turns`：QQ平台明确接受，不代表客户端显示。
- `delivery_unknown_turns`：未知结果，无补发或补推理。
- `client_display_confirmed=false`：程序不伪造人工确认。
- `usage/observed_usage_cost_cny/billing_confirmed=false`：保留每轮实际SDK Usage与估算，不代表云端账单。

PS会检查原生退出码和磁盘最终报告的contract/Scope、预算/请求计数、report_saved及RAM清理状态，进度日志不算最终成功。未知交付、零AI回复和API接受使用不同摘要状态。最终报告写入失败会明确报错，不通过重新推理/发送修复。

主线程承担一次本机审批和控制监督；Gateway非daemon线程独立处理心跳，原AI/交付/监督线程保持有界。Ctrl+C根因不会被清理阶段的QQ_CANCELLED覆盖；网络关闭报错仍尝试加入worker并保存错误报告。SDK清理不安全时仍保留原sticky隔离与owner，不允许重建调度器绕过。

## 7. 本轮离线验证

使用新的合成Schema v2 Monitoring、真实SDK类+MockTransport、Fake Gateway和虚构配置。测试阻断外部网络，不使用现有业务实例或实际密钥。

已覆盖：一次审批五轮、逐轮新观测、SDK资源、多人共享额度/BUSY、重复消息、最后额度、内存TTL/清空、未知交付、普通失败、SDK隔离、撤权/改绑/Scope、批准篡改、写前账本/检查点/最终报告、Ctrl+C、Gateway故障、PS检查和报告核验。B阶段的真实OS双进程/崩溃/Windows句柄测试也在Bot与完整回归中复验。

| 最终验证 | 结果 |
|---|---|
| 持续真实类型与账本相关专项 | 59/59，115.812秒（含原账本覆盖及本轮新增用例） |
| 原多成员锁竞争用例复验 | 连续3/3通过，9.080秒 |
| 最终完整管理Python | 1077/1077，469.453秒 |
| 最终Bot覆盖 | 484/484，包含于完整回归；此前独立Bot首遍480/480 |
| Node前端 | 116/116，零失败/取消/跳过 |
| PS语法、Python/JSON解析、文档链接、git diff --check | 通过 |

本轮新增40个用例：新真实装配/PS文件38个，原账本新增2个。完整回归覆盖SDK、旧FAST/双轮、B的Fake-only持续会话、Web Normal/Streaming、Monitoring、Simulator和Knowledge。SDK Backend、Monitoring、Simulator、Web页面源码摘要与起点一致，未改规则/Schema/Agent循环。

记录：`outputs/test-tmp/bot3ec-20261027T034436Z-3ae00eb5/`。`targeted-corrected.log`、`contention-repeat.log`、`full-regression-final.log`及`final-verification.json`为最终依据；前期日志保留，不将首遍失败冒充通过。所有批准/数据库测试只在新合成目录中进行，真实请求数为零。

首遍完整回归1074项中仅一个多成员用例因上述`RUN_ADMISSION_BUSY`竞态失败，Node116项通过；已定位为运行时读锁竞争，不是扩大全局测试等待来处理。新增短读锁竞争、长竞争不消费及BUSY回复测试后重新运行专项与完整回归。

## 8. BOT-3E-D人工验收（待另行批准）

1. 复核当前Scope与SDK版本、固定Qwen模型/静态价格、原私有凭据由用户正常配置；不要把Key贴到聊天或命令行。
2. 明确批准一个SIMULATOR隔离实例、设备、测试群、1～4名成员、最多5轮/10请求/1800秒、8.02元候选预算及数据披露；本轮不代替该批准。
3. 执行上面的Check，核对其不读取库/密钥/网络；再在交互终端Run并审阅新计划，输入一次挑战。
4. `@机器人 你好`：模板回复、零模型；随后当前水质与追问，每轮重新取数，A/B/C和SIMULATOR/时效限制准确。
5. `/清空会话`只清本成员，不补额度；如多人参与，检查记忆隔离和共享计数。不得伪造长期新鲜时间戳；过期数据应如实stale/offline。
6. 最后额度完成后，再提问应拒绝模型调用；固定命令仍在期限内可用。测试Ctrl+C或自然到期，不进行无限断网重试。
7. 核对result/summary、Ledger、每轮SDK CLOSED、请求数、History提交及API接受；用户另行在QQ客户端确认实际显示，云端账单另核。

## 9. 保留风险

不合作SDK线程仍不能强制终止；本地取消不证明远端计算/计费停止。本地预算不保证云账单硬封顶；静态价格未经本轮联网核价。强杀/断电不能保证最终一次写盘，永久内核存储阻塞也不能由Python保证硬退出。OS所有权不防同账户主动修改源码/内存或管理员回滚文件系统。RAM清空为逻辑失效，不承诺Python堆物理擦除。

没有恢复SDK进程隔离草稿，没有改变Monitoring Schema/规则或Agent循环，没有修改Management，没有commit/push。

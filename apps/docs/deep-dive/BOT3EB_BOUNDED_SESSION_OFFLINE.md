# BOT-3E-B：受控持续会话授权（离线实现）

日期：2026-10-27。项目：Fishery_AI_Prototype，起点`main / e8c9654`。

## 1. 当前边界

已实现独立`qq-qwen-bounded-session-trial@1`、Run级原子额度、Windows运行所有权及Fake持续会话。复用原Scheduler、Service、Agent、Tool、Source/Commit、SDK资源门禁与A/B/C展示，没有新增Agent、数据库或真实网络入口。

**仅Fake-only candidate。** 普通QQ CLI、旧FAST和双轮入口不会启用此模式。`SessionRun`必须显式注入Fake SDK工厂，`SessionQwenTurn`只接受真实SDK类搭配精确`httpx.MockTransport`、零重试、禁代理环境及重定向；QQ仅使用原`OfflineQQGateway`。没有读取实际密钥、配置现有业务实例或连接QQ/Qwen。

前一轮[3E-A设计](research/BOT3EA_BOUNDED_SESSION_CONSENT_DESIGN.md)由用户批准：不恢复余额、保守预留、分级故障、一个群/实例/设备、1～4名明确成员共享额度。这里不把离线批准当作真实模型资格。

## 2. 文件与调用边界

| 文件 | 本轮职责 |
|---|---|
| `qq_bot/run_consent.py` | RunLimits/RunConsent、进程nonce、持久一次声明、独占句柄、Decimal额度与fsync日志 |
| `qq_bot/session_run.py` | 单实例/设备/群与显式成员、统一额度、每轮私有Service、分级故障、检查点与控制线程收尾 |
| `qq_bot/session_run_cli.py` | 仅离线合同Check；没有Run、凭据解析或批准文件导入 |
| `ai_service/channel_session_run.py` | 独立Scope、身份密封TurnLease、精确Fake-only SDK装配和历史授权 |
| `qq_bot/ai_coordinator.py` | 新Host的明确类型检查、冻结身份/历史、准入容量回调、各阶段复核 |
| `qq_bot/ai_scheduler.py` | 原1 AI/1交付/1监督线程；新模式先检查3个总任务位置及会话单飞，再进入额度消费；空闲也监督Run期限与撤权 |
| `qq_bot/ai_delivery.py` | 原单次被动回复Owner；新模式在提交历史前保存对应Turn交付检查点 |
| `ai_service/service.py` | 仅增加明确新类型；candidate不能伪装local_experimental，原Web默认路径不变 |
| `ai_service/channel_trial.py` | 抽出共享SDK初始化守卫；旧构造器仍精确要求QwenTrialApproval，含义与上限不变 |
| `ai_service/channel_conversation.py`与candidate资源 | 新增依赖纳入指纹；刷新两份原candidate，另增持续模式candidate，不修改历史批准 |

```text
认证Mention → 原权限/时效/去重/意图
  ├─ 固定命令、问候、帮助、澄清：程序回复，零模型、零Run额度
  └─ 当前水质/明确追问
      → Scheduler容量和单飞 → Run有效性/额度预留/fsync
      → 身份密封TurnLease → 私有Service/Session/RequestHandle
      → 原ToolCallingService → 本轮只读Monitoring Tool
      → Source/Commit/SDK关闭 → A/B/C → 单次Fake QQ提交
      → 交付检查点 → API明确接受及CAS校验 → RAM历史
```

## 3. RunConsent与TurnLease

RunConsent是当前Host在本机审批动作中创建的不可变对象，绑定新运行随机身份、进程nonce/PID、Scope、完整配置摘要、选定成员、限制和有效期。不存在从批准JSON加载或恢复Run的API；QQ报文不能构造授权。保存的计划/日志只是审计资料。

RunLedger与Host分别核对配置、Scope、成员选择与批准计划。默认只选`TrialInputs.member_id`，可明确传入1～4个成员，但必须同时已在原access和独立AI授权中；不会自动授权整个群或整个allowlist。

每次准入派生内部TurnLease，绑定父批准、序号、原消息键、具体成员/实例/设备、Scope、期限。LeaseAuthority保存对象身份注册；复制dataclass字段、普通JSON或伪造ticket均不能通过验证。每轮绑定实际Store发行的历史快照，不能用其他成员或旧revision的快照代替。

Service和RequestHandle每轮独立，SDK请求计数每轮最多2；多个成员共享Run额度，历史仍按App/群/成员/实例/设备/权限/Policy/Scope/epoch隔离。

## 4. 额度、准入与写前日志

默认候选上限：1800秒、5个AI准入、每轮2请求/每请求512输出Token/90秒/零重试。可批准更小的1～5轮与1～1800秒；预算不足直接拒绝计划。

沿用现有静态价格与输入预留算法：每轮`1.602765`元，5轮`8.013825`元，默认示例总预算`8.02`元。全部金额使用Decimal。该价格并非本轮重新联网核价，实际账单仍未知；本地预留不是云平台绝对费用上限。

准入顺序：原鉴权/时效/去重 → Scheduler容量/单飞 → Run有效 → RAM预留 → 脱敏日志flush/fsync确认 → 签发Lease → 私有Service/Handle入队。BUSY、伪造Mention、非法或未授权消息没有Run消费。

RAM费用锁只修改计数/消息键，不执行文件I/O、模型或网络。单独的I/O锁以非阻塞方式串行化新预留；竞争期间返回`RUN_ADMISSION_BUSY`，不补开线程或无限等待。磁盘写入在费用锁外完成。

一旦进入预留，即保守占用1轮、2请求槽及完整单轮金额，不因后续排队超时、取消、模型失败、未知送达或服务创建失败退款。写入结果未知时也不恢复额度，并永久停止本Run。成功交付次数与准入消费分开统计。

原消息键和指纹在本Run内一直保留，最多5项，不随原300秒消息缓存消失。清空/TTL/容量淘汰/恢复聊天上下文都不恢复额度。最后一个合法Lease检查自身许可与期限，不检查“还剩几个新Turn”，因此不会因余额归零而取消。

## 5. Windows所有权与崩溃

状态目录必须显式指定、位于可信本机磁盘并通过现有路径保护。Host要求新建的空报告目录，不自动选择、修复或覆盖实例/批准。

- 为随机consent_id创建`run-<id>.used`：Windows原生`CREATE_NEW`、仅共享读，不共享写/删除，并持有句柄直至收尾。
- 同一声明的并发创建只有一个成功；其他进程得到`RUN_APPROVAL_ALREADY_USED`。
- 校验持有句柄、PID、文件身份与内容；丢失或不确定立即停止。
- 正常关闭/进程崩溃只释放OS句柄，声明仍留在磁盘，不删除、不恢复余额。
- 新进程产生不同nonce和计划，不能导入旧RunConsent或重放旧消息。删除旧标记不能使旧对象在新进程获得身份。
- 使用create-only JSONL消费日志，保留前序摘要，逐次flush/fsync，核对文件身份与期望字节。失败不“重建账本继续”。

新合成目录中测试了真正两个OS进程同时争用同一新声明、持有期间二进程拒绝、崩溃释放句柄后仍拒绝，以及Windows运行中拒绝删除/重命名。

这保护正常程序的重复启动和意外恢复，不声称抵御同账户修改源码/内存、管理员行为或整个文件系统回滚。也不承诺本地取消能停止远端计算/计费。

## 6. 状态与故障策略

| 状态/故障 | 行为 |
|---|---|
| UNAPPROVED | 不允许AI；只有本机Host审批可转APPROVED |
| APPROVED但额度耗尽 | 拒绝新AI；已预留任务仍可完成；固定命令仍需原授权 |
| Provider失败/超时，SDK明确CLOSED | 本轮消费保留，无成功历史，无重试；允许新的独立消息 |
| 排队过期/停机前尚未SDK执行 | 消费保留，不创建SDK资源；后续仍受Run有效性检查 |
| QQ交付失败/未知 | 不重发、不重新推理、不提交成功记忆、不退额度；可接受独立新消息 |
| SDK关闭失败/隔离/不明 | HALTED，取消关联任务，不重置全局隔离 |
| Scope/Policy/配置/设备/成员权限变化 | HALTED；恢复旧配置也不恢复本Run |
| 所有权/账本/fsync异常 | HALTED；本次不获得可执行Lease，不自动补额度 |
| 必要交付/结果检查点失败 | HALTED；保留已发生的API接受状态，不重新发送 |
| 清空当前会话 | 取消旧快照关联任务，只影响本成员；Run额度保持 |
| Run到期、人工停止 | 控制线程停止准入、Scheduler有界取消/关闭/加入线程、写最终报告、清空RAM |
| 最终报告写入失败 | 返回RUN_REPORT_FAILED，保留已有消费及检查点，不进行补偿请求 |

`run_until_stopped()`在调用方控制线程等待，不占Gateway心跳或AI线程。监督线程即便没有新消息也检查Run；控制线程最终执行`stop()`。最终报告create-only，不覆盖原文件。强杀进程/断电仍不能保证最后一次报告写盘，保留之前逐次消费及交付检查点。

SDK线程架构未改，不合作I/O仍无法强制终止；无法确认清理会报告不安全并保留隔离，而不是宣布已安全结束。未恢复SDK子进程草稿。

## 7. 测试与记录

新增专项：`test_run_consent.py`及`test_session_run.py`。覆盖额度1～5、金额不足、并发/去重、真正双进程/崩溃/Windows句柄、磁盘写入/fsync、五轮同进程、每轮新Tool、BUSY/单飞、多人记忆、清空、Provider失败、超时、排队、断线、SDK隔离、未知交付、撤权、Scope、自动到期、报告失败。

本轮测试全部离线，新SQLite及配置由夹具创建；真实网络被阻断，使用真实SDK类与内存HTTP。测试日志保存在`outputs/test-tmp/bot3eb-20261027T030121Z-9236ffa9/`，不包含密钥、完整OpenID或真实聊天。

| 验证 | 最终结果 |
|---|---|
| 新RunConsent/持续会话专项 | 54/54，42.211秒 |
| Bot回归 | 最终完整回归内444/444；此前独立439/439，169.528秒 |
| 最终完整管理Python | 1037/1037，284.063秒；包含旧FAST/双轮、SDK、Web Normal/Streaming、Monitoring/Simulator/Knowledge及Bot |
| 最终Node | 116/116，零失败/取消/跳过 |
| 离线CLI | BOUNDED_SESSION_CONTRACT_CHECKED；零网络、未创建批准、未检查实例 |
| 语法/JSON/本轮文档链接/差异格式 | Python解析、JSON解析、链接及git diff --check通过 |

首遍完整回归通过后又新增了“实际装配Tool定义变化”的对抗用例：新模式原先只对比预生成Scope，此用例证实可准入不一致的Tool定义；已改为根据本轮实际profile/policy/registry计算Scope后再核对Lease。最终54项和1037项均在修正后运行，不以首遍结果替代最终验证。没有运行真实Provider或QQ。

## 8. 可执行的离线检查

在Prototype根目录的PowerShell执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot.session_run_cli --check-contract --max-turns 5 --total-budget-cny 8.02 --seconds 1800
```

预期`BOUNDED_SESSION_CONTRACT_CHECKED`；不创建批准、不读取密钥、不打开Monitoring，也不表示某个已有实例通过接入检查。2元/5轮会返回`RUN_BUDGET_INSUFFICIENT`。

```powershell
$env:TEMP = Join-Path $PWD 'outputs\test-tmp'; $env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -X utf8 -B -m unittest apps.qq_bot.tests.test_run_consent apps.qq_bot.tests.test_session_run -v
```

这里没有持续会话真实启动命令。原四个PS入口默认行为不变，仍使用旧单轮/双轮审批，不接受新的RunConsent。

## 9. Scope与后续3E-C

新增`ai_service/resources/qq_session_run_candidate.json`，明确`OFFLINE_FAKE_ONLY`、无qualification_id、禁止真实执行/交付，绑定许可、额度、历史、Prompt/Tool、SDK及所有实现依赖。

最终指纹：

| 范围 | SHA-256 |
|---|---|
| 新持续会话Fake-only candidate | `1332d84581c7d7848b907a9cbc52e73d02faa318e6e50b08268146a4dd409670` |
| 当前双轮试用实现 | `1e6d3efb7d19d01fe6e2f39610bb13bb3ae28f164f00e10ca5439dcc6c76b38a` |
| 当前FAST完整实现 | `96313b1187dced36eb09ff5338a223f9d697b560eb4bc4af3edc227892be3864` |
| 原Monitoring-only底层candidate（未变） | `2d89b74fe451f793c09e21fff90dc624d9fd2ee34a02c393284f2e61066350be` |

共享Service、SDK初始化守卫与Coordinator改变，所以旧FAST及双轮实现指纹改变；原Fake/双轮candidate已按实际依赖刷新，状态仍为candidate。原Monitoring-only底层candidate范围没有改变。**没有改写旧批准、used标记或真实回执；它们不授权新代码的再次执行。**

3E-C建议只做：

1. 独立审核真实类型/资格与Provider前置证据，不能把本轮Fake标记改成true就开放网络。
2. 复用已有`Test-QQConversation.ps1`增加显式会话模式和`TotalBudgetCny`，旧默认双轮语义保持。
3. Check核对明确request引用/成员选择/预算/Scope；Run展示完整身份与披露范围，一次本机审批后生成当前进程RunConsent。
4. 把原真实QQ Transport/Gateway通过明确新类型接入，维持原PassiveReplyOwner；测试真实类型装配仍先用Fake。
5. 控制线程承担期限、Ctrl+C、安全收尾与最终报告，心跳线程不等待人工输入。
6. 完整离线通过后另行申请3E-D：模型、最多5轮/10请求、8.02元候选预算、期限、实例设备群成员、SIMULATOR及历史投影披露。未批准前不联网。

真实人工验收需分别确认：问候零费用、五轮额度与每轮新观测、多人隔离、清空不补额度、耗尽拒绝、到期/取消、SDK CLOSED、API接受和QQ客户端显示。平台接受不等于客户端显示，Usage估算不等于账单。

未解决边界：本地文件系统严重阻塞时，Python不能承诺任意内核故障下的绝对退出时限；本轮验证了写入/fsync报错，未模拟永久阻塞的本机存储。会话清空指Store的逻辑失效/释放，不宣称Python堆内存物理擦除。真实长时网络稳定性、最新价格及云端账单均须后续另行核验。

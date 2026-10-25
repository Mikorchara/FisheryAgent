# BOT-3C-2A：SDK资源门禁与取消可靠性

后续状态：[BOT-3C-FAST](BOT3C_FAST_QWEN_TRIAL.md)按用户调整的优先级准备独立单轮试用审批，明确接受线程硬退出不足的实验风险；本页资源失败门禁不放宽，进程隔离仍暂停。本页后续阶段建议保留为当时记录，不代表FAST已获实际联网授权。

核验日期：2026-10-25，仅Prototype。[上一阶段](BOT3C1_REAL_AI_PREPARATION.md)。本轮不连接QQ/Provider/NPU、不读取实际凭据或现有业务实例。

## 1. 结论与尚未解决的边界

已实现显式SDK资源租约、有限清理等待、失败后的进程内隔离门禁、Commit/Delivery防线与可区分的资源状态。合作式取消能关闭Task/SDK stream/client并确认请求线程退出；清理异常或退出未确认会报专用错误，不再把它当普通取消或成功。

**本轮没有实现任意线程的强制终止。** 不合作的同步I/O、吞取消的协程、SDK close或Runner背景任务仍可能使线程残留。此时拒绝后续SDK请求；残留线程及未知I/O不会被宣称已清理。

遗留SDK线程仍保留 `daemon=True`，没有直接改成可能拖住进程退出的非daemon线程，**也不以daemon属性作为清理/退出保证**。这是本轮方案的明确剩余限制，不能写成“已消除所有daemon风险”。Python不能安全强杀任意线程，底层扩展/执行器也可能阻塞进程退出；需要硬退出保证时须另做SDK I/O进程隔离。本轮按限制不进行该架构改造，真实QQ `/问AI`继续AI_DISABLED。

## 2. 原因与状态流转

原 `_bridge` 只向asyncio Task发送取消，最后join最多5s；线程仍存活时只设io_closed=false，未形成稳定的资源失败与全局拒绝门禁。Runner退出中的额外任务可能让线程继续存在，即使SDK client已报告关闭。

现在的资源生命周期：

```text
未使用SDK → reserve（进程内最多8个活跃SDK请求）→ RUNNING
  → 模型/流结束 → 同一个cleanup Task关闭stream/client
  → Task完成 + join确认线程退出 + 本地close成功 → CLOSED
  → close异常/未确认、Runner清理失败、join超时 → CLEANUP_FAILED + QUARANTINED
```

普通响应内容错误/HTTP错误若清理成功，只使本请求失败，不隔离SDK；资源清理失败才触发隔离。SDK自身和现有Preset重试合同未放宽，没有新增模型重试。

| 状态字段 | 能说明什么 | 不能说明什么 |
|---|---|---|
| `cancel_requested` | Handle收到了取消请求（用户、超时、撤权或停机均可触发） | 不能据此推断是用户操作，也不代表SDK已处理 |
| `cancel_signal_sent` | RequestHandle钩子成功排入了Task取消信号；SDK内部期限取消不一定经过该钩子 | 网络或close已经完成 |
| `local_io_closed` | 未创建I/O，或stream/client close顺利返回；SDK暴露is_closed时还要求不能为false | 远端计算或计费停止；false表示未确认，不等于已证明socket仍打开 |
| `task_done` | SDK operation Task完成；未创建Task时为null | Runner的其他Task/线程/执行器全已退出 |
| `thread_exited` | 资源owner观察到请求线程不再存活 | 其他进程、远端模型已经停止 |
| `state/cleanup_error/quarantined` | 清理是否确认及失败原因；晚退出不会消除失败记录 | 自动恢复或重新授予执行资格 |
| `remote_compute_stopped` | 始终unknown | 不因本地取消就声称停止计费 |

状态由 `RequestHandle.resource_info()` 和 `public_info()['sdk_resources']` 提供，不含线程ID、密钥、消息、URL或业务正文。QQ终态保留有限资源引用，可重新观察晚退出；任务仍保持失败，不能变成成功交付。

## 3. 核心实现

| 文件 | 改动及原因 |
|---|---|
| `ai_backend/sdk_resources.py` | `SDKResourceBudget / SDKResourceLease`；共享限额8、close/Task/线程事实、粘性故障隔离，无生产reset入口 |
| `ai_backend/openai_compatible_adapter.py` | 申请租约；取消钩子幂等；一个shielded cleanup Task；检查SDK的is_closed；默认最多2s join；未确认时专用错误覆盖成功 |
| `ai_backend/execution.py` | Handle检查/完成/Commit前检查资源；资源失败优先于USER_CANCELLED；Registry不因terminal/TTL裁剪未确认资源或释放其名额 |
| `qq_bot/ai_coordinator.py` | 发送候选复核增加资源已关闭检查，Source/Final通过也不能绕过 |
| `qq_bot/ai_scheduler.py` | 资源失败优先于取消；取消其他排队AI、拒绝新准入；资源不安全时close明确报错且不释放coordinator绑定 |
| `ai_service/channel_scope.py`及候选JSON | 新contract/release_id为v2；绑定Adapter、资源模块、Handle实现hash与资源合同；仍candidate，资格/批准ID均null |

所有默认Adapter实例共享SDK预算，不能换一个Adapter/Handle/RequestRegistry绕开残留请求。默认允许的并发上限是8；QQ自己的1执行/2等待和Web Registry预算继续生效。

8限制的是本桥接拥有的SDK请求线程，不是SDK/DNS/系统库任意内部资源的硬配额；库内部线程/执行器及GIL阻塞仍属于进程隔离需覆盖的风险。

测试可以显式注入独立预算来测试故障，不通过聊天/HTTP/JSON接收该对象。隔离状态不自动复位，即使晚些时候线程退出、close返回也不恢复；没有“忽略错误继续运行”的公开接口。

### 取消与清理的竞态

Task取消钩子只发送一次取消，重复Stop/abort不反复打断资源关闭。stream/client各只启动一次close；发生取消时继续等待同一个shielded cleanup Task。若正常close结束与取消同时到达，记录本地资源已关闭，但本轮仍取消，不能提交Final。

父调用者不会无限等待cleanup：请求期限或取消后最多再等待清理join预算（默认2s，调度/OS延迟另计）。如果cleanup不合作，owner停止等待、记录失败并隔离SDK；并不是杀死了该线程，也不是无限重试close。若线程持有GIL或宿主本身失去调度，进程内Python不能提供硬实时时限。

### Commit、Registry和QQ关闭

- `_bridge` 在返回完整成功前必须完成资源结算。普通响应即使已产生，也不能越过close/线程退出门禁。
- `RequestHandle.finalize_result` 在调用最终记录函数前再次检查资源；未确认时不调用成功记录函数。未改变Agent Tool Calling循环和监测领域规则。
- 资源失败使Handle为FAILED而非“安全取消”；同时保留cancel_requested，避免两种事实互相覆盖。未确认线程退出时不因finish丢弃仍有效的取消钩子。
- Registry保留失败资源记录，TTL和完成列表裁剪不能偷放名额。进程内SDK隔离拒绝新的真实SDK调用，避免重试造成线程堆积。
- QQ任务不会变为DELIVERY_PENDING/DELIVERED；新的AI准入拒绝AI_RESOURCE_QUARANTINED。正常固定Monitoring查询不依赖SDK预算，仍可继续；AI故障不等于Monitoring停止。
- 若QQ自己的三个线程已退出但SDK资源不安全，`close()`报AI_SDK_RESOURCE_UNSAFE，不能报告“所有底层资源已回收”。不释放唯一scheduler绑定，禁止重建scheduler掩盖故障。

## 4. 稳定错误与运维含义

| 错误 | 含义/处理 |
|---|---|
| SDK_RESOURCE_LIMIT | 正常活跃SDK请求达到上限；没有新建SDK线程 |
| SDK_CLEANUP_FAILED | close/Runner清理异常，或SDK仍报告未关闭；隔离SDK |
| SDK_CLEANUP_TIMEOUT | 有限join后线程仍存活；隔离SDK，不声称强制停止 |
| SDK_RESOURCE_UNCONFIRMED | 成功/Commit被尝试时资源尚未确认安全 |
| SDK_RESOURCE_QUARANTINED | 进程已有未确认清理；拒绝新SDK调用，不能靠换实例重试 |
| AI_RESOURCE_QUARANTINED | QQ调度器的AI准入已隔离 |
| AI_SDK_RESOURCE_UNSAFE | QQ线程可能已经结束，SDK资源仍不能报告安全结束 |

遇到资源隔离应停止新的AI操作，保留安全错误与状态快照，由操作者安排停止/检查/重启。不要循环点重试、清空状态或修改权限来恢复。本轮测试会释放所有假阻塞并join测试线程；生产中的任意阻塞线程没有这样的可靠释放按钮。

## 5. 进程隔离评估：BOT-3C-2B前的决定

若要求“不合作SDK也必须在固定期限内退出且不影响Web主进程”，本轮线程方案不满足该硬保证，需要进程边界，不能用改daemon、注入线程异常或强杀整个Web代替。

Python 3.12官方说明：线程不能直接停止/销毁，daemon在解释器退出时会被突然停止；这不是资源正常释放协议。[threading](https://docs.python.org/3.12/library/threading.html)。Runner.close还包括异步生成器和执行器清理，不能把operation Task完成等同整个Runner退出。[asyncio Runner](https://docs.python.org/3.12/library/asyncio-runner.html)。进程隔离也有代价：Windows默认spawn，强制终止不会执行finally，可能损坏IPC队列/锁，须作为故障退出设计而非成功close。[multiprocessing](https://docs.python.org/3.12/library/multiprocessing.html)。以上资料核验于2026-10-25；本机测试版本仍为3.12.14，在线3.12文档显示维护版号不等于本机版本。

建议后续最小隔离范围是**SDK I/O worker**，Agent/Tool/Monitoring/Policy/Receipt/Commit仍在主进程，不创建第二套Agent。父端拥有有界子进程名额、请求期限、取消信号、退出确认和结果协议；合作退出优先，失败时终止自己创建的子进程并确认退出。终止子进程仍不保证远端计算/计费停止。

代价和必须验证项：Windows spawn/打包/启动延迟（本轮未测，不给伪造性能数）；有界序列化/流式背压；SDK不可序列化对象与Fake测试注入；密钥只经受控短生命周期本机IPC传入，不写文件/命令行/日志；禁止继承不必要的敏感环境；父子异常/断管/退出的单次提交协议；额外内存及Normal/Streaming回归。不得pickle来自群消息的任意对象或回退线程绕过隔离。

本轮不实现该架构，后续需单独审核一个SDK进程隔离小阶段，再决定真实Provider入口是否具备开放条件。当前只读预检仍列出SDK_HARD_THREAD_EXIT_NOT_GUARANTEED；真实QQ AI继续关闭。

## 6. 离线测试与真实网络限制

新增SDK资源测试覆盖正常完成、重复Stop/abort、吞取消协程、同步阻塞事件循环、close不合作、Runner背景Task不退出、close异常/谎报仍打开、跨Adapter/Handle隔离、Registry TTL保护、容量、线程启动失败、取消前零请求、取消与成功close竞态、Final完成后Stop。

新增QQ资源门禁测试覆盖：来源/Final已成功也不交付；资源失败优先于取消；隔离后不准入/不释放唯一绑定；全局SDK隔离错误不需要伪造一份本任务资源才生效。

沿用真实AsyncOpenAI + MockTransport的响应头/响应体黑洞、总期限、正常编码、零重试与关闭测试，以及SDK Stream关闭、Web Normal/Streaming和旧协议差分。关闭故障用专用SDK_CLEANUP_FAILED替代泛化SDK_ERROR；差分仅排除新增SDK观察字段，继续比较旧协议、结果、来源、步骤、关闭事实和最终状态。

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
$env:TEMP = Join-Path $PWD 'outputs/test-tmp'; $env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -X utf8 -B -m unittest apps.ai_backend.tests.test_sdk_resources apps.qq_bot.tests.test_sdk_resource_gate apps.qq_bot.tests.test_provider_sdk_preparation
.\.venv\Scripts\python.exe -X utf8 -B scripts/dev/run_tests.py management
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --check-ai-readiness
```

测试都用新建隔离SQLite、Fake SDK/内存HTTP或合成线程等待；不真实断网、不连接Provider/QQ、不读取Key或已有实例。现场Windows DNS/TLS/网络黑洞、系统调用/GIL阻塞、远端停止和计费仍未验证。

最终结果（`.venv` Python 3.12.14）：新增资源门禁 **20/20**（SDK17、QQ3）；连同既有真实SDK内存HTTP专项 **25/25**；资格/迁移定向 **24/24**；最终完整管理回归 **810/810 Python + 116/116 Node（11文件）**，Python阶段188.748s，退出0。覆盖原Web Normal/Streaming、三工具、Bot固定查询/AI权限队列、Monitoring/Simulator及历史差分。

首遍完整回归暴露一个测试夹具问题：故意制造SDK close失败后，新的全局隔离影响了同进程后续假资格案例。生产隔离未放宽；测试给独立案例注入独立预算后，相关24项及最终完整回归通过。未重写旧协议/资格黄金基线。

AST/JSON、新报告链接和 `git diff --check`通过；只读预检返回QQ_AI_PREFLIGHT_VALID_LIVE_BLOCKED，Scope匹配但真实执行/交付仍false。所有新增不合作假I/O最终由测试显式释放并join，未遗留测试SDK线程。不将这些离线测试视为实际网络或真实模型资格证据。

## 7. Scope与BOT-3C-2B前置条件

Scope更新为 `qq-monitoring-normal-trial@2 / qq-monitoring-normal-trial-v2`，新增资源合同 `sdk-resource-quarantine@1`；Adapter、sdk_resources、execution文件hash均重新绑定，仍candidate；没有修改旧Web发布文件或授予本轮真实资格。

后续仍需：进程硬隔离方案审核及验证；真实Service/Delivery类型化装配；新实现对应Scope重审；逐阶段Provider/模型/费用/输入输出上限/实例设备/群成员和数据披露批准；真实网络取消与送达验证。未满足前不能启用真实Provider或QQ AI，也不能通过can_send/can_deliver或删除阻塞项绕过。

当前阶段交付是**准确的资源失败门禁与故障隔离**，不是任意SDK硬终止能力或真实资格。未改Management、数据库、Settings、Policy、Credential、旧Runtime、Tool Schema或Agent循环；未commit/push。

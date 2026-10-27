# BOT-3F-B0：Web AI / QQ Bot 离线性能对照

日期：2026-10-27（北京时间）。项目：Fishery_AI_Prototype。
源码基线：`main` / `85199370d1e4fdf7066a518a175e246d18d79319`。
本轮仅新增实验脚本、测试及本文，不优化运行代码，不改变 Scope 准备资源、权限、预算或交付语义。

**环境限制：** 本次项目 `.venv\Scripts\python.exe` 在当前 Codex 执行环境实际落到 **Python 3.12.14**，基解释器为 Codex bundled runtime；OpenAI SDK 2.54.0、httpx 0.28.1、Flask 3.1.3。没有修改 venv 或环境配置。下述同环境对比有效，但不能直接当作用户普通终端 Python 3.11 的性能数字；目标解释器下应复跑同一脚本。

## 1. 实验入口和复跑方式

在项目根用 PowerShell 7 执行，不需要 QQ/Qwen 凭据或任何已有业务实例：

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
pwsh -NoProfile -File .\scripts\dev\Compare-WebQQPerformance.ps1 -Smoke
pwsh -NoProfile -File .\scripts\dev\Compare-WebQQPerformance.ps1 -Benchmark -Samples 30 -Warmup 2
```

| 参数 | 作用 |
|---|---|
| 无模式参数或 `-Smoke` | 每条件两次正式样本，用于功能检查；不输出稳定 P95 |
| `-Benchmark` | 每条件、每渠道至少 30 次样本；可用 `-Samples 30..300` |
| `-Suite Core / Entry / Both` | 只测核心对照、实际入口或两者；默认 Both |
| `-Warmup 1..5` | 每条件的预热对数；默认 2，与正式统计分开 |
| `-OutputRoot` | 只能在项目 `outputs/performance/` 内指定位置；自动创建唯一子目录，不覆盖已有运行 |

Smoke 覆盖全部条件，也要执行真实本地校验，可能需要数分钟。完整基准更长，终端逐条件输出进度。失败记录保留；普通失败不自动补样，SDK/资源不安全或清理失败停止实验。中断保留最终已收集数据，P95 不足 30 个成功样本时留空。

新增文件：

- `scripts/dev/Compare-WebQQPerformance.ps1`：路径定位与参数检查的薄封装。
- `scripts/dev/compare_webqq_performance.py`：隔离夹具、Fake SDK/QQ、采样与 JSON/CSV。
- `scripts/dev/performance_observer.py`：透明计时包装、嵌套跨度、统计函数。
- `scripts/dev/tests/test_compare_webqq_performance.py`：测量工具自身的离线测试。

输出目录包含 `results.json`、`samples.csv`、`stages.csv`、`spans.jsonl`、`SUMMARY.md`。JSON/CSV 保留逐样本成功/失败、冷/热阶段、调用次数及计时；跨度包含父子关系、线程和单调时钟。没有消息正文、模型自由文本、Key、Token 或完整 OpenID。

## 2. 两类对照的边界

### A：受控共享核心工作负载

四种场景：全部有效且新鲜、pH 缺测、stale/offline、低氧规则命中。

- 同一原 `AssistantService`、`ToolCallingService`、SINGLE_ROUND 1/1/2。
- 同一合成数据生成方式、同一当前水质 Definition、同一首轮问题输入、空历史。
- 两次相同策略的假模型 HTTP：第一次产生 `{}` 当前水质 Tool Call，第二次依据实际 Tool payload 产生封闭解释 JSON。每轮实际调用一次 Monitoring。
- Web 经真实 `ManagementAssistantService.prepare_turn()/execute_turn()`；QQ 经真实 Session 准入、Scheduler、执行、API Mock 交付、History Commit。
- Web 在新建夹具的 Policy 中合法只选当前水质工具；没有修改全局 Policy、资格或 can_send。为满足 Web 正常配置合同，仍绑定版本固定的公开知识测试资料，但不查询知识。
- Web 和 QQ 都使用同类 `InstanceMonitoring` 只读 facade。合成 Monitoring DB 是每个样本新建的，并非现有业务实例。

**仍不完全等价：** Web Prompt 是 `ASSISTANT_V2@1`，QQ 是 `QQ_CURRENT_DIALOGUE@1`；QQ 有 RunConsent、Scope/绑定复核、额外 Handler Guard、512 Token 请求限制和发送后记忆合同。不能为“同核心”修改这些合同。对照比较共享核心的实际跨度，不代表移除这些差异后的纯算法微基准。

### B：原样实际入口

Web 使用 Flask 测试客户端的 bootstrap、浏览器 Token、request/control、`POST /api/ai/messages`，到成功 DTO 和客户端测试历史提交；QQ 使用认证 Fake 群 @ 事件、原 Router、Session、Scheduler、真实类型化 MockTransport、原单次 PassiveReplyOwner、API 接受及 ConversationStore。

| 条件 | 原问题 | 合成数据 | QQ 当前路由 |
|---|---|---|---|
| q1-water | 现在水质怎么样？ | fresh | AI |
| q2-oxygen | 溶解氧是多少？ | fresh | AI |
| q3-ph | pH 数据是否正常？ | partial / pH 缺测 | AI |
| q4-reliability | 现在的数据可靠吗？ | stale / offline | 程序澄清模板，零模型请求 |
| q5-followup | 那水温呢？ | fresh | 先完成一轮水质问答并提交历史，再追问 |
| q6-risk | 有没有低氧风险？ | 低氧规则命中 | 程序澄清模板，零模型请求 |

q4、q6 的路由差异是本轮发现的现状，不改变文字绕过它。Web 仍执行两次假模型请求，因此这两项**只能比较用户入口行为，不能据其耗时计算 AI 性能优劣**。A 中另有明确水质表述的 stale 和低氧对照。

q5 的历史来自实际完成的测试前轮：QQ 必须 API 接受并 `HISTORY_COMMITTED`；Web 必须 HTTP 200 且 `successful_turn=true`，测试客户端再按 Web 合同提交该答复。没有伪造已交付记录。Web 的客户端历史与 QQ 的安全主题投影不同，不能宣称输入历史字节完全相同。

所有入口仍保留原 Prompt、预算、Scope、权限和来源检查。没有执行真实 Web 浏览器或 QQ 客户端绘制，也没有测量真实 Gateway 网络接收。

## 3. 测量、安全与统计方法

- 使用 `perf_counter_ns()`。计时包装不改参数、返回值、异常或实际检查；函数别名统一观察，结束后恢复。
- 分别记录总时间、共享 Assistant 核心前/中/后、Scope 层级、配置/Policy、模型 Adapter 和逐次内存 HTTP、Tool、Monitoring、SDK close/join/settle、交付、响应封装及历史提交。
- Scope 和 Policy 跨线程跨度重叠；同时给出区间并集。包围时间是混合区间，包含锁等待和回调，不能相加，更不能等同可删除开销。
- 每条件先记录首次夹具执行，再预热，再交错 Web/QQ 顺序采样。样本之间新建隔离实例，避免会话累积、额度或限流改变负载；每个 Fake Run 仍遵守五轮上限，追问使用两轮，没有提高额度。
- 本文“预热后/热样本”指模块、SDK 懒加载及文件系统缓存经过预热；**不是同一 Run 无间断运行 30 轮**。每样本仍有新夹具、新 Run，装配耗时单列；q5 在本夹具内有一轮真实前序交付。持续第 2～5 轮和长时间运行的性能不能由此直接保证。
- “冷”指该条件首次夹具/服务执行；另记录本进程导入耗时和每样本夹具装配耗时。不是完整 Windows/浏览器冷启动 SLA；正式统计只使用预热后样本。
- P95 为 nearest-rank，只有同条件同渠道成功样本数 ≥30 才给出。失败不进入成功延迟分布，但保留在原始结果及失败计数中。
- 观察器开/关各有独立对照样本，不混入正式分布；小样本只能检查量级，不能宣称稳定观察器开销百分比。
- 复用既有 QQ 离线夹具的 socket 禁用防线；只允许 asyncio 内部唤醒用的本机 socketpair。模型和 QQ 全部使用 `httpx.MockTransport`，密钥解析器不读取真实配置；Web 的 CredentialStore 只收到显式虚构字典。
- 所有 SQLite 和 Fake 批准在本次唯一输出目录内的 `fixtures/` 下创建。每样本检查 DB 字节摘要不变、SDK Client 关闭及工作线程退出，然后清理该样本的可替代夹具；不接触任何原有批准、回执或实例。
- 业务时钟使用夹具的固定合成 UTC 时间以控制新鲜度；性能计时是真实单调时钟。这不是伪造真实实例长期在线。低氧、partial、stale/offline 均另有领域接口断言。

## 4. 实测结果

### 4.1 数据集合与可比性复核

完整基准：`outputs/performance/webqq-20261027T085904Z-ba6c457b/`。

- 10 条件 × 2 渠道 × 30 正式样本 = **600/600 成功**。
- 连同冷执行、预热、观察器开关对照，共 **740/740 条测量记录成功**，最终无线程残留。
- 核心 A 的 120 个配对中，首轮问题 SHA、有效 Tool Definition SHA、完整实际 Tool payload SHA 和两次模型请求数**全部匹配**。校验文件：`comparability_checks.json`。
- Prompt SHA 和请求输出预算合同不同，未声称匹配；原始记录保留这些差异。
- `provenance.json` 保存 HEAD、原有 382 个已跟踪文件及测量脚本摘要；`environment.json`、`scope_verification.json` 分别记录解释器/依赖和候选资格核对。
- `spans.jsonl` 是较大的原始嵌套证据，整次结果约 100 MB，均在 gitignore 的输出目录，不加入 Git。

### 4.2 核心 A：每格 n=30，单位 ms

| 场景 | Web 中位数 | Web P95 | Web 最小～最大 | QQ 中位数 | QQ P95 | QQ 最小～最大 |
|---|---:|---:|---:|---:|---:|---:|
| fresh / 全部水质 | 16.801 | 21.527 | 15.440～79.170 | 2307.295 | 2468.143 | 2144.320～2480.937 |
| partial / pH 缺测 | 17.176 | 24.311 | 15.255～26.092 | 2363.816 | 2543.647 | 2201.297～2553.258 |
| stale / offline | 18.047 | 24.059 | 16.102～68.054 | 2373.752 | 2547.501 | 2194.726～2551.117 |
| 低氧规则命中 | 18.336 | 22.951 | 15.452～24.700 | 2386.079 | 2841.691 | 2189.755～3028.664 |

79 ms 等较慢 Web 样本仍保留在原始数据和最大值中，没有裁剪异常点。这里的“总时间”是本地服务/模拟入口完成时间，包含各自实际安全合同；不含单独记录的夹具装配、远端推理和真实网络。

fresh 条件的核心前/中/后区间：

| 区间，中位数 ms | Web Service | QQ Session |
|---|---:|---:|
| 共享 Assistant 开始之前 | 2.463 | 724.028 |
| `AssistantService.send()` 内 | 14.112 | 476.658 |
| Assistant 结束之后至任务/历史完成 | 0.321 | 1073.489 |

逐样本三个区间可组成总时间；**各列独立计算的中位数不能强行相加等于总中位数**。四条件 120 对的均值差额：QQ 总额外 **2346.032 ms**，其中核心外额外 **1864.894 ms（79.49%）**，核心混合区间额外 **481.138 ms（20.51%）**。

### 4.3 实际入口 B：每格 n=30，单位 ms

| 条件 | Web 中位数 / P95 | Web 范围 | QQ 中位数 / P95 | QQ 范围 | 比较限制 |
|---|---:|---:|---:|---:|---|
| 当前水质 | 16.902 / 21.057 | 15.490～21.436 | 2205.225 / 2378.714 | 2147.802～2394.053 | 两边 2 HTTP + 1 Tool，合同仍不同 |
| 溶解氧 | 18.011 / 24.359 | 15.811～83.097 | 2358.342 / 2968.804 | 2143.014～3151.231 | 同上 |
| pH，部分缺测 | 18.300 / 24.417 | 15.729～24.864 | 2302.946 / 2917.154 | 2177.262～2930.215 | 同上 |
| 数据可靠吗 | 17.377 / 18.996 | 15.524～19.450 | 204.080 / 226.862 | 188.356～230.464 | QQ 模板，0 模型，不算 AI 加速比 |
| 带已交付历史的水温追问 | 19.421 / 32.157 | 15.446～33.132 | 3328.761 / 4301.547 | 2146.147～4347.998 | 两边均有实际前轮，历史投影不同 |
| 有没有低氧风险 | 23.054 / 31.011 | 16.038～31.479 | 356.709 / 431.228 | 258.569～501.398 | QQ 模板，0 模型，不算 AI 加速比 |

追问样本波动更大，模板条件也随主机状态变化；不能仅凭该组中位数把增加的耗时归因于历史长度。没有模型网络延迟参与本实验。

### 4.4 重复校验次数与混合区间

下面是每 Turn 次数的中位数；不把嵌套的不同 Scope 层相加成独立顶层检查次数。

| 操作 | A fresh Web | A fresh QQ | B 当前水质 Web | B 当前水质 QQ | B 追问 QQ |
|---|---:|---:|---:|---:|---:|
| 共享底层 `release_scope()` | 2 | 151 | 2 | 151 | 158 |
| QQ 真实试用顶层 `trial_scope()` | 0 | 151 | 0 | 151 | 158 |
| QQ `inputs_snapshot()` | 0 | 132 | 0 | 132 | 138 |
| Management Policy `snapshot()` | 2 | 288 | 2 | 288 | 301 |
| Shared Policy `load()` | 0 | 421 | 2 | 421 | 440 |

A 的 Web Policy 是隔离夹具中显式当前工具选择，所以不再读共享继承 Policy；B 保留原默认继承，仍有 2 次 Shared Policy 读取。这个差异没有被忽略。

fresh 条件中位数：QQ Scope 跨线程区间并集 **1884.357 ms**，配置/Policy 区间并集 **566.202 ms**；Web 分别 **0.085 ms**、**0.646 ms**。两组区间仍有交叠，不可相加。顶层 QQ Scope 的累计包围时间中位数 **2743.570 ms** 甚至大于总延迟，因为 watchdog 与执行/交付线程并发；这是观察区间，不是 CPU 时间或可保证删除的延迟。

### 4.5 更细的局部计时

fresh 条件各局部包围时间中位数，单位 ms：

| 阶段 | Web | QQ | 含义 |
|---|---:|---:|---|
| 第一次 Fake HTTP Handler | 0.107 | 0.095 | 内存请求解析/响应构造，非 Qwen 网络 |
| 第二次 Fake HTTP Handler | 0.274 | 0.300 | 含按实际 Tool 结果生成相同封闭解释策略 |
| 两次 Model Adapter 调用合计 | 7.865 | 117.248 | QQ 含额外准入/参数校验；不能当 HTTP 耗时 |
| ToolExecutor | 1.905 | 141.785 | QQ Guard 的重复授权在此混合区间内 |
| Monitoring 服务查询 | 1.215 | 1.613 | 两边都只查询一次 |
| 两次 SDK Client 关闭合计 | 0.006 | 0.006 | 仅正常合作的 Mock I/O |
| 两次 SDK 线程 join 合计 | 1.379 | 1.829 | 没有删除关闭或加入检查 |
| QQ DeliveryOwner | — | 947.407 | 包含多次校验、渲染、检查点和历史 |
| QQ 内存 HTTP Handler | — | 0.049 | 与 DeliveryOwner 区分 |
| ConversationStore.commit | — | 0.121 | 外层 accept_delivery 另含授权检查 |

精确排队、渲染、资源 settle、响应封装、History 等其余指标见 `stages.csv`；队列为空的微小调度间隔不代表并发队列压力表现。

### 4.6 冷执行、观察器和环境波动

- 本进程导入约 **986.582 ms**，单独记录，不加到每个 Turn。
- 首个 fresh 条件的首次执行：Web **353.973 ms**、QQ **2462.300 ms**；其正式热样本中位数分别为 16.801、2307.295 ms。每样本夹具装配另记，fresh 中位数 Web 94.73 ms、QQ 213.10 ms；夹具包含测试数据和配置准备，不能当成正式应用启动时间。
- 五次各 5000 次 no-op 微测：原函数中位数约 **56 ns/次**，观察器关闭的包装约 **1157 ns/次**，开启计时约 **2454 ns/次**。这是单线程测量器量级，不是多线程完整开销估计，原始结果在 `observer_microprobe.json`。
- 真实整轮观察器开关对照每状态仅 2 次：fresh QQ 开启 2302.666 ms、关闭 2397.450 ms；q1 QQ 开启 2218.785 ms、关闭 2184.585 ms。方向都不稳定，不能声称精确开销百分比，更不能把“关闭后更慢”解释为计时器加速。
- 全部条件的冷/预热/探针都保留在 `records`，不会混入 30 次正式样本或 P95。
- 同一 HEAD 在 BOT-3F-A 的少量离线测试中曾平均约 4.4 秒，本次约 2.3 秒；本轮没有优化生产代码。主机、缓存、观察方法和夹具差异使旧小样本不能充当加速对照。

## 5. 如何解释差异

| 验收问题 | 本轮结论 |
|---|---|
| 共享 AI 核心是否有相似开销？ | 相同 Fake HTTP 和 Monitoring 读取的局部成本相近；整个 Assistant 区间不相近，QQ 的授权回调进入了共享调用链。不能说共享核心跨度完全一样。 |
| QQ 额外 Scope/Policy 占多少？ | fresh Scope 并集约 1884 ms、配置/Policy 并集约 566 ms；重叠，不能相加。它们是强烈的本地开销证据，不是保证可省去的毫秒数。 |
| 各入口调用次数？ | Web 普通请求约 2 次共享 Scope、2 次 Management 快照；QQ 水质约 151 次顶层 Scope、132 次绑定快照、288 次 Management 快照。见上表，追问略增。 |
| 总耗时差多少？ | A 四条件 120 对的平均差额约 2.346 秒；B 的实际 AI 水质请求 QQ 约 2.2～3.3 秒中位数，Web 约 17～19 ms。均仅为本地 Fake 负载，不代表真实云模型性能。 |
| 是否主要 QQ 专用外围层？ | 核心外平均占额外时间约 79.5%；其余约 20.5% 在含 QQ 校验回调的混合核心区间。不能简单把所有差额归为纯网络或纯 Agent。 |
| 哪些优化只需 QQ？ | 同一边界的 Run/authority/Scope/绑定证据复用，QQ 交付链的嵌套重复计算。保留动态撤权、期限、SDK 状态和必要时间边界复核。 |
| 哪些会影响共享层/Web？ | 改通用 Policy Store、ManagementAssistantService、AssistantService、SDK Adapter、关闭协议或缓存策略。当前证据不支持先动这些。 |
| 优先级与风险？ | 先 QQ 内部重复计算，再用同脚本复测；领域 SQL、SDK close 和原 Agent 循环不是当前首要目标。新优化仍需 Scope 重算及权限/取消/交付回归。 |

代码解释与计时相互支持：`SessionTrialRun.check()`、内部 authority、基类 Run 检查、Turn 检查闭包、Handler Guard、Delivery 前回调和 watchdog 多次进入完整 Scope / 配置快照路径。Web 则主要在准备/执行边界解析固定配置；两边没有使用第二套 Agent。

本实验不能回答真实两次 Qwen HTTP 各耗时、真实 QQ token 刷新/发送 RTT、网络黑洞清理耗时或客户端显示时间。没有重新真实联调，也不使用旧 Trace 的缺失字段填造这些数字。

## 6. 最小优化建议与风险

1. 优先处理 QQ 单个校验边界内重复的 Run / authority / Scope / 配置快照构造。保留准入、执行、Tool、模型 I/O、发送前、历史提交前及 watchdog 的时间边界；不使用整个 Run 不再复核文件的缓存，不采用仅 mtime 的信任缓存。
2. 交付路径中完整校验的嵌套重复同样值得优化；API 提交前和历史提交前的最新权限/期限/SDK 检查仍有独立意义，不能删除。不能以已发送的模板或进度消息占用唯一回复权。
3. 不因 Tool 包围耗时高而优化 SQLite：先看 `monitoring.query` 和 `monitoring.repository_read`。观察到的 Handler Guard 开销不能误称领域查询耗时。
4. 共享 Policy/Service/SDK 的通用缓存、连接池化、改变关闭方式或 Agent 循环不属于本轮最小优化。它们可能影响 Web Normal/Streaming，风险大于 QQ 专用校验复用；没有证据支持现在改这些。
5. “数据可靠吗”“低氧风险”的确定性意图覆盖可另列 QQ 交互任务。它会改变哪些消息收费，应独立审批 Scope、权限与费用测试，不能混入性能优化悄悄开启。

预计仅 QQ 的优化位置：`session_run_trial.py`、`session_run.py`、`ai_coordinator.py`、`ai_delivery.py` 以及 QQ 配置快照装配。涉及 `ManagementAssistantService`、共享 Policy Store、`OpenAICompatibleAdapter` 或 `AssistantService` 的修改，需要 Web 独立回归和更严格兼容性审查。

区间并集不是可直接扣减的加速承诺。下一轮应以同脚本重新对照，证明本地延迟和重复调用数降低，同时验证撤权、Scope/设备变化、SDK 失败、送达未知及历史提交不回归。

## 7. 验证、文件状态与停止点

- 实验工具自身 **14/14 测试通过**：不足样本不报 P95、失败不丢失、观察器嵌套/恢复/禁用、目录越界拒绝、报表错误不重试、参数冲突和四种合成领域情景。
- 既有 Web Normal HTTP、Web Streaming 及 QQ 五轮/失败送达专项合计 **48/48 通过，41.330 秒**。只使用新建隔离数据和假 SDK，没有运行 Streaming 性能排名或与 Normal 混排。
- 完整基准 **600 正式样本 / 740 总测量记录，零失败**；首次 Core Smoke **16 正式样本**，PowerShell 实际入口的 Entry Smoke **24 正式样本**，全部通过。
- PowerShell AST、Python AST、`git diff --check` 通过；`-Smoke -Benchmark` 冲突安全拒绝，没有继续运行驱动。
- Scope 核对：`e92595b351669bfb8fe5e0be87f0a6cbfaf7463803e93b0b982b1d7f31427ef2`，与原持续会话准备资源完整匹配，仍 `candidate`、`qualification_id=null`。没有重写资格、批准或历史回执。
- 本次测量前后，原有 382 个已跟踪 apps/scripts 文件摘要一致，三个测量入口/观察器文件也与采样时摘要一致；原 BOT-3F-A 未提交文档保留原状。仅新增开发工具、测试和本文，不 commit/push，不同步 Management。
- 未重跑完整 Python/Node 全套：生产执行逻辑和前端未改，本轮以工具测试、相关入口回归及测量自身的安全断言为验证范围，不把旧全套基线当作本轮结果。

关键交付路径：

| 内容 | 位置 |
|---|---|
| 完整 JSON 与逐样本/阶段 CSV | `outputs/performance/webqq-20261027T085904Z-ba6c457b/` |
| PowerShell Entry Smoke | `outputs/performance/webqq-20261027T091630Z-a805a998/` |
| 初次 Core Smoke | `outputs/performance/webqq-20261027T085625Z-8468d374/` |
| 原有代码与实验脚本身份 | 完整目录中的 `provenance.json` |
| 解释器与依赖 | 完整目录中的 `environment.json` |
| Scope 与回归 | 完整目录中的 `scope_verification.json`、`targeted_regression.json` |

完整运行结果只说明当前离线实现的本地开销。真实 Qwen、QQ 网络、token 刷新网络和客户端显示仍须在用户另行批准的 BOT-3F-C 中测量。本轮不实现 Chat Mode，不修改生产执行逻辑，不提交、不同步 Management。

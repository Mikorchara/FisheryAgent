# BOT-3G-FINAL：实验性真实 QQ Hybrid 试用准备

日期：2026-10-29。仅 Fishery_AI_Prototype。**本轮没有连接 QQ/Qwen，没有读取真实密钥或现有业务数据库。** 新入口允许操作者在本机审阅并重新批准后自行联网；不是生产发布或普通知识准确性资格。旧普通 CLI 仍 AI_DISABLED，旧 Fake Hybrid、本机研究、FAST、TwoTurn 和 Water Session 不自动切换。

## 1. 可以直接操作的入口

在 PowerShell 7 中进入 Prototype。复用此前明确指定的 request；其中的群、成员、实例和设备必须仍是你要测试的对象。没有目录扫描、自动换库或凭据迁移。

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
.\scripts\dev\Test-QQHybrid.ps1 -Check -RequestFile '.\outputs\qq-bot\conversation.request.json'
```

Check 仅核对配置文件、Policy、固定 Preset、预算及实际实现 Scope，不打开 Monitoring、不解析凭据、不联网、不创建或消费批准。检查通过不代表密钥可用、QQ权限正确或观测新鲜。

操作者决定批准联网后，亲自执行：

```powershell
.\scripts\dev\Test-QQHybrid.ps1 -Run -RequestFile '.\outputs\qq-bot\conversation.request.json'
```

Run 会显示模型、实例/数据根、设备、群与成员的脱敏摘要、Scope、期限、最大Turn/请求和费用。终端明确披露实验性 General 的语义防护残余风险。**输入本次随机的 `APPROVE HYBRID <摘要>`，才批准 QQ、Provider、SIMULATOR/投影历史披露及实验性 General 自动发布。** Enter 取消；不逐轮审批。

| 参数 | 默认/约束 |
|---|---|
| `-MaxTurns` | 5；允许1～5，各成员共享 |
| `-RunSeconds` | 1800秒；最长30分钟 |
| `-TotalBudgetCny` | 8.02元；5轮保守预留8.013825元，不足拒绝计划 |
| `-Members` | 默认request指定的一人；可显式选择最多4名已有Access和AI授权成员，不自动扩大白名单 |
| `-ValidMinutes` | 审批等待最长10分钟；不是运行余额恢复期 |
| `-ReportRoot` | 默认本项目 `outputs/qq-bot/test-runs`，每次创建唯一目录 |

固定Preset当前为 `dashscope-qwen38-flash-r1` / `qwen3.8-flash`；以实际Check输出为准。Key在批准后由原Prototype私有CredentialStore延后解析，QQ Secret也由原供应器解析。缺失即失败，不复制Management或源码根`.env`，不输出密钥。模型/实例/成员不从聊天正文选择。

## 2. 装配与门禁

```text
Test-QQHybrid.ps1 → hybrid_trial_cli（复用Session控制器）
  → HybridTrialRun / 独立Scope / 一次本机RunConsent
  → 原QQ Gateway认证@事件、权限、去重、限流、单飞/容量
  → 原RunLedger原子预留 / 独立HybridRunAuthorization / TurnLease
  → 每轮私有HybridTrialQwenTurn / Service / Session / RequestHandle
  → 原AssistantService / ToolCallingService / TrialQwenAdapter / SDK资源门禁
     ├─ 0 Tool / 1请求 → General @2解析与有限发布检查
     └─ 1 Tool / 2请求 → 同轮Receipt/SourceSummary / 原封闭Water计划
  → 原Scheduler / DeliveryOwner / PassiveReplyOwner / SessionQQTransport
  → QQ API明确接受 + 文本SHA + 权限/revision → RAM历史CAS提交
```

没有第二套Agent、QQ发送器、SQLite或工具循环。真实Hybrid由精确Host、Turn、独立授权类型及授权issuer共同验证；不是改变Fake candidate、`can_send`或`can_deliver`。Fake Hybrid不能装配真实Transport，本机研究Turn仍是provider阶段，不取得QQ发布资格。

新Host仅经新的独立CLI启用。普通CLI和旧批准文件不能启用它。即使显式`/问AI`也必须有当前Gateway认证的群@证明，不能用包含@的文本或直接伪造内部消息触发模型。

## 3. Prompt与输出改动

基线 `QQ_HYBRID_DIALOGUE@1` 和 `qq-hybrid-reply@1` 保留。新入口使用独立 [QQ_HYBRID_DIALOGUE@2](../../ai_service/channel_hybrid_trial.py) 和 `qq-hybrid-reply@2`：

- JSON要求放在开头和结尾；“自然中文”明确限定在text字段，提供两条合法General示例。
- 一般概念不因出现水温/pH/溶解氧就查询现场；当前数值、可靠性、在线和风险须取得本轮Tool。
- 允许概念追问、澄清及切回一般知识，不增加收费意图关键词白名单，不新增模型分类器。
- General不能声称已查询/控制、提供现场读数或作安全/健康保证；History永远是不可信旧对话。
- Water仍只允许原六字段封闭计划，指标/规则/时效以实际Tool为准，不直接发布其自由文本。

```json
{"contract":"qq-hybrid-reply@2","kind":"general","text":"溶解氧是溶解在水中的氧气，为水生生物呼吸提供条件。"}
```

General在QQ加“实验性 AI 一般回答（非现场监测结论）”。Water加“本轮监测摘要（SIMULATOR；不代替一般知识解释）”，防止误选Tool后的监测报告被误认为概念答复；这不能自动修复模型选错Tool，错误仍须记录。

### 格式诊断与有限文本保护

新版区分JSON语法、重复字段、非有限常量、大小/类型、非对象、封装版本/字段和plan类型错误，只记录稳定代码，不记录被拒正文。没有修复围栏、自动补字段、第二次审核模型或重试。

General按标点和转折分句，少量完整的安全否定式说明可通过，例如“不能仅凭聊天确诊鱼病”“不能据此保证安全”；不以出现“不”就豁免整段。“不能否认当前水质正常”及否定句后的肯定现场断言仍拒绝。常见伪造读数、查询/操作成功及系统标志继续拒绝；补充已知“您那里此时挺稳，可以安心继续”样例。

**这是有限的发布防护，不是通用语义/逐句事实验证器。** 隐喻、外语、复杂转折、引述及新的隐含现场暗示仍可能漏检；一般知识也可能错误，安全说明可能误拦。免责声明不证明正文正确。操作者需单独接受实验风险，只在指定测试群成员范围使用；若不能接受任意漏检风险，应取消试用。

### SDK结构化输出兼容性

本地SDK的 `chat.completions.create` 暴露`response_format`，但这不证明当前DashScope端点、固定模型、Tool Calling和该JSON合同的组合受支持。本轮只运行Mock，不能验证服务器能力，**不发送未经验证的JSON mode/json_schema参数，不改变共享Adapter**。格式仍依靠明确Prompt+严格解析，失败安全拒绝/降级；真实格式成功率需要新的实际样本，不能用Mock改善替代旧48题的0/12结论。

## 4. 费用、交付和退出

每轮最多2请求、每请求512输出Token、90秒、零重试；1 worker/2等待位置。General通常只用1请求，仍完整预留1.602765元；未用请求不能兑换为Turn。失败、拒绝、超时、未知送达不退款。额度用尽阻止新AI准入，但最后已预留任务仍可完成。

免费固定指令、问候、帮助、清空不预留AI额度。`/清空会话`只影响当前成员历史，不退额度。新请求仍受入口限流约束，频繁连续测试可能先触发RATE_LIMITED。

Source/Commit、SDK资源已关闭、发送前权限/Scope/期限以及History前复核均保留。QQ发送超时或未知不重发、不重新推理、不提交成功记忆。API接受不等于程序确认客户端显示。General被拒可以发送程序说明，但不计为General成功、不提交成功AI历史；Water无效plan只展示本轮可信事实并记录降级。

持续运行到期或按Ctrl+C：原控制器取消关联任务、有界关闭Gateway/worker/API，保存`result.json`并清空RAM。不要直接关终端或强杀进程；OS强制退出/断电不能保证最终报告落盘，已存在的账本/交付检查点不能自动恢复余额或重放旧消息。SDK不合作线程仍可能无法强制终止；资源隔离后停止整个Run，不重置标志继续请求，本地取消不承诺远端停止计费。

每次目录保存 `plan.json`、`approval.json`、独占used声明、额度账本、`session.json`、逐Turn Trace/交付/结果、最终`result.json`及脚本`summary.json`。原聊天正文和原始模型JSON不写普通日志；实际发送文本只在有界RAM历史内保留，落盘使用哈希。报告可区分General/Water、模型请求、Tool次数、展示通过/降级、SDK、API和历史提交。

## 5. 人工验收顺序

默认5个付费Turn可用以下顺序；模板问候/帮助/清空不占5轮：

1. `@机器人 你好`；再发`@机器人 你能做什么？`，应由程序回复，不调用模型。
2. `@机器人 什么是溶解氧？`：预期General，1请求/0Tool、非现场标记。
3. `@机器人 它为什么重要？`：预期使用已接受的General历史，仍为General。
4. `@机器人 现在鱼塘水质怎么样？`：预期Water，2请求/1Tool，来源与新鲜度如实展示。
5. `@机器人 那溶解氧呢？`：预期重新查Tool，不使用上一轮旧读数冒充当前。
6. `@机器人 不谈当前鱼塘了，解释一下pH的含义`：预期切回General。
7. `@机器人 /清空会话`：当前成员RAM清空，额度仍已消费；第6个付费问题不能新增模型请求。
8. 等待运行期限正常退出或按Ctrl+C；检查 `report_saved=true`、`ram_cleared=true`、SDK各轮CLOSED/线程退出、实际请求不超10、未知交付无重试。用户另行确认QQ客户端显示。

真实模型可能选错Tool、输出无效JSON或被文本保护拒绝：这是实验失败样本，保留报告后在新Run复测，不修改used/批准或自动补跑。已有隔离实例中的数据可能已过期；Check不验证新鲜度，Run应如实显示stale/offline，不能改时间戳伪造在线。默认固定命令的Knowledge仍取决于现有授权/装配，Hybrid Agent没有Knowledge或历史Tool。

保留的交互限制：`/帮助`沿用原固定查询模块的帮助（其“未启用AI”标题描述旧固定指令模块，尚未按运行模式改写），Hybrid能力请发“你能做什么？”查看；不能据旧帮助标题判断本次Hybrid未启动。额度耗尽的拒绝码在终端/报告可见，当前不为每次拒绝额外保证群内提醒；免费命令仍可使用。以上不影响新试用的授权和模型路径，也没有为提示另外占用AI消息回复权。

## 6. 兼容性与修改边界

新增：`channel_hybrid_trial.py`、`hybrid_trial_presentation.py`、`qq_hybrid_real_trial.json`、`qq_bot/hybrid_trial.py`、`hybrid_trial_cli.py`、`Test-QQHybrid.ps1`和专项测试。

| 新增文件（项目根相对路径） | 职责 |
|---|---|
| `apps/ai_service/channel_hybrid_trial.py` | 新Prompt、Scope、身份型Hybrid批准、Turn装配及History判定 |
| `apps/ai_service/hybrid_trial_presentation.py` | @2格式诊断、有限General发布保护、原Water计划复用 |
| `apps/ai_service/resources/qq_hybrid_real_trial.json` | candidate准备快照，不是运行许可 |
| `apps/qq_bot/hybrid_trial.py` | 新Host、配置Check、风险披露及原Ledger/Controller扩展点 |
| `apps/qq_bot/hybrid_trial_cli.py` | 独立CLI薄封装，共享原会话控制器 |
| `scripts/dev/Test-QQHybrid.ps1` | 薄PowerShell Check/Run、一次审批、最终报告核对 |
| `apps/qq_bot/tests/test_hybrid_trial.py` | 42项新合同/真实类型Mock/故障测试 |

现有文件修改：`apps/ai_service/{channel_hybrid.py,service.py}`、`apps/qq_bot/{ai_coordinator.py,ai_scheduler.py,ai_delivery.py,ai_trial_delivery.py,session_run_trial.py,session_run_trial_cli.py}`、`scripts/dev/qq_bot_test_common.ps1`。公开准备资源刷新：`qq_conversation_candidate.json`、`qq_conversation_trial.json`、`qq_session_run_candidate.json`、`qq_session_run_trial.json`、`qq_session_run_trial_detailed.json`、`qq_hybrid_candidate.json`、`local_hybrid_research_trial.json`。文档更新README、BUILD_RUN、ROADMAP、STRUCTURE及本文。开始时已有C1-D评估文档/索引改动保留，未改其历史结论。

必要小改：Service对精确新Turn选择Prompt/展示；Coordinator精确新Host和真实@复核；Scheduler/Delivery/Transport允许精确新Host组合；原Session控制器/Host增加默认不变的配置、批准及Scope扩展点；PowerShell报告核对允许显式指定新合同。没有修改Backend/SDK、Monitoring、数据库Schema、规则或Agent循环。

新Scope `qq-qwen-hybrid-experimental-run@1` 仍是candidate准备记录，`qualification_id=null`；只有当前进程的独立身份型RunConsent才能产生`local_experimental`执行。Fake/local research/旧Session等公开准备资源仅刷新实际实现指纹，不提升资格。所有旧真实批准、used和Provider回执保持原样，不授权执行新代码。

## 7. 离线验证记录

证据目录：`outputs/test-tmp/bot3gfinal-20261029T010511-ef765137/`。

- 新Hybrid专项：42/42，73.247秒，`targeted-passed.log`。五轮G→G→W→W→G为7个实际SDK请求、2次当前Tool、5次API接受与History Commit；5轮完整预留不变，清空不退额度。
- 现有显式`conversation.request.json`的PowerShell Check通过：`qwen3.8-flash`、`bot2c-isolated / sim-pond-1`，只显示群/成员摘要，未打开库/读取密钥/联网/消费许可，见`local-check.log`。
- PowerShell缺配置、预算不足、Check/Run冲突均返回明确代码和退出码1，见`missing-check.log`、`budget-check.log`、`conflict-check.log`，没有继续到审批或网络。
- 新真实Hybrid Scope：`2982231963c682dd524d1740806fc870609928606876257eafdc44297434a3da`；以未来Check重算为准，后续代码变化必须刷新准备记录并重新批准。
- 新代码在完整回归前冻结。`verify.py`核对源码/公开资源/脚本277份及文档链接；Backend/SDK、Monitoring、Simulator、Knowledge、Web与旧`src`没有工作树改动。
- 完整管理Python **1244/1244**，657.551秒；Node **116/116**、11文件，约1.44秒，见`full-diagnostic.log`。覆盖旧Web Normal/Streaming、FAST、TwoTurn、Water Session、Fake Hybrid及本机研究、Monitoring、Simulator、Knowledge、SDK与QQ专项；全部通过，没有跳过失败用例。
- 首次普通点状完整运行在Web实例测试附近长时间无进展，已中断并保留`full-regression.log`；该单项独立运行通过。随后以同一`build_suite('management')`的全部1244项逐项诊断重跑，增加每个用例90秒后的只读线程栈观察，不改变测试断言/业务期限。重跑全通过，`slow-test-stacks.log`为空；首轮停滞未确定根因，不能据此宣称已修复某个运行时问题。
- 开发中间的失败日志保留：包括夹具限流窗口、方法签名/统计断言和Scope修改期间失效的早期运行；最终42项与完整回归在固定源码/Scope下通过。仅清理本轮已确认的旧隔离测试进程，未结束外部用户进程；最终没有本轮测试进程残留。
- `git diff --check`、170条文档链接、Python AST及模块/打包回归通过。旧历史报告/批准/used未改；开始HEAD为`347e5a8e65f390267d8218602f18f6fc921a8c87`、main，本轮不commit/push。

Mock证明程序在这些输入下的合同与失败处理，不证明真实Qwen的General可靠性、Tool选择正确率、知识质量或真实QQ客户端显示；上述人工验收仍待操作者执行。

## 8. 2026-10-29：Check 原生状态诊断修复

**现象 → 原因 → 解法**：操作者遇到 `WORKFLOW_NATIVE_NO_STATUS`。本次在当前工作树、项目 `.venv` Python 3.12.14 下，加载/不加载 PowerShell 配置的 Check 均通过；另在本机 PowerShell 7.6.9 下通过 Check（主要自动回归使用 7.6.5）。直接 CLI 输出一行合法状态 JSON、stderr 零行、退出码 0。不能据此确定操作者当次底层错误，也不能把它归因为端口、密钥或数据库。

已离线复现的确定缺陷：原 `Invoke-BotNative` 会把没有 JSON 状态的 Python import/参数/语法诊断全部抑制。例如合成 `ModuleNotFoundError` 原来只显示 `WORKFLOW_NATIVE_NO_STATUS`。Hybrid CLI 在共享控制器导入之前也没有自己的 JSON 异常边界。公共审批正则只识别 `APPROVE <12位小写摘要>`，遗漏 `APPROVE HYBRID <12位小写摘要>`；后者与 Check 无直接因果关系。

最小修复：

- `hybrid_trial_cli.py` 延迟导入共享控制器；启动失败返回 `HYBRID_CLI_DEPENDENCY_MISSING / IMPORT_FAILED / SOURCE_INVALID / STARTUP_FAILED`（均有 `HYBRID_CLI_` 前缀）的 JSON，退出码 1。不输出异常正文、模块名或路径。
- 公共封装在无合法状态时只显示固定诊断分类、真实退出码、输出行数及合法 JSON 行数。区分依赖缺失、import、语法、参数、Python 异常、启动失败、空输出与非法状态。无法分类仍保留 `WORKFLOW_NATIVE_NO_STATUS`，附安全元数据；不猜测错误根因。
- 原生启动错误也转换为安全代码，不泄露命令行或错误正文。退出码不受用户 `PSNativeCommandUseErrorActionPreference` 影响；不局部赋值遮住实际 `$LASTEXITCODE`。
- 保留原输出大小上限与中断；PowerShell 的 `ApplicationFailedException` 可能包装管道的 `WORKFLOW_OUTPUT_LIMIT`，按有界内层异常检查保留原安全错误，不误报启动失败。
- 精确兼容新旧审批挑战，拒绝长摘要、错误前缀及其他审批词。不自动输入批准。Hybrid Run 仍直接连接操作者终端，本次没有执行真实 Run。

检查命令不变：

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
.\scripts\dev\Test-QQHybrid.ps1 -Check -RequestFile '.\outputs\qq-bot\conversation.request.json'
```

缺配置返回 `WORKFLOW_CONFIG_MISSING`；预算不足返回 `RUN_BUDGET_INSUFFICIENT`；Scope 不匹配返回 `HYBRID_TRIAL_SCOPE_REVIEW_REQUIRED`。再次失败时，仅提供最终安全代码和 `WORKFLOW_NATIVE_DIAGNOSTIC` 元数据即可；不要粘贴原始异常、凭据或配置正文。

公共封装和 Hybrid CLI 属于实现 Scope，因此刷新三个公开 candidate 准备快照：`qq_session_run_trial.json`、`qq_session_run_trial_detailed.json`、`qq_hybrid_real_trial.json`；不提升资格、不修改旧批准/used/回执。当前 Hybrid Scope 为 `2484af5c360258704ab6750da8b31a1e1f19be755b72d7e2709657ee462d1b02`；第 7 节 Scope 是首次实现时的历史值。未来真实执行仍须当前进程的新批准。

本次证据仅在 `outputs/test-tmp/hybrid-check-fix-20261029T112137-831df5e6/`：原封装/修复后合成 import 故障对照、Check、专项与回归日志。Check 测试阻断 `sqlite3.connect`、网络连接与凭据供应器，并验证缺配置、Scope、预算拒绝；全部为合成夹具，不打开实际 Monitoring。未连接 QQ/Qwen，未修改 Management。

最终相关回归：QQ Bot **657/657**（550.623 秒，含 Hybrid 44 项和脚本 23 项）；Web AI Normal/Streaming 与 SDK 资源 **41/41**；Node **116/116**。脚本 23 项在 PowerShell 7.6.5 / 7.6.9 各独立通过。43 条相关本地文档链接、Python AST、候选 Scope 与源码哈希、`git diff --check` 通过。本轮没有重新运行整个管理 Python 套件，不把这些专项相加称作完整管理回归。

开发中间日志保留但不作最终通过证据：初版诊断补丁的退出码局部遮蔽、启动失败分类及嵌套输出上限误分类均由测试发现并修正；首个 Bot 回归为修正代码而主动中断。最终回归在固定源码和 Scope 下完成，未跳过失败用例；没有修改 Agent、SDK 资源门禁或交付语义，也没有生成真实批准。

### 同日追加：GBK 终端的准确复现

用户补充 `exit_code=0 / output_lines=1 / json_lines=0` 后，将 `[Console]::OutputEncoding` 设为代码页 936，已复现同样错误。Python 使用 `-X utf8` 输出中文 JSON，PowerShell 却按 GBK 解码，可能破坏 JSON 字符串边界；上一轮默认 UTF-8 终端未覆盖该条件。

`Invoke-BotNative` 现仅在原生调用期间将输出解码设为 UTF-8，并在 finally 恢复操作者原编码。保留全部 JSON、安全诊断、审批、输出上限及退出码合同。新增 GBK 终端测试，校验中文值完整解析且调用结束恢复代码页 936。公开 Session/Session Detailed/Hybrid candidate 快照按实际脚本指纹刷新，最新 Hybrid Scope 为 `afa55f3e7cdb37762d87c57f30986e5ae245f1a5d53e5d6636a74498f2f1b340`；上述旧哈希仅作历史记录。真实批准、used 和报告保持原样。

本次追加验证：脚本专项 24/24（39.226 秒）、Hybrid 专项 44/44（101.192 秒）通过；GBK 条件下公开 Check 退出码 0，原终端编码恢复。未执行真实 Run、连接 QQ/Qwen 或打开现有业务库。

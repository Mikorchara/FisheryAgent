# 管理平台启动、联调与验证

EVT-3A 起 Monitoring 使用 Schema v2：新空实例直接创建 v2，旧 v1 实例在普通启动时拒绝并提示显式维护。不要用重新初始化掩盖旧数据；须先停写、备份并在隔离副本验证。[显式迁移工具](../monitoring/migrate.py)。各实例的升级状态以其维护记录为准，本节不授权操作任何现有库。

## 快速开始 / 常用指令

### BOT 日常验收（PowerShell 7）

BOT-3F-B1/B2：新持续会话默认 Chat；本机可用 `-Mode Session -Presentation detailed -Check` 核对完整 A/B/C 模式。两种模式各自绑定新 Scope，旧批准不可复用；旧 TwoTurn/FAST 展示不变，没有群聊切换指令。[实现、性能与重新验收](deep-dive/BOT3FB12_CHAT_VALIDATION_OPTIMIZATION.md)。本轮未开展真实联网。

BOT-3E-C已完成[真实类型化持续会话装配的离线验证](deep-dive/BOT3EC_REAL_SESSION_ASSEMBLY.md)。配置检查：`.\scripts\dev\Test-QQConversation.ps1 -Mode Session -Check`；复用明确的旧request，默认5轮/1800秒/8.02元候选总预算，不打开库、不读密钥、不联网或消费批准。真实`-Mode Session -Run`须3E-D另行批准，启动时只审批一次。旧默认TwoTurn继续逐轮审批，不能复用旧批准或放大旧参数开启持续运行。

BOT-3E-B的Fake-only合同仍可独立检查：`.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot.session_run_cli --check-contract`。[B阶段记录](deep-dive/BOT3EB_BOUNDED_SESSION_OFFLINE.md)。新真实试用Scope与Fake-only candidate独立。

BOT-3D-2C-1新增独立双轮试用入口：`.\scripts\dev\Test-QQConversation.ps1 -Check`，只检查本机request引用与合同，不打开数据库、不读密钥、不联网。默认request为 `outputs/qq-bot/conversation.request.json`，先按[双轮说明](deep-dive/BOT3D2C1_REAL_CONVERSATION_TRIAL.md)人工填写。`-Run`需另行批准C-2，并在同一进程内逐Turn两次挑战确认；普通QQ CLI和旧FAST许可不扩大。

BOT-3D-2B的Fake Mention/记忆仍可离线复验：`.\.venv\Scripts\python.exe -X utf8 -B -m unittest apps.qq_bot.tests.test_conversations apps.qq_bot.tests.test_mention_conversation -v`。[2B阶段记录](deep-dive/BOT3D2B_MENTION_CONVERSATIONS.md)。普通QQ入口仍默认AI_DISABLED，不支持真实Mention或多Turn参数；真实执行只能经独立双轮或持续会话试用入口及其对应审批。不要给旧批准增加history或Turn数；共享实现指纹已变，旧批准和Provider回执不授权新代码。

QQ试用收到回复后优先等待`run-seconds`自动结束，确认最终`result.json`存在且`summary.json`中`report_saved=true`。中断报告缺失已补充处理，新增单次`result.delivery.json`交付快照；Ctrl+C/关窗仍不能承诺最终报告必定写完。[根因、状态和历史取证](deep-dive/BOT3D1_RESULT_REPORTING.md)。

BOT-3D-1已实现受限中文解释：Qwen选择要点，程序按同轮可信来源渲染；不放行原始正文。新v3 candidate及FAST Scope需要重新计划、审批和Provider回执，旧真实实验不授权新代码。[解释合同、失败降级与人工验收](deep-dive/BOT3D1_BOUNDED_EXPLANATION.md)。

在 Prototype 根执行；不带 `-Run` 默认只做指定实例的只读检查，AI 入口额外生成 pending 计划，不读取密钥、不联网、不创建批准：

```powershell
.\scripts\dev\Test-QQBot.ps1 -Check
.\scripts\dev\Test-QwenProvider.ps1 -Check
```

人工决定执行时分别用 `Test-QQBot.ps1 -Run`、`Test-QwenProvider.ps1 -Run`；QQ AI 用 `Test-QQAI.ps1 -Run -ProviderReport '上次成功Provider的绝对路径/result.json'`，必须明确指定真实成功回执，并独立批准 QQ。脚本保留原人工挑战、费用/期限/Scope 复核及一次性消费。[完整参数、失败处理与示例](deep-dive/BOT_TEST_WORKFLOW.md)。

此前用户报告FAST端到端成功；随后人工收到BOT-3D-1完整A/B/C，但中断导致QQ最终报告缺失。本次修复仅离线复验，历史Backend trace和客户端人工观察不能补造API接受回执。模型自由文本仍不展示，普通`apps.qq_bot --connect`的`/问AI`仍是AI_DISABLED。[阶段总结](deep-dive/BOT_STAGE_SUMMARY.md)、[本次报告修复与指纹](deep-dive/BOT3D1_RESULT_REPORTING.md)。

原 FAST 的 5 项 Fake QQ 失败已在 BOT-REGRESSION-1 最小修复：不改真实期限，成功路径按任务合同观察，合并同次复核的重复 Scope 构建。[完整结果与诊断](deep-dive/BOT_REGRESSION1_FAST_STABILITY.md)。FAST 实现指纹已变，以前的计划/批准和 Provider 前置回执不可复用，真实实验必须重新生成并审批。

### BOT-3C-FAST：Qwen + QQ 受控单轮试用

独立维护入口 `.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot.trial --help`，按“计划 → 交互审批 → 只读检查 → 另行批准后单轮执行”操作。Provider/QQ分别批准，每个批准仅一次；普通QQ CLI仍AI_DISABLED，SDK清理失败门禁保留；未使用的进程隔离草稿已在 BOT-CLEANUP-1 删除。[审批、费用与完整命令](deep-dive/BOT3C_FAST_QWEN_TRIAL.md)。本轮未执行真实联网。

本机准备已提供独立 `outputs/qq-bot/ai.qwen-fast.provider.json`，仅绑定BOT-2C的sim-pond-1及原有一个成员。Prototype与独立Management的私有Store按项目根隔离，不能自动共享Key；当前窗口仅做路径/ACL元数据检查，未读Key。[第7节：实际路径、凭据复用条件及可复制PowerShell步骤](deep-dive/BOT3C_FAST_QWEN_TRIAL.md)。

### BOT-2B 指定 Monitoring 实例只读查询

BOT-3C-2A 的 SDK清理失败会报SDK_CLEANUP_FAILED/TIMEOUT并隔离后续AI请求；不要循环重试或清空状态。仍未取得不合作线程的硬退出保证，进程隔离设计仅保留历史文档；FAST 仅通过独立一次性试用入口执行。[状态区分与剩余风险](deep-dive/BOT3C2A_SDK_RESOURCE_GATE.md)

BOT-3C-1：在 Prototype 根执行 `.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --check-ai-readiness`，仅核对维护者候选Scope，不读取密钥/实例或联网。退出0表示候选一致且**仍禁止真实AI**；`/问AI`保持AI_DISABLED。SDK不合作清理、真实Scope/费用/实例和QQ批准、真实装配仍是前置条件。[准备结果与人工验收清单](deep-dive/BOT3C1_REAL_AI_PREPARATION.md)

BOT-3B-1/2 提供 AI 服务边界、有界队列、取消及单次交付；普通 QQ CLI 的 `/问AI` 仍禁用。独立 AI 配置不能代替 FAST 的真实模型审批。[边界](deep-dive/BOT3B1_QQ_AI_BOUNDARY.md)、[调度/交付](deep-dive/BOT3B2_QQ_AI_SCHEDULING.md)

新增 `--monitoring-config`，与 `--help-only` / `--fictional-data` 互斥。仅在用户单独批准实例和设备后使用；不会自动选择工作区或正式库。先运行 `--check-config` 做纯配置检查，再显式 `--check-monitoring` 只读预检，最后另行批准 QQ 联网。配置模板、完整命令及安全边界见 [BOT-2B 验收](deep-dive/BOT2B_MONITORING_READ_ONLY.md#5-真实实例人工接入步骤待单独批准)。本轮只完成隔离数据验证，未打开真实实例。

### BOT-1B QQ 官方测试群联调

Prototype 已增加官方 WebSocket 通信层。不要将密钥写入源码或访问 JSON；在项目根执行 `.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --configure-secret` 隐藏录入，再按 [BOT-1B 配置与人工验收](deep-dive/BOT1B_QQ_TRANSPORT.md#2-本机配置与人工验收) 发现 OpenID、编辑白名单，显式启用网络。原 help-only / 临时虚构数据模式保留；指定实例走上方 BOT-2B 独立批准流程。没有 LLM、主动通知或群聊写操作；Ctrl+C 或限时结束回收连接。

### BOT-1A 离线实验

在 `D:\CodexProject\Fishery_AI_Prototype` 执行 `.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --offline-demo`；可加 `--command '/历史水质 30'`。只创建并清理本仓 `outputs/test-tmp` 内虚构实例，不读取现有数据、不连接 QQ/AI。后续 Bot 功能先在 Prototype 开发并人工验收，获批提交后再选择性同步 Management。[实现、限制及本轮验证](deep-dive/BOT1A_OFFLINE_PROTOTYPE.md)

### Web 与 Simulator

**本节只用于 Prototype**，在普通 PowerShell 中先进入项目：

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
```

已有工作区数据时，日常启动 Web + Simulator（默认每10秒上报）：

```powershell
.\scripts\dev\run_local.ps1 -Scenario normal
```
七个常用场景：normal、low_oxygen、oxygen_drop_recovery、suspected_disease、reduced_feeding、combined_anomaly、device_offline；

```powershell
.\scripts\dev\run_local.ps1 -Scenario suspected_disease
.\scripts\dev\run_local.ps1 -Scenario low_oxygen
.\scripts\dev\run_local.ps1 -Scenario oxygen_drop_recovery
```
仅启动 Web，使用已有工作区数据，不启动模拟器、不开启 HTTP 写入或 AI：

```powershell
.\.venv\Scripts\python.exe -m apps.management_web --port 8766
```

使用**已初始化**的隔离开发实例进行模拟联调：

```powershell
.\scripts\dev\run_local.ps1 -Scenario low_oxygen -DataRoot "$PWD\outputs\dev-instance"
```

| 常用参数 | 用途 |
|---|---|
| `-Scenario normal` | 上述七个常用场景；默认 normal，无交互 |
| `-Port 8767` / `-Seed 42` | 改端口 / 随机种子；Web-only 使用 `--port` |
| `-NoAssistant` | 模拟联调关闭 AI；不读取私有凭据，不改变数据写入行为 |
| `-NoStreaming` / `-NoMultiRound` / `-NoHistory` | 关闭相应既有试用开关；三工具开关与 History/传输组合仍按原实现联动 |
| `-DataRoot '绝对路径'` | 显式已有隔离实例；缺库拒绝，不自动创建或回退 |

访问 **http://127.0.0.1:8766**（端口改变时同步修改地址）。前台启动器就绪后会提示地址，不自动打开浏览器、没有双终端菜单。**在启动 PowerShell 中按 Ctrl+C** 回收本次两进程；不要直接关闭或强杀 Prototype 启动终端，当前没有 Management 的 Job Object 强制回收保证。

默认工作区路径是 `outputs/management_web`、`apps/knowledge_data/knowledge.sqlite3` 等兼容路径；`-DataRoot` 将业务数据集中到指定实例。正式 `%LOCALAPPDATA%\FisheryManagement` 与 Prototype 实验数据应分开；不要使用 `-UserData` 给正式管理历史注入模拟数据。新隔离实例的显式初始化说明见 [独立运行准备](deep-dive/MANAGEMENT_STANDALONE.md)，不能初始化已有实例来掩盖缺库。隔离业务数据不隔离项目凭据。

`run_local.ps1` 默认启用已批准的 Qwen Normal/Streaming、多轮和三工具本地实验，启动不调用模型；Web-only 原 CLI 默认关闭 AI，完整 AI 开关与工具授权见下文“一行式常用命令”。模型请求仍由用户主动发送。此仓库未移入 Management 专有启动器，后续按“实验 → 测试 → 人工审核 → 选择性同步 → 独立回归”推进。

### 溶解氧快速下降 → 逐步回升

`oxygen_drop_recovery` 使用原生成器、窗口与 Seed，不直接写事件状态。每10秒上报，默认 Seed=42；从该次 Simulator 启动开始计时：

| 时间 | 溶解氧目标值与阶段 |
|---|---|
| 0–20秒 | 约 6.4 mg/L，正常保持 |
| 20–50秒 | 快速降至约 2.2 mg/L |
| 50–90秒 | 保持低氧 |
| 90–180秒 | 逐步升至约 4.2 mg/L |
| 180–300秒 | 继续升至约 6.4 mg/L |
| 300秒以后 | 保持正常，不周期重复 |

目标值经过原随机波动和窗口均值后显示，因此网页不一定恰好等于节点值。规则仍按原阈值生成、更新和结束事件；水温/pH 保持原正常目标，低氧期伴随模拟活动减少。仅用于演示，非设备安全标准或疾病恢复结论。重新启动产生新 Session，不清空原历史。

只在内存中快速验证6分钟、不上报、不访问数据库或凭据：

```powershell
.\.venv\Scripts\python.exe -B -m apps.simulator --scenario oxygen_drop_recovery --seed 42 --windows 36 --dry-run
```

此 dry-run 输出每窗口摘要，不打印完整报文。日常 `run_local.ps1` 会继续向选定实例写模拟观测；如需隔离，请使用上方已初始化的 `-DataRoot`。

### 事件列表与删除

事件记录、首页最近事件以风险周期展示，“是否确认”只有 **已确认 / 未确认**：确认针对当前等级，结束后表示最后等级是否确认；升级或降级后均需重新确认，早期等级的确认只保留在详情历史中。名称随可靠等级变化为“溶解氧偏低 / 溶解氧低 / 溶解氧极低”；结束后按历史最高等级显示，读数明确标为异常时读数。

已结束且存在 ACK 历史的周期，在“查看详情”或事件列表中选择 **删除已结束周期**，预览原始事件数及确认历史数，再明确确认。此操作永久删除整个周期及全部 ACK 历史，不可在应用内撤销；不删除水质历史、采样批次、当前值、知识或设置。活动、恢复观察、未核实、无可靠身份及仍受外部引用的周期不允许删除。原“清理全部已结束事件”仍跳过有 ACK 保护的周期，避免批量误删确认历史。没有自动清理真实数据。

## 详细配置与阶段记录

### 失联提醒人工结束（仅Prototype）

待核实事件的详情可按条件选择“人工结束此风险”，必填原因并确认。它只结束旧提醒，不代表规则恢复；历史和原始证据保留，新一次可靠异常会重新提醒。事件状态新增“已人工结束”筛选。可靠持续异常、恢复观察及已恢复事件不开放此操作；人工记录不参与自动裁剪或历史硬删除。Schema仍为v2，未修改真实实例，未同步Management。[边界与隔离预览](deep-dive/EVENT_MANUAL_END.md)。

以下保留技术配置、历史预算与验证沿革；日常启动优先用上方快速入口。当前管理页面品牌为“AI 监测系统”，不影响包名、接口或数据位置。

## 环境

MIG-2 独立发行模板、严格实例初始化、数据路径与 MIG-3 清单见 [独立运行准备](deep-dive/MANAGEMENT_STANDALONE.md)。当前原启动与数据默认不变；本轮未迁移真实数据。

- 独立离线入口：`.\.venv\Scripts\python.exe -I scripts/dev/run_management_tests.py`，阻断旧包并复用管理 Python/Node 测试。
- 未来明确创建空白实例：`.\.venv\Scripts\python.exe -m apps.management_web --user-data --init-data`；不是迁移命令，已有目标拒绝。
- 未来使用已有独立实例：`.\scripts\dev\run_local.ps1 -Scenario low_oxygen -UserData`，或 `-DataRoot '绝对路径'`；默认用户根 `%LOCALAPPDATA%\FisheryManagement`，缺库/损坏/Schema不兼容则拒绝，不建空库、不回退。Ctrl+C 停止自己的进程。

Credentials 保留独立私有位置，改项目路径可能改变凭据身份，MIG-3 须单独决定，不自动复制密钥。

Python 3.11+，使用根项目已有 Flask 依赖；SQLite、生成器和 HTTP transport 使用标准库。Node 用于前端测试，无需 npm install 或构建。所有命令在 `D:\CodexProject\Fishery_AI_Prototype` 执行；首次环境配置见根 [BUILD_RUN](../../docs/BUILD_RUN.md#环境与启动)。

## R2D-4B：连接测试与可调输出预算

启动仍为 `.\scripts\dev\run_local.ps1 -Scenario low_oxygen`，打开 `http://127.0.0.1:8766/#settings`。启动、读取设置及保存预算不请求模型；只有用户主动点击“测试连接”或聊天“发送”才联网。

### API Key：先测试，再保存

1. 在 Qwen 或 DeepSeek 密钥框输入新值，点击“测试新密钥（1次请求）”。本次只用输入值，不用已有环境或旧 Key，不写正式凭据文件。
2. 测试使用维护者固定 Normal / Thinking OFF 的 Provider 连接，最多 **1 次请求、8 output tokens、20 秒、retry=0**，不提供任何 Tool。认证失败、超时、网络故障、限流和 Provider 异常分别提示；失败不修改旧凭据。
3. 成功后 5 分钟内可点击“保存 / 替换密钥”。服务端单次保存凭证绑定 Key 的有盐摘要、Provider、epoch 和凭据文件 revision；改值、并发覆盖、过期或重复使用均拒绝。输入值只在本次请求与密码框中存在，不写浏览器持久化存储，成功保存后清空输入。
4. “测试已保存密钥”使用正式 Snapshot，可测试 PROCESS_ENV 来源，但不产生新值保存许可。PROCESS_ENV 仍优先且网页只读；环境值需在启动环境修改。清除 Key 沿用二次确认和私有文件 CAS/原子写入。

连接成功只证明固定 API 请求可完成，不证明 Tool Calling / Streaming、回答质量或模型发布资格。8-token 连接响应允许 `finish_reason=length`，正文不返回、不保存；Assistant 的截断与 Commit Gate 合同不变。保存凭证仅短期保留在服务器内存，重启后失效；最近测试提示为本页状态，不伪造长期资格记录。

### 输出预算

当前仅向**已通过原精确发布门禁的本地 Qwen OFF / Normal 或 Streaming / 2/2/3 范围**开放可调输出：推荐 **512 / 1024 / 2048 / 4096**，自定义支持 **1–4096 整数**。不接受 bool、浮点、字符串或越界值，不静默截断。Ollama、DeepSeek、不匹配 Scope、未启用 trial、单轮或候选范围不因此获得编辑权限。

在相应模型/模式卡片选择推荐值或填写自定义整数，点击“保存预算”；Normal/Streaming 分开保存。“恢复默认值”移除该模式覆盖，回到原 Scope 的预算（三工具 Normal 1024、Streaming 512；某些旧 Normal 范围原本未显式设置，则显示 Provider 默认）。**1–4096 是本轮批准的本地安全上限，非新增真实 Provider 资格结论；值太低仍可能截断，较高值仍受 120 秒 deadline 和现有响应限额约束。**

版本为 `management-qwen-output-range@1`：先匹配原模型/协议/Prompt/History/Tool/数据绑定精确 Scope，再将基础执行 revision、范围、选定值、预算版本绑定到新 revision；不删除旧 matcher、不复用旧固定预算真实资格。未配置覆盖时保留原请求编码与资格指纹，恢复默认也更新预算版本，使旧确认失效。浏览器聊天请求不能直接指定预算、范围或 Scope。

继续使用同一 `outputs/management_web/settings.json`；旧 v1 只读兼容，用户首次明确保存时原子写入 v2（偏好 + 独立双模式覆盖 + budget revision），不动真实 Policy/业务 SQLite。配置在准备/claim 时校验，执行中持有冻结 Runtime；设置保存只刷新下一 Turn 配置，不自动发请求/重试、不撤销成功 History。

Preset 对任意生成参数的能力仍可能为 UNKNOWN；本地预算沿用现有 ProtocolSpec 传输成本上限编码，不伪造能力证据。仅内部范围校验成功后赋予最多 4096 的 transport ceiling；默认仍保留 Adapter 原 Normal 1024 / Tool Streaming 512 ceiling。SDK 的 `max_tokens` 必须与选择值一致。Tool Call / Round / Request 仍为 **2 / 2 / 3，retry=0，整 Turn 120 秒**。

最少人工验收：输入新 Key → 主动测试 → 保存；改动输入应立即禁用保存。分别设置 Normal 1537、Streaming 2048，保存后主动发一条问题，核对运行面板与结果；恢复默认。真实测试可能计费，由用户亲自执行，Codex 离线验证不替代实际 Provider 兼容性。

专项：`.\.venv\Scripts\python.exe -m unittest apps.management_web.tests.test_settings apps.management_web.tests.test_settings_connection_budget -q`；完整入口仍为 `scripts/dev/run_tests.py management` 与 `fast`。

R2D-4B 离线验收：管理回归 **458 项 Python（102.480 秒）/ 87 项 Node**，FAST **165 项（1.438 秒）**通过。Fake SDK 经管理 HTTP/SSE 验证 Direct Final、单/双 Tool、1537/2048/4096 实际 `max_tokens`、资源关闭、Preview→Final 与 History；虚构密钥覆盖认证/网络/超时/限流、测试后改值、并发保存及 PROCESS_ENV。隔离浏览器验证预算保存、桌面/390px布局，无控制台错误；未请求真实 Provider，未修改实际凭据/Policy/数据库。

## R2D-4A：系统设置中心

以下保留初版说明；密钥保存流程与可调预算以本页 R2D-4B 为准。

仍使用一行命令 `.\scripts\dev\run_local.ps1 -Scenario low_oxygen`，访问 `http://127.0.0.1:8766/#settings`。无需新启动器，不执行连接探测。

- **常规设置**：默认 Qwen/Ollama、监测设备、Normal/Streaming、聊天详情面板偏好。点击保存后，下次重新打开页面恢复；当前聊天和已启动 Turn 不变。文件为 Git 忽略的 `outputs/management_web/settings.json`，不存密钥，不修改 Tool Policy 或 SQLite。保存校验当前设备与实际发布条件；关闭 Streaming 试用后，已有 Streaming 默认值会显示不可用，不自动降级或联网。
- **模型管理**：展示维护者固定的模型 ID、连接地址、能力与当前 Normal/Streaming 可用性；“选择为默认”进入常规草稿，仍须保存。协议支持不等于产品已开放，凭据已配置不等于连接已通过。当前不编辑 Preset 身份或增加模型，DeepSeek 不因此进入管理 Assistant 列表。
- **API 密钥**：Qwen/DashScope 与 DeepSeek 使用固定 Provider 入口，输入新密钥后明确保存/替换；清除需第二次确认。只返回状态与不透明并发版本，不回显完整值。Windows 仍使用 `%LOCALAPPDATA%\Fishery_AI_Prototype\project-<项目身份哈希>\credentials\.env`；由既有私有目录安全机制创建，原子替换时保持权限、无源码根 `.env` 回退。同项目 Prototype 使用该相同正式凭据位置，后续请求会看到用户明确保存的更新；已运行 Turn 保留原 Snapshot。PROCESS_ENV 优先且只读（包括空变量），须在启动环境中修改；Ollama 无需 Key。不要把密钥复制到聊天、URL、Git 或浏览器持久化存储。
- **回答与执行预算**：展示服务器实际输出上限、请求数、Calls/Rounds、整 Turn Deadline 与 retry。当前精确 Scope 没有获批的替代 Token 数值，因此仅展示、不提供任意滑块。三工具 Qwen Normal 为 1024、Streaming 为 512 tokens/请求；其他授权集合按实际配置展示，不擅自修改默认值。请求次数/Tool 预算和期限也不可在网页放宽。
- **Tool 授权**：继续使用唯一管理端 Policy，三个工具可独立启停；变更影响后续请求并使旧执行确认版本失效。
- **RAG**：只展示 TF-IDF、Top-K=3、Evidence 800 字符上限与内容索引快照。内容到知识库页管理，不开放 Embedding、Chunk 或高级检索参数。

分类切换保留草稿；“重新读取设置”需要明确放弃未保存输入。保存冲突、权限不安全、存储故障仅显示安全错误。所有写操作沿用本机 Host/Origin、loopback、JSON 和浏览器令牌；默认值另有 epoch/revision，密钥另有文件 CAS。此权限边界仅适用于本机开发，尚非远程生产账户管理。

验收：保存默认设备/模式 → 重新打开网页 → 确认选择恢复；在 API 密钥页由用户本人保存密钥并查看状态（不自动请求模型）；查看预算 → 按需调整 Tool 授权 → 主动发送 Normal/Streaming。设置变化不触发模型、不重试失败 Turn，不改变成功 History。

离线验证入口：`.\.venv\Scripts\python.exe -m unittest apps.management_web.tests.test_settings -q`、`node --test apps/management_web/tests/settings-ui.test.mjs`、`.\.venv\Scripts\python.exe scripts/dev/run_tests.py management`、`.\.venv\Scripts\python.exe scripts/dev/run_tests.py fast`。所有凭据写入测试仅使用临时目录和虚构值。

R2D-4A 历史验收：management 447 项 Python / 85 项 Node 通过；随后补充的最终专项 50 项 Python / 14 项 Node 通过（其中设置后端 10 项）；FAST 165 项通过。隔离浏览器验证默认恢复、桌面/390px布局，无页面错误；未调用真实 Provider，未操作实际凭据/Policy/数据库。自定义模型的具体阻碍：当前 ProfileRegistry 是进程内固定集合，管理 Service 与业务 Assistant 都校验 Preset 身份；尚无管理端 Custom Profile 持久化、能力证据与精确 Tool 发布装配。这些能力继续暂缓；现有 Qwen/DeepSeek 密钥连接测试已在 R2D-4B 实现。

## 一行式常用命令

以下从仓库根目录、正常用户PowerShell执行。先停止自己已启动的8766服务，不强杀未知进程。启动网页和模拟数据不会发送LLM请求或修改用户Policy。R2D-2B已获用户批准，启动器默认启用Qwen三工具Normal/Streaming本地实验，非正式released。

推荐一行启动（默认场景 normal；以下为逐渐低氧）：

```powershell
.\scripts\dev\run_local.ps1 -Scenario low_oxygen
```

访问 `http://127.0.0.1:8766`。前台启动器生成一次性接入令牌，仅传给自己创建的两个子进程，不打印/保存，也不改当前终端环境。模拟器每10秒上报；启动与刷新不会请求模型。端口占用时报 `LOCAL_PORT_IN_USE`，不杀外部进程。**在此终端按 Ctrl+C**，启动器终止并回收自己的模拟器和服务器。不要直接关闭终端或强杀启动器；这种退出方式无法保证执行清理。子进程意外退出时，启动器也会清理另一子进程并报告错误。

网页默认Normal。在「系统设置 → Assistant Tool 授权」按需授权当前水质、历史水质、项目知识；再到普通聊天选择Qwen、设备、Normal或Streaming，主动点击「发送」即授权本次模型请求，无需逐条勾选。历史不再需要快捷按钮或Profile。模型自行选择已授权工具，最多2 Calls/2 Rounds/3 Requests，retry=0，120秒；统一范围Normal每请求1024、Streaming每请求512 tokens。真实选择稳定性和回答质量尚未取得新资格，local_experimental不等于技术或生产认证。未授权工具不会提供给模型；关闭历史后，恰好Current+Knowledge继续使用原两工具合同与预算。其他模型不继承三工具范围。

R2D-2C：点击「发送」或 Ctrl+Enter 仅授权这一个冻结配置的 Turn（可能包含预算内多次模型请求，云端可能计费）。请求仍携带当前 epoch/revision 与 `confirm_network=true`；服务端继续复核本机访问、浏览器令牌、Policy、Scope、设备、预算和请求状态。过期配置在联网前拒绝，按提示刷新并主动重新发送；页面加载、刷新、恢复聊天和切换模式不请求模型，不自动重试。此交互仅适用于受控本机管理应用，不提供远程生产鉴权。下文旧阶段提到的联网勾选已由主动发送替代，人工资格 CLI 仍保留各自确认规则。

原服务器CLI仍默认关闭试用；显式启用统一范围的等价AI参数为 `--enable-assistant --assistant-tools-trial --assistant-multi-round-trial --assistant-streaming-trial`。`--assistant-history-trial`只保留旧历史单工具API兼容，不控制新的普通聊天。启动只创建CredentialStore，CredentialSnapshot仍在用户确认后的Turn解析，不读取源码根.env或打印私有Key。

按需关闭功能（先 Ctrl+C 停止旧实例，再执行一行）：

```powershell
.\scripts\dev\run_local.ps1 -Scenario normal -NoStreaming
.\scripts\dev\run_local.ps1 -Scenario normal -NoHistory
.\scripts\dev\run_local.ps1 -Scenario normal -NoStreaming -NoMultiRound -NoHistory
.\scripts\dev\run_local.ps1 -Scenario normal -NoAssistant
```

`-NoStreaming`只关闭Streaming；`-NoHistory`关闭统一三工具和旧历史入口，保留原两工具Normal/Streaming试用；后三个关闭参数一起使用恢复默认Normal单轮。先Ctrl+C停止本次两进程，再重新启动并刷新。`-Port 8767`、`-Seed 42`可选；不删除SQLite或改Policy，新epoch使旧确认失效。高级原CLI命令保留在下文，旧阶段的“历史查询”操作已被普通聊天替代。

聊天右上角提供「刷新可用状态」「进入全屏」「阅读 / 截图」「收起运行面板」。刷新只读取可用配置，同 epoch 不清除成功 History；运行中禁用刷新。全屏隐藏主导航，输入区保留；阅读隐藏输入/选择控件，以正常文档流展开**当前全部聊天**，可使用浏览器整页截图，并手动展开消息内 Tool 记录。运行中阅读仍保留 Stop，临时预览始终标记未提交。退出阅读返回之前模式，ESC 再退出全屏，恢复滚动位置；布局切换不发送请求、不改变 History。向上阅读暂停自动跟随，「回到最新」恢复，右侧问题标记仍可跳转。用户气泡保留右对齐与无障碍「用户消息」描述，不显示重复的「你」标签；Send / Stop 保留独立固定操作区。

日常小改动跑受影响层；管理完整离线链路使用：

```powershell
.\.venv\Scripts\python.exe scripts/dev/run_tests.py management
```

其他针对性命令（全部离线、临时数据）：

```powershell
.\.venv\Scripts\python.exe scripts/dev/run_tests.py fast
.\.venv\Scripts\python.exe -m unittest apps.monitoring.tests.test_water_history apps.ai_service.tests.test_water_history_tool apps.ai_service.tests.test_history_candidate apps.ai_service.tests.test_management_policy
.\.venv\Scripts\python.exe -m unittest discover -s apps/management_web/tests -p 'test_*.py'
node --test apps/management_web/tests/*.test.mjs
```

`management` 包含 Backend/AI业务、Monitoring、Simulator、管理 HTTP/SSE，并自动运行管理前端 Node；Python无重复收集。`fast`、`product`、`qualification` 含义不变：`product`仍不含上述完整管理层；资格基础设施变更才跑离线 `qualification` 或受影响的资格模块，不把它解释成真实请求。`--list` 只列数量，不运行 Python/Node 测试。

真实外部连接由用户从[统一人工入口](../../scripts/manual_real_tests/README.md#5-三工具-normal-候选r2d-2a)亲自执行。R2D-2A 已在隔离 SQLite/Fake SDK 验证启动、10秒实际HTTP上报、占用拒绝、清理、聊天双模式和布局；未启动用户真实数据服务、读取私有凭据或调用 Provider。详见[实施记录](deep-dive/R2D2A_PRODUCT_INTEGRATION.md)。

## 统一知识库（R2D-3B）

**升级前须先关闭管理服务器并完成显式数据迁移，实际用户库迁移另需批准。** 新程序只读取 `apps/knowledge_data/knowledge.sqlite3`，不自动创建空库或回退旧 JSON。先核对安全计划：

```powershell
$knowledgePlan = .\.venv\Scripts\python.exe -m apps.knowledge --dry-run | ConvertFrom-Json; $knowledgePlan
```

批准数量和 hash 后：`.\.venv\Scripts\python.exe -m apps.knowledge --apply --plan-sha256 $knowledgePlan.plan_sha256`。自动备份旧库与 JSON，不移动、不覆盖原文件；新目标已存在不会覆盖。完整步骤、全新安装与回滚见[知识迁移与备份](deep-dive/KNOWLEDGE_CONTENT.md#迁移操作须先批准关闭管理服务器)。

之后继续用顶部 `run_local.ps1 -Scenario low_oxygen`。在「资料与知识库」管理所有导入/用户文本，支持查看、编辑、停用、软删除及恢复；版本冲突会拒绝覆盖。导入原始来源保留，编辑不回写 Prototype。检索测试不调用模型；AI Knowledge Tool 仍需原 Tool Policy 授权。下载选择 Markdown/JSON 和当前启用/全部，UTF-8内容导出不构成自动同步源。

运行数据与备份受 Git 忽略、排除打包；Monitoring SQLite、用户 Policy、凭据与原 Prototype 不变。源合同仍为 R2D-3A 的动态内容 Scope，不修改 Prompt/Schema/模型预算或发布范围，不将历史真实资格冒充为新动态内容验证。

离线专项：`.\.venv\Scripts\python.exe -m unittest apps.knowledge.tests.test_content apps.knowledge.tests.test_unified_store apps.management_web.tests.test_knowledge_content`；前端：`node --test apps/management_web/tests/knowledge-ui.test.mjs`。`management` 入口包含这些业务测试。

## 只读启动

```powershell
.\.venv\Scripts\python.exe -m apps.management_web
```

访问 `http://127.0.0.1:8766`。读取已保存的监测数据或明确 NO_DATA；默认拒绝设备写入。可使用 `--port 8767`。原 Prototype 8765 独立保留；Flask debug/dotenv 关闭。

## Normal Assistant（R2B-3）

```powershell
.\.venv\Scripts\python.exe -m apps.management_web --enable-assistant
```

需同时接收模拟数据时使用 --enable-assistant --enable-ingestion，并按下文先设置开发令牌。AI 关闭方式：停止自己启动的服务器，去掉 --enable-assistant 重启；已有 SQLite 不删除，原 Prototype 不受影响。

启动、刷新和切换页面不发模型请求。网页进入“AI 智能助手”，选择 Qwen 或 Ollama、监测设备，输入问题并主动发送。默认单轮最多两次模型请求，多轮最多三次；点击发送授权本次 Turn，预算仍显示在运行面板。云端可能计费，Ollama 也会执行真实本机推理，并非 Mock。按 Ctrl+Enter 可发送，普通 Enter 换行。

Qwen 使用现有正式用户私有凭据，不需要复制 Key、创建项目 .env 或调整 ACL；缺失/权限错误只显示安全错误码。Ollama 须由用户正常启动既有本地服务与模型，本轮自动测试没有启动或请求它。

人工验收（真实模型调用须另行明确授权）：

1. 未收到上报时问“现在水质怎么样？”，观察 NO_DATA，不得出现 Demo 正常值。
2. 启动模拟器 normal/low_oxygen；比较网页与 Tool 的同设备观测时间、来源、数据质量和 PROTOTYPE 规则。持续上报期间批次可更新，不声称不同查询原子同步。
3. 停止模拟器，超过 30 秒观察 stale、超过 90 秒 offline；缺失/无效/部分窗口按实际状态解释。
4. 问“什么是溶氧？”，允许直接回答、未调用 Tool；再次询问当前值时应查询当前设备，不将历史当本轮来源。
5. 验证 History、模型/设备切换确认、清空、切出页面再返回、Stop 与错误重发；取消/截断不提交成功回答，Stop 不保证远端计费停止。
6. 仅暴露实际授权的工具；无授权时显示“无”，不得越权。Policy、装配 Tool 集合或定义变化使旧 revision 失效，刷新核对后主动重新发送。

### 项目 Knowledge Tool 使用

默认仍只授权水质。需要Knowledge时，在**新管理系统 → 系统设置 → Assistant Tool授权**中保留既有选择、勾选项目知识并保存，再返回聊天刷新/确认。管理端独立Policy存在后，不再跟随旧Prototype Tool Manager的后续改动；没有独立文件时仅只读继承旧选择。保存管理授权不会修改旧Prototype，不需发送模型请求。

管理端执行 `python -m apps.management_web --enable-assistant`，打开 `http://127.0.0.1:8766` → AI 智能助手，刷新后核对“可用 Tool”含 `search_fishery_knowledge`。选择 Qwen/Ollama，逐次确认模型请求，再问“请检索项目资料，说明鳗鲡低氧表现”；观察项目背景 Knowledge 卡片、命中数/NO_MATCH。当前水质问题仍用 Monitoring Tool，不得把知识命中解释为当前 DO 或疾病确诊。真实模型请求须有用户授权；启动与授权配置本身不联网。

默认仍为 1/1/2。若模型同轮请求两项，TOOL_CALL_LIMIT 是安全拒绝；单轮配置第二次请求继续调用 Tool 为 TOOL_ROUND_LIMIT。双 Tool 顺序试用须按下一节显式开启。

离线专项：`python -m unittest apps.management_web.tests.test_assistant` 与 `node --test apps/management_web/tests/assistant-ui.test.mjs`。前者在临时 SQLite 上通过正式 Assistant/Registry/Executor/Source Gate/Trace 执行 Fake Provider HTTP 闭环，阻断所有外部 socket；后者运行实际前端模块的离线 DOM 行为。不是模型真实资格或回答质量证明。

## R2B-4：Normal Multi-Round 本地试用

```powershell
.\.venv\Scripts\python.exe -m apps.management_web --enable-assistant --assistant-multi-round-trial
```

访问 `http://127.0.0.1:8766` → AI 智能助手。同时接入模拟器时，在设置下文开发令牌后追加 `--enable-ingestion`。启动本身不调用模型；每次发送仍须明确确认。

- 在新管理系统设置中授权当前水质与项目知识，实际执行集合仍须精确匹配；授权历史不将其加入普通两工具请求。评分无Handler。页面显示“多轮 · 本地实验”、最多三次模型请求。
- Qwen优先，已有管理网页基本人工观察；Ollama有独立实验Scope，不继承Qwen或旧Prototype资格。二者仍是local_experimental，人工观察不等于正式released。固定OFF / Normal，每轮最多一个Tool，整Turn最多2 Calls / 2 Rounds / 3 Requests、retry=0。
- 开关启用但 Scope/Policy 不匹配时禁用发送；服务端联网前拒绝 `ASSISTANT_MULTI_ROUND_SCOPE_MISMATCH`。Policy/定义/配置/设备/epoch 改变时旧 revision 失效，刷新并重新确认；不自动重发、降级或切换 Provider。
- 配置来自 [管理专用 Scope](../ai_service/resources/assistant_execution.json)，在应用启动时冻结。文件的 `multi_round_enabled` 默认为 false，上述命令仅在本进程启用；浏览器不能指定模式、预算、Prompt 或配置路径。

人工验收（本轮未执行真实请求）：

1. normal 水质问“当前溶氧是多少？”：预期一次水质查询后 Final，也允许模型提前结束；记录实际路径。
2. low_oxygen 问“先查询当前水质，如果异常再检索项目资料解释低氧风险”：观察水质 → Request #2 → Knowledge → Request #3 → 唯一 Final。Tool B 必须由模型看到 Result A 后选择，不保证每次模型都按预期选择。
3. “什么是溶氧？”允许 Direct Final；NO_DATA/STALE/INVALID 如实解释，不补造正常值。Knowledge 卡片是背景来源，不替代当前观测。
4. 核对两个独立 Tool 卡片、完整有序 Steps、聚合 Usage；中途 Stop/Timeout/错误不得进入成功 History，清空/模型/设备切换及 epoch 语义不变。

回滚：停止自己启动的管理服务器，确认管理配置 `multi_round_enabled=false`，去掉 `--assistant-multi-round-trial`，用 `--enable-assistant` 重启。新 epoch 清理旧会话/确认，恢复 1/1/2；无需修改 Policy、SQLite、凭据或 Prototype 配置。执行失败不会自动按单轮重跑。

离线专项：`python -m unittest apps.ai_service.tests.test_execution apps.management_web.tests.test_multi_round`。使用正式 Assistant 多轮 Prompt、History、Registry、Executor、Ledger 与提交门禁，Fake Provider 根据真实临时 Monitoring Result 决定下一 Tool；不是实际模型质量或资格证据。

## 连续模拟器本机联调

同一 PowerShell 中创建仅本次开发会话使用的访问令牌，让服务器子进程继承；不显示、不落盘、不使用真实 API Key：

```powershell
$env:FISHERY_SIM_INGEST_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$managementServer = Start-Process -FilePath .\.venv\Scripts\python.exe -ArgumentList '-m','apps.management_web','--enable-ingestion' -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru
.\.venv\Scripts\python.exe -m apps.simulator --scenario low_oxygen
```

先打开网页，初次上报等待约 10 秒；约 60–120 秒观察溶氧逐渐降低和关联事件。也可选择 normal、suspected_disease、reduced_feeding、combined_anomaly、device_offline。device_offline 在场景 30 秒处停止上报，但进程继续等待，便于观察过期/中断。

停止模拟器按 Ctrl+C；服务器继续保存和显示末次数据。停止自己启动的服务器：

```powershell
Stop-Process -Id $managementServer.Id
Remove-Item Env:\FISHERY_SIM_INGEST_TOKEN
```

不要停止未由当前会话启动的进程。若 8766 已占用，服务器加 `--port 8767`，模拟器加 `--server http://127.0.0.1:8767`。可在独立终端分别启动，但双方必须继承同一个开发令牌；不要打印令牌或写入项目 .env。

可选参数：

```powershell
.\.venv\Scripts\python.exe -m apps.simulator --scenario normal --seed 42 --interval 10 --sample-period 1 --frame-period 0.5 --windows 6
.\.venv\Scripts\python.exe -m apps.simulator --scenario normal --switch-to combined_anomaly --switch-after 60
.\.venv\Scripts\python.exe -m apps.simulator --scenario combined_anomaly --dry-run --windows 12
```

dry-run 快速推进逻辑时间，不联网、不读取访问令牌。上报失败停止进程，不自动重试。重新启动使用新 session_id，sequence 从零开始；观测时间从新的启动时间继续。R1 静态 Demo 仅可用 `--legacy-demo` 显式启动，不能同时启用接入。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s apps/monitoring/tests -p "test_*.py"
.\.venv\Scripts\python.exe -m unittest discover -s apps/simulator/tests -p "test_*.py"
.\.venv\Scripts\python.exe -m unittest discover -s apps/management_web/tests -p "test_*.py"
.\.venv\Scripts\python.exe -m unittest discover -s apps/ai_service/tests -p "test_*.py"
node --test apps/management_web/tests/*.test.mjs
```

这些测试独立于根 product 发现范围。前两组除明确的 loopback HTTP 测试外不联网；只用临时数据库/虚构令牌，无真实 Provider 或 NPU。

R2B-2 日常 targeted：`python -m unittest discover -s apps/monitoring/tests -p "test_business_services.py"`，规则变更追加 `test_rule_governance.py`，调度变更运行 simulator/tests。真实 loopback 测试现在使用零人为时间缓冲；发送端先确认 UTC 窗口结束。SIMULATOR_CLOCK_OUT_OF_SYNC 时停止并检查时钟，不放宽服务器时间校验或自动补发。

R2B-3.2 读取/投影改动优先运行：`python -m unittest apps.monitoring.tests.test_water_capture apps.monitoring.tests.test_business_services apps.monitoring.tests.test_rule_governance apps.management_web.tests.test_assistant`。覆盖一次读取/诊断、并发新批次隔离、Web/Tool 同源、质量/来源/时间、DTO 大小、Ledger、Normal、取消及安全拒绝；无需调用 Provider。原 Web 交互继续用上面的 Node 测试验证。

R2B-3.3：`python -m unittest apps.management_web.tests.test_knowledge apps.management_web.tests.test_assistant`，配合上述 Node 测试。HTTP 测试复用正式 Registry/Handler/Executor/Source Gate，含本地 KnowledgeService + Fake Provider；所有模型网络被阻断，使用临时 Policy/SQLite。覆盖 NO_MATCH、参数/授权/检索错误、来源隔离、取消、单轮预算、定义/Policy revision 和 History；不是实际 LLM 选择或回答质量资格证据。

R2B-3.4 边界测试：`python -m unittest apps.ai_service.tests.test_service apps.management_web.tests.test_ai_boundary`。前者直接创建业务 Service + 临时 Monitoring/Fake Provider，复用调用方 RequestHandle，无需启动 Flask；后者验证 Web 令牌不传入业务、HTTP 门禁优先执行及 source identity。原 Assistant/Knowledge HTTP 测试全部保留，内部 patch/import 当前指向 `apps.ai_service.service` 与 `apps.ai_service.business_tools` 的实际 owner，不保留旧 bindings 入口。启动与端口不变，不新增 AI 服务进程。

界面验收：七页导航；窗口均值、有效样本和历史；视觉有效帧、加权体长检测记录与无标定缺失；零鱼帧计入数量均值；PROTOTYPE 规则和事件 ACTIVE / RESOLVED / INDETERMINATE；缺失、过期、离线不能确认恢复，只有可靠同版本新观测可消退；所有时间按北京时间显示到秒；停止后 >30 秒过期、>90 秒中断；恢复上报后更新；桌面与窄屏无溢出。读取失败清除当前展示并提示失效，不将缓存当实时。阻塞后的错过窗口跳过不补发，日志显示 skipped，历史保留时间缺口。

服务/合同变更运行相关 Python 和 Node；UI 变更增加浏览器行为与布局检查。涉及共享 Runtime 桥接追加其相关回归。文档变更检查链接与 diff。不要把测试启动器的旧授权当作真实模型执行许可。

## 数据与限制

存储为 `outputs/management_web/monitoring.sqlite3`，Git ignored；重启保留记录。不要删除已有数据库来“重置演示”，需要隔离测试时使用临时库和服务注入。

这是本机模拟接入，不是生产设备鉴权；AI 默认 503，显式启用后使用 Normal 安全门禁。真实视频、文件写入、用户权限与设备控制未开放。安全与 DTO 详见 [INTEGRATION](INTEGRATION.md)。


## 历史趋势人工检查（R2B-4.1）

重启自己启动的管理 Web，并刷新页面加载新静态文件；无需删除数据库或重新启动模拟器。综合总览 / 水质监测中，选择“最近 30 分钟”“最近 1 小时”或“全部存储历史”。范围以最后观测为终点，页上北京时间与 stale/offline 状态仍须保留。

核对：最近会话的 10 秒点展开；全部历史保留停机间距并在会话切换处断线；五个时间刻度不挤在首段，纵轴相邻标签可区分；窄卡片仅图表内部允许横向滚动。History 表与 API 仍保存全部有界历史，范围切换与 5 秒刷新只读、不采样。

专项离线验证：`node --test apps/management_web/tests/chart-ui.test.mjs apps/management_web/tests/monitoring-ui.test.mjs apps/management_web/tests/view-model.test.mjs`；`python -m unittest apps.monitoring.tests.test_history_projection apps.monitoring.tests.test_pipeline apps.monitoring.tests.test_water_capture`。固定测试数据不依赖用户真实 SQLite。


## R2B-5B：Streaming 后端离线验证

不带试用参数启动时仍关闭 Streaming；原 Normal 参数不变。R2B-5E 已获批准开放 Qwen 精确两工具本地实验，启用与回滚见下节；这不是正式 released。

```powershell
.\.venv\Scripts\python.exe -m unittest apps.ai_service.tests.test_streaming_config apps.management_web.tests.test_streaming
```

该测试从受控管理 HTTP POST SSE 路由进入，运行正式 Assistant Prompt/History、Gateway/Assembler、临时 SQLite Monitoring、Knowledge、Ledger、Trace 与提交门禁；SDK 为纯离线 Fake，网络被阻断，只容许 Windows asyncio 自身唤醒套接字。临时 local_experimental 配置只在测试实例内注入，不修改磁盘候选或用户 Policy。实际 max_tokens=512、2/2/3、120 秒、资源关闭和结果传递均有断言。新增桥接测试把三条实际 HTTP/SSE 路径的事件逐字节送入正式前端 parser / Workspace，验证各自只有一个成功 pair；不代表真实模型资格或回答质量。

## R2B-5C：聊天前端离线验收

```powershell
node --test apps/management_web/tests/*.test.mjs
.\.venv\Scripts\python.exe -m unittest apps.management_web.tests.test_streaming
```

页面操作：模式切换仅影响下一条消息，成功 History 共用，每次切换清除联网确认；执行中模式/模型/设备/Clear 冻结。聊天内部滚动，输入区保持位置；发送自动跟随新问题，向上阅读暂停跟随，“回到最新”恢复。右侧编号对应每个问题，悬浮查看摘要、点击跳转，Tab/Enter 和方向键/Home/End 可操作。

Streaming 临时正文在同一消息卡片内转为最终回答；Tool 请求、失败、截断、超时、Stop 或断线撤销预览，保留草稿且不写成功 History。不自动重连、重发或转 Normal。离开/刷新页面尽力取消原 Handle；后端已经完成但 Final 未到达时，浏览器仍不提交，远端计算/计费停止状态为 UNKNOWN。

R2B-5E 允许显式启动本地试用后人工检查 Streaming。关闭开关、candidate 或 Scope 错配仍拒绝发送；不继承原 Prototype 资格。

## R2B-5D：单案例资格准备

默认 Dry-run 的 `scripts/qualification/qualify_management_streaming.py` 固定三个案例 direct-final / current-water / low-oxygen；只考虑管理 Qwen 两工具 Scope、512 tokens/请求、2/2/3 和 120 秒。真实执行须逐案例批准并提供 `--confirm-network --plan-sha256`，可在交互终端选择 `--review-answer`，不保存正文或自动批准。用户已完成三个真实案例，技术均 PASS，共六次模型请求；人工回答质量仍待审，CLI 未验证真实浏览器 HTTP/SSE。

命令、报告与证据边界见 [Streaming Qualification](deep-dive/STREAMING_QUALIFICATION.md)。配置状态变化会改变后续资格计划 hash，旧报告保留，不补跑或覆盖。

## R2B-5E：Qwen Streaming 本地实验

用户明确批准本地试用，回答质量审核留待后续。维护者范围为 `local_experimental`，不是 `released`；qualification_id / validated_at 仍为空，不伪造人工批准。磁盘配置仍为 `enabled=false`，只在显式启动的进程中开启：

```powershell
.\.venv\Scripts\python.exe -m apps.management_web --enable-assistant --assistant-streaming-trial
```

访问 `http://127.0.0.1:8766`。如还需保留 Normal 2/2/3 本地实验，追加 `--assistant-multi-round-trial`；否则 Normal 仍为 1/1/2。两个开关独立，界面默认始终 Normal。模拟接入另按前文配置开发令牌后追加 `--enable-ingestion`，启动与切换本身不调用模型。

1. 在管理平台「系统设置 → Assistant Tool 授权」中，由用户明确授权水质查询与项目知识检索；不要修改默认Policy。管理覆盖未建立时才只读继承旧选择；已有覆盖后不要去旧Prototype Tool Manager更改管理授权。Streaming仅暴露这两个Tool，不装配评分。
2. 刷新管理页面 → AI 智能助手 → Qwen 3.8 Flash → 选择监测设备 → Streaming。核对“本地实验 · local_experimental”、512 tokens/请求与最多三次模型请求；模型/Policy/Scope 不匹配时页面解释原因，服务端在凭据解析/联网前拒绝。
3. 输入概念问题、当前水质问题，或“先查询当前水质，如果异常，再检索项目资料解释低氧风险”。勾选本次 REAL NETWORK REQUEST 确认后发送；一次确认覆盖最多三次请求及本地只读 Tool。检查独立 Tool 卡片、Steps、Usage 和预览原位转 Final；模型可以提前 Final，不保证每次都选 Tool。
4. Normal / Streaming 切换只影响下一条消息、保留成功 History并清除旧确认；执行中冻结模式/设备/模型。测试向上阅读暂停跟随、问题标记跳转、Stop 和断线撤销。临时预览、失败、截断及取消不进入成功 History；不自动重连、重试、切 Provider 或以 Normal 重发。

精确范围：`dashscope-qwen38-flash-r1` / OFF / STREAMING / `get_current_water_quality` + `search_fishery_knowledge`，2 Calls / 2 Rounds / 3 Requests、每轮最多一个 Tool、retry=0、120 秒整 Turn、每请求最多512 output tokens。Identity、协议、Prompt、History、definitions、数据绑定、设备、Policy、预算和 epoch/revision 必须匹配。Ollama、DeepSeek、评分与三工具 Streaming 均未开放。Tool 返回的模拟观测不是实际硬件采样；规则为 PROTOTYPE，知识为背景来源，回答质量尚未完成审核，512 tokens 仍可能截断。Stop 不保证远端计算/计费停止。

回滚：先在页面 Stop，停止自己启动的管理服务器（Ctrl+C），去掉 `--assistant-streaming-trial` 后重启：

```powershell
.\.venv\Scripts\python.exe -m apps.management_web --enable-assistant
```

若需保留原 Normal 多轮，回滚命令可追加 `--assistant-multi-round-trial`。新 epoch 撤销旧会话/确认；刷新页面，Streaming 被拒绝，Normal 可用。磁盘 `enabled=false` 不被启动参数写回；不用改数据库、Policy、凭据或原 Prototype。

本轮离线验证：管理配置/AI Service/资格兼容/HTTP SSE 与 Normal 相关 Python 124 项、共享 Streaming Assembler/Runtime/Source/Web 回归134项，合计258项通过；管理前端 Node 52项通过，包含 HTTP/SSE → 正式 parser/Workspace 的三路径桥接。覆盖512实际编码、发布拒绝、Scope/revision、双 Tool Result/独立Ledger、Preview→Final、Stop/超时/截断、History和回滚。未运行无关全量测试，没有调用真实 Provider/NPU，也没有启动实际网页推理；真实网页体验由用户后续验收。

## 独立 Backend：启动与回滚

管理Service/Web/SSE/管理qualification已统一使用apps.ai_backend和ai_service.runtime，不再运行旧LLM Runtime。正常命令和精确local_experimental授权保持不变：

修改业务 Tool、Prompt、Preset 或发布配置前先读 [开发指南](deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)。其中区分实际代码 owner、测试入口与需要另行批准的精确实验范围；本节命令不授予新的 Provider 或 Tool 资格。

```powershell
# 默认Normal，单轮；不启用Streaming
.\.venv\Scripts\python.exe -m apps.management_web --enable-assistant
# 本地实验：Normal多轮 + Qwen精确两工具Streaming，网页默认仍Normal
.\.venv\Scripts\python.exe -m apps.management_web --enable-assistant --assistant-multi-round-trial --assistant-streaming-trial
# 离线测试
.\.venv\Scripts\python.exe scripts/dev/run_tests.py backend
.\.venv\Scripts\python.exe scripts/dev/run_tests.py fast
.\.venv\Scripts\python.exe scripts/dev/run_tests.py product
.\.venv\Scripts\python.exe scripts/dev/run_tests.py qualification
node --test apps/management_web/tests/*.test.mjs
```

先停止自己启动的旧进程，再重启并刷新页面；新epoch使旧确认失效，不能自动重发问题。访问http://127.0.0.1:8766；沿用上文Tool Policy配置，必须授权水质+Knowledge才匹配Streaming Scope。本轮没有打开开关或修改用户Policy，默认关闭Streaming、Qwen两工具512/2/2/3/120秒/retry=0不变。

正式wheel已在outputs/r2c1d-build/env隔离环境以本机缓存setuptools84.0.0构建/安装，build-system>=68未改，不联网、不修改现有.venv。Wheel包括明确的管理应用包、JSON和静态资源，排除tests/outputs。源码启动保持原root；wheel安装后从有效项目工作区启动，无法确认时WORKSPACE_REQUIRED，避免变更私有凭据身份或写入site-packages。

管理资格计划升级management-streaming-qualification@2，增加apps.ai_backend@1标记，旧plan-sha不可复用；问题/Prompt/Scope/Schema/预算保持。旧报告不编辑或重新解释为新Backend真实运行。后续真实smoke必须另获明确授权并重新dry-run，不使用上次资格授权。

仅关闭试用的回滚：停止Web，去掉--assistant-streaming-trial和--assistant-multi-round-trial重启，恢复默认Normal1/1/2。若需回滚Backend代码：保存当前修改，停止自己启动的Web，整体恢复Phase I基线0cf64f6的service/contracts/bindings/execution/streaming、Web请求控制/SSE、管理资格与打包；不要只替换Adapter或Handle，不reset整个工作树，不修改SQLite/凭据/Policy/报告。重启新epoch，失败请求不自动重发。

R2C-1E：用户已通过真实管理网页完成 Qwen Normal 水质 Tool / Final、Qwen Streaming 水质 + Knowledge / Final 提交，以及模拟来源与 PROTOTYPE 标签的基本验收。迁移主线结束；回答质量专项审核与正式资格仍分开处理，local_experimental 和默认关闭不变。该人工观察没有新增资格 JSON、qualification_id 或 released 授权。

最终工程快速检查只运行 FAST、Backend 迁移/边界和管理前端离线测试；具体数量见 [收尾记录](deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md#15-r2c-1e-工程收尾与人工验收)。本轮未请求 Provider/NPU。`a256569` 是已提交的 Phase II 切换基线；`0cf64f6` 是需要整体回退旧管理装配时的 Phase I 参考点，不能以重置工作树代替审阅和完整回滚。

业务 Tool 组织与专项回归：Definition/Handler/validator 在 business_tools 的对应 Tool 模块，唯一装配入口为 registry.bind_tools；旧 runtime/tools.py 与 bindings.py 已移除。离线可运行 `python -m unittest apps.ai_service.tests.test_business_tools`；backend 测试层已包含该合同测试，前后 Definition/DTO 基线不因目录迁移重写。新增 Tool 操作见 [开发指南](deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md#2-新增业务-tool)。

## 管理端 Tool 授权与历史候选（R2D-1D）

1. 按本页已有命令启动管理服务并显式启用 Assistant；原 Normal/Streaming 启动参数保持不变。
2. 打开「系统设置 → Assistant Tool 授权」。首次读取只显示原有选择，不写文件。按需勾选/取消历史水质，再点「保存 Tool 授权」。保存前保留 Water/Knowledge 原选择，评分兼容项不可执行。
3. 保存只写管理端的 `outputs/tool-policies/management_assistant_policy.json`，不写 Prototype 共用文件。其他窗口已修改时必须重新读取再保存；损坏配置不会自动清空或恢复默认。
4. 保存使旧网络确认失效；下一条消息重新确认。已 claim 的 Turn 使用冻结授权，撤销对下一 Turn 生效；History/draft 保留。重新启动后读取同一管理配置，未存在覆盖时继续只读继承。
5. **此处是1D阶段准备记录**：界面授权不等于发布。历史单工具现已获批准，按下文1G启用；普通对话仍使用原两工具，三工具组合保持candidate。不要编辑JSON的status/enabled，也不要用旧Prototype Tool Manager写历史名称。

离线验证（全部使用临时数据与 Fake SDK）：

```powershell
.\.venv\Scripts\python.exe -m unittest apps.ai_service.tests.test_management_policy apps.ai_service.tests.test_history_candidate apps.ai_service.tests.test_water_history_tool
node --test apps/management_web/tests/*.test.mjs
```

后续真实单案例的准备、批准及 Scope 发布必须分开，见 [集成合同](INTEGRATION.md#历史-tool-授权与候选边界r2d-1d)。R2D-1E 已提供独立的历史单案例资格 CLI（默认 Dry-run，见下节）；现有 Streaming 资格脚本仅验证原两工具，不能代替历史资格。设置功能不是生产权限中心，未来账户/RBAC 需在同一 API 前增加身份与服务端授权，不能只隐藏按钮。

R2D-1D 验证：新增 Policy 7 项、历史候选 HTTP 10 项；Backend 整层 163 项、管理 HTTP/API 93 项、管理 Streaming 资格基础设施 17 项、FAST 164 项及前端 Node 55 项通过（测试层之间有覆盖重叠，不作唯一总数相加）。原六条 Normal/Streaming 路径和三个两工具资格计划 hash 基线不变；无真实 Provider/NPU 请求。历史 HTTP 成功路径仅在测试中 stub 未发布准入，真实 candidate 仍关闭。Markdown 本地链接/锚点、Python/JS/JSON 语法、diff 与改动文件敏感模式检查通过。

## 历史 Tool 单案例资格准备（R2D-1E）

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_history.py --case valid-history --dry-run
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_history.py --case no-data --dry-run
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_history.py --case partial-history --dry-run
```

省略 `--dry-run` 同样不联网。每个进程只有一个案例；三个案例各自计划 hash，不能复用其他案例或旧两工具授权。真实实验需先审阅计划、逐案例获批，命令和终端人工预览见 [历史资格操作说明](deep-dive/HISTORY_QUALIFICATION.md)。本阶段不开放 Web candidate，也没有启动历史试用的参数。

离线：`python -m unittest apps.ai_service.tests.test_history_qualification apps.ai_service.tests.test_streaming_qualification`；资格基础设施变更运行 `python scripts/dev/run_tests.py qualification`。Source/旧范围回归：`python -m unittest apps.ai_service.tests.test_water_history_tool apps.ai_service.tests.test_history_candidate`。这些测试均阻断真实模型网络，仅用隔离数据和 Fake SDK。

R2D-1F准备阶段将候选升级为1024 tokens/请求的v2计划。当时仅Dry-run；固定15 Turns/最多30请求的授权现已由用户执行完毕，不能再次复用。完整hash与执行记录见[历史资格指南](deep-dive/HISTORY_QUALIFICATION.md#7-r2d-1f固定15样本批次)，当前开放操作见下节。

## R2D-1G：历史水质单工具本地试用

> 以下保留1G阶段操作记录。R2D-2B普通聊天已统一三工具并移除历史快捷按钮；当前操作请使用本页顶部一行式命令，不再按旧按钮步骤操作。

**当前状态：local_experimental，默认关闭，非released。** 用户已完成固定15样本（30请求），技术全部通过，并批准精确Qwen范围。回答质量未审核；本轮开放只用Fake SDK回归，不重跑真实资格。结果和限制见[历史资格记录](deep-dive/HISTORY_QUALIFICATION.md#9-r2d-1g真实批次通过与本地实验开放)。

以下在同一个正常用户PowerShell终端执行。先停止自己已启动的8766服务器；不要关闭其他进程。使用既有私有Qwen凭据，无需读取、复制或打印Key：

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
$env:FISHERY_SIM_INGEST_TOKEN = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
$managementServer = Start-Process -FilePath .\.venv\Scripts\python.exe `
  -ArgumentList '-m','apps.management_web','--enable-ingestion','--enable-assistant',`
    '--assistant-multi-round-trial','--assistant-streaming-trial','--assistant-history-trial' `
  -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru
.\.venv\Scripts\python.exe -m apps.simulator --scenario normal --seed 42 --interval 10
```

服务器与模拟器继承同一开发接入令牌；不打印/保存该令牌。模拟器默认每10秒上报，当前真实窗口仍是10秒均值。可换成`low_oxygen`等既有场景。原Prototype Web不受影响。若只试历史，可省略两个既有multi-round/streaming试用参数，历史仍为Normal 1/1/2。

网页 `http://127.0.0.1:8766`：

1. 「系统设置 → Assistant Tool 授权」：保持已有选择，显式勾选历史水质并保存。不会写旧Prototype Policy或自动勾选其他Tool。
2. 「AI智能助手」：选择Qwen 3.8 Flash、监测设备及Normal，点击输入区的「历史查询」。页面显示「下一条：历史水质查询」及本地实验状态，预算仍为1/1/2、每请求最多1024 tokens。聊天页不再提供执行Profile选择器。
3. 确认「本次可用工具」为「历史水质」，勾选本次联网确认，问「过去10分钟溶解氧有什么变化？请说明数据覆盖」。不必等待完整30分钟，稀疏历史应返回PARTIAL；区间没有数据返回NO_DATA。
4. 核对历史Tool卡片、Source类型、唯一Final、Token/Steps。历史不能证明当前状态，不判断持续低氧或恢复；NO_DATA不是执行错误。Stop/超时/截断/失败不提交成功History，不自动重试或切换执行方式。
5. 历史查询成功后恢复普通提问，也可点击「取消历史查询」。成功History保留；变更业务操作、响应模式、模型、设备或实际工具范围均清除联网勾选。历史查询失败保留该业务操作，须用户处理后再次确认；不会自动重跑。模型/设备切换仍按原规则清会话。普通提问由模型在已授权的当前水质/Knowledge中选择；历史不自动加入该组合。

权限、Scope、版本或开关不匹配时发送被禁用/联网前拒绝，并显示原因。旧确认revision不能复用；启动开关随应用epoch冻结，运行中的设备/授权不随页面变化。

**关闭与回滚**：先在模拟器终端按Ctrl+C，再停止自己启动的服务器，去掉历史开关重启（既有两工具参数可保留）：

```powershell
Stop-Process -Id $managementServer.Id
.\.venv\Scripts\python.exe -m apps.management_web --enable-ingestion --enable-assistant `
  --assistant-multi-round-trial --assistant-streaming-trial
```

这不会删除SQLite或用户授权。新epoch使旧页面确认失效；刷新后点击「历史查询」会显示服务器未启用的具体原因，确认框与发送均禁用。需要同时撤销授权时由用户在设置中取消历史。无需删除历史数据、资格报告或修改JSON。全部联调结束后可执行`Remove-Item Env:\FISHERY_SIM_INGEST_TOKEN`。

产品Normal预算通过既有Adapter的内部`transport_output_token_limit`编码，严格Normal≤1024/Streaming≤512、retry=0；仅历史精确Scope装配Normal上限。没有使用development资格Adapter，也没有修改Tool循环、Prompt、统计或原两工具配置。

### R2D-1H：可用状态与三工具候选

- 「本地实验」是许可状态，启动开关和用户授权仍须分别满足。历史查询显示未启用时，重新勾选联网确认不能解决；按页面提示启用启动参数或到系统设置授权，再点「刷新可用状态」。禁止发送时确认框同时禁用且取消勾选。
- 历史查询在 Streaming 或其他模型下会明确提示选择 Qwen / Normal；页面不会替用户切换模式。历史成功后恢复普通提问并清除确认；已成功的对话不丢失。
- 三工具自主选择已建立独立 `management-normal-three-tools@1` candidate（当前水质、Knowledge、历史水质；Qwen OFF / Normal / 2/2/3 / 1024 tokens / retry=0 / 120秒），**未开放**。它不属于现有启动参数许可；R2D-2A补充了四个独立人工资格案例，尚无新增真实组合资格。两个旧Scope、历史单工具Scope和预算原样保留。
- 开放三工具前，须另行批准该精确候选计划，逐案例验证三类选择、Current→History、History→Knowledge、提前Final、参数、Result传递、Ledger/提交及三来源需求的预算限制，再独立批准本地试用。三个可选工具不表示可执行三个；当前预算最多两个，不能宣称获得未执行的第三来源。离线 Fake 不能替代真实选择证据。

R2D-1H 离线验收结果见[历史资格说明](deep-dive/HISTORY_QUALIFICATION.md#10-r2d-1h交互修复与独立三工具候选)。

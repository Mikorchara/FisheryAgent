> 历史归档（2026-10-31）：本阶段已被后续实现替代。保留设计与验收证据；当前操作见 [启动指南](../../BUILD_RUN.md) 和 [文档入口](../../README.md)。

# BOT-3C-FAST：受控 Qwen 单轮实验准备

后续：用户报告旧版FAST真实端到端成功，见[阶段总结](../../deep-dive/BOT_STAGE_SUMMARY.md)。2026-10-26 [BOT-3D-1](../../deep-dive/BOT3D1_BOUNDED_EXPLANATION.md)新增受限解释合同及新Scope；原始正文仍不展示，旧计划/批准/Provider回执不能用于新代码，操作优先用[简化入口](../../deep-dive/BOT_TEST_WORKFLOW.md)。下文保留FAST初始实施和审批合同的历史说明。

2026-10-25，仅 Prototype。本轮完成代码、离线装配和测试，**没有真实 Qwen / QQ 验收结果，没有创建真实试用批准文件**。普通 `python -m apps.qq_bot --connect ...` 仍不启用 `/问AI`。

## 1. 执行链与边界

独立维护入口：`python -m apps.qq_bot.trial`。`--prepare / --approve / --check` 不联网、不解析密钥；`--run-provider / --run-qq` 需要另外取得人工批准。

```text
本机计划、交互审批、网络确认 → QwenTrialSession
  → ManagementAssistantService → AssistantService → 原 ToolCallingService
  → 当前水质 Tool → InstanceMonitoring → 原 MonitoringService / mode=ro Repository
  → TrialQwenAdapter → 原 OpenAICompatibleAdapter / SDK资源租约 → AsyncOpenAI

QQ @ /问AI → 原入口权限/去重/限流 → QQAICoordinator → 原 QQAIJobScheduler
  → 上述同一 Service → Source Gate / Commit Gate / SDK资源关闭检查
  → 原 DeliveryOwner / 共用 PassiveReplyOwner → TrialQQTransport → QQAPI
```

固定 `dashscope-qwen38-flash-r1 / qwen3.8-flash`、Normal、SINGLE_ROUND 1 Tool / 1 round / 2 model requests、空 History、一个批准设备、当前水质只读查询、SIMULATOR 来源。不新增 Agent、工具循环、Knowledge、历史 AI Tool、写操作或 Schema；不改变 Web 默认装配。

模型未调用当前水质 Tool 时 Source Gate 拒绝成功，不自动重试来诱导调用。其他设备参数、Knowledge/写工具不存在对应可执行权限。原 `sdk_process_*` 草稿已在 BOT-CLEANUP-1 删除，仅保留历史设计；本机制继续使用原 SDK 资源门禁。

## 2. 独立 Scope、批准与失效

新合同 `qq-qwen-current-local-trial@1`，旧 v2 candidate 和 Web 三工具资格保持独立。计划绑定项目根目录、实际 Trial Adapter/原 Adapter、SDK及资源合同、RequestHandle、Prompt、Tool Definition、预算、关键执行代码、Provider/Preset/模型/协议；另绑定访问配置、独立 AI 配置、管理 Policy revision、实例文件身份、设备、群/成员与数据披露。

计划为 `pending_operator_approval`。只有本机终端审阅后输入 `APPROVE <计划摘要前12位>`，才生成独立的 `local_experimental` 批准，`qualification_id=null`。不生成 released 资格，修改 candidate JSON 或 `can_send/can_deliver` 无效。

- Provider 与 QQ 分开批准。QQ 必须引用同 Scope/绑定的本机真实成功报告；`OFFLINE_QWEN_TRIAL_TESTED` 不能满足前置条件。
- QQ 试用的 AI 与固定命令均收窄到本次批准的一个群/成员；访问文件中原有其他白名单不会自动获得本次试用权限，原文件不改写。
- 有效期从生成计划起计算，默认10分钟、最多30分钟，不自动延期；价格/上下文复核不能超过24小时。
- 每个批准最多一个 AI Turn。消费标记在已批准 AI 配置的目录下，名为 `.qwen-trial-<批准ID>.used`，防覆盖创建。复制/改名批准文件不能获得新名额，跨进程竞争只有一个成功。
- 崩溃、失败、密钥缺失或结果未知不退还批准；不自动重推理。不要删除 `.used` 来重试，须人工调查并重新审批。
- Scope、配置内容/文件身份/修改时间、Policy revision、实例身份或期限改变，旧任务失效；撤群、撤权、断线和停机会取消未交付任务。

这是**可信本机操作者的实验许可**，不是用户登录、数字签名认证或生产发布机制；同 Windows 账户下可修改代码/批准文件的人仍在可信维护边界内。计划与批准含 OpenID 和路径，只在本机保存，不进 Git、不贴公共日志。

## 3. 费用、次数与期限

2026-10-25 核验官方 [价格](https://help.aliyun.com/zh/model-studio/model-pricing) 和 [Qwen3.8-Flash 限制](https://help.aliyun.com/zh/model-studio/qwen3-8-flash)：北京区文本输入0.8元/百万 Token、输出2.7元/百万 Token，上下文100万 Token。实际批准前须再次核对账户/地域/现价，不计免费额度、缓存或优惠。

实现不把 UTF-8 字节当作 Token。每次实际请求 JSON 另限32KiB；为避免本机分词器差异，费用保守按每次**整个100万 Token 输入上下文**预留：

`2 × (1,000,000 × 0.8 + 512 × 2.7) / 1,000,000 = 1.6027648元`

向上取整为 **1.602765元**，示例申请2元上限。预算不足直接拒绝；这是最坏预留，不是预计消费。

| 限制 | 实施方式 |
|---|---|
| 一轮、两个模型请求 | 持久批准消费、Session/Handle所有权、原SINGLE_ROUND循环、Adapter/HTTP重复门禁 |
| 每请求512输出Token | 传输强制 `max_tokens=512`，整个Turn最多1024；思考关闭 |
| 零重试 | SDK retries=0，无Provider切换、禁止重定向/环境代理；未知不退款、不重试 |
| 实际POST有界 | HTTP hook最终校验权限、URL/方法/大小；每SDK Client最多一次，Turn最多两次 |
| 90秒总Turn | RequestHandle期限；排队占预算，批准更早到期则收紧；SDK原取消/清理门禁保留 |
| QQ有界调度 | 原1执行/2等待、10秒排队、原消息5分钟减15秒余量；试用自身仅准入一轮 |
| Usage缺失/超约定 | 拒绝成功，未知费用继续占用保守预留 |

报告区分 `usage_complete`、已返回Usage对应金额、保守预留和 `billing_confirmed=false`。未知Usage对应的0不表示零账单。

本地不能约束平台违反合同、价格改变或同账号其他程序的费用，也不能撤销已受理请求的远端计费。须由用户确认北京区价格/上下文依据及平台消费限制；不符则暂停重审。本轮未访问账户或设置平台限额。

## 4. SDK与输出安全

BOT-3C-2A 的共享 SDK 预算、清理失败隔离、RequestHandle、Source/Commit、Scheduler/Delivery 检查均保留。资源未确认关闭不能成功/交付，隔离后停止试用并拒绝后续请求，不自动清空门禁。

不合作线程仍无法可靠强制终止，合作取消的通过不证明所有真实网络/SDK行为都可结束。取消请求、本地I/O关闭、线程退出与远端停止/计费是不同事实，远端始终 unknown。FAST以单独风险批准接受此实验边界，没有删除旧预检的 `SDK_HARD_THREAD_EXIT_NOT_GUARANTEED`，进程隔离继续暂停。

只展示本次可信 SourceSummary；模型自由文本继续“未展示，尚未可靠核验”。保留 SIMULATOR、设备、观测/接收/评估时间、质量、新鲜度、连接状态；过期、缺测、离线不能称当前正常。日志/报告不保存问题、模型原文、密钥或Token，批准文件本身包含本机配置身份。

## 5. 人工操作（实际联网需另行批准）

### 5.1 本机变量与独立配置

路径均由用户明确填写，不自动发现业务实例；优先用另行批准的 BOT-2C 隔离 SIMULATOR 实例。旧测试数据过期就如实呈现 stale/offline，不改时间伪装在线。

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
$python = '.\.venv\Scripts\python.exe'
$access = Read-Host '批准的 access.json 绝对路径'
$monitoring = Read-Host '批准的 Monitoring 配置 JSON 绝对路径'
$ai = Read-Host '本次独立 AI 配置 JSON 绝对路径'
$policies = Read-Host '该实例原管理 Tool Policy 目录绝对路径'
$group = Read-Host '专用测试群 group_openid'
$member = Read-Host '授权成员 member_openid'
$trialDir = Join-Path $PWD 'outputs\qq-bot\trials'
[IO.Directory]::CreateDirectory($trialDir) | Out-Null
$runId = [guid]::NewGuid().ToString('N')
$planFile = Join-Path $trialDir ($runId + '.provider.plan.json')
$approvalFile = Join-Path $trialDir ($runId + '.provider.approval.json')
$receiptFile = Join-Path $trialDir ($runId + '.provider.result.json')
```

独立 AI 配置参考 `apps/qq_bot/examples/ai.example.json`，默认关闭。维护者在独立副本中设置 `enabled=true`、512/90预算、测试群/成员/设备及唯一 `get_current_water_quality` 后申请审批；此开关本身不能联网。不得修改全局Policy来扩大权限。

Qwen复用现有 `DASHSCOPE_API_KEY` 的私有 CredentialStore / 进程环境优先级；QQ AppSecret 使用原安全入口。Key不写命令行、批准JSON或计划。`--check`不验证Key是否存在/有效，实际运行时缺失仍消费本轮批准。

### 5.2 Provider计划、审批、只读检查（不联网）

```powershell
& $python -X utf8 -B -m apps.qq_bot.trial --prepare --phase provider --access-file $access --monitoring-config $monitoring --ai-config $ai --policy-directory $policies --group-id $group --member-id $member --max-cost-cny '2.00' --valid-minutes 10 --output $planFile --confirm-instance-read
if ($LASTEXITCODE -ne 0) { throw '计划未通过，停止。' }
Get-Content -LiteralPath $planFile
$approved = & $python -X utf8 -B -m apps.qq_bot.trial --approve --plan $planFile --output $approvalFile --confirm-instance-read | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $approved.status -ne 'local_experimental') { throw '审批未通过，停止。' }
$approvalHash = $approved.approval_sha256
& $python -X utf8 -B -m apps.qq_bot.trial --check --approval $approvalFile --approval-sha256 $approvalHash --confirm-instance-read
if ($LASTEXITCODE -ne 0) { throw '复核未通过，停止。' }
```

`--confirm-instance-read`仅允许只读指定实例，不允许迁移/写入或扫描其他实例。输出目录必须存在，所有文件防覆盖创建。

### 5.3 另批真实Provider后运行一次

**本轮未执行**。实际前须另批模型、两次请求/1024总输出Token、90秒、费用、实例/设备、模拟数据披露和线程剩余风险。

```powershell
& $python -X utf8 -B -m apps.qq_bot.trial --run-provider --approval $approvalFile --approval-sha256 $approvalHash --output $receiptFile --confirm-instance-read --confirm-provider-network
if ($LASTEXITCODE -ne 0) { throw '失败或资源未知；保留批准、used及报告，停止，不重试。' }
```

只有 `QWEN_PROVIDER_TRIAL_VERIFIED`、两次请求、Source/Commit成功及SDK明确 CLOSED 才算本机验证通过。报告包含可信来源摘要、Usage与资源状态，不打印模型原文。

### 5.4 本机通过并另批QQ后继续

新建QQ计划，不能直接改Provider批准的phase；必须引用本机真实成功报告。

```powershell
$qqId = [guid]::NewGuid().ToString('N')
$qqPlan = Join-Path $trialDir ($qqId + '.qq.plan.json')
$qqApproval = Join-Path $trialDir ($qqId + '.qq.approval.json')
$qqResult = Join-Path $trialDir ($qqId + '.qq.result.json')
& $python -X utf8 -B -m apps.qq_bot.trial --prepare --phase qq --access-file $access --monitoring-config $monitoring --ai-config $ai --policy-directory $policies --group-id $group --member-id $member --provider-receipt $receiptFile --max-cost-cny '2.00' --valid-minutes 10 --output $qqPlan --confirm-instance-read
if ($LASTEXITCODE -ne 0) { throw 'QQ计划未通过，停止。' }
Get-Content -LiteralPath $qqPlan
$qqApproved = & $python -X utf8 -B -m apps.qq_bot.trial --approve --plan $qqPlan --output $qqApproval --confirm-instance-read | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $qqApproved.status -ne 'local_experimental') { throw 'QQ审批未通过，停止。' }
$qqHash = $qqApproved.approval_sha256
& $python -X utf8 -B -m apps.qq_bot.trial --check --approval $qqApproval --approval-sha256 $qqHash --confirm-instance-read
# 以下仅在另外取得本次 QQ + Qwen 联网批准后执行：
& $python -X utf8 -B -m apps.qq_bot.trial --run-qq --approval $qqApproval --approval-sha256 $qqHash --output $qqResult --run-seconds 120 --confirm-instance-read --confirm-provider-network --confirm-qq-network
```

授权成员发送一次 `@机器人 /问AI 请查询当前水质并说明数据时效`。原固定命令保留。统一被动回复owner，每消息最多一次 `msg_seq=1`；发送前（含Token刷新后）重验权限/期限，未知不重发、不重新推理。Ctrl+C、限时结束、断线或撤权取消未交付任务并回收本次线程/连接。

`api_accepted=true`仅指QQ平台接受，`client_display_confirmed`始终false，用户需另行观察客户端。报告区分 `backend_completed` 与交付结果。

发送前复核不能撤回已经提交的消息；撤权/断线发生在POST期间时可能送达未知，仍不重发。真实QQ网络取消、关闭及终端交互仍需人工验证，不把MockTransport通过当作硬退出保证。

## 6. 文件与验证

新增：`ai_service/channel_trial.py`（Scope/预算/原Adapter子类）、`qq_bot/trial_configuration.py`（审批/消费/绑定）、`trial.py`（维护CLI与装配）、`ai_trial_delivery.py`（QQ传输）、`tests/test_qwen_trial.py`（离线专项）。

修改：`ai_service/service.py`的明确可选trial装配；QQ coordinator/scheduler/delivery/router的类型化试用支持；Gateway显式trial路由及生命周期；QQAPI最终发送前回调。没有改Agent循环、Monitoring、Schema或暂停草稿。

最终完整管理回归 **853/853 Python + 116/116 Node（11文件）通过**，Python阶段200.485s，总命令退出0。包括本轮新增37项试用专项；先行资源/调度/SDK/准备定向128项及Scope/暂停边界定向63项也通过。最终补充的其他群固定命令拒绝、空实例NO_DATA和partial缺测均纳入853项。

覆盖默认Web Normal/Streaming、原固定查询、Monitoring/Simulator/Knowledge及历史差分；新路径覆盖审批/过期/配置及Policy变更、并发消费、跨群设备权限、真实SDK类与MockTransport、构造/关闭失败、取消/总期限、Token刷新后拒绝、送达未知不重试、Fake Gateway完整运行/部分装配失败清理、来源及模型正文隔离。

12个相关Python文件AST、新文档链接与 `git diff --check`通过；无运行中的SDK子进程。原v2预检仍返回 `QQ_AI_PREFLIGHT_VALID_LIVE_BLOCKED`，真实执行/交付false、网络0、未读取凭据或实例；该预检只描述旧candidate，FAST使用本页独立审批。Prototype仍为 `main@7322f0d`，原未提交改动保留，未commit/push。

```powershell
$env:TEMP = Join-Path $PWD 'outputs/test-tmp'; $env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -X utf8 -B -m unittest apps.qq_bot.tests.test_qwen_trial apps.qq_bot.tests.test_provider_sdk_preparation apps.qq_bot.tests.test_ai_preparation apps.qq_bot.tests.test_ai_scheduler apps.qq_bot.tests.test_sdk_resource_gate apps.ai_backend.tests.test_sdk_resources
.\.venv\Scripts\python.exe -X utf8 -B scripts/dev/run_tests.py management
```

未验证：真实Key/账户/计费、真实DNS/TLS及不合作I/O、真实Qwen Tool Calling/时延/Usage、QQ回复和客户端显示。本轮未读取已有业务实例或真实密钥，未修改Management、真实数据、Settings/Policy/Credential，未commit/push；下一步等待人工授权。

## 7. 本机人工验收准备复核（2026-10-25，未联网）

本节是后续准备记录：仅只读检查用户指定的 BOT-2C 隔离实例，新增独立AI配置，不创建最终批准，不调用模型或QQ。

### 7.1 凭据位置：不能将两项目视为同一个 Store

Qwen Preset仍为 `dashscope-qwen38-flash-r1 / qwen3.8-flash`，引用 `DASHSCOPE_API_KEY`，优先级为当前进程环境 → 当前项目私有Store → 缺失。未调用 `CredentialStore.resolve/status/_project_values` 来检查真实密钥；这些方法会读取值。

| 默认启动项目 | 私有文件路径（仅检查元数据，未打开内容） |
|---|---|
| Prototype Web / 本次试用 | `C:\Users\HP\AppData\Local\Fishery_AI_Prototype\project-4e5f7b2702af5d742ab9\credentials\.env` |
| 独立 Management Web | `C:\Users\HP\AppData\Local\Fishery_AI_Prototype\project-bd0d253a3c5ffdfcfaaa\credentials\.env` |

两边路径解析源码相同，身份由项目根计算；业务 `--data-root / --user-data` 不切换凭据身份，显式覆盖 `--project-root` 则需要按实际启动值判断。两份文件均存在，**存在不代表其中必有 DashScope Key**，也可能只保存了其他凭据。

用户随后已明确确认：此前保存DashScope Key并成功调用Qwen的网页来自 **Fishery_AI_Prototype**。因此本次按同一Prototype私有Store复用，不需要重新输入或保存Key；这里确认的是来源/路径一致，当前有效性留待另批的真实单轮验证，助手没有读取Key。

如果此前保存Key的是Prototype Web，可复用同一Store；如果是独立Management默认身份，不能自动复用其私有文件。本轮不读、复制、迁移或重新保存Key，不修改任何ACL或私有路径规则。

当前Codex进程未设置 `DASHSCOPE_API_KEY` 引用（只测名称是否存在，未读值）；两处元数据/ACL检查均报 `SecureFileError / ENV_PERMISSION_ERROR`。这不能证明普通PowerShell也失败。应由用户在普通终端复核，不把它误判为应用或已有Key不可用。

### 7.2 已准备与通过的检查

| 项 | 实际结果 |
|---|---|
| 访问配置 | `D:\CodexProject\Fishery_AI_Prototype\outputs\qq-bot\access.json`，唯一符合当前水质权限的群/成员组合 |
| 数据源配置 | `D:\CodexProject\Fishery_AI_Prototype\outputs\qq-bot\monitoring.bot2c.json` |
| 数据库 | `D:\CodexProject\Fishery_AI_Prototype\outputs\bot2c-instance\monitoring.sqlite3`，实例 `bot2c-isolated`，设备 `sim-pond-1` |
| 独立AI配置 | `D:\CodexProject\Fishery_AI_Prototype\outputs\qq-bot\ai.qwen-fast.provider.json`，防覆盖新建且Git忽略；一个原有成员、唯一当前水质工具、512/90预算 |
| Policy | `D:\CodexProject\Fishery_AI_Prototype\outputs\tool-policies`，实际管理覆盖generation=11，原三工具选择保留；本次经Registry/AI授权交集只开放当前水质，不写Policy |
| 数据安全 | Schema v2、integrity=ok、外键违规0、query_only=1、连接changes=0；检查前后数据库、访问/源/AI配置及原Policy文件SHA-256一致 |
| 观测 | SIMULATOR；最后水质观测UTC `2026-10-24T18:55:28.308984+00:00`；partial/stale/offline。没有刷新时钟或补写数据 |
| Scope与门禁 | 已在内存构造并验证待审批Provider计划，不落盘；SDK资源门禁健康，进程隔离入口仍拒绝 |
| 离线测试 | Qwen试用37 + SDK内存HTTP5 + QQ资源门禁3 + SDK资源门禁17 + 进程暂停6，共68项通过，30.736s |

脱敏结果：`outputs/qq-bot/FAST_PROVIDER_PRECHECK-20261025T095553Z.json`。没有保存真实计划或最终批准，凭据内容未读；真实Key可用性仍未知。`--check-config` 和 `--check-monitoring` 均退出0。

### 7.3 用户先复核凭据路径（不读取Key、不联网）

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
@'
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from apps.ai_service.runtime.locations import private_project_location
print('PROCESS_ENV_REF_PRESENT=' + str('DASHSCOPE_API_KEY' in os.environ))
for name, root in [('Prototype', Path.cwd()), ('Management', Path(r'D:\CodexProject\Fishery_Management'))]:
    location = private_project_location(root)
    print(name + '_PATH=' + str(location.env_path))
    print(name + '_FILE_EXISTS=' + str(location.env_path.exists()))
    try:
        ready = location.check(create=False)
        print(name + '_ACL=' + ('PASS' if ready else 'PASS_STORE_NOT_CREATED'))
    except Exception as error:
        print(name + '_ACL=FAIL_' + type(error).__name__)
'@ | & '.\.venv\Scripts\python.exe' -I -X utf8 -B -
```

如果原Key仅在另一个项目Store，不能靠改Bot根目录、复制.env或软链接共享。合法选项是用户自行向既有Prototype安全入口配置，或由用户在**本次终端**隐藏输入自己已有的Key到现有 `PROCESS_ENV` 来源，不落盘。本轮都未执行。

**本次已确认使用Prototype原Store，跳过下面的可选环境变量示例及其清理命令，不需要再次录入Key。** 先只做上方只读权限复核，再按7.4～7.5操作。

后者只在用户自行选择、且手头已有Key时使用；不是从Management文件读取，也不要求新增/重置Key。不要将密钥贴到聊天或命令参数中：

```powershell
# 可选：仅用户自己输入；已有进程变量时不覆盖。
$fastTemporaryKey = $false
if (-not (Test-Path Env:DASHSCOPE_API_KEY)) {
    $fastKeyInput = Read-Host '现有 DashScope Key（隐藏输入，仅本次终端）' -AsSecureString
    $fastKeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($fastKeyInput)
    try { $env:DASHSCOPE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($fastKeyPointer) }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($fastKeyPointer)
        $fastKeyInput.Dispose()
    }
    $fastTemporaryKey = $true
}
```

它不修改私有Store的ACL/规则，Key只在本次PowerShell及其子进程环境中。实验结束或取消后，仅清理本段新建的变量：`if ($fastTemporaryKey) { Remove-Item Env:DASHSCOPE_API_KEY; $fastTemporaryKey = $false }`。如果不选择已有进程环境、也无法确认Prototype私有Store的来源/权限，应停在审批前。

### 7.4 生成计划、人工审批与复核（用户亲自执行；不联网）

整段执行，失败会退出脚本块，返回对象保持为空；不要在错误后继续执行真正联网命令。独立AI配置含本地OpenID，以下只在本机读取，不在聊天里展示其值。

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
$fastTrial = $null
$fastTrial = & {
    $root = 'D:\CodexProject\Fishery_AI_Prototype'
    $py = (Get-Item -LiteralPath (Join-Path $root '.venv\Scripts\python.exe') -ErrorAction Stop).FullName
    $ai = Join-Path $root 'outputs\qq-bot\ai.qwen-fast.provider.json'
    $config = Get-Content -LiteralPath $ai -Raw | ConvertFrom-Json -ErrorAction Stop
    if (@($config.grants).Count -ne 1 -or @($config.grants[0].members).Count -ne 1) { throw '绑定数量已变化，停止。' }
    $grant = $config.grants[0]
    $directory = Join-Path $root 'outputs\qq-bot\trials'
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $id = [guid]::NewGuid().ToString('N')
    $plan = Join-Path $directory ($id + '.provider.plan.json')
    $approval = Join-Path $directory ($id + '.provider.approval.json')
    $result = Join-Path $directory ($id + '.provider.result.json')
    $planText = & $py -X utf8 -B -m apps.qq_bot.trial --prepare --phase provider --access-file (Join-Path $root 'outputs\qq-bot\access.json') --monitoring-config (Join-Path $root 'outputs\qq-bot\monitoring.bot2c.json') --ai-config $ai --policy-directory (Join-Path $root 'outputs\tool-policies') --group-id $grant.group_id --member-id $grant.members[0] --max-cost-cny '2.00' --valid-minutes 10 --output $plan --confirm-instance-read
    if ($LASTEXITCODE -ne 0 -or -not $planText) { throw '计划失败，停止。' }
    $planStatus = $planText | ConvertFrom-Json -ErrorAction Stop
    if ($planStatus.code -ne 'QWEN_TRIAL_PLAN_READY') { throw '计划状态不正确，停止。' }
    Get-Content -LiteralPath $plan | Out-Host
    $approvalText = & $py -X utf8 -B -m apps.qq_bot.trial --approve --plan $plan --output $approval --confirm-instance-read
    if ($LASTEXITCODE -ne 0 -or -not $approvalText) { throw '审批未通过，停止。' }
    $approved = $approvalText | ConvertFrom-Json -ErrorAction Stop
    if ($approved.status -ne 'local_experimental' -or -not $approved.approval_sha256) { throw '无有效批准，停止。' }
    $checkText = & $py -X utf8 -B -m apps.qq_bot.trial --check --approval $approval --approval-sha256 $approved.approval_sha256 --confirm-instance-read
    if ($LASTEXITCODE -ne 0 -or -not $checkText) { throw '复核失败，停止。' }
    $checked = $checkText | ConvertFrom-Json -ErrorAction Stop
    if ($checked.code -ne 'QWEN_TRIAL_APPROVAL_VALID_NETWORK_NOT_STARTED') { throw '复核状态异常，停止。' }
    [pscustomobject]@{ Python=$py; Plan=$plan; Approval=$approval; ApprovalHash=$approved.approval_sha256; Result=$result }
}
$fastTrial | Format-List
```

`--approve`会要求在真实终端输入本次计划的 `APPROVE ...`。批准有效期从计划生成起10分钟，过期后须重新生成并审批，不能改时间延期。它尚不测试Key，不等于付费调用成功。

### 7.5 另行明确批准真实Provider后，单独执行一次

**以下命令本轮未执行。** 仅限已确认凭据来源、批准本次2元上限/一个Turn/最多两次模型请求/每次512Token/90秒/SIMULATOR披露及线程风险之后，另行粘贴运行。失败不重试，不连接QQ：

```powershell
& {
    if ($null -eq $fastTrial -or -not $fastTrial.ApprovalHash) { throw '没有本次有效批准，停止。' }
    $checkText = & $fastTrial.Python -X utf8 -B -m apps.qq_bot.trial --check --approval $fastTrial.Approval --approval-sha256 $fastTrial.ApprovalHash --confirm-instance-read
    if ($LASTEXITCODE -ne 0 -or -not $checkText) { throw '批准过期/变化/已使用，停止。' }
    $checked = $checkText | ConvertFrom-Json -ErrorAction Stop
    if ($checked.code -ne 'QWEN_TRIAL_APPROVAL_VALID_NETWORK_NOT_STARTED') { throw '复核异常，停止。' }
    & $fastTrial.Python -X utf8 -B -m apps.qq_bot.trial --run-provider --approval $fastTrial.Approval --approval-sha256 $fastTrial.ApprovalHash --output $fastTrial.Result --confirm-instance-read --confirm-provider-network
    if ($LASTEXITCODE -ne 0) { throw '实验失败或资源未知；保留报告和used标记，停止，不重试。' }
}
```

本次旧观测应继续显示partial/stale/offline；成功只证明链路和可靠事实投影通过，不证明水质实时正常。模型自由文本仍不直接展示。SDK资源隔离则立即停止，不清空门禁、不恢复进程隔离草稿。本次用户操作之后再决定QQ阶段，本轮不提供或执行QQ联网命令。

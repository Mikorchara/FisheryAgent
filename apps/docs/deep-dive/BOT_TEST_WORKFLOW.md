# QQ / Qwen 日常验收入口

2026-10-25，适用于 **Fishery_AI_Prototype**，使用 PowerShell 7。三个入口只串联原有 CLI，不实现审批、费用、权限或 Agent 逻辑。当前阶段与兼容性见 [阶段总结](BOT_STAGE_SUMMARY.md)、[Web 审计](research/BOT_WEB_IMPACT_AUDIT.md)。

2026-10-26 [QQ中断与报告修复](BOT3D1_RESULT_REPORTING.md)：用户已人工收到BOT-3D-1 A/B/C，旧版中断路径可能缺最终报告。本补丁增加交付检查点、统一停止报告及真实文件核对；FAST指纹再次变化，旧记录作为历史证据保留，不能授权新运行。无需为补历史报告重新调用模型或QQ。

2026-10-26 [BOT-3D-1](BOT3D1_BOUNDED_EXPLANATION.md)：新增受限解释合同和新Scope，旧Provider报告、计划和批准不能复用；须重新通过下面的Provider→QQ分阶段人工审批。本轮脚本只增加展示同意提示、解释状态白名单和“模型成功但解释未过”的明确结果，没有代替原安全检查。

## 1. 常用操作

先在普通 PowerShell 7 中执行：

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
```

| 目的 | 不联网检查（默认模式，`-DryRun` 等同 `-Check`） | 人工决定联网后 |
|---|---|---|
| 固定指令、当前/历史水质、异常 | `.\scripts\dev\Test-QQBot.ps1 -Check` | `.\scripts\dev\Test-QQBot.ps1 -Run` |
| 本机 Qwen + 当前水质工具 | `.\scripts\dev\Test-QwenProvider.ps1 -Check` | `.\scripts\dev\Test-QwenProvider.ps1 -Run` |
| QQ + Qwen 单轮 | 下面命令指定成功 Provider 回执 | 检查命令的 `-Check` 换为 `-Run` |

QQ AI 必须**明确指定已有成功 Provider 原始 result.json**，不能传 summary.json，也不会自动挑选最近文件：

```powershell
.\scripts\dev\Test-QQAI.ps1 -Check -ProviderReport 'D:\CodexProject\Fishery_AI_Prototype\outputs\qq-bot\test-runs\替换为成功Provider目录\result.json'
```

这条含待替换目录的命令是格式示例。上一步会打印实际报告目录；其中 `result.json` 才是原 CLI 生成的前置证据。脚本不制造或修改成功回执，`prerequisite_valid` 校验真实来源标记、新Scope、绑定摘要、两次请求、SDK CLOSED、原始正文未显示，且 `explanation_validated=true`、`explanation_code=EXPLANATION_CONTRACT_VALID`、解释合同匹配。配置或代码变化导致前置失效时，停止并重新检查，不能修改 JSON 绕过。

`-Run` 先生成新计划，再显示具体 Preset/模型、实例/设备、群成员摘要、有效期、费用上限与保守预留。输入 `QWEN` 仅表示同意进入 Provider 审批；QQ 阶段还须单独输入 `QQ`。随后原 Python CLI 要求操作者亲自输入 `APPROVE <本次挑战>`，脚本不代填。最后原 CLI 复核批准并执行一次。请在有交互终端的普通 PowerShell 中运行，不用重定向 stdin 或 `-NonInteractive` 执行 `-Run`。

Provider 脚本不连接 QQ。固定命令脚本不调用 LLM；在授权群中 @机器人后发送 `help`、`/当前水质`、`/历史水质 10`、`/当前异常`。QQ AI 使用 `/问AI 当前水质如何？`，同一批准最多一个 AI Turn。

## 2. 默认路径与参数

| 参数 | 默认 / 作用 |
|---|---|
| `-AccessFile` | `outputs/qq-bot/access.json`；群/成员/设备授权，无密钥 |
| `-MonitoringConfig` | `outputs/qq-bot/monitoring.bot2c.json`；明确实例，绝不自动改用正式库 |
| `-AIConfig` | `outputs/qq-bot/ai.qwen-fast.provider.json`；两个 AI 脚本使用，独立 AI 授权 |
| `-PolicyDirectory` | `outputs/tool-policies`；交给现有 Policy 求交，不改写 |
| `-GroupId` / `-MemberId` | AI 配置仅有一个候选组合时自动选；多个必须明确指定。CLI 再检查 access/AI/设备交集 |
| `-MaxCostCny` | `2.00`；原 CLI 根据固定请求上限及价格依据检查保守预留，非新定价逻辑 |
| `-ValidMinutes` | 10，范围 1–30；超过期限拒绝新请求 |
| `-RunSeconds` | QQ 会话默认 120，范围 1–600；Provider Turn 仍受原 90s 期限约束 |
| `-ReportRoot` | `outputs/qq-bot/test-runs`；只接受本项目 outputs 子目录，拒绝重解析点/网络盘 |

默认检查会读取明确指定实例的只读业务接口，以核对 Schema/设备/来源；**不读取密钥、不联网**。AI 检查会写一份 pending 计划和脱敏摘要，**不创建批准或消费标记**；它不是“完全不写文件”模式。不想访问某个实例时不要使用其配置，用隔离实例参数。

路径缺失、歧义、Scope/Policy/设备不符、前置报告不符、审批拒绝或过期时立即停止。不会初始化空库、修改 AI 开关/Policy、复制凭据或自动刷新过期观测；stale/offline 应真实呈现。

## 3. 记录、安全与失败处理

每次使用唯一目录，文件拒绝覆盖；不删除旧计划、批准、回执或 used 标记：

```text
outputs/qq-bot/test-runs/test-UTC时间-随机ID/
  summary.json   # 固定字段的状态摘要；没有完整 OpenID、模型正文、Key/Token
  plan.json      # AI 检查生成；含本机批准所需标识，不当普通日志分享
  approval.json  # 仅人工审批成功后生成
  result.delivery.json # QQ单轮交付后提前保存，只有Receipt/安全状态，无正文；不是最终报告
  result.json    # 原 CLI 回执，不是 summary 的复制品
```

原 CLI 仍在 AI 配置所在目录保存单次消费标记与受限 trace。失败后不得删除 used 标记重试；送达未知不能重发、补推理或复用批准。脚本不会接收外部 URL、密钥或取消门禁参数，也不重新定价、不修改候选资格。

`PROVIDER_VERIFIED` 表示Provider及解释检查通过；`PROVIDER_VERIFIED_FACTS_ONLY_QQ_NOT_READY` 表示模型/工具完成但解释合同未过，只能退回事实，此报告不能用于QQ阶段，也不自动补调模型。`QQ_API_ACCEPTED_CHECK_CLIENT` 只表示API已接受，仍要检查 `explanation_validated` 和客户端；`client_display_confirmed` 始终false，不自动伪造人工验收。固定命令会话结束不代表所有指令均已验收。

正常自动到期会保存最终报告；`QWEN_QQ_TRIAL_STOPPED`只表示会话结束，需另外看delivery。封装现在要求文件实际存在、与stdout/Scope/phase/完成标志一致，才记录`report_saved=true`；QQ_STOPPED或一条API接受进度日志不能替代报告。

收到回复后再Ctrl+C，可出现`QQ_API_ACCEPTED_SESSION_CANCELLED`：此前API接受与会话取消同时为真。若PowerShell直接中断native管道，摘要为`INTERRUPTED_REPORT_UNCONFIRMED`，找到检查点时为`INTERRUPTED_CHECKPOINT_SAVED_CHECK_CLIENT`；不会伪造result。PowerShell中断有时跳过显式exit，甚至host退出码0，必须核对摘要与文件。

`QQ_DELIVERY_UNKNOWN_NO_RETRY`仍不得重发。`REPORT_WRITE_FAILED/TRIAL_RESULT_WRITE_FAILED`明确表示最终保存失败；检查点失败单独为`TRIAL_DELIVERY_CHECKPOINT_FAILED`，不会抹去真实API接受状态。强制关窗/杀进程/掉电仍不能保证最终报告或检查点，优先等待自动结束；历史已有文件永不覆盖。

回复的A部分为同轮可信事实，B部分是模型选择要点后由程序校验/渲染的中文，C部分为来源与时效限制。`model_text_displayed=false` 指原始模型JSON/正文不显示，不等于B部分为空。超过整体长度时完整降级或拒绝，不裁掉关键说明；解释失效、发送失败或送达未知均不自动再推理/再发送。

SDK 清理失败继续触发粘性隔离。停止当前实验，保留记录，正常关闭相关进程后调查；脚本不清空门禁或杀死未知进程。仍使用现有线程式 SDK 桥接，没有新增独立进程超时/强杀框架；不合作 I/O 的硬退出风险仍在，不能声称取消一定终止远端计费。Ctrl+C、期限及关闭由原 CLI/RequestHandle 负责，脚本不承诺额外强制回收能力。

输出按行解析，有 64KiB 单行 / 1MiB 总量 / 2048 状态条目上限；非结构化错误不原样回显。若超限或没有稳定状态，停止、不自动执行下一阶段。请仅分享 `summary.json` 中必要的非敏感字段，不上传整个实验目录。

## 4. 实现范围

入口为 `scripts/dev/Test-QQBot.ps1`、`Test-QwenProvider.ps1`、`Test-QQAI.ps1`，公共薄封装在 `qq_bot_test_common.ps1`。测试在 `apps/qq_bot/tests/test_test_workflow.py`；私有函数仅在独立测试进程内替换，不暴露绕过审批的公开开关。

原 `apps.qq_bot` / `apps.qq_bot.trial` 仍可单独使用。脚本不会自动修改Scope或创建final approval；本轮业务展示代码更新已改变Scope，需重新审批。脚本默认配置指向用户此前明确选择的BOT-2C实例，自动化测试只创建自己拥有的合成实例，不读取这些现有文件。

## 验证记录

2026-10-26 QQ报告修复：新增9项CLI/持久化与5项PowerShell测试，Bot308项、完整901 Python / 116 Node全部通过；自动到期、处理中断、失败停止、未知交付、文件缺失/不匹配、保存失败及防覆盖均离线验证。[根因与记录](BOT3D1_RESULT_REPORTING.md)。强制关窗/真实Ctrl+C的所有主机行为不在本轮联网验证范围。

2026-10-26 BOT-3D-1：脚本14项通过（增加Provider解释未过时禁止转QQ的状态测试）；QQ专项294项、完整887 Python / 116 Node通过。新解释合同与完整回归见[实施报告](BOT3D1_BOUNDED_EXPLANATION.md)，以下保留各历史阶段数字。

2026-10-26 [BOT-CLEANUP-1](BOT_CLEANUP1_SDK_DRAFT_REMOVAL.md) 仅删除未使用的四份进程隔离草稿和专用测试文件（6项）；清理后 **868 Python / 116 Node 全部通过**，与此前874的差额仅为6项暂停测试。两个 Scope 与 BOT-REGRESSION-1 相同，不影响原测试入口或 SDK 资源门禁。下方更早的数量为历史记录。

后续 [BOT-REGRESSION-1 修复报告](BOT_REGRESSION1_FAST_STABILITY.md) 已完成 FAST 短窗口/夹具修复与同次 Scope 构建去重；五项三轮、Bot 275 项、Web 相关 78 项通过，完整基线为 **874 Python / 116 Node 全部通过**。FAST 实现指纹已改变，旧计划/批准和 Provider 前置回执必须重新生成/审批，不能修改 JSON 复用。下面是首次脚本审计的历史记录。

本轮所有执行均离线、合成数据库、Fake Provider / Fake QQ；没有重新进行真实群或模型验收。

| 命令 / 检查 | 结果 |
|---|---|
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest apps.qq_bot.tests.test_test_workflow -q` | 新增 13 项全部通过，46.361s |
| `.\.venv\Scripts\python.exe -X utf8 -B scripts/dev/run_tests.py management`（TEMP/TMP 指向本仓 outputs/test-tmp） | 866 Python，861 通过、4 错误 / 1 失败，565.331s；11 个 Node 文件、116 项全部通过 |
| 原 FAST 失败 5 项以完整 unittest 名称单独重跑 | 43.423s，仍为 4 错误 / 1 失败；列表与诊断见 [审计](research/BOT_WEB_IMPACT_AUDIT.md#2-兼容性证据与限度) |
| 三个脚本及公共 helper 的 PowerShell Parser | 通过（包含在新 13 项） |
| Windows 伪终端、同一 native 包装的 stdin 探针 | `SYNTHETIC_STDIN_TTY`，捕获输出未剥夺交互输入；没有审批真实计划 |
| Fake workflow | 默认不审批/不联网；人工取消、审批/复核失败、运行超时、缺配置、错误前置回执、未知交付均立即停止；无重试 |
| SQLite / 日志 | 新合成库查询前后文件 SHA-256 一致；输出及 summary 不含完整标识和 Key/模型正文哨兵 |
| Scope / 暂停草稿导入 | 已有绑定源码改动数 0；生产导入草稿数 0；草稿仍全部保留、禁用 |
| 文档 / Git | 129 个本地链接目标存在（不含外网或全部锚点验证）；`git diff --check` 通过 |

当时完整回归的失败不是新增 wrapper 测试失败，不能隐去或写成“全通过”。当时得到额外观察等待后 11.969s 正常交付的隔离证据，因此安排后续 BOT-REGRESSION-1；没有在原审计中修改生产预算、安全检查或原有测试。既有用户真实验收、首次审计失败和后续修复结果分别记录。

本轮没有验证：真实 PowerShell 人工审批到联网执行的整套体验、真实 Provider/QQ、真实 Web 断网/Streaming 长稳态、现有业务实例以及 Management 兼容性。这些均按限制留给后续明确授权与人工验收。

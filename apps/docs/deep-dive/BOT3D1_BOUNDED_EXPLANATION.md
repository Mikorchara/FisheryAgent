# BOT-3D-1：受限 AI 解释与可信展示

日期：2026-10-26。仅 Fishery_AI_Prototype；起点 `main / 2470cbd`、工作树为空。本轮没有连接真实 Qwen / QQ、读取真实凭据或现有业务实例，没有修改 Management，也没有提交。

## 1. 本轮实现与边界

QQ 回复在同轮可信事实之外增加可验证的中文解释。**Qwen 选择解释要点和顺序，程序根据已验证的引用生成固定中文句子**，不直接展示模型原文。这是一版有限模板解释，不是任意自然语言回答，也不是通用逐句事实核验器。

```text
授权的 /问AI → 原 Coordinator / Scheduler → 原 AI Service / Agent
  → 模型请求1 → 当前水质 Tool（一次只读 capture）→ 模型请求2
  → 原 Source Gate / Commit Gate / SDK 资源关闭检查
  → 同轮 SourceSummary + 结构化解释计划
  → 引用/质量/时效/规则校验 → 固定中文渲染或退回事实摘要
  → 原 DeliveryOwner 发送前复核 → 原 PassiveReplyOwner 单次提交
```

未增加 Agent、Tool、知识/历史查询、聊天记忆、额外模型审核、重试或自动处置。继续 Normal / SINGLE_ROUND / 空 history / 1 Tool / 1 Round / 最多2个模型请求；每请求512输出 tokens、总90s、QQ消息期限及原费用预算不变。

## 2. 过去为何隔离正文

`channel_presentation.py` 原有数字/来源冲突检查只能发现部分明显错误，不能证明其他句子可信，所以所有模型正文都被拒绝。格式看似正确、数字碰巧相同或文本没有命中正则，都不等于通过来源核验。

本轮保留旧诊断供拒绝原因使用，**没有任何正则未命中后的自由文本放行分支**。只有下面的封闭 JSON 引用合同能产生解释；任何附加自由文本字段都无效。

## 3. 解释合同

独立 Prompt：`QQ_CURRENT_EXPLANATION@1`；输出合同：`qq-water-explanation@1`。例如，本轮真实 Tool 投影命中严重低氧规则时，模型可以返回：

```json
{
  "contract": "qq-water-explanation@1",
  "source": "simulator",
  "context": "window",
  "metrics": ["dissolved_oxygen_mg_l", "ph"],
  "rules": ["OXYGEN_CRITICAL_LOW"],
  "advice": ["review_rules", "verify_observation"]
}
```

示例不含读数；`OXYGEN_CRITICAL_LOW` 必须确为**本次 Tool** 的 HIT，否则拒绝。模型使用原 SDK 的文本响应返回 JSON，不新增供应商 `response_format` 要求或第三次请求。

| 字段 | 服务端校验 |
|---|---|
| 整体 | UTF-8最多2048字节，恰有上述6个字段；拒绝重复字段、NaN/Infinity、Markdown围栏、前后文及额外属性 |
| contract / source | 精确匹配合同和 `simulator`；不是大小写或后缀模糊匹配 |
| context | 只有本次来源为 OK、valid、fresh、online 且全部指标有效有限数值时可为 `window`；其他必须 `limited` |
| metrics | 1–3个唯一指标ID，仅水温/pH/溶解氧，且必须存在于本次来源；不能携带数值、结论或对象 |
| rules | 0–3个唯一code，必须完整对应本轮 `WATER_RISK/HIT` 集合；不能增删规则命中或写入恢复结论 |
| advice | 1–2个固定建议代码；有HIT必须包含 `review_rules`，无HIT不能使用它；`check_reporting` 仅限证据不足，`continue_observation` 仅限有效窗口 |

字段顺序可变化，键名/值/类型必须精确。JSON解码后的重复键也拒绝，包括用Unicode转义伪装同名字段；不依靠字符串替换猜测含义。

建议仅为“核对后续观测 / 复核规则证据 / 检查上报质量与时间 / 观察后续窗口”，均标记**未执行**。没有ACK、删除、增氧机控制或疾病确诊的可输出语义。

## 4. 同轮来源与显示

`SourceSummary.from_result()` 继续只读取实际执行的唯一当前水质 `ToolExecutionStep` 与 Receipt；新增 `rule_hits` 从该payload复制权威规则命中，不重新查库、不复制诊断阈值、不接受模型给出的规则事实。

回复包含三个部分：

1. **A 系统事实**：实例/设备、SIMULATOR、观测/接收/评估时间、质量/新鲜度/连接、留存窗口读数、已有业务规则命中。
2. **B 模型解释**：依据模型选择的有效引用生成句子；明确“留存窗口记录”“业务规则说明”“建议（未执行）”。部分/缺测/离线时先说明不能确认当前整体状态。
3. **C 来源与限制**：合成观测不是真实硬件；实验规则不能替代专业判断；质量及在线判断属于评估时刻，**发送时未重新采样**。

例如B部分可为：

> 以下说明仅对应本次评估窗口，不代表发送时重新测得的水质。溶解氧存在有效的留存窗口记录，触发情况以业务规则为准。业务规则说明使用本轮原规则消息，并明确不是模型独立诊断。建议人工复核规则命中及观测证据，不据此自动处置。

关键边界：有有效读数不等于“正常”；没有HIT也不生成“全部正常”。pH缺失不能声称pH正常；stale/offline不会改写成实时水质；SIMULATOR不能改为真实传感器。

完整回复仍限1600字符，前缀也计入。解释超长或不合格时退回完整事实与来源说明；如果连完整事实降级文本也放不下，则 `AI_REPLY_TOO_LONG`、不提交消息。没有裁掉安全说明后宣称完整的路径。

## 5. 失败、资源与交付

Backend Final、Source/Commit、权限或SDK关闭失败时，不得发送成功答复。结构化输出失效只影响解释资格，不重跑模型、不改读数，也不补读另一份数据伪装本轮来源。

| 报告字段 | 含义 |
|---|---|
| model_text_displayed=false | 原始模型JSON/自由文本没有直接显示；不表示B部分一定为空 |
| explanation_contract / explanation_code | 当前解释合同和稳定的校验结果；不记录模型原文 |
| explanation_validated | Provider候选回复已通过合同和整体长度检查；或QQ任务实际准备的解释资格 |
| explanation_in_payload | 准备提交的QQ完整文本中包含受限解释；不代表QQ已接受或用户已看到 |
| api_accepted | QQ API接受；发送失败/未知时仍不能当作已显示 |
| client_display_confirmed=false | 留给人工观察，程序不伪造客户端验收 |

HTTP失败/结果未知保持单次提交、不重发、不重新推理。权限、期限、绑定、Scope仍在原时间边界复核。SDK租约、RequestHandle、清理失败粘性隔离及取消逻辑没有变更；仍存在不合作线程不能强制退出、远端计算/计费未知的风险。

## 6. Scope 与审批

本轮只维护新的 **v3 candidate**，`qualification_id / validated_at / trial_approval_id` 仍为空，不冒充released或已完成真实资格。

- 基础合同：`qq-monitoring-normal-trial@3`。
- 独立试用合同：`qq-qwen-current-explanation-trial@1`。
- 展示合同：`qq-current-facts-bounded-explanation@1`。
- Prompt、输出合同、展示实现、原SDK资源合同及FAST相关实现均纳入现有指纹。
- 本轮candidate Scope：`2d89b74fe451f793c09e21fff90dc624d9fd2ee34a02c393284f2e61066350be`。
- 本轮FAST Scope：`9e37f1e7580d3016bf11351c0c64eb478b4784e11ff11fc5409c8ca6fa116b28`。

旧Provider回执、计划和批准不能授权新代码；本轮没有读取或改写旧文件。普通 `apps.qq_bot` 的 `/问AI` 继续 `AI_DISABLED`，必须走现有单独试用批准流程。

QQ阶段除原有两次请求、相同Scope/绑定、真实报告及SDK CLOSED条件，还要求**新Provider报告**具有 `explanation_validated=true` 和 `EXPLANATION_CONTRACT_VALID`。Provider成功但解释不合格时，脚本显示 `PROVIDER_VERIFIED_FACTS_ONLY_QQ_NOT_READY`，该报告不能作为QQ前置；不会自动再试。

## 7. 主要修改位置

| 文件 | 职责变化 |
|---|---|
| [channel_presentation.py](../../ai_service/channel_presentation.py) | QQ Prompt、封闭合同、引用校验、固定中文和全长降级 |
| [channel.py](../../ai_service/channel.py) | 同轮规则摘要与更保守的可用证据判断；原始模型文本仍未核验 |
| [runtime/assistant.py](../../ai_service/runtime/assistant.py)、[service.py](../../ai_service/service.py) | 仅内部渠道装配注入单轮Prompt；Web默认Prompt不变，不复制/改变工具循环 |
| [channel_scope.py](../../ai_service/channel_scope.py)、[channel_trial.py](../../ai_service/channel_trial.py)、[候选记录](../../ai_service/resources/qq_monitoring_trial.json) | 独立候选/试用合同与实现指纹 |
| [ai_delivery.py](../../qq_bot/ai_delivery.py)、[ai_scheduler.py](../../qq_bot/ai_scheduler.py) | 计入前缀长度、状态摘要；复用原单次Delivery Owner |
| [trial.py](../../qq_bot/trial.py)、[trial_configuration.py](../../qq_bot/trial_configuration.py) | 安全结果字段、独立展示同意、新Provider前置要求 |
| [qq_bot_test_common.ps1](../../../scripts/dev/qq_bot_test_common.ps1) | 中文审批提示、状态白名单和事实成功/解释未过的区分 |
| [test_explanation.py](../../qq_bot/tests/test_explanation.py)及原Bot测试 | 封闭合同、真实SDK类+内存HTTP、Fake QQ、失败与旧功能回归 |

未修改Monitoring、Knowledge、Simulator、Web生产模块、Tool Definition、SDK Adapter/资源门禁、数据库Schema或旧 `src/fishery_ai`。

## 8. 离线验证

所有测试使用虚构数据、隔离SQLite、Fake Provider、Fake QQ或SDK内存HTTP；未打开用户已有实例。

| 验证 | 结果 |
|---|---|
| 新解释合同 + PowerShell薄入口 | 25项通过（11解释 / 14脚本） |
| QQ Bot全部专项 | 294项通过，84.708s；包含FAST 52项及原权限/取消/资源/交付测试 |
| Web AI / Normal / Streaming / Tool / 业务Runtime定向回归 | 90项通过，13.549s |
| 完整management Python / Node | 887 Python全部通过（193.002s）；11个Node文件 / 116项全部通过（1.921s），退出码0 |
| 代码/指纹/链接 | 14个改动Python文件语法通过；候选预检仍LIVE_BLOCKED；164处本地链接目标存在，无新增断链；`git diff --check`通过 |

新增19个测试方法：11个合同、7个FAST集成、1个脚本状态；原868项Python全部保留。覆盖正常要点、引用原规则、编造数值、stale/offline、pH缺测、伪造硬件、注入、重复键/大小写/字段序/错误类型、超长、无Tool、Commit失败、SDK取消与清理失败、发送失败/未知及不重复执行。FAST集成验证实际Mock请求为2次、capture一次、回复最多一次；已结束任务线程随原测试清理。

测试只能证明本地边界与合约行为，不能证明真实Qwen一定遵守JSON合同、512 tokens内稳定完成、真实回答质量或QQ客户端可见。新入口未进行真实联网验收。

执行命令为 `.\.venv\Scripts\python.exe -X utf8 -B scripts/dev/run_tests.py management`，TEMP/TMP限定在本仓`outputs/test-tmp`。完整日志、专项日志和源码/默认Prompt对比保留于 `outputs/test-tmp/bot3d1-20261025T163740Z-b024b184/`，属于Git忽略的本轮非敏感测试记录。原预期拒绝路径会输出CLI错误示例，应以最终887项OK和退出码判断，不能将该类夹具输出当作真实实例故障。

133份受保护源码的前后摘要仅`ai_service/runtime/assistant.py`因内部Prompt注入点变化；原Web单轮/多轮Prompt字面量摘要相同。SDK进程隔离四份草稿仍不存在。最终仅Prototype源码、测试和上述文档有未提交改动；HEAD保持`2470cbd`，未执行commit/push。

## 9. 后续人工验收（本轮不执行）

先由用户明确批准现有配置指定的实例/设备、Qwen模型、群/成员、数据披露、费用、期限及线程风险，不能借用历史批准。普通PowerShell 7在Prototype根依次执行：

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
.\scripts\dev\Test-QwenProvider.ps1 -Check
```

`-Check` 不联网、不读密钥，但会只读打开**指定**实例并生成新pending计划；仍须先批准访问该实例。本轮仅自动检查不访问实例的 `--check-ai-readiness`。

确认模型、实例、费用、时限及Prompt/Scope后，由用户决定：

```powershell
.\scripts\dev\Test-QwenProvider.ps1 -Run
```

亲自完成QWEN与原APPROVE挑战；一次批准仅一轮。如果报告不是解释通过、SDK CLOSED且两次请求成功，停止，不循环执行以碰运气。格式不兼容时保留脱敏错误码，再评估Prompt/合同；任何代码变化均需重新生成Scope与批准。

取得**本轮**成功原始Provider `result.json`绝对路径后，独立审批QQ阶段：

```powershell
$providerReport = Read-Host '本轮解释合同通过的 Provider result.json 绝对路径'
.\scripts\dev\Test-QQAI.ps1 -Check -ProviderReport $providerReport
.\scripts\dev\Test-QQAI.ps1 -Run -ProviderReport $providerReport
```

三个脚本仍使用原显式配置/Policy/费用参数，详见[日常验收入口](BOT_TEST_WORKFLOW.md)。这里的`-Run`仅供用户获批后执行，不是本轮联网授权。

在批准测试群@机器人 `/问AI 当前水质如何？`：检查A/B/C完整、读数/时间与本轮来源一致、模拟来源醒目、建议未执行；新鲜度只代表评估时刻。若指定隔离数据已过期，应看到证据不足和stale/offline，不改时间冒充在线。QQ API接受后还须人工确认客户端显示；未知不重发。无效解释退回事实时保留安全说明，不新增模型请求。

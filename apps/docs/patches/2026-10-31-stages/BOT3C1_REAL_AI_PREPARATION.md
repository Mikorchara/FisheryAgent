> 历史归档（2026-10-31）：本阶段已被后续实现替代。保留设计与验收证据；当前操作见 [启动指南](../../BUILD_RUN.md) 和 [文档入口](../../README.md)。

# BOT-3C-1：真实 AI 联调前置准备

后续状态：[BOT-3C-FAST](BOT3C_FAST_QWEN_TRIAL.md)已新增独立限时审批和Provider/QQ试用入口的离线装配；本页保留3C-1阶段记录。普通QQ CLI及旧v2 candidate仍不能启用真实AI，实际联网须另批。

核验日期：2026-10-25。仅 Prototype；[B-1 服务边界](BOT3B1_QQ_AI_BOUNDARY.md)、[B-2 调度交付](BOT3B2_QQ_AI_SCHEDULING.md)。本轮没有读取真实凭据、打开已有实例或连接 QQ / Provider / NPU。

后续维护见 [BOT-3C-2A](../../deep-dive/BOT3C2A_SDK_RESOURCE_GATE.md)：现已增加资源失败门禁、默认2s清理等待和粘性隔离，候选Scope更新v2；下文5s join描述为C-1时的历史状态。不合作线程仍不能硬终止，真实入口依然关闭。

## 1. 结论与范围

已完成独立 Monitoring-only 真实试用 Scope 的**候选准备**、统一回复所有权的离线装配、真实 SDK 类的内存 HTTP 取消验证，以及事实/模型解释分区。**当前仍不能直接开展真实 QQ AI 联调**：Scope 未获本轮真实试用批准，真实渠道 Service/Delivery 仍未装配，SDK 不合作清理也尚不满足既定资源要求。

新增 `--check-ai-readiness` 只读检查维护者候选文件，成功表示“候选与当前代码一致且仍被禁用”，不表示可发模型请求。真实 CLI `/问AI` 仍 AI_DISABLED；`--enable-ai` 不存在。不能通过编辑 `can_send/can_deliver` 或配置示例启用。

## 2. Scope、资格与 Policy

### 2.1 现有机制检查

- `ai_service/runtime/release_contracts.py:release_scope` 对 Provider/Preset/协议、Prompt、History投影及实际可执行 Tool Definition 做指纹。`AssistantMultiRoundRelease` 区分 candidate / local_experimental / released；released 才可携带真实资格ID和验证时间。
- `ai_service/execution.py:ManagementRelease / management_scope` 绑定 Knowledge source/version/retrieval；其现有资格和三工具试用范围不适用于当前 Monitoring-only QQ 渠道。
- B-1 `channel.py:candidate_decision` 是 OFFLINE_FAKE_ONLY，AI Service 仅接受精确 OfflineChannelProvider。其内部执行决定服务于 Fake 测试，不能授权真实SDK。
- 管理 Policy、Registry、独立 QQ AI 授权、群/成员权限、设备绑定与有效 Scope 仍要求交集；预检不会读取真实 Policy、授权配置或实例，不能把模板一致性视为这些条件已经通过。

### 2.2 本轮候选

`ai_service/channel_scope.py` 生成独立 `qq-monitoring-normal-trial@1` 合同，维护文件为 `ai_service/resources/qq_monitoring_trial.json`。只允许 current water Tool、SINGLE_ROUND 1/1/2、Normal、thinking off、空 History、零重试；Knowledge=null，来源仅 simulator。**真实模型执行不等于已接真实传感器。**

Scope 包括实际单轮 Prompt、Definition hash、水质投影、固定 Provider身份和协议、预算/超时、Backend Adapter文件hash、安装SDK版本、独立展示合同；Provider/Tool/Prompt/SDK/预算/展示变更都需重新核查。一次运行的实际实例、设备、群、成员、Policy revision、generation 与截止时间另由不可来自聊天正文的服务器授权冻结；不将易变运行身份伪装为可跨运行沿用的资格。

当前仓库固定配置：Preset `dashscope-qwen38-flash-r1`，service `dashscope`，adapter `openai_chat`，model `qwen3.8-flash`，HTTPS base `https://dashscope.aliyuncs.com/compatible-mode/v1`，credential_ref `DASHSCOPE_API_KEY`。这只证明**代码中的配置**，本轮未验证账号可用模型、服务端版本或价格。

候选文件是 candidate，qualification_id / validated_at / trial_approval_id 均null。`check_candidate` 严格匹配完整规范化合同；改成 local_experimental、写入旧三工具资格、加入 can_send 或篡改类型均拒绝，不会自动修正指纹。

### 2.3 BOT-3C-2 合法试用流程（待授权/实施）

1. 先完成下面的SDK资源门禁和真实类型化装配；这会改变 Adapter Scope hash，须重新生成并人工审核候选，不能沿用本轮旧hash。
2. 维护者明确批准该**具体** Scope 为有限 local_experimental。单独保存试用批准ID/范围，不伪造“真实 qualification 已通过”；qualification_id / validated_at 仍不得冒填。
3. 单次运行还需有期限的 RunConsent，明确阶段、实例/设备、群/成员、模型、费用、请求数和数据披露。资格/配置、Policy与运行同意缺一即拒绝，逐次模型I/O/Tool/发送前复核，不能仅在启动时判断一次。
4. Provider 单轮人工记录成功/失败、Usage、取消、实际成本与审核结果；QQ单轮另行批准和记录。真实证据只覆盖当前合同，不能回填成Web三工具或其他来源资格。

本轮只有候选检查器，没有加载真实批准并返回允许执行的分支；没有新增真实执行开关。示例 `qq_bot/examples/real-trial.request.example.json` 是**申请单，不是运行配置**，程序不会加载它。

## 3. Gateway、调度与统一交付

本轮离线装配使用真正的 `QQGateway._dispatch / _work / run` 接收及收尾路径，但通过显式 `offline_router` 注入：

```text
Fake Gateway帧 → normalize → 原有有界接收worker → OfflineQQAIRouter
  → 共用原QQAdapter准入：App/群/成员、时效、去重、限频
    ├ 固定指令 → 原ReadOnlyQueries → 共用PassiveReplyOwner → Mock QQ HTTP
    └ /问AI → 原QQAICoordinator → B-2有界Scheduler → 原AI Service/Agent
                → 同轮来源+成功Final/Source/Commit → DeliveryOwner
                → 同一PassiveReplyOwner → Mock QQ HTTP
```

`ai_delivery.py:PassiveReplyOwner` 统一原消息 claim、完整长度检查、msg_id/msg_seq=1 和接受/失败/未知。固定、AI成功、BUSY/会话忙/禁用提示都使用它；重放或跨路由改变同一msg_id不再执行模型。未知/失败不重试、不补偿推理；API接受不代表客户端显示。

固定查询不等待AI结果；AI仍为1执行/2等待、全流程最多3任务、每会话单飞、排队10s/总90s并保留原消息15s余量。心跳留Gateway pump，未引入线程随消息增长。交付摘要完整时最长1600字符，超过限制整体拒绝，不截去事实限制。

断线立即取消AI，恢复网络不重放旧AI；移除群撤销其权限并保守取消旧generation任务；停机关闭scheduler。发送前检查全部权限及期限；已经提交到平台的消息不能保证撤回，无法确认时记UNKNOWN。

这里的撤权指Gateway移群事件或服务器显式reconfigure；启动冻结的access/AI配置文件手工修改，不等于正在运行的进程已重载。真实阶段须提供受控重载，或先停Bot再修改/重启，不能假定编辑JSON会立即撤销旧任务。

注入只接受精确 `OfflineQQAIRouter + OfflineGatewayAPI`，拒绝真实QQAPI和默认网络connector；HTTP交付仍只接受精确OfflineQQGateway。实际 CLI 不提供这个注入参数，默认Gateway路径保留原固定命令行为。**这不是生产真实AI已经装配完成**；未来真实路由必须有独立Trial/RunConsent Gate，不能删除Fake类型限制或换一个布尔值就启用。

## 4. Provider SDK：已证实与阻塞

核验安装版本 OpenAI SDK **2.54.0**、httpx **0.28.1**；测试运行于 `.venv` Python 3.12.14。

`ai_backend/openai_compatible_adapter.py:_bridge` 在线程内运行 asyncio Runner / Task，RequestHandle.bind 挂接 `loop.call_soon_threadsafe(task.cancel)`；finally 关闭SDK stream/client，consumer中止时abort_io；SDK自身max_retries=0，当前Qwen Preset也为零重试，使用剩余Turn期限限制每次请求。

本轮使用真正 AsyncOpenAI 类和当前Qwen Runtime，但HTTP仅 httpx.MockTransport、密钥仅虚构字面值。实测覆盖：等待响应头、等待响应体、总期限、HTTP 503零重试、两次请求正常编码；取消传播至Task，客户端/流关闭、SDK线程退出，remote_compute_stopped仍unknown。wire body核对model/max_tokens=512/enable_thinking=false/非Streaming，不把Mock响应当真实Provider资格。

**真实执行阻塞项：** 同一 `_bridge` 仍创建 daemon `fishery-sdk-request`，finally join最多5s；若还存活只把handle.io_closed设false，不能证明已停止。B-2的三个调度线程虽是非daemon，这个底层线程仍需单独处理。本轮未重构通用Backend，不能声称SDK所有失败路径都符合B-2要求。

BOT-3C-2 先做最小独立维护：不合作I/O/SDK close超时要有明确资源失败、禁止成功Commit/交付；清理失败不能释放名额后继续建SDK线程，不用daemon掩盖。需要合成不合作SDK与Windows真实网络黑洞验证，不能仅把daemon改false导致进程退出永久挂起。

尚未验证：Windows真实DNS/TLS/代理/网络黑洞、SDK在真实网络栈的关闭时限、Provider端是否停止计算/计费、账号权限与返回模型身份、真实QQ最终显示。取消本地I/O并不保证停止远端计算或费用。

## 5. 两部分展示与自由文本安全

`ai_service/channel_presentation.py` 提供独立 `qq-current-facts-withheld-explanation@1` 合同：

- **A 系统事实**：只从本次Tool Steps/Receipt的SourceSummary呈现；保留来源SIMULATOR、设备、观测/接收/评估时间、质量、新鲜度、连接及留存窗口含义，不重新查库补证据。
- **B 模型解释**：与A分区，本轮固定说明“未展示：自由文本尚未可靠核验”。不把模型文本拼入事实，不在失败时换用模型答案。
- `assess_explanation` 提供有限诊断：显式读数不符、缺测却声称数值、模拟来源却声称真实实测、可靠性不足却声称正常、声称写入操作；返回安全代码，不存储原文或抽取的私有值。
- 所有自由文本目前都allowed=false；匹配数值或没匹配到危险词也不证明安全。渲染器不依据一个allowed布尔值放行。否定句/引用/单位/隐含推理/疾病判断无法靠这些词法检查可靠理解，可能有误报漏报；**没有通用逐句事实验证器**。

未来可先研究限定结构化解释码→经审核服务器模板，或人工审核解释；若改变Prompt/输出合同/语义范围，须新Scope。不得直接把当前检测器当通行证开放任意自由文本。

## 6. BOT-3C-2 分阶段人工验收

### 6.1 现在可安全执行的命令

只读候选检查（不读Key/Policy/实例，不联网）；应返回 `QQ_AI_PREFLIGHT_VALID_LIVE_BLOCKED`，scope_matches=true、candidate、ai_enabled=false、can_execute_real=false、can_deliver_real=false。退出0仅表示候选准备有效：

`ai_enabled=false`说明真实QQ AI入口未装配，不是在检查Web助手或某个离线AI配置的开关。本轮不判断私有凭据是否存在、ACL是否可用；真实阶段由用户本机单独确认，不能把未检查解释为缺失。

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --check-ai-readiness
```

离线专项与完整管理回归（仅新建测试实例，不打开BOT-2C或用户实例）：

```powershell
$env:TEMP = Join-Path $PWD 'outputs/test-tmp'; $env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -X utf8 -B -m unittest apps.qq_bot.tests.test_ai_preparation apps.qq_bot.tests.test_provider_sdk_preparation
.\.venv\Scripts\python.exe -X utf8 -B scripts/dev/run_tests.py management
```

### 6.2 用户必须逐项批准

| 项目 | 要明确的内容 |
|---|---|
| Provider | 固定Preset/service/base/model；是否同意把指定当前窗口事实发给Provider；Key由用户本机录入，不贴聊天 |
| Scope | SDK清理修复后的精确Scope hash、本地实验批准ID；不能只说“使用现有Qwen资格” |
| 次数 | Provider本机阶段最多1 Turn、QQ阶段另行最多1 Turn；每Turn最多2次模型HTTP请求、1个只读Tool，零重试 |
| 输出和时间 | 建议沿用512 tokens/请求、90s总Turn；最多1024输出tokens/Turn，队列等待占总时间 |
| 成本 | 用户批准的币种/金额上限、官方输入/输出价格和核验日期、输入预算及执行方式、账号消费保护；均未配置，不能宣称有硬费用上限 |
| 实例/设备 | 明确本机配置路径、instance_id、设备ID、只读v2实例；是否允许源为SIMULATOR的数据作为这次真实模型输入 |
| QQ披露 | AppID、专用测试群、成员OpenID白名单；确认群内其他人能看到数据这一事实；不能以昵称/群主身份授权 |
| 有效期/撤销 | 有期限的RunConsent、权限generation、过期拒绝、如何停止和撤销 |

`max_tokens`只限制输出，不是费用总上限；输入的System/问题/Tool上下文也可能计费。未取得最新官方价格、输入上限和平台消费约束前不填写估算金额，不假设取消不计费。

### 6.3 联调顺序与命令边界

1. 完成SDK资源阻塞维护、真实类型化Service/Provider和Delivery Gate；重新审Scope并获批。先重跑上述离线检查，不读取或探测真实Key来代替授权。
2. 明确批准指定实例只读访问后，使用**现有真实存在的**配置检查命令，替换路径为已批准文件；本轮未替用户执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --check-config --access-file '已批准的绝对访问配置路径' --monitoring-config '已批准的绝对Monitoring配置路径'
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --check-monitoring --access-file '已批准的绝对访问配置路径' --monitoring-config '已批准的绝对Monitoring配置路径'
```

3. 真实Provider本机单轮先行：仅在新入口实现/离线测试和用户逐次费用批准后执行；校验实际Tool Receipt、来源/限制、请求数、Usage、总耗时、取消和SDK资源。未成功不进入QQ阶段。
4. 再独立批准真实QQ AI单轮：专用测试群、授权成员发`@机器人 /问AI 当前水质如何？`；固定命令仍响应，A事实完整，B解释仍不暴露未核验文本；分别记录API接受和QQ客户端显示。
5. 用新消息分别人工测试超时/取消、Gateway断线、权限撤销、重复消息、未授权成员、发送未知；模拟/失败均不得自动重推理或重发。取消、超时是否仍计费由真实Provider记录确认。

**当前没有可执行的真实Provider渠道单轮命令，也没有真实QQ AI启动命令。** 既有`--connect`只能验证固定只读命令，不能完成第3/4步；不要尝试不存在的`--enable-ai`、把示例当运行配置，或沿用旧三工具资格脚本冒充渠道验收。BOT-3C-2需要先按阻塞清单实施并审核入口，再给出其精确命令；本轮不杜撰尚未实现的CLI。

## 7. 测试矩阵与结果

| 范围 | 本轮离线证据 | 仍需人工/后续维护 |
|---|---|---|
| Scope/资格 | 精确候选匹配、变更失效、旧资格/自升状态拒绝、预检零实例/密钥/网络 | 真实试用批准、RunConsent、成本执行门禁 |
| Gateway装配 | 原worker/run接收/收尾、独立固定回复、唯一共享claim、跨路由去重、群移除/断线取消 | 真实类型化装配、实际QQ送达 |
| SDK | 真实SDK+内存HTTP，headers/body取消、期限、零重试、关闭/线程退出 | 不合作清理、真实网络、远端计算/计费 |
| 内容 | 读数/来源/状态/动作矛盾诊断，匹配仍拒绝，篡改allowed也不展示正文 | 受控解释输出合同与真实回答质量 |
| 回归 | B-1/B-2、固定查询、Web、Monitoring、Knowledge、Simulator与前端 | 本轮不继承真实模型资格 |

最终结果：新增 **28/28**（准备/路由/展示23项、真实SDK内存HTTP5项）；相关定向 **88/88**；完整管理回归 **790/790 Python（含214项Bot）+ 116/116 Node（11文件）**，Python阶段165.999s，退出0。覆盖原BOT-2B固定查询、B-1/B-2、Web Normal/Streaming和原三个只读Tool、Monitoring/Knowledge/Simulator/HTTP；不把这些离线通过记为真实模型资格。

10个本轮相关Python文件AST、2份新增JSON语法、新报告链接与 `git diff --check` 通过。只读 `--check-ai-readiness` 实跑返回 `QQ_AI_PREFLIGHT_VALID_LIVE_BLOCKED`，Scope匹配，真实执行/交付均false，密钥/Policy/实例未检查、网络请求0。

## 8. 开发边界与复核

新增准备范围：`channel_scope.py / channel_presentation.py`、候选JSON、`ai_preflight.py / ai_routing.py`、两份专项测试；修改`ai_delivery.py`共用提交owner、scheduler批量取消、Gateway显式Fake注入、CLI只读预检，以及必要文档索引。没有修改Agent循环、Monitoring规则/Schema或Web公开DTO，没有安装依赖。

真实数据/凭据未读取或修改，Management及其他项目未修改，没有commit/push。工作树开始时包含此前未提交的BOT阶段成果；执行期间检测到外部HEAD更新为`7322f0d`（BOT-3B），已保留，当前新改动仍在工作区，不回退该提交。

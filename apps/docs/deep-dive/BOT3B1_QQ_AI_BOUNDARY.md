# BOT-3B-1：QQ AI 服务边界与权限装配

实施日期：2026-10-25。仅 `D:\CodexProject\Fishery_AI_Prototype`，基线 `main@fb140f0`；保留 BOT-2B/BOT-3A 未提交改动。本阶段完成离线基础装配，**不是可连接真实 Provider/QQ 的 AI 发布版本**。

## 1. 当前结果

```text
模拟 QQ 消息
 → QQAdapter.admit_offline（原 App/群/成员/时间/去重/限流/并发准入）
 → QQAICoordinator.prepare（本机 AI 许可、设备、权限 revision 与预算）
 → ManagementAssistantService.prepare_channel_turn / claim_turn
 → 原 AssistantService → 原 ToolCallingService SINGLE_ROUND 1/1/2
 → 唯一 get_current_water_quality Handler → InstanceMonitoring → MonitoringService / mode=ro
 → 原 Source Gate / Commit Gate
 → SourceSummary：从同一 Turn 的真实 Steps/Receipt 投影
 → 离线候选结果；实际 QQ 交付始终禁止
```

没有新增 Agent、HTTP 服务、Redis、工具循环、Prompt、数据库 Schema 或监测规则。通用 `apps/ai_backend` 和 `runtime/assistant.py` 未修改；Web 原有带 Knowledge 的装配和公开响应 DTO 保持兼容。

## 2. 修改文件与职责

| 文件 | 改动 |
|---|---|
| [qq_bot/monitoring_source.py](../../qq_bot/monitoring_source.py) | 补 `devices()`、守护后的 `bind()`、`binding_revision` 和历史 `metrics` 参数；委托既有 Service，不复制 SQL/规则/统计 |
| [qq_bot/adapter.py](../../qq_bot/adapter.py) | 提取共享 ingress 执行入口；新增仅 OFFLINE_NOT_SENT 可用的准备回调，不在锁内执行模型 |
| [qq_bot/ai_configuration.py](../../qq_bot/ai_configuration.py) | 独立严格 AI 配置，默认关闭；群/成员/设备/工具许可和 token/时间预算 |
| [qq_bot/ai_coordinator.py](../../qq_bot/ai_coordinator.py) | 离线 prepare/execute/check_delivery/discard；无 worker 队列、聊天历史或 QQ sender |
| [ai_service/channel.py](../../ai_service/channel.py) | 服务器内部授权、candidate Scope、canned Fake Provider、SourceSummary 和隔离的渠道结果 |
| [ai_service/service.py](../../ai_service/service.py) | Knowledge 可缺席；新增内部渠道 prepare/execute/validate，仍复用原 claim 和执行链 |
| [ai_service/contracts.py](../../ai_service/contracts.py) | Prepared Turn 可携带内部授权对象；不进入 Web 输入或公开 DTO |
| [business_tools/registry.py](../../ai_service/business_tools/registry.py) | Knowledge 缺席时完全不注册对应 Definition/Handler；沿用唯一工具 owner |
| [test_ai_coordinator.py](../../qq_bot/tests/test_ai_coordinator.py) | 新建隔离库、Fake Provider、模拟 QQ 的专项测试 |
| [ai.example.json](../../qq_bot/examples/ai.example.json) | 仅独立离线配置模板，enabled=false、grants=[]；未创建实际 AI 配置文件 |

## 3. Monitoring-only 与 Scope

`ManagementAssistantService(..., knowledge=None)` 现在可以合法初始化，只注册当前水质工具；历史、Knowledge、事件及写入工具均不在该组合中。历史 facade 的参数兼容不等于开放历史 AI Tool。

Monitoring-only 的普通 Web prepare/execute 路径保持不可发送；Bootstrap 显示 `candidate / can_send=false`。原本带 Knowledge 的 Web 路径没有改变默认工具、Prompt、预算或资格文件。

新组合合同为 `channel-current-offline@1`：

- 当前 Preset 的真实身份、Prompt/Definition 指纹、历史投影版本与 Policy revision；
- `data_bindings.water=management-current-water@1`，`knowledge=null`，不伪造 source/version；
- 冻结设备、实例绑定 revision、渠道权限 revision、预算与 epoch；
- 强制 `history=[]`、`CURRENT_OBSERVATION_QUERY`、Normal、SINGLE_ROUND 1/1/2；
- `environment=OFFLINE_FAKE_ONLY`、`release_status=candidate`，没有 qualification_id 或借用旧 released/local_experimental。

候选执行只允许 Service 显式注入的**精确类型** `OfflineChannelProvider`；它仅消费预置 ModelResponse/安全错误，没有 SDK、URL 或网络实现。渠道路径不使用原 `gateway_factory`，也不解析 Service 的真实 CredentialStore；只建立内存虚构凭据以满足原 Preset 类型合同。

底层 Prepared execution 的 `can_send=true` 仅用于这条受控 Fake 执行链，不是对真实 Provider 的发布授权。渠道结果固定 `offline_only=true / can_deliver=false`；普通 Monitoring-only Web 路径仍 false，真实 CLI 没有候选装配入口。不得以此标记申请真实资格已通过。

Scope、Preset、设备、工具集合、来源要求或 token 预算被更改时，执行前重新计算候选合同并拒绝不一致的 Prepared Turn。

## 4. 权限继承与失效

实际交集：已注册当前工具 ∩ 管理 Policy ∩ 独立 AI grant ∩ 原群/成员白名单及 current capability ∩ 冻结设备 ∩ 当前 candidate Scope。

- 只有显式 `/问AI 问题` 可准入；普通文字、`/AI`、固定命令不会被本协调层解释为 AI 请求。
- 原 access 配置不修改、不增加隐含 AI 能力。成员即使能使用固定只读查询，没有独立 AI grant 也不能执行模型。
- 设备来自群绑定与 AI grant，二者必须一致且在指定实例白名单内；问题正文不提供 Provider、工具、设备或数据路径覆盖。
- 当前工具只接受空参数；模型注入 `device_id` 会在 Handler 前失败。Knowledge/历史/ACK/删除/控制函数即使被模型伪造调用也不能执行。
- 准入、claim/实际执行、工具读取和交付检查均验证权限。管理 Policy 的共享来源与覆盖来源都核对 revision，不只检查管理覆盖文件。
- 本机 `reconfigure` 增加 generation 并取消旧 Handle；源绑定变化、Policy 变化、AI 关闭或预算改变使旧任务失效。
- 已完成任务在准备交付时再次验证原对象与权限；不能拿其他任务 ID 或结果替换。`check_delivery` 即使验证通过也固定返回 false。

这些对象仅供可信服务器代码创建，不接受 QQ/HTTP JSON 反序列化的 callback/Prepared Turn；数据类型本身不是对任意 Python 调用者的安全隔离。

## 5. 预算、重放与生命周期

独立配置仅支持固定 Qwen Preset、当前工具、每 Turn 输出 1–1024 token、时间 1–90s，默认 512/90。它不是对旧输出资格范围的扩展。

实际期限取配置预算与原 QQ 五分钟窗口扣除 15s 余量的较小值；临近窗口结束的消息在模型前拒绝。期限从准入起计算，不因执行阶段重新延长。

复用原 ingress 的去重和每成员/群限流；内部最多保存 8 个未清理的候选计划，Handle 沿用 RequestRegistry。计划只能执行一次；过期/撤销/重复均不能重新调用模型。已完成结果只是暂存的任务结果，不用于下一轮聊天历史，可显式 discard。

本阶段同步离线执行，没有 AI worker 队列、生产调度、单会话公平排队、成本总账或退出交付协议。因此不能把该接口接到真实 Gateway。`admit_offline` 对 live Adapter 直接拒绝，原 `receive()` 与 CLI 继续返回 AI_DISABLED。

## 6. SourceSummary 与模型错误事实

SourceSummary 从原执行结果的一个真实 ToolExecutionStep 与对应 Receipt 提取，包含：实例、设备、来源、操作状态、观测/接收/评估时间、质量、新鲜度、连接状态及三个有限指标。

接收时间取本轮 Tool canonical reading 的 `retrieved_at`，不是回答结束时间。摘要不从模型正文提取数值，也不再读数据库补证据。专项测试让工具返回 2.2 后入库 6.4，摘要仍保留模型当时取得的 2.2 与原时间，且 capture 仅调用一次。

`CURRENT_OBSERVATION_QUERY` 证明查询完成，不证明有数据或 fresh/valid；NO_DATA 也可完成操作。无数据、partial/missing/invalid、stale/offline 时展示“当前状态无法完整确认”，保留原值的留存窗口含义，不补零、不假定健康。

**本阶段不宣称有自由文本事实判定器。** 模型正文放在内部 `model_text`，始终 `model_text_verified=false`，不作为可交付文本。`presentation` 仅用可信 Tool 事实生成，明确 SIMULATOR 和时间限制。Fake Provider 即使说“实时 DO=8、全部正常”，该文本也不会进入事实展示；实际 2.2、缺测和过期限制不会被覆盖。

原 Agent 的完整 Final/Source Gate/Trace Commit 仍运行。未调用工具的伪装查询、工具失败、截断或 Trace 失败不产生成功来源摘要。Backend 完成与 QQ 成功送达仍是两个门槛，本阶段第二个门槛始终关闭。

## 7. 离线验证

只使用测试新建的临时 SQLite、虚构 UTC 观测、Fake QQ 报文、canned Provider 和临时 Trace；不打开 BOT-2C 实例、工作区默认业务库、备份或任何 Management 数据。不读取实际 access/AI/Policy/Credential 文件。

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
$env:TEMP = Join-Path $PWD 'outputs/test-tmp'; $env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -X utf8 -B -m unittest apps.qq_bot.tests.test_ai_coordinator
.\.venv\Scripts\python.exe -X utf8 -B scripts/dev/run_tests.py management
```

专项覆盖：合法单轮、零密钥读取、一次 capture、数据库不变、模型伪造读数隔离、默认关闭、未知成员/群、只有固定查询授权的成员、群能力交集、设备不匹配/跨群隔离、Knowledge/历史/写工具拒绝、参数注入、无 Tool 伪装、NO_DATA、stale/offline/partial/missing/invalid、权限/Policy/绑定变更、模型后撤销、交付前失效、取消、claim-execute 间失效、重放、近 QQ 期限拒绝、篡改 Scope/预算/来源要求、Trace 失败、日志隐私与配置严格校验。

验证环境为项目 `.venv` 的 Python 3.12.14。新增专项 **31/31** 通过；Web/历史/三工具等定向 **75/75** 通过；最终完整管理回归 **722/722 Python + 116/116 Node** 通过。语法、JSON、文档链接和 `git diff --check` 通过。最后仅明确了 Monitoring-only availability 文案，随后追加专项及 Web Service 定向验证。

未执行真实 QQ 或模型验收，未改 Monitoring Schema、领域规则、Agent 循环、真实数据或凭据；不把 Fake 成功标记为真实发布资格。

## 8. BOT-3B-2 后续计划

以下为 B-1 当时的后续计划。B-2 现已完成 **Fake-only** 有界调度与交付协议，当前状态见 [BOT-3B-2](BOT3B2_QQ_AI_SCHEDULING.md)；真实入口、真实 Scope 资格及模型正文展示仍未开放。

1. 审核本次 candidate 服务边界和事实展示策略；保持 AI 默认关闭。
2. 实现有界 AI worker/队列、每会话单飞、公平背压、AI 独立频率/总成本上限，保持固定命令及心跳短路径。
3. 完成真实消息上下文的单次交付、发送前授权/期限复核、送达未知不重发、停机取消及有界资源回收。
4. 单独批准模型、有限输出/费用、指定实例和允许披露的群/成员；为真实 Provider 建立明确的候选到实验范围，不把本次 Fake Scope 标成真实资格。
5. 先 Fake Gateway/Provider 联合验收，再单独批准真实 QQ 与真实 Provider 单轮；无数据或过期限制始终可见。
6. 本阶段不做聊天记忆、Knowledge、历史 AI Tool、事件 AI Tool、主动通知或写操作；这些不能通过打开本配置而自动获得。

如果尚未完成队列与交付协调，真实 QQ `/问AI` 必须继续 AI_DISABLED。配置示例只是离线授权合同，不是可联网启动命令。

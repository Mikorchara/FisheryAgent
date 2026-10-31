> 历史归档（2026-10-31）：本阶段已被后续实现替代。保留设计与验收证据；当前操作见 [启动指南](../../BUILD_RUN.md) 和 [文档入口](../../README.md)。

# BOT-3D-2C-1：逐 Turn 真实类型装配（离线准备）

日期：2026-10-26；仓库 `Fishery_AI_Prototype`，起始 `main / 96f8a23`、工作树干净。

本轮完成真实类型化路径的代码和 Fake 验证，不是联网验收。没有访问真实 QQ/Qwen、私有凭据或现有业务实例，没有修改 Management、Monitoring Schema、规则或 Agent 工具循环。旧单轮 FAST 与普通 QQ CLI 保留原合同；普通 CLI 仍 AI_DISABLED。

## 1. 架构与许可边界

```text
本机终端（主线程）                         Gateway 独立线程
  第1轮计划 → 人工挑战批准                    READY / 心跳 / Mention / 固定指令
       ↓                                           ↓
  同一 ConversationTrial / Store / Coordinator / Scheduler / DeliveryOwner
       ↓                                           ↓
  第1轮独立 Service + ConversationQwenTurn + 原 TrialQwenAdapter + Handle
       ↓ 原 Agent / 当前水质Tool / Source、Commit、SDK资源门禁
       ↓ 一次QQ提交 → API明确接受 → 实际安全文本哈希核对 → RAM提交
       ↓ 任务释放、脱敏结果就绪
  第2轮实际状态计划 → 人工再次批准                心跳继续运行
       ↓
  第2轮独立 Service + 独立 Session / Handle → 重新取得本轮水质
```

不在两轮之间修改共享 Service 的 `_channel_trial`，也不复用已经执行过的 Session。持久 Coordinator 的基础 Service 不执行模型；每个 Plan 固定引用本轮私有 Service。两轮共享 RAM，但各有独立 SDK 计数、批准、Handle 和资源关闭结果。没有第二套 Agent、Redis、数据库聊天表或另一个消息平台。

新入口默认不联网；运行必须显式同意实例读取、Provider、QQ 和 Mention AI。一个进程最多消费两轮模型批准、最长600秒，仅原配置授权的一个群/一个成员/一个设备；问候和能力说明是程序模板。固定命令优先，未知指令不会转为模型请求。新 Transport 是明确的独立类型，不能把 Fake Store 任意接到旧 Trial Transport。

## 2. 独立逐 Turn 批准

新合同：`qq-qwen-conversation-turn-trial@1`。

| 绑定项 | 实现 |
|---|---|
| 运行身份 | 每进程新 `run_id`、Service epoch；不重启机器人续接旧批准 |
| Scope / Provider | 当前源码、SDK资源合同、Prompt、Tool、固定 Qwen Preset、预算及展示合同 |
| 访问权限 | 本机指定的 access / AI / Monitoring / Policy 配置和绑定摘要，运行时持续复核 |
| 会话状态 | 完整身份键哈希、清空/重建 revision、已接受 Turn 数、实际安全答复哈希序列摘要 |
| 第二轮前置 | 第一轮真实结果摘要的 predecessor SHA-256；第一轮交付、历史提交、资源关闭均须可确认 |
| 金额 / 有效期 | 本轮费用上限、批准期限，不超过整个进程剩余期限 |
| 一次性消费 | 原AI配置目录下独立 `.qwen-conversation-<approval_id>.used`，create-only写入 |

每轮批准仍只允许：Normal、SINGLE_ROUND、1 Tool / 1 Round / 最多2模型请求、512输出Token/请求、90秒、零重试。没有提高旧批准的 max_turns。

准入即消费本轮批准；之后即使排队、SDK、发送或报告失败，也不会退还、重试或重复消费。文件改名/复制不改变消费身份。第二轮不能提前生成：第一轮必须先成为已交付且已记忆的实际结果。没有第二轮批准时，不签发第二轮 HistorySnapshot，更不会开始推理。

终端主线程审批，Gateway、心跳和原只读命令在独立线程运行。Windows控制台使用可取消的逐键输入，不建立无法停止的 input() 后台线程，不在等待输入期间持有 Service / Scheduler / Store 锁。第二次审批期间仍验证了心跳响应。进程期限包含人工审批等待时间。

## 3. 历史与事实

继续复用 [2B 的有界 Store 和服务器历史快照](BOT3D2B_MENTION_CONVERSATIONS.md)：6个成功Turn、15分钟TTL、64会话、24KiB/会话、1MiB总内容、4KiB Agent投影。真实入口进一步限制为同一批准身份的两轮。

第二轮批准绑定第一轮实际安全答复的摘要，不保存模型原始正文或完整QQ事件。进入 Agent 的仍是原 `UNTRUSTED_TRANSCRIPT_V1` 话题投影。历史不创建 Tool Receipt，不能代替当前水质事实。每轮都强制本轮 Monitoring Tool，并继续使用 `qq-water-explanation@1` 的 A/B/C 展示，原始自由文本不会放行。

只有 API 明确接受、Backend/Source/Commit成功、SDK安全关闭、实际发送文本与 Receipt 哈希相同、身份和会话仍有效时才提交历史。未知、失败、取消、撤权或清空冲突均不提交成功历史。记忆写入失败不补发、不重新推理。

清空会话会使尚未执行的旧状态批准失效，不能用旧批准重新创建已清空的历史。第二轮完成后仍可用程序指令 `/清空会话`；第三个水质AI请求拒绝，不自动增加许可。

## 4. 输出记录与停止

所有计划和报告在新建、拒绝覆盖的运行目录中。不会改写以前的批准、used标记或历史Provider回执。

| 文件 | 含义 |
|---|---|
| `session.json` | 当前完整Scope与脱敏模型/实例/设备/群成员摘要、预算 |
| `turn-1.plan.json` / `turn-2.plan.json` | 对应本轮状态的待批准计划 |
| `turn-N.approval.json` | 本机操作者明确挑战确认后的独立批准 |
| `turn-N.trace.jsonl` | 原allowlist日志：步骤、状态、Usage、耗时，不含聊天或模型正文 |
| `turn-N.delivery.json` | QQ提交后立即保存的安全交付检查点；不冒充最终历史提交结果 |
| `turn-N.result.json` | Backend、SDK、API接受、解释校验、History Commit及一次性消费摘要 |
| `result.json` | 整体停止原因、两轮结果、RAM清空、完成状态；不保存聊天正文 |

API接受和客户端实际显示严格分开：报告始终保留 `client_display_confirmed=false`，客户端显示必须人工确认。`verified` 表示本轮安全执行/交付/历史条件通过，不是通用语句事实核验或真实计费确认；解释是否放行看 outcome 中的 explanation 字段。

Ctrl+C、审批拒绝、超时、撤权或Gateway失败会取消待执行任务和拥有的I/O、回收线程，保留已接受的检查点及最终报告；没有补偿发送。Gateway原始失败原因不能被稍后的RAM关闭错误掩盖。最终报告写入失败输出 `CONVERSATION_RESULT_WRITE_FAILED / report_saved=false`，不覆盖原文件，不重跑模型。

一次Ctrl+C按正常清理路径验证。强制杀进程、反复中断或直接关窗仍可能阻止最后一次磁盘写入，不能承诺这些情况下必有最终报告；提前交付检查点提供已保存证据。原SDK不合作线程无法强制退出的剩余风险仍在，资源清理失败即停止，不自动开启下一轮，远端计算/计费是否停止仍为 unknown。

## 5. 实现文件

| 文件 | 职责 |
|---|---|
| `apps/ai_service/channel_conversation_trial.py` | 独立真实试用Scope、每Turn Session与历史授权决策，复用原SDK Adapter |
| `apps/qq_bot/conversation_trial.py` | 本机配置检查、两轮许可接力、消费、私有Service装配和安全结果 |
| `apps/qq_bot/conversation_trial_cli.py` | Check / Run、可取消审批、并行Gateway、检查点/最终报告 |
| `scripts/dev/Test-QQConversation.ps1` | 复用已有路径、报告目录和联网确认辅助函数的简洁入口 |
| `apps/qq_bot/conversations.py` | 增加不含正文的会话状态摘要，内存合同不变 |
| `apps/qq_bot/ai_coordinator.py`、`ai_scheduler.py` | Plan绑定本轮Service、完成后接力，旧路径默认保持 |
| `apps/ai_service/service.py` | 精确识别新增试用Session；原Web和旧单轮分支保持 |
| `apps/qq_bot/ai_trial_delivery.py`、`ai_delivery.py`、`ai_routing.py` | 明确的Conversation Transport、原交付owner及Mention门禁 |
| `apps/qq_bot/gateway.py` | 复用真实类型路由；可请求中断自身连接，保留URL/TLS/重连限制 |
| `apps/ai_service/channel_trial.py`、`channel_conversation.py` | 为新增依赖更新实现指纹；旧次数/预算/发布资格不变 |
| 两份 `resources/qq_conversation_*.json` | 新真实试用candidate、重算的Fake candidate，均非批准 |
| `apps/qq_bot/examples/conversation-trial.request.example.json` | 六项本机配置引用；不含密钥、不自行建立Policy |
| `apps/qq_bot/tests/test_conversation_trial.py` | 真实SDK类+内存HTTP+Fake Gateway+合成SQLite与PS Check测试 |

## 6. 离线验证与Scope

全部自动化使用临时合成SQLite、MockTransport和虚构QQ消息；没有真实账号或Key。

| 验证 | 结果 |
|---|---:|
| 新增逐Turn专项 | 31项，包含在下两项回归中全部通过 |
| Bot全套（含旧FAST、2B Fake） | 390 / 390，172.817秒 |
| 完整管理Python（含Web Normal/Streaming、Monitoring、Simulator、Knowledge） | 983 / 983，270.100秒 |
| Node前端 | 116 / 116 |
| 静态校验 | 14个Python文件语法、JSON、147个本地文档链接、git diff --check通过 |

源码SHA-256与开始时比较：`apps/ai_backend/`（含原SDK资源门禁）、`ai_service/runtime/`、Monitoring、Web、Simulator、旧`src/`均无变化。HEAD仍为`96f8a23`；没有commit/push或跨项目同步。

非敏感记录：`outputs/test-tmp/bot3d2c1-20261026T090143Z-6d5b6b22/` 的 `bot-regression-final.log`、`management-regression.log`、`scopes-after.json`、`static-checks.json`。临时SQLite、虚构批准及used标记随对应测试夹具释放；没有读取或改写旧真实批准、回执和业务实例。中间失败调查日志保留，以最终回归为准。

| Scope | 本轮SHA-256 |
|---|---|
| 新逐Turn真实试用candidate | `a204da6968ff312ab058a319b054b063d17dd3d1a69f1ebb6eb0ca5b97c75636` |
| 重算Fake Mention/Memory candidate | `01cd536a361fca5aa327329943138e908d6b4841c3a2238b33ecb361a1fbd3cb` |
| 原单轮FAST完整实现 | `d9f7bfa10cc34445513eb8e3a4e38694be577775d3bbe837298511f7b28a872d` |

关键验证：同一Gateway/Store进程的两轮共4模型请求、2次当前水质读取、2次独立消费；第二轮DO从2.2更新到6.1，旧读数不进入当前事实。第二轮终端审批期间已测试Gateway心跳响应。每轮报告、交付检查点、最终报告与RAM清空均有Fake端到端验证。

另外覆盖：未批准不签发历史快照、不能提前批第二轮、跨进程旧批准/复制已消费批准拒绝、期限和状态变化、跨群/成员隔离、撤权取消真实SDK类的本地Mock I/O、超时、SDK失败隔离、未知交付、审批取消/Ctrl+C、Gateway失败、最终报告写入失败、数据库查询前后字节摘要一致。自动化没有证明真实QQ客户端显示、真实网络中断后SDK行为或远端停止计费，这些仍属于C-2验收和已知限制。

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m unittest apps.qq_bot.tests.test_conversation_trial -v
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s apps/qq_bot/tests -t .
.\.venv\Scripts\python.exe -X utf8 -B scripts/dev/run_tests.py management
```

维护者candidate位于 [qq_conversation_trial.json](../../../ai_service/resources/qq_conversation_trial.json)，`status=candidate / qualification_id=null`。只存在该文件不授予真实执行许可；批准必须经新合同的本机挑战、当前绑定验证和一次性消费。

Fake candidate 和FAST完整实现指纹也会随共享装配改动变化；没有改写旧真实批准、回执或发布资格。旧单轮批准不兼容新多轮合同，新多轮批准不能通过旧FAST加载。普通QQ CLI不支持本轮真实多轮开关。

## 7. C-2 人工验收准备（尚未执行、仍需授权）

1. 人工确定隔离SIMULATOR实例、设备、专用群和一个授权成员；保留原只读实例和Monitoring-only Policy。不读取或复制凭据，继续用现有Prototype私有存储。确认本机已保存Qwen/QQ凭据，但本轮未检查其存在或有效性。
2. 将 [request示例](../../../qq_bot/examples/conversation-trial.request.example.json) 的六项引用填入自己新建的 `outputs/qq-bot/conversation.request.json`。路径及群/成员必须对应已有获批配置；不新建空Policy来绕过原配置，不改真实实例。示例路径不是对本机现有文件的存在保证。
   如已有相同六字段的本机request，可用 `-RequestFile '绝对路径'` 指向它；这只复用配置引用，不复用旧批准或Provider回执。
3. 在Prototype根执行安全检查（不联网、不打开Monitoring数据库、不读密钥、不创建批准）：

   ```powershell
   .\scripts\dev\Test-QQConversation.ps1 -Check
   ```

4. 用户批准C-2 Scope、实例披露与两轮预算后，才执行：

   ```powershell
   .\scripts\dev\Test-QQConversation.ps1 -Run -MaxCostCny '2.00' -RunSeconds 300
   ```

   先分别确认QWEN、QQ联网；脚本显示固定模型、实例/设备、群成员摘要、Scope和预算。群/成员原ID只在自己的配置中核对，普通日志不输出完整OpenID。原FAST仍是独立单轮入口，不替换其Provider前置回执门禁；新多轮合同由每轮同时明确批准Provider/QQ及数据披露，不以旧Provider回执充当许可。

5. 复核 `turn-1.plan.json` 后，在本机终端输入本轮 `APPROVE <挑战>`。机器人连接成功后发送 `@机器人 你好`（零模型），再发 `@机器人 现在水质怎么样？`。
6. 第一轮API接受、记忆提交、SDK关闭后，终端生成第二轮实际状态计划并再次等待人工挑战。审批期间心跳正常运行。批准后再发 `@机器人 那溶解氧呢？`，本轮会重新读水质。
7. 收到第二轮后发送 `@机器人 /清空会话`，核实仅当前RAM清空。等待运行时间结束，或按一次Ctrl+C并等待报告保存。程序只记录API接受，QQ客户端两次实际显示由用户分别确认。
8. 检查两份Turn结果的2模型请求、SDK `CLOSED / thread_exited / local_io_closed`、API接受、`HISTORY_COMMITTED`、解释合同与最终 `result.json`。送达未知或资源失败停止，不重用许可、不自动重跑。

默认每Turn费用上限2.00元，两Turn总上限4.00元；复用原FAST静态价格合同下的保守预留约1.602765元/Turn（两Turn3.205530元），不是实际扣费或实时价格。操作者须在审批时重新核对北京区价格/上下文依据；每请求输出仍为512 Token，零重试。

测试库若已经 stale/offline，页面/QQ必须如实显示，不能修改时间戳冒充新鲜；需要新观测时由用户另行批准向指定隔离实例生成SIMULATOR数据，不在本轮自动启动Simulator或接入其他实例。

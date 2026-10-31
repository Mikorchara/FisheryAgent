> 历史归档（2026-10-31）：本阶段已被后续实现替代。保留设计与验收证据；当前操作见 [启动指南](../../BUILD_RUN.md) 和 [文档入口](../../README.md)。

# BOT-3D-2B：Mention AI 与有界会话记忆（离线）

核验日期：2026-10-26。项目：Fishery_AI_Prototype；起始 HEAD `3dcc2ac`。

后续状态：[2C-1 已增加逐Turn真实类型装配并离线验证](BOT3D2C1_REAL_CONVERSATION_TRIAL.md)，尚未执行C-2联网。本文件保留2B阶段的实现与历史Scope；当前指纹以新说明及资源文件为准，普通QQ入口仍未开放Mention AI。

本阶段实现了经批准的 [2A 设计](../../deep-dive/research/BOT3D2A_MENTION_CONVERSATION_DESIGN.md)，仅允许精确 Fake Provider / Fake QQ Transport 装配。普通 QQ CLI 和真实 FAST 单轮入口没有接入会话记忆；没有调用 QQ/Qwen，没有读取密钥或现有业务实例，没有修改 Management。

## 1. 调用链与修改范围

```text
Fake Gateway READY / Resume 后的真实类型 GROUP_AT_MESSAGE_CREATE
  → 有界接收队列 + 绑定本 Gateway/消息内容的内部 Mention 凭证
  → 原 QQAdapter 准入（群、成员、去重、限流）
  → 确定性意图路由
      ├─ 原固定命令优先 → 原只读服务 / 同一个 PassiveReplyOwner
      ├─ 问候、能力、澄清 → 程序模板 / 同一个 PassiveReplyOwner
      ├─ /清空会话 → 当前授权会话失效 + 取消其未完成任务
      └─ 当前水质 / 明确追问
          → 原 QQAICoordinator / Scheduler
          → 服务器签发的 RAM HistorySnapshot
          → 原 ManagementAssistantService / AssistantService / ToolCallingService
          → 每 Turn 重新执行当前水质 Tool → Source / Commit / SDK 资源门禁
          → 原 A/B/C 安全答复 → 单次 API 提交
          → 明确 API 接受后，提交实际发送的安全答复到 RAM
```

没有增加 Agent、工具循环、HTTP 服务、SQLite 表或持久聊天记录。`apps/ai_backend/`、`ai_service/runtime/`、Monitoring 与 Web 源码不变。

| 文件 | 职责 |
|---|---|
| `qq_bot/intent.py` | 有限的确定性意图、程序答复、内部 Mention 凭证 |
| `qq_bot/conversations.py` | 严格配置、会话身份、RAM 存储、快照、限额与清空代次 |
| `ai_service/channel_conversation.py` | Fake-only 历史授权、独立 Prompt / candidate Scope |
| `ai_service/contracts.py`、`service.py` | Prepared Turn 增加可选服务器历史快照；旧单轮仍拒绝无快照的非空历史 |
| `qq_bot/ai_coordinator.py` | 身份绑定、失效检查、历史签发与交付后提交 |
| `qq_bot/ai_routing.py`、`gateway.py` | 固定命令优先、认证事件边界、Fake 路由 |
| `qq_bot/ai_delivery.py`、`ai_scheduler.py` | 交付结果释放前的安全文本交接、历史状态和当前会话取消 |
| `ai_service/channel_trial.py` | FAST 指纹补齐新增依赖；单轮许可、次数、费用与 history=false 不变 |
| `qq_bot/examples/conversation.fake.example.json` | 默认 Command / 无记忆的独立离线配置模板 |
| `ai_service/resources/qq_conversation_candidate.json` | Mention + 记忆组合的维护者 Fake-only candidate；不授予真实执行资格 |
| 两份 `test_conversations.py` / `test_mention_conversation.py` | 有界存储、权限、交付竞态与 Fake Gateway 多轮端到端 |
| 本说明、README / ROADMAP / BUILD_RUN / STRUCTURE 与 2A 状态提示 | 实现说明、离线命令、文件索引与真实试用边界 |

## 2. 触发方式和能力边界

`ConversationOptions` 默认 `trigger_mode="command"`、`memory_enabled=false`。JSON 模板通过 `ConversationOptions.from_dict()` 严格解析，只允许所列字段和向下缩小的限额；它是独立的 Fake 装配配置，不是新的真实 QQ CLI 参数。旧 AI v1 配置和真实批准文件不增加字段。

离线测试装配使用 `ConversationOptions(trigger_mode="mention_ai", memory_enabled=True)`，把 Store 显式交给 Coordinator。Service 必须是精确 `OfflineChannelProvider` 且没有 QwenTrialSession；Router 必须使用精确 `OfflineQQGateway`。把会话 Store 接到旧真实/试用装配会拒绝，不因 candidate 或配置布尔值而获得网络权限。

| 输入 | 行为 |
|---|---|
| `/帮助`、当前/历史水质、当前异常等原固定命令 | 始终优先，参数错误也不转为模型请求 |
| `@机器人 你好` / `你能做什么？` | Mention 模式且 AI 授权满足时，程序模板，零模型请求 |
| `@机器人 现在鱼塘水质怎么样？` | 本轮当前水质 Tool + 原结构化解释 |
| `@机器人 那溶解氧呢？` | 有有效已交付水质话题才进入 Agent；重新查询当前观测 |
| `那它呢？` / 没有上下文的追问 | 程序要求澄清 |
| `/问AI 当前水质` | Command 或 Mention 模式均可显式请求；空正文或嵌套命令不会成为任意聊天 |
| `/清空会话` | 仅当前授权身份的 RAM 会话；不修改任何 Monitoring 事件 |
| 未知 `/指令`、历史 AI、Knowledge、写操作、设备/Provider 切换 | 不触发模型；保留固定命令错误或说明能力限制 |

只有 Gateway 在认证 READY/合法 Resume 路径收到的群 @ 事件能取得内部凭证。普通群事件、伪造 `@` 文本、直接提交未认证事件、换用另一消息内容或另一个 Gateway 的凭证均不能触发 Mention AI。显式 `/问AI` 保留原命令授权合同。

首版记忆是有限话题记忆，不是开放领域聊天。原问题先转为当前水温/pH/溶解氧/水质的规范问题；用户注入文本和任意旧正文不进入模型历史。

## 3. 会话身份、预算与失效

会话键：App + 群 + 成员 + instance_id + device_id + 权限 revision/generation + 绑定版本 + Policy revision + Scope SHA-256 + Service epoch。内部键和 Turn 禁止默认 repr 暴露标识或答复。

| 限制 | 默认上限 |
|---|---:|
| 成功且 API 接受的水质 Turn | 6 / 会话 |
| 空闲 TTL | 900 秒，以单调时钟计算 |
| 会话数 | 64 |
| 序列化 Turn 内容 | 24 KiB / 会话，1 MiB / Store |
| 进入 Agent 的完整历史对投影 | 4 KiB |
| 待完成快照 | 8，与既有 Coordinator 准入上限相同 |

内容预算不是 Python 进程 RSS 保证；对象与索引另有开销，但会话数、Turn 数、快照数均有独立上限。超限按完整 Turn 裁剪，必要时淘汰空闲会话；不淘汰仍有有效任务租约的会话来腾挪容量。不能安全容纳时拒绝记忆写入，不能靠重发补救。

快照使用 Store 内部登记的对象身份，不能靠复制 dataclass 或伪造 history 取得授权。清空/过期/重建后产生新代次；旧快照不能写回。原 Scheduler 保持同会话单飞。TTL 在读取、校验和提交时惰性检查，不新增后台定时线程。撤权、绑定/Policy/Scope 改变后原历史失效；重启创建全新 Store，不恢复磁盘记忆。

## 4. History 与事实边界

Store 保留规范化问题、实际发送的安全答复及其哈希、API 接受时间、同轮来源时间和有效性标记。不保留原始平台事件、完整用户正文、密钥或原始模型正文。

交给原 `AssistantRequest` 的是 `AssistantHistoryTurn` 完整对：规范化问题 + 程序生成的话题/时间/来源投影，经过原 `UNTRUSTED_TRANSCRIPT_V1` 编码。旧数值和实际答复全文不再喂给模型。投影不创建 Tool Receipt，不加入本轮来源 Ledger。每个当前水质 Turn 都强制 `CURRENT_OBSERVATION_QUERY`，沿用 SINGLE_ROUND 的 1 Tool / 1 轮 / 最多 2 模型请求。

水质解释仍使用 BOT-3D-1 的 `qq-water-explanation@1` 和 A/B/C 展示。新 Prompt `QQ_CURRENT_DIALOGUE@1` 只加强“旧对话仅作主题、本轮重新取证”，没有放行模型自由文本。问候/澄清属于独立程序答复，不伪造 SourceSummary。

## 5. Delivery → History 合同

1. 原 Backend Final、Source Gate、Commit Gate 必须成功；原 RequestHandle 确认 SDK 资源安全关闭。
2. 原 DeliveryOwner 渲染并清理 A/B/C 文本，原 PassiveReplyOwner 每原始消息至多提交一次。
3. 只有 `DELIVERED` + `api_accepted=true` 才能候选提交历史；这表示 QQ API 接受，不是客户端已显示。
4. 在结果被释放前交接实际发送文本，核对 UTF-8 SHA-256 与 Receipt、任务未取消、权限/绑定/Scope/期限及快照代次仍有效。
5. 清空与交付并发时旧代次写入失败。失败、送达未知、取消、过期、撤权均不提交成功 Turn。
6. 记忆写入异常保留实际 API 接受状态，返回 `HISTORY_NOT_COMMITTED` 并丢弃该代次上下文；不会重发，也不会重新推理。报告交付检查点仍在历史提交之前执行。

历史状态有 `HISTORY_COMMITTED`、`HISTORY_ALREADY_COMMITTED`、`HISTORY_DISABLED`、`HISTORY_NOT_COMMITTED_DELIVERY`、`HISTORY_NOT_COMMITTED`，不写聊天正文到普通日志。

## 6. 离线复验

在 Prototype 根执行，测试使用临时合成 SQLite、精确 Fake Provider 与内存 QQ HTTP，不加载实际实例或密钥：

```powershell
$env:TEMP = Join-Path $PWD 'outputs\test-tmp'; $env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -X utf8 -B -m unittest apps.qq_bot.tests.test_conversations apps.qq_bot.tests.test_mention_conversation -v
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s apps/qq_bot/tests -t .
.\.venv\Scripts\python.exe -X utf8 -B scripts/dev/run_tests.py management
```

专项 51 项通过。包含 Fake Gateway READY → 两轮自然语言 → 4 次 Fake 模型请求、2 次当前水质读取、2 次 API 接受/历史提交，结束后 Gateway worker 与 3 个 Scheduler 线程均退出。第二轮观测从 DO 2.2 更新为 6.1，答复使用第二轮的 6.1；旧历史投影不含 2.2。

另覆盖固定指令优先、未授权/伪造 Mention、模板零调用、多身份隔离、TTL/字节预算/清空、过期缺测、权限/绑定/Scope 失效、清空与交付竞态、送达未知/失败、记忆异常不重发、注入、伪造快照、无 Tool 不能构造来源、资源清理失败、旧试用拒绝记忆。

| 验证 | 结果 |
|---|---:|
| 新 Mention / Store 专项 | 51 / 51，4.807 秒 |
| Bot 全部专项（含 FAST / 原固定命令） | 359 / 359，123.435 秒 |
| 完整管理 Python（含 Web Normal / Streaming、Monitoring、Simulator、Knowledge） | 952 / 952，251.557 秒 |
| Node 前端 | 116 / 116 |

原基线为 901 Python / 116 Node；本轮新增 51 项 Python。`git diff --check`、13 个改动/新增 Python 文件的无产物语法检查、修改文档本地链接检查通过。与开始时文件 SHA-256 对比，`ai_backend/`、`ai_service/runtime/`、Monitoring、Web、Simulator、`src/`、`scripts/` 受保护源码无变化。HEAD 仍为 `3dcc2ac`，没有提交。

非敏感测试记录保留于 `outputs/test-tmp/bot3d2b-20261026T072627Z-0700dd65/`：`mention-targeted-final.log`、`bot-regression.log`、`management-regression.log`、`scopes-after.json`、`static-checks.json`。中间夹具错误已修复，最终以这些 final / regression 结果为准；测试数据库是临时合成数据，测试退出后释放，未访问现有业务实例。

## 7. Scope 与 BOT-3D-2C 前置计划

| 范围 | 本轮结果 |
|---|---|
| Mention + Memory Fake-only candidate | `4f17f63e7678c133890c1a6a73f4ba9793e18275637f3013eede4f3e7e8f6e88` |
| 原单轮 Monitoring-only candidate | 保持 `2d89b74fe451f793c09e21fff90dc624d9fd2ee34a02c393284f2e61066350be` |
| FAST 完整实现 Scope | `e45d0a37c2c998e62e3204f5ac071ae53a85914e8b87b141bd2bc10141ca9f8e`，因共享装配与依赖清单变化失效旧批准 |

新增 candidate 的 `qualification_id=null`、`can_execute_real=false`、`can_deliver_real=false`。没有改写旧审批、used 标记、Provider 回执或已发布资格。原 FAST 继续 history=false、max_turns=1；本阶段真实多轮功能不可启动。

2C 必须单独设计并审核每 Turn 一次性批准接力、真实历史披露范围和绑定快照；每轮保持原次数、费用、Token、时间与 SDK 清理门禁。先用 Fake 验证每 Turn 消费/拒绝/中断，再由用户选择实例、群、成员、模型并批准 Provider 与 QQ 联网验收。不能给旧批准提高 max_turns，也不能直接把 Fake Store 接上 Trial Transport。

真实 SDK 不合作线程无法强制退出的既有风险没有改变；清理失败仍隔离并禁止后续 Commit/Delivery。QQ API 接受仍不等于用户客户端实际看见，需要人工分别确认。没有迁移或同步到 Management。

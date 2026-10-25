# BOT 阶段总结与后续边界

核查日期：2026-10-25（UTC+8）。仓库：Fishery_AI_Prototype，`main`，核查起点 `ddb9ecf`，工作树原为空。

## 1. 目前已经做到哪里

QQ 是原 AI Service 的接入渠道，没有建立第二套 Agent。固定指令可查询本机明确批准的 Monitoring 实例；自然语言实验仅限 `/问AI`、当前绑定设备、SIMULATOR、Normal、空历史、当前水质只读工具。一个 Turn 最多两次模型请求、一次工具调用，尚无聊天记忆、Knowledge/历史 AI 工具或写操作。

**人工验收证据**：本轮用户报告最近一次真实 Qwen → Monitoring Tool Calling → QQ 实验成功，SDK 正常关闭，QQ API 接受且用户在客户端看到消息。本轮没有重新联网或读取该实验的私有记录。程序的 `api_accepted` 与人工观察仍分开；不能把客户端可见自动写成机器已经验证的事实。模型自由文本继续不展示，展示的是同轮工具产生的可信来源摘要。

**本轮回归状态**：新脚本 13 项通过，管理 Python 866 项中 861 通过、4 错误 / 1 失败（均为原 FAST Fake QQ 集成用例），Node 116 项通过。单独重跑仍复现，尚不能宣称已形成稳定全绿基线；优先厘清 5s 夹具窗口与重复校验开销，再开展 BOT-3D。没有通过改生产期限、门禁或原测试断言来掩盖失败。

| 阶段 | 已实现的职责 | 当前使用状态 / 证据边界 |
|---|---|---|
| BOT-0/1A | 平台研究、固定命令、群/成员/设备权限、去重、限流 | 已进入后续真实链路；Fake 测试仍保留 |
| BOT-1B | 官方 HTTPS/WSS、心跳 ACK、Resume/Identify、有界重连、被动回复 | 用户报告核心群验收通过；长断网恢复、未授权成员仍应按原清单补测 |
| BOT-2B/2C | 显式实例配置、SQLite 只读、当前/历史/事件查询 | 用户报告指定 SIMULATOR 实例群验收通过；不自动寻找生产实例 |
| BOT-3B-1 | Monitoring-only Service、渠道权限交集、同轮 SourceSummary | 与 Web 共用现有工具循环；Fake candidate 不等于真实模型资格 |
| BOT-3B-2 | 有界 AI 队列、取消、Delivery Owner、一次回复 | 1 执行、2 等待、每会话 1 个；10s 排队 / 90s 总期限；被动回复期限留 15s 余量 |
| BOT-3C-1/2A | 真实装配准备、SDK 租约、清理失败隔离、Commit/Delivery 防线 | 已用于 FAST；线程不合作时仍不能强制退出 |
| BOT-3C-2B | SDK 子进程隔离草稿 | 暂停，所有执行入口拒绝；未接入 Web/QQ，不是已有保护能力 |
| BOT-3C-FAST | 独立 local_experimental 审批、Provider 前置报告、QQ 一次性试用 | 用户报告端到端已通过；原普通 QQ CLI 的 AI 入口仍禁用 |

历史阶段文档记录的是当时状态；“尚未实施 / 真实调用待批准”不能再作为整个项目当前结论。当前说明以本文件与实际源码为准，历史测试数字不代表本轮重新执行结果。

## 2. 模块、依赖及使用边界

| 模块 | 入口与依赖 | 职责 / 当前状态 |
|---|---|---|
| `qq_bot/cli.py`、`configuration.py` | access 配置、私有 CredentialStore | 固定命令网络入口；不执行模型。只在明确联网阶段解析凭据 |
| `gateway.py`、`transport.py` | websockets、httpx | 心跳、接收、重连、官方地址验证、token 与被动回复；不直接查询业务 SQL |
| `contracts.py`、`adapter.py`、`service.py` | 配置及权威业务服务 | 消息解析、权限、去重、限流和固定只读命令 |
| `monitoring_source.py` | MonitoringService → 只读 Repository | 本机固定实例/设备，保留来源、时效、质量；群消息不能改路径 |
| `ai_configuration.py`、`ai_coordinator.py` | 渠道授权、AI Service | 显式 `/问AI`，冻结权限与预算、空历史、当前水质能力 |
| `ai_scheduler.py` | Coordinator、RequestHandle、Delivery Owner | 有界任务、取消和线程回收；模型不阻塞 Gateway 心跳 |
| `ai_delivery.py`、`ai_trial_delivery.py`、`ai_routing.py` | 统一被动回复所有权 | 发送前重验权限/期限；未知送达不重试，固定指令与 AI 不争夺回复 |
| `ai_service/channel*.py` | 原 Service / Backend | 内部渠道合同、候选 Scope、来源展示及独立真实试用资格，不是另一个 Agent |
| `ai_backend/sdk_resources.py`、`execution.py`、SDK Adapter | OpenAI-compatible SDK | 租约、I/O 取消、清理确认、失败隔离；Web 也受影响 |
| `qq_bot/trial_configuration.py`、`trial.py` | 计划、审批、Policy、指定实例 | 人工审批、单次消费、费用/期限、Provider/QQ 分阶段装配 |
| `qq_bot/offline.py`、`tests/` | Fake SDK/Gateway、合成 SQLite | 隔离测试；不得用 Fake 回执冒充真实 Provider 前置报告 |
| `outputs/qq-bot/` | 本机配置、计划、审批、回执、trace | 不属于源码；含标识及批准材料，不应上传、提交或同步 |

## 3. 三条调用链

BOT 前的 Web：

```text
Web UI / HTTP → ManagementAssistantService → AssistantService
             → ToolCallingService / ModelGateway → SDK Adapter → Provider
             → Knowledge / Monitoring 只读工具 → Source Gate → Commit → Web
```

当前 Web：

```text
原 Web 路由与默认配置 → 同一 ManagementAssistantService / Agent 循环
                      → 同一 SDK Adapter + 新 SDK 资源租约/清理门禁
                      → 原 Knowledge / Monitoring 工具 → Source / Commit → Web
```

当前 QQ AI：

```text
QQ Gateway → Adapter / Trial Router → AI Scheduler → Coordinator
  [QQ 专用]                                ↓ 内部渠道授权 + 空 History
                 ManagementAssistantService → 原 Agent / SDK [与 Web 共用]
                          ↓                         ↓ SDK_RESOURCES（进程内共享）
                 指定实例 Monitoring 只读工具 → Source Gate / Commit
                          ↓ 同轮 SourceSummary；模型自由文本不展示
                 Delivery Owner → 发送前重验 → QQ API → 用户客户端人工确认
```

Web 与 Bot 通常为不同 Python 进程，资源隔离门禁不跨进程传播。同进程装配时，各 SDK Adapter 共享资源故障状态，不能笼统宣称两者互不影响。

## 4. 下一阶段建议

1. 先处理本轮发现的 FAST 5 项回归失败，再做三个薄测试入口的人工检查，固定成功/失败证据格式。
2. 经单独批准删除暂停草稿及专用测试，保留研究结论和 C2A 防线。
3. BOT-3D 先研究解释文本的证据约束、输出长度和失败降级，再单独实现多轮会话；不要同时引入记忆、更多工具和主动推送。
4. 成熟代码按共享依赖集合选择性同步 Management，独立回归；不复制批准文件、业务实例、trace 或凭据。

详见 [Web 影响与清理审计](research/BOT_WEB_IMPACT_AUDIT.md)、[日常测试入口](BOT_TEST_WORKFLOW.md)。

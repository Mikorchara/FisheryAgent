# BOT-3C-2B：SDK I/O 进程隔离历史设计与暂停记录

2026-10-26 更新：用户批准 BOT-CLEANUP-1，未进入生产链路的四份草稿及专用测试文件已删除。本文仅保留设计边界、未完成事项及当时的暂停证据，**不是当前可运行模块或命令说明**。[清理与验证](BOT_CLEANUP1_SDK_DRAFT_REMOVAL.md)。BOT-3C-2A 资源门禁保留；没有获得线程硬退出保证。

后续：[BOT-3C-FAST](BOT3C_FAST_QWEN_TRIAL.md)已实现独立试用入口；以下正文均为 2026-10-25 暂停时的历史快照，资格与人工验收现状见阶段总结。

日期：2026-10-25。范围仅 `Fishery_AI_Prototype/apps/`；未同步 Management，未 commit/push。

## 当时的暂停决定（历史）

用户调整优先级，计划先讨论真实 Qwen + QQ 的受控单轮实验。BOT-3C-2B **已进入实现，现已暂停**，并非完成或通过进程隔离验收。本轮不开始 BOT-3C-FAST，也不连接 QQ 或 Provider。

保留已有草稿，不回滚、覆盖或清理先前工作。为避免误启用，Adapter 构造、底层进程启动及 worker 执行入口均明确返回 `SDK_PROCESS_DEVELOPMENT_PAUSED`。没有环境变量或 CLI 开关启用该草稿；worker 命令直接退出 2，不读取启动输入、不创建 SDK、不连接网络。

## 当时的实现草稿（以下文件已删除）

| 原文件 | 当时的草稿职责 | 暂停时状态（非当前存在） |
|---|---|---|
| `apps/ai_backend/sdk_process_adapter.py` | 父进程拥有 SDK 子进程、限额、期限、取消及退出确认；复用原 Adapter 的编码与组装 | 明确禁用，未注册到 Web/QQ |
| `apps/ai_backend/sdk_process_worker.py` | 子进程内 SDK I/O、MockTransport 夹具及响应传输 | 所有执行入口拒绝 |
| `apps/ai_backend/sdk_process_protocol.py` | 版本化 JSON 帧、大小/数量边界与严格解码 | 仅纯协议基础检查通过 |
| `apps/ai_backend/sdk_process_job.py` | Windows Job 及父端拥有的子进程管理 | 未开展真实生命周期验收 |

拟定边界仍是：Agent、Tool、Monitoring、权限、Source Gate、Commit Gate 和 QQ 交付在父进程；仅 SDK I/O 在子进程。草稿没有接入现有服务，也没有提供可运行的进程隔离模式。

收尾新增 `apps/ai_backend/tests/test_sdk_process_paused.py`，验证默认/离线/授权参数均不能构造 Adapter、直接 Session 不能启动、worker 的 Python/命令行入口拒绝，以及纯 JSON 基础解码。它们**不是**成功请求、取消或硬终止测试。

## 保留不变的安全边界

- BOT-3C-2A SDK 资源租约、有限清理等待、清理失败隔离与后续请求拒绝保持原样。
- RequestHandle、Source Gate、Commit Gate、QQ Scheduler/Delivery 保护没有被放宽。
- Web 继续使用原有 Adapter；没有整体切换执行路径，也没有新增回退。
- Monitoring-only Scope 仍为 **v2 candidate**。草稿未选入执行合同，因此本轮不生成 v3 或授予真实资格。
- `/问AI` 仍为 `AI_DISABLED`；未增加真实 AI 启动参数或修改 `can_send/can_deliver`。
- 未读取真实密钥、打开现有业务实例、修改数据库/Policy/Settings 或连接外部服务。

当前线程路径的限制仍存在：不合作的底层 I/O 无法由 Python 请求线程可靠强制终止；失败门禁只会明确失败、拒绝后续执行，不等于已经杀死线程，也不保证远端停止计算或计费。

## 暂停时测试状态（历史数字）

本轮收尾专项 **31/31 通过**：暂停边界 6 项、SDK 资源门禁 17 项、QQ 资源门禁 3 项、真实 SDK + 内存 HTTP 5 项。全部离线。

完整管理回归 **816/816 Python + 116/116 Node（11 文件）通过**，Python 阶段 188.117s，总命令退出 0。与上一阶段 810 项 Python 的差异仅为本轮新增 6 项暂停/协议测试。

只读预检返回 `QQ_AI_PREFLIGHT_VALID_LIVE_BLOCKED`：`scope_matches=true`、`status=candidate`、`ai_enabled=false`、`can_execute_real=false`、`can_deliver_real=false`、`network_requests=0`，未检查凭据或打开业务实例。5 个草稿/测试 Python 文件的 AST 解析及 `git diff --check` 通过；未发现运行中的 `sdk_process_worker.py` 子进程。

当时专项命令还包含 `apps.ai_backend.tests.test_sdk_process_paused`，该模块已删除，不再提供这条失效命令作为当前操作。现行资源专项、完整回归与预检命令见 [清理报告](BOT_CLEANUP1_SDK_DRAFT_REMOVAL.md)；暂停测试的 6 项减少不代表移除了资源门禁测试。

## 暂停时未完成的设计检查（历史）

Windows 子进程成功/取消/强制退出/崩溃/断 IPC/父进程退出、Job 清理、真实 SDK 流式协议、两次模型请求的 Tool Calling、资源故障后的再准入、性能和内存测量均未完成。

当时计划在恢复前复核继承 Adapter 的无 Handle 调用路径，防止绕回原线程执行；完善真实 HTTP 请求计数、异常及清理失败优先级、重复清理和未确认退出资源的管理。暂停时通过入口拒绝阻止未完成部分进入运行链路；源码现已删除。未来若重新立项，必须重新设计和验收，当前没有可启用的进程隔离入口。

后续 BOT-3C-FAST 必须由用户另行确认范围、模型和费用、实例及数据披露、群/成员授权、Scope 与交付策略；不能通过删除现有阻塞项、关闭安全检查或修改候选资格来加速。本文仅记录暂停，不构成真实联调授权。

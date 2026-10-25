# BOT 共享模块、Web 兼容性与清理审计

2026-10-26 后续：BOT-CLEANUP-1 已按本页建议删除四个暂停草稿及专用测试，保留 SDK 资源门禁和历史设计；本页第3节记录清理前证据，不是当前文件清单。[清理与验证](../BOT_CLEANUP1_SDK_DRAFT_REMOVAL.md)。

后续状态：原 FAST 5 项失败已由 [BOT-REGRESSION-1](../BOT_REGRESSION1_FAST_STABILITY.md) 定位和最小修复；本页保留前次审计的失败数据与风险分析，当前测试结果及 Scope 以修复报告为准。

日期：2026-10-25。源码审计：`8d90d07..ddb9ecf`；该范围 `apps/ scripts/` 共 78 文件、+10435/-164 行，并非每一行都属于 BOT。四个阶段提交为 `6f2fee2`、`fb140f0`、`7322f0d`、`ddb9ecf`。本轮开始工作树为空；没有读取真实数据或凭据，没有联网。

范围外另有项目级 `pyproject.toml`：增加可选 `qq = [websockets>=15.0.1,<16]`、QQ 包发现及 examples 打包规则，排除 QQ 测试；没有给普通 Web 新增强制运行依赖。本轮未修改该配置或安装依赖。

## 1. 共享代码实际改变了什么

| 位置 / 依据 | 实际变化 | 对 Web 的判定 |
|---|---|---|
| `ai_service/service.py` 构造、`_runtime_state`、`_execute_claimed_turn` | 允许无 Knowledge；增加内部渠道授权、Fake/试用分支 | Web 有 Knowledge 的默认分支仍注册原工具、使用原凭据与 gateway_factory；仅凭代码不能证明真实网络完全无回归 |
| `ai_service/business_tools/registry.py` | 仅在实际绑定 Knowledge 时注册相关工具和历史能力 | Web 正常装配仍绑定 Knowledge；新组合不伪造来源/发布资格。未新增写工具 |
| `ai_service/contracts.py`、`channel*.py` | Prepared Turn 增加内部授权字段；独立 candidate / local_experimental | 普通 Web 入口拒绝渠道 Turn 混入；原公开结果结构保持，内部渠道结果另行投影 |
| `monitoring/repository.py` | 显式 `read_only=True`、mode=ro、query_only、authorizer；设备事件有界快照 | 默认读写仍保留；无 Schema / 规则变化。Bot 不初始化、升级或修复数据库 |
| `monitoring/service.py` 的 `events/event_cycles` | 可选 device_id；设备查询使用受限快照，单次投影共用时钟 | 无 device_id 保留旧查询路径；新范围过大时明确拒绝，不静默截断 |
| `ai_backend/openai_compatible_adapter.py`、`sdk_resources.py` | SDK bridge 租约、Task/I/O/线程退出确认、失败粘性隔离 | **真实行为变化**：清理失败覆盖成功/取消；所有同进程 Adapter 都可能拒绝后续请求 |
| `ai_backend/execution.py` | RequestHandle/Registry 保留未关闭资源，完成前校验；公开状态加 sdk_resources | Web 错误码与状态 DTO 有新增字段，前端和外部消费者应允许该字段；不能说默认错误处理完全不变 |
| `management_web/tests/test_streaming.py` 等 | 加强 Fake SDK/资源错误回归 | Web 的生产路由、页面、默认开关未因 BOT 修改；测试夹具隔离故障预算，避免故障污染其他用例 |

在上述 Git 范围未修改 `ai_backend/tool_conversation.py`、`ai_service/runtime/assistant.py`、`runtime/sources.py`、`runtime/resources/presets.json`、`management_web/app.py`。凭据路径解析、安全规则、Monitoring 领域规则和 SQLite Schema 没有为 QQ 放宽。脚本不修改这些文件或现有 Scope 指纹。

## 2. 兼容性证据与限度

**自动化可以证明的范围**：Fake Provider 的 Normal/Streaming、工具循环、Knowledge/Monitoring、HTTP、取消、清理失败优先级、来源/Commit 防线；只读数据库不改写；并发/权限撤销及未知交付不重试。具体本轮数量见 [测试记录](../BOT_TEST_WORKFLOW.md#验证记录)。

**本轮不是全绿基线**：866 项 Python 中 861 项通过，4 项错误、1 项失败，全部集中于原有 `qq_bot/tests/test_qwen_trial.py`；Node 116 项和新增脚本 13 项通过。不能把此前阶段报告的“全部通过”当作此次结果。以下用例单独复跑 5 项，仍为 4 错误 / 1 失败：

| 用例（省略 test_ 前缀） | 实际结果 |
|---|---|
| `expiry_during_qq_token_refresh_blocks_message_post`（约 500 行） | scheduler.wait(task,5) → AI_TASK_WAIT_TIMEOUT |
| `qq_success_fixed_commands_single_owner_and_hidden_model_prose`（约 248 行） | 同上 |
| `qq_unknown_delivery_never_resends_or_reinfers`（约 261 行） | 同上 |
| `second_ai_message_is_rejected_even_after_first_delivery_but_fixed_still_works`（约 341 行） | 同上 |
| `fake_gateway_run_uses_shared_owner_and_joins_all_workers`（约 402 行） | QQ POST 数 1，预期 2 |

进一步隔离诊断：没有修改生产期限、门禁或原测试。单独构造相同 Fake SDK/SQLite 任务，以额外观察等待查看结果，出现 `DELIVERED / QQ_REPLY_API_ACCEPTED`，模型请求 2，SDK active=0 / quarantined=0。一次样本准入 0.318s、总 4.083s，发生 83 次完整授权校验，校验耗时之和 5.864s、单次最大 0.190s（并发调用重叠，耗时之和不能当作关键路径总时长）。

另按失败用例原顺序先固定水质查询、再 AI，以额外 25s 观察等待查看任务（生产 90s 期限未变），得到 `FIXED_API_ACCEPTED=True / TASK_STATE=DELIVERED / AI_SECONDS=11.969 / MODEL_REQUESTS=2 / QQ_POSTS=2 / SDK_RESOURCE_ERROR=None`。这个样本直接证实 5s 等待不足以观察该次正常完成；仍需逐项验证其他失败，而不是一概认作无害抖动。

Fake Gateway 失败探针记录到 `QQ_REPLY_API_ACCEPTED → AI_ADMITTED → GATEWAY_DISCONNECTED → QQ_RUN_DURATION_REACHED → AI_GATEWAY_DISCONNECTED`；该夹具会话本来只有 5s。说明短观察窗口与重复完整校验开销值得优先调查，但**尚不能证明全部失败只有这一原因**，尤其不能据此简单删除权限复核或调高生产预算。它没有推翻用户已报告的真实成功，也不能用于声称当前所有 QQ 回归稳定。

**代码审查结论**：Web 默认仍为有 Knowledge 的原路径；渠道传入内部授权才进入新分支。Backend 未反向导入 QQ/Monitoring/Knowledge；没有循环依赖或第二套 Agent。不过 `service.py` 默认构造也导入 channel_trial，试用 Scope 又按文件散列引用 QQ 源码路径：存在部署/打包层面的耦合，未来拆包不能只复制单个 Service 文件。

**本轮未验证的运行风险**：

1. 真实 Web SDK Normal/Streaming 在 Windows 断网、SDK close 不合作和长时间运行下的表现。本轮不联网；资源失败会更保守地拒绝后续请求，需要正常关闭并重启进程，而不是清除隔离标志继续试。
2. 请求线程仍为 daemon；门禁能发现并阻止不安全成功，不能强制杀死 Python 线程，不能承诺远端停止计费。带 Handle 的正式路径受到租约保护；无 Handle 的同步 SDK 路径只检查进程健康，不计入 bridge 的 8 租约上限，不能把它描述成全 SDK 并发限额。
3. 原 Web `runtime/release_contracts.py:release_scope` 绑定模型/协议/Prompt/工具定义，未绑定 SDK 源码。QQ 试用另外绑定当前实现。原 Web 资格文件未改变，不代表新的 SDK 清理行为经过重新真实模型资格验收。

新增进程级状态为 `SDK_RESOURCES`：最多 8 个 bridge 租约，失败后粘性隔离；Registry 不裁剪资源不安全的终态 Handle。通常 Web、Bot 分进程，因此不会自动互相污染；同进程部署则共享故障域。有限清理等待现在为 2s（此前 bridge 等待为 5s），错误码可能变成 SDK_CLEANUP_FAILED / SDK_CLEANUP_TIMEOUT，属于需要认识的兼容性差异。

## 3. 暂停 SDK 子进程草稿（清理前历史）

| 文件 | 物理行数 | 运行引用 / 副作用 |
|---|---:|---|
| `ai_backend/sdk_process_adapter.py` | 334 | 仅草稿与专用测试引用；创建预算对象，不启动进程；构造/启动明确拒绝 |
| `ai_backend/sdk_process_worker.py` | 125 | 仅草稿/专用测试；导入时修改 sys.path；执行入口明确拒绝 |
| `ai_backend/sdk_process_protocol.py` | 76 | 仅草稿/专用测试使用的有界 JSON 协议函数 |
| `ai_backend/sdk_process_job.py` | 38 | Windows ctypes/Job 定义；只有实例化才创建 Job，暂停入口不走到这里 |
| `ai_backend/tests/test_sdk_process_paused.py` | 76 | 6 项暂停/协议检查，不代表进程生命周期已验收 |

`rg -n 'sdk_process_|SDK_PROCESS_DEVELOPMENT_PAUSED' apps scripts` 的生产调用引用闭包限于上述草稿；`qq_bot/tests/test_qwen_trial.py` 另有“Scope 不含草稿”的反向断言。离线导入探针在阻断 socket、Popen、Thread.start 后导入 Web Service / QQ CLI / trial，输出 `PRODUCTION_IMPORTS_DRAFT_MODULES=0`；再显式导入四份草稿，输出 `DRAFT_IMPORT_STARTS_THREADS=0`、`WORKER_IMPORT_MUTATES_SYS_PATH=True`。`pyproject.toml` 自动发现 ai_backend 包，草稿仍可能随 wheel 分发，属于维护与误读负担，并非当前网络执行依赖。

原审计建议删除这 4 个源码和 1 个专用测试；BOT-CLEANUP-1 已获批准并执行，目录和现行命令同步更新。[暂停设计与代价](../BOT3C2B_SDK_PROCESS_ISOLATION.md) 继续保留为历史，SDK 资源门禁不在删除范围内。

必须保留：`sdk_resources.py`、共享 Adapter 的资源确认、`execution.py` 的 Handle/Registry 防线、资源测试、QQ Scheduler/Commit/Delivery 门禁。草稿未参与 FAST Scope，所以未来删除不应改变 FAST 执行资格；仍需重新计算并比对指纹，不靠推测。

本轮核查 FAST Scope 为 `05a018fa50961627f22b2fbfb9e4f7fe74dd5c0ff0a9e11da38eafcf12f35cde`；计划中的实现清单加 SDK Adapter/resources/execution，与 HEAD 比对的改动文件数为 0，且 Scope 不含 `sdk_process_`。新增脚本/文档没有改变现有资格或指纹。

最小未来验证：导入/打包边界、SDK 正常/取消/不合作 I/O、Bot 试用及 Web Normal/Streaming、完整管理回归、Scope 前后比对、文档链接。避免顺带改 Agent 或重写 IPC。

## 4. 必要冗余与可简化项

| 顺序 | 建议 | 收益 / 风险 |
|---|---|---|
| 0 | 复核 BOT-REGRESSION-1 的完整基线和新 Scope，再进入下一阶段 | 后续已修复短窗口/夹具和同次复核的重复计算；保留独立时间边界，不扩大生产预算 |
| 1 | 本轮增加薄测试入口和当前状态导航；保留阶段报告 | 减少手抄审批命令，低风险；不复写审批/费用/工具逻辑 |
| 2 | BOT-CLEANUP-1 已按授权删除暂停草稿及 6 项专用测试 | 移除 649 行维护负担；历史设计与 C2A 防线保留 |
| 3 | 修复历史文档状态和失效索引 | 本轮已把 README/BUILD_RUN/ROADMAP 中已不存在的 EVENT_ACK.md 导向现存事件说明/迁移源码；旧文档在核查前已删除，没有凭空恢复其内容。阶段报告继续保留历史属性 |
| 4 | 后续考虑把试用实现指纹清单集中到渠道中立位置 | 减少 Service 与 QQ 源码布局的耦合；会影响 Scope，必须独立任务/重新审批 |
| 5 | 随 BOT-3D 明确是否保留纯 Fake candidate 的公开测试入口 | Fake 夹具仍有回归价值；不要因已完成真实验收就删掉离线安全证据 |

另有一处低风险文案债务：`ai_service/service.py:availability` 在未绑定 Knowledge 时固定描述为“offline candidate / 未开放真实发送”，未区分已批准的 channel_trial。现有真实 CLI 不用该字段决定权限，不影响审批安全；若将来给 QQ 状态页复用，应准确投影实际资格，不能直接删除门禁或把 candidate 改成 released。

准入、工具读取前、Commit 前、发送前重复查权限是必要的时间边界检查；Scope/Policy/绑定摘要与单次消费也不是可随意合并的重复状态。Scheduler 和 Delivery 各自状态区分“执行完成”和“API 接受”，不能合并为一个 success。私有配置、批准文件和回执目的不同，不建议靠共享可变配置消除文件数量。

## 5. 后续 Management 同步边界

1. 先只读比较两个仓库的 HEAD/工作树，记录 Management 的本地差异；不要从 Prototype 整目录覆盖。
2. 共享集合：Monitoring 只读选项/设备事件查询、Service 可选 Knowledge/内部渠道合同、SDK Adapter + execution + sdk_resources 及相应测试。必须作为有依赖的集合独立回归，评估新增状态 DTO 和清理错误码。
3. QQ 专用 `apps/qq_bot`、示例配置、可选 websockets 依赖及验收脚本应独立保留；不让 Web 默认启动 QQ，也不强制安装 QQ 运行依赖。
4. 不同步 `outputs/`、测试实例、OpenID 白名单、AI 启用配置、计划/审批/used 标记、真实回执、Trace、任何凭据/SQLite/Settings/Policy。Management 的品牌、启动器、正式数据路径保持自身实现。
5. FAST Scope 包含项目根和实现散列，Prototype 批准在 Management 不可复用；需要该项目自己的实例/成员批准和资格检查。此轮未同步、未修改 Management。

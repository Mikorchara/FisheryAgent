# BOT-REGRESSION-1：FAST 回归定位与最小修复

后续：2026-10-26 [BOT-CLEANUP-1](BOT_CLEANUP1_SDK_DRAFT_REMOVAL.md) 已移除未使用的进程隔离草稿和专用测试，本文保留修复时的 874 项基线；清理后数量及两个 Scope 的一致性见清理报告。

日期：2026-10-25（UTC+8）。项目为 Fishery_AI_Prototype；开始时 `main / 5641e4c`，工作树为空。本轮只修改本仓库，不访问真实实例、Provider、QQ 或密钥，不提交、不删除暂停 SDK 草稿。

## 1. 结论与根因分类

五项失败由**测试观察窗口与实际执行合同不一致、Fake Gateway 错误处理夹具、真实的重复计算开销**共同造成，没有证据表明是 SDK 资源泄漏或重复交付。

| 原失败用例（test_qwen_trial.py，省略 test_） | 原因 | 最小修复 |
|---|---|---|
| `expiry_during_qq_token_refresh_blocks_message_post` | 测试在完整 Tool Calling/交付权限复核完成前，5s 观察等待先超时，尚未到它要验证的 token 刷新/到期边界 | 等待已准入任务自己的执行期限及有界清理；仍断言过期后没有业务消息 POST |
| `qq_success_fixed_commands_single_owner_and_hidden_model_prose` | 合法任务可超过 5s，观察等待超时被误认为功能失败 | 同上；两次模型请求、两次回复（固定+AI）、正文隐藏和重复消息拒绝断言均保留 |
| `qq_unknown_delivery_never_resends_or_reinfers` | 同上，未等到送达未知分支 | 同上；仍断言 DELIVERY_UNKNOWN、一次提交且不重新推理 |
| `second_ai_message_is_rejected_even_after_first_delivery_but_fixed_still_works` | 同上，第一次任务尚未结束，第二次消息/固定指令的断言未执行 | 同上；一次批准仅一个 Turn 及固定指令独立性的断言保留 |
| `fake_gateway_run_uses_shared_owner_and_joins_all_workers` | Fake 会话只跑 5s，却承载最多 90s 的 AI Turn；`_pump` 内的测试断言还会被真实 Gateway 的异常重连分支当作断线，造成取消和少一条回复 | Fake 会话使用原 trial CLI 的 120s 会话上限，结果完成即结束；有界等待队列/任务，断言移到生产重连循环之外 |

Scheduler、Delivery、watchdog 中的准入、执行、工具读取、Source/Commit、发送前和 token 刷新后复核都继续保留。没有修改真实 90s Turn、10s 排队、285s 回复安全窗口、SDK 失败隔离、零重试或单次提交合同。

## 2. 如何复现与定位

### 2.1 普通负载与可控慢响应

本轮第一次逐项诊断，五项在轻负载下均通过，耗时约 3.2–3.9s；这与上一轮 4 错误 / 1 失败及约 12s 正常完成并不矛盾，说明原测试依赖机器运行速度。

在隔离 Fake SDK 的首个响应前增加 **6s 可取消异步等待**（仍远小于真实 90s 期限），未修改生产预算、安全检查或网络行为：

| 版本 | 五项结果 | 观察到的状态 |
|---|---|---|
| 修复前，原 5s 夹具 | 稳定复现 4 错误 / 1 失败，约 5.7–6.1s/项 | 四项等待超时时任务仍 RUNNING；Gateway 夹具提前结束并取消执行 |
| 修复后，相同 6s Fake 等待 | 5/5 通过，约 7.8–8.0s/项 | 成功任务 DELIVERED；超时送达保持 DELIVERY_UNKNOWN；到期场景没有发业务消息 |

这些诊断均输出新残留拥有线程数 0，SDK budget active=0 / quarantined=0。Fake 的6s是复现条件，不是新增的生产延迟或日常测试固定 sleep。

第一份 before-normal 探针的 scope 计数仅覆盖 trial_configuration 的调用别名，用于整体耗时对照；后续 slow 探针覆盖两处原调用别名。每次完整复核 3→1 的结论另有直接调用计数专项，不用两份计数范围不同的报告推导比例。

非敏感原始诊断保留在本仓 `outputs/test-tmp/`：

- `bot-regression1-diagnose.py`：本次专用探针，只装配已有 Fake SDK、Fake QQ 与新建临时 SQLite；不读取现有业务实例。
- `bot-regression1-before-5641e4c.json`：修复前普通样本。
- `bot-regression1-before-slow-5641e4c.json`：修复前 6s Fake 样本。
- `bot-regression1-after-normal.json`、`bot-regression1-after-slow.json`：修复后样本。
- `bot-regression1-repeated.json`：五项连续重复三轮结果。

这些文件均在 Git 忽略范围，不是批准文件、真实 Provider 回执或迁移数据，不应作为真实模型资格证据。

### 2.2 权限复核为什么很多

`QQAIJobScheduler._watch()` 在任务存续期间反复 `validate_plan()`，循环空闲间隔为 20ms、校验耗时另计；`ManagementAssistantService.validate_channel_turn()` 经渠道授权、trial.check、decision.check 等路径复核。模型请求、工具读取、Commit、Delivery 和发送前也各自检查。独立时间边界不能因次数多就删除；调用链中的嵌套复核仍可能有进一步优化空间，本轮只合并已证明相同的单次验证内部计算，不重构权限传播。

原 `validate_record()` 在同一次验证里调用 `scope()` 两次：一次比较完整 Scope，一次比较其 SHA-256；`compose_trial.validate()` 又在 `record.check()` 后重算一次相同 Scope。因此一次完整 trial 复核有 **3 次**全量 Scope 构建，重复读取源码、SDK 版本并计算摘要。

本轮修改为：

1. `validate_record()` 每次调用新建一个 Scope，同时比较内容和摘要。
2. `compose_trial.validate()` 检查当前 bindings、Policy、QQ 前置回执后，以 `record.check()` 作为最后一步；它完整检查批准字节、当前 Scope、有效期和一次性标记，不再另建重复 Scope。
3. 不跨调用缓存，不使用 TTL 或“文件大小/mtime 未变即可信”的捷径；每个时间边界和监督轮次仍重新读取/验证。

参考样本：普通成功查询用例端到端从 3.650s 降到 1.624s；任务观察等待从 2.950s 降到 1.233s。完整 trial 复核从每次 3 次 Scope 构建降为 1 次，单独 validate_record 从 2 次降为 1 次。样本用于定位开销，不是跨机器性能承诺；并发线程的耗时之和不能直接当作任务关键路径耗时。

监督线程仍会带来多次 Policy/绑定复核，这是当前安全冗余，没有改成一个全局可变权限快照。后续若进一步优化，应另行设计安全失效机制，不能将本轮局部去重扩展成跨时刻缓存。

## 3. 等待策略与超时仍可检测

仅四个成功路径集成用例使用 `wait_trial()`：从已准入任务的 `context.deadline` 计算剩余执行期限，加现有 SDK 清理 2s 和线程关闭 3s 余量。该余量只用于**测试观察**，不会延长 RequestHandle、模型请求、QQ 原消息或实际任务期限。终态一到立即返回，不固定等待 95s。

主动取消、撤权、断线、SDK 失败测试保留原有短等待。Fake Gateway 的队列观察也有界，不再无界 queue.join；其模拟 pump 记录错误、设置 stop，退出原 Gateway 后再抛出测试错误，避免被当作网络故障吞掉。

新增确定性测试验证：

- Scope 每次复核只构建一次，下一次复核仍重新构建。
- 修改 Scope 源码内容（只在 Fake 的 Path.read_bytes 返回值模拟，大小和 metadata 不变）后，下一边界立即拒绝；运行中的 SDK 也被取消。
- SDK 阻塞时解绑设备，监督复核取消任务；原 Policy 移除/撤群测试继续有效。
- bindings 检查期间批准过期，最后的批准检查拒绝执行。
- 推进注入的 Scheduler 单调时钟跨越真实任务 deadline，任务仍 EXPIRED / AI_TOTAL_TIMEOUT，SDK CLOSED、无 QQ POST。
- Event 控制的 Fake 响应未释放时，短观察等待仍抛 AI_TASK_WAIT_TIMEOUT；释放后原任务继续完成，不重复模型调用或回复。

没有通过增加真实预算、放松断言或自动重试来换取通过。

## 4. 修改范围与 Scope

| 文件 | 修改原因 |
|---|---|
| `apps/qq_bot/trial_configuration.py` | 一次验证只构建一个新鲜 Scope |
| `apps/qq_bot/trial.py` | 合并重复 Scope 检查，最终批准检查放在其他校验 I/O 之后 |
| `apps/qq_bot/tests/test_qwen_trial.py` | 四个合同期限等待、Fake Gateway 夹具、8 项失效/超时/资源回归 |
| 本文及阶段总结、审计、测试说明、文档索引/路线图 | 用本轮结果更新当前基线，保留上一轮失败为历史证据 |

共享 Backend、Agent、Monitoring、Web、SDK 资源门禁及暂停草稿均未修改。

FAST Scope 绑定实现文件，故当前实现指纹变为：

```text
5337073a2d049cdda4b65579156e87228903202acdb82e688abb4fa7a5683b54
```

Monitoring-only 基础 candidate Scope 仍为 `af2ddb61aacd36e4706b381781974d92dd031bd1e3b6ed2f650607e3bee2e23d`；`--check-ai-readiness` 通过并输出 candidate、can_execute_real=false、can_deliver_real=false。没有修改资格文件或授予 released/local_experimental。

**已有 FAST 计划、批准及 Provider 前置报告绑定旧实现，不能复用**；以后真实试验需重新生成计划、人工审批和相应 Provider 前置验证。本轮未读取、修改、删除或消费既有批准；旧记录不匹配新实现时由校验器拒绝，文件仍保留。

## 5. 验证结果

| 检查 | 结果 |
|---|---|
| 五项普通复跑 | 连续 3 轮，15/15 通过；每轮新残留拥有线程 0 |
| 五项 6s Fake 响应复现 | 修复前 4 错误 / 1 失败；修复后 5/5 通过 |
| FAST 原专项 + 新回归 | 45 项全部通过，37.299s（包含新增 8 项） |
| QQ Bot 专项 | 275 项通过，93.761s |
| Web AI Normal / Streaming 相关 | 78 项通过，18.799s |
| 完整 Python + Node | 874 Python 全部通过，216.928s；11 个 Node 文件、116 项全部通过，退出码 0 |
| 语法 / 文档 / Git | 三个改动 Python 文件语法通过；122 个本地文档链接目标存在；git diff --check 通过 |
| Scope / 默认 AI 门禁 | 基础 candidate 一致、真实入口未开放、90s / 2 请求 / 零重试保持 |

首次 Web 专项命令误选不存在的 test_ai 模块，仅造成一次测试加载错误；已使用实际 test_assistant / test_ai_boundary / test_streaming 等模块重新运行，上表记录的是修正后的结果。

## 6. SDK 草稿清理是否可开始

完整回归已通过，具备另立最小清理任务的条件：删除四个未接入的 sdk_process_* 草稿、专用暂停测试及失效索引，保留历史设计文档和 C2A 资源门禁。此轮没有清理或同步 Management。清理应再次比对引用、打包及 Scope，并重新回归，不能顺带修改 Agent 或移除失败隔离。

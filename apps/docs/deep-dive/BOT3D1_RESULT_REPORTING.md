# BOT-3D-1：QQ试用中断后的报告缺失

2026-10-26，仅Prototype。起点HEAD `2470cbd`，保留此前BOT-3D-1尚未提交的改动。本轮只读取已有脱敏报告/trace并做隔离测试；没有重新连接Qwen或QQ、读取密钥/聊天正文、打开其他业务实例、修改Management或提交Git。

## 1. 根因与结论

用户已确认收到回复后使用了Ctrl+C或关闭终端。这属于**会话中断**，不能等同正常`run-seconds`到期。

原流程存在三个缺口：

1. `trial.py --run-qq` 只在`run_qq()`正常返回后写`result.json`；`KeyboardInterrupt`分支仅打印`QWEN_TRIAL_CANCELLED`，不写报告。Gateway内部捕获中断、外层捕获中断、PowerShell直接中断native管道是不同路径。
2. `run_qq()`只在成功路径提取Scheduler结果，失败/清理异常路径会丢失此前已完成交付的状态；写报告异常随后被通用异常分支再次写入，第二次写入错误还被吞掉。
3. PowerShell把`summary.status`初始设为`STOPPED`，只有整个native调用返回才赋成功状态；中断可能跳过catch及返回值赋值、只执行finally。封装还只取最后一行JSON，没有确认`result.json`真实存在。原Fake封装夹具也没创建结果文件，却能通过“成功”测试。

离线先复现了两个失败：处理中断后`result.json`不存在、报告写入失败出现两次写尝试。修复后覆盖正常结束、中断、失败停止和交付未知。**未发现正常自动到期必然漏报告的路径**；本次已知现象与中断分支相符，不是Qwen回答或Tool Calling失败的证据。

## 2. 这次历史执行能确认什么

未修改以下任何原文件，也未补造`result.json`。

| 证据 | 可确认 | 不能据此确认 |
|---|---|---|
| `outputs/qq-bot/test-runs/test-20261025T173805Z-b3432975988646bc9e2db0643fe89e58/` | 只有plan、approval、summary；summary为STOPPED，未记录最终退出码和API接受状态 | STOPPED不是模型失败结论，也不是交付成功回执 |
| 同时间窗 `qwen-trial-8306afe0a4144e1995614fbc8d43662c.trace.jsonl` 的白名单字段 | 北京时间2026-10-26 01:38:44–01:38:48，两次模型请求→一次当前水质Tool/OK→Final，assistant completed、error_code为空；Prompt为QQ_CURRENT_EXPLANATION@1，history为空 | 此trace没有QQ HTTP接受回执，也不能单独证明最后的SDK资源关闭/会话清理状态 |
| 原Provider阶段result | QWEN_PROVIDER_TRIAL_VERIFIED、两次模型请求、EXPLANATION_CONTRACT_VALID、SDK CLOSED/线程退出/I/O关闭 | Provider阶段成功不是QQ阶段的程序交付回执 |
| 用户本轮陈述 | QQ客户端人工收到完整A/B/C回复 | 不自动把人工确认改写成机器审计记录或API响应记录 |

因此无需为“找回历史报告”重跑模型。历史Backend成功有程序证据，客户端收到有人工证据；**本次QQ程序交付最终状态没有可恢复的已落盘回执**，不能伪造。后续新产生的检查点将改善这种取证缺口。

## 3. 最小修复

### 3.1 停止路径保留结果

`TrialRuntime`保存本轮安全的终态快照和停止原因；`run_qq()`在finally、原资源关闭流程之后收集状态，失败或中断也保留此前交付结果。原API关闭仍在finally执行，不增加重试。

正常、失败和可处理的Ctrl+C统一通过`publish_result()`防覆盖写一次最终报告。写入/刷新失败明确输出`TRIAL_RESULT_WRITE_FAILED`、原操作code及`report_saved=false`，不吞错、不再次写同一报告、不补推理或补发送。已完成的Backend不会仅因退出时Ctrl+C而被重新标成模型取消。

### 3.2 提前保存非敏感交付状态

仅试用装配传入内部`receipt_sink`。Delivery Owner拿到原单次提交的Receipt后、等待剩余QQ运行时间之前，创建：

```text
本次唯一test-runs目录/
  plan.json
  approval.json
  result.delivery.json  # 单次、拒绝覆盖的交付检查点
  result.json           # 会话退出时的最终报告
  summary.json          # PowerShell安全摘要
```

检查点只包含合同/Scope/绑定摘要、原Receipt状态、API接受标志、接受时间/回复摘要、解释校验状态、SDK资源状态及请求数；没有聊天正文、模型原文、实际读数、密钥或Token。它不是Provider前置报告、最终会话报告或再次执行许可。

检查点写入失败不能撤销已经被平台接受的回复：保留真实Delivery状态，同时记录`TRIAL_DELIVERY_CHECKPOINT_FAILED`并让试用以报告错误结束，禁止重发。所有文件使用现有`write_new()`、create-new和fsync；已存在result或检查点时在执行前拒绝，不覆盖、不删除。

### 3.3 PowerShell核实落盘

`Test-QQAI.ps1`本身仍是薄入口；修复在公共helper。执行前设置RUNNING并明确`report_saved=false`。执行返回后读取真实结果文件，核对stdout终态、Scope、phase与完成标志，再复制白名单字段；正常结束只接受相应的最终试用code。只有路径或一条进度日志不算结果。

中断时finally可读取已落盘检查点，但不会创建或补造缺失的最终结果。PowerShell停止管道可能跳过脚本的显式exit，离线测试还观察到host退出码0，所以验收不能只看退出码。

## 4. 状态含义

| 状态/code | 精确含义 |
|---|---|
| QQ_STOPPED | Gateway会话已停止的进度日志，不是AI成功或最终报告 |
| QQ_REPLY_API_ACCEPTED | 程序收到QQ API接受；不等于客户端实际显示 |
| QWEN_QQ_TRIAL_STOPPED | 正常会话结束的最终code；是否交付必须另看delivery/completed |
| QQ_API_ACCEPTED_CHECK_CLIENT | 最终报告已核实、API接受，等待人工查看客户端 |
| QQ_API_ACCEPTED_SESSION_CANCELLED / SESSION_FAILED | 之前API已接受，但会话后来中断/失败；退出码非0不能抹去先前交付事实 |
| QQ_DELIVERY_UNKNOWN_NO_RETRY | 提交结果未知，不自动重发、不再推理 |
| REPORT_WRITE_FAILED / TRIAL_RESULT_WRITE_FAILED | 最终报告未确认写入，不能声称试用记录完整 |
| INTERRUPTED_REPORT_UNCONFIRMED | native管道中断且最终报告未确认 |
| INTERRUPTED_CHECKPOINT_SAVED_CHECK_CLIENT | 中断后找到检查点；只报告其中程序状态，最终result仍可能缺失 |

QQ最终报告中的`completed/api_accepted`表示已知交付事实，不表示整个会话无错误；`code`、`stop_reason`、退出码和`report_saved`表达会话/保存结果。`client_display_confirmed`继续false；用户的实际观察单独记录，不自动伪装成平台证明。

## 5. 修改文件

| 文件 | 本轮改动 |
|---|---|
| [qq_bot/trial.py](../../qq_bot/trial.py) | 统一报告持久化、停止原因/终态保留、交付检查点、写入失败状态 |
| [qq_bot/ai_delivery.py](../../qq_bot/ai_delivery.py) | 可选内部Receipt保存回调；持久化错误与真实交付状态分开 |
| [qq_bot/ai_scheduler.py](../../qq_bot/ai_scheduler.py) | 传递可选保存回调、终态保留报告错误；队列/预算/取消不变 |
| [qq_bot_test_common.ps1](../../../scripts/dev/qq_bot_test_common.ps1) | 核实结果文件、明确状态、native退出码、finally检查点摘要 |
| [test_qwen_trial.py](../../qq_bot/tests/test_qwen_trial.py) | 新增9项：Ctrl+C、到期、停止失败、未知交付、检查点/最终写失败和防覆盖 |
| [test_test_workflow.py](../../qq_bot/tests/test_test_workflow.py) | 新增5项；修正旧Fake夹具真正生成报告，验证缺文件/进度误判/文件不匹配/取消/管道中断 |

保留既有权限交集、费用与请求预算、Scope检查、SDK租约及失败隔离、Source/Commit、去重与单次提交。没有修改SDK Adapter、Agent循环、Monitoring规则或Schema、Web生产代码和实例。

## 6. 测试与指纹

本轮测试全为合成SQLite、Fake SDK/Gateway及本机离线故障注入。实际走通SDK/Gateway的新CLI集成用例均为两次内存Provider请求、一次Fake QQ提交；纯退出/拒绝用例不执行模型。中断/保存失败均未增加请求，拥有的worker关闭后无新增残留。

| 检查 | 结果 |
|---|---|
| 修复前定向复现 | 2项失败：中断不保存、写入失败重试2次 |
| 新停止/持久化7项 + PowerShell18项 | 25项通过，38.553s |
| 后补PowerShell管道中断/检查点测试 | 1项通过；捕捉到host可为退出码0但摘要必须否认成功 |
| Bot全部 | 308项通过，117.493s |
| 完整管理Python与Node | 901 Python全部通过（264.416s）；11个Node文件 / 116项全部通过（1.453s）；总退出码0 |
| 静态核查 | 5个本轮Python文件语法通过；135处本地链接目标存在；`git diff --check`通过；candidate预检仍LIVE_BLOCKED |

基础v3 candidate保持`2d89b74fe451f793c09e21fff90dc624d9fd2ee34a02c393284f2e61066350be`，仍默认禁用真实入口。FAST源码指纹从`9e37f1e7580d3016bf11351c0c64eb478b4784e11ff11fc5409c8ca6fa116b28`变为`6ad00ee864c60c6e729980e7b7795cf2e8e4fba571770c675cbae2ea7d23f252`，原批准及Provider回执保留为历史证据，不能授权新实现；未修改资格或批准。

本轮审计/测试记录位于`outputs/test-tmp/bot3d1-reporting-20261025T174650Z-7b0c474d/`，不进Git。已核对11份相关历史文件及188份受保护业务源码，前后摘要相同；进程隔离草稿仍不存在，HEAD保持`2470cbd`，所有本轮改动未提交。先前BOT-3D-1未提交成果保留。

## 7. 后续使用与剩余边界

无需重跑本次历史试用，也不要修改used标记或补写官方成功回执。后续获得独立授权的新试用，优先等待原`run-seconds`自动结束，确认`result.json`存在、`summary.json`中`report_saved=true`及交付字段，再手工查看客户端。

Ctrl+C若到达Python并允许finally完成，会保存中断报告；PowerShell管道被直接停止、关窗、强杀或掉电仍不能保证最终报告写完。检查点是在交付返回后及时保存，平台接受与本地落盘之间仍有很小的中断窗口；不承诺任何强制结束都能留下检查点。已存在检查点可提供程序交付证据，不能据客户端可见或Gateway stopped反推API已确认。

本轮没有真实联网复验Windows控制台快捷键、Qwen或QQ端到端行为。新的真实试用须另行审批；本修复不授权自动重跑。

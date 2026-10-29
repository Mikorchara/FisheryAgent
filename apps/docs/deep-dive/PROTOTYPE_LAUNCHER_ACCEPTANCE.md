# Prototype 两/三终端启动整理

> 后续日常数据收尾已取代下方的初版默认：统一使用 `apps/data`，从原日常数据非覆盖复制，旧目录保留；Web Assistant 默认启用，仍可 `-NoAssistant` 关闭。当前命令和复制边界见 [BUILD_RUN](../BUILD_RUN.md)。下文保留初版实施依据与隔离验证记录。

## 日常数据统一与授权界面收尾（2026-10-29）

用户选择以原日常监测、知识和偏好为主，复制到新 `apps/data`；未混入 `launcher-demo-instance` 或 `bot2c-instance`。Monitoring/Knowledge 均保持 Schema v2。1440 个批次、720 条历史、3 条事件、2 条操作记录及32条知识记录的表计数、Schema摘要、逻辑摘要和外键检查一致。来源文件不修改，旧日志留在原位置；设置和两份 Tool Policy 按字节复制，不重新授权，不读取/迁移私有凭据。详细非敏感校验凭证在本机 `apps/data/data-preparation.json`。

默认路径解析、普通 Web、`run_local.ps1` 和双/三终端均使用同一日常目录。QQ 新生成 `outputs/qq-daily-config`，只更换 Monitoring 引用，保留原群/成员/AI/Policy配置引用；新实例 ID 为 `prototype-daily`，必须按本次绑定重新审批，不导入旧批准或余额。

原启动器强制 `assistant=False` 是设置/Tool不可读取的原因。现在默认沿用原 `run_local` 的 Assistant、三工具和 Normal/Streaming 试用开关；`-NoAssistant` 仍可关闭。没有替用户勾选工具，模型发送、来源和 SDK 门禁不变。Tool选择改为38px紧凑行，复选框15px；390px窄屏、浅色与深蓝主题均可操作。

验证：新增日常数据合成复制测试覆盖不覆盖、不补残库、损坏拒绝、失败不发布、来源与配置完整性；已有启动、权限、保存与网络零调用断言保留。所有自动化仅使用临时合成数据，不连接 QQ/Qwen。当前日常入口见 BUILD_RUN；下方均为初版历史记录。

最终管理独立回归：1241 Python、121 Node 全通过。原同mtime绑定变更测试存在原地重写JSON与监督线程的竞态；仅将合成测试夹具改为完整文件原子替换，保留同mtime、同长度及拒绝变更的原断言，重复10次通过，未修改Bot业务校验。Hybrid候选Scope记录与原脚本保持一致。相关测试日志与合成界面截图在本机 `outputs/ui-theme-review`，不包含真实密钥或聊天正文。

2026-10-29，Prototype `main / dcb70a2`，开始时工作树干净。仅修改 Prototype 的启动脚本、测试和文档，没有同步或修改 Management，没有修改旧 `src/fishery_ai`。

## 1. 实际能力

- `启动演示系统.cmd`：Web + Simulator，交互选择七种场景，自动打开网页。
- `启动QQ演示系统.cmd`：再增加独立 QQ Hybrid 控制台；使用原 `apps.qq_bot.hybrid_trial_cli`，必须重新输入本次 `APPROVE HYBRID`，无自动批准。
- `Start-PrototypeStack.ps1`：检查、非交互场景、自定义实例、独立 Bot；`Stop-PrototypeStack.ps1` 只停止本次目录中的所有服务或仅 Bot。
- 原 `run_local.ps1` 默认行为保留，新增可选可见窗口/菜单/浏览器参数；原 `Test-QQHybrid.ps1` 及其他 BOT 实验脚本不变。

新入口默认关闭 Web AI，避免依赖旧知识内容或在演示时装配额外模型能力；QQ 仍在原许可、预算与资源门禁下运行。

## 2. 为什么新建演示实例

本次只读核对了已有 QQ request 及其 Monitoring 路径元数据：它绑定 `outputs/bot2c-instance`，有 Monitoring 库，但没有 Knowledge 库。Web 显式完整实例启动需要两个库，因此不能直接把它当三终端实例，也不能悄悄给旧实例补库。

CMD 入口显式传 `-PrepareDemo`：只有全新 `outputs/launcher-demo-instance` 才初始化空 Monitoring v2、空 Knowledge 和必要目录，并写 Prototype 专属标记。已有根目录不完整、损坏或无标记时拒绝，不删除、覆盖、补库或迁移。

首次三终端另建 `outputs/launcher-qq-config`：保留原 access/AI/Policy 路径及已选身份，仅创建指向新实例的 Monitoring 配置和 request。不复制凭据、数据库、批准、used、账本或聊天历史。新绑定 ID 为 `prototype-launcher`，需要原 Hybrid 流程为本次进程批准。

本轮测试在新建临时合成目录中执行；未初始化上述实际默认演示目录，留给用户首次启动。原 `bot2c-instance`、现有配置和历史批准没有写入。

## 3. 安全与兼容边界

- `-Check` 只检查元数据、原 Hybrid Scope/Policy 与本机端口，不打开数据库、读取密钥、连接 QQ/Qwen或创建批准。首次实例未准备时明确返回 `prepare_required=true`；摘要标记为原配置模板，不假称新实例已经可用。
- 运行仅接受本仓库 `outputs` 下明确指定的实例；不从 Management 或 `%LOCALAPPDATA%/FisheryManagement` 自动寻找数据。
- 仍使用原 local_session 的 Web/Simulator 命令和临时上报 Token，未复制 HTTP 接入或 Agent 执行逻辑。
- Windows Job 辅助来自已验证的 Management 通用进程代码，使用独立 Prototype 命名；不存在跨项目运行时导入。
- 新入口对同实例和同测试群加独占运行锁。原独立实验 CLI 不共享这层启动器锁，不能同时另开同群 Bot；不声称所有历史入口都受新锁保护。
- 新控制台加入本次 Job 后才启动业务。Bot 关闭/崩溃不结束 Web/Simulator；Web/Simulator 配对停止后回收本次 Bot。没有自动重启或消息重放。
- 停止时通过本次 nonce 的控制文件发出请求，Bot 工作进程协作中断原 CLI，由其取消任务、关闭资源、保存报告。超过有界等待才终止本次拥有的 Job，不搜索/终止其他 Python 进程。
- Bot `RUNNING` 状态仅代表控制台工作进程已启动，真实连接以原 CLI 的 `QQ_GATEWAY_READY` 为准。创建窗口不等于三个服务已经业务就绪。
- 每个服务状态文件含实际 Python PID 与退出码。Web/Simulator 有日志；Bot 沿用原报告与检查点，不把其标准输出再复制一份到普通启动日志。
- 强制退出或不合作 SDK 线程可能导致最后报告不完整；日志明确保留强制终止状态。不保证本地取消会停止远端计算或计费。

## 4. Scope 与资格

本轮未改 Prompt、Tool、Agent 循环、SDK Adapter、RunConsent 或旧审批脚本。Hybrid Scope 修改前后相同：

`afa55f3e7cdb37762d87c57f30986e5ae245f1a5d53e5d6636a74498f2f1b340`

未编辑 candidate、资格记录、旧批准、used 或 Provider 回执。Scope 不变不等于旧批准可以重复使用：新进程、新实例绑定仍必须按原合同重新批准。

## 5. 验证方法与中间问题

离线测试覆盖新实例初始化/拒绝覆盖、旧实例字节保持、模板元数据引用、Check 禁止 SQLite/凭据/外网、原 Hybrid 拒批零调用、七场景映射、相对路径、BOM、旧非交互入口及实际 Windows 三控制台。

进程测试使用新建合成库和注入的 Fake Bot，覆盖选择前不产生新观测、无效输入、场景选择、0取消、独立停止 Bot、Bot 崩溃后持续上报，以及占用端口不影响外部监听。Fake 替换仅存在于测试代码，不是产品自动批准/联网开关。

中间问题：

1. 首轮复用了 Bot 测试夹具的全网络阻断，连本机端口探测也被拒绝；测试夹具改为只允许该检查所需的回环探测，继续拒绝外网。
2. 新 Bot 工作进程可能继承忽略 SIGINT 的控制台状态，协作停止未触发。仅在该工作进程安装 Python 标准中断处理，保留原 CLI 的取消与资源关闭逻辑；单独回归已验证退出。

专项日志位于 `outputs/test-tmp/prototype-launcher-*.log`，最初失败日志保留用于区分修复过程。测试结束只回收本次拥有的进程，不清理任何既有实验数据。

最终结果：

| 检查 | 结果 |
|---|---|
| 新启动器、原 local_session、实例、Simulator、Hybrid 及 PowerShell 工作流相关 Python 回归 | 119/119，206.063秒；日志 `prototype-launcher-regression-final.log` |
| 原前端 Node 回归 | 116/116；日志 `prototype-launcher-node.log` |
| Windows 协作停止单独复测 | 1/1；日志 `prototype-stop-recheck.log` |
| 新文档文件链接、代码语法、PowerShell BOM、git diff --check | 通过 |
| Hybrid Scope 前后比较 | 相同，未刷新或提升资格 |

本次运行的是相关 Python 集合，不冒称整个旧实验项目的全量回归。没有真实 QQ/Qwen 联网验证。

## 6. 文件入口

- [日常启动指南](../BUILD_RUN.md)
- [详细运行与阶段参考](PROTOTYPE_RUN_REFERENCE.md)：原材料迁移保留，旧锚点链接同步指向新位置。
- [编排](../../../scripts/dev/prototype_stack.py)、[控制台](../../../scripts/dev/prototype_console.py)
- [新启动专项](../../management_web/tests/test_prototype_stack.py)

真实验收由用户另行运行：选择场景、在 Bot 窗口批准、核对同实例当前水质与来源、观察实际 QQ 回复，再正常停止并检查 `bot-run/result.json`。离线通过不等于本次已经连接过真实模型或平台。

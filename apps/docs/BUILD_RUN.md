# Prototype 启动指南

在 **Fishery_AI_Prototype 根目录**打开 PowerShell。与 Management 的操作习惯一致，但使用 Prototype 自己的数据、私有凭据和原 Hybrid 审批。

网页默认保留浅色外观。右上角的「浅色主题／深蓝主题」按钮可切换深蓝科技风格，刷新后记住本浏览器的选择；窄屏显示同一按钮的图标。仅保存外观偏好，不切换数据实例，也不影响 AI、QQ 或事件状态。

新增设备联调时，见 [场景说明与首次真实接入方案](deep-dive/DEVICE_INTEGRATION.md)：原完整模拟默认不变；模式2仅模拟水质。首次真实接入需显式绑定报告目录，并另启接收器，不能只在菜单选2。

## 1. 两个日常入口

**两个终端：Simulator + Web**

```powershell
.\scripts\dev\启动演示系统.cmd
```

**三个终端：Simulator + Web + QQ Hybrid Bot**

```powershell
.\scripts\dev\启动QQ演示系统.cmd
```

二选一，不重复启动同一实例。两种入口都在 **Simulator 窗口选场景**，并打开 http://127.0.0.1:8766 。Enter 默认正常；输入 `0` 取消，停止本次整组服务；首个完整窗口约10秒。

| 输入 | 场景 | 非交互参数 |
|---|---|---|
| 1 | 正常水质 | `normal` |
| 2 | 低溶解氧 | `low_oxygen` |
| 3 | 疑似疾病信号 | `suspected_disease` |
| 4 | 摄食减少 | `reduced_feeding` |
| 5 | 复合异常 | `combined_anomaly` |
| 6 | 设备离线 | `device_offline` |
| 7 | 溶解氧快速下降后逐步回升 | `oxygen_drop_recovery` |

三终端还需在 **Bot 窗口**核对本次实例、群/成员摘要、模型与预算，再输入显示的完整 `APPROVE HYBRID <摘要>`；没有自动审批。模型、QQ 网络和实验性 General 发布仍由原 Hybrid 入口管理。默认最多30分钟、5个付费 Turn，总预算8.02元；预算为保守预留，不是最终账单。普通自然语言可能收费。

## 2. 日常数据只用一份

两/三终端入口、`run_local.ps1` 和默认 Web 启动统一使用 **`apps/data`**：

- `monitoring.sqlite3`：监测历史、事件及已有人工记录。
- `knowledge.sqlite3`：原日常知识库。
- `settings.json`、`tool-policies/`：原偏好与 Tool 选择；`logs/` 保存此后运行日志。
- QQ 配置引用：`outputs/qq-daily-config/request.json`；监测也指向同一 `apps/data`。配置与报告不是另一份业务数据库。

首次显式准备会将原 `outputs/management_web/monitoring.sqlite3`、`apps/knowledge_data/knowledge.sqlite3`、偏好及两份 Tool Policy **复制到全新的 `apps/data`**，校验记录数、Schema、外键及逻辑摘要；不改 Schema、不删除或覆盖来源。只剩部分旧文件时拒绝，不创建空库替代。全新安装且完全没有旧数据时才初始化空库。

`outputs/launcher-demo-instance`、`bot2c-instance` 和原数据文件继续保留作历史副本，不混入日常库。自动测试仍使用临时合成实例。密钥继续留在原私有 Store，不复制到 `apps/data`。

两种入口默认启用 Web Assistant、Normal/Streaming、多轮与原三工具本地试用开关；Tool 仍需在设置中授权，实际发送仍需确认，不因启动自动请求模型。只看监测可给 `Start-PrototypeStack.ps1` 加 `-NoAssistant`。QQ 继续使用原独立审批，不自动继承 Web 发送权限。

**已有目录缺库、损坏、无标记或引用不一致会拒绝，不补库、不覆盖。** 更换日常实例绑定后需重新审批 QQ，不复用旧批准、used 或余额。若 QQ 模板未配置，按[原 Hybrid 说明](deep-dive/BOT3G_FINAL_HYBRID_QQ_TRIAL.md)准备。

## 3. 检查、指定场景与停止

**离线检查：不打开数据库、不读取密钥、不连接 QQ/Qwen，也不创建实例或批准。** 可能检查本机端口是否空闲：

```powershell
.\scripts\dev\Start-PrototypeStack.ps1 -WithBot -Check
```

首次会显示 `prepare_required=true`，此时 summary 是原配置模板检查；运行入口首次准备完成后才产生新实例绑定与原 Hybrid 审批。

不显示菜单，直接使用低氧场景：

```powershell
.\scripts\dev\Start-PrototypeStack.ps1 -PrepareDemo -WithBot -Scenario low_oxygen -OpenBrowser
```

需要菜单则增加 `-InteractiveScenario`。端口可加 `-Port 8767`；不加 `-WithBot` 时只启动 Web+Simulator。显式使用其他已初始化隔离实例时可传 `-DataRoot`，或用 `-RequestFile` 指定已有完整实例的 QQ request；这两种情况不使用 `-PrepareDemo`，也不自动建库。仅 Bot 可增加 `-BotOnly -WithBot`。

**展示本地视频：**在启动命令增加 `-DemoVideo .\sample.mp4`，进入网页「视频监控」页：

```powershell
.\scripts\dev\Start-PrototypeStack.ps1 -PrepareDemo -InteractiveScenario -OpenBrowser -DemoVideo .\sample.mp4
```

这是两终端；需要 QQ 第三终端时加 `-WithBot`，仍须原人工审批。只看监测可加 `-NoAssistant`。先检查参数可用 `Start-PrototypeStack.ps1 -DemoVideo .\sample.mp4 -Check`，不会启动服务。

录像通过本机同源 HTTP 播放，默认静音循环，可暂停/拖动；统计刷新不重建播放器。仅支持显式 MP4，推荐 H.264/AAC；更换文件后重启。当前 sample.mp4 为60秒1080p H.264/AAC，保留在本机并被 Git 忽略。不加参数保留原无视频状态。录像水印不是当前观测时间；播放不产生检测统计、事件或摄像头在线状态，不代表实时推流接入已完成。见[边界与验证](deep-dive/LOCAL_VIDEO_DEMO.md)。

**停止整组：**在最初启动的 PowerShell 按 Ctrl+C。关闭 Web 或 Simulator 任一窗口也会结束本次配对并回收本次 Bot；关闭或停止 Bot 不结束 Web/Simulator。

另开终端也可用 `Stop-PrototypeStack.ps1 -RunDirectory '本次输出的完整目录'`；仅停 Bot 再加 `-BotOnly`。目录以 `PROTOTYPE_STACK_STARTING` 输出为准，位于 `outputs/prototype-stack/stack-<随机ID>/`。

Web/Simulator 日志和各服务 PID/状态位于该目录；Bot 使用原 CLI 的 `bot-run/result.json` 与交付检查点，不额外把聊天正文复制到启动器日志。优先正常停止；SDK 不合作或强制关窗时，最终报告可能不完整，有界等待后只终止本次拥有的 Job，不自动重启或重发。

## 4. 旧入口仍可用

`run_local.ps1 -Scenario ...` 默认使用 `apps/data`。独立 Hybrid 实验如需同一主数据，使用 `Test-QQHybrid.ps1 -RequestFile .\outputs\qq-daily-config\request.json -Check`，实际执行换成 `-Run`，仍需人工审批。不要与三终端同时运行同一群的 Bot。`run_local.ps1` 可额外加 `-ShowTerminals -InteractiveScenario -OpenBrowser`，默认仍不等待菜单输入。历史研究脚本、旧 request 或手动指定的 `-DataRoot` 不自动改写；它们的原试用合同和数据引用保持独立。

- [运行维护与历史实验入口](deep-dive/PROTOTYPE_RUN_REFERENCE.md)
- [新增启动器的边界与验收](deep-dive/PROTOTYPE_LAUNCHER_ACCEPTANCE.md)

新启动器默认使用本项目 `apps/data`，也支持明确选择 `outputs` 下的测试实例；不访问 `%LOCALAPPDATA%/FisheryManagement` 或 Management 项目。不修改 Agent、Tool、审批和 SDK 资源合同。Scope 或绑定变化时仍由原检查拒绝，不编辑旧批准解决。

# Prototype 启动指南

在 **Fishery_AI_Prototype 根目录**打开 PowerShell。与 Management 的操作习惯一致，但使用 Prototype 自己的数据、私有凭据和原 Hybrid 审批。

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

## 2. 首次运行会准备什么

新入口的 `-PrepareDemo` 明确允许**只在全新目录**建立空 Monitoring v2、空 Knowledge 和必要目录，不复制知识、旧监测数据或密钥：

- 演示实例：`outputs/launcher-demo-instance`，两/三终端共用。
- QQ 实例引用：`outputs/launcher-qq-config/request.json`；仅首次三终端准备时生成。
- 现有 QQ 模板：`outputs/qq-bot/conversation.request.json`。复用其 access、AI 和 Policy 文件引用与已选身份，新 request 只将 Monitoring 指向新演示实例。

现有 `bot2c-instance` 不受修改；该实例只有 Monitoring、没有 Web 所需 Knowledge，所以不直接拿它当完整三终端实例。新配置与绑定需要本次重新审批，不复用旧批准、used 或余额。

**已有目录缺库、损坏、无标记或引用不一致会拒绝，不补库、不覆盖。** 若此前没有完成 QQ 模板配置，三终端会先报错；按[原 Hybrid 说明](deep-dive/BOT3G_FINAL_HYBRID_QQ_TRIAL.md)准备，不从 Management 自动取配置或凭据。

这两个新入口默认关闭 Web AI；QQ AI 可在独立审批后使用。需要原 Web AI/Knowledge 实验时，继续使用[原启动与配置说明](deep-dive/PROTOTYPE_RUN_REFERENCE.md)。空 Knowledge 不等于已导入原知识内容。

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

**停止整组：**在最初启动的 PowerShell 按 Ctrl+C。关闭 Web 或 Simulator 任一窗口也会结束本次配对并回收本次 Bot；关闭或停止 Bot 不结束 Web/Simulator。

另开终端也可用 `Stop-PrototypeStack.ps1 -RunDirectory '本次输出的完整目录'`；仅停 Bot 再加 `-BotOnly`。目录以 `PROTOTYPE_STACK_STARTING` 输出为准，位于 `outputs/prototype-stack/stack-<随机ID>/`。

Web/Simulator 日志和各服务 PID/状态位于该目录；Bot 使用原 CLI 的 `bot-run/result.json` 与交付检查点，不额外把聊天正文复制到启动器日志。优先正常停止；SDK 不合作或强制关窗时，最终报告可能不完整，有界等待后只终止本次拥有的 Job，不自动重启或重发。

## 4. 旧入口仍可用

`run_local.ps1 -Scenario ...`、`Test-QQHybrid.ps1 -Check/-Run` 保持原默认含义；不要与新三终端同时运行同一群的 Bot。旧 `run_local.ps1` 可额外加 `-ShowTerminals -InteractiveScenario -OpenBrowser`，默认仍不等待菜单输入。

- [运行维护与历史实验入口](deep-dive/PROTOTYPE_RUN_REFERENCE.md)
- [新增启动器的边界与验收](deep-dive/PROTOTYPE_LAUNCHER_ACCEPTANCE.md)

新启动器仅操作本项目 `outputs` 下明确选择的隔离实例，不访问正式 `%LOCALAPPDATA%/FisheryManagement` 或 Management 项目；不修改 Agent、Tool、Scope、审批和 SDK 资源合同。Scope 变化时仍由原检查拒绝，不通过初始化或编辑旧批准解决。

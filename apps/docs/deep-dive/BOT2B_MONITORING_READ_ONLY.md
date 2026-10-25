# BOT-2B：QQ Bot 指定 Monitoring 实例只读查询

实施日期：2026-10-25。项目：`D:\CodexProject\Fishery_AI_Prototype`，起始 `main@fb140f0`。

本轮只使用新建的隔离合成 SQLite、Fake QQ 请求及本机模拟 Gateway 回归；未访问既有业务实例、真实凭据、QQ、Provider 或 NPU。没有修改 Management，也没有提交或推送。本轮完成代码和离线验证，**真实实例接入仍须用户单独批准和人工验收**。

## 1. 能力与调用链

```text
本机 source JSON：固定一个绝对数据根 + 批准的设备 ID
本机 access JSON：App / 群 / 成员 / 设备 / 查询能力
                         ↓ 装配时交叉验证
QQ Gateway → 原 Adapter 权限 / 去重 / 限流 / 并发门禁
  → ReadOnlyQueries → InstanceMonitoring（固定实例、设备白名单）
    → MonitoringService.capture_water / query_water_history / event_cycles(device_id=...)
      → MonitoringRepository(read_only=True) → SQLite mode=ro + query_only
```

没有新增 HTTP 接口、第二套 Agent、数据库 Schema 或规则。现有 Gateway、网络 opt-in、超时、重连、队列及纯文本输出限制不变。

| 模式 | 数据访问 | 能力 |
|---|---|---|
| `--help-only` | 不打开业务库 | 帮助 |
| `--fictional-data` | 临时新建、退出清理的虚构库 | 原水质 / 历史 / 事件 / 虚构 Knowledge |
| `--monitoring-config FILE` | 只读打开用户明确指定的数据根中的 `monitoring.sqlite3` | 当前水质、10/30/60 分钟历史、当前异常 |

三种数据模式互斥。指定实例模式不装配 Knowledge、不调用 LLM；即使 access JSON 包含 `knowledge`，也在装配时去除，并在命令层再次拒绝。AI 始终返回 `AI_DISABLED`。不能 ACK、人工结束、删除、修改规则或配置。

**实例查询不等于真实传感器接入。** 当前 Monitoring 合同仍为 Simulator；读取持久化数据后仍显示 `SIMULATOR`，不能改标成硬件实测。只查询原记录，不更新新鲜度、不重新采样。

## 2. Repository 防写与兼容

- 新增 `read_only=True`，隐含 `require_existing=True`。不创建父目录、不建库、不初始化、不迁移、不修复。
- 每次操作新建短连接：SQLite URI `mode=ro`、`PRAGMA query_only=ON`、外键检查开启。
- Authorizer 进一步拒绝写 SQL、DDL、ATTACH/DETACH、切换 journal、关闭 query_only 和写 PRAGMA。即使调用者拿到连接，也不能借另一个附加库绕过防写。
- v1 明确报 `MONITORING_SCHEMA_UPGRADE_REQUIRED`；空库、未知版本、缺表和外键异常拒绝。新源装配额外执行有界 `integrity_check`。
- 原 Repository 默认读写行为及网页写入用例保留；没有修改 Management 仓库。
- 不使用 `immutable=1`：并发写入库必须看到新提交和 WAL。SQLite 可能需要已有 WAL/SHM 的访问，或创建/更新 WAL 协调侧文件；只读承诺针对业务数据及 Schema，不承诺文件系统零元数据变化。权限不足或热 journal 需要恢复时直接失败，不修改 ACL/journal、不降级成读写。
- 正式实例本轮没有打开。只读/读写兼容证据来自临时库的字节一致、Schema 版本、逻辑读取及并发测试。

## 3. 显式配置与路径边界

模板：[monitoring.example.json](../../qq_bot/examples/monitoring.example.json)。模板占位符故意不能通过检查；必须由用户填写获批路径和设备。

```json
{
  "schema_version": 1,
  "instance_id": "approved-monitoring",
  "data_root": "D:/APPROVED/INSTANCE",
  "devices": ["approved-device-id"]
}
```

上面是格式示例，不表示这个路径存在或已批准。`data_root` 是实例目录，不是数据库文件；真实文件路径统一由 `ManagementPaths.resolve(data_root=...)` 得出。只使用其 Monitoring 路径，不检查或打开 Knowledge、Settings、Policy、Credential 或 Trace。

- 配置严格校验固定字段、版本、重复键、字节上限、设备 ID 和去重；最多 16 个批准设备。
- 所有 access 群的绑定设备必须位于 source 白名单；`devices` 不能替代群与成员白名单。
- 数据根必须绝对路径，拒绝 `..`、UNC；Windows 拒绝非固定本地盘，包括映射网络盘。
- 打开前和每次查询前检查文件、祖先目录和 SQLite sidecar 的链接 / junction / hardlink 风险；拒绝空文件、路径替换，不自动重新绑定另一个文件。
- 无默认工作区、`--user-data` 或正式目录回退。群消息不能给出路径、改变实例或选择其他设备。修改绑定后需退出并重新启动。
- 本机配置文件由有权限的操作者管理；这不是抵御本机恶意管理员或文件检查与打开之间竞态的完整隔离机制。不得把普通可读业务目录当作 Credential Store，也不修改原凭据安全规则。

## 4. 查询语义和预算

当前水质复用 `capture_water` 和现有 Tool 事实投影，保留来源、观测时间、单位、各指标质量、新鲜度和连接状态。缺测不补零；过期或离线的留存值不能作为当前正常的证据。缺少某通道的新报文不会刷新该通道原观测时间。

历史复用原 Service 的时间窗口汇总、覆盖与会话边界逻辑：10/30/60 分钟，最多 720 行，每行 8 KiB，结果最多 24 KiB。输出的是可靠窗口均值的范围，不是原始采样极值；留存完整性仍为 UNKNOWN。

事件使用参数化 `WHERE device_id=?`，**先限定设备，再读取完整留存范围并按周期整合**，不先截取最近五条。事件及当前两通道证据在同一读事务快照内读取，再复用 EventService、`project_families`、`manual_end.project`、`summarize_cycles`。读取投影不会写回规则恢复状态。

| 预算 | 固定限制与超限行为 |
|---|---|
| 只读 SQLite 连接 | 锁等待 250ms；进度检查每 1000 条 VM 指令；每连接最多 200 万指令或约 2s SQL 执行预算 |
| SQLite 单值 | 256 KiB；超过由 SQLite 拒绝 |
| 设备事件 | 最多 256 条完整留存原记录；多读一条用于判定超限，超限整次失败 |
| 事件 payload | 每条最多 64 KiB、合计最多 2 MiB；同一存储周期或旧记录推断组最多 16 个成员，防止关联投影膨胀 |
| 当前事件证据 | 单通道 payload 最多 64 KiB；仅水质 / 视觉 |
| 群回复 | 最多展示 5 个未结束周期；原 Adapter 纯文本最多 1600 字符，超出截断 |

SQL 预算不是全进程绝对墙钟保证；本地文件 I/O 与 Python 投影另有开销。预算为实验保守上限，不改变存储留存配置或 Schema。存储事件超过 256 条时会报 `EVENT_QUERY_LIMIT`，**不会自动删历史、只取部分事件或宣称没有异常**。大实例应先讨论安全的索引/查询优化，不能通过清理真实数据规避。

当前异常区分活动、恢复观察、未知；视觉仍为连续三个可靠 CLEAR。规则已恢复和人工结束周期不列入未结束提醒，但人工结束数量及“人工结束不代表规则恢复”会明确说明。没有事件也不能据此推定视觉正常；水质缺少可靠证据时显示未知。

设备快照不扫描全库 ACK/人工确认表，Bot 不提供确认历史查询或写入权限；ACK 审计仍由原网页维护。默认 Web `events()` / `event_cycles()` 的完整人工状态投影保持不变。

## 5. 真实实例人工接入步骤（待单独批准）

**以下命令本轮没有对现有实例执行。不要直接使用正式/演示默认目录；先确认用户批准的实例、设备、群和成员。**

1. 用户确认可以向指定 QQ 测试群披露该设备的监测数据。独立批准实例绝对路径；确认 Schema v2、当前写入器和 WAL 访问条件。v1 需另立显式维护任务，不在 Bot 中迁移。
2. 在 Git 忽略的本地目录准备 source JSON，例如 `outputs/qq-bot-monitoring.local.json`；另准备原 BOT-1B access JSON，例如 `outputs/qq-bot-access.local.json`。不要把群 OpenID、业务路径或密钥作为群消息输入。source JSON 不含密钥。
3. 先做纯配置核对：不打开所指实例、不访问凭据和 QQ。

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --check-config --access-file '.\outputs\qq-bot-access.local.json' --monitoring-config '.\outputs\qq-bot-monitoring.local.json'
```

4. 获批后，显式只读预检实例，不访问凭据和 QQ；预期 `QQ_MONITORING_READ_ONLY_READY`。只显示安全状态与批准设备数，不打印路径或业务内容。

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --check-monitoring --access-file '.\outputs\qq-bot-access.local.json' --monitoring-config '.\outputs\qq-bot-monitoring.local.json'
```

5. 另外获准 QQ 联网后，使用已经按 BOT-1B 安全保存的 QQ 凭据启动。没有凭据时按原文档在本机隐藏录入，不在聊天或 source JSON 中填写。

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --connect --access-file '.\outputs\qq-bot-access.local.json' --monitoring-config '.\outputs\qq-bot-monitoring.local.json' --confirm-qq-network --run-seconds 600
```

6. 白名单成员在批准群 @机器人，依次发 `help`、`/当前水质`、`/历史水质 10`、`/历史水质 30`、`/历史水质 60`、`/当前异常`。应看到固定实例别名、正确设备、SIMULATOR、原观测时间及质量；与本机同一时刻的 Service/Web 对照，过期/离线不得显示正常。
7. 检查 `/知识 ...` 被拒、`/问AI ...` 为 AI_DISABLED；未知成员/群、附加其他设备 ID、ACK/删除/人工结束命令均不能执行业务访问。不要为验收打开未知群权限。
8. Ctrl+C 停止；只关闭 Bot 自己的连接，不停止 Monitoring 写入器、不恢复数据库、不清理业务数据。对实时写入库不要要求文件哈希静止：应依据写入器基线和合成测试证明 Bot 无写路径。

原非实例命令 `--connect --fictional-data --confirm-qq-network ...` 和 `--offline-demo` 保留。本轮不实施主动推送。

## 6. 故障说明与已知限制

| 安全错误码 | 操作建议 |
|---|---|
| `INVALID_MONITORING_CONFIG` | 检查严格字段、占位符、绝对路径与设备格式；不要补回退 |
| `MONITORING_DEVICE_NOT_APPROVED` | 在本机核对批准设备和 access 绑定；不通过消息改变设备 |
| `MONITORING_DATABASE_MISSING` / `MONITORING_PATH_REJECTED` | 停止，核对实例和链接；不建库、不修改 ACL |
| `MONITORING_SCHEMA_UPGRADE_REQUIRED` / `MONITORING_SCHEMA_INVALID` | 单独维护和隔离检查，不自动迁移 |
| `MONITORING_DATABASE_UNAVAILABLE` / `MONITORING_INTEGRITY_FAILED` | 核对锁、WAL 权限或损坏；不修复或覆盖源库 |
| `MONITORING_DATABASE_REPLACED` | 文件身份变化，停止并重新审批绑定 |
| `EVENT_QUERY_LIMIT` / `HISTORY_QUERY_BUDGET_EXCEEDED` | 超出完整查询预算；不能将失败解释为无异常 |
| `MONITORING_READ_FAILED` / `HISTORY_STORAGE_ERROR` | 查看安全错误码，检查锁/存储/记录；不输出原始行或堆栈 |

查询失败沿用原 Adapter 行为：记录安全状态，不发送业务结果；群内暂未增加失败解释消息。需人工联调确认使用体验，不冒充稳定生产服务。异常查询不提供全部历史事件详情或 ACK 历史；没有主动通知、硬件、LLM、多实例动态切换或多用户认证。

BOT-1B 用户已报告真实测试群 Gateway、只读虚构查询与 AI_DISABLED 通过；长时间断网恢复后的成功 Resume/Identify、未经授权成员拒绝仍待补充人工验收。本轮没有连接真实 QQ 重复验证。

## 7. 离线验证

所有数据库均由测试新建，位于临时目录；不复制用户库，不运行正式 Web 或 Simulator 上报。

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
$env:TEMP = Join-Path $PWD 'outputs/test-tmp'; $env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -X utf8 -B -m unittest apps.monitoring.tests.test_read_only apps.qq_bot.tests.test_monitoring_source
.\.venv\Scripts\python.exe -X utf8 -B scripts/dev/run_tests.py management
```

新增专项 28 项：防写 SQL、缺失/空库/v1、SQL 指令预算与锁超时、WAL 并发、字节/Schema 保持、设备隔离、错误路径/损坏、严格配置、替换/hardlink 拒绝、事件行/体积/成员预算、三窗恢复、等级周期、人工结束、会话缺测、不读取其他设备损坏 payload、失败去重、CLI 互斥及 Fake Transport 装配。

验证环境为本项目 `.venv` 的 **Python 3.12.14**。验证结果：新增专项 **28/28**；完整管理回归 **691/691 Python + 116/116 Node**，其中包含 **115 项 Bot、203 项 Monitoring**；最后补充旧记录推断组预算后，Bot + Monitoring **318/318** 再次通过。语法、JSON、新文档本地链接及 `git diff --check` 通过。测试还包括原 Management Web 的读写、Knowledge、AI Service Fake 请求、Simulator、事件及前端回归，未修改独立 Management 项目。

真实实例与 QQ 接入留待用户授权。后续依旧遵守 Prototype 开发 → 人工验收与获批提交 → Management 选择性同步。

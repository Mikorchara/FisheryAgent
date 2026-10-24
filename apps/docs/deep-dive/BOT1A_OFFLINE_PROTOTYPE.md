# BOT-1A：QQ Bot 离线原型

> 本文保留 BOT-1A 阶段记录。后续 [BOT-1B](BOT1B_QQ_TRANSPORT.md) 已在 Prototype 增加显式启用的官方通信层，原 `--offline-demo` 仍不联网。当前入口与新增文件以 BOT-1B 文档为准；两边核心不再逐字节相同，Management 尚未同步本轮通信实现。

日期：2026-10-24。项目：`D:\CodexProject\Fishery_AI_Prototype`，移植起始 HEAD `8d90d07`。

本轮从 Management 已验证的 BOT-1A 选择性移植 9 个源码/测试文件，核心逐字节保持一致。原 BOT-0 调查位于 Management 的 `apps/docs/deep-dive/research/BOT0_QQ_INTEGRATION_FEASIBILITY.md`，这里只作来源记录，不构成跨仓库运行依赖。

**后续统一执行：Prototype 开发 → 人工验收 → 获批提交 → Management 选择性同步并独立回归。BOT-1B、BOT-1C 等后续功能必须先在本仓开发。** 本轮不提交，Management 已完成的成果保留。

## 1. 已实现什么

这是**离线消息 Adapter 与固定只读命令原型**。没有 QQ 登录、AppSecret、token、WebSocket/Webhook 客户端、HTTP 监听或模型执行入口。输出 `OFFLINE_NOT_SENT` 和中文“未发送 QQ”，不代表任何消息已投递。

处理链路：

```text
虚构 GROUP_AT_MESSAGE_CREATE 字节报文 + 离线传输 AppID
 → 严格解析 → App/群/成员白名单 → 服务端群/设备绑定
 → 时效/去重/限频/容量检查 → 现有 Monitoring / Knowledge 只读查询
 → 有界纯文本 OfflineReply（只返回内存，不发 QQ）
```

没有重复实现 Monitoring 规则、检索索引、Agent 或 Tool Calling。固定命令的授权来自显式 `GroupAccess.capabilities`，不是模型 Tool 授权；它们不会伪造 Tool receipt/来源 Ledger。后续 AI 仍须经过原 AI Service、Policy、联网确认与来源/提交门禁。

## 2. 一条命令体验

在 Prototype 项目根执行：

```powershell
.\.venv\Scripts\python.exe -B -m apps.qq_bot --offline-demo
```

只试一条命令：

```powershell
.\.venv\Scripts\python.exe -B -m apps.qq_bot --offline-demo --command '/历史水质 30'
```

也可重复 `--command`，最多 6 条。默认演示依次显示帮助、当前水质、历史、知识、当前异常和 AI 禁用提示，最后显示 `DUPLICATE` 与 `GROUP_DENIED`。

若重定向输出或终端中文编码不匹配，在 Python 参数中加入 `-X utf8`，例如 `.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --offline-demo`。

入口在仓库忽略目录 `outputs/test-tmp/bot1a-<随机名>` 下独占创建临时 SQLite；用已有 Simulator 生成虚构窗口、设置固定虚构 DO，写入少量虚构知识后查询。所有测试时间固定为 `2026-10-24T04:00:00Z`（北京时间 12:00），不表示电脑当前数据。正常结束清理自己创建的临时目录，不启动常驻进程。

不接收 `--data-root`、`--user-data`、真实配置文件或密钥参数，不复制正式/演示知识或其他业务文件。无 `--offline-demo` 会直接拒绝。若被强行终止，可能残留该次虚构临时目录，不自动进行跨目录清理。

演示和专项测试在运行期间拦截 socket connect/connect_ex/sendto/DNS；这是额外本地测试保护，不是面向恶意插件的系统级网络沙箱。

## 3. 命令与来源

| 命令 | 实际复用 | 说明 |
|---|---|---|
| `/帮助` | 本模块固定说明 | 显示离线与只读边界 |
| `/当前水质` | `MonitoringService.capture_water()` + 既有当前水质 DTO 投影 | 显示数值/单位、质量、新鲜度、连接、观测时间与原规则提示；不重新采样 |
| `/历史水质 10` / `30` / `60` | `MonitoringService.query_water_history()` | 展示实际保留窗口均值范围、可靠窗口与完整性限制；不照搬网页“全部历史” |
| `/知识 关键词` | 原知识查询参数校验/有界 Evidence 投影与 `KnowledgeContentService.search()` | 只显示前 2 项摘要和来源/版本/Evidence ID，不进行知识写入 |
| `/当前异常` | `MonitoringService.event_cycles()` | 按绑定设备，排除可靠恢复/已人工结束提醒；显示前 5 个未结束风险，保留未知和恢复观察 |
| `/AI ...`、`/问AI ...` | 无模型调用 | 返回 `AI_DISABLED`；没有以 Fake 回答冒充现有 AI Runtime |

命令前的 `/` 可省略。设备不从消息解析；`/当前水质 other-device` 等多余参数拒绝。ACK、人工结束、删除和改配置均不支持。

事件查询没有结果时，仍检查水质观测可靠性；过期/缺测显示未知，不认定正常。水质可靠也不推定视觉正常、疾病治愈或规则恢复。原数据 `SIMULATOR` 来源始终明确。

## 4. 安全与内存边界

- **身份：**`BotConfig` 是不可变配置，显式 AppID、群、成员、设备和查询能力；默认示例只允许虚构群/成员。群昵称和 `member_role=owner` 不构成业务授权。
- **重要限制：**离线调用者传入的 `transport_app_id` 只用于模拟应用路由，**不证明消息来自 QQ**。没有验签或在线网关认证，不可直接挂到公网接收 JSON。真实接入属于 BOT-1B。
- **输入：**仅接收有界 UTF-8 字节 JSON 的文本 @事件；8 KiB 报文、2 KiB 正文，拒绝重复 JSON key、非有限数字、错误类型、控制字符、附件、全量事件及伪造 history 等额外业务字段。应用/群/成员/设备 ID 为 1～128 位受限字符；消息 ID 单独按不透明 ASCII 值校验，允许 `ROBOT1.0_` 等前缀与有限标点，本地上限 512 字符，不与设备 ID 共用格式。
- **时效：**本地实验拒绝已满 5 分钟或超过未来 30 秒的消息；查询完成后再次检查回复时效。时间回退拒绝新处理，避免恢复已过期请求。这里不是新增 QQ 平台保证。
- **去重：**键包含 AppID/群/消息 ID，指纹包含成员/时间/正文；重投不再读取也不重复产生回复。相同 ID 改正文或成员返回冲突，外层网关 sequence 改变不影响去重。
- **有界状态：**默认最多 512 个有效去重条目、128 个会话、16 个已配置群，每群最多 64 名成员。容量满拒绝，不驱逐尚有效的去重项；5 分钟时效过去后才回收对应项。
- **限频：**默认每成员/绑定会话 6 次/分钟、每群 20 次/分钟；包括错误命令，重投不再次扣次数。会话闲置 15 分钟后在下一次处理时回收。
- **并发：**同步单条处理，竞争请求立即 `BUSY`，没有无界队列、后台线程、自动重试或孤儿进程。SQLite 的实际等待继续使用既有服务超时；不是抢占式任务超时系统。
- **错误与输出：**未知错误仅返回 `READ_FAILED`，不暴露异常原文；输出一条纯文本，正文限制 1600 字符并显式省略，转义 `@` 和终端控制字符。无需 Markdown、附件下载或外部 URL。

会话键是 `(AppID, group_openid, member_openid, device_id)`。当前只保存成功命令计数、时刻和限频计数，**不保存聊天正文、答案或多轮历史**。Web 会话没有被导入。计数与去重只在进程内，重启后不具备持久幂等或真实投递恢复保证。

`ReadOnlyQueries` 的命令表不暴露写方法，但底层服务/Repository 仍是现有对象，不能把这个 Python facade 宣称为操作系统/数据库权限隔离。真实凭据保存、可信身份、持久收发、群数据共享授权与 AI 会话提交留到后续阶段。

## 5. 文件与职责

| 文件（相对项目根） | 职责 |
|---|---|
| `apps/qq_bot/contracts.py` | 配置、身份/时间校验、受限平台事件解析 |
| `apps/qq_bot/adapter.py` | 离线收件、去重/限频/会话容量、OfflineReply、安全错误 |
| `apps/qq_bot/service.py` | 固定只读命令与有界文本，不创建模型客户端 |
| `apps/qq_bot/offline.py` | 虚构夹具、socket 保护、有限离线演示 |
| `apps/qq_bot/__main__.py` | 仅允许显式离线演示的入口 |
| `apps/qq_bot/tests/test_adapter.py` | 权限、查询、生命周期边界、重放/并发/限频、业务记录不变 |
| `apps/qq_bot/tests/test_offline.py` | CLI 拒绝真实参数、虚构演示、临时目录清理、无网络 |
| `scripts/dev/run_tests.py` | 将 Bot 专项纳入 Prototype 原 management/management-independent 分层 |
| `pyproject.toml` | 将 Bot 包加入现有发行包发现；无新增依赖 |

原 Monitoring、Knowledge、AI Service/Backend、Web 和 Simulator 功能源码均不修改；没有新数据库 Schema。

## 6. 本次移植验证记录

- Prototype 专项 30 项通过：全部只读命令、三档历史、数据/来源/单位、权限、设备绑定、去重、限频、并发、容量、时效、异常脱敏和两库全部业务记录查询前后不变。
- 两个仓库分别使用自己的 `.venv` 运行默认离线演示：5 个成功只读/帮助结果、`AI_DISABLED`、`DUPLICATE`、`GROUP_DENIED` 一致；只对随机虚构 Knowledge ID 规范化后，完整终端输出一致。
- Prototype 原入口 `.\.venv\Scripts\python.exe -B scripts/dev/run_tests.py management`：**597 项 Python、116 项 Node 全部通过，退出码 0**，Python 用时 116.275 秒；覆盖 Monitoring、Knowledge、AI Service/Backend、Web、Simulator、原有差分边界和 Bot 专项。
- Management 本轮重新运行 Bot 专项 **30 项通过**。由于其功能代码保持原状，没有重复运行独立完整管理回归；605 项 Python/116 项 Node 为上一轮记录，不冒充本轮重跑。
- 临时测试使用各自的 `outputs/test-tmp`，不读取真实业务库、Settings、Policy、AppSecret 或 API Key，不调用 QQ/Provider/NPU。

## 7. 本阶段未实现与下一步

1. **BOT-1B：**批准后增加真实官方传输，验证应用身份、目标群 @ 回复、重连和在线权限；不要将本离线 AppID 参数当认证。
2. **BOT-1C：**用 Fake SDK 走原 `ManagementAssistantService.prepare_turn/execute_turn`，再验证历史隔离、Source/Commit、预算与取消；本轮没有越阶段创建第二套 Fake Agent。
3. **BOT-1D：**群级业务授权、逐条联网确认和发布边界核准后，用户主动进行限制次数的真实 AI 测试。
4. **BOT-2：**主动通知权限、通知去重和可靠队列独立验证；本轮没有主动发送、订阅线程或 Monitoring outbox。

当前可人工验收的是终端中的离线命令及安全拒绝行为；尚不能通过 QQ 群测试。无 commit/push，等待人工认可再进入在线阶段。

## 8. 两项目差异及移植范围

| 项目 | Prototype | Management | 处理方式 |
|---|---|---|---|
| Git | main，8d90d07；起始干净 | codex/mig3-baseline，689f0f3；已有 BOT-0/BOT-1A 未提交改动 | 独立仓库，不混用历史，不 reset/commit/push |
| 发行身份 | fishery-ai-prototype，扫描 src 和根，保留旧 fishery_ai | fishery-management，仅独立 apps | 只给 Prototype 增加 qq_bot include 与 tests exclude，不复制项目配置 |
| 测试入口 | 原 run_tests.py 的 product/backend/management/qualification 等分层 | run_management_tests.py -I 独立入口 | 只扩展 Prototype 的 management 与 management-independent 发现目录，其余入口/过滤保持 |
| 运行环境 | 自身 .venv，实测 Python 3.12.14 | 自身 .venv，实测 Python 3.12.14 | 两项目声明仍为 >=3.11；本轮不安装/升级/替换环境 |
| 已安装依赖差异 | python-dotenv 1.2.3；setuptools 未安装 | python-dotenv 1.2.4；setuptools 84.0.0 | 保留各自环境；openai 2.54.0/httpx 0.28.1/Flask 3.1.3 一致，无新依赖 |
| 数据位置 | 入口按自己的 __file__ 定位仓库 outputs/test-tmp | 同样按自己的仓库定位 | 相同源码自动适配，不复制真实库或配置 |
| Bot 核心 | 本轮新增 9 个源码/测试文件 | 保留原已验证 9 个文件 | 逐字节一致，无分支判断/跨仓导入 |
| Bot 业务依赖 | 所核对的 10 个直接业务模块与另一仓一致 | 同左 | Monitoring/Knowledge/AI/Web/Simulator 源码均不修改 |

9 个移植文件：`__init__.py`、`__main__.py`、`contracts.py`、`adapter.py`、`service.py`、`offline.py`、`tests/__init__.py`、`tests/test_adapter.py`、`tests/test_offline.py`，均位于 `apps/qq_bot/`。必要配套只调整本仓 `pyproject.toml` 的包清单、`scripts/dev/run_tests.py` 的测试发现以及 apps/docs 的操作/索引/结构/路线说明。

不存在新的运行依赖、数据库 Schema 或新的 QQ/AI 权限。Management 仅补充流程说明，既有 Bot、打包和测试代码保留；不把这一轮作为撤销正式应用代码的理由。

静态核验：9 个 Bot 文件 SHA-256/字节一致；Prototype pyproject 仅增加包 include/tests exclude，其他 TOML 内容与 HEAD 相同；测试脚本移除两处新增 Bot 目录后，AST 与 HEAD 相同。源码语法、文档链接和 diff 空白检查通过。Prototype 未安装 setuptools，本轮只做发行清单静态检查，未额外执行 Wheel 构建或安装构建工具。

Git 最终状态：两个 HEAD 均未改变，未执行 add/commit/push。Prototype 新增 Bot 与本文并调整六个既有配套文件；Management 保留原未提交成果，仅在原 BOT-1A 文档补充流程纠偏与本轮复核记录。未修改既有业务功能源码、旧 src Runtime 或真实数据。

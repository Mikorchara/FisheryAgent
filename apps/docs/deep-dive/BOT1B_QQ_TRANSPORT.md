# BOT-1B：QQ 官方 WebSocket 只读联调

后续状态（2026-10-25）：本页保留 BOT-1B 首轮实现与当时边界。用户已报告测试群 Gateway、固定只读虚构查询及 AI_DISABLED 通过；长时间断网后的成功 Resume/Identify 和未授权成员拒绝仍待补充人工验收。BOT-2B 另增显式 Monitoring 实例只读模式，未在本轮接入既有实例或真实 QQ；操作以 [BOT-2B 文档](BOT2B_MONITORING_READ_ONLY.md) 为准。

核验日期：2026-10-24。开发项目：`D:\CodexProject\Fishery_AI_Prototype`，起始 `main@6f2fee2`。

当前状态：已实现真实 QQ HTTPS / WSS 通信层并完成离线协议测试；**尚未完成真实 QQ 测试群验收**。用户已准备官方机器人和测试群，将按下文在本机录入 AppSecret、配置 OpenID 白名单。开发期间没有读取真实凭据、连接 QQ、发送群消息或调用模型。仅修改 Prototype，未同步 Management、未提交。

## 1. 本轮边界与实际链路

```text
用户在测试群 @机器人 + 固定命令
 → QQ 官方 Gateway（出站 WSS，已验证的 App AccessToken）
 → 仅 GROUP_AT_MESSAGE_CREATE；去掉平台附带元数据
 → 复用 BOT-1A 的 App / 群 / 成员白名单、群设备绑定、时效、去重、限流
 → help-only：仅帮助；或 fictional-data：临时虚构 Monitoring / Knowledge 查询
 → 有界纯文本 → QQ 官方被动回复 POST（原消息 msg_id，msg_seq=1）
```

不新建 AI Agent、HTTP 监听器或 Web 路由。本轮没有自然语言模型问答、主动推送、ACK、人工结束、删除、规则/配置修改。群消息不能更改设备绑定、权限或数据路径。固定命令只借用现有只读业务查询和参数校验，不冒充 AI Tool 执行或来源账本。

为首轮真实通信验收收窄数据边界：**CLI 不提供真实业务实例选项**，不打开已有 Monitoring / Knowledge、Settings、Policy、Trace。`--fictional-data` 只创建本仓 `outputs/test-tmp/bot1b-*` 内的新库，退出删除；不是复制现有业务数据。`--help-only` 不创建任何业务库。后续真实数据绑定、AI 与通知分别授权。

### 官方协议核验

以下日期是官方页面标注的“更新时间”，不是推断的发布日期；统一于 2026-10-24 核验。

| 官方资料 | 更新日期 | 本轮使用的明确合同 |
|---|---|---|
| [平台总览](https://bot.q.qq.com/wiki/) | 2026-10-21 | WS / Webhook 选择；IP 白名单配置；资格仍取决于实际账号 |
| [事件接入框架](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html) | 2026-09-11 | Hello、Identify、Heartbeat/ACK、Resume；群事件 intent `1 << 25` |
| [获取 AccessToken](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html) | 2026-09-16 | AppID + AppSecret；`QQBot` Authorization；HTTP 200 仍须检查业务 code |
| [获取 Gateway](https://bot.q.qq.com/wiki/develop/api-v2/openapi/wss/url_get.html) | 2026-07-30 | GET `/gateway` 返回 WSS 地址 |
| [群 @ 消息事件](https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_at_message_create.html) | 本轮未记录页面更新时间 | `group_openid`、`author.member_openid`、原消息 ID、时间戳与正文 |
| [发送群消息](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html) | 2026-09-03 | 被动回复关联原消息，五分钟内，最多五条；本实现只回一条 |
| [Gateway 断开码](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/error-trace/websocket.html) | 2026-07-21 | 权限/封禁等致命码停止；会话失效重新 Identify，其他可恢复断开有界重连 |
| [websockets 15.0.1 同步 API](https://websockets.readthedocs.io/en/15.0.1/reference/sync/client.html) | 固定版本文档 | 有超时的同步收发与 context manager；可选依赖固定兼容范围 `>=15.0.1,<16` |

选择 WS 是为了本机验收无需公网入站地址、域名和 HTTPS 回调服务；仍需要本机能够出站访问 QQ 官方 HTTPS/WSS。Webhook 的签名验证与公网部署**没有实现**。平台群事件权限、测试群资格、IP 白名单与实际投递仍须用真实账号验证，离线测试不能代替。

## 2. 本机配置与人工验收

以下命令均在普通 PowerShell 执行。**不要把 AppSecret、AccessToken 或含敏感元数据的完整 QQ 报文贴到聊天或日志。** 本轮机器人只回复你主动发送的测试指令；没有自动通知。

### 第一步：依赖与私有 AppSecret

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
.\.venv\Scripts\python.exe -m pip install 'websockets>=15.0.1,<16'
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --configure-secret
```

最后一条会在终端隐藏输入。首次使用只允许创建；已有该项时拒绝覆盖。确需轮换时显式加 `--replace-secret`。不要通过命令参数传密钥。

固定引用名是 `FISHERY_QQ_APP_SECRET`。复用现有 `CredentialStore` / `ProjectEnvWriter`，存入由 `private_project_location(Prototype根目录)` 计算的私有文件：

```text
%LOCALAPPDATA%\Fishery_AI_Prototype\project-<本项目路径身份>\credentials\.env
```

不读取源码根 `.env`，不复制 Management 或其他项目密钥；保留既有文件的其他配置字节。凭据仍遵守 PROCESS_ENV > 私有 PROJECT_ENV > MISSING；若该引用已在进程环境中，写入按既有 `PROCESS_ENV_READ_ONLY` 规则拒绝。ACL/本地文件系统/链接检查沿用原实现，失败必须停止，不放宽安全检查、不自行改 ACL。Bot AccessToken 只存内存，提前 60 秒刷新，退出清除引用。AppID 不属于 AppSecret，但访问配置仍不要提交。

在 QQ 官方开发后台选择 WebSocket 接入，启用账号允许的群 @ 事件，并将机器人加入专用测试群；检查开发/沙箱群范围及平台 IP 白名单。不要假设创建 App 就自动取得全部事件权限。

### 第二步：发现 OpenID（不回复、不查询业务）

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --discover --app-id '替换为数字AppID' --confirm-qq-network --run-seconds 120
```

看到 `QQ_GATEWAY_READY` 后，在测试群里**真正 @机器人**，发送 `help`。终端最多显示十组实际收到事件中的 `group_openid` / `member_openid`，不会回复或查询任何业务数据。它们不是普通 QQ 群号/QQ 号，也不能用 `member_role=owner` 代替业务授权。该模式仅供本机配置，不将收到消息者自动加入白名单；结束后手动审核需要允许的群和成员。

### 第三步：编辑访问白名单

```powershell
New-Item -ItemType Directory -Path '.\outputs\qq-bot' -Force | Out-Null
if (Test-Path -LiteralPath '.\outputs\qq-bot\access.json') { throw '访问配置已存在，请直接编辑，不覆盖。' }
Copy-Item -LiteralPath '.\apps\qq_bot\examples\access.example.json' -Destination '.\outputs\qq-bot\access.json'
notepad '.\outputs\qq-bot\access.json'
```

**仅首次配置时复制**；已有 `access.json` 时直接编辑，不重复覆盖。替换 AppID、群 OpenID、成员 OpenID，`device_id` 保持 `sim-pond-1`（虚构低氧池）或 `sim-pond-2`（虚构正常池）。示例占位 AppID 故意不能通过校验。文件不接受 secret、URL、角色或额外权限；AppSecret 不填入 JSON。

```json
{
  "schema_version": 1,
  "app_id": "123456789",
  "groups": [{
    "group_id": "替换为真实群OpenID",
    "device_id": "sim-pond-1",
    "members": ["替换为授权成员OpenID"],
    "capabilities": ["current", "history", "knowledge", "events"]
  }]
}
```

上面是格式示例，中文占位不能作为真实 ID。多个成员须逐个列明，禁止未知群/成员业务访问。

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --check-config --access-file '.\outputs\qq-bot\access.json'
```

成功输出 `QQ_ACCESS_CONFIG_VALID`。该命令不读取凭据、不联网。修改权限需停止并重启连接，运行中不热加载。

### 第四步：先 help，再虚构只读查询

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --connect --access-file '.\outputs\qq-bot\access.json' --help-only --confirm-qq-network --run-seconds 600
```

授权成员 @机器人 `help` 或 `/帮助`，应收到带 `BOT-1B 只读实验` 的帮助；水质等能力在此模式强制关闭，不因配置列出 capability 就执行。确认后 Ctrl+C 停止，改为：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --connect --access-file '.\outputs\qq-bot\access.json' --fictional-data --confirm-qq-network --run-seconds 600
```

| 手工测试消息（均须 @） | 预期 |
|---|---|
| `help`、`/帮助` | 固定帮助，不调用模型 |
| `/当前水质` | 虚构设备数据、单位、SIMULATOR、质量与新鲜度 |
| `/历史水质 10`，也支持 30 / 60 | 窗口均值范围；不伪装原始采样历史 |
| `/知识 溶解氧` | 一条虚构学习资料，含版本与 Evidence，不是真实现有知识库 |
| `/当前异常` | 虚构低氧周期；不认定疾病或人工处置 |
| `/问AI 分析` | AI_DISABLED，不请求任何模型 |
| `/删除`、`/ACK` 或自然语言长问题 | 不支持，不执行写入/Agent |
| 未授权成员或其他群 @ | 本地 GROUP_DENIED / MEMBER_DENIED，无数据查询、无群回复 |

虚构夹具仅在启动时产生三窗历史，不是持续 Simulator；等待后新鲜度自然变成 stale / offline，不能把它当故障或“当前正常”。为复测新鲜数据可停止后重新运行，生成新的临时夹具；不清理或修改已有用户实例。

每成员每分钟 6 条、每群每分钟 20 条，共用 BOT-1A 门禁；超限仅日志 `RATE_LIMITED`、不重复回复。一次验收避免连续刷超过限额。用不同消息逐项测试，不能把平台“重新投递同一 ID”当成新问题。会话最多 3600 秒（默认 600），到时或 Ctrl+C 关闭 WSS、等待当前有界查询/HTTPS 完成、回收工作线程和临时库。没有常驻后台服务。

## 3. 失败处理与日志

普通日志为时间、安全 code 与按字段/类型白名单过滤的 JSON 行，不输出正文、群成员 ID、AppSecret、AccessToken、HTTP body/headers、异常栈。`--discover` 是明确例外，只将必要 OpenID 显示到本机终端；不要公开该输出。平台 `message_scene.auth_token` 等元数据在解析入口丢弃；兼容移除 READY 中本机器人 ID 对应的前置 mention，不剥离他人 mention。

| 安全诊断 | 处理 |
|---|---|
| `QQ_WEBSOCKETS_DEPENDENCY_MISSING` | 用第一步安装本项目可选依赖；无需安装整个 Bot 框架 |
| `QQ_CREDENTIAL_UNAVAILABLE` / `QQ_SECRET_MISSING_OR_INVALID` / `ENV_PERMISSION_ERROR` | 检查私有配置与原有安全权限；不把密钥写进 JSON 或源码根 |
| `QQ_HTTP_401` / `QQ_API_<数字>` | 检查本机 AppID/Secret、平台资格和 IP 白名单；HTTP 200 的业务错误也拒绝 |
| `QQ_GATEWAY_CLOSE_4014` | 核查事件 intent / 平台授权；不自动降权或改成其他协议 |
| `QQ_GATEWAY_CLOSE_4914` / `4915` | 核查沙箱范围 / 账号限制，停止重试，按官方后台处理 |
| READY 后无事件 | 确认真正 @、测试群范围、群事件权限和官方 WS/WH 选择；不能靠放宽群门禁解决 |
| `GROUP_DENIED` / `MEMBER_DENIED` / `CAPABILITY_DENIED` | 手工核对白名单；权限不由群主角色或消息正文决定 |
| `MESSAGE_EXPIRED` / `REPLY_EXPIRED` | 核查 Windows 时钟和延迟，不复用过期 msg_id |
| `QQ_HTTP_403` / `429` | 核查官方权限和频率；不自动重发本条回复 |
| `QQ_DELIVERY_UNKNOWN` / `QQ_SEND_NOT_CONFIRMED` | 投递结果不能确定；不声称成功、不自动重发。观察群消息后用新的消息重新测试 |
| `QQ_QUEUE_FULL` / `QQ_RECONNECT_LIMIT` | 减少并发、检查网络后人工重启；不建无限队列/重试 |

收到 Hello 后 Identify；正常连接按官方 interval 心跳并检查 ACK。断开保留 session/seq 尝试 Resume，支持官方“先补发遗漏 Dispatch，再发送 RESUMED”的顺序；初次 Identify 前的业务事件仍拒绝。会话失效重新 Identify。每次运行最多首次连接加三次重连，退避 1/2/4 秒；致命鉴权、权限、封禁直接停止。独立协议截止时间保护和断线状态日志见 §3.3。所有连接仅限固定 QQ 官方 HTTPS/WSS 主机，禁重定向和系统代理，不支持自定义 URL；企业代理环境需另行评估，不能通过随意放开 URL 绕过。

只有响应 HTTP/业务状态正常且有发送消息 ID 时记录 `QQ_REPLY_ACCEPTED`，它表示平台接受，不代表终端已展示。消息去重、会话计数是**进程内**，重启无持久去重保证；固定 `msg_seq=1` 遵守平台被动回复去重合同，不宣称端到端 exactly-once。网络失败可能丢一条回复，这是本阶段避免不确定重复发送的明确取舍。

### 3.1 BOT-1B-DIAG：Gateway URL 拒绝诊断

2026-10-24 增补。只在 Gateway 地址被拒绝时增加一行结构化诊断，原来的最终 `GATEWAY_URL_REJECTED` 和失败退出码保持兼容。`QQ_STOPPED` 仍可能先出现，因为清理在异常返回 CLI 前执行；它不是“已成功连接”的证明。成功 URL 不额外输出诊断，不改变原有发现、查询和回复流程。

| 新增诊断 code | 含义 |
|---|---|
| `GATEWAY_URL_FIELD_MISSING` | 已成功解析的 Gateway JSON 对象中没有 `url` 字段 |
| `GATEWAY_URL_TYPE_INVALID` | `url` 不是字符串；显式 JSON `null` 与字段缺失分开 |
| `GATEWAY_URL_PARSE_FAILED` | URL 结构解析失败，例如畸形方括号；不记录异常原文 |
| `GATEWAY_URL_PORT_INVALID` | URL 主体可解析，但端口格式或范围不能解析 |
| `GATEWAY_URL_POLICY_REJECTED` | 可解析，但至少一条原有白名单/组件规则不匹配 |

每行有 `diagnostic_version=1`；`stage=response` 表示 GET `/gateway` 的字段校验，`validation` 表示后续 connector 等直接 URL 校验。仅包含：

- `url_present`；`url_type` 固定为 missing / string / null / boolean / number / object / array / non_json，不打印字段值或 Python 类型名。
- `parse_ok`、`port_parse_ok`；scheme / hostname / port / path 的 `*_matches`，均为布尔值；**未能检查的项为 `null`，不等于不匹配**。不输出任何实际组件值。
- `has_username`、`has_password`、`has_query`、`has_fragment`：是否有非空组件，沿用既有拒绝条件；不输出组件内容。
- `input_has_whitespace`、`input_has_controls`：输入是否包含空白/控制字符，只是诊断，不清洗或重写 URL。

DIAG 阶段没有扩大域名白名单；当前 FIX 阶段的精确双域名兼容见 §3.2。仍只允许 WSS、默认/443 端口、`/websocket` 或 `/websocket/`，不增加参数或跳转许可。HTTPS 请求仍禁止重定向。HTTP/JSON/业务状态在 URL 校验前就失败时，继续原有安全错误码，不伪造 URL 诊断。

在普通 PowerShell 中重新执行（**由用户操作，本轮开发测试未执行真实连接或读取凭据**）：

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --discover --app-id '替换为数字AppID' --confirm-qq-network --run-seconds 120
```

无需重新保存密钥。若再次拒绝，只反馈新增的 `GATEWAY_URL_*` 诊断 JSON 行与最终错误码即可，不提供完整 URL、响应、密钥或发现到的群/成员 OpenID。这些字段用于取得证据，**当前没有推断实际 Gateway 地址或宣称真实故障已修复**。

DIAG 验证：Bot 专项 **85/85 通过**（原 73 项 + 新增 12 项），日志位于 `outputs/test-tmp/bot1b-gateway-diag-tests.log`。覆盖 JSON 类型/缺失、解析/端口失败、白名单不变、HTTP 禁跳转、脱敏字段白名单、CLI 保留旧错误码及拒绝后不连接；仅 Mock HTTPS 和原有本机回环测试，未连接 QQ/Provider。下面 640 Python / 116 Node 是初始 BOT-1B 的历史完整回归结果，本次未重复运行该完整套件。

### 3.2 BOT-1B-FIX：精确兼容已确认的 Gateway 域名

2026-10-25：用户在本机使用已有凭据请求官方 GET `/gateway`，确认实际 hostname 为 `api.sgroup.qq.com`；此前诊断仅 `hostname_matches=false`，其余安全条件通过。旧校验只接受 `api.bot.qq.com`，因此在建立 WSS 前错误阻断了本次已确认的 Gateway。

官方历史依据：[腾讯文档仓库的 Gateway 示例](https://github.com/tencent-connect/bot-docs/blob/main/docs/develop/api-v2/openapi/wss/url_get.md) 使用 `api.sgroup.qq.com`，[腾讯 Python SDK](https://github.com/tencent-connect/botpy/blob/master/botpy/http.py) 亦保留该域名；当前[在线接口文档](https://bot.q.qq.com/wiki/develop/api-v2/openapi/wss/url_get.html) 则示例为 `api.bot.qq.com`。本次根据用户实际确认及上述来源增加一个精确兼容项，不将所有历史域名视为当前已授权地址。

当前边界：

- `transport.py:GATEWAY_HOSTS` 为固定集合：`api.bot.qq.com`、`api.sgroup.qq.com`，使用解析后的 hostname 精确匹配；DNS 大小写规则沿用原解析器。
- REST `API` 保持 `https://api.bot.qq.com`，获取令牌、获取 Gateway、被动回复均不改到旧 REST 域名。
- WSS、默认/443 端口、两种既有路径、用户名/密码/query/fragment 检查、TLS 证书及 hostname 默认验证、禁重定向/系统代理均保留。返回 URL 原样传给 connector，不把旧域名替换为新域名。
- 不接受任意子域名、后缀匹配、沙箱地址、鉴权服务地址或自定义 URL。原有脱敏诊断继续有效，`hostname_matches` 现按上述集合判断。

验证：用 Mock HTTP 先复现旧代码的 `GATEWAY_URL_REJECTED`；修改后 **89/89 Bot 专项通过**，原 85 项保持通过，新增 4 项覆盖旧 Gateway 响应而 REST 地址不变、伪造/子域名拒绝、两域名同等 URL 限制及 connector 不覆盖 TLS 默认验证。原合法 URL 用例也扩展至两个域名。未读取真实密钥，未连接 QQ/Provider；仅虚构响应和原有本机回环测试。

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --discover --app-id '替换为数字AppID' --confirm-qq-network --run-seconds 120
```

由用户本人重新联调，无需重新保存密钥。出现 `QQ_GATEWAY_READY` 后，在测试群 @机器人发送 `help`；discover 模式仅向本机显示 OpenID，不回复。随后按 §2 配置白名单并以 help-only 测试真实回复。此次仅修复已确认的域名拒绝，真实 READY、事件投递和回复仍待人工验收。

测试日志：`outputs/test-tmp/bot1b-host-compat-tests.log`。本轮源码仅改 `transport.py` 的域名常量和匹配条件，另更新 `tests/test_transport.py` 与本文；未同步 Management、未 commit/push。初始完整管理回归仍是下文历史结果，本轮只运行所需 Bot 专项。

### 3.3 断网检测与有界恢复修复

2026-10-25。用户报告真实 QQ 已 READY 且能回复，但断网恢复后无回复、无新状态日志。本轮没有操作真实网络或 QQ；在本机模拟 Gateway 中复现并修复了以下缺口，未取得用户故障当时的线程栈，不能断言其现场一定停在某一行。

**调查依据与复现：**

- 原有 `ws.recv(timeout≤0.5)` 在普通无消息场景会正常超时；单纯丢失 ACK 的本机黑洞可被原来的心跳循环检测。因此不能把所有无日志等待都归因于 `recv()` 卡死。
- 已安装 websockets 15.0.1 的同步 `send_context/send_data` 在协议锁内调用 `socket.sendall()`；`recv()` 遇 EOF 后还可能等待 `recv_events_thread.join()`。应用层 recv 超时不能覆盖这些内部等待。关闭时也可能等待同一协议锁。[上游源码](https://github.com/python-websockets/websockets/blob/15.0.1/src/websockets/sync/connection.py)、[同步 API](https://websockets.readthedocs.io/en/15.0.1/reference/sync/client.html)。本轮不修改第三方库。
- 原有 `HEARTBEAT_TIMEOUT` 日志在退出连接 context 后才输出；清理被阻塞时，连已经发生的故障也可能尚未输出。健康连接此前也不打印心跳发送/ACK，正常检测窗口内的等待缺少说明。
- 注入阻塞发送后，旧版超过测试的心跳截止时间仍无超时日志；另一个固定测试证实 Resume 在 RESUMED 前收到重复序号会误报 `QQ_EVENT_BEFORE_AUTH`。

**最小修复：**

- `transport.GatewayDeadline` 为每条活动连接提供一个独立、可停止并回收的截止时间线程。它监测原有 Hello、鉴权、心跳 ACK、关闭及会话运行截止时间；额外留 0.5 秒供正常 recv 轮询和线程调度完成，不缩短或替换原协议阈值。
- 到期时先输出安全错误码，再对**本次连接自己的底层 socket** 执行 shutdown/close，释放阻塞的发送、内部接收等待或关闭锁等待。不能通过再次调用可能等待同一把锁的 WebSocket close 来打断它。
- 正常关闭保留库的 2 秒超时，并在其外提供独立保护；保护线程停止失败会明确报错并停止，不启动下一轮保护线程。
- 保持 Hello 接收 10 秒、鉴权 15 秒、原 ≤0.5 秒轮询、服务器下发心跳间隔、首次连接加三次重连和 1/2/4 秒退避。HTTP、两个精确 Gateway 域名、TLS 验证、禁重定向和代理策略不变。
- 同一个 Adapter、容量 4 的队列、单查询 worker、进程内去重和权限状态跨重连保留。有效 Resume 的重复序号忽略；会话失效后仍重新 Identify，不能由未鉴权的新连接直接查询业务。

**时间与日志：**服务器下发间隔为 I 秒时，普通 ACK 丢失由原循环检测；若循环本身卡在同步 I/O 中，最迟约两轮心跳加 0.5 秒调度余量触发强制中断。若 I=45 秒，应允许约 90.5 秒检测窗口，不保证拔网线后立即报错；会话总时长到期会更早结束。

新增安全日志包括 `QQ_GATEWAY_CONNECTING`、`QQ_GATEWAY_WAIT_HELLO`、`QQ_GATEWAY_IDENTIFYING` / `QQ_GATEWAY_RESUMING`、`QQ_HEARTBEAT_CONFIGURED`（只有整数 heartbeat_ms）、`QQ_HEARTBEAT_SENT` / `QQ_HEARTBEAT_ACK`、`QQ_GATEWAY_CLOSING`、`QQ_GATEWAY_RETRY_WAIT`（只有次数/退避秒数）。超时报告 `HEARTBEAT_TIMEOUT`、`GATEWAY_HELLO_TIMEOUT`、`GATEWAY_AUTH_TIMEOUT` 或 `GATEWAY_CLOSE_TIMEOUT`；预算耗尽仍为 `QQ_RECONNECT_LIMIT`。到运行时长为 `QQ_RUN_DURATION_REACHED`，不是自动无限重启。没有正文、URL、Token、会话 ID、异常堆栈或完整响应。

**隔离验证：**Bot 专项 96/96 通过（原 89 项 + 7 项新测试）。本机服务使用 1 秒心跳，覆盖无 ACK 的黑洞、阻塞发送、接收内部等待和关闭；测试在 3.5 秒内观察发送/接收失效，在 5 秒内观察关闭失效，并验证重连后新消息能处理。还验证 Resume 补发去重、失效 Resume → Identify 的 `[2,6,2]` 顺序、运行总时长约束、所有测试连接/接收线程/worker/截止时间线程回收。已有四次连接上限、权限、域名、脱敏日志和只读命令测试继续通过。故障注入不等同于真实 Windows 网卡断开实测。

日志：`outputs/test-tmp/bot1b-reconnect-before.log` 保留旧版两项失败证据，`outputs/test-tmp/bot1b-reconnect-tests.log` 为通过结果，均为虚构数据。此次未重跑下文初始完整管理回归，也未读取真实凭据或用户实例。

**用户人工验收：**

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --connect --access-file '.\outputs\qq-bot\access.json' --help-only --confirm-qq-network --run-seconds 600
```

1. READY 后由白名单成员 @机器人 `help`，确认 `OK` / `QQ_REPLY_ACCEPTED`，记录 `heartbeat_ms`。
2. 手工断网，观察有界超时/关闭/重试日志；要验证失效检测，可保持断网至第一次超时后尽快恢复网络。短暂断网若原 TCP 仍有效，恢复后继续收到 ACK 也属于正常结果。
3. 在重连预算内恢复后，应出现 RESUMING → RESUMED，或会话失效后的 IDENTIFYING → READY；再发**新消息** `help`，确认恢复回复。不要靠反复转发同一消息绕过去重，注意每成员每分钟 6 条限额。
4. 超过三次重试才恢复网络时，预期明确 `QQ_RECONNECT_LIMIT` / `QQ_STOPPED` 并需人工重启；不会无限后台等待。会话 600 秒到期也会明确停止。
5. Ctrl+C 后确认正常退出。只分享上述安全状态码，不贴 OpenID、密钥、正文或完整平台报文。

底层 socket 中断依赖当前固定的 websockets 15 同步实现；今后升级该可选依赖必须重新运行本机断线测试。此次没有修改 Management、业务合同、用户数据库或 AI 能力，没有 commit/push。

## 4. 文件、测试与未验收部分

| 文件 | 职责 |
|---|---|
| `apps/qq_bot/cli.py` / `__main__.py` | 显式网络确认、私有配置、发现/帮助/虚构模式和退出清理；原 offline-demo 保留 |
| `configuration.py` / `examples/access.example.json` | 严格白名单、固定 credential_ref、复用私有 Store 和安全写入器 |
| `transport.py` | AccessToken、固定官方 HTTPS、单条被动回复、受限 WSS connector |
| `gateway.py` | Identify/Resume、心跳、事件正规化、有界单 worker 队列、安全诊断 |
| `adapter.py` / `service.py` | 原 BOT-1A 门禁/只读命令复用；live 文案与英文 help |
| `tests/test_transport.py` | Mock HTTP 合同、错误、超时、token 与被动回复边界 |
| `tests/test_gateway.py` | Fake QQ 生命周期、白名单/重放/限流；真实 websockets 库本机回环测试 |
| `tests/test_reconnect.py` | 本机黑洞、同步 I/O 阻塞、Resume/重新鉴权、恢复回复和线程回收 |
| `tests/test_configuration_cli.py` | 私有 Store 路由、无真实数据入口、隐藏录入、无网络配置检查 |
| `pyproject.toml` | 可选 `qq` 依赖和示例资源，不改变默认 AI/Monitoring 依赖 |

验证命令（TEMP/TMP 限本仓隔离区）：

```powershell
$env:TEMP = Join-Path $PWD 'outputs/test-tmp'; $env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s apps/qq_bot/tests -t . -v
.\.venv\Scripts\python.exe -X utf8 -B scripts/dev/run_tests.py management
```

初始 BOT-1B 验证结果（本项目 `.venv` Python 3.12.14、websockets 15.0.1；后续 DIAG/FIX 见 §3.1/§3.2）：

- Bot 专项 **73 项通过**：原 30 项保留，新增 43 项，含 Resume 补发顺序。覆盖真实通信库的本机假 Gateway，不连接 QQ；Mock HTTPS、不调用 Provider。
- 最终完整管理回归 **640 项 Python、116 项 Node 全通过**；Bot 专项包含在 640 项内。覆盖 Backend、AI Service、Monitoring、Simulator、Knowledge 和 Management Web。
- Bot 全部 Python AST、pyproject TOML、`git diff --check`、本轮涉及文档的本地文件链接检查通过。
- 非敏感回归日志保留在 `outputs/test-tmp/bot1b-management-regression-final.log`（Git 忽略）；所有临时 Bot 库、回环测试服务和工作线程已结束。
- 工作树只涉及 `apps/qq_bot/`、相关 `apps/docs/` 与 `pyproject.toml`；HEAD 仍为 `6f2fee2`。没有修改 Management、旧 src Runtime 或真实业务/凭据文件，没有 commit/push。

仍待用户人工完成：私有 AppSecret 实际写入与本机 ACL、官方后台事件权限、真实 Gateway READY、授权群 @ 的 help/只读回复、未知成员拒绝与真实断线体验。**这些未完成之前，不标记 BOT-1B 真实联调通过，不进入 BOT-2，不同步 Management。**

# EVT-3A：人工知晓 ACK 与操作留痕

当前仅在 Prototype/apps 实现，待人工验收；未同步 Management。没有操作真实数据库、Settings、Policy、Credential 或真实 Provider/NPU。ACK 不改变 ACTIVE / INDETERMINATE / RESOLVED，不提供 Snooze、Close、派单、登录或 AI 写入 Tool。

## 1. 确认对象与等级版本

- 水质同族使用已持久化的 risk_family.episode_id，连同设备、通道、风险方向及规则身份计算稳定周期键；视觉和数据质量等单 code 使用事件 ID 及完整规则身份。
- 无可靠规则身份或只有 legacy-* 推断身份的旧记录只读，显示待确认，不允许写 ACK。没有批量补造旧记录身份或确认时间。
- ACK 等级取自显式 code→rank 注册表；水质复用 FAMILIES 的等级序号，严重低氧和极低氧即使同为 critical，仍分别为 2、3。注册表有 ack-grades-v1 指纹，不从标题或 severity 字符串猜测。
- grade_token 绑定周期、等级、等级合同版本及持久化的最后一次等级变化证据。同等级 HIT 不产生新 token；升降级或等级往返都会产生新 token，不会复活早先确认。
- 只允许当前等级成员确认；旧等级详情可看共享周期的人工状态及历史，但需打开当前等级记录操作。详情“知晓对象”明确指向当前等级。

| 情况 | 人工状态 |
|---|---|
| 首次 ACK | 当前周期／等级已知晓 |
| 同等级持续 HIT | 保留已知晓 |
| 等级升级，包括严重→极低氧 | 重新待确认，历史保留 |
| 等级降低或返回旧等级 | 保守地重新待确认，不继承较高或过去等级的确认 |
| 缺测、过期、离线、新 Session | 保留知晓；观测状态仍按既有机制显示未知或中断 |
| 当前观测未知但有稳定、仍挂接 alerts 的风险周期 | 可确认已知晓风险及证据不足，不表示当前异常已被再次证实 |
| RESOLVED | 仅展示历史确认，不允许新增 ACK |
| 消退后复发／规则身份变化 | 新周期，重新待确认 |

人工字段不写入 events.payload；原阈值、状态机、三窗恢复与事件族语义不变。

## 2. SQLite Schema v2

| 新表 | 职责 |
|---|---|
| event_handling | 稳定周期及锚点事件、当前等级与 token/版本、人工 revision、本等级确认时间 |
| event_actions | 追加式 ACK 历史：幂等 ID、请求摘要、服务器时间、事件引用、当时等级、revision、本机来源和原事件快照 |
| event_handling_members | 小型关联表：绑定已确认周期的全部现有／后续等级成员，以外键保护审计所需事件 |

第三张表承担引用完整性，避免只保护首次确认的单个 code。所有外键均为 RESTRICT，连接开启 foreign_keys，不用级联删除。应用只追加操作记录，不提供修改或删除审计历史的 API；这不等于能够抵御有数据库写权限的管理员篡改。

新空库直接创建 v2。普通 Repository 和 Web 启动遇到 v1 会提示 MONITORING_SCHEMA_UPGRADE_REQUIRED / MONITORING_DATABASE_UPGRADE_REQUIRED，并在装配 Knowledge、凭据或服务器前停止；不会静默升级或重新初始化旧库。

## 3. 并发与幂等

POST /api/events/ack 复用 Host/Origin、本机来源、JSON 和 X-Management-Events 门禁。严格接收 event_id、cycle_id、grade_token、grade_version、revision、request_id；不接收操作者姓名、状态、时间或等级覆盖。

Repository 在 BEGIN IMMEDIATE 中重新核对活动 alerts、周期、当前等级、等级版本和人工 revision，同时写入状态、成员引用和操作记录；任一步失败整体回滚，不执行网络请求。

- 相同 request_id 和相同请求返回原操作回执，不再新增记录；即使之后等级已变化，该回执也只是历史提交结果。前端成功后重新读取当前详情。
- 相同 request_id 携带不同内容拒绝；新请求携带旧 revision/token 或错误周期返回冲突，不自动重试。
- 已知晓的当前等级不接受新的重复确认；消退事件不接受新的 ACK。
- 安全错误：400 参数错误、403 访问拒绝、404 记录不存在、409 状态/周期/等级/revision 冲突或不可操作、503 存储错误。不返回 SQL、文件路径或异常堆栈。

操作来源固定为 local_visitor，页面显示“本机操作（未认证访客）”；它不是可信工作人员身份。仅在当前活动风险详情提供确认按钮，用户再次确认才提交。首页与列表只显示人工状态，不增加一排操作按钮。每次读取返回最近 20 次简要确认及总数，完整记录保留在 SQLite。

## 4. 删除与留存

首个 ACK 后，当前周期的全部成员受到保护；后续新增等级在同一入库事务补入关联表。单条删除、批量清理及普通 300 条裁剪均跳过这些成员。详情和列表说明“知晓审计留存，不可删除”。外键提供额外防线，失败时事务整体回滚。

原始 events 行和每次确认的事件快照保留。batches/history 仍遵循原有留存上限；本功能不是无限保存每个原始采样窗口的档案系统。长期归档及审计保留期限另行设计。

## 5. 受控 v1 → v2 维护

以下仅是将来对**已确认的隔离副本**运行的示例，本轮没有执行任何真实库升级。实际实例必须先停止 Web、Simulator、SQLite 编辑器等写入者，确认无未知写入器，并选择可信本地文件系统上的独立备份位置。

在 Prototype 根目录执行，一行可复制：

```powershell
.\.venv\Scripts\python.exe -I -B apps\monitoring\migrate.py --database 'D:\isolated-instance\monitoring.sqlite3' --dry-run
```

确认预检后才执行：

```powershell
.\.venv\Scripts\python.exe -I -B apps\monitoring\migrate.py --database 'D:\isolated-instance\monitoring.sqlite3' --apply --backup 'D:\isolated-backups\monitoring-before-evt3a.sqlite3' --writers-stopped
```

- 源库和备份必须为绝对本地路径，拒绝网络盘、链接、junction 和硬链接文件；不创建缺失源库，不修改 ACL。
- dry-run 使用 mode=ro，检查 integrity_check、版本、必要 Schema 及活动事件引用；无效引用停止，不修复原数据。输出六张原业务表的数量、内容摘要和表定义摘要，不输出观测正文。
- apply 先取得写事务锁，防覆盖创建备份，再用独立只读连接的 SQLite Backup API 备份已提交状态，包含 WAL 中的已提交记录。
- 校验备份后，在同一事务中创建人工表及索引、设置 user_version=2；原六张表的定义、行数与逻辑摘要必须保持一致，然后提交并复核。
- 已为 v2 时返回 ALREADY_CURRENT；不重建表、不重复写记录、不覆盖备份。已有备份路径拒绝覆盖。写入停止声明不代替人工进程核查；锁冲突会失败，不杀进程。

**回退：**提交前失败自动回滚 Schema，保留备份。提交后发现问题，先停写，保留 v2、备份和所有新数据；禁止自动用 v1 覆盖。仅在确认升级后没有新写入时，才由用户批准恢复备份；有新 ACK 或监测记录时须先制定保留新数据的恢复方案。旧代码不支持 v2，不能只切回旧代码继续写新库。

## 6. 验证与后续同步

测试均使用临时 SQLite、虚构事件和 Fake 请求：首次确认、幂等、同等级、升级/降级/往返、复发、规则变化、Session/缺测/离线、重启、并发与错误版本、事务回滚、删除/裁剪保护、旧库备份迁移及 WAL、普通启动拒绝 v1、HTTP 门禁和前端确认/取消/冲突。

主要离线入口：

```powershell
.\.venv\Scripts\python.exe -B -m unittest apps.monitoring.tests.test_event_ack apps.monitoring.tests.test_monitoring_migration apps.monitoring.tests.test_event_lifecycle apps.monitoring.tests.test_event_management apps.monitoring.tests.test_event_wording -q
.\.venv\Scripts\python.exe -B scripts\dev\run_tests.py management-independent
node --test apps/management_web/tests/*.test.mjs
```

本轮通过：Targeted Python 50、Targeted Node 33；完整 Monitoring 162、管理 Web 144、Simulator 20；完整管理入口 509 项 Python、109 项 Node。测试环境为项目 .venv 的 Python 3.12.14。

1440px 与 390px 使用临时预览实际确认并刷新，人工状态保持，观测状态仍异常持续；列表同步展示，页面无横向溢出，详情宽表局部滚动。截图：[桌面](assets/EVT3A/ack-desktop.jpg)、[390px](assets/EVT3A/ack-mobile.jpg)。预览冻结逻辑时钟，截图时间为虚构观测时钟。

Management 必须在人工验收后另行批准选择性同步；先保留完整正式实例备份，再在隔离副本上试迁移和独立回归，核对既有记录/知识/Settings/Policy 不变。正式与演示 Monitoring 库分别检查版本，不能只升级其中一个，也不能在启动器里偷偷升级。正式发布须停写、明确批准维护窗口和备份路径；不复制 Prototype 真实数据库或凭据。本轮没有修改 Management。

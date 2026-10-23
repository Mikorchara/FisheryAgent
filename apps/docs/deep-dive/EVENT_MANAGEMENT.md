# EVT-2：事件族、时间筛选与历史清理

仅在 Prototype/apps 实验，待人工验收；没有同步 Management，没有修改真实数据库。SQLite user_version 仍为 1，无 Schema 迁移。水质阈值、视觉三窗恢复、AI Tool/Prompt/Scope 均不变。

## 1. 两个低氧事件为什么并排

隔离实测 DO 4.2 → 2.2 mg/L：OXYGEN_LOW 从 warning/ACTIVE 变为 INDETERMINATE，原因 OTHER_RISK_CONDITION_ACTIVE；同时创建 critical/ACTIVE 的 OXYGEN_CRITICAL_LOW。两个 alerts 关联仍保留。旧机制按 code 管理周期，严重等级切换不提供恢复证明；原页面把等级变化与观测不足统一显示为未知。

阈值仍由 diagnosis.py 唯一拥有：DO <1.0 极低、<3.0 低、<5.0 偏低。本轮没有调整它们。只读过期投影使用 STALE_OR_OFFLINE，避免保留上次等级变化原因；该合并原因不能单独证明设备离线。

### EVT-2 文案收尾：显示语义不改变生命周期

首页、事件列表、详情及详情内关联成员共用 `eventStateName()`；详情用 `eventStateReasonName()` 展示中文解释，原原因代码仍保留供核对。

| 显示条件 | 最终文案 |
|---|---|
| INDETERMINATE、OTHER_RISK_CONDITION_ACTIVE，且同族当前可靠等级高于该记录；当前为 OXYGEN_CRITICAL_LOW / EXTREME | 已升级为严重低氧 / 已升级为极低氧 |
| 其他同指标等级转换，或旧数据不能证实升级方向 | 同指标等级已变化 |
| 当前设备已被既有分析判定 offline，或明确收到缺失视觉通道的报文 | 监测数据中断 |
| 其他 INDETERMINATE：仅过期但仍 online、无效/不完整/缺少证据、规则变化、旧记录 | 恢复状态待确认 |
| ACTIVE，视觉可靠 CLEAR 计数 1 或 2 | 恢复观察中 1/3 或 2/3 |
| ACTIVE，非恢复观察 | 异常持续 |
| RESOLVED | 规则条件已消退 |

视觉消退详情明确为“连续可靠观测未再检出该异常信号”，不代表疾病治愈或人工处理完成。历史 `visual_recovery.continuity=interrupted` 可能记录过去的窗口不连续，不能仅凭它断言当前离线；页面改为说明“历史观测存在不连续”。无活动事件的空状态仍沿用严格的可靠观测门禁，未知不显示正常。SIMULATOR 来源说明保留。

`EventService.project()` 只读追加 `current_data_quality`（quality/freshness/connectivity）；`project_families()` 依据既有等级序号追加 `family_level_change`，并投影到关联成员。两者不落盘，不改变 status、lifecycle_state、state_reason、code、阈值、时间或恢复规则。没有 Schema 变化、历史回填或人工管理能力；旧 payload 缺少这些字段时保守显示，不猜测标题字符串。

本次文案收尾离线验证：Targeted Python 32 项、Targeted Node 30 项通过；完整 Monitoring 144、管理 Web 144、Simulator 20、管理 Node 106 项通过。新增合成事件验证查询前后原 payload 不变、旧族投影、离线与仅过期的区分、三窗恢复及 Bootstrap/列表/详情字段一致；真实页面代码的 DOM 回归核对首页、列表、详情和关联成员文案。本次未启动浏览器或真实数据实例，下面 EVT-2 原验收截图未重新生成。

## 2. 关联方式与证据

`monitoring/event_families.py` 只关联相同设备、通道、指标、风险方向与规则身份的未结束 code 周期。低氧三级属于同族；温度/pH 的偏高、偏低各自独立。视觉各类信号不合并，不跨设备或规则范围强行合并。

保留原事件 ID、occurred_at、批次、恢复时间和 alerts；新增 events.payload.risk_family。episode_id 是事件族身份，不是必须存在的数据库外键。等级变化在原 ingestion 事务内保存观测时间、原始指标统计、Batch/Session/Sequence、窗口引用和等级，快照复制到成员，单条删除历史成员不会抹去其他成员已保存的变化证据。

为限制 payload 大小，保留首次和最近 99 次变化，公开 omitted_transitions 数量；未做无限归档。连续同等级窗口继续更新原事件，不重复追加变化。恢复后新异常形成新族周期。

首页每个未结束事件族显示一项，优先选择有当前可靠 HIT 的等级；证据中断时仅保留一个“当前等级未知”提示，不把历史最高等级冒充当前判断。原始等级记录在历史表与详情中保留。旧 payload 只读兼容；只有可确定同一身份、仍未结束的旧成员才保守关联，不回算缺失的历史变化。身份不明的旧记录不强行合并。

新 Session 自身不关闭事件；恢复仍须显式可靠 CLEAR。缺测、离线不能提供 CLEAR，视觉继续遵守 EVT-1 连续同 Session 三窗门槛。

## 3. 时间筛选与分页

`GET /api/events`：lookback_minutes=5/10/30/60/all（默认 all），q、severity、status 可组合；limit 默认 50、最大 100，offset 默认 0。先查询完整留存集合、投影当前状态、组合筛选，再分页；不对 Bootstrap 的最近五条做过滤。

时间含义是**事件关注区间与所选时段相交**：起点为 occurred_at，结束事件终点为 resolved_at，未结束事件保持关注。发生很早但未结束的事件仍在最近五分钟中；未知期间不等于持续检出。边界相交计入。关闭但缺少可靠恢复时间的旧记录只在“全部记录”中保守展示。

历史表显示“首次发生”时间，详情另有最近信号、有效观测和恢复时间。首页活动概况始终读取独立的完整 Bootstrap 事件，不受历史筛选和分页影响。“全部记录”只含仍留存数据，不能找回已裁剪记录；原有 300 条历史加全部活动关联留存规则不变。

## 4. 引用检查与硬删除

现有 events/alerts 没有 SQLite 声明外键。alerts.event_id 是应用维护的活动关联；payload.superseded_by 是事件替代引用。Batch/Observation 引用、事件族 episode_id 和变化条目的 event_id 是历史证据标识。

仅同时满足以下条件的记录可硬删除：

- lifecycle_state=RESOLVED、status=closed，具有有效恢复时间；
- 没有任何 alerts 关联；
- 没有其他留存事件以 superseded_by 引用它。

ACTIVE、恢复观察、未知、旧 closed 但恢复证据不明的记录，以及被引用的已结束记录均保留。事件族变化快照保留历史标识及证据，详情关联列表只列仍存在的记录。

单条删除一次确认；批量先核对范围，再最终确认。批量范围为**全部设备、全部时间的可删除记录，忽略当前筛选与分页**，两步均显示服务端预计数量。取消或 Escape 不提交删除。

端点：

| 端点 | 行为 |
|---|---|
| POST /api/events/deletion-preview | 返回 scope/event_id/count/revision，只预览，不删除 |
| POST /api/events/delete | 提交相同 scope/event_id 和 revision，执行硬删除 |

两者要求回环来源、允许的 Host/Origin、JSON 和当前应用生成的 X-Management-Events 能力令牌（Bootstrap 下发，仅内存使用）。严格拒绝额外字段；客户端状态/数量不参与授权。它是本机开发维护边界，不是生产账户权限系统，也不提供 AI Tool 写能力。

提交在 BEGIN IMMEDIATE 内重新读取所有候选及引用，以实际 ID/原 payload 计算 revision。新增、删除、编辑候选或关联状态变化时拒绝过期计划，不自动重试；事务锁防止候选校验与删除交错。单条重复请求返回未找到；重复旧批量计划冲突；空集合可安全返回删除 0 条。数据库错误整体回滚。

只 DELETE events，不删除 alerts，不操作 history、batches、current、Knowledge、Settings、Policy、Credential 或 Trace。成功后重新读取首页、列表及数量，并撤销旧轮询请求的覆盖资格。硬删除不可在应用内撤销；没有伪装为删除的隐藏或软删除。

## 5. 离线验收

在 Prototype 根目录执行：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s apps\monitoring\tests -q
.\.venv\Scripts\python.exe -B -m unittest discover -s apps\management_web\tests -q
.\.venv\Scripts\python.exe -B -m unittest apps.simulator.tests.test_simulator -q
node --test apps/management_web/tests/*.test.mjs
```

测试使用临时 SQLite、虚构观测和 Fake SDK。覆盖低氧升降级与恢复、多设备/方向、可靠/未知、三窗机制、五档筛选和边界、分页前筛选、单条/批量清理、取消、SQLite 并发修改、alerts/superseded_by 引用保护、重复请求和旧记录。

本轮结果：Monitoring 140、管理 Web 144、Simulator 20 项 Python 通过；管理 Node 104 项通过。1440/1024/900/390px 下首页每族一项，最近事件保持通栏，事件宽表局部横向滚动、无页面横向溢出。浏览器实测五分钟筛选、批量两步确认后取消、单条隔离记录删除后 11→10 条及等级详情；没有操作真实实例。控制台无警告/错误。

实现入口：`monitoring/event_families.py`（关联/变化快照）、`event_records.py`（关注区间和删除资格）、`repository.py`（事务/引用检查）、`service.py`（查询投影）、`events.py`（过期原因）；`management_web/event_api.py` 与 `app.py`（维护门禁/HTTP）、`static/{app.js,view-model.js,services.js,styles.css}`（交互）；对应 `test_event_management.py`、`monitoring-ui.test.mjs` 和隔离 `event_preview.py`。README/ROADMAP/STRUCTURE/INTEGRATION 已同步说明。

隔离页面预览：

```powershell
.\.venv\Scripts\python.exe -I -B apps\management_web\tests\event_preview.py --port 8788 --evt2
```

访问 http://127.0.0.1:8788；临时数据库、不装配 AI/凭据/上报，十分钟自动退出或 Ctrl+C。测试结束后临时数据回收；不连接正式或原演示实例。

截图：[首页](assets/EVT2/home.jpg) · [事件页桌面](assets/EVT2/events-desktop.jpg) · [390px](assets/EVT2/events-390.jpg) · [等级详情](assets/EVT2/family-detail.jpg) · [批量最终确认](assets/EVT2/confirmation.jpg)。

人工验收后，才可选择性同步 Management 并独立回归。完整历史归档、人工确认、生产账户/远程维护权限均未实现。

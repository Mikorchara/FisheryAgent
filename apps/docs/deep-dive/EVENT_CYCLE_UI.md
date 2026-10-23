# SIMPLIFY-1：事件按风险周期展示

仅在 Prototype 实施，等待人工验收；未同步 Management。不包含归档或人工结束。后续经用户明确批准增加已结束 ACK 周期永久删除，详见下节；Schema、监测阈值及视觉三窗恢复保持不变。

## 实现

- `monitoring/event_cycles.py:summarize_cycles` 为只读摘要，复用 ACK 的 `cycle_reference` 稳定身份。无法可靠归族的旧记录按原 ID 独立展示，不使用 inferred / legacy-* 强行合并。
- 所有原始事件完成服务端投影后先整合，再按时间关注区间、关键词、等级、状态筛选及分页。关键词搜索涵盖全部周期成员的名称、code 和 ID。活动按当前可靠等级筛选；已恢复按留存证据中的最高等级筛选；未知不冒充旧等级为当前可靠等级。
- 原 `GET /api/events` 默认仍返回原始记录，兼容旧消费者。新增 `view=cycles` 只读选项；不接受其他 view 值。列表计数单位为周期，不是底层事件行数。
- Bootstrap 保留 `events`，额外返回同一份原始读取结果生成的 `event_cycles`，首页当前异常与最近事件使用该字段。原 `GET /api/events/<原始ID>` 与 ACK 请求合同不变。
- 活动显示当前可靠等级及最新异常观测；已恢复显示周期首次发生、恢复时间、历史最高等级和“异常时读数”。留存等级轨迹可补充已被普通历史裁剪的等级证据，但不补造不存在的观测。
- 主列表使用“异常中／状态待核实／已恢复”；旧版已结束但未复核的记录继续显示原兼容文案。恢复观察仍未结束，进度在原详情中查看。另设“是否确认”列，仅显示“已确认／未确认”，不混入观测状态；确认绑定当前／结束前最后等级，而非只要曾 ACK 就算已确认。
- 低氧名称按可靠当前 code 投影“溶解氧偏低／溶解氧低／溶解氧极低”；结束后用历史最高等级，未知显示等级待核实。原始证据、规则 code 与阈值不变。
- 已可靠恢复的状态标签使用浅蓝底、深蓝字；旧版已结束但未复核的记录仍保持中性灰色，不以颜色暗示已确认恢复。
- 详情入口重新读取原始事件，保留等级变化、关联事件 ID、批次与 ACK 历史。摘要不能直接当作整周期删除对象。

## 删除边界

主要文件：`apps/monitoring/{event_cycles,event_records,service}.py`、`apps/management_web/app.py`；前端 `static/{app,services,view-model}.js`、`static/styles.css`；测试 `apps/monitoring/tests/test_event_cycles.py`、`apps/management_web/tests/{monitoring-ui,view-model}.test.mjs`。文档入口及目录索引同步更新。

初版只做 SIMPLIFY-1；后续用户已明确授权删除整个已结束周期及其 ACK 历史，不保留独立审计快照。

无 ACK 且符合原条件的已结束原始记录仍可单条删除。有 ACK 的可靠已结束周期增加独立“删除已结束周期”：预览原始成员及 ACK 数，明确确认后在同一事务删除其全部事件、操作和成员关联。只要有活动/未知成员、告警关联、外部引用、成员不完整或 revision 变化即拒绝；外键保持开启，任何 SQL 错误整体回滚。确认历史将永久丢失，不承诺永久审计留存。既有“清理全部已结束事件”仍跳过 ACK 周期，不自动删除真实数据。实现见 `monitoring/event_cycle_deletion.py`，不改 Schema v2。

## 验证

### 后续确认列与已结束周期删除

- 完整 `management-independent` 回归：527 项 Python、115 项 Node 全部通过。最后补充“只删目标周期、其他活动 ACK 周期及重启状态不变”用例后，ACK 删除及启动器专项共11项通过；最后文案调整后前端页面专项24项通过。
- ACK 删除专项7项覆盖：可靠结束整组删除、观测保留和外键检查；活动/未知拒绝与普通批量保护；旧 revision 冲突、SQL 失败整笔回滚；外部引用/缺成员拒绝；HTTP 本机与 Token 门禁；当前/最后等级的确认语义；不同周期隔离与重启。
- 原生成器 `oxygen_drop_recovery / seed=42 / 360秒` 共36窗口，合同全部通过，低氧先偏低再严重，最终一条已恢复水质风险周期；不修改阈值，不发送 HTTP。新增场景被两处原启动器枚举接受，PowerShell 语法检查通过，未启动真实用户实例。
- 浏览器使用 `event_preview.py --ack-cycles --port 8789` 的临时 v2 数据，1440px 与390px检查确认列、动态低氧名称、已结束ACK周期预览和取消。取消后记录仍在；实际删除、回滚及权限由隔离 SQLite/HTTP 自动化测试验证。宽表在容器中滚动，窄屏无页面横向溢出，控制台无错误。
- 截图：[桌面](assets/ACK_CYCLE_DELETE/events-desktop.png) · [390px](assets/ACK_CYCLE_DELETE/events-mobile.png) · [删除预览](assets/ACK_CYCLE_DELETE/delete-preview.png) · [窄屏删除提示](assets/ACK_CYCLE_DELETE/delete-mobile.png)。临时预览已关闭，未触碰真实数据或凭据，Management 未修改，没有 commit/push。

### 初版 SIMPLIFY-1 记录

- 5 项周期专项：偏低→严重→ACK→恢复；周期复发；未知、旧记录及设备隔离；视觉三窗恢复；54 条原记录先整合为 27 个周期再筛选分页；HTTP Bootstrap、原始详情和 view 参数。查询前后原 payload 不变。
- 完整 management-independent：520 项 Python 通过（包含 Monitoring、Simulator、管理 HTTP 等）；最终完整 Node 113 项通过。新增前端用例核对服务端周期字段、三态显示、原详情读取及历史读数标签。
- 隔离预览使用 `tests/event_preview.py --evt2 --port 8789`，只生成虚构窗口，冻结逻辑时钟，未启用 AI / Provider / NPU、真实知识库或上报。浏览器实际执行一次 ACK 并核对仍 ACTIVE、知晓历史和删除保护。
- 1440px 与 390px：页面无横向溢出，窄屏宽表在容器内横向滚动，详情宽度 360px；无控制台错误。筛选“溶解氧”后，展示三个独立周期，每个周期包含两个等级，不是把不同周期合并。

截图：[桌面](assets/SIMPLIFY1/events-desktop.png) · [390px](assets/SIMPLIFY1/events-mobile.png) · [390px详情与ACK](assets/SIMPLIFY1/detail-mobile.png)。截图均为虚构数据。

本轮没有读取或修改真实业务数据库、Settings、Policy、凭据或 Management，没有 commit/push。预览结束后关闭本次临时服务器并释放 8789，临时 SQLite 自动清理。

## 人工验收

在原启动终端 Ctrl+C 后重新运行 `scripts/dev/run_local.ps1 -Scenario normal`，刷新网页加载新代码。核对列表每周期一行、恢复时间及历史读数；点击详情仍可查看各原始 ID、等级证据和 ACK。启动 Simulator 会按原机制继续写入当前实例的模拟观测，本轮没有替用户启动真实实例。

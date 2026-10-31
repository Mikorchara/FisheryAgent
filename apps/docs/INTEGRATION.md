# 统一监测协议与集成边界

当前 Prototype 的 EVT-3A 新增本机 ACK，人工状态与 Monitoring 生命周期独立；Schema v2 和独立人工/操作/成员表不改变 v1 上报 DTO、规则阈值或 AI Tool Scope。旧 v1 库须显式维护，ACK 审计周期同时受删除和自动裁剪保护。[当前合同](deep-dive/EVENT_MANAGEMENT.md)。下文 R2B/EVT-1/EVT-2 的 Schema v1 描述保留当时实现脉络。

AI 的扩展操作见 [AI Backend 与 Assistant 开发指南](deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)；本文件维护当前数据/应用边界。带 R 阶段编号的章节保留来源脉络；MIG-1 后正式管理运行链及 Monitoring 领域合同均不导入旧 fishery_ai。

R2D-2C 本机聊天确认方式：主动点击「发送」或 Ctrl+Enter 授权一个 Turn，前端随冻结的设备、epoch/revision 提交 `confirm_network=true`，不再保存勾选状态。底层确认合同及 Host/Origin、浏览器令牌、Tool Policy、Scope、预算、唯一 claim、取消和提交校验不变；缺少确认或配置过期仍在凭据/模型 I/O 前拒绝。刷新可用状态、切换模式与 History 恢复只读，不自动重发。此规则不扩展到远程生产接口或人工资格 CLI；下文旧阶段关于勾选确认的操作以此为准。[当前网页操作](deep-dive/PROTOTYPE_RUN_REFERENCE.md#一行式常用命令)。

R2D-3B：管理知识只读写统一SQLite，导入内置与用户知识均可管理；不再导入旧 KnowledgeService/Evidence，也不运行时读取旧JSON。下列R阶段对旧固定资源/共享Policy的描述保留历史脉络，当前知识入口以[统一知识库](deep-dive/KNOWLEDGE_CONTENT.md)为准。迁移须单独批准，旧文件不移动或覆盖。

## 1. 当前运行链路

MIG-2：数据路径由 `apps.management_paths.ManagementPaths` 在启动时统一选择；未提供参数仍用原工作区。显式 `--data-root` / `--user-data` 使用独立实例，两个数据库先只读预检，全部成功才装配；`--init-data` 仅创建空白新实例并退出，绝不隐式迁移。Settings、管理 Policy/同实例共享兼容 Policy 和 Trace 同根，Credential Store 保持独立。详见[实例生命周期与发行边界](deep-dive/MANAGEMENT_STANDALONE.md)。

知识内容的独立链路为 Web → `apps.knowledge` → `apps/knowledge_data/knowledge.sqlite3` / 原算法的独立 TF-IDF；管理 AI 装配注入同一服务供只读 Knowledge Tool 查询，不依赖 Monitoring 数据库，也不增加 LLM 写能力。原始来源/编辑版本、显式迁移、导出备份、快照、精确源 Scope 和本机写入合同见[知识内容管理](deep-dive/KNOWLEDGE_CONTENT.md)。

```text
Simulator：Scenario → 逻辑采样 → 10 秒窗口 → HTTP
    → management_web Ingestion：本机与令牌检查
    → monitoring.contracts：v1 严格校验
    → DomainAnalysisService：时间/上下文 → rules → Findings
    → MonitoringRepository：单事务保存 water / visual
        → EventService：计算事件变更 → 同事务持久化
    → MonitoringService：统一查询、历史、Web 投影
        → Dashboard / Monitoring / Video / Events
        → capture_water(device_id) → AI Tool 精简投影（与网页同源）
```

`apps/monitoring/` 不依赖 Flask 或页面。Web `create_app(data_service=...)` 将同一服务用于监测、视觉和事件；CLI 正常入口总是装配 SQLite 服务。无 data_service 的工厂保留 R1 测试/兼容 Demo；CLI 必须显式 `--legacy-demo` 才使用它，接入失败不回退 Demo。

MIG-1：`water_contracts.py` 拥有管理端 WaterQualityReading、Quality/Freshness、时间校验及 RuleFinding；`diagnosis.py` 是管理端唯一水质阈值实现，保留原算法、文本及版本。`current.py` 保留 bind().water_reader 的只读接口，读取既有设备来源一次、只更新返回副本的新鲜度，不创建第二个 Snapshot Store。`analysis.py` / `rules.py` / Assistant sources 使用同一套新类型；旧 Prototype 自身实现不变。

领域类身份有意独立：Python 中新旧 dataclass 不作为同类互换，构造器仍拒绝另一侧枚举；JSON 字段、枚举字符串、Tool DTO、Receipt 和规则结果不变。历史 RULE_VERSION `fishery-production-c400b7a-v1` 仅保留兼容身份，RuleIdentity 继续是 PROTOTYPE。

普通管理测试的固定知识来自 `apps/knowledge/tests/fixtures/`，不从旧包定位资源。新旧领域/Runtime 对拍、历史资格和旧数据迁移仍可显式依赖旧包或旧 JSON；它们不是产品启动依赖。`test_backend_migration` 在新进程中阻断整个 fishery_ai 包，并经实际管理 HTTP/SSE 执行三工具路径及统一知识 SQLite 流程；`test_domain_compatibility` 保留新旧字段、拒绝、阈值、Reader 和来源认证差分。

独立项目尚需后续处理根打包/启动/测试入口、历史资格夹具和数据路径；MIG-1 不迁移 SQLite、Policy、Settings、凭据或项目身份。离线入口：`python -m unittest apps.monitoring.tests.test_domain_compatibility apps.ai_service.tests.test_backend_migration -q`，以及 `python scripts/dev/run_tests.py management`。

## 2. HTTP v1 批次 DTO

`POST /api/ingestion/batches`，Content-Type application/json。示例是虚构窗口，不包含令牌：

```json
{
  "schema_version": 1,
  "batch_id": "example-batch-1",
  "session_id": "example-session",
  "sequence": 0,
  "device_id": "sim-pond-1",
  "timestamp": "2026-10-14T00:00:10+00:00",
  "window": {
    "start": "2026-10-14T00:00:00+00:00",
    "end": "2026-10-14T00:00:10+00:00",
    "duration_s": 10
  },
  "water": {
    "aggregation": "window_mean",
    "sample_count": 10,
    "metrics": {
      "temperature_c": {"unit":"°C","mean":26.4,"min":26.3,"max":26.5,"latest":26.4,"valid_samples":10,"invalid_samples":0},
      "ph": {"unit":"","mean":7.5,"min":7.4,"max":7.6,"latest":7.5,"valid_samples":10,"invalid_samples":0},
      "dissolved_oxygen_mg_l": {"unit":"mg/L","mean":6.4,"min":6.3,"max":6.5,"latest":6.4,"valid_samples":10,"invalid_samples":0}
    }
  },
  "visual": {
    "aggregation": "window_summary",
    "frames_processed": 20,
    "valid_frames": 20,
    "anomaly_counts": {"suspected_lesion":0,"surface_anomaly":0,"suspected_dead":0},
    "behavior_ratios": {"normal_activity":0.8,"reduced_activity":0.1,"feeding":0.1,"feeding_anomaly":0,"unknown":0},
    "length": {"average_length_cm":null,"length_sample_count":0,"valid_frame_count":0,"calibration":"uncalibrated","calibration_id":null},
    "visible_fish_count": 8.5,
    "model_version": "synthetic-visual-v2"
  }
}
```

固定结构拒绝未知/重复 JSON 字段，拒绝 NaN/Infinity、bool 代替数值、非法类型/单位/范围。ID 限制为 1–64 个 ASCII 字母数字、下划线或连字符，device_id 须在服务器 allowlist；默认只有 sim-pond-1。

时间必须带时区并归一化 UTC；timestamp = window.end。窗口 1–60 秒，duration 与起止一致；未来时间或超过 300 秒延迟拒绝。水质物理范围复核温度 -50–100°C、pH 0–14、DO 0–100 mg/L；这不是水质风险阈值。

R2B-2 时间修正：monotonic 到点不保证 UTC 窗口已经结束，旧发送逻辑可在提前唤醒/两种时钟偏差时发送未来窗口。生产端现在发送前确认 UTC 已到 window.end；最多 1 秒等待预算 / 3 次检查，仍未完成或明显时钟偏差则 SIMULATOR_CLOCK_OUT_OF_SYNC 并关闭 Reporter。窗口时间不重写，服务端未来/超过 300 秒拒绝保持不变。联调已去掉一秒人为缓冲；确定性测试复现默认 10 秒周期的 UTC 提前 5ms 情况，并验证修复。两个进程/真实设备的时钟同步、系统大幅跳时仍属部署限制，不无限容忍未来数据。

water 或 visual 可以为 null，但不能同时为空。两个通道独立更新；缺失通道不复制另一通道，也不清掉其末次记录。接收时间由服务器生成，客户端不能指定 source、quality、freshness、received_at 或真实设备标识。

## 3. 窗口与业务语义

- 窗口定义为 (start, end]，默认 10 秒。水质逻辑采样默认每 1 秒，视觉逻辑帧默认每 0.5 秒；与上报周期独立，周期须整除窗口。本模拟器在推进窗口时生成逻辑样本，不执行真实采集或视频推理。
- 温度、pH、DO 的 water.mean 是各指标**窗口内有效样本的算术平均**，输出保留三位小数，不是单次值。每个样本按其采样时的通道状态、缺失/无效标记与物理范围过滤，不使用窗口结束状态代替整窗质量。min/max/latest 同样只包含有效样本；valid_samples + invalid_samples ≤ sample_count，差值为缺失样本。有效数为零时四个值都必须 null。
- R2B-1：原始窗口均值和样本证据仍完整保存。每指标质量分 valid / partial（有效覆盖不完整）/ invalid / missing。Reader 只投影完整有效指标，其他指标为 None；任一 invalid 样本或无可用指标使 canonical Reading 为 INVALID，部分可用为 PARTIAL。独立 analysis.data_quality 保留原始质量与覆盖，避免把总体 INVALID 误解为所有指标都不可判断。
- 完全未收到 water 是 NO_DATA；已有全缺失/无效窗口仍是一个存在但不可用的 Snapshot。STALE 和连接 OFFLINE 是独立时间维度，不能改成正常。
- 视觉 frames_processed 是窗口内尝试的帧数，valid_frames 是有效帧数，无效帧不参与统计。anomaly_counts 是每类信号出现的有效帧数，类别可重叠；全零只表示有效帧未出现所列信号，不证明健康。疑似病灶、体表异常、疑似死亡均为检测信号，非最终疾病诊断。
- behavior_ratios 是互斥行为的有效帧比例，总和为 1；没有有效帧时均为 0，页面显示“无有效帧”，不能解释为正常活动。无有效视觉帧不使已有异常事件自动消退。
- **画面平均可见数** = 有效帧可见鱼数之和 / valid_frames；零鱼帧计入，无效帧排除。valid_frames 为 0 时 visible_fish_count 为 null，不是 0；不是累计鱼数或鱼池存量。
- **窗口平均体长** = Σ(帧平均体长 × 该帧有效体长测量数) / Σ(有效体长测量数)，等价于所有有效体长检测记录的算术平均，保留三位小数。两帧分别 2 条有效测量、均值 10 cm 和 6 条、均值 20 cm，结果 17.5 cm。length_sample_count 是有效体长检测记录总数，valid_frame_count 是有有效体长测量的帧数；测量数不一定等于可见鱼数，零鱼帧无体长测量。重复检测记录不代表独立鱼个体，更不代表全池平均体长。
- 默认未标定：体长 null、测量数/体长有效帧数为 0。手写 Phase 可启用纯 simulated 标定，同时提供模拟 calibration_id；逐帧检查标定状态，不宣称真实厘米精度。
- 上述帧数为 v1 的受限可选统计字段，旧 v1 批次仍可接收，已有 SQLite 不迁移、不回算旧窗口。新生产端 model_version 为 synthetic-visual-v2；旧体长计数曾表示帧数，页面明确标为旧语义，不冒充新的测量计数。新增字段仍严格校验，拒绝额外未知字段和相互矛盾的统计。
- model_version 保留模型来源位置，当前只有 synthetic 生产端。未来 boxes、track IDs、受控媒体引用须增加受限合同/版本，不使用任意扩展字典或本地路径；R2A 未生成截图、录像或检测框。

## 4. SQLite 与状态生命周期

`outputs/management_web/monitoring.sqlite3`，Git ignored；schema user_version=1，未知版本拒绝，不自动改未知数据。标准库 SQLite 每操作短连接、事务提交/关闭；每设备每通道 current 一份，water/visual 不混合。

默认每设备每通道保留 360 个窗口（10 秒周期约 1 小时），每设备 1440 个批次幂等记录。EVT-1 保留全部 alerts 关联的未结束事件，另保留最近 300 条未关联历史，总事件数可超过 300。超限按最旧历史裁剪；SQLite 可复用空闲页，不承诺文件立即缩小。重启保留数据，不删除旧库。

- 同 batch_id 或 device/session/sequence 的相同有效内容返回 duplicate，不再次入库/造事件；内容冲突返回 409 BATCH_ID_CONFLICT。幂等受有界记录和观测时间限制。
  有效 duplicate 或乱序批次只刷新独立的通道接触时间，不改原观测/接收时间；在线不代表数据新鲜。
- 乱序有效窗口保留历史；只有比该通道 current 更新的观测才推进 current 和事件。相同观测时间的新批次拒绝 OBSERVATION_CONFLICT，防止歧义覆盖。
- 新 session 可从 sequence=0 重启；排序依赖规范化观测时间，不依赖客户端 sequence 或收到先后。
- 一个批次验证失败不写任何通道/事件，不更新在线状态；成功批次及事件变更处于同一事务。
- 当前水质与其历史在同一读事务捕获。不同页面/通道读取可能有各自查询时点，保留各自批次和时间，不声称整个网页是一次原子观测。

查询时复用 Domain evaluate_freshness，默认观测超过 30 秒为 STALE；通道 last_reported_at（最后有效接触）超过 90 秒为 OFFLINE，未接收为 never_received。按通道判断，另一通道持续上报不能掩盖失联。延迟/乱序窗口可在线但已过期。原 current 的 received_at 始终保留首次接收时间，查询不改原观测或创建事件。

事件只由实际接收且推进 current 的批次产生；重复/乱序仍不重建事件。R2B-1 只有显式 CLEAR 且规则 Identity 匹配，才能写入 RESOLVED（兼容 status=closed）。HIT 为 ACTIVE，数据/覆盖不足为 INDETERMINATE；后两者兼容 status=pending，均不表示已人工处理。Finding 消失不能作为恢复证明。事件保留真正的 severity 与 finding_severity、规则状态、最近命中/最近评估/恢复的观测引用。

同规则持续命中保留首个 ID 与批次，并更新最近命中、标题、等级。规则版本/范围/评估策略变化不得合并或判旧异常恢复；新版本命中产生独立事件，旧事件待确认并关联 superseded_by。SQLite schema 仍为 1，无表迁移或历史回算；旧事件只在读投影补 PROTOTYPE / INDETERMINATE / LEGACY_UNREVIEWED，旧 severity 优先用 finding_severity。旧 closed 仅保留历史兼容字段，不冒充新合同下的可靠恢复；只有可靠的新评估才更新仍活动的旧事件。

同一指标的异常从一个严重程度 code 切换到另一个（如低氧进一步恶化）也不等于恢复；只要该指标还有其他 WATER_RISK 命中，旧事件保持待确认，原因 OTHER_RISK_CONDITION_ACTIVE。该指标获得可靠无风险评估后，才可确认相关事件解除。

EVT-2 保留各 code/ID，使用事件 JSON 的 risk_family 关联相同设备、指标、方向与规则身份的等级变化；首页每族只展示当前可靠等级，旧等级显示“同指标等级已变化”，缺测/过期仍为未知。GET /api/events 按关注区间相交筛选 5/10/30/60 分钟或全部，再服务端分页（默认50、最多100）。POST /api/events/deletion-preview 与 /api/events/delete 使用本机独立能力令牌，只硬删除明确 RESOLVED、无活动或替代引用的历史记录；批量不受当前筛选影响。没有 Schema、阈值或 AI Scope 变化。[关联、证据、删除与并发合同](deep-dive/EVENT_MANAGEMENT.md)。

过期/离线时 events() 只将当前确定性撤回为 INDETERMINATE 的只读投影，不写入新事件、不修改历史。完全缺失通道的批次不覆盖该通道 current；EVT-1 对缺失视觉通道的有效新批次同事务重置视觉恢复进度、记录缺测时间水位，防止迟到旧窗重新提供恢复证明。事件初次批次可能因保留限额被裁剪，事件自身保留时间、来源与首末引用。

EVT-1：四种视觉异常的 RESOLVED 需要三个连续可靠 CLEAR。Session 相同、Sequence 连续、窗口首尾相接、完整有效且 fresh/online、前一证据未过期才累计；中断后从当前可靠窗重新计数，HIT 保留原 ID 并清零。恢复进度保存在事件 JSON，查询不推进计数；水质恢复判定不变。视觉消退表示“连续观测未再检出”，没有人工确认语义。[详细合同与离线验证](deep-dive/EVENT_LIFECYCLE.md)。

### R2B-1 分析合同与规则状态

- Observation / Facts：现有 metrics / visual summary 是收到的事实；ObservationRef 明确 device/channel/batch、来源、窗口、聚合方式及观测/接收时间。独立通道保留各自时间，不做跨通道融合。
- DataQuality：quality、freshness、connectivity 独立；coverage 记录每指标有效数/计划数或有效帧/总帧。NO_DATA 表示没有该通道 Snapshot，已有全缺失窗口仍是存在的观测。
- MonitoringFinding：code、kind、state、severity、facts_used、rule、observation、reason。state 为 HIT / CLEAR / INSUFFICIENT_EVIDENCE / NOT_EVALUATED；非 HIT 的 severity 为 null，不把数据不足变成风险严重程度。DATA_QUALITY 与 WATER_RISK / VISUAL_SIGNAL / BEHAVIOR_SIGNAL 分开。
- ChannelAnalysis：只包含本通道事实引用、DataQuality、完整 Finding 评估和 evaluated_at；不再复制原始观测 payload。snapshot.analysis / cameras[].analysis 为增量公开投影，旧 metrics/summary/findings 字段保留。旧 findings 仅显示 HIT，完整 CLEAR/无法判断状态在 analysis 中。
- RuleIdentity：rule_id、version、scope、publication_status、assessment_policy_version。旧水质计算版本保留，所有规则强制 PROTOTYPE；名称含 production 不提供批准依据。当前范围为 simulator + water/window_mean 或 visual/window_summary，养殖适用性未确认；不能由 HTTP 上报指定规则或批准状态。
- 水质仍调用 DiagnosisService，不复制阈值。临时保守证据门禁：每指标完整有效采样、fresh、online 才判断命中或解除；无效/覆盖不足指标不传入风险诊断，其他完整指标独立判断。完整覆盖是技术防误判条件，不是新增养殖阈值；后续放宽须人工确认。
- 视觉有效部分中明确出现信号可形成有限 HIT（疑似检测信号，非疾病诊断）；部分覆盖无信号不能形成 CLEAR。只有完整有效且 fresh/online 的窗口可说明所列信号未出现，不证明鱼群健康。
- rules.py 只负责确定性条件与证据门禁，水质调用原 DiagnosisService。R2B-2 的 DomainAnalysisService 统一通道求值与时间/设备检查，EventService 统一状态转换与只读投影；两者都不依赖 Flask、SQLite、模型或网络。趋势规则尚未实施；现有管理 Assistant 桥接见下文 R2B-3。

历史 API 保留原 summary；当前趋势展示将无效/覆盖不足均值置为 null，并附 metric_quality，不把历史不可用均值连成可靠趋势。

### R2B-2 业务服务边界

- `analysis.py / DomainAnalysisService.evaluate(device_id, channel, row, evaluated_at=...)` 是纯计算入口：输入已验证的服务端事实，统一 freshness/connectivity，再委托 rules。设备不匹配或评估时间早于接收时间拒绝；没有规则副本或隐式采样。canonical Reading 投影也放在这里，`service.reading_from_row` 保留 import 兼容。
- `events.py / EventService.transition(existing, assessment)` 返回 EventChanges（updates / inserts / active_links / resolved_codes），不执行 SQL。`project(event, assessment)` 只撤回当前确定性，不确认恢复；版本匹配及严重程度切换策略共用同一处 helper。输入不修改，旧记录兼容投影也由此统一。
- Repository 在原 `BEGIN IMMEDIATE` + 锁中读取活动事件、计算变更并应用 SQL；current、历史、事件、alerts 和接触时间仍整体提交/回滚。重复与乱序不推进事件；缺失视觉通道的新观测会撤回连续性。未更换 SQLite 或表结构；EVT-1 调整事件保留策略以保护未结束事件。
- MonitoringService 协调设备范围、读写与展示；`capture_water(device_id)` 和绑定后的 `DeviceReadContext.capture_water()` 返回一次事实捕获及分析。`analysis(device_id, "water")` 从同一入口取得 ChannelAnalysis；visual 仍独立求值。现有 water_reader 保留兼容，管理 AI 不使用它再次诊断风险。
- snapshot/cameras 不再重复计算时间状态；当前事实先捕获，再选 evaluated_at。同一 events 查询对每 device/channel 只求值一次；不同查询仍按各自时点更新，不建会过期的全局分析缓存。
- 每通道仍独立，窗口和设备引用明确。本阶段没有增加跨通道关联规则；以后要关联必须校验设备/池映射和时间重叠，不能仅因同一页面或批次到达就认为同步。

## 5. 场景编写与连续运行

`apps/simulator/scenarios.py` 用 frozen Phase 列表定义全局 elapsed 时间线；按 at_s 升序，从零开始。相邻数值 Phase 线性插值，加小幅有界随机游走，模拟波动和渐变；连接/缺失/标定为离散开关。

主场景 normal、low_oxygen、suspected_disease、reduced_feeding、combined_anomaly、device_offline；另有 partial、invalid、visual_only、water_only 用于数据边界验收。新增场景只编辑 Phase 定义，不改 HTTP transport；无需通用编辑器。

WaterQualityGenerator 与 VisualDetectionGenerator 使用独立 RNG（seed、seed+1），视觉采样周期不会改变水质随机序列。seed 默认 42；固定 start、session_id、seed、场景和周期时完整批次可复现。真实运行自动生成新的 session_id/启动时间，值的随机序列固定，ID/时间按本次实例变化。advance 可离线快速推进；switch_scenario 不重置时间/RNG/sequence，新场景按全局 elapsed 求值，人工切换处允许场景值跳变。

实时 CLI 使用 monotonic 定时，默认首批在 10 秒后发送，维持 10 秒时间网格。阻塞/唤醒迟到时只生成并发送最近一个完整窗口，跳过更早错过的窗口（elapsed 与 sequence 同步推进，历史保留缺口），不生成/补发追赶批次；下次等待下一网格边界。固定 seed 在相同推进/跳过条件下可复现，不承诺阻塞运行与未阻塞运行数值相同。失败即停止，无透明 retry、重定向或代理；Ctrl+C 关闭上报资源。device_offline 不发送任何批次，服务器自行变过期/中断。

## 6. Web 与 AI 的统一读取

正常启动的四页面来自 MonitoringService；浏览器每 5 秒只读 Bootstrap。历史和事件不由页面生成；读取失败显示失效，恢复后重新读取，旧异步响应不能覆盖新区域选择。页面保留草稿/筛选；没有实时视频或生产权限声明。

所有页面时间统一经 timeText 使用 Intl.DateTimeFormat 的 Asia/Shanghai 时区转换，显示到秒并标记“北京时间”；趋势轴显示时分秒，图注标明北京时间 UTC+8。内部通信/存储仍为带时区的 UTC，不手动加 8 小时。观测、服务器接收、查询、窗口起止、历史和事件时间使用同一格式化入口；30 秒过期/90 秒离线判断不受显示时区影响。

HTTP 读取：/api/bootstrap?device、/api/monitoring?device、/api/monitoring/history?device&channel=water|visual&limit=N、原事件 API。历史上限不超过 repository.history_limit；缺省查询 60 条。

同进程装配同一个 repository / MonitoringService。R2B-3.2 的 `capture_water(device_id)` 只读一次 current（包括同一 SELECT 的通道接触时间），读取后取得 evaluated_at；`DomainAnalysisService.capture_water()` 产生 frozen `WaterCapture`：指标统计、canonical Reading、ChannelAnalysis、规则版本及 last_reported_at。每指标质量计算一次；规则、Reading 和展示复用同一分类，风险仍由唯一 DiagnosisService 判断，没有全局缓存或第二次数据库查询。

Web 的 `snapshot()` 继续在同一读事务捕获 current + history，再使用同一个纯捕获入口与 `project_water_snapshot()`，保留原 Web DTO 和趋势。AI 的 `water_payload()` 改用 current-only capture，再由纯 `project_water_tool()` 生成 Tool DTO，不读取历史、不构造页面趋势、不重新诊断。已有 capture 可供两种投影直接复用而不再读库。不同请求/页面依然可能捕获不同批次和评估时间，不能声称它们始终原子同步；query-time 查询不等于新采样。

设备 ID 在 context 中绑定，不跟随网页全局选择改变；它不是冻结旧观测，下次 Tool 查询仍可取得该设备的新数据。如后续需要视觉 Tool，可使用同服务的视觉读取。跨进程须共同受控服务/存储，不靠导入类共享内存。

### 6.1 有界历史水质查询（R2D-1B）

R2D-1B 提供 Monitoring 只读服务，没有新增 HTTP API。R2D-1C 的历史 Tool 仅为离线候选，见下节；正式网页仍未开放。设计依据见 [R2D-1A](deep-dive/research/R2D1A_WATER_HISTORY_TOOL_DESIGN.md)。

```python
result = monitoring.query_water_history(
    device_id,
    lookback_minutes=30,
    metrics=["dissolved_oxygen_mg_l", "temperature_c"],
)
```

- `lookback_minutes` 只接受真正的 int：10 / 30 / 60；不接受 bool、float、字符串或自动转换。metrics 接受 1–3 个不重复的已知指标组成的 list/tuple，省略时为三项，输出按固定指标顺序；不接受 null、空列表或字符串。device 必须来自 Monitoring 已登记设备。
- Service 只取得一次时钟并归一化 UTC，范围为 `(evaluated_at-lookback, evaluated_at]`。Repository 使用参数化 SQL、既有时间索引及一次读事务，按 window.end 读取最多 721 条；超过 720 条明确拒绝，不缩短范围、不分页或自动重试。没有改动 SQLite schema / 保留配置或既有 `history()`。
- `history.py` 是纯计算入口，复用上报的窗口/指标 Schema 校验及 `water_metric_facts()`；校验参照原 received_at，而非把旧观测按现在的新鲜度重评。不调用 DiagnosisService、EventService 或 Current 查询，不产生任何写入。查询时刻之后才接收的并发迟到记录不参与结果，数量另列。
- 完整处于请求区间的窗口才进入样本计数/数值统计；跨起点窗口只贡献其实际交集的 received coverage，不能按时间比例估算均值。边界排除数单列。候选及存储 JSON 损坏均安全拒绝，不把损坏混同于合法 invalid 数据。

返回独立、脱离存储对象的 dict，`projection_version=management-water-history@1`：

| 字段 | 当前合同 |
|---|---|
| status / query_completed | NO_DATA：没有完整匹配窗口；PARTIAL：有匹配窗口但可靠覆盖、Session 或歧义存在限制；OK：请求区间的全部所选指标可靠覆盖完整、无歧义/未知 Session/Session 切换。合法返回的 query_completed 均为 true |
| requested_range / evaluated_at | UTC 起止、`(start,end]` 和固定查询时刻；不是新采样时间 |
| source_kind / aggregation | simulator / window_mean；历史未重新标为当前事实 |
| counts | 候选、完整匹配、跨界排除、查询时刻后接收、歧义、重复观测时刻组/行、未知 Session 数。重复行数是歧义组中全部行数，不只是多出的行数 |
| metrics | 每指标 valid / partial / invalid / missing 窗口数；声明的 valid/invalid/missing/总样本数；可靠窗口/有效样本数、首末窗口均值与差值、窗口均值极值及独立时间/批次引用。并列极值返回次数、首次与末次引用 |
| coverage / metrics.*.reliable_window_s | received coverage 是候选窗口交集的区间并集；可靠覆盖仅由完整、非歧义且指标 valid 的窗口构成。分别返回秒数/比例，不用条数乘 10 秒，也不是样本覆盖率 |
| gaps / metrics.*.gaps | 全局缺口为 NO_RETAINED_WINDOW；逐指标缺口为 NO_RELIABLE_METRIC（也包括全局缺口、跨界或歧义排除）。各自给出全量 count/total_s，最多 12 段及 omitted_count；不能相加当作不同缺口 |
| sessions / continuity | 已知 Session 数、相邻观测记录的已知 Session 变化及省略数；连续段仅包含全部所选指标可靠、已知同 Session、窗口精确衔接的记录。unknown / 歧义 / 不可靠记录、时间缺口和 Session 切换截断连续段，最多展示 12 段；不推导异常持续时长 |
| details / details_omitted | 最多 12 个等长时间桶各选末个实际窗口；是抽选，不是桶平均或完整轨迹。全量统计先于抽选；极值引用不依赖抽选结果。partial / invalid / missing 或歧义明细的 window_mean 为 null |
| latest_observation_lag_s | 查询终点减候选中的最大观测时间；没有候选为 null。不是当前 freshness 或设备连接状态 |
| retention_completeness / limitations | 因无裁剪水位，始终 UNKNOWN；保留 NOT_CURRENT_OBSERVATION 和 RETENTION_COMPLETENESS_UNKNOWN。若区间已被可靠记录完整覆盖，UNKNOWN 本身不阻止 OK，不声称区间之外留存完整 |
| analysis | persistent_low_oxygen / recovery 均 NOT_EVALUATED；没有历史规则重评、回归趋势、预测或新阈值 |

质量只按实际指标判断：partial / invalid / missing 不进入可靠数值统计；其他完整有效指标仍可用。所有样本数是匹配记录中的声明总数，歧义记录可能重复计数，不代表独立物理样本；`reliable_valid_samples` 单列排除歧义及不可靠指标后的计数。缺失值不补零，历史“最低值”专指最低有效**窗口均值**，不声称知道原始最低采样的确切时间。

同时间或传递性重叠窗口整组标为歧义，排除可靠数值统计和可靠覆盖；received coverage 仍取并集，不重复累加。已知不同 Session 可参与分段的历史极值，但不能连接成持续状态。旧批次表被裁剪后 Session 保持 unknown，不猜回来源。没有留存记录不等于设备离线，也不能区分“从未上报”和“被裁剪”；NO_DATA / PARTIAL 都不证明环境正常或恢复。

静态限额：720 条候选 / 单行 JSON 8 KiB / 明细 12 条 / 每组缺口与连续段 12 条 / 完整紧凑 UTF-8 JSON 24 KiB。超过输出上限拒绝整个结果，不裁断 JSON。SQLite 保持既有锁、短连接及 5 秒连接等待；本阶段不接入 AI Turn，后续 Handler 必须遵守原有 Stop / Deadline，不能据此宣称 SQL 已支持强制中断。

安全拒绝使用 `HistoryQueryError.code`：`INVALID_WATER_HISTORY_QUERY`、`INVALID_HISTORY_QUERY_TIME`、`HISTORY_QUERY_BUDGET_EXCEEDED`、`HISTORY_RECORD_INVALID`、`HISTORY_RECORD_TOO_LARGE`、`HISTORY_RESULT_TOO_LARGE`、`HISTORY_STORAGE_ERROR`；不附 SQL、路径或记录内容。未知设备保持既有 `UNKNOWN_MONITORING_DEVICE` 行为。

与设计的细化：边界窗口的时间交集只计实际 received coverage；retention UNKNOWN 与区间 OK 分开；增加单行 8 KiB 防护和 as-of 接收时间过滤。Monitoring 不负责 Receipt、Policy 或发布配置；这些边界见下节。

离线验证入口：`python -m unittest discover -s apps/monitoring/tests -v`，其中 `test_water_history.py` 使用临时 SQLite 与固定时钟；不读取运行数据库或调用 Provider。

R2D-1B 验收：Monitoring 106 项通过（新增历史查询 40 项，26.069s）；管理 Web app/Assistant 与业务 Tool 合同回归 35 项通过（4.210s）；FAST 164 项通过（1.739s）。前者包括旧 History API、Current、Events、只读事务、跨时区/亚秒边界、720/721 和真实超 24 KiB 结果拒绝。无 UI 修改，未运行 Browser 或历史真实资格实验。

### 6.2 历史水质 Tool 离线候选（R2D-1C）

[water_quality_history.py](../ai_service/business_tools/water_quality_history.py) 实现 `get_water_quality_history` 的 Definition、严格 Validator 和 Handler。必填 lookback_minutes=10/30/60；metrics 可省略，指定时必须是三个已知指标的非空、不重复 JSON 列表。拒绝 bool、float、数值字符串、额外字段及 device_id；复用 Monitoring 参数校验和 720 行 / 12 条明细 / 24 KiB 限额。

Handler 签名为 `history_payload(arguments, *, monitoring, device_id)`，只调用一次 `monitoring.query_water_history(device_id, **arguments)`，原样返回上节 DTO；不查 SQLite、不重新计算统计/诊断、不添加当前水质字段。合法 NO_DATA 包括“只有跨界覆盖但没有完整匹配窗口”，PARTIAL 包括稀疏或全不可用窗口；可靠能力必须根据实际指标决定。

唯一注册入口仍为 [registry.py](../ai_service/business_tools/registry.py)：

- `bind_tools(...)` 默认不变：Current + Knowledge，定义/描述/Schema/顺序不变。
- `bind_tools(..., include_history=True)` 仅供显式离线候选装配，历史定义附加在原两项之后。formal 与 per-Turn 都须带该选项，否则拒绝；重绑同一冻结设备的 Current / History Handler，Knowledge entry 与实例继续共享。
- 候选由隔离内存 `ToolPolicy('assistant', True, (...,))` 控制，名称存在不等于授权。共享 `KNOWN_TOOL_NAMES` 和 Policy 资源不增加历史名称；临时 UserToolPolicyStore 也拒绝写入它，旧 Prototype Tool Manager 不变。评分仍只保留存储兼容名称，无 Handler。
- ManagementAssistantService 不提供候选参数，普通 Web 请求仍只装配原两项；没有新增真实资格入口或发布记录。不能通过打开现有多轮/Streaming 试用开关取得历史 Tool。

业务来源扩展在 [sources.py](../ai_service/runtime/sources.py)，未改通用 Backend / Prompt / Gate 算法：

| 本轮真实历史执行结果 | history_query_completed | HISTORICAL_WATER_OBSERVATIONS | HISTORICAL_WATER_QUERY 满足 |
|---|---|---|---|
| OK 或 PARTIAL，至少一个可靠指标窗口 | true | 有 | 是 |
| 合法 PARTIAL，全不可用指标 | true | 无 | 是 |
| 合法 NO_DATA，包括只有跨界窗口 | true | 无 | 是 |
| ERROR、无调用、未授权、非法参数、DTO 合同不一致 | false | 无 | 否 |

Receipt 额外记录有限范围、evaluated_at、完整匹配窗口数与**逐指标**可靠窗口数，不把多个指标数量相加冒充独立窗口数。result_metadata() 校验版本、时间、质量/计数、范围和有限引用一致性，不重算统计；还必须来自匹配的 Model/Tool Step 且模型请求和 Handler 真正启动。历史文字、模仿调用、浏览器声明均不能构造 Receipt。

历史 Receipt 不设当前 observation_query_completed、quality/freshness/observed_at，不能满足当前、评分或 Knowledge Requirement。每次执行仍是独立 Ledger entry；产品默认 AUTO 不变。旧工具的 Receipt.to_dict() 不增加默认历史字段，保持原两工具的序列化/提交指纹。Stop、Timeout 或 Trace 失败不提交成功回答，History 继续只包含成功 user/final 文本 pair。

Catalog 为候选提供显示 metadata，不提供权限；候选 Trace 使用 `HISTORY_CANDIDATE_TOOL_NAMES`，正式 Trace 使用未改变的 `FORMAL_TOOL_NAMES`。通用 Backend 的 Activity 白名单未扩展：Steps/轮询复用有界 display_summary，显示历史来源、UTC 范围及逐指标可靠窗口数；候选单工具 tool_activity 还提供同样的有限结构。无原始参数、明细、均值、SQL、Prompt、凭据或完整 Tool Result。

发布隔离证据：[r2d1c_two_tools.json](../ai_service/tests/fixtures/r2d1c_two_tools.json) 在修改前以临时 SQLite/Fake SDK 捕获原 Normal/Streaming 各 Direct/Single/Double 六路径的协议、结果、Steps、Usage、Ledger、安全 DTO、revision 和清理状态，以及三份管理 Streaming 计划指纹。修改后逐项相等，既有 Scope SHA256 仍为 `fc476b2e9ac19046b0127e65d70dc1488016c04f9dde29698d681c6047708e90`。这是离线等价证据，不是新 Provider 资格。

候选定义即使未授权也会改变 assembled_definitions / revision；实际授权历史后，现有两工具 Normal/Streaming Scope 拒绝匹配。没有放宽 matcher 或伪造资格维持旧 hash。R2D-1C 的 Current → History → Final 仅为内部 Fake 2/2/3 案例，不能用于批准真实组合。

后续正式开放前必须单独审核：管理端兼容且独立的 Policy opt-in/存储边界、设备与历史绑定版本、精确 Definition/模型/协议/Prompt/History/Transport Scope、确认 revision 与 epoch 生命周期、候选单案例真实授权及人工答案来源审查。先考虑仅 History、Normal、1/1/2；Current+History 和 Streaming 各自另审。当前无新模型配置或 release 记录，无 Provider/NPU 请求。

离线入口：`python -m unittest apps.ai_service.tests.test_water_history_tool -v`；新测试也已纳入 `python scripts/dev/run_tests.py backend` 及 FULL PRODUCT 的 Backend 子集。

R2D-1C 离线验收：历史候选 targeted 21 项通过（含六条旧 HTTP/SSE 路径、三计划指纹及内部 Current→History Fake）；Backend 146 项通过；管理 Assistant/Knowledge/Normal 多轮/Streaming 与管理资格 targeted 92 项通过；FAST 164 项通过。未运行真实 Provider/NPU、未开放历史 Web 试用；这些集合有交叉，不作为不同真实样本数统计。

管理 Assistant 经薄 Adapter 绑定到此服务；原 Prototype Web 的内存 Snapshot 保持独立，不受新页面影响。复用 AssistantService、Gateway、CredentialSnapshot、RuntimeSnapshot、Policy、Ledger、Commit Gate、History Projection、Deadline 和 Stop；不复制 Tool 循环、不混合多次观测、不把模拟来源升级为真实事实。

## 7. 开发写入边界与真实替换

写入默认关闭；--enable-ingestion 需要 FISHERY_SIM_INGEST_TOKEN（32–128 ASCII 字母数字）。只接受 loopback peer、允许的 Host、正确令牌、JSON 与无 Origin 的设备请求；不信任 forwarded IP、不提供 CORS，8 KiB 上限。令牌只在进程内，不发送到页面、不写文件/日志、不是现有模型 Key。

此接口只认证“本机模拟生产端”；真实 source_kind 不由客户端自报，当前所有接收来源固定 simulator。真实设备/NPU 接入须新增受控生产 Adapter 和服务器设备/来源登记、独立认证/部署配置；不能只换 URL 就把 simulator 标签改成 sensor。生产 TLS、账户权限、限流、备份、迁移、设备租户隔离仍未实现。本机令牌与 IP 限制不是生产鉴权。

未显式启用 Assistant 时 AI 消息返回 503；启用后的独立访问控制见下文。无 device control、配置写入、文件任意访问、Shell、数据库管理 API。不读取或复制正式 API Key，不改现有 Credential/ACL，不加载源码根 .env。

## R2B-3 Normal Assistant 桥接

```text
独立聊天 Session（成功 user / assistant 完整 pair）
 → 同源 AI HTTP：访问令牌 / epoch / 确认 revision / 设备登记校验
 → Web ManagementAssistant：浏览器令牌 / RequestRegistry / 同一个 RequestHandle
 → ai_service.ManagementAssistantService：冻结 device_id、Preset、Policy，取得正式 RuntimeSnapshot
 → ai_service.runtime.assistant.AssistantService：Prompt v2 / 正式多轮 Prompt；History完整pair裁剪
 → ai_backend History Projection / ToolCallingService / Gateway / Registry / Executor
      → get_current_water_quality：MonitoringService.capture_water(device_id)
          → DomainAnalysisService.capture_water → project_water_tool，无历史/二次诊断
      或 search_fishery_knowledge：旧领域 KnowledgeService / ai_service.business_tools.fishery_knowledge Handler
          → 项目背景 Evidence 或 NO_MATCH，不读取 Monitoring
 → Source Ledger / Commit Gate / 安全 Trace → 唯一 Final
```

- 启用开关 --enable-assistant；默认关闭，与 --legacy-demo 互斥。不读取或继承旧 Web 的多轮/Streaming 开关。只提供 Qwen 3.8 Flash（默认）与 Ollama Qwen3.5 4B，正式 Preset Identity、协议、Capability、OFF/Normal 均由管理侧固定Preset资源提供；DeepSeek 不列入首版。页面“已启用/已装配”仅表示本地 Adapter 可用，不表示 Provider 已联网或凭据已验证；启动不发健康 Probe。
- 默认 1 Tool Call / 1 Round / 最多 2 Model Requests；显式 Normal 多轮本地实验可为 2/2/3，retry=0；同一个 RequestHandle 的整 Turn Deadline 包含全部模型请求与 Tool，复用 Stop/Trace 提交门禁，无失败重跑。Qwen 精确两工具 Streaming 可由独立 trial 参数开启（下文）；新 RAG、评分、视觉 Tool 或固定 Analysis 未接入。
- `business_tools.registry.bind_tools()` 返回新 Backend 的 ToolRegistry，使用各 business_tools 模块的 Definition / validator；水质绑定 Monitoring Handler，Knowledge 绑定业务检索映射。当前不存在名为 ManagementToolRegistry 的类。Tool Policy 优先使用管理端独立的 management_assistant_policy.json；不存在时只读继承已有 outputs/tool-policies/tool_policies.json（再缺省为内置只授权水质），不自动写入或迁移。实际授权 = 用户 Assistant Policy ∩ 服务器本次装配集合；默认 profile 仍为水质查询、项目知识检索，历史候选有独立门禁。评分只参与已知存储配置校验，不进入管理 Registry，不回退旧 Snapshot。
- Tool Result 保留 canonical 水质与来源合同，使用精简 `management-current-water@1` 投影（下节）。这些数据只送入后续模型请求，不原样发给浏览器。存在窗口时 status=OK 表示读取完成，不表示有效或正常；NO_DATA 是未收到窗口。canonical quality 保守投影，独立 data_quality/coverage 保留实际覆盖；Findings 和 PROTOTYPE Rule Identity 与同批次网页一致，STALE/OFFLINE 不得证明恢复。
- 设备按本次请求的服务器登记 ID 冻结，不跟随其他页面的选择变化。冻结的是设备而非旧读数；Tool 执行时读取该设备最新已接收数据，并保留时间/批次。因此不同时间的页面读取可能有不同批次，不能声称始终是同一时刻。
- 凭据使用 ai_service.runtime.locations 的 private_project_location(仓库根) + ai_backend.credentials.CredentialStore；执行时一次 resolve 得到冻结 CredentialSnapshot。云端凭据缺失/私有文件权限错误安全失败，不复制、不迁移、不创建项目 .env。Ollama 按既有 Auth NONE；没有第二套凭据 UI。
- API：GET /api/ai/bootstrap?device；POST /api/ai/requests 创建有界 RequestHandle；POST /api/ai/messages 发送；POST /api/ai/request-state 与 /api/ai/cancel 用控制令牌读取安全状态/停止。Bootstrap 只返回安全模型列表、工具名、预算、epoch、revision、进程内浏览器访问令牌，不解析/回显 Secret。
- AI 写 API 要求 loopback peer、固定 Host、同源 Origin（存在时）、JSON 与 X-Management-AI；无 CORS。仅在 AI API 使用 32 KiB 有界消息，Ingestion 仍限 8 KiB。浏览器不能提交 mode、预算、Prompt、SourceRequirement、Provider 或自定义连接。revision 绑定既有 Preset 配置、设备、完整有效 Policy、实际授权集合、实际装配的 Tool 名称/type/description/parameters、水质投影版本和 epoch；变化时联网前拒绝，要求重新确认。本轮校验并冻结的同一个 Registry/Policy 用于实际执行，不在凭据读取后重建另一套绑定。RequestHandle 不允许重复执行。
- History 只在页面 Session 内保存成功文本 pair，复用后端 6 轮/6 KiB 完整 pair 裁剪和 UNTRUSTED_TRANSCRIPT_V1。失败、取消、截断、pending、Tool 协议/Result/Trace 不进入成功 History。浏览器只限制提交 envelope 大小，不重写后端 Projection；模型/设备切换确认并清本会话，刷新清空；epoch 失效保留草稿、清旧历史、重新 Bootstrap，不自动重发。
- UI textContent 渲染；独立 Tool 卡片、安全有序 Steps、Usage/状态详情，Normal 状态轮询不丢最终步骤，Streaming 使用严格校验的 SSE。无 Prompt、参数、Raw Tool Result、Reasoning、凭据或 traceback。Normal 合法完整响应或 Streaming 合法 Final 是提交依据；取消已接受后的迟到响应不提交，远端计算/费用是否停止仍为 UNKNOWN。
- 安全 Trace 位于 Git ignored 的 outputs/management_web/assistant-traces.jsonl，复用 JsonlTraceSink，只存 allowlist 元数据，不保存对话正文。SQLite 和事件生命周期不因聊天清空/切换而改变。

这是本机开发集成，不是生产账户/租户权限或设备鉴权。离线 Fake Provider 验证不代表真实回答质量已验收；真实 Provider 调用需要用户另行授权。

### R2B-3.4：独立 AI 业务边界

`apps/ai_service/` 是可无 Web 使用的同进程 Python 业务包，不是新微服务，没有新端口。`service.py` 协调 AI 业务，`business_tools/registry.py` 显式装配水质与 Knowledge，各 Tool 模块拥有自己的 Definition / Handler / DTO；`management_web/ai_adapter.py` 保留薄 Web 门面，HTTP 路由、UI、请求/响应 JSON 和启动命令不变。内部业务符号的导入改用新位置，不增加旧路径转发层。

- `contracts.py` 定义进程内 frozen PreparedAssistantTurn 与 AssistantBackend Protocol，包含 availability、bootstrap、prepare_turn、execute_turn、claim_turn 及 monitoring/epoch；不是 HTTP DTO，也不接受 Flask 对象。Protocol 是开发合同，不是权限；Web 仍只通过显式装配的 ManagementAssistant 启用执行，并校验其 Monitoring 与页面服务是同一实例。
- `prepare_turn(value)` 只接受业务字段，复用 AssistantRequest 校验及原 Policy/Definition/revision 确认；返回 frozen `PreparedAssistantTurn`，含既有 Request、设备、epoch、Profile、Policy 与 Registry。它只在服务器内短暂使用，不序列化、不进 History/数据库、不含已解析凭据，其 repr 不暴露问题/历史。预检不读观测、不解析凭据、不发请求。
- Web 保留浏览器令牌、RequestRegistry、控制令牌校验、状态/Stop API；移除 request_id/control_token 后调用业务预检。预检成功后才取出原 Handle，交给 `execute_turn(prepared, handle)`。后者检查 epoch，再沿用 handle.start 防重放/取消、原整 Turn deadline、一次 CredentialSnapshot/RuntimeSnapshot 和 AssistantService。未建立第二套取消、循环或 Trace。
- 同一 Turn 冻结 Registry/Policy/设备；另一个页面选择不改变它。本次 Tool 执行仍查询该设备当时的统一 Monitoring 数据，不冻结旧读数；Knowledge 仍独立。业务包不导入 Flask/management_web，Monitoring 生产代码不反向导入 AI service；没有全局 Demo fallback。
- `local()` 的私有凭据工厂、outputs/tool-policies 与 outputs/management_web/assistant-traces.jsonl 保持原位置；本次整理未读取/迁移/复制私有文件，真实执行仍由原 CredentialStore 获取 Snapshot。UI epoch/revision、每次网络确认、Qwen/Ollama、OFF/Normal/1/1/2 和所有提交安全语义不变。
- Normal Multi-Round：本业务层通过 execution.py 解析管理独立 Scope/flag/revision，再选择 Backend 的显式执行模式；Streaming：streaming.py 只负责发布配置/Scope，Web 的同名文件负责 SSE worker/断线，Backend Adapter 负责组装。新 Tool 在本层绑定管理业务服务；新 RAG 应替换 Knowledge 依赖，保持背景 Evidence 边界。当前 Normal 多轮与 Qwen 精确两工具 Streaming 均可显式本地试用，其他组合不自动开放。

### R2B-3.3：Knowledge Tool 装配与来源隔离

- 当前生产装配显式注入同一个 `KnowledgeContentService`，只读统一文本SQLite；AI Service没有旧固定库默认回退。历史资格夹具通过 `apps.knowledge.migration.legacy_reference` 显式载入隔离固定JSON，保留原计划，不读取用户内容。
- `business_tools/fishery_knowledge.py` 定义唯一 Knowledge model definition、validator 和检索结果映射；`business_tools.registry.bind_tools()` 用 Backend ToolDefinition 绑定共享 KnowledgeService，并在逐 Turn 装配时保留 formal Registry 中的 Knowledge entry。实际执行仍走 Backend ToolCallingService / ToolExecutor，不复制检索逻辑或执行循环。Policy 的已知名称包含评分以兼容存储，不表示管理应用装配了评分 Handler。
- Knowledge 只接受现有 `{"query":"..."}` 合同，固定 top_k=3、每条正文最多 800 字符加省略号；参数、结果大小限制和异常映射均由原合同执行。非法参数不会检索，未授权返回 TOOL_NOT_ALLOWED；检索异常是 TOOL_EXECUTION_ERROR，不能伪装成 NO_MATCH，不继续模型请求。
- OK 的合法 Evidence 只能授予 RETRIEVED_PROJECT_EVIDENCE；NO_MATCH 只表示本轮检索完成，不授予命中或当前观测来源。二者都不能满足 CURRENT_OBSERVATION_QUERY / CURRENT_SCORE_EVALUATION。History、模型正文和来源声明不生成 Receipt。
- 默认 Web 是 OFF / Normal / 1 Call / 1 Round / 最多 2 Requests（R2B-4 显式实验另见下节）。两项授权表示模型择一，不表示同轮双 Tool；多个调用整批拒绝，Request #2 的 tool_choice=none，继续调用为 TOOL_ROUND_LIMIT，失败不重试、不提交成功 History。Knowledge 成功但后续模型失败时仍可保留执行审计，不提交成功回答。
- UI 按实际 Tool 显示独立卡片；Knowledge 只显示背景来源标识、执行状态、命中数量和耗时，NO_MATCH 显示“检索完成 · 无合格命中”，不显示 query、Raw Result、Evidence 正文。Knowledge 不是当前水质或现场疾病确诊依据。模型自由正文的来源可信度仍需人工验收，不由 Fake Provider 测试证明。
- 默认授权不变，不伪造 qualification_id、不修改 Preset / Capability / Normal 或 Streaming 发布配置。管理端不继承 Prototype 的 2/2/3 或 Streaming Scope；R2B-4 使用单独冻结的精确 Scope 与确认 revision，只提供本地实验状态，未发布真实资格。

使用原 Prototype 的 Tool Manager → Assistant 标签显式授权项目知识，刷新管理 Assistant 后按新的 revision 重新确认。两 Web 共用既有 Policy 文件，用户调整也会影响原 Prototype 的下一次请求；管理程序不替用户修改文件或建立第二套权限界面。操作和离线测试见 [BUILD_RUN](BUILD_RUN.md)。

### R2B-3.2：精简水质 Tool DTO

`ai_service.business_tools.current_water_quality.project_water_tool(capture)` 只投影、不读取或分析；`projection_version=management-current-water@1` 纳入管理端确认 revision，不改变模型 Tool Schema 或原 Preset 资格范围。

- `water_quality`：原 canonical 三指标、quality、freshness、observed_at、retrieved_at、source，供现有 Receipt / Ledger 使用。只投影完整有效指标；部分覆盖或无效指标仍为 null，不补正常值。STALE/OFFLINE 保留历史观测值并显式注明失效，不能认证当前正常。
- 共同上下文：device_id、channel、batch_id、window、aggregation、statistics_version、source_kind、evaluated_at、last_reported_at、connectivity、rule_version。
- `data_quality`：原领域 quality / freshness / connectivity / coverage；coverage 为各指标有效数与总数。`metrics` 只补充单位、指标质量及无效样本数，不携带 Web label、min/max/latest 或趋势。
- `findings`：保留全部 HIT / CLEAR / INSUFFICIENT_EVIDENCE / NOT_EVALUATED，含 code、kind、state、severity、message、facts_used、reason 和完整 rule 身份（版本/范围/PROTOTYPE/评估策略）。共享观测引用位于顶层，不在每个 Finding 重复，不再附第二份完整 analysis 或 HIT 列表。
- NO_DATA：water_quality=null、findings=[]、batch_id=null、data_quality=missing/unknown/never_received；不伪造观测或正常结论。收到全缺失窗口时依然为 OK，领域 quality=missing、canonical quality=invalid，保持既有保守合同，并非 NO_DATA。PARTIAL / INVALID 是质量维度，STALE 是新鲜度，OFFLINE 是连接维度，不能混成风险严重度。
- Source Gate / Receipt / Ledger / Commit Gate、设备绑定、空参数 `{}`、Policy、1/1/2、History 与取消均不变。没有来源即不能用 DTO 或模型文字补造来源；Tool ERROR 不继续第二次模型请求。

离线固定低氧/正常窗口的紧凑 UTF-8 JSON：旧投影 15665 / 14799 bytes，新投影 7686 / 7680 bytes（约减小 51% / 48%）；这是固定 fixture 的字节数，不是 token 或真实模型成本保证。测试约束这些样本小于 10 KiB；Executor 原有 32768 bytes 硬上限仍有效，未引入截断或放宽。

### R2B-3.1：参数拒绝的安全诊断

水质 Tool 仍只接受 `{}`，设备由服务器绑定；Schema、Policy、预算和执行权限不变。拒绝仍保留原错误码；新增可选 `argument_diagnostic` 元数据进入有序 Activity 与安全 Trace，管理页面在“本次运行详情”显示。该元数据不进入 Tool Result JSON、模型消息、Receipt 或 History。

- `schema_version=1`；`stage` 仅为 `model_contract`、`stream_assembler`、`executor` 或 `definition`。
- `reason` 是有限枚举：`MALFORMED_JSON`、`NOT_OBJECT`、`UNEXPECTED_ARGUMENTS`、`ARGUMENTS_TOO_LARGE`、`INVALID_ENCODING`、`VALIDATOR_REJECTED`、`ARGUMENTS_TOO_COMPLEX`、`INVALID_JSON_VALUE`。
- `argument_bytes` 为 UTF-8 字节数，饱和上限 65536；不可编码时为空。`object_member_count` 只在已知 object 时记录，饱和上限 1024。计数不参与授权，不表示放宽 4096 bytes 原限制；未到达/无法确定的计数为空。
- 不记录字段名、参数值、validator 异常文字、Prompt、原始 Result 或凭据。未知异常仍是 `TOOL_EXECUTION_ERROR`，取消仍是 `USER_CANCELLED`，不能伪装成参数拒绝。
- Normal 的非法 JSON / 非 object 通常在 ModelToolCall 构造处被拒绝，对外仍为 `INVALID_TOOL_CALL`（Assistant 归一为 `MODEL_TOOL_CALL_MALFORMED`）；Executor 的参数拒绝仍为 `INVALID_TOOL_ARGUMENTS`。Streaming 原有错误码保持不变。
- 拒绝不执行对应 Handler，不继续模型请求，不授予任何执行来源，不提交成功 History。先前 Qwen 失败记录没有这些字段，无法追溯具体参数原因；未来新的失败只需检查安全拒因，无需保存原始参数。此次实现没有联网取证。

## 8. 其他业务边界

文件管理与索引/检索仍分开，资料页面已管理统一文本知识并提供内容导出；文件上传/导入和RAG技术配置尚未实现。未来 Knowledge Evidence 不能认证现场事实；Analysis 自动 RAG 与 Assistant Knowledge Tool 保持原边界。

Video/NPU 将通信、推理、事实归一化和网页播放分离；不迁移桌面 GPU 项目。Events 人工处理、附件授权和通知待独立设计。管理员权限与开发设备接入开关分离。

管理 Runtime 的当前边界见 [独立 Backend](../ai_backend/README.md) 与 [业务 Runtime](../ai_service/runtime/README.md)。旧 Prototype 的 [Analysis / Assistant](../../docs/deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md)、[Tool Runtime](../../docs/deep-dive/tools/READ_ONLY_TOOL_CALLING.md) 与 [凭据](../../docs/deep-dive/operations/PRIVATE_CREDENTIAL_STORAGE.md) 保留迁移来源和独立实验说明，不作为新侧自动同步合同。启动与验收见 [BUILD_RUN](BUILD_RUN.md)。

R2C-1D：正式ManagementAssistantService和Web/SSE/资格入口已统一使用apps.ai_backend新类型；业务Prompt/History/Receipt/Ledger/Policy在ai_service.runtime。顶层 service/contracts/execution/streaming 分别负责协调、进程内合同与发布计算；R2C-2B 将业务绑定整理为 business_tools/registry 与每 Tool 模块，不留旧 tools/bindings 入口。MIG-1 后 Monitoring/Knowledge 正式服务与来源认证均无旧包依赖，历史资格资源另行处理。Scope及授权/输出预算不变，qualification计划@2重新绑定授权，非新真实资格。见 [当前Backend](../ai_backend/README.md)。

R2C-1E：迁移主线和基本真实网页人工验收已结束；Qwen Normal 水质查询、Streaming 水质 + Knowledge、Final 提交及来源 / PROTOTYPE 标签由用户观察为正常。本轮工程检查未再调用 Provider，未改变资格记录、发布范围或默认开关。Monitoring 的旧 Diagnosis / telemetry / 领域合同、KnowledgeService / 固定资源仍在业务层，后续独立化不应反向引入通用 Backend。

## R2B-4：管理独立 Normal 多轮执行范围

`ai_service.execution` 加载自己固定资源 `resources/assistant_execution.json`，开关/Scope 在业务实例的 epoch 内冻结，无 Web 模式或路径覆写。默认关闭、1/1/2；显式 `--assistant-multi-round-trial` 后，只有匹配 local_experimental Scope 的 Qwen/Ollama 才能执行 2/2/3。两者独立声明、qualification_id/validated_at 均为空，不继承 Prototype released 或真实模型结论；DeepSeek/Streaming/评分均未纳入。

- 精确 Scope：Preset ID/variant/contract、service/adapter/normalized URL/model、完整 ProtocolSpec、OFF/Normal、正式 `ASSISTANT_BOUNDED_MULTI_ROUND@1` 的 hash、History projection/version、实际授权 Tool 名称和 definitions hash，以及 `management-current-water@1`、Knowledge binding/source/version/backend。当前唯一组合为水质查询 + 项目知识检索。
- 复用核心 `release_scope` / `resolve_execution_profile` 的纯计算，传入管理自己的维护者记录；不加载 Prototype 发布文件。管理 revision 还绑定完整用户 Policy、实际装配 Definition、设备、epoch 和配置。输出预算/Timeout/retry/凭据引用通过核心 runtime revision 纳入确认；安全摘要不向浏览器暴露这些私有设置。
- Bootstrap 每个 Preset 返回有效 mode、can_send、预算、实验状态和 revision。Turn 预检先核对 epoch / confirm / revision / Scope，再取得 RequestHandle、一次 CredentialSnapshot 和 RuntimeSnapshot；Policy / Registry / ExecutionDecision / 设备在预检时冻结。开关开启但未匹配时联网前拒绝，不静默降级；浏览器过期确认不能复用。
- `ManagementAssistantService` 选择 apps.ai_service.runtime.assistant.AssistantService 与 apps.ai_backend.tool_conversation.ToolCallingService 的 mode；正式多轮 Prompt、History v2 裁剪、Source Gate、Ledger、Commit Gate、预算和 Deadline 均复用。Tool A Result 进入下一请求，由模型决定 Tool B 或 Final；最后请求 tool_choice=none。没有预执行、第三个 Tool、第四次模型请求、自动重试或 failover。
- 水质 Tool 仍执行一次 `capture_water`，冻结设备而非旧读数，保留 batch/time/quality/coverage/Findings/PROTOTYPE Rule Identity。Knowledge 独立检索，Ledger 每次执行留独立 Receipt，不把知识 Evidence 合并为现场事实。后续错误保留已有 Ledger 审计，但不提交成功回答。
- 前端沿用通用有序 Steps、每 Tool 独立卡片、聚合 Usage、Stop 和唯一 Final。只有完整通过门禁的最终文本 pair 进入 History；不保存中间模型正文、Tool 协议、Ledger 或 payload。网络确认动态显示最多 2 或 3 次，请求结束清除确认。

关闭管理开关并重启即可回滚，新 epoch 不自动续用旧确认/历史。此本地实验不等于管理链路真实资格验收；模型选择与回答质量仍需用户另行授权测试。启动与人工验收见 [BUILD_RUN](deep-dive/PROTOTYPE_RUN_REFERENCE.md#r2b-4normal-multi-round-本地试用)。

## R2B-4.1：历史趋势显示与 Ollama 调查

图表默认显示**最后观测之前 30 分钟**，可选 1 小时或全部有界历史；这不是当前时刻的新鲜度保证。实际库存 214 个水质窗口 / 3 个 Session 跨约 20.15 小时，包含约 13.23 小时与 6.34 小时中断。原图全部压进同一时间轴，又用第 0/3/7/11 个点作为刻度，所以形成窄点簇与重叠标签；本次盘点未见相同或倒序观测时间，不是该库已有重复记录造成。

- 保留真实时间比例；不按样本序号挤掉停机时长。全部历史仍可能呈现窄簇，这是实际时间跨度的结果；查看最近范围可分辨每个窗口。
- Web trend / History API 新增可选 session_id，trend 增加 window_start。Repository 在原读事务 LEFT JOIN 批次元数据，按 observed_at / received_at / batch_id 稳定排序，不迁移 SQLite、删除历史、改写观测或影响 AI 的 current-only capture。批次元数据被裁剪时 session_id=null，仍保留历史；无法确认旧 Session 时只依时间/窗口缺口断线。
- 图表再按时间数值排序；同时间记录只显示最后接收项（平局按 batch_id 和原顺序确定），无效/缺失的最后项不回填旧值。API/库保留所有记录。缺失、明确时间缺口与已知 Session 切换断线；非法时间不使用虚构索引。
- 时间刻度独立于数据密度，最多五个均匀位置；短于 4 秒范围显示毫秒，跨日期补日期行；纵轴使用可辨识的步长和精度。全部显示用 Asia/Shanghai；窄卡片内部横向滚动，不压缩标签至互相重叠。

Ollama 只读证据：`outputs/management_web/assistant-traces.jsonl` 中同一个 request_id `2eec55f56e3b456d9226be6f5d756981` 的 conversation + assistant 两条记录，对应**一次失败 Turn**。preset 为 ollama-qwen35-4b-r1、正式多轮 Prompt；Request #1 outcome=multiple_tool_calls、finish_reason=tool_calls，Request #2 未开始；1 Model Request、0 Tool attempts / executions，预算为 2/2/3。触发原 ToolCallingService 的 len(calls)>1 分支，不是整个 Turn 耗尽预算、Handler 执行失败或 SQLite 问题。

这证明归一化后的首轮存在多个已通过结构校验的调用，且 ID 不重复（重复 ID 会更早被归为 malformed）。现有安全 Trace 不保存该拒绝分支的完整调用集合，**无法确定准确个数、重复逻辑调用还是不同 Tool，也没有独立 raw/normalized 对照证据**。不能根据短输出长度猜测。当前 Adapter 逐项解析 provider tool_calls，未配置 parallel_tool_calls=false；本轮不改变 Adapter、Prompt、Schema、Runtime 或预算。

建议保留单轮一个 Tool 合同。若后续获批改善，可先增加仅含有界 call_count、allowlist Tool 名称和重复标记的安全诊断，再单独评估 Ollama 协议是否支持并遵守 parallel_tool_calls=false；即使设置该提示，Runtime 仍须整批拒绝多调用，不自动择一、补跑或扩大预算。当前仅一个失败样本，不能据此判定所有 Ollama 请求不兼容。


## R2B-5B：管理 Streaming 后端

**R2B-5E 已获明确授权开放本地实验，默认仍关闭。** `ai_service.streaming` 读取管理自己的固定 resources/assistant_streaming.json，一次加载、随 epoch 冻结；默认 enabled=false，唯一 Qwen OFF / Streaming / 水质 + Knowledge 两工具 local_experimental，qualification_id/validated_at 为空。`--enable-assistant --assistant-streaming-trial` 只在本进程启用，不写回文件或修改用户 Policy；candidate 仍不能授权发送，不继承 Normal 或 Prototype 发布资格。回答质量审核留待后续，当前不是 released。

复用核心 streaming_scope / resolve_streaming_profile，管理外层绑定 Monitoring/Knowledge 版本、source/version/backend；revision 同时绑定实际 definitions、完整 Policy、设备、epoch、配置、预算与 Runtime 设置。Bootstrap 每 Preset 增加 streaming 安全摘要（can_send / mode / transport / revision / release_status / mode_reason / 请求及 Tool 上限 / max_output_tokens），原 execution 和 revision 保留 Normal 语义。Ollama 不在 Streaming 范围。浏览器不能传入 mode、Transport、预算、Prompt、Deadline 或来源要求。

`POST /api/ai/messages/stream` 使用与 Normal 相同的 JSON envelope，服务端由路由选择内部 Transport。先执行原 loopback/Host/Origin/X-Management-AI、32KiB、epoch、confirm、Streaming revision/Scope 校验，再取得同一 Handle。Service.claim_turn 在任何 worker/凭据/模型 I/O 前唯一 start，返回一次性闭包；Normal 也复用它。worker 显式建立 request_scope、沿用从 claim 开始的整 Turn deadline，解析一次 CredentialSnapshot/RuntimeSnapshot，再执行原 AssistantService / ToolCallingService。

Streaming 使用 BOUNDED_MULTI_ROUND + ToolModelTransport.STREAMING，仍为 2 Calls / 2 Rounds / 3 Requests、每轮最多一个 Tool、retry=0、120 秒。Runtime.default_response_mode 仍是 normal，传输上限通过 transport_output_token_limit=512 编码；当前 Qwen 原生成上限为 None，Fake SDK 每次实际收到 stream=true、max_tokens=512。若未来生成默认更低，Adapter 仍取 min，512 不是强制消费量或完整回答保证。

Web 的 streaming.py 只投递现有 AssistantEventChannel，不另写 Tool 或事件队列循环：schema v1 / request_id / epoch / 连续 seq，start、activity、preview_reset、preview、final/error/cancelled，注释心跳不占号。Activity 使用既有安全投影，快速步骤保留；预览是有界累计 content，仅临时，不保存 Trace/History。参数、Prompt、Raw Result、reasoning 和凭据不作为事件数据。Final 来自安全 AssistantResult.to_dict，保留 Trace/Source Gate/Commit Gate，失败结果没有 final_text/completed_at 或成功资格。

响应 text/event-stream / no-store / X-Accel-Buffering:no；原 cancel/state API 不变，响应关闭（包括首次消费前）及迭代器断开均取消原 Handle。worker finally 清事件引用，线程启动失败安全结束，无自动重试、重连、Normal 降级或 failover。已完成但投递中断时，后端保留完成记录；客户端未收到 Final 就不能提交成功 History。控制令牌不进 URL 或事件；这仍是本机开发边界，不是生产用户权限或多进程任务服务。

### R2B-5C：前端事件与 Session

`services.ai.stream` 仅负责同源认证 POST fetch；独立 `assistant-events.js` 消费 schema v1，校验 id/连续 seq/request_id/epoch、start 的设备/revision/预算/状态、Activity v2 与唯一终态。重复旧 seq 不重复应用，跳号/非法身份/未知事件安全失败；注释心跳不占号。通道在新 Request reset 后可能补发旧 Request reset，前端仅忽略这个旧清除动作，不能撤销较新预览。UTF-8 严格解码；单缓冲 512 KiB、总量 8 MiB、预览 16 KiB、事件最多 513（含终态）。读流最终 cancel/releaseLock，无 EventSource 自动重连。

模式默认 Normal；Streaming 选择的 profile/revision 决定确认与路由，浏览器不提交 mode/预算。正在执行的 Turn 冻结配置；History 只存同一成功文本 pair，模式切换不清 History。仅合法 Final（完整非空正文、stop、trace_recorded、completed Activity、匹配请求/设备/revision）交给 Workspace 成功提交；预览/失败/取消不会成为 History。Stop 立即隐藏预览，复用原 cancel API；接受取消后 Abort 原读流，迟到事件不改状态。服务端先完成时允许收到的合法 Final，页面离开后即使迟到也不提交。

消息节点及内部滚动容器持续存在，Preview→Final 不另建一条回复；每 Tool 独立卡片和有序 Steps/Usage 沿用安全投影，不渲染 Raw Result/参数/reasoning。滚动跟随与问题导航仅为显示状态，不改变模型 History/Source 合同。后续真实测试/试用须另获明确授权，本阶段不能直接开启。

### R2B-5D：qualification 边界

`ai_service.development.streaming_qualification` 只由单案例 CLI/离线测试导入。先按正式 definitions/绑定/Scope 计算无副作用计划；获批后创建临时 Monitoring SQLite 与 Policy，经正式 ManagementAssistantService 冻结设备、Credential/Runtime 和执行 2/2/3。它仅为单案例资格构造服务器内 PreparedAssistantTurn 的执行许可，保留当时的 Scope 发布状态；不更改配置或 Web prepare_turn 门禁，不提供浏览器可控的 bypass。

执行观察复用既有 QualificationAdapter / Streaming observer / ExperimentGateway；Tool 循环、Source Ledger、Commit Gate 均来自原 Runtime。实际 SDK 分片/清理和 Result 上下文比较可成为管理业务链证据；CLI 不走 HTTP/SSE，报告明确该缺口。产品结果完成与实验路径合格分别记录；人工预览不写 JSON，也不作为发布批准。具体审批/回滚见 [资格说明](deep-dive/STREAMING_QUALIFICATION.md) 和 [本地启动](deep-dive/PROTOTYPE_RUN_REFERENCE.md#r2b-5eqwen-streaming-本地实验)。

## 历史 Tool 授权与候选边界（R2D-1D）

- **独立存储**：[management_policy.py](../ai_service/management_policy.py) 固定使用 `outputs/tool-policies/management_assistant_policy.json`，schema_version=1、递增 generation、selected_tools。文件不存在时只读继承共享 Assistant 选择；首次明确保存完整选择才脱离继承。Analysis 与共享文件均不修改。历史缺省不授权；兼容评分选择可保留但无 Handler。
- **安全保存**：8 KiB 有界读取、严格字段/类型/重复键校验；拒绝链接/重解析点/多硬链接目标。进程锁 + OS 文件锁覆盖读取/CAS/原子替换，临时文件 fsync 后 replace。并发旧 revision 返回 `TOOL_POLICY_REVISION_MISMATCH`，锁占用返回 `TOOL_POLICY_BUSY`；损坏配置启动/请求均关闭失败，不回退内置授权。此处不提供 reset 或自动迁移。
- **HTTP/设置**：`GET/POST /api/ai/tool-policy` 与现有 AI API 共用 loopback、Host/Origin、浏览器令牌、JSON/大小边界。POST 仅接受 epoch/revision/selected_tools；设置 → Assistant Tool 授权只负责本机开发配置，并非生产账户/RBAC。
- **撤销与确认**：bootstrap/prepare 使用单份 Policy snapshot。管理覆盖的 generation/revision 进入确认 revision；准备后、claim 前再校验，撤销/修改阻止旧确认联网。claim 后属于已开始 Turn，继续使用冻结授权/设备，不中途改变执行权限；下一 Turn 使用新配置。共享旧格式尚在继承时保留原有 prepare 冻结语义。设置保存清除页面确认，执行中则在结束后刷新配置，成功 History/draft 不清空。
- **候选 Scope**：[history_execution.py](../ai_service/history_execution.py) + [固定资源](../ai_service/resources/water_history_candidate.json)：Qwen `dashscope-qwen38-flash-r1` / OFF / Normal / `get_water_quality_history` / 1 Call、1 Round、2 Requests / retry=0 / 120 秒。沿用单轮 `ASSISTANT_V2@1` 与当前 History Projection；绑定 Identity、ProtocolSpec、Prompt/History framing、Definition hash、默认 generation 参数、Monitoring `management-water-history@1` 及 720/12/24KiB、`historical-water-receipt@1`、设备和 Policy revision。
- **发布不能由授权代替**：R2D-1G将固定`water_history_candidate@2`登记local_experimental、资源enabled=false；仅维护者`--assistant-history-trial`可进程内启用。candidate仍关闭，released与JSON enabled=true均拒绝。还需管理Policy显式授权及页面「历史查询」业务操作；原Normal/Streaming两工具Scope不变。每请求1024、1/1/2/retry=0/120秒进入Scope；配置/开关/Policy/设备/epoch进入revision。真实批次与操作见[历史资格记录](deep-dive/HISTORY_QUALIFICATION.md#9-r2d-1g真实批次通过与本地实验开放)。
- **隔离执行与来源**：候选 formal 保留旧 Knowledge entry；逐 Turn 只重绑冻结设备 Handler。历史 profile 仅暴露已授权历史 Tool，服务端指定 HISTORICAL_WATER_QUERY；Receipt 仍由真实 Steps 推导，NO_DATA/合法 PARTIAL 完成操作，可靠观测另行认证，不能满足 CURRENT_OBSERVATION_QUERY。网页仅接收有限 Activity，不接收历史明细、SQL 或参数。

R2D-1H：Web 请求仅接受受控业务 `action="history_query"`，由 `management_web/ai_adapter.py` 映射内部历史范围；浏览器提交 `execution_profile`、自选预算或任意 action 均拒绝。Bootstrap 对页面提供 `history_query` 可用性、原因及不透明 revision，不提供内部历史 Profile ID。普通请求不带 action，仍使用原 Current + Knowledge 范围；成功的历史快捷查询自动恢复普通提问，失败不自动换范围。模式、设备、模型、工具范围或 revision 变化时，页面清除确认，服务端继续精确复核。

独立三工具候选位于 `normal_selection.py` / `resources/assistant_normal_candidate.json`，只支持服务端显式离线装配。它绑定正式多轮 Prompt、History、三项 Definition、Monitoring/Knowledge/历史来源版本、1024 token 上限和 2/2/3。没有产品启用开关，准入恒为 false；测试只能在离线网络阻断及 Fake SDK 下显式 stub 未发布准入，不能授予产品资格。现有两工具发布解析和用户Policy不变。
- **离线证据边界**：旧candidate测试显式stub未发布准入；新的local_experimental HTTP测试使用真正开关/Scope/Policy，不stub门禁，通过正式Adapter验证max_tokens=1024。实际15样本Provider技术证据与用户发布批准单独记录，不等于回答质量审核或released。

R2D-1E 已新增开发层的历史单案例计划（默认 dry-run，见 [操作说明](deep-dive/HISTORY_QUALIFICATION.md)），固定隔离 SQLite/seed/clock 与 10/30/60 参数、完整 Scope/计划 hash、HISTORICAL_WATER_QUERY、1/1/2/retry=0。先核对计划与本候选一致，再由用户逐案例批准一次网络请求范围；仅资格入口持有服务器执行许可，不改 Web 发布门禁。安全报告记录执行/来源/Usage，不写参数正文/观测明细/凭据。完成真实与人工审核后，再单独批准 exact local_experimental 配置及默认关闭的启动开关；不修改用户 Policy，不继承旧两工具资格。

## 系统设置中心（R2D-4A）

`management_web/settings_api.py → ai_service/settings.py → ai_backend/project_env.py / CredentialStore`。固定 Provider 的密钥写入复用既有 Writer 算法；无新凭据 Store、模型循环、Policy 或发布配置。Writer 不接受 Web 路径/环境变量名，沿用私有位置、PROCESS_ENV 优先、文件 CAS、锁、ACL 与原子替换。保存不会探测模型；当前 Turn 使用原冻结 Snapshot，后续请求才解析更新。

非敏感默认偏好保存到已有 `outputs/management_web/` 下的 `settings.json`。路径由启动装配决定，格式/大小受限、原子写入及 CAS；复用管理端既有文件路径与进程锁函数，不复用或改写 Policy 数据。设置 HTTP 沿用 Host/Origin、loopback、浏览器 token；写请求有 epoch/revision，过期或不支持组合拒绝。前端仅在首次挂载聊天前应用默认值，不重建现有会话或 RequestHandle。

R2D-4B 在原精确 execution 准入之后叠加 `management-qwen-output-range@1`，仅对本地 Qwen OFF / 2/2/3 允许 1–4096 输出上限；原 Scope、Policy、Prompt/History/Tool/数据绑定 matcher 不变。预算在同一设置文件 v2 中分模式保存，版本与基础 Scope/选定值一起进入 execution revision；prepare/claim 防过期，运行中使用原冻结 Runtime。未配置覆盖时保持旧编码和资格计划。聊天 HTTP 仍拒绝客户端直接注入 Token/ceiling、Tool 预算、Prompt 或连接地址。Generic Adapter 仅新增服务器内部 ceiling 校验，默认 1024/512 限制保留，不改变循环或能力证据。

显式连接测试复用固定 Provider、ProfileRegistry 的临时 environ Snapshot、已有 Adapter 和 RequestHandle，只有 1 次 Normal 请求 / 8 output tokens / 20秒 / retry=0，无 Tool、History 或领域 Receipt。成功且清理完成后发放短期一次性保存凭证，仅保留有盐摘要/Provider/文件版本；正常保存仍由既有私有 Writer 原子执行，PROCESS_ENV 只读。测试成功不授予产品资格。操作见[设置说明](deep-dive/PROTOTYPE_RUN_REFERENCE.md#r2d-4b连接测试与可调输出预算)。自定义模型与 RAG 高级配置继续暂缓。

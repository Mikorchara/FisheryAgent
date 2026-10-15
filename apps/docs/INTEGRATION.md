# 统一监测协议与集成边界

## 1. 当前运行链路

```text
Simulator：Scenario → 逻辑采样 → 10 秒窗口 → HTTP
    → management_web Ingestion：本机与令牌检查
    → monitoring.contracts：v1 严格校验
    → DomainAnalysisService：时间/上下文 → rules → Findings
    → MonitoringRepository：单事务保存 water / visual
        → EventService：计算事件变更 → 同事务持久化
    → MonitoringService：统一查询、历史、Web 投影
        → Dashboard / Monitoring / Video / Events
        → bind(device_id).water_reader（未来 AI Tool 接入口）
```

`apps/monitoring/` 不依赖 Flask 或页面。Web `create_app(data_service=...)` 将同一服务用于监测、视觉和事件；CLI 正常入口总是装配 SQLite 服务。无 data_service 的工厂保留 R1 测试/兼容 Demo；CLI 必须显式 `--legacy-demo` 才使用它，接入失败不回退 Demo。

服务复用现有 WaterQualityReading、DiagnosisService、evaluate_freshness 与 CurrentWaterQualityReader，只依赖领域读取能力，不启动模型或修改 Prototype 当前 Store。

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

默认每设备每通道保留 360 个窗口（10 秒周期约 1 小时），每设备 1440 个批次幂等记录，全局 300 个事件。超限按最旧记录裁剪；SQLite 可复用空闲页，不承诺文件立即缩小。重启保留数据，不删除旧库。

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

过期/离线时 events() 只将当前确定性撤回为 INDETERMINATE 的只读投影，不写入新事件、不修改历史。完全缺失通道的批次不覆盖该通道 current；其已有观测随后按各自年龄失效。事件初次批次可能因保留限额被裁剪，事件自身保留时间、来源与首末引用。

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
- Repository 在原 `BEGIN IMMEDIATE` + 锁中读取活动事件、计算变更并应用 SQL；current、历史、事件、alerts 和接触时间仍整体提交/回滚。重复与乱序不执行事件变更。未更换 SQLite、表结构或保留策略。
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

管理 Assistant 经薄 Adapter 绑定到此服务；原 Prototype Web 的内存 Snapshot 保持独立，不受新页面影响。复用 AssistantService、Gateway、CredentialSnapshot、RuntimeSnapshot、Policy、Ledger、Commit Gate、History Projection、Deadline 和 Stop；不复制 Tool 循环、不混合多次观测、不把模拟来源升级为真实事实。

## 7. 开发写入边界与真实替换

写入默认关闭；--enable-ingestion 需要 FISHERY_SIM_INGEST_TOKEN（32–128 ASCII 字母数字）。只接受 loopback peer、允许的 Host、正确令牌、JSON 与无 Origin 的设备请求；不信任 forwarded IP、不提供 CORS，8 KiB 上限。令牌只在进程内，不发送到页面、不写文件/日志、不是现有模型 Key。

此接口只认证“本机模拟生产端”；真实 source_kind 不由客户端自报，当前所有接收来源固定 simulator。真实设备/NPU 接入须新增受控生产 Adapter 和服务器设备/来源登记、独立认证/部署配置；不能只换 URL 就把 simulator 标签改成 sensor。生产 TLS、账户权限、限流、备份、迁移、设备租户隔离仍未实现。本机令牌与 IP 限制不是生产鉴权。

未显式启用 Assistant 时 AI 消息返回 503；启用后的独立访问控制见下文。无 device control、配置写入、文件任意访问、Shell、数据库管理 API。不读取或复制正式 API Key，不改现有 Credential/ACL，不加载源码根 .env。

## R2B-3 Normal Assistant 桥接

```text
独立聊天 Session（成功 user / assistant 完整 pair）
 → 同源 AI HTTP：访问令牌 / epoch / 确认 revision / 设备登记校验
 → ManagementAssistant：冻结 device_id、Preset、Policy，取得正式 RuntimeSnapshot
 → 原 AssistantService：Prompt v2 / History v2 / 现有裁剪
 → 原 ToolCallingService / Gateway / Registry / Executor
      → get_current_water_quality：MonitoringService.capture_water(device_id)
          → DomainAnalysisService.capture_water → project_water_tool，无历史/二次诊断
      或 search_fishery_knowledge：原 KnowledgeService / 原 Handler
          → 项目背景 Evidence 或 NO_MATCH，不读取 Monitoring
 → Source Ledger / Commit Gate / 安全 Trace → 唯一 Final
```

- 启用开关 --enable-assistant；默认关闭，与 --legacy-demo 互斥。不读取或继承旧 Web 的多轮/Streaming 开关。只提供 Qwen 3.8 Flash（默认）与 Ollama Qwen3.5 4B，正式 Preset Identity、协议、Capability、OFF/Normal 均由原 Runtime 固定；DeepSeek 不列入首版。页面“已启用/已装配”仅表示本地 Adapter 可用，不表示 Provider 已联网或凭据已验证；启动不发健康 Probe。
- 固定 1 Tool Call / 1 Round / 最多 2 Model Requests，retry=0；同一个 RequestHandle 的整 Turn Deadline 包含两次模型请求与 Tool，复用 Stop/Trace 提交门禁，无失败重跑。没有 Streaming、新 RAG、评分、视觉 Tool 或固定 Analysis。
- ManagementToolRegistry 复用正式 Definition / validator；水质只替换为 Monitoring 数据 Handler，Knowledge 直接使用原绑定。Tool Policy 从已有 outputs/tool-policies/tool_policies.json 读取；不存在时复用内置默认（只授权水质）。实际授权 = 现有 Assistant Policy ∩ 本应用装配集合（水质查询、项目知识检索）；不自动修改用户 Policy。评分只参与全局 Policy 兼容校验，不进入管理执行 Registry，不回退旧 Snapshot。
- Tool Result 保留 canonical 水质与来源合同，使用精简 `management-current-water@1` 投影（下节）。这些数据只送入后续模型请求，不原样发给浏览器。存在窗口时 status=OK 表示读取完成，不表示有效或正常；NO_DATA 是未收到窗口。canonical quality 保守投影，独立 data_quality/coverage 保留实际覆盖；Findings 和 PROTOTYPE Rule Identity 与同批次网页一致，STALE/OFFLINE 不得证明恢复。
- 设备按本次请求的服务器登记 ID 冻结，不跟随其他页面的选择变化。冻结的是设备而非旧读数；Tool 执行时读取该设备最新已接收数据，并保留时间/批次。因此不同时间的页面读取可能有不同批次，不能声称始终是同一时刻。
- 凭据使用原 private_project_location(仓库根) + CredentialStore；发送前一次 resolve 得到冻结 CredentialSnapshot。云端凭据缺失/私有文件权限错误安全失败，不复制、不迁移、不创建项目 .env。Ollama 按既有 Auth NONE；没有第二套凭据 UI。
- API：GET /api/ai/bootstrap?device；POST /api/ai/requests 创建有界 RequestHandle；POST /api/ai/messages 发送；POST /api/ai/request-state 与 /api/ai/cancel 用控制令牌读取安全状态/停止。Bootstrap 只返回安全模型列表、工具名、预算、epoch、revision、进程内浏览器访问令牌，不解析/回显 Secret。
- AI 写 API 要求 loopback peer、固定 Host、同源 Origin（存在时）、JSON 与 X-Management-AI；无 CORS。仅在 AI API 使用 32 KiB 有界消息，Ingestion 仍限 8 KiB。浏览器不能提交 mode、预算、Prompt、SourceRequirement、Provider 或自定义连接。revision 绑定既有 Preset 配置、设备、完整有效 Policy、实际授权集合、实际装配的 Tool 名称/type/description/parameters、水质投影版本和 epoch；变化时联网前拒绝，要求重新确认。本轮校验并冻结的同一个 Registry/Policy 用于实际执行，不在凭据读取后重建另一套绑定。RequestHandle 不允许重复执行。
- History 只在页面 Session 内保存成功文本 pair，复用后端 6 轮/6 KiB 完整 pair 裁剪和 UNTRUSTED_TRANSCRIPT_V1。失败、取消、截断、pending、Tool 协议/Result/Trace 不进入成功 History。浏览器只限制提交 envelope 大小，不重写后端 Projection；模型/设备切换确认并清本会话，刷新清空；epoch 失效保留草稿、清旧历史、重新 Bootstrap，不自动重发。
- UI textContent 渲染；独立 Tool 卡片、安全有序 Steps、Usage/状态详情，500ms 状态轮询不丢最终步骤。无 Prompt、参数、Raw Tool Result、Reasoning、凭据或 traceback。最终 POST 是提交依据，Stop 后迟到响应不作为成功回答；远端计算/费用是否停止仍为 UNKNOWN。
- 安全 Trace 位于 Git ignored 的 outputs/management_web/assistant-traces.jsonl，复用 JsonlTraceSink，只存 allowlist 元数据，不保存对话正文。SQLite 和事件生命周期不因聊天清空/切换而改变。

这是本机开发集成，不是生产账户/租户权限或设备鉴权。离线 Fake Provider 验证不代表真实回答质量已验收；真实 Provider 调用需要用户另行授权。

### R2B-3.3：Knowledge Tool 装配与来源隔离

- 每个 ManagementAssistant 只创建一个原 `KnowledgeService`，数据固定为包内 `src/fishery_ai/resources/knowledge/eel_knowledge.json`，使用原 portable 检索实现；不是资料页面 Demo 文件，不接入新上传/索引/RAG。
- 原 ToolRegistry 创建唯一 `search_fishery_knowledge` Definition、validator 和 Handler；ManagementToolRegistry 直接保留该 ToolDefinition 对象。实际执行仍走同一 ToolCallingService / ToolExecutor，不复制检索逻辑、Schema 或执行循环。全局 Policy 校验 Registry 可识别评分等原 Tool，不表示管理应用可以执行它们。
- Knowledge 只接受现有 `{"query":"..."}` 合同，固定 top_k=3、每条正文最多 800 字符加省略号；参数、结果大小限制和异常映射均由原合同执行。非法参数不会检索，未授权返回 TOOL_NOT_ALLOWED；检索异常是 TOOL_EXECUTION_ERROR，不能伪装成 NO_MATCH，不继续模型请求。
- OK 的合法 Evidence 只能授予 RETRIEVED_PROJECT_EVIDENCE；NO_MATCH 只表示本轮检索完成，不授予命中或当前观测来源。二者都不能满足 CURRENT_OBSERVATION_QUERY / CURRENT_SCORE_EVALUATION。History、模型正文和来源声明不生成 Receipt。
- Web 仍是 OFF / Normal / 1 Call / 1 Round / 最多 2 Requests。两项授权表示模型择一，不表示同轮双 Tool；多个调用整批拒绝，Request #2 的 tool_choice=none，继续调用为 TOOL_ROUND_LIMIT，失败不重试、不提交成功 History。Knowledge 成功但后续模型失败时仍可保留执行审计，不提交成功回答。
- UI 按实际 Tool 显示独立卡片；Knowledge 只显示背景来源标识、执行状态、命中数量和耗时，NO_MATCH 显示“检索完成 · 无合格命中”，不显示 query、Raw Result、Evidence 正文。Knowledge 不是当前水质或现场疾病确诊依据。模型自由正文的来源可信度仍需人工验收，不由 Fake Provider 测试证明。
- 默认授权不变，不伪造 qualification_id、不修改 Preset / Capability / Normal 或 Streaming 发布配置。管理端没有继承 Prototype 的 2/2/3 或 Streaming Scope；以后开放多轮须单独冻结并验证精确 Preset identity、协议、Prompt/History、Tool 定义/数据绑定、预算和确认 revision，再接入发布门禁。

使用原 Prototype 的 Tool Manager → Assistant 标签显式授权项目知识，刷新管理 Assistant 后按新的 revision 重新确认。两 Web 共用既有 Policy 文件，用户调整也会影响原 Prototype 的下一次请求；管理程序不替用户修改文件或建立第二套权限界面。操作和离线测试见 [BUILD_RUN](BUILD_RUN.md)。

### R2B-3.2：精简水质 Tool DTO

`management_web.ai_adapter.project_water_tool(capture)` 只投影、不读取或分析；`projection_version=management-current-water@1` 纳入管理端确认 revision，不改变模型 Tool Schema 或原 Preset 资格范围。

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

文件管理与索引/检索仍分开，资料页面只展示 Demo 元数据；本轮没有新增 RAG。未来 Knowledge Evidence 不能认证现场事实；Analysis 自动 RAG 与 Assistant Knowledge Tool 保持原边界。

Video/NPU 将通信、推理、事实归一化和网页播放分离；不迁移桌面 GPU 项目。Events 人工处理、附件授权和通知待独立设计。管理员权限与开发设备接入开关分离。

共享 Runtime 的内部合同见 [Analysis / Assistant](../../docs/deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md)、[Tool Runtime](../../docs/deep-dive/tools/READ_ONLY_TOOL_CALLING.md)、[凭据](../../docs/deep-dive/operations/PRIVATE_CREDENTIAL_STORAGE.md)。启动与验收见 [BUILD_RUN](BUILD_RUN.md)。

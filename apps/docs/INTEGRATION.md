# 统一监测协议与集成边界

## 1. 当前运行链路

```text
Simulator：Scenario → 逻辑采样 → 10 秒窗口 → HTTP
    → management_web Ingestion：本机与令牌检查
    → monitoring.contracts：v1 严格校验
    → MonitoringRepository：单事务保存 water / visual / 事件
    → MonitoringService：当前状态、历史、query-time Freshness
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

已知时间边界：本机真实时间测试出现过 OBSERVATION_TIME_REJECTED，UTC 观测时间与 monotonic 调度不保证绝对同步；默认模拟器零缓冲可能触及严格未来时间门禁。本阶段不修改调度/时间容差，联调测试使用明确滞后一秒的已完成窗口，仍保留未来/超龄拒绝测试。后续应单独决定设备时钟偏差策略，不能用放宽规则证据门禁解决。

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
- rules.py 为小型纯函数边界，不依赖 Flask、SQLite、模型或网络；事件转换仍位于原事务中。DomainAnalysisService / EventService 全面提取、趋势规则、AI 桥接均留待下一阶段。

历史 API 保留原 summary；当前趋势展示将无效/覆盖不足均值置为 null，并附 metric_quality，不把历史不可用均值连成可靠趋势。

## 5. 场景编写与连续运行

`apps/simulator/scenarios.py` 用 frozen Phase 列表定义全局 elapsed 时间线；按 at_s 升序，从零开始。相邻数值 Phase 线性插值，加小幅有界随机游走，模拟波动和渐变；连接/缺失/标定为离散开关。

主场景 normal、low_oxygen、suspected_disease、reduced_feeding、combined_anomaly、device_offline；另有 partial、invalid、visual_only、water_only 用于数据边界验收。新增场景只编辑 Phase 定义，不改 HTTP transport；无需通用编辑器。

WaterQualityGenerator 与 VisualDetectionGenerator 使用独立 RNG（seed、seed+1），视觉采样周期不会改变水质随机序列。seed 默认 42；固定 start、session_id、seed、场景和周期时完整批次可复现。真实运行自动生成新的 session_id/启动时间，值的随机序列固定，ID/时间按本次实例变化。advance 可离线快速推进；switch_scenario 不重置时间/RNG/sequence，新场景按全局 elapsed 求值，人工切换处允许场景值跳变。

实时 CLI 使用 monotonic 定时，默认首批在 10 秒后发送，维持 10 秒时间网格。阻塞/唤醒迟到时只生成并发送最近一个完整窗口，跳过更早错过的窗口（elapsed 与 sequence 同步推进，历史保留缺口），不生成/补发追赶批次；下次等待下一网格边界。固定 seed 在相同推进/跳过条件下可复现，不承诺阻塞运行与未阻塞运行数值相同。失败即停止，无透明 retry、重定向或代理；Ctrl+C 关闭上报资源。device_offline 不发送任何批次，服务器自行变过期/中断。

## 6. Web 与未来 AI 的统一读取

正常启动的四页面来自 MonitoringService；浏览器每 5 秒只读 Bootstrap。历史和事件不由页面生成；读取失败显示失效，恢复后重新读取，旧异步响应不能覆盖新区域选择。页面保留草稿/筛选；没有实时视频或生产权限声明。

所有页面时间统一经 timeText 使用 Intl.DateTimeFormat 的 Asia/Shanghai 时区转换，显示到秒并标记“北京时间”；趋势轴显示时分秒，图注标明北京时间 UTC+8。内部通信/存储仍为带时区的 UTC，不手动加 8 小时。观测、服务器接收、查询、窗口起止、历史和事件时间使用同一格式化入口；30 秒过期/90 秒离线判断不受显示时区影响。

HTTP 读取：/api/bootstrap?device、/api/monitoring?device、/api/monitoring/history?device&channel=water|visual&limit=N、原事件 API。历史上限不超过 repository.history_limit；缺省查询 60 条。

未来同进程装配同一个 repository / MonitoringService，将 `bind(device_id)` 返回的 frozen DeviceReadContext 交给 Tool：其 water_reader.query() 使用原 CurrentWaterQualityReader，从**同一 SQLite current** 生成 canonical Reading，保留来源、观测/接收时间和 query-time freshness。query-time 查询不等于新采样。

设备 ID 在 context 中绑定，不跟随网页全局选择改变；它不是冻结旧观测，下次 Tool 查询仍可取得该设备的新数据。如后续需要视觉 Tool，可使用同服务的视觉读取。跨进程须共同受控服务/存储，不靠导入类共享内存。

本轮没有把原 Prototype Tool 绑定到此服务，也没有接 AI。后续 Adapter 才复用 AssistantService、Gateway、CredentialSnapshot、RuntimeSnapshot、Policy、Ledger、Commit Gate、History Projection、Deadline 和 Stop；不复制 Tool 循环、不混合多次观测、不把模拟来源升级为真实事实。

## 7. 开发写入边界与真实替换

写入默认关闭；--enable-ingestion 需要 FISHERY_SIM_INGEST_TOKEN（32–128 ASCII 字母数字）。只接受 loopback peer、允许的 Host、正确令牌、JSON 与无 Origin 的设备请求；不信任 forwarded IP、不提供 CORS，8 KiB 上限。令牌只在进程内，不发送到页面、不写文件/日志、不是现有模型 Key。

此接口只认证“本机模拟生产端”；真实 source_kind 不由客户端自报，当前所有接收来源固定 simulator。真实设备/NPU 接入须新增受控生产 Adapter 和服务器设备/来源登记、独立认证/部署配置；不能只换 URL 就把 simulator 标签改成 sensor。生产 TLS、账户权限、限流、备份、迁移、设备租户隔离仍未实现。本机令牌与 IP 限制不是生产鉴权。

AI 消息仍固定 503；无 device control、配置写入、文件任意访问、Shell、数据库管理 API。不要读取或复制正式 API Key，不改现有 Credential/ACL，不加载源码根 .env。

## 8. 其他业务边界

文件管理与索引/检索仍分开，资料页面只展示 Demo 元数据；本轮没有新增 RAG。未来 Knowledge Evidence 不能认证现场事实；Analysis 自动 RAG 与 Assistant Knowledge Tool 保持原边界。

Video/NPU 将通信、推理、事实归一化和网页播放分离；不迁移桌面 GPU 项目。Events 人工处理、附件授权和通知待独立设计。管理员权限与开发设备接入开关分离。

共享 Runtime 的内部合同见 [Analysis / Assistant](../../docs/deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md)、[Tool Runtime](../../docs/deep-dive/tools/READ_ONLY_TOOL_CALLING.md)、[凭据](../../docs/deep-dive/operations/PRIVATE_CREDENTIAL_STORAGE.md)。启动与验收见 [BUILD_RUN](BUILD_RUN.md)。

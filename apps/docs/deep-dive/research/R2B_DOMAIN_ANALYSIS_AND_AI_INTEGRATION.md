# R2B-0：Domain Analysis 与 AI 集成架构评估

日期：2026-10-14。源码基线：`51c405a`，审查开始时工作树干净。

**结论：建议先建立共享 Domain Analysis / Event 合同，再接管理平台 AI。** 当前已有可靠的数据读取和 AI 执行基础，无需复制 Runtime。尚缺跨通道分析、规则发布治理、事件状态语义和管理系统 AI 装配。本报告全部新增结构均为建议，尚未实施；仅阅读源码与测试，没有运行测试、模型、NPU 或访问运行数据库。

## 1. 当前真实链路与职责

### 原 AI Prototype

```text
显式 Scenario Apply → Telemetry → WaterQualityReading → 内存 Snapshot Store
  ├─ Web 捕获 CurrentWaterQualityView
  │    → Analysis：Diagnosis → 自动 Knowledge 检索 → 固定 AnalysisContext
  │    → ModelGateway → 可选只读 Tool → 模型解释 / 建议
  └─ Assistant：System + 已裁剪/投影 History + 本轮问题
       → ToolCallingService → 可选 Tool → Final → Source/Commit Gate
```

- **Domain**：`DiagnosisService.diagnose()` 是无模型、无网络的水质规则函数，输入 Reading，输出 `RuleFinding`。质量、新鲜度与阈值异常都可成为 Finding；不负责事件持久化或疾病确诊。
- **Analysis**：`Orchestrator.analyze()` 在调用模型前捕获事实、计算规则、自动检索知识。`_build_model_request()` 将三类上下文分开，模型产生 inference / recommendations / uncertainty。可选 Tool 使用共享 Coordinator，后来的观测不能覆盖固定事实。Normal 与普通 Streaming 均保留固定流程；Analysis Tool Calling 仍为单轮。
- **Assistant**：没有自动 Snapshot / Diagnosis / RAG 注入；当前事实由实际 Tool 返回。History 默认 `UNTRUSTED_TRANSCRIPT_V1`，仅投影完整保留的文本对。Assistant 提交检查最终正文、finish、取消/超时、Trace 与来源要求。
- **Tool**：Registry 定义和依赖绑定 → Policy 授权 → Executor 参数/预算校验 → Handler。查询 Tool 调 Reader 与 Diagnosis，评分 Tool 调 Reader 与实验评分，Knowledge Tool 调同一个 KnowledgeService。Handler 不负责模型循环。
- **Runtime**：ToolCallingService 统一 Normal / 内部 Streaming 和有界多轮；单轮 1/1/2，多轮 2/2/3，每轮最多一个 Tool。Preset、CredentialSnapshot、RuntimeSnapshot、RequestHandle、Steps、Ledger 与 Commit Gate 属于执行安全基础。
- **知识**：`KnowledgeService` 当前是本地 JSON 分块、字符 TF-IDF/关键词及启发式排序，不是实时观测。Analysis 自动检索与 Assistant 显式 Knowledge Tool 共用检索实现。

重要例外：`Orchestrator` 未传 reading 时仍调用 repository 的 Scenario 兼容路径；现有 Prototype Web 显式传入 Reader 捕获的 reading，避免该路径。新管理平台不能以缺失 reading 调它来获得默认 normal。旧 `DetectionEvent/DetectionSummary` 主要表达单帧框与置信度；当前固定 Analysis 并未调用 detection repository，不能认为已支持视觉融合。

### 新管理平台

```text
apps/simulator：共同时间线上的水质采样 / 视觉帧 → 10 秒窗口
  → 受控 HTTP Ingestion → DTO 校验 / UTC 规范化
  → MonitoringService.ingest：水质 Diagnosis / 模拟视觉信号规则
  → Repository 事务：历史、current、联系时间、事件阶段去重
  → MonitoringService.snapshot / cameras / history / events
  → Dashboard / Monitoring / Video / Events

MonitoringService.bind(device_id).water_reader → 未来 AI Tool（尚未装配）
```

水质为有效采样均值；可见数为有效帧平均（含零鱼帧）；体长按有效检测记录加权。视觉为信号帧计数和行为比例，非真实 NPU 诊断。无数据不补正常值；来源固定 simulator。旧 AI Web 的内存 Snapshot 与这里的 SQLite 是**两份独立状态**，目前没有共享。

## 2. 重复、耦合与潜在冲突

| 检查项 | 当前事实与迁移风险 |
|---|---|
| 水质阈值 | Monitoring 已直接复用 DiagnosisService，没有第二套养殖阈值。其 `RULE_VERSION=fishery-production-c400b7a-v1` 只是旧标识，不能证明阈值已经获得生产批准。温度 20–30、pH 7–8.5、DO ≥5 及极值分档须由维护者确认物种/阶段/条件。 |
| 多入口求值 | Ingestion、snapshot 查询、查询 Tool 和 Analysis 都会调用 Diagnosis。重复计算本身不构成重复规则；但若各自增加质量过滤或视觉判断，就会发生语义分叉。需共享纯求值入口，不将上次 Finding 当永远有效的当前判断。 |
| 有效性与数值 | Reading 任一 invalid 样本导致整体 INVALID，诊断仍检查非空数值；评分则返回 NOT_SCORABLE。所有指标有均值但部分采样缺失时，Reading 可以为 VALID，覆盖率保留在窗口统计中。需定义每指标可诊断条件，避免无效/低覆盖均值被宣传为已确认异常。 |
| 趋势 | snapshot.trend 传均值、时间和窗口长度，没有每指标质量/有效样本数。当前图表排除 null，但非空 INVALID 均值仍可能入图；“图上有值”不等于有效趋势证据。 |
| Finding 与事件 | 查询时会新增 STALE Finding，过期/离线不是定时写入的事件。入库时的事件是当时判断，不能等同于查询时的当前 Finding。 |
| 等级与版本 | Repository._events 固定事件 severity=warning，另存 finding_severity；持续事件只更新时间/批次，初始标题、等级和规则版本保留。去重键没有规则版本，规则升级需明确分段/重评策略。 |
| 恢复判定 | 水质某 Finding 消失就会关闭对应事件，缺失指标也可能令原数值 Finding 消失，不能据此证明恢复正常。R2A.1 已保护“全无效视觉帧不自动消退”，但不足以涵盖水质缺失或低覆盖。 |
| 跨通道一致性 | 水质 current+history 由一个读事务捕获；bootstrap 分别读水质、视觉和事件，不是统一跨通道快照。同设备也不保证窗口相同。 |
| 元数据损失 | canonical Reading 没有 batch/device/window、有效样本数或 connectivity；DeviceReadContext 只绑定设备和 Reader。直接桥接现有水质 Tool 可复用事实/时间/诊断，但不能自动传递全部窗口证据。 |
| 视觉证据 | 旧单帧 Detection 与新窗口统计不可直接互换。模拟器独立生成可见数和信号，缺少真实帧/目标/置信度关联，不能作为疾病验证材料。 |
| 物理范围 | HTTP 合同与 WaterQualityReading 分别验证温度/pH/DO 物理范围，当前范围一致；未来变更用 parity 测试保护。物理输入校验与养殖风险阈值是不同责任。 |

## 3. 目标分析链路与依赖方向

```text
Simulator / Sensor Adapter / NPU Adapter
  → Ingestion：身份、来源、格式、单位、窗口、幂等校验
  → MonitoringRepository：权威事实 / current / 有界历史
  → 捕获设备范围内的事实与所需历史（标识独立通道版本）
  → DomainAnalysisService：质量/覆盖 → 水质规则 / 视觉信号 / 趋势摘要
       ├─ Dashboard / Monitoring / Video：同一分析合同的展示投影
       ├─ EventService：规则授权 + 确定性阶段转换 → 事务内保存事件
       ├─ AI Tool：只读投影 → 现有 Registry / Executor
       └─ Analysis Adapter：固定 Analysis Context + 背景 Evidence → LLM

Assistant Adapter → 现有 AssistantService / Runtime
  → 按需 Tool → 同一 Monitoring / DomainAnalysis → Final
```

### 最小模块建议（暂不创建）

- `apps/monitoring/analysis.py`：纯 `DomainAnalysisService.evaluate(facts, history, evaluated_at, rule_policy)`；不读取 HTTP、数据库、Provider 或 RAG，不改变事实。
- `apps/monitoring/events.py`：纯事件转换规则及薄 EventService；输入新分析和已有阶段，输出事件变更。读取旧阶段、检查 current 是否推进及写事件仍在 Repository 的同一事务，防并发双建和乱序恢复。
- `apps/monitoring/contracts.py`：追加最小事实引用、分析和事件 DTO。无需马上建立另一个跨项目 Domain 框架；实际外部消费者出现后再提取。
- `MonitoringService`：负责绑定设备、捕获事实/历史、选择一次 evaluated_at，调用共享分析并投影，减少在 cameras/ingest 中继续堆规则。
- `apps/management_web/ai_adapter.py`：未来薄应用 Adapter，冻结设备/池上下文，装配正式 Runtime、Registry 和确认/取消接口；不复制执行循环。页面不接触 Provider SDK。
- `src/fishery_ai/`：继续保留可复用 Domain 和 AI Runtime；不得反向 import 管理 apps。应用层通过依赖注入调用旧服务。

“同一权威来源”不是要求所有查询返回同一时刻：固定 Analysis 捕获后不变，Assistant Tool 可取得更新观测；用引用和时间明确两次读取，Ledger 按步骤保留，不能合并成一份当前事实。需要跨通道分析时增加一次有界联合 capture；即使同一事务读取，水质/视觉窗口仍可能不同，须保留差异并按允许时间跨度判断是否可关联。

## 4. Domain Analysis 与 Event 最小合同

以下字段是建议，不能描述为已存在接口。

| 合同 | 最小字段 / 语义 |
|---|---|
| ObservationRef | device_id（池映射待决定）、channel、batch_id、source_kind/source、observed_at、received_at、window、aggregation、quality、freshness、connectivity、统计版本。标识实际观测，不使用 query 时间替代采样时间。 |
| WaterFacts / VisualFacts | 保留原 canonical 水质与每指标样本证据；视觉保留 valid_frames、信号计数/分母、行为比例、加权体长/测量数/标定/model_version。通道可缺失；不把未测量编码成零。 |
| DomainAnalysisResult | schema_version、analysis_id、device/context、evaluated_at、observation_refs、status=AVAILABLE/PARTIAL/NO_DATA、facts、findings、trend_summary、rule_pack_id/version、publication_status=PROTOTYPE/APPROVED。可用性不是健康等级。 |
| Finding | 复用 RuleFinding 的 code/severity/message/facts_used/rule_version；外围追加 kind=DATA_QUALITY/WATER_RISK/VISUAL_SIGNAL/BEHAVIOR_SIGNAL/TREND、observation_refs、assessment=CONFIRMED_SIGNAL/PROVISIONAL/INSUFFICIENT_DATA/NOT_EVALUATED、规则发布状态。CONFIRMED_SIGNAL 只指检测/规则条件成立，不是疾病确诊。 |
| TrendSummary | 明确查询区间、指标、实际保留区间、有效窗口数/覆盖、缺口、首末值/变化量、单位及算法版本；历史不足返回 INSUFFICIENT_HISTORY。第一版先做摘要，不发布趋势风险阈值或预测。 |
| Event | event_id、device/channel、finding_code、rule_version、source_kind、analysis/observation refs、first/last_observed_at、received_at、resolved_at、真实 finding severity、lifecycle_state=ACTIVE/RESOLVED/INDETERMINATE。ack/处理状态另列，未实现时不假装已处理。 |

核心状态规则：

- NO_DATA：查询完成但无对应观测；不构造健康结论，也不能自动解除旧异常。
- INVALID/PARTIAL/STALE/OFFLINE：分别表达质量、完整性、观测年龄、联系状态；可并存。某指标无法判断时记录 NOT_EVALUATED，而非正常。
- 无有效视觉帧：无视觉判断；有效零鱼帧可作为计数证据，但不产生有效体长。无信号不证明无疾病。
- 事件恢复需要对应条件被有效数据明确解除；未知/失联进入或保留未确认状态，不冒充恢复。历史补报不回滚 current/活动事件；重复报送不重建事件。
- 查询时 Aging 更新当前分析，不因用户多次读取重复造事件。若未来要持久化“过期/离线事件”，单独设计受控生命周期评估触发，不放进 Tool 读取副作用。
- 规则未批准：输出明确 PROTOTYPE/模拟风险提示，可保留开发事件；不进入正式生产告警发布。LLM 不得把标签升级为专业结论。

示例：同窗 34°C / DO 2.2 与体表异常帧，可分别产生原型水质 Finding 和视觉疑似信号，并记录共同设备/窗口关联；不能确定病因，更不能据此确诊疾病。知识检索只补背景解释。

## 5. 旧代码复用 / 提取 / 重写决策

| 现有代码 | 建议 | 理由与限制 |
|---|---|---|
| WaterQualityReading、Quality、Freshness、evaluate_freshness、CurrentWaterQualityReader | 直接复用 | 已被 Monitoring 使用；新增窗口/设备证据放外层，不把视觉汇总塞入 Reading。Reader 的具体 Store 类型标注与实际 duck typing 可在真正桥接时最小澄清。 |
| DiagnosisService / RuleFinding | 先复用计算，后提取可配置规则入口 | 不复制阈值；先确认质量门禁及规则授权。当前版本名不能作为生产依据。保留旧原型 parity，不先大规模搬模块。 |
| WaterQualityScoringService | 保留独立实验能力 | 引用 Diagnosis 正常区间，另有惩罚/等级公式；不是生产风险规则，也不是疾病分析。规则参数将来需使用同一明确版本来源。 |
| MonitoringRepository | 复用存储、事务和时序 | 事件纯转换可提取；不把业务新规则直接埋进 SQL，不替换 SQLite 或迁移历史数据库作为本阶段前提。 |
| MonitoringService 视觉判断 | 提取到共享 DomainAnalysis | 当前 any-count / any-feeding-anomaly 是模拟提示；未来 NPU 的置信度/有效覆盖/持续性规则需重新设计验证，不能照搬为生产阈值。 |
| Orchestrator | 复用固定水质流程，逐步加入共享上下文边界 | 显式传 captured reading；禁止缺失时 Scenario fallback。现有 AnalysisResult 必需 water，无法直接承载 visual-only/NO_DATA；先新建外围可选通道合同，实际消费者需要时再做小型上下文注入点。 |
| AssistantService、ToolCallingService、Gateway、Activity、History、Ledger、Commit Gate | 直接复用 | 新 Web Adapter 装配，保持预算/权限/取消/发布 Scope；不在新 Web 复制循环或 Prompt。 |
| 三个 Tool Handler / Registry | 复用只读执行与注入模式，适配共享判断 | Reader 可绑定同一 SQLite；当前水质 Handler 仍自己 diagnose，若要输出共享扩展分析需薄数据投影/依赖注入，不增加第二份规则。修改定义会影响 Scope 指纹，须明确资格更新。 |
| KnowledgeService / Knowledge Tool | 当前复用，未来以检索 Adapter 替换 | 固定有界 search 接口，保留 Evidence 来源与 NO_MATCH；新 RAG 可更换索引，避免复制索引或把 Files UI 当检索。 |
| 旧 MockRepository、Telemetry Simulator、单帧 DetectionSummary | 原型保留，管理系统不复用生产路径 | Mock 数据源不能接权威 current；新连续模拟器已独立。单帧框数不等于窗口平均鱼数，不强行转换。 |
| 旧 Web 路由与前端 | 不迁移整页 | 复用服务合同与安全经验，新管理页面维持原布局；认证/设备上下文/确认/epoch 必须在新服务端实现。 |

## 6. 回答质量限制与未来 Tool / RAG 接口

1. **执行可信不等于正文可信**：Receipt 证明真实执行及返回的有限来源，不能证明每句回答遵从事实。AUTO 下无 Tool 也可以提交；History framing 和来源 Prompt 是软约束，不能视为自动当前事实路由。Analysis JSON 解析验证形状，不验证医学正确性；解析失败仍可返回 COMPLETED + structured_parse_ok=False，管理端须明确降级展示。
2. **上下文范围有限**：当前 Analysis 主要是水质，没有视觉/历史融合输入；Assistant 最多保留 6 轮 / 6 KiB 的完整 pair，多轮预算最多 2 个 Tool。三个来源都需要时不能自动扩容或并行调用，需先确定产品用例，诚实说明未取得来源。
3. **检索命中不是因果证据**：当前小型鳗鲡知识 JSON、字符相似度和加权排序可能命中不相关疾病内容；score 不是病因置信度。Knowledge Tool 有 3 条/文本长度上限，NO_MATCH 表示检索完成无命中。未来先验证引用准确性/相关性，再选择索引或 embedding，不将新 RAG 当本次迁移前置。
4. **未来视觉 Tool**：返回共享 VisualFacts / Finding、版本、有效帧、时间与校准限制，不读 Simulator/NPU raw packet，不输出确诊、未授权图片或路径。静态 Registry / Catalog / Policy 与 Source Receipt 需显式扩展；现有 Receipt 只认识水质/评分/Knowledge，不能自动将视觉结果认证为 CURRENT_TOOL_OBSERVATION。
5. **未来历史 Tool**：设备在 Turn 绑定，区间/指标/limit 严格服务端校验，返回真实存储覆盖/缺口及算法版本；历史来源不得冒充当前观测。是否增加独立 HISTORICAL_OBSERVATION_REQUIREMENT 需单独设计，不复用当前查询已完成标志偷换语义。
6. **Analysis 自动 RAG 与 Knowledge Tool**：可共用检索服务，但两次 Evidence 分别标识 retrieval id/时间/查询用途。若允许 Analysis 后续 Knowledge Tool，不把后一次结果覆盖固定 RAG；UI 和模型 Context 应区分两组来源。缓存不能将旧检索认证为本轮新检索。
7. **疾病与药物安全**：当前 Prompt 限制缺乏直接证据时诊断/药物剂量；不是专业审核或语义硬拦截。新系统先明确用户职责、直接证据标准和人工复核流程，AI 输出不得写入事实、确诊或事件真相。

## 7. R2B 分阶段建议及验证成本

| 阶段 | 最小交付 | 进入下一步的条件 |
|---|---|---|
| R2B-1：合同与规则身份 | Optional 通道分析合同、规则 PROTOTYPE 状态、每指标质量/覆盖、事件未知与恢复语义；不接模型 | 人工确认规则适用范围；确定水质 INVALID 下哪些字段可判断。合同 fixture 覆盖 NO_DATA/部分通道/不同窗口。 |
| R2B-2：共享纯分析 / 事件投影 | 提取 Monitoring 视觉/业务分析入口，水质复用 Diagnosis；同事务事件转换，当前与历史带质量 | 页面/服务/Tool 适配 fixture 对同一设备、版本、evaluated_at 得到一致 Findings；去重、乱序、版本变化、缺失不恢复测试通过。 |
| R2B-3：管理 Assistant Normal 桥接 | 同一 repository 与设备绑定 Reader，现有三 Preset/权限/确认/Stop/History/epoch；先离线 | 模型调用只由 Send 触发；NO_DATA 不 Apply normal；Turn 中切设备不污染请求；保留原 Prototype。 |
| R2B-4：Analysis 固定上下文桥接 | 捕获共享 DomainAnalysis，独立可选 LLM 解释；失败仍可查看确定性事实 | 固定上下文不被后来 Tool 覆盖；NO_DATA/visual-only 有明确页面状态；无双重阈值或事件副作用。 |
| 后续：Scope / 新 Tool / RAG | 精确范围内接现有 Multi-Round/Streaming，再分别开发视觉/历史查询与新检索 | 定义/Prompt/工具组合变化重新审查资格；需要真实 Provider 时单独授权，不继承旧组合结论。 |

测试分层：纯 Domain/事件转换先跑快速向量测试，再跑 Monitoring 临时 SQLite 与 Flask/Node 合同；真正 Runtime 桥接时才追加 Assistant/Source/Tool/Scope targeted 和一次必要产品回归。Fake SDK 验证取消/截断/Source Gate；不以重复全量测试或真实时间等待代替规则测试。禁止把测试 Mock 成功描述为真实 Provider / NPU 证据。

### 当前测试证据（仅阅读，未重新执行）

- [Monitoring pipeline](../../../monitoring/tests/test_pipeline.py)：同源 Reading、按通道缺失、query-time freshness、乱序/事务回滚、事件去重/恢复、设备绑定、加权统计、全无效视觉帧不恢复。尚无跨通道融合/趋势风险/生产阈值批准测试。
- [Simulator tests](../../../simulator/tests/test_simulator.py)：有效样本精确均值、加权 17.5 cm、零鱼/无效帧、逐帧标定、阻塞跳窗。
- [Analysis Tool tests](../../../../tests/tools/test_analysis_tools.py)：固定上下文保留、Tool 后观测变化、NO_DATA、门禁和单轮预算。
- [Source tests](../../../../tests/assistant/test_assistant_sources.py)：负向业务结果完成操作但不授予正向来源、正文 imitation 不生成 Receipt、Ledger 不合并多时观测、失败不能成功提交。
- [评分](../../../../tests/domain/test_water_quality_scoring.py)与[Knowledge Handler](../../../../tests/tools/test_knowledge_handler.py)：实验/无效/部分评分及背景 Evidence、NO_MATCH、有界安全投影。

## 8. 需人工决定的事项

1. 哪些水质阈值有可靠来源，适用何种鳗鲡阶段/环境，谁批准；批准前统一原型提示，不发布生产规则。
2. 每指标有效样本最低覆盖、INVALID 是否允许有限阈值提示、STALE 数据是否只作历史解释，以及事件恢复必须具备哪些有效证据。
3. 设备与养殖池映射、多水质传感器/多摄像头聚合、跨通道最大时间差；同池不等于同一观测。
4. 视觉异常的置信度、标定、有效帧比例、持续时间与人工确诊要求；目前不能从模拟信号决定这些生产阈值。
5. 事件保留期、等级升级、规则版本变化、人工处理/确认和生命周期状态；当前有界存储不是长期可追溯生产事件库。
6. 优先接只读 Assistant 还是固定 Analysis；建议先共用 Domain 结果、随后 Normal Assistant，保持 Analysis 作为独立固定流程。

## 9. 关键源码定位

- [domain.py](../../../../src/fishery_ai/domain.py)：DiagnosisService 第 8 行、diagnose 第 14 行；[contracts.py](../../../../src/fishery_ai/contracts.py)：Reading / Finding / ObservedFacts / AnalysisResult。
- [application.py](../../../../src/fishery_ai/application.py)：AnalysisContext 79、Prompt 构建 97、解析 129、检索 176、Normal 188、Streaming 272；[Prototype web.py](../../../../src/fishery_ai/web.py)：Reader/Registry 装配 241–252，正式 Analysis 显式捕获传入 1293–1317。
- [assistant.py](../../../../src/fishery_ai/assistant.py)：Request 102、Context 164、Service 224、提交边界 258；[assistant_sources.py](../../../../src/fishery_ai/assistant_sources.py)：Receipt 31、执行来源推导 154、Ledger 241、满足检查 292。
- [tool_conversation.py](../../../../src/fishery_ai/tool_conversation.py)：预算 154、模式 176、Service 333、循环 393；[Registry](../../../../src/fishery_ai/tools/registry.py)、[Executor](../../../../src/fishery_ai/tools/executor.py)、[Knowledge](../../../../src/fishery_ai/knowledge.py)。
- [Monitoring service](../../../monitoring/service.py)：Reading 转换 18、设备绑定 68、入库求值 73、当前分析投影 104、视觉 138；[Repository](../../../monitoring/repository.py)：入库事务 65、事件转换 113、捕获 149。
- [Management app](../../../management_web/app.py)：bootstrap 52、AI 固定 503 接口 139；[Simulator generator](../../../simulator/generator.py)：视觉汇总 80。现有稳定监测合同见 [INTEGRATION](../../INTEGRATION.md)。

**停止点：本报告是设计建议。未创建 Domain/Event 模块、未迁移旧代码、未修改规则或 Runtime，等待讨论。**

# 水质 Scenario 与 telemetry 数据准备

**CURRENT 审计 + PROPOSED 研究 · 2026-10-03**。代码确认事实与未来建议分开。依据当前 contracts.py、domain.py、repositories.py、composition.py、application.py、web.py、__main__.py、Mock/知识资源及离线测试；没有修改生产项目、领域阈值、RAG/Grounding 或模型合同。

## 1. 当前 Scenario 与实际数值

包内水质列表是以下 **5 项**，Web 自动读取资源 key，CLI choices 同为这 5 项。不存在额外包内 invalid/high_temperature 等场景。默认 Web 和 CLI 分析没有真实传感器输入。

时间代号均为 UTC：A=2026-09-27T00:00:00Z，B=2026-09-26T23:00:00Z，R=2026-09-27T00:00:20Z。

| CURRENT scenario | 温度 °C | pH | DO mg/L | observed_at | retrieved_at | Quality / Freshness | source | missing | Findings（顺序） |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| normal | 28 | 7.5 | 6.4 | A | R | valid / fresh | mock:sensor-normal | 无 | 无 |
| low_oxygen | 28 | 7.5 | 2.2 | A | R | valid / fresh | mock:sensor-low-oxygen | 无 | OXYGEN_CRITICAL_LOW |
| partial | 28 | None，原始为 -- | 6.4 | A | R | partial / fresh | mock:sensor-partial | ph | SENSOR_PARTIAL |
| stale | 28 | 7.5 | 6.4 | B | R | valid / stale | mock:sensor-stale | 无 | SENSOR_STALE |
| partial_stale | 28 | None，原始为 -- | 6.4 | B | R | partial / stale | mock:sensor-partial-stale | ph | SENSOR_PARTIAL、SENSOR_STALE |

当前字段是 **retrieved_at**，表示取快照时点，不是已实现的 received_at/acquired_at，也不证明硬件接收时间。fixture 中 A→R 为 20 秒，B→R 为 3620 秒；stale_after_s 默认 300，可注入配置，只有 age > threshold 才 stale（等于仍 fresh）。这些时间固定，不使用运行当天的 utcnow 重新判定；适用于可复现测试，不可冒充实时数据。

当前每个水质结果的 ObservedFacts.detection_summary 为 None。另有独立 Detection fixtures：

| CURRENT detection | observed_at | source / model / frame | detections / summary |
| --- | --- | --- | --- |
| normal | A | mock:camera-1 / mock-detector-v1 / frame-001 | eel 2 条；confidence 0.93/0.88，均有 bbox/track_id；count 2，mean 0.905 |
| count_jump | 2026-09-27T00:00:05Z | mock:camera-1 / mock-detector-v1 / frame-002 | eel 7 条；confidence 0.91/0.92/0.87/0.83/0.89/0.90/0.86；无 bbox/track_id；mean 0.882857… |

没有水质场景自动绑定 count_jump，没有 YOLO 或数量变化诊断规则；检测时间与水质时间也没有默认融合逻辑。

## 2. 当前阈值与 RuleFinding

规则版本 **fishery-production-c400b7a-v1**。下表“无告警”仅表示当前程序没有输出该指标 Finding，不表示专业养殖安全结论。

| 指标 | 精确区间 | code | severity |
| --- | --- | --- | --- |
| 温度 | t < 15 | TEMP_CRITICAL_LOW | critical |
| 温度 | 15 ≤ t < 20 | TEMP_LOW | warning |
| 温度 | 20 ≤ t ≤ 30 | 无 | — |
| 温度 | 30 < t ≤ 33 | TEMP_HIGH | warning |
| 温度 | t > 33 | TEMP_CRITICAL_HIGH | critical |
| pH | p < 6.5 | PH_CRITICAL_LOW | critical |
| pH | 6.5 ≤ p < 7 | PH_LOW | warning |
| pH | 7 ≤ p ≤ 8.5 | 无 | — |
| pH | 8.5 < p ≤ 9 | PH_HIGH | warning |
| pH | p > 9 | PH_CRITICAL_HIGH | critical |
| DO | o < 1 | OXYGEN_CRITICAL_EXTREME | critical |
| DO | 1 ≤ o < 3 | OXYGEN_CRITICAL_LOW | critical |
| DO | 3 ≤ o < 5 | OXYGEN_LOW | warning |
| DO | o ≥ 5（合同允许 0–100） | 无低氧告警，无高氧规则 | — |

Quality INVALID → SENSOR_INVALID / warning；PARTIAL → SENSOR_PARTIAL / warning，两者互斥。Freshness STALE → SENSOR_STALE / warning，可与任一 Quality/数值异常并存。没有“normal finding”。

每个指标使用 if/elif，较严重分支优先：0.9 DO 只产生 EXTREME，不叠加 LOW；34°C 只产生 CRITICAL_HIGH。多个指标之间不收敛成全局一条，不自动产生“联合异常新规则”。输出顺序为 Quality → stale → temperature → pH → DO；facts_used 是对应字段名，SENSOR_STALE 用 observed_at，均携带同一 rule_version。

数值解析合同的物理范围：温度 [-50,100]、pH [0,14]、DO [0,100]；这是输入校验范围，不是养殖规则阈值。None、空字符串、-- 或缺失 key 表示 missing；非数值、NaN/Infinity、越界被置为 None 并标 INVALID；全缺失也 INVALID。有效数字字符串可转 float。INVALID 并不阻止对其余非 None 指标诊断，不能宣称当前实现“invalid 后停止分析”。

## 3. 规则与知识库的差异（只登记，不统一）

| 项目 | 当前规则 | 包内 eel_knowledge.json | 差异性质 |
| --- | --- | --- | --- |
| 温度区间 | 20–30 无告警；>30 warning；<20 warning | optimal 25–30，growth 27–29；warning_low=15/high=33，lethal 5/38 | 规则无告警不等于最适；JSON 字段等级名称与程序 critical 边界不同 |
| pH | [7,8.5] 无告警，6.5/9 是 critical 外边界 | optimal [7,8.5]，best [7.5,8]；warning 6.5/9，lethal 5/10 | 最适范围接近，warning/critical 等级名不同；无独立 lethal Finding |
| DO | <5 warning、<3 critical、<1 extreme critical；无上限告警 | optimal [5,8]、growth minimum 5、warning_low 3、lethal_low 1；>8 描述充足/留意夜间回落 | >8 不触发高氧规则；背景气体过饱和知识不证明高 DO 或气泡病 |
| 联合影响 | 各指标独立 Findings | key_relationships 描述温度/DO、pH/氨氮关系 | 没有实际氨氮值或联合确定性阈值，不能凭关系文字造数或新规则 |

本轮没有专业阈值建议、没有添加药物方案，也不把 legacy JSON 当最新权威标准。知识快照版本及出处缺口见[来源](../../src/fishery_ai/resources/knowledge/SOURCE.md)。

## 4. 原覆盖与缺口

原包内覆盖正常、2.2 低氧、缺 pH、过期、partial+stale；test_v01 另有 invalid temp、DO=0.9、temp=34、pH=6.4 等构造值，不等于 Web selectable scenario。原测试不是所有阈值完整的三点边界测试。

缺口包括温度低/高 warning、pH 高 warning/critical、DO warning 与精确边界、正常边缘、质量与异常并存、多指标组合、stale 策略等号、全缺失。**高 DO 是“当前无告警行为覆盖”而非待添加高氧规则**。

本轮选择最小补充：新增 tests/test_water_quality_matrix.py，使用测试内确定性 raw fixtures 和表驱动三点边界；**包内 scenarios.json、CLI/Web choices 与 Domain 代码保持不动**，不为每个测试增加 UI 项目。

## 5. Scenario Matrix

CURRENT 五项见第 1 节。下表 PROPOSED 表示将来若需交互演示可提升为包内场景；本轮仅在离线测试 fixture 覆盖，不是已增加的 Web 场景。每个建议都可用于未来只读 Tool 的事实/规则断言，最后列说明重点。

| PROPOSED id | °C / pH / DO | Quality / Freshness | 目的与预期 Findings | 未来只读 Tool 测试 |
| --- | --- | --- | --- | --- |
| temp_low | 18 / 7.5 / 6.4 | valid/fresh | 单低温 warning：TEMP_LOW | 可，保持程序判断 |
| temp_extreme_low | 14 / 7.5 / 6.4 | valid/fresh | TEMP_CRITICAL_LOW，只一条 temp | 可 |
| temp_high | 31 / 7.5 / 6.4 | valid/fresh | TEMP_HIGH | 可 |
| temp_extreme_high | 34 / 7.5 / 6.4 | valid/fresh | TEMP_CRITICAL_HIGH | 可 |
| ph_low | 28 / 6.8 / 6.4 | valid/fresh | PH_LOW | 可 |
| ph_extreme_low | 28 / 6.4 / 6.4 | valid/fresh | PH_CRITICAL_LOW | 可 |
| ph_high | 28 / 8.8 / 6.4 | valid/fresh | PH_HIGH | 可 |
| ph_extreme_high | 28 / 9.1 / 6.4 | valid/fresh | PH_CRITICAL_HIGH | 可 |
| oxygen_warning | 28 / 7.5 / 4 | valid/fresh | OXYGEN_LOW | 可 |
| oxygen_extreme | 28 / 7.5 / 0.9 | valid/fresh | OXYGEN_CRITICAL_EXTREME，不叠加 LOW | 可 |
| oxygen_high_no_rule | 28 / 7.5 / 12 | valid/fresh | 无 Finding；不创建不存在的高 DO 规则 | 可，防止模型编造高氧诊断 |
| hot_low_oxygen | 34 / 7.5 / 2.2 | valid/fresh | TEMP_CRITICAL_HIGH、OXYGEN_CRITICAL_LOW | 可，多指标保持独立 |
| ph_high_low_oxygen | 28 / 9.1 / 2.2 | valid/fresh | PH_CRITICAL_HIGH、OXYGEN_CRITICAL_LOW | 可 |
| multi_critical | 34 / 9.1 / 0.9 | valid/fresh | TEMP_CRITICAL_HIGH、PH_CRITICAL_HIGH、OXYGEN_CRITICAL_EXTREME | 可，无新联合 rule |
| partial_low_oxygen | 28 / None / 2.2 | partial/fresh | SENSOR_PARTIAL、OXYGEN_CRITICAL_LOW | 可，缺失不是 0 |
| stale_low_oxygen | 28 / 7.5 / 2.2 | valid/stale | SENSOR_STALE、OXYGEN_CRITICAL_LOW | 可，不把旧值当实时 |
| partial_stale_low_oxygen | 28 / None / 2.2 | partial/stale | SENSOR_PARTIAL、SENSOR_STALE、OXYGEN_CRITICAL_LOW | 可，两维不合并 |
| invalid_temp_low_oxygen | bad→None / 7.5 / 2.2 | invalid/fresh | SENSOR_INVALID、OXYGEN_CRITICAL_LOW | 可，错误值与剩余值区分 |
| all_missing | None / None / None | invalid/fresh | SENSOR_INVALID，不虚构阈值 Finding | 可，说明无法完整判断 |
| threshold_neighbours | baseline，其一替换边界±0.01 | valid/fresh | 每边界严格比较，预期如下 | 可，规则回归不依赖 LLM |

边界矩阵（“前/等/后”为 b-0.01、b、b+0.01；—表示该指标无 Finding）：

| 指标 / b | 前 | 等 | 后 |
| --- | --- | --- | --- |
| temp 15 | TEMP_CRITICAL_LOW | TEMP_LOW | TEMP_LOW |
| temp 20 | TEMP_LOW | — | — |
| temp 30 | — | — | TEMP_HIGH |
| temp 33 | TEMP_HIGH | TEMP_HIGH | TEMP_CRITICAL_HIGH |
| ph 6.5 | PH_CRITICAL_LOW | PH_LOW | PH_LOW |
| ph 7 | PH_LOW | — | — |
| ph 8.5 | — | — | PH_HIGH |
| ph 9 | PH_HIGH | PH_HIGH | PH_CRITICAL_HIGH |
| oxygen 1 | OXYGEN_CRITICAL_EXTREME | OXYGEN_CRITICAL_LOW | OXYGEN_CRITICAL_LOW |
| oxygen 3 | OXYGEN_CRITICAL_LOW | OXYGEN_LOW | OXYGEN_LOW |
| oxygen 5 | OXYGEN_LOW | — | — |

数据质量与时间 fixture 还覆盖坏字符串、非有限值、物理越界、缺字段/空值、无时区、观测晚于取样、stale 300 秒等号和 301 秒。质量出错原因细分与 boolean 拒绝目前没有 canonical 字段/保证，是 Adapter 设计缺口，不在本轮修领域行为。

## 6. Canonical 内部合同

WaterQualityReading 已是最小可复用 canonical，ObservedFacts 已可包装它与可选 DetectionSummary，不另建重复 WaterQuality 模型。

| 关注项 | 当前支持 | 未来最小准备 / 缺口 |
| --- | --- | --- |
| 三指标 / 单位 | temperature_c、ph、dissolved_oxygen_mg_l；单位由字段名体现，pH 无量纲 | Adapter 严格转换来源单位；未知单位拒绝/隔离，不让 LLM 转换 |
| 时间 | aware observed_at / retrieved_at，observed ≤ retrieved | received_at 不存在，不将 retrieved 强行改义；有接收延迟/重发需求后再加可选 reception metadata |
| Quality / Freshness | valid/partial/invalid 与 fresh/stale 分开 | freshness 当前固定于取快照时；真实 current 服务需按查询时点策略重新评估，不让 LLM 判断 stale |
| 来源/设备 | 非空 source 文本 | 暂可由 Adapter 映射稳定设备来源；专用 device_id/sequence/packet_id 放接收元数据边界，不凭未知硬件格式添加整套合同 |
| missing | None 表示无值，--/空/缺 key 由 from_raw 归一 | 不把缺失补 0；bad 与 missing 最终都 None，需留原因时最小增加 per-field validity/reason metadata |
| sensor validity | 数值范围/finite 校验、总 Quality | 不是硬件自检、校准或故障状态；硬件 status 需 Adapter 解释，尚无每传感器状态映射 |
| 历史/顺序 | 当前快照，无 history Store | 接收层处理 duplicate/out-of-order，记录 query 的来源时点；不靠 timestamp 猜 packet sequence |

from_raw 的 temp/ph/oxygen 名称只是一种现有 Mock 归一入口，**不是计算板协议**。它还会接受可转浮点的值（包括 Python boolean），不能充当严格硬件 parser。直接构造 dataclass 的 Quality 来自调用者，无法推回硬件可信度。必要的严格字段/类型/单位/设备 status 校验应先在 Adapter；待样例明确后决定最小 metadata 扩展，不整体重构 Domain。

## 7. 未来接收流程（未实现）

```text
Raw Hardware Packet（传输/字段待确认）
  → Telemetry / Sensor Adapter
    校验 schema/type/unit/time/device/status、记录接收时点
    去重/乱序策略、canonical 单位转换、无效值原因
  → Canonical WaterQualityReading
  → Current Snapshot Store / History Repository / Domain Service
  → Diagnosis / RAG / 未来只读 Tool / LLM
```

Raw packet 的受控保留策略、最大尺寸与敏感字段过滤在接收层定义；不要将任意 JSON 全量送 Prompt/Trace。传输可能是 HTTP/MQTT/WebSocket/Serial，尚未确认，本轮不选择网络框架或消息队列。

## 8. PROVISIONAL 数据包示例

**该结构不是实际计算板协议，真实格式待硬件/嵌入式团队提供样例后确认。仅讨论用途，不加入 resources/schema 或程序 parser。**

```json
{
  "schema_version": "discussion-only-0",
  "device_id": "example-board-A",
  "sequence": 42,
  "observed_at": "2026-10-03T08:00:00Z",
  "readings": {
    "temperature": {"value": 28.0, "unit": "degC", "status": "ok"},
    "ph": {"value": null, "unit": null, "status": "missing"},
    "dissolved_oxygen": {"value": 2.2, "unit": "mg/L", "status": "ok"}
  },
  "status": "partial"
}
```

此例没有定义正式 status 枚举、sequence 重置规则、认证或 checksum。received_at 应由实际接收服务可信时钟记录，不能把设备填写的字段当作服务接收时点。单包/批量模式与 schema_version 约定均等待样例。

## 9. 未来只读 Tool 概念接口（未实现）

| 概念接口 | 输入 | 输出 | 读取来源与边界 |
| --- | --- | --- | --- |
| get_current_water_quality() | 授权范围内 device/site 标识（单设备是否可省略待定），不接受 raw JSON 或阈值修改 | canonical WaterQualityReading + 已确认查询/来源 metadata；无数据给明确 NO_DATA，不造快照 | Current Snapshot Store / Domain Service，按查询时点 freshness 策略评估 |
| get_recent_water_quality(...) | 设备范围、aware 起止时间、受限条数；上限/排序待实际需求确认 | canonical readings[]、实际覆盖范围、缺口/分页标识；不编造未采样点 | 独立 history repository，当前不存在，不能假装已可读 |

若 Tool 返回确定性 findings，它们必须由同一 DiagnosisService 生成并携带 rule_version；固定 Advice 的必要诊断仍不能交模型自行决定。只读 allowlist、超时/取消、身份权限与审计要在执行层验收，Manual 返回工具请求也绝不自动执行。

不暴露原始 packet：隔离字段/协议变动、单位/错误约定、重复包及可信时间，保证每条事实来源可追溯，避免 Prompt 直接解释任意硬件字段。本轮只是边界建议，不实现工具 Schema、执行器或 Agent。

## 10. 向硬件 / 嵌入式团队确认

- 成功、缺失、错误、批量的实际 JSON/二进制样例；schema/version、字段名和字段类型。
- 温度、pH、DO 的单位、精度、原始/校准值、校准状态、sensor 范围与 error sentinel。
- timestamp 格式、时区/UTC、时钟同步、采样 vs 发包时间、离线缓存；接收端如何补可信 received_at。
- device ID 唯一性、site/channel/sensor ID；sequence 的作用域、重启回绕/重置和 packet ID。
- 采样/上传频率、批量上报、单包最大尺寸、缺值/坏值表达、status/checksum/错误代码。
- HTTP / MQTT / WebSocket / Serial 等实际传输、编码、认证、checksum 的验证责任与测试环境。
- 重发/乱序/重复包、离线重连、ack、丢包处理与 current/history 选择规则。
- 数据保留、权限/隐私、故障处理和现场可验证样例；谁批准阈值/校准规则。

## 11. 本轮交付与验证

只新增离线矩阵测试与本报告，不修改包内 Mock、运行程序、业务阈值、Knowledge JSON、UI 场景或 Preset。测试结果见[文档整理审计](../DOCUMENTATION_AUDIT.md#验证与范围)。本轮没有真实模型请求、传感器接入、生产修改或 commit/push。

[当前架构](../architecture/CURRENT_ARCHITECTURE.md) / [下一阶段](../ROADMAP.md) / [文档导航](../README.md)

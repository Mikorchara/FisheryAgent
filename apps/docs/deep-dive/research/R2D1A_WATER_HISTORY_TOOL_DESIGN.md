# R2D-1A：历史水质查询与分析 Tool 设计

状态：**研究方案，未实现、未注册、未授权、未进行真实模型验证。**

基线：2026-10-17，`d72420c`（R2C-2B）；审查开始时工作树干净。本轮只检查源码、测试及文档，没有打开真实监测 SQLite、凭据或运行数据。下文新增名称、参数、限额和 DTO 均是建议，不能当作现有 API。

## 1. 结论

**建议先实现一个简单、可靠的历史查询 Tool，再增加时间序列领域分析。** 第一版提供真实时间范围内的有效窗口统计、有限观测明细、覆盖与缺口说明；不发布“持续低氧”“已经恢复正常”等结论。

- 模型选择最近 **10 / 30 / 60 分钟**，可限定指标；设备由本轮服务器冻结，不接受模型指定。
- Monitoring 新增有界时间范围读取入口，复用现有存储与质量合同；不能用最近 N 条替代时间范围。
- 历史来源独立认证；查询成功不等于有可用数据，更不等于取得当前观测。
- 先做离线及单 Tool 资格，再研究“当前 + 历史”两 Tool；不改变现有 2/2/3 或 Qwen 两工具 Streaming 范围。

依据：[开发指南](../AI_BACKEND_DEVELOPMENT_GUIDE.md)、[集成合同](../../INTEGRATION.md)、[工程规则](../../../AGENTS.md)。开发指南 §2 的 `limit` 是通用参数校验示例，不足以成为本 Tool 的正式时间合同。

## 2. 当前 Monitoring 实际能力

### 2.1 查询与存储

| 当前入口 / 位置 | 实际行为 | 不能据此声称的能力 |
|---|---|---|
| [service.py](../../../monitoring/service.py) `MonitoringService.history(device_id, channel, limit=None)` | 校验设备和 water/visual；默认 `min(60, history_limit)`；limit 必须为真正的 int，范围 1..history_limit；返回按观测时间排列的最后 N 条 | 不接受 start/end、lookback、metrics；没有统计或连续异常分析 |
| [repository.py](../../../monitoring/repository.py) `history()` / `_history()` | 读取该设备、通道的全部留存行，再由 Service 切片；SQL 按 observed_at、received_at、batch_id 排序，LEFT JOIN batches 取得 session_id | 当前没有数据库时间范围过滤或查询行数上限参数 |
| 同文件 `capture()` / [service.py](../../../monitoring/service.py) `snapshot()` | 同一读事务捕获 current + history；网页趋势投影复用指标质量分类 | 不等于对每条历史重新诊断，也不等于网页与随后 Tool 查询原子同步 |
| [app.py](../../../management_web/app.py) `monitoring_history()` | GET `/api/monitoring/history?device=...&channel=water&limit=N`，转交上述 history | 没有按时间查询的 HTTP 合同 |
| [analysis.py](../../../monitoring/analysis.py) `DomainAnalysisService` | 当前通道的质量、新鲜度、连接状态和 Findings；水质阈值复用既有 DiagnosisService | 不提供历史统计、持续异常片段或趋势分类 |
| [events.py](../../../monitoring/events.py) `EventService` | HIT 持续更新；可靠 CLEAR 可恢复；证据不足或规则变化撤回确定性 | ACTIVE 不证明连续低氧；RESOLVED 不证明当前仍正常或所有指标正常 |

SQLite schema 版本为 1。关键数据：

- `history` 保存 batch_id、device_id、channel、observed_at、received_at、JSON payload；payload 是 `window + data`，水质 data 包含三指标的 mean/min/max/latest、单位、有效/无效样本数及总采样数。**没有逐样本值、各样本时间，也没有每个历史窗口的 Findings / Rule Identity 快照。**
- `batches` 保存 session_id、sequence、摘要及接收时间；history 的 session_id 来自关联查询，并非自身持久字段。批次表裁剪后，旧历史仍可能存在但 session_id 为 null；不能从 batch_id 猜回 Session。
- 默认每设备每通道留存 360 个历史窗口、每设备 1440 个批次记录、全局 300 个事件；可配置上限各不超过 10000。360 条仅在持续 10 秒周期下约等于一小时，**不是一小时保留保证**。
- 乱序窗口可进入历史，但不推进 current / Events；相同当前时间的新批次被拒绝，不过较旧的同时间不同批次仍可能留存。事件表有独立留存和状态推进机制，不能替代完整历史。
- 上报时间须带时区，`contracts.timestamp()` 解析为 UTC，`validate_batch()` 将 timestamp / window.start / window.end 归一化为 UTC ISO 字符串。observed_at = window.end；窗口为 `(start, end]`、1–60 秒，默认 10 秒。received_at 是服务器接收时间，不是观测时间。

### 2.2 网页趋势的真实处理

[services.js](../../../management_web/static/services.js) 的页面读数来自 `/api/monitoring`，趋势使用 snapshot.trend；范围选择主要是客户端筛选，不是调用时间范围 History API。

[app.js](../../../management_web/static/app.js) 提供 30 分钟 / 1 小时 / 全部选项；[view-model.js](../../../management_web/static/view-model.js) `chartGeometry()`：

1. 解析真实观测时间排序，以**最后一条观测**减去范围得到起点，不以服务器当前时间为终点。
2. 同一观测时刻选择最后接收的一行用于绘图；不平均重复值，也不改数据库。
3. 只画有限且质量 valid 的指标值；缺失、无效、已知 Session 变化和窗口时间缺口处断线。
4. Session 为 null 不会自动造成断线；这是一种旧数据可读的展示策略，不能用于认证连续观测。窗口衔接判断存在 10 毫秒绘图容差，也不是已批准的领域连续性标准。
5. 没有时间桶聚合或趋势推断；绘制的是服务器保存的窗口均值。时间轴按真实时间比例，最多五个刻度，统一北京时间显示。

因此可以复用时间、质量与展示组件的经验，**不能直接把图形去重、连线或“最近范围”当成可信历史分析算法**。

### 2.3 已有测试证据及边界

- [test_history_projection.py](../../../monitoring/tests/test_history_projection.py)：跨 Session / 设备与乱序排序；旧时刻不同批次均留存；批次裁剪后 Session 可缺失。
- [chart-ui.test.mjs](../../../management_web/tests/chart-ui.test.mjs)：真实时间坐标、同时间展示选择、Session / 缺口断线、缺失不补值、北京时间刻度。
- [test_rule_governance.py](../../../monitoring/tests/test_rule_governance.py)：部分/无效指标限制，缺失、STALE / OFFLINE 不证明恢复，规则身份变化不合并。
- [test_business_services.py](../../../monitoring/tests/test_business_services.py)：统一领域分析、事件事务回滚、重复/乱序不再次推进事件。

这些是现有测试的源码证据；本轮没有重跑测试。它们没有验证尚不存在的时间范围统计、持续时长或历史来源 Receipt。

## 3. 六类问题：现成能力与缺口

| 问题 | 当前已有基础 | 仍需新增 / 允许的结论 |
|---|---|---|
| 过去 30 分钟 DO 变化 | 留存窗口及 mean、质量、时间 | 按 query-time 的 30 分钟读取；首末有效窗口均值、差值与覆盖。差值不是单调趋势或恶化诊断 |
| 最近一小时最低 DO 及时间 | 每窗口 mean/min/max | v1 返回“最低有效窗口均值”及该窗口起止/观测时间。单样本 min 的确切发生时间未保存，不能声称精确到某秒 |
| 是否持续低氧 | 单窗口 Diagnosis、事件首末时间 | 缺连续性、时长和规则治理合同；不能用 ACTIVE 或首末时间之差回答 |
| 是否已恢复正常 | 当前有效窗口及 rule-specific CLEAR / RESOLVED | 只能说明某时点的某规则状态；持续恢复、当前仍正常需要新的有效证据和时间序列标准 |
| 哪些时间段缺数据 | 窗口起止、质量、部分 Session | 新增区间覆盖/缺口计算；留存中没有记录，不足以区分从未上报、离线或已裁剪 |
| 当前与过去一小时相比 | 当前 capture + 历史窗口 | 分开查询、保留两次时间/来源；历史 Tool 不认证当前。更强的同事务对比属于后续 Monitoring 用例 |

## 4. 推荐第一版 Tool 合同

### 4.1 参数与 Description

建议名称：`get_water_quality_history`。Description 草案：

> 只读查询本轮绑定设备最近 10、30 或 60 分钟内已留存的历史水质窗口，用于回顾温度、pH、溶解氧及数据缺口。返回有限有效窗口统计、观测明细和质量/覆盖限制；数值是窗口有效样本均值，不是连续原始采样。NO_DATA 表示查询完成但没有匹配窗口，PARTIAL 表示覆盖或数据可用性有限。历史记录及末次历史值不能证明当前系统状态、持续低氧或已经恢复；需要当前状态时使用当前水质查询工具。

```json
{
  "type": "object",
  "properties": {
    "lookback_minutes": {"type": "integer", "enum": [10, 30, 60]},
    "metrics": {
      "type": "array",
      "items": {"type": "string", "enum": ["temperature_c", "ph", "dissolved_oxygen_mg_l"]},
      "minItems": 1,
      "maxItems": 3,
      "uniqueItems": true
    }
  },
  "required": ["lookback_minutes"],
  "additionalProperties": false
}
```

不接受 device_id、Session、自由日期表达式、SQL、路径、limit、分页或动态预算。模型省略 metrics 时查三项；输出按固定指标顺序规范化。每次真实 Handler 开始时固定一个 UTC `evaluated_at`，查询范围为 `(evaluated_at - lookback, evaluated_at]`；查询不产生新采样。相同 Turn 的设备不能变化，两次真实查询也不能假装同时发生。

第一版只承诺近一小时的受限窗口；明确日期/任意起止时间留待确有需求后扩展，不将用户问的“三天”悄悄改成一小时。

服务端 Validator 示意（仅设计，不是实现）：

```python
def validate_history_arguments(arguments):
    metric_order = ("temperature_c", "ph", "dissolved_oxygen_mg_l")
    if (type(arguments) is not dict
            or "lookback_minutes" not in arguments
            or set(arguments) - {"lookback_minutes", "metrics"}):
        raise ValueError("invalid history arguments")
    minutes = arguments["lookback_minutes"]
    if type(minutes) is not int or minutes not in (10, 30, 60):
        raise ValueError("invalid history range")
    metrics = arguments.get("metrics", list(metric_order))
    if (type(metrics) is not list or not 1 <= len(metrics) <= 3
            or any(type(key) is not str or key not in metric_order for key in metrics)
            or len(set(metrics)) != len(metrics)):
        raise ValueError("invalid history metrics")
    return {"lookback_minutes": minutes,
            "metrics": [key for key in metric_order if key in metrics]}
```

JSON Schema 不替代 Validator；复用现有 ModelToolCall / Executor 的非法 JSON、编码、大小、深度与额外参数拒绝。不能接受 true、30.0、`"30"`、null、重复指标或未知字段，也不自动纠错。

### 4.2 Monitoring 读取与预算

建议新增 `MonitoringService.query_water_history(device_id, *, lookback_minutes, metrics)`，将读取和确定性投影放 Monitoring；Handler 只调用它并投影 DTO，不直接查 SQLite，不导入旧 Snapshot。

- Repository 增加**参数化、按设备 + water + 真实时间过滤**的只读入口；复用 `history_lookup` 索引和 UTC 规范化。一次短读事务捕获候选行、Session 关联及所需留存边界，不分别读出混合批次。
- 按窗口结束时间筛选候选，再验证窗口完整包含在请求区间内。跨起点的窗口标为边界排除，不能按比例切分窗口均值；无原始样本就无法精确计算那一小段。
- 建议最大 60 分钟、最多读取 721 行探测、最多处理 720 行；超出时安全报查询预算错误，不用“最近 720 条”伪装完成整个区间。复用短连接与锁；SQL 等待/处理也须受现有整 Turn Deadline 约束，不引入自动重试。
- 对全部符合条件的行先做质量/冲突处理并统计，再选择最多 12 条明细。可按 12 个等长时间桶各取末个实际窗口，明确这是**代表窗口抽选，不是桶均值或连续轨迹**。明细省略数单列，不影响统计范围。
- 最多展示 12 个缺口，保留总个数/总时长和 omitted_count；禁止省略后声称列全。完整 UTF-8 紧凑 JSON 建议不超过 24 KiB，低于当前 Executor 默认 32768 bytes；超过则安全失败，不能裁断 JSON。字段及每字符串也应有静态上限。
- 对内部损坏/不符合存储合同的行安全拒绝；与合法 payload 中的 invalid / partial 业务质量区分，不静默跳过存储错误。

这些是建议的维护者限额，不允许模型或 Web 指定。不调整默认存储、不回写/删改历史；现有 history API 和图表保持兼容。

### 4.3 统计、冲突与缺口

1. 复用 `water_metric_facts()` 的逐指标质量。主要数值统计仅使用完整 valid 指标；partial / invalid / missing 分开计数，有限明细中不可用均值为 null，不能填 0。有效样本数、总数和无效数保留，不能只看窗口总质量。
2. 首末值、差值、最低/最高均指**窗口均值**；每个极值保留真实窗口及 batch 引用。相同极值先后并存时给出次数与首末发生窗口，不编造唯一时刻。v1 不返回跨窗口总平均或回归斜率，避免将不同有效样本数/时长的均值直接平均。
3. 不同时刻、同设备的独立 Session 可以共同参与“已留存记录的极值”统计，但分段标识；不能连接成连续状态。Session 缺失时标为 unknown，不能认证跨越它的持续性。
4. 同时间不同批次或重叠窗口属于歧义组；v1 保留计数/引用，保守排除该组的主要数值统计和可靠覆盖，不能照搬图表的“最后接收者覆盖”成为事实规则。
5. 覆盖按窗口区间并集计算，不能简单用条数 × 10 秒；分别给 received-window coverage 与各指标 reliable-window coverage，不能混为有效样本覆盖。连续性在 Session 改变、unknown、缺口及不可靠窗口处中断。
6. 无留存窗口的区间标为 `NO_RETAINED_WINDOW`，有窗口但无可靠指标标为 `NO_RELIABLE_METRIC`；Session 边界另列。**缺口不等于离线，也不等于正常或持续异常。** 无裁剪水位证据时留存完整性为 UNKNOWN，不能声称全部缺口都是设备中断。

### 4.4 返回 DTO 示例

以下是**虚构**的简化单指标结果：请求 10 分钟，但仅有一个完整有效的 10 秒窗口。省略的是另外两项未请求指标，不是隐瞒窗口；生产 DTO 的字段集合须单独冻结并测试。

```json
{
  "projection_version": "management-water-history@1",
  "status": "PARTIAL",
  "device_id": "example-pond",
  "channel": "water",
  "source_kind": "simulator",
  "evaluated_at": "2026-10-17T08:10:00+00:00",
  "requested_range": {"start": "2026-10-17T08:00:00+00:00", "end": "2026-10-17T08:10:00+00:00", "interval": "(start,end]"},
  "aggregation": "window_mean",
  "query_completed": true,
  "retention_completeness": "UNKNOWN",
  "counts": {"matching_windows": 1, "boundary_excluded": 0, "ambiguous_windows": 0, "unknown_session_windows": 0},
  "coverage": {"received_window_s": 10, "requested_s": 600},
  "latest_observation_lag_s": 300,
  "metrics": {
    "dissolved_oxygen_mg_l": {
      "unit": "mg/L",
      "quality_counts": {"valid": 1, "partial": 0, "invalid": 0, "missing": 0},
      "valid_samples": 10, "sample_count": 10, "invalid_samples": 0,
      "reliable_window_s": 10,
      "first": {"window_mean": 2.2, "observed_at": "2026-10-17T08:05:00+00:00", "batch_id": "example-batch"},
      "last": {"window_mean": 2.2, "observed_at": "2026-10-17T08:05:00+00:00", "batch_id": "example-batch"},
      "last_minus_first": 0,
      "min_window_mean": {"value": 2.2, "batch_id": "example-batch", "occurrences": 1},
      "max_window_mean": {"value": 2.2, "batch_id": "example-batch", "occurrences": 1}
    }
  },
  "details": [{
    "batch_id": "example-batch", "session_id": "example-session",
    "window": {"start": "2026-10-17T08:04:50+00:00", "end": "2026-10-17T08:05:00+00:00", "duration_s": 10},
    "observed_at": "2026-10-17T08:05:00+00:00", "received_at": "2026-10-17T08:05:01+00:00",
    "metrics": {"dissolved_oxygen_mg_l": {"window_mean": 2.2, "quality": "valid", "valid_samples": 10, "sample_count": 10, "invalid_samples": 0}}
  }],
  "detail_selection": "last_actual_window_per_time_bucket",
  "details_omitted": 0,
  "gaps": {
    "count": 2, "total_s": 590, "omitted_count": 0,
    "items": [
      {"start": "2026-10-17T08:00:00+00:00", "end": "2026-10-17T08:04:50+00:00", "reason": "NO_RETAINED_WINDOW"},
      {"start": "2026-10-17T08:05:00+00:00", "end": "2026-10-17T08:10:00+00:00", "reason": "NO_RETAINED_WINDOW"}
    ]
  },
  "analysis": {"persistent_low_oxygen": "NOT_EVALUATED", "recovery": "NOT_EVALUATED"},
  "limitations": ["INCOMPLETE_TIME_COVERAGE", "RETENTION_COMPLETENESS_UNKNOWN", "NOT_CURRENT_OBSERVATION"]
}
```

极值引用应可解析到窗口元数据，**即使该窗口不在 12 条抽选明细内**：正式 DTO 应在极值对象内带有界起止时间/observed_at，而不是要求模型另查未返回的 batch；上例唯一 batch 可直接解析。完整 min/max/latest 原始统计如非问题所需，不重复逐窗口传递。

第一版不返回历史 Findings 或伪造历史规则版本。统计 DTO 保留 projection/统计版本；以后新增规则重评时须附实际 Rule Identity、PROTOTYPE、`reevaluated_at`，明确并非当时已持久保存的规则结论。

## 5. 质量、新鲜度与来源认证

### 5.1 维度分开

当前 [ToolStatus](../../../ai_backend/tools/contracts.py) 只有 OK / PARTIAL / NOT_SCORABLE / NO_DATA / NO_MATCH / ERROR，**没有 INVALID / STALE**。建议历史工具不扩通用枚举：

| 历史结果 | Tool status | operation completed | 有可用历史观测 | 能满足当前观测要求 |
|---|---|---|---|---|
| 合同有效、覆盖及所选指标可用，无声明限制 | OK | 是 | 是 | 否 |
| 稀疏、部分指标有效、Session 不明或存在歧义 | PARTIAL | 是 | 按实际可靠指标决定 | 否 |
| 有窗口但全为合法 invalid / missing / partial，无完整可靠指标 | PARTIAL | 是 | 否 | 否 |
| 范围内没有完整匹配窗口 | NO_DATA | 是 | 否 | 否 |
| 参数拒绝、未授权、存储错误、超预算或结果合同不合法 | ERROR / 安全拒绝 | 否 | 否 | 否 |
| 无真实 protocol 调用，只有历史/正文声明“查过” | 无 Receipt | 否 | 否 | 否 |

历史窗口年龄大于 30 秒是正常情况，不能全部按“当前 STALE”排除。保留历史质量和 `latest_observation_lag_s`，不向历史值授予 current freshness；目标区间末端缺数据照实表达。OFFLINE 只有独立的通道接触证据才能判断，不能从历史缺口直接生成；v1 不必返回当前连接判断。

### 5.2 Receipt 与 SourceRequirement 建议

在业务 [sources.py](../../../ai_service/runtime/sources.py) 内扩展同一合同，建议：

- `SourceRequirement.HISTORICAL_WATER_QUERY`：要求本轮合法完成历史读取；NO_DATA / 合法 PARTIAL 也满足，不要求必须得到正向数值。普通产品请求仍默认 AUTO，不从自然语言生成 Requirement。
- `TurnSource.HISTORICAL_WATER_OBSERVATIONS`：仅当结果通过历史 DTO 校验且至少存在一个可靠历史指标时授予；与查询完成标记分离。记录存在但全不可用时只认证操作，不授予此正向能力。
- Receipt 增加少量有界元数据：history_query_completed、范围、evaluated_at、返回窗口数/可靠窗口数、可用指标、合同版本。无数值数组、完整缺口、原始参数、Evidence 或第二份 payload。
- `ledger_from_execution()` 继续只消费本轮匹配 ModelExecutionStep / ToolExecutionStep 的真实结果；对 Tool 名、call id、status、payload 结构与时间关系校验。不能因 Handler 启动、正文、历史或浏览器声明而认证完成。
- `requirement_satisfied()` / `requirement_satisfied_by_ledger()` 增加独立分支；历史 Receipt 不能设置 observation_query_completed、CURRENT_TOOL_OBSERVATION、评分或 Knowledge 来源。即使最后一条历史非常新，也没有执行当前查询操作。
- 后续 Provider 失败、Stop 或 Gate 失败可保留执行审计，但仍不提交 successful_turn / completed History；History 只保存最终成功文本 pair，不保存 Tool Result / Receipt / Ledger。

不要把 DTO 内的 query_completed 自声明直接当成认证依据；必须连同真实执行和有界业务合同验证。也不要复用现有 `_observation()` 强塞历史末值到 `water_quality`。

## 6. 持续低氧与恢复：后续确定性分析要求

这些能力应放 Monitoring 纯计算层，复用 DiagnosisService 的阈值与 Rule Identity，不在 Handler、前端或 LLM 中复制规则。

**持续低氧**至少要求：同设备/指标、已知且一致的 Session、明确的规则版本、无歧义且衔接的窗口、每个窗口可靠有效、低氧条件逐窗成立。缺口、partial / invalid / missing、未知 Session、重叠或规则变化都截断片段，不能桥接。持续阈值、时间容差及适用范围须先治理批准，仍标 PROTOTYPE，不在本轮拍定生产阈值。

由均值只能断言“相邻有效窗口均值连续低于规则阈值”，不能证明窗口内每个样本都低或鱼群持续缺氧；若将来利用 sample max 加强证据，也只能说明实际有效采样，不能证明采样间状态。

**恢复**需明确恢复哪条规则/指标、哪个历史片段，以及后续完整有效的 CLEAR 证据。历史单次 CLEAR / RESOLVED 可说明当时条件解除，不能证明当前恢复；“持续恢复”还需另审时长、覆盖及可能的滞回标准。要回答“现在已经恢复吗”，必须获得本轮当前水质证据，过期/离线时只能待确认。

不能用 `DomainAnalysisService.evaluate(..., evaluated_at=现在)` 遍历旧行作为历史风险重评：它会因当前新鲜度门禁不作风险判断。也不能伪造 fresh/online 绕过该门禁；未来需独立、明确的历史重评入口。历史读取不能写 Events 或改既有状态。

## 7. 接入修改地图与权限边界

以下是**下一阶段**修改清单，本轮均未修改：

| 文件 / 区域 | 最小职责 |
|---|---|
| `apps/monitoring/repository.py` | 有界时间过滤、单事务捕获、Session / 留存边界；保留现有 history() |
| `apps/monitoring/service.py`、必要的 `contracts.py` | 统一历史用例与明确结果合同；设备、时间和读预算校验 |
| 拟新增 `apps/monitoring/history.py` | 纯区间/质量/基础统计与有限投影；无 LLM、Flask、数据库调用，无持续异常框架 |
| 拟新增 `business_tools/water_quality_history.py` | 名称、Description、Schema、Validator、Handler、Tool DTO 版本；复用 Monitoring，不另读旧数据 |
| [business_tools/registry.py](../../../ai_service/business_tools/registry.py) | 唯一显式装配；formal / per-Turn 定义一致；历史 Handler 绑定同一冻结 device，保持现有两工具相对顺序和共享 KnowledgeService |
| [runtime/policy.py](../../../ai_service/runtime/policy.py)、内置 tool_policies 资源 | 接受已知新名称，但默认不授权；不得写用户 Policy；评分仍只是兼容名称，没有 Handler |
| [runtime/sources.py](../../../ai_service/runtime/sources.py) | 历史操作与正向能力、Receipt/Ledger/Gate 的独立分支 |
| [runtime/catalog.py](../../../ai_service/runtime/catalog.py)、[activity.py](../../../ai_service/runtime/activity.py) | 标识“历史”，有限范围/状态/计数；不显示原始参数、窗口 JSON 或实时标识 |
| [service.py](../../../ai_service/service.py) | formal / per-Turn 绑定、固定 Trace tool_names allowlist、确认配置；不新增执行循环 |
| [execution.py](../../../ai_service/execution.py)、[streaming.py](../../../ai_service/streaming.py)、对应 resources JSON | 独立候选组合和数据绑定版本；没有批准时不改现有范围，也不放宽 matcher |
| Monitoring / AI service / Web 相关 tests；现有 qualification 入口 | 先离线验证、再单案例明确授权；不用旧实验授权 |

当前 Policy 配置与旧 Prototype 共用，授权主要通过旧 Tool Manager；它不会自动认识管理端新增名称。下一阶段需明确**管理端 opt-in 的受控配置入口及共享文件兼容策略**，不能直接让新名称写入后使旧 Prototype 解析失败；首轮可采用隔离的测试 Policy，不触碰真实用户文件。

目前 execution.data_bindings 的键集合是固定合同；新增 history 绑定需另审版本化扩展，不能随意加键或省略验证。revision 还包含全部已装配 definitions，所以即使新 Tool 未授权，也可能使旧确认失效；应重启/新 epoch、重新 bootstrap 与确认，不能为了维持旧 hash 删除安全绑定。

已有水质/Knowledge Definition 必须逐字保持；新增定义、有效 Tool 集合或绑定语义变化不继承旧 Scope/资格。正式部署前应做旧两工具计划指纹差分：若绑定合同升级使其不再匹配，需保留明确的旧版本路径或重新审核批准，不能静默沿用失效资格。

## 8. 第三个 Tool 与当前预算

| 目标路径 | 最多实际调用 | 现有预算是否容纳 |
|---|---|---|
| History → Final | 1 Tool / 1 round / 2 requests | 是，适合作为首个隔离资格案例 |
| Current → History → Final，或相反 | 2 / 2 / 3 | 是；模型看到前一结果再决定第二个，来源和时间各自保留 |
| History → Knowledge → Final | 2 / 2 / 3 | 数量可容纳，但属于另一个未验证组合 |
| Current + History + Knowledge 都需要真实获取 | 3 / 3 / 4 | 否；三项同时授权也不能增加调用上限 |

**推荐初始范围：Qwen OFF / Normal、仅 History、1/1/2、固定设备、隔离 Policy、candidate。** 注册/离线测试不等于正式 Web 暴露；先在业务测试/资格装配中使用，用户现有两工具继续工作。真实实验需下一轮逐案例授权，失败不补跑。

单工具验证后，再另审 Current + History 的 Normal 2/2/3。现有 Qwen Streaming 仅 Current + Knowledge、512 tokens/request、retry=0、120 秒、本地实验且默认关闭；不得以此自动批准历史工具、三工具组合或其他模型。`streaming.py` 还有精确两工具限制，只改 JSON 无法合法启用新组合。

不增加预算来掩盖首次设计问题。只有确认业务确需三次独立来源操作、两次无法完成，并已有安全/成本/取消/发布测试及明确批准时，才研究预算升级。本轮不改 Prompt、预算或发布配置。

## 9. 离线测试矩阵与验收标准

| 层次 | 必测内容 / 通过条件 |
|---|---|
| 时间范围 | 冻结 UTC；10/30/60 分钟真实时间；边界包含规则、跨日/时区、迟到/乱序、窗口跨界；不能先取 N 再过滤 |
| 质量与数值 | valid / partial / invalid / missing、单指标可用、全无效、零值、非有限值；首末/极值/差值、样本数精确；均值极值不冒充瞬时极值 |
| 区间与留存 | 变长窗口、重复时刻、重叠、跨 Session、Session 被裁剪、缺口、留存不足；覆盖按并集不重复累加；unknown 不变成连续或 offline |
| 读取预算 | 720 与 721 边界、12 条代表明细、12 个缺口与总数、24 KiB；统计先于抽选；超限安全失败、不悄悄缩短范围 |
| 参数/权限 | `{}`、bool、float、字符串数值、null、额外字段、重复/未知指标、编码/深度异常拒绝；未授权 Handler 不执行 |
| Registry / 数据一致性 | formal / per-Turn 定义 hash 一致；设备冻结；无 current / Events 写入；同一读捕获不混合批次；旧两工具 DTO 和评分不可执行不变 |
| 来源 | OK / PARTIAL / NO_DATA 的完成与能力分离；全无效无正向能力；ERROR / 假 Tool 文本无认证；历史永不满足当前/评分/Knowledge Requirement |
| Runtime / Web | Fake Provider 直答、History → Final、后续候选 Current → History；1/1/2 与 2/2/3 不超限；Result 正确传递；Stop/Timeout/Trace 失败不提交成功 History |
| Scope / 安全 | opt-in 默认关闭，新增定义使旧确认失效；旧两工具精确范围回归；不泄露 SQL、路径、原始记录或参数；SSE/Activity 不混入历史 payload |

实施时先跑受影响 Monitoring、AI service/source 与 Web targeted；涉及范围装配时加配置/资格离线回归。真实质量评价与 Provider 行为证据单列，Mock 不能替代。当前研究未运行 Python / Browser 测试，也未进行真实资格请求。

## 10. 分阶段建议与待审核事项

1. **R2D-1B：基础历史读取与纯统计。** 新有界 Monitoring 用例、质量/覆盖/缺口、有限 DTO 和精确临时 SQLite 测试；无新规则阈值、无持续异常判断、不迁移旧数据。
2. **R2D-1C：历史 Tool 离线接入。** 一个 Tool 模块、统一注册、独立来源合同、默认关闭、隔离资格装配；先解决共享 Policy opt-in 兼容问题。Scope/数据绑定另审，保持现有实验不扩大。
3. **单案例真实资格与小范围试用。** 待用户批准后先 History → Final，再 Current + History；人工检查来源和时间表述，不能仅凭技术成功发布。Streaming 在 Normal 通过后单独批准。
4. **后续历史领域分析。** 根据实际问题补历史规则重评、连续片段、恢复证据与治理标准；不由 LLM 自行猜测，不默认升级预算。

下一阶段最小可实施范围是第 1 步；如果希望一次完成 Tool，至少应把第 1、2 步作为两个可独立验收的边界。

待人工决定：10/30/60 分钟与上述限额是否适用；是否需要超过当前约一小时的留存；管理端独立授权入口；持续/恢复标准及养殖适用性。长期建议在 history 自身持久保存 Session / 统计版本并记录裁剪水位，但这需要单独的兼容迁移，**不是 v1 可靠读取的强制前提**：旧数据可保持 UNKNOWN 并拒绝连续性结论。

本轮仅新增本报告。未修改产品、测试、Prompt、Schema、Policy、发布范围、数据库或旧 Prototype；未调用 Provider / NPU；未 commit / push。

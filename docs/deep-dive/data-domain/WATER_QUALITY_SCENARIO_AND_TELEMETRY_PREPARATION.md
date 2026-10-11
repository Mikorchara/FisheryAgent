# 水质数据、Scenario 与 Telemetry

本文描述当前水质数据链。`WaterQualityReading` 是 Scenario 模拟与未来真实传感器接入之间的 canonical Domain 合同；从该合同往上，Diagnosis、RAG 与模型应用不依赖数据来自 Simulator 还是 Hardware。

## 输入到当前快照

```text
Builtin / User / 临时 ScenarioTemplate
→ TelemetrySimulator
→ SimulationPacket (sim-v1)
→ SimulationAdapter
→ WaterQualityReading
→ CurrentSnapshotStore
```

- `telemetry/scenario_templates.py` 管理模板并由 `apply_scenario_template()` 统一执行生成与写入。
- `telemetry/models.py` 定义模拟专用 `SimulationRecipe` / `SimulationPacket`；`simulator.py` 仅合成 baseline 与明确覆盖，不包含业务诊断阈值。
- `adapter.py` 校验 `sim-v1`，将缺失、无效和数值转换为 `WaterQualityReading`。`sim-v1` 不是硬件协议。
- `snapshot.py` 在内存保存最后一次明确写入的 immutable reading。未 Apply 时为 `None`；Web 重启后为空。选择模板本身不改变当前快照。
- `current.py::CurrentWaterQualityReader.query()` 捕获一次 Reading，并根据查询时钟重算 freshness；不修改 Store 中原值，不生成 normal fallback。

Web 组合创建一个共享 `CurrentSnapshotStore` / Reader；Apply、Normal / Streaming Analysis 和只读水质 Tool 均从此状态读取。分析请求在开始时捕获自己的不可变 reading；期间再次 Apply 不会改写该请求的 Facts。

## 水质合同与诊断

`contracts.py` 保存 `WaterQualityReading`、`Quality`、`Freshness` 与规则结果合同。质量有效性和新鲜度是两个独立维度，可同时表示 PARTIAL + STALE。没有水质快照是 `NO_DATA`；已存在的 MISSING/PARTIAL、INVALID、STALE 或数值异常仍是有状态的数据，不等于没有数据。

`domain.py::DiagnosisService` 是温度、pH、DO 阈值的唯一实现。当前阈值版本为 `fishery-production-c400b7a-v1`：

| 指标 | 当前规则 |
| --- | --- |
| 温度 | <15℃ critical low；15–<20℃ warning low；20–30℃无 finding；>30–33℃ warning high；>33℃ critical high |
| pH | <6.5 critical low；6.5–<7 warning low；7–8.5 无 finding；>8.5–9 warning high；>9 critical high |
| DO | <1 mg/L extreme critical；1–<3 mg/L critical low；3–<5 mg/L warning low；≥5 mg/L 无低氧 finding |

无 finding 仅表示这些程序规则未触发，不是专业诊断。`water_quality_scoring.py` 实现独立实验评分：温度与 pH 使用上述正常区间，DO 使用 ≥5 mg/L；偏离距离按温度 10、pH 40、DO 20 的 penalty rate 扣分，分项限制在 0–100，现有指标的未舍入分项求平均后保留一位小数。等级为 GOOD / ACCEPTABLE / WARNING / CRITICAL，版本为 `experimental-water-quality-score-v1`。PARTIAL 只平均已有指标并报告缺失项；INVALID 返回 NOT_SCORABLE；STALE 给 warning 但不额外扣分。该评分仅为 EXPERIMENTAL / NOT PROFESSIONAL STANDARD，不修改阈值、不替代 Diagnosis Findings。

## Analysis、Assistant 与知识数据

- 固定 Analysis 捕获水质、运行 Diagnosis、再向 `KnowledgeService` 查询背景 Evidence，然后构建模型上下文。
- Assistant 不自动读取 Snapshot、Diagnosis 或 RAG。当前观测来自本轮真实只读 Tool 执行；查询 Tool 返回 canonical Reading，评分 Tool 也可带回它实际使用的 Reading。旧历史与 Knowledge Evidence 不能替代当前观测。
- 当前知识服务在 `knowledge.py`，使用包内 `resources/knowledge/eel_knowledge.json`；`resources/knowledge/SOURCE.md` 记录数据来源缺口。知识条目是背景依据，不是现场观测或疾病证据。
- RAG 是当前 TF-IDF baseline；Knowledge Tool 已注册，在共享 KnowledgeService 注入后可执行，默认关闭，已有受控真实资格记录；检索相关性和长期选择可靠性仍待评估。接口与背景证据边界见[只读 Tool 当前实现](../tools/READ_ONLY_TOOL_CALLING.md)；检索不产生当前现场观测。
- Detection Mock 是 `resources/scenarios/detection/` 中的静态事件 fixture。当前没有 Detection Simulator、硬件解析器或正式 Detection Tool。

## 边界与限制

- Scenario / SimulationPacket 只存在于输入与适配前半段；Diagnosis、RAG、AnalysisResult 和 Tool 面向 canonical domain facts。
- Tool 通过共享 Reader 查询状态；不得读取模板文件、模拟包或前端 Scenario，也不得 Apply、改 Store 或回退到 normal。
- 当前 Snapshot 是进程内数据，不是持久化历史；多 Web worker 不共享独立进程内 Store。未来生产传感器集成须明确共享数据源、时间戳、单位、校准、丢失/乱序语义，再提供专用 Adapter。
- stale 阈值由应用组合配置并传入 Reader；Tool 不复制阈值、不让模型判断 freshness。

## 主要代码与测试

- 合同与规则：`src/fishery_ai/contracts.py`、`src/fishery_ai/domain.py`。
- Telemetry：`src/fishery_ai/telemetry/{models,simulator,adapter,snapshot,current,scenario_templates}.py`。
- 知识：`src/fishery_ai/knowledge.py` 与 `src/fishery_ai/resources/knowledge/`。
- 回归：`tests/test_water_quality_matrix.py`、`test_telemetry_simulator.py`、`test_scenario_templates.py`、`test_current_water_quality.py`、`test_water_quality_scoring.py`、`test_v01.py`。

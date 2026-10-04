# 水质情景模板与 Telemetry

当前统一数据流：

```text
Scenario Template → TelemetrySimulator → SimulationPacket（sim-v1）
  → SimulationAdapter → WaterQualityReading → CurrentSnapshotStore
  → DiagnosisService → 现有分析流程
```

WaterQualityReading 仍是 canonical Domain 合同。两种 schema 都只用于模拟，不是计算板协议；Domain 不依赖 Telemetry。

## 资源与来源

```text
src/fishery_ai/resources/scenarios/
├─ water_quality/
│  ├─ normal.json
│  ├─ low_oxygen.json
│  ├─ partial.json
│  ├─ stale.json
│  └─ partial_stale.json
└─ detection/
   ├─ normal.json
   └─ count_jump.json
```

内置水质模板为 BUILTIN，只读，可应用、查看、Save As。USER 模板保存在 Git ignored 的 outputs/scenario_templates/water_quality/，可创建、编辑、另存、删除、重启后加载；临时“仅应用”不写文件。

Detection 只拆分资源，保留原事件 ID、时间、source、model、confidence、bbox、track_id。没有 Detection Simulator / CRUD / 新规则，不自动绑定水质。

## Scenario Template v1

```json
{
  "schema_version": "scenario-template-v1",
  "id": "hot_low_oxygen",
  "display_name": "高温低氧",
  "device_id": "sim-device-001",
  "observed_age_s": 0,
  "water_quality": {
    "temperature_c": {"state": "NORMAL", "value": 34},
    "ph": {"state": "NORMAL", "value": 7.5},
    "dissolved_oxygen_mg_l": {"state": "NORMAL", "value": 2.2}
  }
}
```

可选 description；device_id 留空使用 sim-device-001。state 只允许 NORMAL / MISSING / INVALID。NORMAL 必须有有限数值；MISSING / INVALID 不保存 value。模板描述输入意图，不直接创建 reading。温度 °C、DO mg/L。

ID 为小写字母开头，允许数字、下划线、连字符，最长 64 字符；拒绝目录跳转、绝对路径、Windows 保留文件名。Web 新建 / 另存由后端生成 user-<uuid>，不接受任意文件路径。Store 保留 BUILTIN / USER 来源，禁止覆盖内置 ID；用户写入使用同目录 staging、原子发布 / 替换，重复 ID 不覆盖原文件，拒绝 symlink / reparse / hardlink。它是本地模板 Store，不提供跨进程编辑 revision。

## 时间与内置模板

Apply 使用当前 UTC retrieved_at，observed_at = retrieved_at - observed_age_s。Template 不存水质固定时间戳或 freshness；现有 canonical 合同按 stale_after_s 计算。默认 300 秒，可在 composition / create_app 配置；300 秒 fresh、301 秒 stale。测试注入固定 clock。

| 模板 | 温度 °C | pH | DO mg/L | 年龄秒 | Quality / Freshness | 程序 Findings |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| normal | 28 | 7.5 | 6.4 | 0 | valid / fresh | 无 |
| low_oxygen | 28 | 7.5 | 2.2 | 0 | valid / fresh | OXYGEN_CRITICAL_LOW |
| partial | 28 | Missing | 6.4 | 0 | partial / fresh | SENSOR_PARTIAL |
| stale | 28 | 7.5 | 6.4 | 301 | valid / stale | SENSOR_STALE |
| partial_stale | 28 | Missing | 6.4 | 301 | partial / stale | SENSOR_PARTIAL + SENSOR_STALE |

五场景的数值、质量、新鲜度和诊断语义保持一致；时间改为每次 Apply 生成，来源为 simulation:<device_id>。全部缺失仍按现有领域合同标记 INVALID。

## Telemetry 职责

- models.py：SimulationRecipe / sim-v1 Packet；readings 只读，数值、null、invalid 故障标记。
- simulator.py：baseline 28 / 7.5 / 6.4，加 set_temperature / set_ph / set_do / missing / invalid；后写覆盖，显式时间，sequence 从 1 递增，仅辨认模拟输出。
- adapter.py：版本、字段、类型、时间与来源校验；复用 WaterQualityReading.from_raw 归一，不判断养殖异常。
- snapshot.py：进程内最后一次明确写入的 immutable reading；初始 None。
- scenario_templates.py：模板合同、来源与 CRUD、统一 apply_scenario_template。

Simulator 没有业务阈值，Adapter 不调用模型、RAG 或 Tool。底层 sim-v1 非数字（含 bool / 数字字符串）为 invalid，不转换成有效观测。

## Web 与 Orchestrator

下拉顶部“+ 自定义情景...”，下方分组“内置模板 / 我的模板”。Modal 提供名称、三项 State / Value、Observed Age、Device ID；Missing / Invalid 禁用 Value。取消丢弃草稿；仅应用只更新内存；保存模板并应用先保存，再生成快照。内置查看只读，Save As 新建用户模板；User 可编辑、保存、另存、删除。

Apply 不调用模型或硬件。页面显示 canonical 数值、Quality、Freshness、两个时间戳、source 和程序 Findings，前端不计算诊断。新增写入 / Apply API 复用本地 Host / Origin / CSRF 门禁。

已 Apply 的情景由 Analyze 读取当前 Store；选择已保存模板但尚未 Apply 时，分析 API 的兼容 scenario 参数也通过同一 Telemetry 管线应用后分析。CLI / Demo 的 MockRepository 同样使用模板转换，不保留旧混合资源路径。

Normal / Streaming 都向 Orchestrator 注入请求开始时捕获的 reading；后续 Apply 不改变进行中的请求。RAG、Grounding、模型、Preset、Credential 未修改。

每个 Web app 共享一个 CurrentSnapshotStore，跨请求保留，重启为空。没有快照且未指定模板时返回 NO_DATA，不自动制造 normal。删除模板不删除已应用快照；Store 不自动刷新保存的 Freshness，不提供跨进程共享、History 或数据库。多个标签页共享当前状态，各分析持有自己的 reading。

## 未来 Tool 与硬件

未来 get_current_water_quality() 只读 CurrentSnapshotStore，空状态返回 NO_DATA；不得直接读 Template、SimulationPacket 或原始资源。本轮没有 Tool Calling / Agent。

```text
未来 Hardware Receiver → Hardware Adapter → WaterQualityReading
  → 同一个 CurrentSnapshotStore → 未来只读 Tool Boundary
```

硬件团队需提供成功 / 缺失 / 错误 packet、单位、校准、时钟、设备 ID、采样频率与乱序规则；拿到样例后才实施真实 parser / receiver。sim-v1 不作为硬件协议。

## 确定性阈值

仍在 src/fishery_ai/domain.py，tests/test_water_quality_matrix.py 覆盖边界，本轮未修改。

| 指标 | 当前规则 |
| --- | --- |
| 温度 | <15 critical low；15–<20 warning low；20–30 无 Finding；>30–33 warning high；>33 critical high |
| pH | <6.5 critical low；6.5–<7 warning low；7–8.5 无 Finding；>8.5–9 warning high；>9 critical high |
| DO | <1 extreme critical；1–<3 critical low；3–<5 warning low；≥5 无低氧 Finding |

无 Finding 不等同专业诊断。Quality / Freshness 为独立维度。

## 离线验证

2026-10-04：Scenario / Web 专项 19 项、Telemetry 专项 18 项、现有水质矩阵 9 项、输出 parity 4 项、Scenario Browser 专项 7 项通过；完整 Python 408 项、完整 Browser 113 项通过，app.js 语法检查通过。

使用临时文件、固定时间、虚构设备，阻断外部网络。覆盖五模板、来源与只读保护、User CRUD / 重载、路径安全、状态和时间边界、完整转换、共享 Snapshot、临时 Apply、Streaming 捕获 reading、Detection 和 Browser Modal。没有真实模型或硬件请求。

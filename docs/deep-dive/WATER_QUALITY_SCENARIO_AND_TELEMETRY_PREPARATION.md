# 水质数据与 telemetry 准备

本文只记录当前原型事实及接入传感器前的必要问题。生产 Fishery_Project 保持只读，本文不定义硬件协议。

## 当前 Mock 水质场景

包内文件：src/fishery_ai/resources/mock/scenarios.json。时间戳是固定 UTC fixture，不是实时数据。

| 场景 | 温度 °C | pH | 溶氧 mg/L | Quality / Freshness | 当前规则结果 |
| --- | ---: | ---: | ---: | --- | --- |
| normal | 28 | 7.5 | 6.4 | valid / fresh | 无 Finding |
| low_oxygen | 28 | 7.5 | 2.2 | valid / fresh | OXYGEN_CRITICAL_LOW |
| partial | 28 | 缺失 | 6.4 | partial / fresh | SENSOR_PARTIAL |
| stale | 28 | 7.5 | 6.4 | valid / stale | SENSOR_STALE |
| partial_stale | 28 | 缺失 | 6.4 | partial / stale | 两项 Quality / Freshness Finding |

同一资源含独立 Detection Mock：normal 与 count_jump。水质流程不会自动把检测数量变化并入诊断；没有 YOLO 或数量变化诊断规则。

## 动态 Telemetry Simulator

新增 src/fishery_ai/telemetry/，只使用标准库。固定 Mock 是回归样本；Simulator 是可组合的模拟数据源，两者独立。scenarios.json 的五个场景、现有 Web 和 Demo 均保留；未增加模拟器 Web 面板。

```text
SimulationRecipe（baseline） + 按顺序覆盖数值 / 故障
  → TelemetrySimulator → SimulationPacket（sim-v1）
  → SimulationAdapter → 既有 WaterQualityReading
  → CurrentSnapshotStore
```

文件职责：models.py 定义模拟合同；simulator.py 生成数值与事件；adapter.py 校验协议并归一到领域合同；snapshot.py 保存当前快照；__init__.py 只导出这五个公共类。

### Simulation Packet v1

sim-v1 是内部模拟协议，**不是计算板协议**。Packet 为不可变数据类，readings 会复制为只读映射；合法模拟值为数字、null 或字符串标记 `invalid`。没有实现 HTTP/MQTT 接收或硬件 JSON parser。

| 字段 | 表达 / 约束 |
| --- | --- |
| schema_version | 固定 sim-v1；Adapter 拒绝其他版本 |
| device_id | 非空模拟设备 ID；canonical source 为 simulation:&lt;device_id&gt; |
| sequence | 非负整数；Simulator 每次 generate 从 1 递增，仅用于辨认模拟输出，不进入业务诊断或排序 |
| observed_at | 带时区的 datetime；序列化说明对应 ISO 8601；调用方显式提供，旧时间可模拟 stale |
| readings.temperature_c | 温度 °C；JSON 数字 / null / invalid |
| readings.ph | pH；JSON 数字 / null / invalid |
| readings.dissolved_oxygen_mg_l | DO mg/L；JSON 数字 / null / invalid |

读数键缺失或 null 表示 missing。其他非数字值（包括 bool、数字字符串、空字符串）均视为 invalid，不将其转换成有效数值。非有限数和超出 canonical 物理范围的值也归为 invalid。未知读数键拒绝，避免拼写错误被忽略。无效字段变为 None，其余有效读数保留；全部缺失时沿用领域合同的 Quality.INVALID。

### 最小用法

```python
from datetime import datetime, timedelta, timezone
from fishery_ai.domain import DiagnosisService
from fishery_ai.telemetry import (
    CurrentSnapshotStore, SimulationAdapter, TelemetrySimulator,
)

now = datetime(2026, 10, 4, tzinfo=timezone.utc)
simulator = TelemetrySimulator(device_id="sim-tank-01")
simulator.set_temperature(34).set_do(2.2)
packet = simulator.generate(observed_at=now)
reading = SimulationAdapter(stale_after_s=300).to_reading(packet, retrieved_at=now)
store = CurrentSnapshotStore()
store.set_current(reading)
findings = DiagnosisService().diagnose(store.get_current())
# TEMP_CRITICAL_HIGH + OXYGEN_CRITICAL_LOW，由 Domain 判断

simulator.missing("ph")  # 或 invalid("ph")
old_packet = simulator.generate(observed_at=now - timedelta(seconds=301))
partial_stale = SimulationAdapter(stale_after_s=300).to_reading(
    old_packet, retrieved_at=now,
)
```

默认 baseline 为 28 / 7.5 / 6.4；可用 SimulationRecipe 替换。set_temperature / set_ph / set_do、missing(field)、invalid(field) 按调用顺序覆盖，后写值生效；已经发出的 Packet 不被后续覆盖改变。field 使用表中的 canonical 字段名。旧 observed_at 和可配置 stale_after_s 共同决定 Freshness，超过阈值才 stale；Quality 与 Freshness 仍独立。

Simulator 不判断异常、不包含养殖阈值。SimulationAdapter 只做版本、字段类型、时间和来源校验，并复用 WaterQualityReading.from_raw 的物理范围 / Quality / Freshness 归一；不调用 Diagnosis、模型或 RAG。

### Current Snapshot Store 与未来 Tool

CurrentSnapshotStore 只保存最后一次 set_current(reading) 的 immutable WaterQualityReading。未写入返回 None，不自动生成 normal，不判断时间顺序，不自动刷新 retrieved_at / Freshness。服务调用方持有并共享同一 Store 实例；重启即空，不是跨进程存储，也没有 History / retention / receiver / 后台线程。

本轮只提供模块和测试，不把新 Store 接入现有 Orchestrator。下一阶段的只读 get_current_water_quality() 应读取 Store，空状态明确返回 NO_DATA；不得直接读 Packet、固定 Mock 或硬件 JSON。未来真机接入只增加 Hardware Receiver / Hardware Adapter，再写入相同 canonical Store，Tool 的数据边界不需要改变。

## 确定性阈值

实现位置：src/fishery_ai/domain.py。边界由代码与 tests/test_water_quality_matrix.py 覆盖。

| 指标 | 当前程序规则 |
| --- | --- |
| 温度 | <15 critical low；15–<20 warning low；20–30 无 Finding；>30–33 warning high；>33 critical high |
| pH | <6.5 critical low；6.5–<7 warning low；7–8.5 无 Finding；>8.5–9 warning high；>9 critical high |
| DO | <1 extreme critical；1–<3 critical low；3–<5 warning low；≥5 无低氧 Finding |

“无 Finding”不等同养殖最适或专业诊断。Quality INVALID / PARTIAL 与 Freshness STALE 是不同维度；过期可与缺失、数值异常并存。

## 接入真实传感器前需确认

当前 WaterQualityReading 仍是 canonical 水质领域合同；Hardware Adapter 应负责字段、单位、范围、时间、设备状态和来源校验。获得实际设备样例前，不实现硬件 parser 或选择 HTTP/MQTT 等传输。

需要硬件团队提供：成功/缺失/错误 packet 样例；单位、精度和校准状态；设备时间与服务接收时间；设备/传感器 ID；采样频率、乱序/重发规则；认证、最大 packet 尺寸与数据保留要求。

    实际 Packet → Hardware Adapter 校验与归一 → WaterQualityReading
                 → CurrentSnapshotStore → Diagnosis / 未来只读 Tool

不把原始 packet 直接交给模型或写进 Trace。历史查询要等真实历史数据源存在之后再定义。

## 离线验证

2026-10-04 验证：telemetry 专项 `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_telemetry_simulator.py' -v`，18 项通过；现有水质矩阵 `-p 'test_water_quality_matrix.py' -v`，9 项通过；完整 `.venv/Scripts/python.exe -m unittest discover -s tests`，389 项通过。

测试固定时间、虚构设备和模拟读数，阻断 socket 网络；覆盖组合异常、partial / invalid / stale、协议校验、快照空状态与最后写入、旧 Mock 兼容性。未修改 Web，因此按本轮范围没有运行 Browser / JS 检查；没有真实模型请求。

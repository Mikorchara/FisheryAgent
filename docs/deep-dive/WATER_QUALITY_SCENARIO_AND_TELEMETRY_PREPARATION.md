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

## 确定性阈值

实现位置：src/fishery_ai/domain.py。边界由代码与 tests/test_water_quality_matrix.py 覆盖。

| 指标 | 当前程序规则 |
| --- | --- |
| 温度 | <15 critical low；15–<20 warning low；20–30 无 Finding；>30–33 warning high；>33 critical high |
| pH | <6.5 critical low；6.5–<7 warning low；7–8.5 无 Finding；>8.5–9 warning high；>9 critical high |
| DO | <1 extreme critical；1–<3 critical low；3–<5 warning low；≥5 无低氧 Finding |

“无 Finding”不等同养殖最适或专业诊断。Quality INVALID / PARTIAL 与 Freshness STALE 是不同维度；过期可与缺失、数值异常并存。

## 接入真实传感器前需确认

当前 WaterQualityReading 是唯一水质领域合同；Adapter 应负责字段、单位、范围、时间、设备状态和来源校验。获得实际设备样例前，不实现 parser 或选择 HTTP/MQTT 等传输。

需要硬件团队提供：成功/缺失/错误 packet 样例；单位、精度和校准状态；设备时间与服务接收时间；设备/传感器 ID；采样频率、乱序/重发规则；认证、最大 packet 尺寸与数据保留要求。

    实际 Packet → Sensor Adapter 校验与归一 → WaterQualityReading
                 → Snapshot / History 存储 → Diagnosis / 只读 Tool

不把原始 packet 直接交给模型或写进 Trace。历史查询要等真实历史数据源存在之后再定义。

# 路线图

本路线只说明当前边界与下一步，不自动授权实现。

## 当前可用

- 确定性水质合同、规则诊断、固定 Mock 水质与 Detection 数据。
- telemetry/ 动态模拟入口：Simulator → SimulationAdapter → WaterQualityReading → CurrentSnapshotStore。sim-v1 仅用于模拟；快照只在进程内保存，空 Store 返回 None。
- TF-IDF 知识检索、Evidence Grounding、Normal / Application Streaming。
- Preset、Managed Custom、Manual Expert V1/V2 三条模型接入路径。
- R2 用户私有凭据、R3 ProtocolSpec、R4 Capability Evidence Resolver、R5 显式单项 Probe。
- Usage、JSONL Trace、请求取消及离线 Python / Browser 测试。

## 下一阶段：只读 Tool Calling

先定义少量只读工具及参数/返回合同，例如 get_current_water_quality() 从 telemetry/ 的 CurrentSnapshotStore 读取 canonical 水质快照；没有快照时明确返回 NO_DATA。工具不能直接读取 SimulationPacket、scenarios.json 或硬件原始 JSON，也不能改变诊断规则或写入数据库。缺少传感器历史存储时，不提供伪造的“历史查询”。

实现前需要明确只读 allowlist、授权数据范围、审计、超时和取消边界。Manual 返回的 tool_calls 继续只展示、不执行。

## 暂缓

- Agent Loop：只读工具边界验收后再单独决策；不得直接操作设备、数据库或阈值。
- 生产项目 / 真实传感器 Adapter：等待硬件协议样例、单位、时钟和设备状态定义。未来 Hardware Receiver → Hardware Adapter → WaterQualityReading → 同一个 CurrentSnapshotStore；不把 sim-v1 当成计算板协议。
- RAG 评估继续使用离线对照；没有证据前不增加向量数据库或大型框架。
- Fine-tuning 等待明确任务定义和额外数据。

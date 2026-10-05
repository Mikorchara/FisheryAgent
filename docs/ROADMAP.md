# 路线图

本路线只说明当前边界与下一步，不自动授权实现。

## 当前可用

- 确定性水质合同、规则诊断、只读内置情景与独立 Detection Mock 数据。
- telemetry/：Builtin / User Scenario Template → Simulator → SimulationAdapter → WaterQualityReading → CurrentSnapshotStore。Web 支持自定义情景 Modal、仅应用、保存 / 编辑 / 另存 / 删除；CLI 使用同一模板转换逻辑。两个 schema 只用于模拟，快照在进程内共享，重启为空。
- TF-IDF 知识检索、Evidence Grounding、Normal / Application Streaming。
- Preset、Managed Custom、Manual Expert V1/V2 三条模型接入路径。
- R2 用户私有凭据、R3 ProtocolSpec、R4 Capability Evidence Resolver、R5 显式单项 Probe。
- Usage、JSONL Trace、请求取消及离线 Python / Browser 测试。
- 只读 Tool Calling T1–T5：Gateway 合同、静态 Registry / Executor、get_current_water_quality、单轮 Model → Tool → Model 和 Web 离线开发入口。当前事实只经共享 CurrentWaterQualityReader 读取，首次请求不预载水质；固定 Analysis 保留。

## 当前整理与下一步

Managed Custom 已有 T5 显式 Tool Probe，入口在模型能力的高级验证操作；用户已报告 QW_2 实际验证成功，证据只授权精确 Identity。Development / Test 负责已有能力的对话验证，不自动管理能力。

Analysis Model 保留固定分析，不向模型暴露 Tool；Assistant Model 当前为 Policy 限制的单轮实验路径。见[架构与 Tool Policy](deep-dive/ASSISTANT_MODEL_ARCHITECTURE.md)。下一步可单独评审实验评分 Tool 的程序 / 模型触发方式，以及 Preset Tool Calling Qualification；当前没有实现评分或升级 Preset。真实请求仍需当轮明确授权。

第一阶段仍只有 get_current_water_quality，NO_DATA 明确返回。工具不读取 Scenario Template、SimulationPacket、场景资源或硬件原始 JSON，不改变规则、Snapshot 或数据库。保留已有 allowlist、单轮限制、Trace 和取消；不增加 Streaming Tool Calling 或 Agent。Manual 返回的 tool_calls 继续只展示、不执行。

## 暂缓

- Agent Loop：只读工具边界验收后再单独决策；不得直接操作设备、数据库或阈值。
- 生产项目 / 真实传感器 Adapter：等待硬件协议样例、单位、时钟和设备状态定义。未来 Hardware Receiver → Hardware Adapter → WaterQualityReading → 同一个 CurrentSnapshotStore；不把 sim-v1 当成计算板协议。
- RAG 评估继续使用离线对照；没有证据前不增加向量数据库或大型框架。
- Fine-tuning 等待明确任务定义和额外数据。

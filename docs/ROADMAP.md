# 路线图

**CURRENT · 2026-10-03**。阶段名用于范围划分，不自动授权实施。每阶段先审计、定义最小合同、离线验证，再安排明确授权的真实验证。

## 已完成基础

- canonical 水质/Detection/ObservedFacts、Quality 与 Freshness 分离、Mock 数据、确定性诊断。
- TF-IDF RAG baseline、Grounding 与结构化 AnalysisResult / Usage / Trace。
- Cloud/Local SDK adapter、应用 Streaming、请求取消、Secret 安全错误。
- R2 用户私有凭据 CRUD / hot reload / immutable snapshot。
- R3 ProtocolSpec、R4 Evidence Resolver、R5 显式单项 Probe。
- Preset / Managed / Manual V1/V2 三种路径；三个新 Preset 固定合同已有用户人工运行依据。
- 离线 Python / Browser 测试。生产项目尚未接入，真实模型结论仅限精确 Identity/发布组合。

## 1. 水质数据与 telemetry Adapter 准备（本轮）

盘点规则与 Scenario，补离线边界/组合测试，复用 WaterQualityReading canonical 合同。向硬件团队获取实际 packet、单位、时间和传输样例；**真实 Adapter 实现待样例确认**。[研究与矩阵](research/WATER_QUALITY_SCENARIO_AND_TELEMETRY_PREPARATION.md)。

## 2. Read-only Tool Calling（下一设计阶段，尚未实现）

定义 get_current_water_quality / get_recent_water_quality 等最小只读合同；输出来自 canonical Snapshot Store / Domain Service，不让 Tool 或 LLM 直接解析硬件 JSON。Diagnosis 保持程序负责，LLM 不能改阈值或事实。历史工具要先有实际数据源，不能用空接口假装已实现。

## 3. Tool execution boundary（工具运行前必须验收）

只读 allowlist、参数校验、受限数据范围、请求标识、审计、超时/取消与输出事实来源；禁止任意 DB mutation、文件写入或硬件控制。Tool Calling 的协议试验不能代替执行权限设计，不自动执行 Manual 返回的 tool_calls。

## 4. Read-only Agent Loop（上述边界稳定后，单独授权）

定义有限步数、终止条件、失败/取消和可解释记录，只允许已验收只读工具。不自动控制增氧机、投喂设备、DB 或规则。当前固定 Orchestrator 不因新模型可用而改为 Agent。

## 5. 后续 Memory / production integration

有实际任务、数据授权与验收目标后再讨论 Memory、传感器历史、正式项目 Adapter、Detection / YOLO、生产集成。正式 Fishery_Project 仍只读；本路线不授权修改。

## 持续评估与未启动事项

RAG relevance / Grounding / JSON 输出评估与各阶段并行，但没有新向量数据库或自动 JSON repair。知识 provenance 缺口须由真实资料补足，不编造来源。

Fine-tuning: pending task definition and additional data。数字人、自动模型发布、在线全能力扫描和自动 Provider failover 无当前实施任务。旧 A1/A2/A3 路线只保留在[历史](history/README.md)。

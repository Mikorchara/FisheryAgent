# 路线图

路线图区分已稳定能力、暂停项和未来研究，不构成自动实施授权。

## STABLE

- 结构化水质合同、确定性诊断、Scenario/Telemetry 到 canonical Snapshot 的进程内数据链。
- TF-IDF RAG baseline、证据边界与固定 Analysis（Normal / application Streaming）。
- Preset、Managed Custom、Manual Expert V1/V2 三种模型接入方式；OpenAI-compatible SDK Gateway、凭据快照、Usage、JSONL Trace 与请求取消。
- Managed 精确 Identity 的 Capability Evidence / Resolver / 显式 Probe；Preset 使用维护者固定合同。
- Assistant Model v1：三个发布 Preset，OFF + Normal，有界页面会话历史，最多一个只读 Tool / 一轮 / 两次模型请求。
- Analysis Model 可按 Policy 显式启用 Normal 单轮只读 Tool；Development/Test 提供安全测试入口。水质查询和实验评分保持原流程；第三个 Knowledge Tool 的实现与验收状态见下节。Tool Calling 不等于 Agent。
- 全离线 Python 与 Browser 回归测试。

## IMPLEMENTED / VALIDATION PENDING

- **Knowledge Tool v1**：参数合同、validator、Handler、NO_MATCH、Registry、Catalog、共享服务装配与 UI 已实现；Web 中可执行，必须由用户显式选择，包内默认关闭。
- **待验收**：真实模型多 Tool 选择、History 干扰、无 Tool 却声称已查询 / 评分 / 检索，以及知识相关性；不能以协议可传输代替真实验收。四项 Qwen 首轮取证因正式凭据预检失败未启动。
- 阶段依据见[Knowledge Tool 总结](records/2026-10-knowledge-tool-v1-summary.md)；当前合同见[只读 Tool 文档](deep-dive/tools/READ_ONLY_TOOL_CALLING.md)。

## PAUSED

- RAG v2 / Retrieval Benchmark 未恢复开发；不因 Knowledge Tool 已注册而自动启动检索架构改造。

## RESEARCH

- RAG 检索质量改进与离线评估；先建立可复现基准，再决定是否调整排序或数据合同。当前 TF-IDF baseline 保持不变。

## NEXT

- Tool 选择与来源声明问题：先完成有限 Provider 取证，再决定修复范围；不自动扩大请求或 Tool round。
- Production Integration preparation：先审查正式项目的数据与服务边界，再提出渐进式集成方案；原型不直接替换生产流程。

## FUTURE

- Detection facts：先确定 canonical Detection 合同、来源与时序，再决定是否接入模型上下文或只读 Tool。
- Multi-Tool：只有业务需要同一轮联合多个结果时再设计预算和冲突语义；当前每轮最多一个 Tool。
- Agent：未来单独评审自治范围、预算、停止条件和人工控制；不得直接修改设备、数据库或诊断阈值。

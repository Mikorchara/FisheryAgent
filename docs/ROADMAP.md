# 路线图

路线图区分已稳定能力、暂停项和未来研究，不构成自动实施授权。

## STABLE

- 结构化水质合同、确定性诊断、Scenario/Telemetry 到 canonical Snapshot 的进程内数据链。
- TF-IDF RAG baseline、证据边界与固定 Analysis（Normal / application Streaming）。
- Preset、Managed Custom、Manual Expert V1/V2 三种模型接入方式；OpenAI-compatible SDK Gateway、凭据快照、Usage、JSONL Trace 与请求取消。
- Managed 精确 Identity 的 Capability Evidence / Resolver / 显式 Probe；Preset 使用维护者固定合同。
- Assistant Model v1：三个发布 Preset，OFF + Normal，有界页面会话历史，最多一个只读 Tool / 一轮 / 两次模型请求。
- Assistant History v2：完整 pair 裁剪后使用 `UNTRUSTED_TRANSCRIPT_V1@1`；保留内部 `CURRENT_NATIVE@1` 回滚，配置在 app epoch 内固定，Web 不可覆盖。
- Assistant Source Contract：真实执行结果生成有限 Receipt；内部非 AUTO 来源要求受提交门禁约束。普通 Web 请求仍为 AUTO，不自动判断自然语言意图。
- Analysis Model 可按 Policy 显式启用 Normal 单轮只读 Tool；Development/Test 提供安全测试入口。三个 Tool 为水质查询、实验评分、项目知识检索；Knowledge 默认关闭并需显式授权。Tool Calling 不等于 Agent。
- 全离线 Python 与 Browser 回归测试。

## 验证范围与剩余风险

- 受控真实资格实验已覆盖 Knowledge 调用、历史再查询与三模型投影对照，P2E 结果支持可回滚迁移；详情见[迁移决策](records/2026-10-history-v2-migration-decision.md)。这是有限样本，不是长期选择稳定性或回答真实性证明。
- 普通 AUTO 请求仍可能无 Tool 却声称“已查询 / 已评分 / 已检索”。Receipt 不从正文生成，也不认证正文真实性；当前没有自然语言 Requirement Router。
- Knowledge 检索相关性、Analysis 自动 RAG 与可选 Knowledge Tool 的双重证据来源仍待评估。当前合同见[只读 Tool 文档](deep-dive/tools/READ_ONLY_TOOL_CALLING.md)，历史材料见[记录索引](records/README.md)。

## PAUSED

- RAG v2 / Retrieval Benchmark 未恢复开发；不因 Knowledge Tool 已注册而自动启动检索架构改造。

## RESEARCH

- RAG 检索质量改进与离线评估；先建立可复现基准，再决定是否调整排序或数据合同。当前 TF-IDF baseline 保持不变。

## NEXT

- Assistant 来源与历史可靠性：在已完成的受控实验基础上评审产品剩余风险；保留回滚，不自动扩大请求、工具预算或引入意图路由。
- Production Integration preparation：先审查正式项目的数据与服务边界，再提出渐进式集成方案；原型不直接替换生产流程。

## FUTURE

- Detection facts：先确定 canonical Detection 合同、来源与时序，再决定是否接入模型上下文或只读 Tool。
- Multi-Tool：只有业务需要同一轮联合多个结果时再设计预算和冲突语义；当前每轮最多一个 Tool。
- Agent：未来单独评审自治范围、预算、停止条件和人工控制；不得直接修改设备、数据库或诊断阈值。

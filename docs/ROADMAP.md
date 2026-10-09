# 路线图

路线图区分已稳定能力、暂停项和未来研究，不构成自动实施授权。

## STABLE

- 结构化水质合同、确定性诊断、Scenario/Telemetry 到 canonical Snapshot 的进程内数据链。
- TF-IDF RAG baseline、证据边界与固定 Analysis（Normal / application Streaming）。
- Preset、Managed Custom、Manual Expert V1/V2 三种模型接入方式；OpenAI-compatible SDK Gateway、凭据快照、Usage、JSONL Trace 与请求取消。
- Managed 精确 Identity 的 Capability Evidence / Resolver / 显式 Probe；Preset 使用维护者固定合同。
- Assistant Model v1：三个发布 Preset，OFF + Normal，有界页面会话历史，最多一个只读 Tool / 一轮 / 两次模型请求。
- Analysis Model 可按 Policy 显式启用 Normal 单轮只读 Tool；Development/Test 提供安全测试入口。当前两个 Tool 为水质查询和实验评分。Tool Calling 不等于 Agent。
- 全离线 Python 与 Browser 回归测试。

## PAUSED

- **Knowledge Tool**：只读检索项目内鲭鲡养殖背景知识。Step 2–8 已完成（参数合同、`NO_MATCH`、Handler、注册、Catalog 条目、Policy 默认核对、共享服务装配）；**真实 Runtime 中已 `executable`，用户可勾选，但默认不授权**。剩余：提示词选择规则（Step 9）、UI 文案（Step 10）、离线测试与人工验收（Step 11）。
- **阻塞项 D1b**：`MockToolGateway` Request #1 的 `request.tools[0]` fallback，会以 `"{}"` 调用 Knowledge 而被 validator 拒。**必须在 Mock Knowledge 的人工使用/验收之前解决**（Step 11 前置）。

## RESEARCH

- RAG 检索质量改进与离线评估；先建立可复现基准，再决定是否调整排序或数据合同。当前 TF-IDF baseline 保持不变。

## NEXT

- Copilot Handoff：整理源码学习路径与交接材料。
- Production Integration preparation：先审查正式项目的数据与服务边界，再提出渐进式集成方案；原型不直接替换生产流程。

## FUTURE

- Detection facts：先确定 canonical Detection 合同、来源与时序，再决定是否接入模型上下文或只读 Tool。
- Multi-Tool：只有业务需要同一轮联合多个结果时再设计预算和冲突语义；当前每轮最多一个 Tool。
- Agent：未来单独评审自治范围、预算、停止条件和人工控制；不得直接修改设备、数据库或诊断阈值。

# 管理平台路线

共享 AI Runtime 现状见根 [路线图](../../docs/ROADMAP.md)。规划不表示已授权真实服务接入。

## 已实现

- R1：独立管理布局、七业务页面、Demo/空状态、只读应用 API 和测试。
- R1.1：工程规则与管理平台文档入口。
- R2A：独立连续模拟器、v1 HTTP 上报校验、本机写入门禁、SQLite 当前状态/有界历史、服务器领域诊断、模拟事件去重、四页面统一读取与轮询、设备绑定 Reader。没有 AI 对话或真实设备/NPU。
- R2A.1：精确窗口统计、检测记录加权体长、逐样本质量、阻塞跳窗、北京时间到秒。
- R2B-1：统一通道分析合同、PROTOTYPE 规则身份、每指标证据门禁、ACTIVE/RESOLVED/INDETERMINATE、事件等级/版本/旧库兼容；没有 AI 接入。
- R2B-2：纯 DomainAnalysisService / EventService、事务内事件变更应用、统一设备绑定分析查询；模拟器发送前有界检查 UTC 窗口完成，保持严格服务端时间门禁。

## R2B-3：Normal Assistant 已接入，等待人工验收

薄 ManagementAssistant 复用 AssistantService、Gateway、ToolCallingService、Ledger、Commit Gate、History Projection 与取消机制。Qwen 为默认、保留 Ollama，固定 OFF / Normal / 1 Call / 1 Round / 2 Requests；当前水质 Tool 读取同一 SQLite 与治理后的规则结果，设备按 Turn 冻结。正常启动默认关闭 AI；--enable-assistant 后仍需每次 Send 明确网络确认。规则保持 PROTOTYPE，本轮仅完成离线验证，未调用 Provider。参见 [当前集成边界](INTEGRATION.md#r2b-3-normal-assistant-桥接)。

### 后续接入顺序（未实施）

1. 人工验收当前 Normal、设备/数据来源、质量、取消和 History；真实模型测试需单独授权。
2. 设计管理数据专用评分/知识/视觉 Tool 的业务与来源合同，不直接复用旧 Snapshot Handler。
3. 按精确资格 Scope 单独评估 Multi-Round / Streaming。管理应用本轮不继承原 Prototype 的实验开关或发布范围；原 Prototype Snapshot 仍独立，未切换数据库。

## 后续独立工作

- 真实 Monitoring：设备登记/认证、物理采集 Adapter、持久历史与运维策略；不由客户端自报真实来源。
- Video/NPU：实际视频传输、校准、推理结果归一化、受控截图/片段；不迁移旧 GPU 桌面项目。
- Events：生产告警策略、通知、人工处理和审计；当前 closed 只表示模拟信号消退。
- Knowledge/Files：文件管理、索引与检索分别接入，RAG 改善单独设计。
- Security：账户、服务端权限、生产设备凭据、TLS、限流、监控/备份和迁移；开发令牌不能当作生产方案。

不增加 Agent、自动设备写操作或通用场景编辑器，不为规划建立空模块。

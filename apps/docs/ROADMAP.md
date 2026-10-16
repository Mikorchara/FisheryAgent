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

薄 ManagementAssistant 复用 AssistantService、Gateway、ToolCallingService、Ledger、Commit Gate、History Projection 与取消机制。Qwen 为默认、保留 Ollama，默认 OFF / Normal / 1 Call / 1 Round / 2 Requests；当前水质 Tool 读取同一 SQLite 与治理后的规则结果，设备按 Turn 冻结。正常启动默认关闭 AI；--enable-assistant 后仍需每次 Send 明确网络确认。规则保持 PROTOTYPE，本轮仅完成离线验证，未调用 Provider。参见 [当前集成边界](INTEGRATION.md#r2b-3-normal-assistant-桥接)。

### 已完成的接入整理

R2B-3.1 已补安全参数拒因；R2B-3.2 已提供 current-only WaterCapture 与独立 Web / Tool 投影，保留全部质量、规则和来源语义，去除 Tool 的趋势读取及重复 analysis。仅离线验证，不表示真实模型回答质量获新资格。

R2B-3.3 已装配现有 Knowledge Tool，复用原 KnowledgeService / Handler / 参数校验与来源合同；通过已有 Policy 显式 opt-in。UI 区分背景检索与当前观测；NO_MATCH 不冒充命中。仍为 OFF / Normal / 1/1/2，未授权新资格或开放多轮。

R2B-3.4 已提取独立 apps/ai_service：业务协调、Runtime 装配、Monitoring/Knowledge 绑定与冻结 Turn 合同；Web 保留 HTTP/浏览器访问控制和同一 RequestHandle 的创建/状态/Stop。无新能力或模式，未来多轮/Streaming/新 Tool 的业务装配从该包扩展，不在 Web 重建执行逻辑。

### 下一步（未实施）

1. 人工验收当前 Normal、设备/数据来源、质量、取消和 History；真实模型测试需单独授权。
2. 人工验收项目知识调用、NO_MATCH、来源可信度与当前事实区分；评分/视觉查询另行设计，不直接复用旧 Snapshot Handler。Knowledge 相关性改善留待独立 RAG 研究。
3. R2B-4 已接入管理独立的默认关闭 Flag、精确 Scope、动态预算确认和安全 Steps；Qwen/Ollama 各自为 local_experimental。显式启用且授权水质 + Knowledge 后复用正式 2/2/3 Runtime，默认仍 1/1/2。下一步是单独授权管理链路真实多轮资格与人工质量审核；Streaming 另立门禁，不继承原 Prototype 发布记录。

## 后续独立工作

- 真实 Monitoring：设备登记/认证、物理采集 Adapter、持久历史与运维策略；不由客户端自报真实来源。
- Video/NPU：实际视频传输、校准、推理结果归一化、受控截图/片段；不迁移旧 GPU 桌面项目。
- Events：生产告警策略、通知、人工处理和审计；当前 closed 只表示模拟信号消退。
- Knowledge/Files：文件管理、索引与检索分别接入，RAG 改善单独设计。
- Security：账户、服务端权限、生产设备凭据、TLS、限流、监控/备份和迁移；开发令牌不能当作生产方案。

不增加 Agent、自动设备写操作或通用场景编辑器，不为规划建立空模块。


## R2B-5：Streaming 分阶段接入

- R2B-5B 后端已离线实现：管理独立 candidate/关闭开关、精确 revision、唯一 claim、POST SSE 与原 Streaming Runtime；Qwen 两工具，512 上限 / 2/2/3 / 120 秒。用户已报告 Qwen 管理 Normal 多轮初步验收通过，但未因此发布 Streaming。
- R2B-5C 前端已离线接通：模式选择、严格 SSE 消费、原卡片预览转 Final、Stop/断线撤销、共用成功 History、内部滚动和问题导航。Normal 默认，未启用或不匹配的 Streaming 仍拒绝真实发送。
- R2B-5D 管理独立单案例入口已完成三个真实技术 PASS（Direct Final、当前水质、低氧双 Tool），共六次模型请求；安全报告不保存正文，人工回答质量仍未批准，CLI 未覆盖真实浏览器。见 [逐案例操作与审批](deep-dive/STREAMING_QUALIFICATION.md)。
- R2B-5E 用户明确批准 Qwen OFF / 两工具 Streaming local_experimental；`--assistant-streaming-trial` 进程内启用，默认关闭，非 released。下一步由用户进行网页体验；回答质量另行研究。Ollama、评分/三工具、其他 Provider 不继承范围。启动和回滚见 [BUILD_RUN](BUILD_RUN.md#r2b-5eqwen-streaming-本地实验)。

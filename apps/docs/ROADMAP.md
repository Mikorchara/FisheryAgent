# 管理平台路线

管理平台以独立 `apps.ai_backend` 为当前执行实现；旧 Prototype 的实验路线见根 [路线图](../../docs/ROADMAP.md)。规划不表示已授权真实服务接入。

## 已实现

- R2D-4A：六区设置中心、默认偏好、固定云Provider私有密钥与原 Tool 授权。
- R2D-4B：Qwen/DeepSeek 主动连接测试后保存，Qwen 本地 Normal/Streaming 的版本化 1–4096 输出范围；不新增模型或 RAG 配置。自定义模型、地址编辑、其他 Provider 可调预算与高级检索仍待后续批准，不自动授权 Tool/Streaming。

- R2D-3B：统一SQLite文本知识库、旧资源显式迁移/备份、内置导入可编辑、状态恢复、JSON/Markdown导出；管理Knowledge已脱离旧代码，保持TF-IDF算法与现有Tool权限。[迁移合同](deep-dive/KNOWLEDGE_CONTENT.md)。实际用户库迁移待批准。

- R1：独立管理布局、七业务页面、Demo/空状态、只读应用 API 和测试。
- R1.1：工程规则与管理平台文档入口。
- R2A：独立连续模拟器、v1 HTTP 上报校验、本机写入门禁、SQLite 当前状态/有界历史、服务器领域诊断、模拟事件去重、四页面统一读取与轮询、设备绑定 Reader。没有 AI 对话或真实设备/NPU。
- R2A.1：精确窗口统计、检测记录加权体长、逐样本质量、阻塞跳窗、北京时间到秒。
- R2B-1：统一通道分析合同、PROTOTYPE 规则身份、每指标证据门禁、ACTIVE/RESOLVED/INDETERMINATE、事件等级/版本/旧库兼容；没有 AI 接入。
- R2B-2：纯 DomainAnalysisService / EventService、事务内事件变更应用、统一设备绑定分析查询；模拟器发送前有界检查 UTC 窗口完成，保持严格服务端时间门禁。

## 当前 AI 基础：R2C-1 主要迁移已完成

ManagementAssistant → ManagementAssistantService → 业务 Assistant / 独立 Backend。Qwen 为默认、保留 Ollama，默认 OFF / Normal / 1 Call / 1 Round / 2 Requests；本地试用可显式开启 Normal 多轮或 Qwen 精确两工具 Streaming。当前水质 Tool 与网页共享 Monitoring / SQLite，设备按 Turn 冻结。正常启动默认关闭 AI；--enable-assistant 后仍需每次 Send 确认。用户已报告独立 Backend 的 Qwen Normal 水质查询、Streaming 水质 + Knowledge、Final 提交及模拟来源 / PROTOTYPE 标签正常。它是基本网页验收，未升级正式资格，回答质量仍待专项审核。

### 已完成的接入整理

R2B-3.1 已补安全参数拒因；R2B-3.2 已提供 current-only WaterCapture 与独立 Web / Tool 投影，保留全部质量、规则和来源语义，去除 Tool 的趋势读取及重复 analysis。仅离线验证，不表示真实模型回答质量获新资格。

R2B-3.3 已装配现有 Knowledge Tool，复用原 KnowledgeService / Handler / 参数校验与来源合同；通过已有 Policy 显式 opt-in。UI 区分背景检索与当前观测；NO_MATCH 不冒充命中。仍为 OFF / Normal / 1/1/2，未授权新资格或开放多轮。

R2B-3.4 已提取独立 apps/ai_service：业务协调、Runtime 装配、Monitoring/Knowledge 绑定与冻结 Turn 合同；Web 保留 HTTP/浏览器访问控制和同一 RequestHandle 的创建/状态/Stop。无新能力或模式，未来多轮/Streaming/新 Tool 的业务装配从该包扩展，不在 Web 重建执行逻辑。

### 下一步业务开发（待另行批准）

1. 以已完成的 Backend 为基础完善管理业务；针对实际需求补充 History 跨模式、Stop、断线和异常来源的人工验收。现有离线覆盖不替代这些人工观察，新的真实请求需单独授权。
2. 独立评估回答质量、Knowledge 相关性和来源表述；知识命中不能证明现场状态或疾病，评分 / 视觉 Tool 需单独合同与授权。
3. R2D-2B已获用户批准并开放Qwen三工具Normal/Streaming本地实验，移除历史快捷操作；下一步由用户真实网页验收选择与来源，技术资格和回答质量另行记录，不自动released。视觉检测Tool、持续异常分析或固定上下文Analysis按实际需要另行开发，不复制Runtime。新RAG保持独立研究任务。

R2D-2A已补Policy锁初始化、管理测试入口、一行启动和全屏/阅读模式；当时三工具为candidate。当前范围和按钮修复见[R2D-2B](deep-dive/R2D2B_UNIFIED_TOOLS.md)，原[2A记录](deep-dive/R2D2A_PRODUCT_INTEGRATION.md)保留历史。

## 后续独立工作

- R2C-1E 已完成迁移收尾与基本真实网页人工验收；不再继续零散 Runtime 迁移。Monitoring 的 Diagnosis / telemetry / Reading，仍依赖旧领域包，应另立领域独立化任务；Knowledge的旧代码依赖已由R2D-3B移除，旧JSON仅作迁移/隔离资格来源，不迁入通用 Backend。旧 Prototype 继续独立实验。见 [收尾记录](deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md#15-r2c-1e-工程收尾与人工验收)。
- 真实 Monitoring：设备登记/认证、物理采集 Adapter、持久历史与运维策略；不由客户端自报真实来源。
- Video/NPU：实际视频传输、校准、推理结果归一化、受控截图/片段；不迁移旧 GPU 桌面项目。
- Events：生产告警策略、通知、人工处理和审计；当前 RESOLVED 需可靠新观测确认规则恢复，不表示人工处置或生产告警闭环。
- Knowledge/Files：文件管理、索引与检索分别接入，RAG 改善单独设计。
- Security：账户、服务端权限、生产设备凭据、TLS、限流、监控/备份和迁移；开发令牌不能当作生产方案。

不增加 Agent、自动设备写操作或通用场景编辑器，不为规划建立空模块。


## R2B-5：Streaming 分阶段接入

- R2B-5B 后端已离线实现：管理独立 candidate/关闭开关、精确 revision、唯一 claim、POST SSE 与原 Streaming Runtime；Qwen 两工具，512 上限 / 2/2/3 / 120 秒。用户已报告 Qwen 管理 Normal 多轮初步验收通过，但未因此发布 Streaming。
- R2B-5C 前端已离线接通：模式选择、严格 SSE 消费、原卡片预览转 Final、Stop/断线撤销、共用成功 History、内部滚动和问题导航。Normal 默认，未启用或不匹配的 Streaming 仍拒绝真实发送。
- R2B-5D 管理独立单案例入口已完成三个真实技术 PASS（Direct Final、当前水质、低氧双 Tool），共六次模型请求；安全报告不保存正文，人工回答质量仍未批准，CLI 未覆盖真实浏览器。见 [逐案例操作与审批](deep-dive/STREAMING_QUALIFICATION.md)。
- R2B-5E 用户明确批准 Qwen OFF / 两工具 Streaming local_experimental；`--assistant-streaming-trial` 进程内启用，默认关闭，非 released。R2C-1E 用户已报告新 Backend 基本网页体验通过，回答质量另行研究。Ollama、评分/三工具、其他 Provider 不继承范围。启动和回滚见 [BUILD_RUN](BUILD_RUN.md#r2b-5eqwen-streaming-本地实验)。

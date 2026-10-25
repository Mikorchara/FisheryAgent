# 管理平台路线

管理平台以独立 `apps.ai_backend` 为当前执行实现；旧 Prototype 的实验路线见根 [路线图](../../docs/ROADMAP.md)。规划不表示已授权真实服务接入。

## 已实现

- 2026-10-25 BOT 阶段审计：区分 QQ 专用与 Web 共享 SDK 影响，保留资源门禁和暂停草稿；增加三个默认不联网的 PowerShell 7 薄验收入口。用户报告 FAST 真实端到端已通过，模型自由文本仍不展示。[当前总结](deep-dive/BOT_STAGE_SUMMARY.md)、[审计](deep-dive/research/BOT_WEB_IMPACT_AUDIT.md)、[测试入口](deep-dive/BOT_TEST_WORKFLOW.md)。下列 BOT 条目为阶段完成时记录，不是最新联网资格。

- 2026-10-25 BOT-3C-FAST：Monitoring-only Qwen本机/QQ试用准备，限时独立审批、防重复消费、保守费用预留、单次交付；仅离线验证，真实联网待另批，SDK资源门禁保留、进程隔离暂停。[说明与操作](deep-dive/BOT3C_FAST_QWEN_TRIAL.md)。

- 2026-10-25 BOT-3C-2A：SDK租约/有限清理/粘性隔离，Handle/Commit/QQ防线；20新专项、810 Python / 116 Node通过，Scope v2仍candidate。硬退出仍需进程隔离，真实QQ AI关闭。[实施与评估](deep-dive/BOT3C2A_SDK_RESOURCE_GATE.md)。

- 2026-10-25 BOT-3C-1（Prototype离线准备）：独立candidate预检、统一回复Fake装配、真实SDK内存HTTP取消、事实/解释分区；28专项、790 Python / 116 Node通过，真实授权/装配与SDK不合作清理仍阻塞。[准备与BOT-3C-2清单](deep-dive/BOT3C1_REAL_AI_PREPARATION.md)。

- 2026-10-25 BOT-3B-2（仅 Prototype Fake）：1执行/2等待、10s排队/90s总期限、权限失效与I/O取消、单次提交及未知不重试；40专项、762 Python / 116 Node通过，保留 candidate 与真实 AI_DISABLED。[实现、验证与 BOT-3C 前置条件](deep-dive/BOT3B2_QQ_AI_SCHEDULING.md)。

- 2026-10-25 BOT-3B-1（仅 Prototype 离线）：Monitoring-only、QQ AI 权限交集/失效、单轮 Fake Tool Calling 与同轮 SourceSummary；31 专项、722 Python / 116 Node 完整回归通过。模型正文隔离、真实 Provider/QQ 未开放。[实现与 BOT-3B-2](deep-dive/BOT3B1_QQ_AI_BOUNDARY.md)。

- 2026-10-25 BOT-3A 架构调查完成：建议同进程 AI Service＋有界 AI worker，先补 Monitoring-only 与渠道权限装配，再做单轮 Fake 联调；48 项无数据库离线检查通过。[研究、风险与 BOT-3B 计划](deep-dive/research/BOT3A_QQ_AI_SERVICE_INTEGRATION.md)。未实现 QQ AI、未调用模型或连接 QQ。

- 2026-10-25 BOT-2B（仅 Prototype）：Repository `mode=ro/query_only`、显式实例/设备装配、复用当前/历史/周期投影和有界设备查询；不接 Knowledge/LLM，不改 Schema。隔离回归与真实接入步骤见 [实施及人工验收](deep-dive/BOT2B_MONITORING_READ_ONLY.md)，真实实例仍待单独批准。

- 2026-10-24 BOT-1B：Prototype 增加官方 HTTPS/WSS、心跳/Resume、有界重连与被动回复，复用 BOT-1A 门禁及私有 CredentialStore；只开放 help/临时虚构数据。管理 640 Python / 116 Node（含 73 Bot）通过，真实群联调待用户配置，不接 LLM、不主动通知、不同步 Management。[配置与验收](deep-dive/BOT1B_QQ_TRANSPORT.md)。

- 2026-10-24 BOT-1A：从 Management 选择性移植 9 个离线 Adapter/测试文件，保留原实现；固定只读命令与群/成员门禁，虚构 SQLite，无 QQ/Provider 调用。后续 BOT-1B/BOT-1C 统一先 Prototype 开发→人工验收与获批提交→Management 选择性同步。[边界与验证](deep-dive/BOT1A_OFFLINE_PROTOTYPE.md)。

- 失联提醒人工结束（仅Prototype，待验收）：原因/确认/幂等/事务校验，稳定周期或旧单条ID，独立于监测恢复；历史保留，新可靠HIT重新提醒，自动裁剪/删除保护。Schema保持v2，未同步Management。[实现及限制](deep-dive/EVENT_MANUAL_END.md)。

- SIMPLIFY-1 收尾（仅 Prototype，待验收）：恢复“已确认/未确认”列，低氧名称随当前可靠等级变化；用户明确批准后，可单独永久删除可靠结束的整个 ACK 周期及其确认历史，事务校验、普通批量清理仍受保护，Schema 保持 v2。新增 `oxygen_drop_recovery` 快降慢升场景及启动枚举。[操作说明](BUILD_RUN.md#溶解氧快速下降--逐步回升)。
- SIMPLIFY-1（仅 Prototype，待验收）：一风险周期一行，服务端全留存整合后筛选分页，首页共用周期摘要；原详情、ACK 与删除保护不变，未实现归档。[实现与验收](deep-dive/EVENT_CYCLE_UI.md)。
- 旧版已结束事件兼容（仅 Prototype）：明确“旧版已结束（未复核）”；有效原结束信息且无活动/引用/ACK 审计关联时，可经原确认流程清理。保留原 payload 与观测状态，不改 Schema，不自动删除真实记录。[条件与边界](deep-dive/EVENT_MANAGEMENT.md#旧版已结束记录兼容仅-prototype)。

- EVT-3A 历史阶段：稳定周期／等级版本 ACK、追加操作历史及审计成员保护；Monitoring Schema v2，v1 只允许显式备份升级，普通启动拒绝。当时 509 项管理 Python、109 项 Node 通过；旧 EVENT_ACK.md 已退役，当前语义见 [事件管理](deep-dive/EVENT_MANAGEMENT.md)。

- EVT-2 文案收尾：只读投影区分等级升级、恢复状态待确认与监测数据中断，首页/列表/详情统一；文案本身不改变生命周期或 SQLite Schema。已选择性同步 Management 并经人工验收。

- EVT-2：按风险族整合首页等级提示，保留 code 与变化证据；事件关注区间五档筛选、服务端分页、已恢复历史预览/确认/事务硬删除。[规则与限制](deep-dive/EVENT_MANAGEMENT.md)。已同步 Management 并经人工验收。

- EVT-1：视觉异常连续三个可靠 CLEAR 才消退；恢复进度同事务持久化，活动事件不受历史 300 条裁剪。首页新增当前异常概况；[状态与验证](deep-dive/EVENT_LIFECYCLE.md)。已同步 Management 并经人工验收。

- 管理页面品牌统一为“AI 监测系统”，保留原 Logo/导航；BUILD_RUN 顶部补充快速入口，Prototype 前台启动与 Management 双终端保护差异继续明确保留。

- 历史图 UI：五档范围、分档 marker、三指标 Min–Max 总览与原值 tooltip；首页两列底边对齐、底部通栏事件，96 项前端回归通过。经人工认可，已选择性同步独立 Management，两个仓库继续独立回归；范围与解释见 [图表说明](deep-dive/HISTORY_CHART_UI.md)。

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

# 管理平台目录与职责

当前实际结构；缓存不展开。完整仓库见根 [地图](../../docs/STRUCTURE.md)。Tool/Prompt/Scope 的开发步骤见 [开发指南](deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)。

```text
apps/
├─ ai_backend/                                                           # 管理正式通用LLM Backend，无旧Runtime依赖
│  ├─ tests/                                                             # 离线测试及Fake SDK
│  │  ├─ __init__.py                                                     # 无启动 I/O 的包标记
│  │  ├─ support.py                                                      # 独立 Fake SDK/分片，无真实传输
│  │  ├─ test_assembler.py                                               # 独立分片、截断、清理与错误测试
│  │  ├─ test_boundary.py                                                # 阻断旧包导入与跨 Runtime 拒绝
│  │  ├─ test_credentials.py                                             # 虚构凭据来源与快照安全
│  │  ├─ test_execution.py                                               # Fake SDK 取消、资源关闭与 Raw body 隔离
│  │  └─ test_protocol_specs.py                                          # 三 Provider 参数编码 parity
│  ├─ tools/                                                             # 通用Registry/Executor/Policy合同
│  │  ├─ __init__.py                                                     # 无启动 I/O 的包标记
│  │  ├─ contracts.py                                                    # Tool 状态/错误、Handler/validator 绑定及执行结果
│  │  ├─ executor.py                                                     # 参数/权限/去重/执行边界
│  │  ├─ policy.py                                                       # 不可变的逐 Turn Tool 授权与 Registry 求交
│  │  └─ registry.py                                                     # 调用方提供的静态绑定
│  ├─ README.md                                                          # 快速入口
│  ├─ __init__.py                                                        # 无启动 I/O 的包标记
│  ├─ assistant_activity.py                                              # 安全通用 Steps 投影
│  ├─ assistant_events.py                                                # 有序有界事件及临时预览
│  ├─ contracts.py                                                       # 执行状态、Usage 聚合、RuntimeInfo 与 UTC 辅助
│  ├─ credential_paths.py                                                # 底层私有位置检查合同
│  ├─ credentials.py                                                     # 私有 Store/Snapshot 与来源优先级
│  ├─ project_env.py                                                     # 既有固定路径凭据写入器的独立实现；CAS/私有权限/原子保存
│  ├─ execution.py                                                       # 请求上下文、取消及 Deadline
│  ├─ history_projection.py                                              # 已保留完整 pair 的 B 默认投影与 A 回滚
│  ├─ manual.py                                                          # 原 Raw 传输合同，无管理 UI 入口
│  ├─ model_gateway.py                                                   # 新模型消息、Profile/Snapshot 与 Gateway
│  ├─ model_options.py                                                   # 原能力与生成选项校验
│  ├─ observability.py                                                   # 限定字段安全 Trace
│  ├─ openai_compatible_adapter.py                                       # SDK 传输、Streaming assembler 与归一化
│  ├─ protocol_specs.py                                                  # Provider 参数编码规则
│  ├─ providers.py                                                       # Provider/Auth 元数据
│  ├─ secure_files.py                                                    # 原私有文件/锁/链接安全逻辑
│  ├─ tool_argument_diagnostics.py                                       # 新侧独立参数拒因合同
│  └─ tool_conversation.py                                               # 有序 Steps、预算与唯一 Tool 循环
├─ ai_service/                                                           # 独立 AI 业务包（同进程，无新端口）
│  ├─ business_tools/                                                   # 业务 Tool 单模块与统一静态装配
│  │  ├─ __init__.py                                                    # 包标记，无 re-export 或自动发现
│  │  ├─ current_water_quality.py                                       # 水质 Definition、单次 capture 与有限 DTO
│  │  ├─ fishery_knowledge.py                                           # Knowledge Definition、query 校验与有限 Evidence
│  │  ├─ registry.py                                                    # 默认两工具与显式离线历史候选装配
│  │  └─ water_quality_history.py                                       # 历史 Schema/validator、委托 Handler 与有限来源元数据
│  ├─ development/                                                       # 显式开发入口，不由正式 Runtime 导入
│  │  ├─ __init__.py                                                     # 无启动 I/O 的包标记
│  │  ├─ history_qualification.py                                        # 历史单案例计划、隔离夹具及受控候选执行
│  │  ├─ normal_selection_qualification.py                               # 三工具Normal候选单案例，复用既有观察和同意合同
│  │  ├─ qualification_adapter.py                                        # 新Backend资格Adapter，有限预算与安全观察
│  │  ├─ qualification_support.py                                        # 新类型Observer/凭据定位/安全报告写入
│  │  ├─ streaming_observation.py                                        # 有界流式统计/组装/清理观察
│  │  └─ streaming_qualification.py                                      # 管理单案例资格、隔离 SQLite 与安全观察
│  ├─ resources/                                                         # 固定包内业务资源
│  │  ├─ assistant_execution.json                                        # Qwen/Ollama 独立本地实验 Scope，默认关闭
│  │  ├─ assistant_normal_candidate.json                                 # Qwen Normal 三工具精确 candidate，未开放
│  │  ├─ assistant_unified_tools.json                                    # 独立Normal/Streaming三工具本地许可与显式授权子集
│  │  ├─ water_history_candidate.json                                    # 历史单工具local_experimental，默认关闭
│  │  └─ assistant_streaming.json                                        # Qwen 两工具 local_experimental，默认关闭
│  ├─ runtime/                                                           # 业务Assistant/来源/Policy/固定资源，已正式使用
│  │  ├─ resources/                                                      # 固定包内业务资源
│  │  │  ├─ presets.json                                                 # 固定 Preset 合同的独立副本
│  │  │  └─ tool_policies.json                                           # 原默认授权，不覆盖用户文件
│  │  ├─ tests/                                                          # 离线测试及Fake SDK
│  │  │  ├─ __init__.py                                                  # 无启动 I/O 的包标记
│  │  │  ├─ test_differential.py                                         # 独立新旧 Turn 确定性对拍
│  │  │  ├─ test_foundation.py                                           # 来源/History/预算/提交/评分兼容
│  │  │  └─ test_integration.py                                          # 新侧 Fake Normal/Streaming 全路径
│  │  ├─ README.md                                                       # 快速入口
│  │  ├─ __init__.py                                                     # 无启动 I/O 的包标记
│  │  ├─ activity.py                                                     # 水质、Knowledge、历史候选的有限安全摘要
│  │  ├─ assistant.py                                                    # 业务 Prompt、History 裁剪及最终提交
│  │  ├─ catalog.py                                                      # 业务展示 metadata，不授予权限
│  │  ├─ locations.py                                                    # 保留原私有目录身份算法
│  │  ├─ policy.py                                                       # 默认/用户 Tool 选择校验、安全存储与授权求交
│  │  ├─ presets.py                                                      # 新侧固定 Preset 资源加载
│  │  ├─ release_contracts.py                                            # Normal 发布合同、Prompt/Tool 指纹与执行模式解析
│  │  ├─ sources.py                                                      # 业务 Requirement/Receipt/Ledger
│  │  ├─ streaming_contracts.py                                          # Streaming 发布合同、Scope 指纹与可用性解析
│  ├─ tests/                                                             # 离线测试及Fake SDK
│  │  ├─ fixtures/                                                       # 虚构/哈希测试基线
│  │  │  ├─ r2c1d_http_baseline.json                                     # 迁移前六路径安全哈希基线
│  │  │  ├─ r2c1d_plan_baseline.json                                     # 旧计划安全指纹与新授权隔离
│  │  │  ├─ r2c2b_business_tools.json                                    # 迁移前 Definition / DTO 哈希与有限状态基线
│  │  │  └─ r2d1c_two_tools.json                                         # 历史候选接入前六路径与三计划指纹基线
│  │  ├─ __init__.py                                                     # 无启动 I/O 的包标记
│  │  ├─ capture_migration.py                                            # 六条Fake HTTP/SSE哈希采集，无正文/凭据
│  │  ├─ test_backend_migration.py                                       # HTTP前后指纹、旧模块阻断与双侧独立
│  │  ├─ test_business_tools.py                                          # 定义/DTO parity、冻结装配、权限与无旧入口
│  │  ├─ test_history_qualification.py                                    # Dry-run/逐案授权、统计来源、预算与脱敏报告
│  │  ├─ test_history_batch.py                                            # 固定15样本顺序、授权、计数和安全停止
│  │  ├─ test_history_candidate.py                                       # 历史 HTTP 候选门禁、Fake SDK、来源及两工具隔离
│  │  ├─ test_management_policy.py                                       # 独立配置、CAS/并发、恢复和安全写入
│  │  ├─ test_normal_selection.py                                        # 三工具选择、预算、候选隔离与Web输入门禁
│  │  ├─ test_unified_tools.py                                           # 正式HTTP/SSE三工具本地Scope、权限/预算/提交与前端桥接
│  │  ├─ test_normal_selection_qualification.py                           # 四个候选计划、Fake SDK路径/来源/脱敏与拒绝
│  │  ├─ test_execution.py                                               # 管理配置校验、独立 Scope 与默认关闭
│  │  ├─ test_service.py                                                 # 无 Web 的执行、冻结、取消、路径及依赖边界
│  │  ├─ test_streaming_config.py                                        # Streaming 本地试用、类型/预算与独立范围
│  │  ├─ test_streaming_qualification.py                                 # 计划授权、正式管理链路、来源/报告与安全预览
│  │  └─ test_water_history_tool.py                                      # 历史候选、Receipt/Gate、Fake SDK 与原六路径指纹
│  ├─ __init__.py                                                        # 无启动 I/O 的包标记
│  ├─ contracts.py                                                       # 进程内 PreparedAssistantTurn 与 AssistantBackend 合同
│  ├─ content_binding.py                                                 # 动态知识源的精确本地 Scope 变体，不继承旧真实资格
│  ├─ execution.py                                                       # Normal 多轮发布、数据绑定、Scope 与确认 revision
│  ├─ history_execution.py                                               # 历史单工具Scope、1024预算与独立试用门禁
│  ├─ management_policy.py                                               # 管理端授权、只读继承、原子保存与 revision
│  ├─ normal_selection.py                                                # 冻结Normal候选与独立获批的Normal/Streaming本地试用
│  ├─ service.py                                                         # 唯一ManagementAssistantService业务装配
│  ├─ settings.py                                                        # 默认偏好持久化、真实模型/预算投影及固定Provider凭据操作
│  ├─ settings_store.py                                                  # 同一设置JSON的原子CAS、v1兼容与双模式预算持久化
│  ├─ credential_test.py                                                 # 显式单请求连接测试、脱敏错误、短期绑定保存凭证
│  ├─ output_budget.py                                                   # 原精确Scope之后的Qwen有界输出合同，不增加模型资格
│  └─ streaming.py                                                       # Streaming 发布配置、精确 Scope 与确认 revision
├─ knowledge/                                                            # 统一文本内容业务，Web/AI共享
│  ├─ tests/                                                            # 内容/迁移/导出/检索 parity，隔离SQLite
│  ├─ README.md                                                         # 业务入口与迁移说明
│  ├─ __init__.py                                                       # 包标记
│  ├─ __main__.py                                                       # 显式迁移/备份CLI，默认dry-run
│  ├─ evidence.py                                                       # 独立检索Evidence
│  ├─ legacy_import.py                                                  # 仅迁移/历史资格夹具的旧JSON分块
│  ├─ migration.py                                                      # 备份/幂等/校验/原子不覆盖发布
│  ├─ docs/                                                                 # 实际目录
│  ├─ deep-dive/                                                         # 实际目录
│  │  ├─ model/                                                          # 实际目录
│  │  ├─ research/                                                       # 实际目录
│  │  │  ├─ R2B3_MANAGEMENT_AI_ARCHITECTURE_REVIEW.md                    # 当前架构、参数故障证据与路线建议
│  │  │  ├─ R2B5_MANAGEMENT_ASSISTANT_STREAMING_INTEGRATION.md           # Streaming 设计与实施状态
│  │  │  ├─ R2B_DOMAIN_ANALYSIS_AND_AI_INTEGRATION.md                    # R2B-0 评估基线，非实现现状
│  │  │  ├─ R2C1A_LLM_BACKEND_AUDIT.md                                   # 独立化审计基线
│  │  │  ├─ R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md                      # 独立 Backend 迁移方案、实施与最终人工验收
│  │  │  ├─ R2D1A_WATER_HISTORY_TOOL_DESIGN.md                            # 历史查询、来源合同与分阶段分析设计
│  │  │  ├─ R2D1_TOOL_RETROSPECTIVE_AUDIT.md                               # 最终成本、质量风险与简化开发流程
│  │  │  └─ R2D1F_TOOL_INTEGRATION_COST_AUDIT.md                           # 历史Tool成本盘点、预算与批量准备
│  │  ├─ AI_BACKEND_DEVELOPMENT_GUIDE.md                                  # 请求链、Tool/Prompt 扩展与安全测试指南
│  │  ├─ R2D2A_PRODUCT_INTEGRATION.md                                     # Policy修复、候选、启动器与聊天视图验收
│  │  ├─ R2D2B_UNIFIED_TOOLS.md                                           # 操作栏根因、三工具本地范围与离线验收
│  │  ├─ HISTORY_QUALIFICATION.md                                         # 历史候选逐案例计划、审批与人工预览
│  │  └─ STREAMING_QUALIFICATION.md                                      # 单案例批准、脱敏报告、人工预览及试用/回滚
│  ├─ BUILD_RUN.md                                                       # 启动、联调与验证
│  ├─ INTEGRATION.md                                                     # 上报合同和替换边界
│  ├─ README.md                                                          # 快速入口
│  ├─ ROADMAP.md                                                         # 当前状态与后续工作
│  └─ STRUCTURE.md                                                       # 真实目录与职责
├─ management_web/                                                       # 管理页面与 Web 专属后端
│  ├─ static/                                                            # 实际目录
│  │  ├─ app.js                                                          # 七页面路由与监测 5 秒轮询
│  │  ├─ assistant-events.js                                             # 有界 POST SSE、序号/身份/终态校验与流清理
│  │  ├─ assistant.js                                                    # 双模式聊天、全屏/阅读、临时预览、History、Stop、滚动
│  │  ├─ components.js                                                   # 安全文本、卡片、表格、图表
│  │  ├─ index.html                                                      # 布局、来源标识和弹窗
│  │  ├─ tool-policy.js                                                  # 本机设置授权面板，不授予模型发布许可
│  │  ├─ services.js                                                     # 同源监测与受控 Assistant API
│  │  ├─ settings.js                                                     # 六区设置中心、稳定草稿、默认偏好与密钥显式操作
│  │  ├─ styles.css                                                      # 样式与响应式布局
│  │  └─ view-model.js                                                   # 展示转换、来源和状态
│  ├─ tests/                                                             # 离线测试及Fake SDK
│  │  ├─ assistant-events.test.mjs                                       # SSE 分片、重复/乱序、身份、终态与有界拒绝
│  │  ├─ assistant-fixture.mjs                                           # 共用离线聊天 DOM/API 夹具
│  │  ├─ assistant-stream-fixture.mjs                                    # 安全事件与碎片化读流夹具
│  │  ├─ assistant-stream-ui.test.mjs                                    # Streaming 会话、撤销、History 与滚动/导航
│  │  ├─ assistant-transport.test.mjs                                    # 正式 fetch 路由、确认、AbortSignal 与取消
│  │  ├─ assistant-ui.test.mjs                                           # Normal 聊天、History、epoch 与 Stop 行为
│  │  ├─ assistant-view.test.mjs                                         # 全屏/阅读、滚动恢复、进行中Turn与Stop不变
│  │  ├─ chart-fixture.mjs                                               # 固定多次重启、20 小时时间跨度数据
│  │  ├─ chart-ui.test.mjs                                               # 时间坐标、重复/缺口、精度和 SVG
│  │  ├─ dom-fixture.mjs                                                 # 无网络 DOM 测试辅助
│  │  ├─ monitoring-ui.test.mjs                                          # 实际页面代码的离线 DOM 行为
│  │  ├─ local_session_fixture.py                                        # 临时SQLite管理服务器，不装配AI或凭据
│  │  ├─ stream-browser-bridge.mjs                                       # 实际管理 SSE 到前端解析/提交的 Node 桥
│  │  ├─ test_ai_boundary.py                                             # Web 访问控制、令牌隔离、同一 Handle 与显式装配门禁
│  │  ├─ test_app.py                                                     # R1 兼容、API 和安全
│  │  ├─ test_settings.py                                                # 临时私有凭据/配置、HTTP/CAS、实际Turn快照隔离
│  │  ├─ test_settings_connection_budget.py                              # Fake SDK连接测试/保存门禁、预算编码、SSE前端与冻结
│  │  ├─ settings-ui.test.mjs                                            # 设置草稿、显式保存/清除、默认恢复和无自动联网
│  │  ├─ test_assistant.py                                               # Fake Provider HTTP 闭环、同源数据、Ledger 与取消
│  │  ├─ test_knowledge.py                                               # Knowledge HTTP 闭环、授权/来源隔离、拒绝与确认指纹
│  │  ├─ test_local_session.py                                           # 双子进程、10秒上报、占用拒绝和清理
│  │  ├─ test_multi_round.py                                             # HTTP 双 Tool、Scope/revision、预算、取消与回滚
│  │  ├─ test_streaming.py                                               # Fake SDK HTTP/SSE、安全门禁及真实事件到前端的桥接
│  │  ├─ tool-policy.test.mjs                                            # 设置保存、冲突提示与确认失效
│  │  └─ view-model.test.mjs                                             # 纯展示合同
│  ├─ README.md                                                          # 快速入口
│  ├─ __init__.py                                                        # 无启动 I/O 的包标记
│  ├─ __main__.py                                                        # 本机启动、存储装配与写入开关
│  ├─ ai_adapter.py                                                      # Web 薄门面：浏览器令牌、RequestRegistry 与业务合同委托
│  ├─ app.py                                                             # HTTP、访问控制与服务装配
│  ├─ contracts.py                                                       # Web Protocol、共享 DTO 导出
│  ├─ package.json                                                       # Node 原生测试，无依赖
│  ├─ services.py                                                        # R1 兼容 Demo、未接入 AI/文件服务
│  ├─ settings_api.py                                                    # 设置/凭据HTTP，沿用Assistant本机访问门禁
│  └─ streaming.py                                                       # 请求内 SSE 投递、worker 生命周期与断线清理
├─ monitoring/                                                           # Web 与未来 Tool 共享的数据基础
│  ├─ tests/                                                             # 离线测试及Fake SDK
│  │  ├─ test_business_services.py                                       # 纯服务一致性、设备/时间边界与故障回滚
│  │  ├─ test_domain_compatibility.py                                    # MIG-1 新旧领域/Reader/来源验证差分
│  │  ├─ test_history_projection.py                                      # 历史 API 排序、会话与旧元数据兼容
│  │  ├─ test_local_http.py                                              # 真实 loopback 上报及停止/重启
│  │  ├─ test_pipeline.py                                                # 校验、时序、安全、状态与共享来源
│  │  ├─ test_rule_governance.py                                         # 规则状态、证据范围、可靠恢复与兼容
│  │  ├─ test_water_capture.py                                           # 单次读取/诊断、双投影一致性、质量语义和 DTO 大小
│  │  └─ test_water_history.py                                           # 时间范围、质量/覆盖、歧义、来源与预算只读测试
│  ├─ __init__.py                                                        # 无启动 I/O 的包标记
│  ├─ analysis.py                                                        # 纯领域求值、单次水质捕获与 canonical Reading 投影
│  ├─ contracts.py                                                       # v1 上报校验、监测事实与分析 DTO
│  ├─ current.py                                                         # 自有只读 Reader/View；保留 bind().water_reader
│  ├─ diagnosis.py                                                       # 管理端唯一水质阈值实现，保留原规则身份/结果
│  ├─ events.py                                                          # 纯 EventService、事件变更及只读状态投影
│  ├─ history.py                                                         # 有界历史窗口统计、覆盖/缺口与有限 DTO
│  ├─ repository.py                                                      # SQLite、事务、历史与事件变更持久化
│  ├─ rules.py                                                           # 纯评估函数、证据门禁与 PROTOTYPE 规则投影
│  ├─ water_contracts.py                                                 # 独立水质 Reading/枚举/时间校验/RuleFinding
│  └─ service.py                                                         # 监测业务协调、统一查询与设备绑定
├─ simulator/                                                            # 独立设备生产端
│  ├─ tests/                                                             # 离线测试及Fake SDK
│  │  └─ test_simulator.py                                               # Seed、采样、场景、调度与清理
│  ├─ __init__.py                                                        # 无启动 I/O 的包标记
│  ├─ __main__.py                                                        # 场景 CLI、窗口调度与连续 HTTP 上报
│  ├─ generator.py                                                       # 确定性水质/视觉窗口生成
│  ├─ scenarios.py                                                       # 手写 Phase 时间线
│  └─ transport.py                                                       # 受控 HTTP 上报，无重试/重定向
├─ AGENTS.md                                                             # 管理工程与安全规则
└─ __init__.py                                                           # 无启动 I/O 的包标记
```

## 依赖与生命周期

```text
Simulator → 受控HTTP Ingestion → Monitoring contracts → Repository事务
    → DomainAnalysisService / rules（原Diagnosis阈值）→ Findings / EventService
    → Web snapshot/history 或 capture_water（同一SQLite权威来源）

management_web HTTP/SSE/访问控制 + 新RequestRegistry
    → ai_service.service.ManagementAssistantService（唯一业务装配）
    → ai_service.runtime.assistant（Prompt/History/Source Gate/Commit Gate）
    → ai_backend.ToolCallingService → Gateway/Adapter/Assembler → 新Provider类型
    → 新Registry/Policy/Executor → ai_service.business_tools → Monitoring / Knowledge
    → 新Steps / EventChannel / SafeTrace → Web临时Preview或唯一Final
```

Backend无fishery_ai/Flask/SQLite/业务反向依赖。MIG-1 后 Monitoring/Knowledge 和业务 sources 正式链均不导入 fishery_ai，也不连带旧 model_options/telemetry；旧 Prototype 保留独立实现。普通管理测试使用 knowledge/tests/fixtures 固定资源，新旧差分/历史资格/显式迁移仍保留有意的旧包或旧资源引用，后续独立项目需分类处理。管理单个 Turn 只用新 ContextVar/Handle/Registry/Adapter。

Phase I 的五个 runtime 准备模块和三份重复测试已移除；当前 Service/合同/发布装配在顶层，业务 Tool 在 business_tools，无 alias/fallback。R2C-1E 迁移验收记录保留当时结构，见 [收尾记录](deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md#15-r2c-1e-工程收尾与人工验收)。

测试层级：FAST小集合；backend为新Backend及业务合同；FULL PRODUCT含backend一次；FULL QUALIFICATION额外包含管理 Streaming、历史单案例及固定批次资格测试；Web/Node按BUILD_RUN运行。Qualification只在显式开发入口加载，默认dry-run，不自动请求Provider。

业务 Tool：business_tools 下每个模块拥有自己的 Definition/validator/Handler/有限 DTO，registry.py 是唯一装配入口；runtime 的 Policy/来源/Activity 职责不变。旧 runtime/tools.py 与顶层 bindings.py 已删除，不设兼容转发；评分只为已知 Policy 名称，不装配 Handler。新增 Tool 参见 [开发指南](deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md#2-新增业务-tool)。

历史资格 CLI 位于 [scripts/qualification/qualify_management_history.py](../../scripts/qualification/qualify_management_history.py)；默认 Dry-run，只用新 Backend 和正式单轮业务 Assistant，不是 Web 发布开关。见 [逐案例操作](deep-dive/HISTORY_QUALIFICATION.md)。

历史产品试用使用`python -m apps.management_web --enable-assistant --assistant-history-trial`，由Service/Scope/Policy/现有Adapter共同执行，未导入development资格代码。R2D-2B普通聊天由Qwen自主选择已授权三工具，不暴露Profile或历史快捷操作。统一Normal/Streaming需独立服务器试用许可；原两工具与旧历史单工具API/资格保留，不继承真实资格。启动与回滚见[BUILD_RUN](BUILD_RUN.md#r2d-1g历史水质单工具本地试用)。

[qualify_management_history_batch.py](../../scripts/qualification/qualify_management_history_batch.py) 是固定3案例×5的薄进程编排入口：每个子进程仍只运行一个案例，默认Dry-run，真实执行需三个新计划的一次性明确批准；无重试、补跑或自动恢复。

[scripts/manual_real_tests/](../../scripts/manual_real_tests/README.md) 为用户人工真实连接统一索引；`run_qualification.py`只委托管理单案例CLI，新增Normal三工具候选四案例，不参与应用启动。`scripts/dev/run_local.ps1` + `local_session.py` 负责已有CLI的临时令牌/双进程生命周期，不装配AI或修改Policy。`run_tests.py management` 包含Monitoring/Simulator/Backend/AI业务/管理HTTP/SSE和Node；`product`含义不变。资格层保持离线，不能当作真实Provider证据。见[R2D-2A记录](deep-dive/R2D2A_PRODUCT_INTEGRATION.md)。

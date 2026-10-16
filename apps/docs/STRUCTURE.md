# 管理平台目录与职责

当前实际结构；缓存不展开。完整仓库见根 [地图](../../docs/STRUCTURE.md)。

```text
apps/
├─ ai_backend/                                                           # 管理正式通用LLM Backend，无旧Runtime依赖
│  ├─ tests/                                                             # 离线测试及Fake SDK
│  │  ├─ __init__.py                                                     # 无启动 I/O 的包标记
│  │  ├─ support.py                                                      # 独立 Fake SDK/分片，无真实传输
│  │  ├─ test_assembler.py                                               # 独立分片、截断、清理与错误测试
│  │  ├─ test_boundary.py                                                # 阻断旧包导入与跨 Runtime 拒绝
│  │  ├─ test_credentials.py                                             # 虚构凭据来源与快照安全
│  │  ├─ test_execution.py                                               # 管理配置校验、独立 Scope 与默认关闭
│  │  └─ test_protocol_specs.py                                          # 三 Provider 参数编码 parity
│  ├─ tools/                                                             # 通用Registry/Executor/Policy合同
│  │  ├─ __init__.py                                                     # 无启动 I/O 的包标记
│  │  ├─ contracts.py                                                    # Web Protocol、共享 DTO 导出
│  │  ├─ executor.py                                                     # 参数/权限/去重/执行边界
│  │  ├─ policy.py                                                       # 明确授权和参数门禁
│  │  └─ registry.py                                                     # 调用方提供的静态绑定
│  ├─ README.md                                                          # 快速入口
│  ├─ __init__.py                                                        # 无启动 I/O 的包标记
│  ├─ assistant_activity.py                                              # 安全通用 Steps 投影
│  ├─ assistant_events.py                                                # 有序有界事件及临时预览
│  ├─ contracts.py                                                       # Web Protocol、共享 DTO 导出
│  ├─ credential_paths.py                                                # 底层私有位置检查合同
│  ├─ credentials.py                                                     # 私有 Store/Snapshot 与来源优先级
│  ├─ execution.py                                                       # 请求上下文、取消及 Deadline
│  ├─ history_projection.py                                              # 原 B 默认投影与 A 兼容
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
│  ├─ development/                                                       # 显式开发入口，不由正式 Runtime 导入
│  │  ├─ __init__.py                                                     # 无启动 I/O 的包标记
│  │  ├─ qualification_adapter.py                                        # 新Backend资格Adapter，有限预算与安全观察
│  │  ├─ qualification_support.py                                        # 新类型Observer/凭据定位/安全报告写入
│  │  ├─ streaming_observation.py                                        # 有界流式统计/组装/清理观察
│  │  └─ streaming_qualification.py                                      # 管理单案例资格、隔离 SQLite 与安全观察
│  ├─ resources/                                                         # 固定包内业务资源
│  │  ├─ assistant_execution.json                                        # Qwen/Ollama 独立本地实验 Scope，默认关闭
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
│  │  ├─ activity.py                                                     # 固定水质/Knowledge 安全摘要
│  │  ├─ assistant.py                                                    # 业务 Prompt、History 裁剪及最终提交
│  │  ├─ catalog.py                                                      # 业务展示 metadata，不授予权限
│  │  ├─ locations.py                                                    # 保留原私有目录身份算法
│  │  ├─ policy.py                                                       # 明确授权和参数门禁
│  │  ├─ presets.py                                                      # 新侧固定 Preset 资源加载
│  │  ├─ release_contracts.py                                            # 原 Normal 发布合同与指纹
│  │  ├─ sources.py                                                      # 业务 Requirement/Receipt/Ledger
│  │  ├─ streaming_contracts.py                                          # 原 Streaming 发布合同与指纹
│  │  └─ tools.py                                                        # 两工具 Definition/query 合同及已知评分名称
│  ├─ tests/                                                             # 离线测试及Fake SDK
│  │  ├─ fixtures/                                                       # 虚构/哈希测试基线
│  │  │  ├─ r2c1d_http_baseline.json                                     # 迁移前六路径安全哈希基线
│  │  │  └─ r2c1d_plan_baseline.json                                     # 旧计划安全指纹与新授权隔离
│  │  ├─ __init__.py                                                     # 无启动 I/O 的包标记
│  │  ├─ capture_migration.py                                            # 六条Fake HTTP/SSE哈希采集，无正文/凭据
│  │  ├─ test_backend_migration.py                                       # HTTP前后指纹、旧模块阻断与双侧独立
│  │  ├─ test_execution.py                                               # 管理配置校验、独立 Scope 与默认关闭
│  │  ├─ test_service.py                                                 # 无 Web 的执行、冻结、取消、路径及依赖边界
│  │  ├─ test_streaming_config.py                                        # Streaming 本地试用、类型/预算与独立范围
│  │  └─ test_streaming_qualification.py                                 # 计划授权、正式管理链路、来源/报告与安全预览
│  ├─ __init__.py                                                        # 无启动 I/O 的包标记
│  ├─ bindings.py                                                        # Monitoring 单次捕获与 Knowledge 绑定
│  ├─ contracts.py                                                       # Web Protocol、共享 DTO 导出
│  ├─ execution.py                                                       # 请求上下文、取消及 Deadline
│  ├─ service.py                                                         # 唯一ManagementAssistantService业务装配
│  └─ streaming.py                                                       # 请求内 SSE 投递、worker 生命周期与断线清理
├─ docs/                                                                 # 实际目录
│  ├─ deep-dive/                                                         # 实际目录
│  │  ├─ model/                                                          # 实际目录
│  │  ├─ research/                                                       # 实际目录
│  │  │  ├─ R2B3_MANAGEMENT_AI_ARCHITECTURE_REVIEW.md                    # 当前架构、参数故障证据与路线建议
│  │  │  ├─ R2B5_MANAGEMENT_ASSISTANT_STREAMING_INTEGRATION.md           # Streaming 设计与实施状态
│  │  │  ├─ R2B_DOMAIN_ANALYSIS_AND_AI_INTEGRATION.md                    # R2B-0 评估基线，非实现现状
│  │  │  ├─ R2C1A_LLM_BACKEND_AUDIT.md                                   # 独立化审计基线
│  │  │  └─ R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md                      # 获批分叉方案与 Phase I 实施记录
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
│  │  ├─ assistant.js                                                    # 双模式聊天、临时预览、History、Stop、滚动和问题导航
│  │  ├─ components.js                                                   # 安全文本、卡片、表格、图表
│  │  ├─ index.html                                                      # 布局、来源标识和弹窗
│  │  ├─ services.js                                                     # 同源监测与受控 Assistant API
│  │  ├─ styles.css                                                      # 样式与响应式布局
│  │  └─ view-model.js                                                   # 展示转换、来源和状态
│  ├─ tests/                                                             # 离线测试及Fake SDK
│  │  ├─ assistant-events.test.mjs                                       # SSE 分片、重复/乱序、身份、终态与有界拒绝
│  │  ├─ assistant-fixture.mjs                                           # 共用离线聊天 DOM/API 夹具
│  │  ├─ assistant-stream-fixture.mjs                                    # 安全事件与碎片化读流夹具
│  │  ├─ assistant-stream-ui.test.mjs                                    # Streaming 会话、撤销、History 与滚动/导航
│  │  ├─ assistant-transport.test.mjs                                    # 正式 fetch 路由、确认、AbortSignal 与取消
│  │  ├─ assistant-ui.test.mjs                                           # Normal 聊天、History、epoch 与 Stop 行为
│  │  ├─ chart-fixture.mjs                                               # 固定多次重启、20 小时时间跨度数据
│  │  ├─ chart-ui.test.mjs                                               # 时间坐标、重复/缺口、精度和 SVG
│  │  ├─ dom-fixture.mjs                                                 # 无网络 DOM 测试辅助
│  │  ├─ monitoring-ui.test.mjs                                          # 实际页面代码的离线 DOM 行为
│  │  ├─ stream-browser-bridge.mjs                                       # 实际管理 SSE 到前端解析/提交的 Node 桥
│  │  ├─ test_ai_boundary.py                                             # Web 访问控制、令牌隔离、同一 Handle 与显式装配门禁
│  │  ├─ test_app.py                                                     # R1 兼容、API 和安全
│  │  ├─ test_assistant.py                                               # Fake Provider HTTP 闭环、同源数据、Ledger 与取消
│  │  ├─ test_knowledge.py                                               # Knowledge HTTP 闭环、授权/来源隔离、拒绝与确认指纹
│  │  ├─ test_multi_round.py                                             # HTTP 双 Tool、Scope/revision、预算、取消与回滚
│  │  ├─ test_streaming.py                                               # Fake SDK HTTP/SSE、安全门禁及真实事件到前端的桥接
│  │  └─ view-model.test.mjs                                             # 纯展示合同
│  ├─ README.md                                                          # 快速入口
│  ├─ __init__.py                                                        # 无启动 I/O 的包标记
│  ├─ __main__.py                                                        # 本机启动、存储装配与写入开关
│  ├─ ai_adapter.py                                                      # Web 薄门面：浏览器令牌、RequestRegistry 与业务合同委托
│  ├─ app.py                                                             # HTTP、访问控制与服务装配
│  ├─ contracts.py                                                       # Web Protocol、共享 DTO 导出
│  ├─ package.json                                                       # Node 原生测试，无依赖
│  ├─ services.py                                                        # R1 兼容 Demo、未接入 AI/文件服务
│  └─ streaming.py                                                       # 请求内 SSE 投递、worker 生命周期与断线清理
├─ monitoring/                                                           # Web 与未来 Tool 共享的数据基础
│  ├─ tests/                                                             # 离线测试及Fake SDK
│  │  ├─ test_business_services.py                                       # 纯服务一致性、设备/时间边界与故障回滚
│  │  ├─ test_history_projection.py                                      # 历史 API 排序、会话与旧元数据兼容
│  │  ├─ test_local_http.py                                              # 真实 loopback 上报及停止/重启
│  │  ├─ test_pipeline.py                                                # 校验、时序、安全、状态与共享来源
│  │  ├─ test_rule_governance.py                                         # 规则状态、证据范围、可靠恢复与兼容
│  │  └─ test_water_capture.py                                           # 单次读取/诊断、双投影一致性、质量语义和 DTO 大小
│  ├─ __init__.py                                                        # 无启动 I/O 的包标记
│  ├─ analysis.py                                                        # 纯领域求值、单次水质捕获与 canonical Reading 投影
│  ├─ contracts.py                                                       # v1 上报校验、监测事实与分析 DTO
│  ├─ events.py                                                          # 纯 EventService、事件变更及只读状态投影
│  ├─ repository.py                                                      # SQLite、事务、历史与事件变更持久化
│  ├─ rules.py                                                           # 纯评估函数、证据门禁与 PROTOTYPE 规则投影
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
    → 新Registry/Policy/Executor → ai_service.bindings → Monitoring / Knowledge
    → 新Steps / EventChannel / SafeTrace → Web临时Preview或唯一Final
```

Backend无fishery_ai/Flask/SQLite/业务反向依赖。Monitoring/Knowledge及业务sources保留旧领域合同/资源，连带旧model_options；它们不调用旧LLM Runtime。旧Prototype独立，管理单个Turn只用新ContextVar/Handle/Registry/Adapter。

Phase I的runtime/assembly、contracts、bindings、execution、streaming五个准备模块已合并回顶层实际实现，三份重复测试已移除；无alias/fallback。R2C-1E 已完成迁移收尾及用户基本网页验收；依赖核对、证据边界和回滚见 [收尾记录](deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md#15-r2c-1e-工程收尾与人工验收)。

测试层级：FAST小集合；backend为新Backend及业务合同；FULL PRODUCT含backend一次；FULL QUALIFICATION额外包含管理资格17项；Web/Node按BUILD_RUN运行。Qualification只在显式开发入口加载，默认dry-run，无批次或自动Provider请求。

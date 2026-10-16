# 管理平台目录与职责

当前实际结构；缓存不展开。完整仓库见根 [地图](../../docs/STRUCTURE.md)。

```text
apps/
├─ AGENTS.md                         # 管理工程与安全规则
├─ __init__.py                       # 应用命名空间
├─ docs/
│  ├─ README.md                      # 当前状态与文档入口
│  ├─ STRUCTURE.md                   # 真实目录与职责
│  ├─ BUILD_RUN.md                   # 启动、联调与验证
│  ├─ INTEGRATION.md                 # 上报合同和替换边界
│  ├─ ROADMAP.md                     # 当前状态与后续工作
│  └─ deep-dive/
│     ├─ STREAMING_QUALIFICATION.md   # 单案例批准、脱敏报告、人工预览及试用/回滚
│     └─ research/
│        ├─ R2B_DOMAIN_ANALYSIS_AND_AI_INTEGRATION.md # R2B-0 评估基线，非实现现状
│        ├─ R2B5_MANAGEMENT_ASSISTANT_STREAMING_INTEGRATION.md # Streaming 设计与实施状态
│        ├─ R2B3_MANAGEMENT_AI_ARCHITECTURE_REVIEW.md # 当前架构、参数故障证据与路线建议
│        └─ R2C1A_LLM_BACKEND_AUDIT.md # 通用后端依赖审计、最小迁移与兼容计划
├─ ai_backend/                      # 已迁入的通用 LLM 基础，不依赖旧 Runtime
│  ├─ __init__.py                    # 无 I/O 的包标记
│  ├─ README.md                      # 公共接口、当前范围与迁移边界
│  └─ tool_argument_diagnostics.py   # 参数拒因、阶段、有界计数与安全投影唯一实现
├─ ai_service/                      # 独立 AI 业务包（同进程，无新端口）
│  ├─ __init__.py                    # 包标识，不自动创建业务实例
│  ├─ contracts.py                   # AssistantBackend 与服务器内 PreparedAssistantTurn
│  ├─ service.py                     # 业务校验、冻结配置、凭据/Runtime 装配及正式 Assistant 调用
│  ├─ bindings.py                    # Monitoring 水质 DTO、原 Knowledge Handler 与静态绑定
│  ├─ execution.py                   # 管理专用精确 Scope、冻结开关与确认 revision
│  ├─ streaming.py                   # 管理独立 Streaming 配置、精确 Scope 与确认
│  ├─ development/                   # 显式开发入口，不由正式 Runtime 导入
│  │  ├─ __init__.py                 # 惰性 development 边界
│  │  └─ streaming_qualification.py  # 管理单案例资格、隔离 SQLite 与安全观察
│  ├─ resources/
│  │  ├─ assistant_streaming.json     # Qwen 两工具 local_experimental，默认关闭
│  │  └─ assistant_execution.json    # Qwen/Ollama 独立本地实验 Scope，默认关闭
│  └─ tests/
│     ├─ __init__.py
│     ├─ test_service.py             # 无 Web 的执行、冻结、取消、路径及依赖边界
│     ├─ test_streaming_config.py    # Streaming 本地试用、类型/预算与独立范围
│     ├─ test_streaming_qualification.py # 计划授权、正式管理链路、来源/报告与安全预览
│     └─ test_execution.py           # 管理配置校验、独立 Scope 与默认关闭
├─ monitoring/                      # Web 与未来 Tool 共享的数据基础
│  ├─ __init__.py
│  ├─ contracts.py                   # 上报、WaterMetricFact/WaterCapture、质量/Finding/Event 合同
│  ├─ analysis.py                    # 纯领域求值、单次水质捕获与 canonical Reading 投影
│  ├─ rules.py                       # 纯评估函数、证据门禁与 PROTOTYPE 规则投影
│  ├─ events.py                      # 纯 EventService、事件变更及只读状态投影
│  ├─ repository.py                  # SQLite、事务、历史与事件变更持久化
│  ├─ service.py                     # current-only 捕获、Web snapshot 投影与设备绑定
│  └─ tests/
│     ├─ test_pipeline.py            # 校验、时序、安全、状态与共享来源
│     ├─ test_rule_governance.py      # 规则状态、证据范围、可靠恢复与兼容
│     ├─ test_business_services.py    # 纯服务一致性、设备/时间边界与故障回滚
│     ├─ test_history_projection.py  # 历史 API 排序、会话与旧元数据兼容
│     ├─ test_water_capture.py        # 单次读取/诊断、双投影一致性、质量语义和 DTO 大小
│     └─ test_local_http.py          # 真实 loopback 上报及停止/重启
├─ simulator/                       # 独立设备生产端
│  ├─ __init__.py
│  ├─ __main__.py                    # 实时调度、离线推进与清理
│  ├─ scenarios.py                   # 手写 Phase 时间线
│  ├─ generator.py                   # 确定性水质/视觉窗口生成
│  ├─ transport.py                   # 受控 HTTP 上报，无重试/重定向
│  └─ tests/
│     └─ test_simulator.py           # Seed、采样、场景、调度与清理
└─ management_web/                  # 管理页面与 Web 专属后端
   ├─ __init__.py
   ├─ __main__.py                    # 本机启动、存储装配与写入开关
   ├─ README.md                      # 快速入口
   ├─ app.py                         # HTTP、访问控制与服务装配
   ├─ streaming.py                   # 请求内 SSE 投递、worker 生命周期与断线清理
   ├─ ai_adapter.py                  # Web 薄门面：浏览器令牌、RequestRegistry 与业务合同委托
   ├─ contracts.py                   # Web Protocol、共享 DTO 导出
   ├─ services.py                    # R1 兼容 Demo、未接入 AI/文件服务
   ├─ package.json                   # Node 原生测试，无依赖
   ├─ static/
   │  ├─ index.html                  # 布局、来源标识和弹窗
   │  ├─ styles.css                  # 样式与响应式布局
   │  ├─ app.js                      # 七页面路由与监测 5 秒轮询
   │  ├─ assistant.js                # 双模式聊天、临时预览、History、Stop、滚动和问题导航
   │  ├─ assistant-events.js         # 有界 POST SSE、序号/身份/终态校验与流清理
   │  ├─ components.js               # 安全文本、卡片、表格、图表
   │  ├─ view-model.js               # 展示转换、来源和状态
   │  └─ services.js                 # 同源监测与受控 Assistant API
   └─ tests/
      ├─ test_app.py                 # R1 兼容、API 和安全
      ├─ test_ai_boundary.py         # Web 访问控制、令牌隔离、同一 Handle 与显式装配门禁
      ├─ test_assistant.py           # Fake Provider HTTP 闭环、同源数据、Ledger 与取消
      ├─ test_streaming.py           # Fake SDK HTTP/SSE、安全门禁及真实事件到前端的桥接
      ├─ test_multi_round.py         # HTTP 双 Tool、Scope/revision、预算、取消与回滚
      ├─ test_knowledge.py           # Knowledge HTTP 闭环、授权/来源隔离、拒绝与确认指纹
      ├─ assistant-ui.test.mjs       # Normal 聊天、History、epoch 与 Stop 行为
      ├─ assistant-events.test.mjs   # SSE 分片、重复/乱序、身份、终态与有界拒绝
      ├─ assistant-stream-ui.test.mjs # Streaming 会话、撤销、History 与滚动/导航
      ├─ assistant-transport.test.mjs # 正式 fetch 路由、确认、AbortSignal 与取消
      ├─ assistant-fixture.mjs       # 共用离线聊天 DOM/API 夹具
      ├─ assistant-stream-fixture.mjs # 安全事件与碎片化读流夹具
      ├─ stream-browser-bridge.mjs   # 实际管理 SSE 到前端解析/提交的 Node 桥
      ├─ chart-fixture.mjs            # 固定多次重启、20 小时时间跨度数据
      ├─ chart-ui.test.mjs            # 时间坐标、重复/缺口、精度和 SVG
      ├─ dom-fixture.mjs            # 无网络 DOM 测试辅助
      ├─ view-model.test.mjs          # 纯展示合同
      └─ monitoring-ui.test.mjs       # 实际页面代码的离线 DOM 行为
```

## 依赖与生命周期

```text
Simulator scenarios → generator → HTTP reporter
    → Web Ingestion（鉴权）
    → monitoring contracts（验证）→ repository（事务存储）
    → MonitoringService → DomainAnalysisService → rules → 复用 Domain 阈值 → Findings
        → Repository 事务：读取旧阶段 → EventService → 持久化变更
        → Dashboard / Monitoring / Video / Events
        → ManagementToolRegistry（水质绑定）→ ToolExecutor → AssistantService

原 KnowledgeService → 原 Registry/Handler → ManagementToolRegistry（Knowledge 绑定）
        → 同一个 ToolExecutor / AssistantService（每 Turn 择一 Tool）

MonitoringService → 已有 Domain / Diagnosis / CurrentWaterQualityReader
management_web API / ManagementAssistant（HTTP/令牌/请求控制）
    → ai_service.AssistantBackend 合同
    → ManagementAssistantService（校验/冻结/Runtime 装配）
    → src/fishery_ai AssistantService / ToolCallingService / Gateway / CredentialSnapshot
```

模拟器不导入服务器存储或网页变量。共享 monitoring 不依赖 Flask 或网页组件；水质 DTO 只有一个定义，Web 兼容导出。SQLite 连接按操作关闭，生成器与 HTTP 生命周期分离，页面轮询不触发采样或写入。

DomainAnalysisService 与 EventService 不导入 Repository/Flask。Repository 只应用 EventChanges，规则/生命周期判断不再埋入 SQL。MonitoringService.capture_water() 只读一次 current，得到 frozen WaterCapture（指标/canonical Reading/同批次分析）；Assistant 投影不再借用 Web snapshot 或查询趋势。Web snapshot() 保留 current+history 事务和原 DTO，与 Tool 共用纯捕获实现，不二次诊断、不跨通道融合。

页面负责交互与展示；API 负责输入/访问控制；服务负责用例和状态；Adapter 负责接入差异。七页路由在 static/app.js，独立 Assistant Session 在 static/assistant.js。ai_adapter.py 只把业务字段交给 ai_service 的 prepare_turn，再把冻结结果与 Web 管理的同一个 RequestHandle 交给 execute_turn；业务包不持有浏览器/控制令牌、不创建 RequestRegistry，不复制执行循环、Prompt 或 History Projection。

管理 Registry 只装配水质与项目 Knowledge，两者经原 Assistant Policy 求交。Knowledge 是项目背景 Evidence，不认证当前现场；未装配的评分不可执行。既有默认仍只授权水质，管理 API 不新增授权写入口。

Normal Multi-Round 的管理专用 Scope/Flag/revision 归 ai_service.execution，service 冻结 ExecutionDecision 并装配正式 Prompt/History/预算；复用核心 ToolCallingService。默认 1/1/2，显式本地试用且匹配精确 Scope 后才为 2/2/3。Streaming 的业务模式也在 ai_service 装配，HTTP SSE/断线/重连归 management_web，Provider delta 归原 Runtime Adapter。新视觉/历史 Tool 的管理数据绑定归 ai_service.bindings、事实/判断归 Monitoring；新 RAG 的服务装配入口归 ai_service，检索实现不写进 Web 或本业务协调器。出现实际需求再拆领域文件，不提前建空框架。

Runtime/Core 为共享领域与 AI 包；Development 为模拟器和测试；Generated 为 Git ignored 的 outputs/management_web/（SQLite、脱敏 Assistant Trace）；User-private 为已有凭据目录，管理前端不可接触。可显式启用 Qwen/Ollama Normal；Qwen 精确两工具 Streaming 已获本地实验授权，启动参数 --assistant-streaming-trial 进程内启用、默认关闭，非 released。真实设备、NPU、文件索引和固定 Analysis 尚未开放。

资格 CLI 位于 `scripts/qualification/qualify_management_streaming.py`；只导入 `ai_service.development` 并复用共享资格 Adapter/观察器。报告在 Git ignored 的 `outputs/assistant-qualification/`，临时夹具在其 `.management-work/` 下结束清理；不导入原型 Snapshot，不读取管理生产库或用户 Policy。

R2C-1A 的 ai_backend 目前只提供参数诊断模块，旧 `fishery_ai.tool_argument_diagnostics` 单向别名到同一实现。Gateway/执行控制/History/Tool 循环尚未迁移；完整现状与目标图见 [后端审计](deep-dive/research/R2C1A_LLM_BACKEND_AUDIT.md)。边界测试在根 `tests/tools/test_backend_boundary.py`，纳入既有产品发现；根安装清单同时包含该 Backend，不发布其余管理模块。

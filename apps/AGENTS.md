# 管理平台开发规则

本文件适用于 `apps/`，同时遵守根目录 AGENTS.md。[主要文档入口](docs/README.md)。

- `apps/monitoring/` 是共享数据合同、存储与读取服务；`apps/simulator/` 是独立生产端，只经受控 HTTP 上报，不直接写服务器状态。模拟源不可由客户端声明为真实设备。

- `apps/management_web/` 放页面、HTTP/浏览器访问控制与请求控制；`apps/ai_service/` 放 AI 业务协调、Runtime 装配和数据 Tool 绑定。AI service 不导入 Flask/Web，Monitoring 不反向依赖 AI service。当前 `ManagementAssistantService`、Web/SSE、管理资格入口统一使用 `apps.ai_backend`；`ai_service/runtime/` 只保留业务 Assistant、来源/Prompt/Policy/Preset 与发布计算。禁止逐请求新旧选择器、fallback 和长期转发 Facade。
- `apps/ai_backend/` 是获批 R2C-1B 一次性选择性分叉的通用 LLM Backend；禁止导入 `fishery_ai`、AI service、Web、Monitoring、Knowledge 或 SQLite。目标为 Web → AI service → Backend，业务 Prompt、Tool/Policy、Preset/发布配置、Receipt/Ledger/Commit Gate 留服务层。Prototype 保留独立实现，不使用新旧 Alias/Facade；单个 Turn 只能使用一套新类型、ContextVar、Handle、Registry、循环和取消状态。不得自动回退旧 Runtime。
- 分叉允许新旧平台后续独立演进，不建立自动同步；管理端内部仍禁止复制第二个 Gateway、Tool 循环、Assembler 或执行状态。迁移要检查协议/提交差分、安装清单与 Scope 指纹；旧真实资格不能改写为新 Backend 的真实运行记录。Monitoring 自有 water_contracts / diagnosis / current；正式管理链禁止导入旧 fishery_ai，历史资格、显式迁移及差分测试的资源依赖单独列账。
- 页面负责交互，组件负责展示，应用服务负责用例，Adapter 负责设备、数据库或 Runtime 接入；HTTP 路由保持薄。先使用现有结构，只有出现实际消费者时才拆文件，不建空框架或动态插件。
- 业务 Tool 放在 `apps/ai_service/business_tools/`，一个 Tool 模块拥有 Definition/参数校验/Handler/有限 DTO；只由 registry.py 显式装配，不扫描模块。Policy、来源 Ledger 和 Activity 留 runtime；评分兼容名称不产生可执行 Handler，不为旧 tools/bindings 路径增加转发层。
- 接口用明确 DTO、版本和安全错误表达。值、单位、来源、观测时间、质量、新鲜度不可丢失；缺失不补 0、不回退 Demo。Protocol 类型声明不等于运行时校验。
- 网页与 AI Tool 的当前事实必须来自同一权威监测来源；不能各自维护一份 current state。多设备选择须有明确、冻结的上下文，不能依赖可变全局选择。新鲜度与诊断复用 Domain 规则，前端不复制阈值。
- Demo、真实观测、推理结果、实验评分和背景知识必须区分。文件管理、索引、检索分离；视频传输、NPU 推理与页面展示分离。
- Secret 不读取、输出、记录或传入页面，不存 localStorage。接入 AI 时复用正式私有凭据 composition；禁止源码根 `.env`、fallback、load_dotenv，Flask 启动保持 `load_dotenv=False`。
- Tool 继续按 Policy / Registry / Executor 执行；Source Ledger、Commit Gate、预算、Deadline、Stop、发布 Scope 与逐次网络确认不得绕过。预览不作为成功回答或 History。
- 当前本机展示边界不是生产鉴权。禁用或隐藏按钮不提供权限保护；新增写 API、文件访问或 AI 执行前补服务端安全检查。管理员操作与开发调试入口分开，禁止未经授权的设备、数据库和阈值修改。
- 行为变更补离线 Python / Node 测试和中文文档；UI 变更检查导航、空状态和响应式布局。相关 Runtime 桥接还须运行对应原型回归。真实请求须本轮明确授权，禁止测试自动调用 Provider / Ollama。
- `apps/docs/` 描述管理平台及独立 Backend 当前状态；根 `docs/` 描述旧 AI Prototype 实验平台。两侧 Runtime 与领域实现独立演进，不要求自动同步；管理端水质阈值仅在 monitoring/diagnosis.py 定义，rules.py 负责证据门禁，不复制阈值。以源码、测试为事实，规划明确标为未实现。保护未提交改动，不修改 `D:\Fishery_Project` 或工作区外文件。

- 管理知识文本仅由 `apps/knowledge_data/knowledge.sqlite3` 权威存储（Git忽略/不打包），`apps/knowledge/` 放程序。旧JSON只供显式备份迁移和隔离资格夹具，正常管理链不再导入旧Knowledge/Evidence；不将实际用户库迁移夹带进启动。知识写操作不是LLM Tool，原始来源与编辑版本分离。

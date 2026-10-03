# 项目结构

本文件登记主要文件与目录的作用。行数随 V0.1.1-A1 持续变化，不作为架构合同。

## 三种模型访问入口

包内 `resources/web/index.html`、`app.js`、`app.css` 将 Preset 模型与 Variant 分开，Managed Custom 独占 CRUD，Manual Expert 使用独立 Raw JSON 面板。当前新发布 Qwen 3.8 Flash、DeepSeek Flash、Ollama Qwen3.5 4B；Mock 放在 Development / Test。Clean-room 前 Built-in 与合同只在显式历史 fixture / 归档中保留，不在正常启动时恢复。详见[当前发布报告](deep-dive/PRESET_SIMPLIFICATION_AND_FIRST_PUBLICATION.md)；[界面整理报告](deep-dive/MODEL_SELECTION_UI_THREE_MODE_CLEANUP.md)保留历史。

## Preset / R6 / R7 新增模块

| 文件 | 作用 |
|---|---|
| `presets.py` / `resources/profiles/presets.json` | 项目维护的固定 Template / Variant 与版本化合同，发布入口不加载本地 Evidence；已发布三个精确模型，各三种组合 |
| `execution.py` | 本地单进程 RequestHandle、控制令牌、状态与取消上下文 |
| `manual.py` | 独立 Raw JSON 请求及原始结果合同，无水质业务或 Capability 判断 |
| `openai_compatible_adapter.py` | 保留原编码；新增 AsyncOpenAI bridge，实际取消 SDK await、关闭流和 client，Manual passthrough 共用安全传输 |
| `scripts/validate_access_modes.py` | 显式授权的有界 smoke，复用 R2 私有凭据 composition；默认不读凭据、不联网 |
| `tests/test_preset.py` / `test_execution.py` / `test_access_web.py` / `test_access_validation.py` | 固定合同、取消、Manual 隔离和真实入口离线保护 |

范围、实测阻塞与使用限制见 [阶段报告](deep-dive/PRESET_CANCELLATION_MANUAL_IMPLEMENTATION.md)。下方保留既有文件登记，不将历史说明作为当前能力合同。

## 1. 目录树（每项末尾为该条目作用）

```text
Fishery_AI_Prototype/
├─ README.md                      # 项目定位、V0.1 已实现/范围外、与其他项目的关系、命令速查
├─ AGENTS.md                      # AI 协作约定：生产项目只读、测试必须离线、文档用中文、禁止自动发起付费 LLM 调用
├─ pyproject.toml                 # 包元数据 + 运行依赖(openai/httpx/python-dotenv/Flask) + 包内资源声明
├─ .gitignore                     # 忽略 .venv/、.env、outputs/、*.egg-info/、build/、模型权重(*.pt 等)
├─ .venv/                         # 本地虚拟环境（不入库）
├─ src/
│  └─ fishery_ai/
│     ├─ __init__.py              # 包标识与 __version__ = "0.1.0"
│     ├─ __main__.py              # CLI 入口：demo、validate-real、web；demo 覆写 socket 阻断联网
│     ├─ composition.py           # 装配根：把 Mock 仓库/诊断/检索/Profile/MockGateway/Trace 组装成 Orchestrator
│     ├─ application.py           # 编排：冻结 Profile → 取水质 → 诊断 → 检索 → 拼 prompt → 调网关 → 解析 → 落 Trace
│     ├─ contracts.py             # 领域/结果合同；Usage 来源与字段、内存 UsageAccumulator
│     ├─ domain.py                # 确定性水质诊断：11 条阈值规则，每指标只输出最严重的一条
│     ├─ knowledge.py             # 知识分块(31 块) + TF-IDF 检索 + 证据构建；三后端 portable/sklearn/keyword
│     ├─ model_gateway.py         # Profile 分类/身份、精确模型快照、请求/响应、Gateway 与 MockGateway
│     ├─ model_options.py         # 生成/思考选项、三态能力与严格校验
│     ├─ providers.py             # 静态 ProviderRegistry 与 AuthSpec
│     ├─ credentials.py           # 只读 CredentialStore、私有不可变快照、随机凭据 generation
│     ├─ credential_paths.py      # 启动边界的每项目用户私有路径及存储权限校验
│     ├─ project_env.py           # 固定所选凭据文件的安全 CRUD、文本保留、revision 与回滚
│     ├─ secure_files.py          # Windows ACL、安全暂存、跨进程锁与同卷原子替换
│     ├─ web_security.py          # 本地 Host / Origin、会话 CSRF 与浏览器安全响应头
│     ├─ openai_compatible_adapter.py  # 唯一直接 import openai 的文件：选项翻译、Usage 映射、重试与流式响应
│     ├─ real_validation.py      # 仅显式入口使用：私有凭据文件、单项受控 Cloud 检查与脱敏输出
│     ├─ web.py                  # 本地开发验证 UI：薄 Flask 路由，复用现有 Orchestrator
│     ├─ observability.py         # 白名单 JSONL Trace（不落 Key、不落 prompt、不落模型正文）
│     ├─ repositories.py          # 从 scenarios.json 读取固定 Mock 水质与检测输入
│     └─ resources/
│        ├─ knowledge/
│        │  ├─ eel_knowledge.json # ★ RAG 参考数据快照（源自生产 commit c400b7a，31 个知识块）
│        │  └─ SOURCE.md          # 该快照的来源、commit、SHA-256 溯源说明
│        ├─ mock/
│           ├─ scenarios.json     # 固定输入：5 个水质场景 + 2 组检测场景
│           └─ profiles.json      # 仅供 Mock 演示的 EXPERIMENTAL/CUSTOM Profile；没有真实 VERIFIED 预设
│        ├─ profiles/
│           ├─ deepseek_experimental.json # DeepSeek 实验 Profile，无 Key
│           └─ qwen_experimental.json     # Qwen 实验 Profile，无 Key
│        └─ web/                  # 包内 HTML/CSS/JS；无需前端构建工具
├─ tests/
│  ├─ test_v01.py                 # V0.1 离线回归：合同/诊断/检索/网关/编排/Trace
│  ├─ test_v011_a1.py             # A1 离线测试：状态、能力、参数映射、Usage、安全与网络阻断
│  ├─ test_v011_a2.py             # A2 真实入口的离线假网关测试；不读取 .env
│  ├─ test_v011_a2_1.py           # A2.1 能力和安全错误分类离线测试
│  ├─ test_credential_writer.py   # R2 临时私有 .env、CRUD、权限、回滚、Web 安全与轮换缓存
│  └─ test_v011_a3_web.py         # A3 Flask 客户端、Mock/Cloud 路由与安全边界离线测试
├─ scripts/
│  └─ run_mock_demo.py            # 未安装包时从源码直接跑 demo 的薄包装
├─ docs/
│  ├─ README.md                   # 文档导航（先读哪些、各自用途）
│  ├─ BUILD_RUN.md                # 环境准备、离线测试、Mock 演示的可照抄命令
│  ├─ STRUCTURE.md                # 本文件：文件与目录登记表
│  ├─ ROADMAP.md                  # V0.1 已完成 / V0.1.1 真实运行时验证 / V0.2 Tool Calling / 远期研究
│  ├─ TROUBLESHOOTING.md          # 已知限制与初步排查方向（真实服务、本地部署、流式、知识来源、依赖）
│  ├─ CODE_REVIEW.md              # 代码评审记录模板（当前空白）
│  └─ deep-dive/
│     ├─ README.md                              # 深度文档索引
│     ├─ V0.1_IMPLEMENTATION_REPORT.md          # 第一轮实现记录（描述写作时状态）
│     ├─ V0.1_HARDENING_REPORT.md               # SDK 接管、打包迁移、数据合同加固记录
│     ├─ V0.1.1_LOCAL_RUNTIME_VALIDATION.md     # 真实本地/云模型验证计划与验收标准（尚未执行）
│     ├─ MULTI_MODEL_PARAMETER_ARCHITECTURE_PLAN.md # 多模型架构评审计划（历史决策依据）
│     ├─ V0.1.1_A1_MULTI_MODEL_IMPLEMENTATION_REPORT.md # A1 实施范围、测试与待决策事项
│     ├─ V0.1.1_A2_DEEPSEEK_VALIDATION_REPORT.md # A2 部分真实验证、失败与后续清单
│     └─ V0.1.1_A3_0_DEVELOPER_WEB_UI.md # 开发验证 UI 架构、使用和限制
├─ data/                          # 空目录残留：资源已迁入包内 resources/，此目录可删（git 不跟踪空目录）
│  ├─ knowledge/
│  └─ mock/
└─ outputs/                       # 运行产物（.gitignore，不入库）
   ├─ mock-traces.jsonl           # 每次运行 demo 追加的 Trace
   └─ package-check/              # wheel 打包检查产物（含 .whl 副本与其自测输出）
```

## 2. 模块关键符号速查

| 文件 | 主要符号 | 说明 |
|---|---|---|
| `contracts.py` | `WaterQualityReading`、`Detection`/`DetectionEvent`/`DetectionSummary`、`ObservedFacts`、`RuleFinding`、`KnowledgeEvidence`、`Usage`/`UsageSource`/`UsageAccumulator`、`RuntimeInfo`、`AnalysisRequest`、`AnalysisResult`、`Quality`/`Freshness`/`Mode`/`Status` | 领域与结果合同；Usage 缺失保持未知，会话累计不持久化 |
| `domain.py` | `DiagnosisService.diagnose()`、`RULE_VERSION` | 纯函数式诊断，不依赖模型与网络 |
| `knowledge.py` | `chunk_knowledge()`、`KnowledgeService.search()`、`_PortableTfidf`、`EXPANSIONS` | 兼容生产块 ID、扩展词与 0.04 门槛 |
| `model_gateway.py` | `ModelProfile`、`ProfileRegistry`、`RuntimeSnapshot`、`ModelRequest`/`ModelResponse`/`ModelEvent`、`ModelGateway`、`MockGateway`、`GatewayError`/`RetryableGatewayError` | Provider/协议/模型/部署身份分开；`RuntimeSnapshot` 不可变且 `api_key` 不出现在 `repr` |
| `model_options.py` | `ProfileStatus`、`Support`、`GenerationOptions`、`ReasoningOptions`、`ModelCapabilities`、`validate_options()` | 显式高级选项严格校验；能力绑定当前精确模型 |
| `credentials.py` | `CredentialStore.resolve()`、`CredentialSnapshot` | 外部环境优先，每个请求重新读取，已有快照保持原值；只缓存不可逆内部标识和随机 generation |
| `project_env.py` | `ProjectEnvWriter.inspect()/.mutate()`、`edit_env()` | 固定路径、原始文本片段编辑、revision 冲突、私有暂存与失败回滚 |
| `web_security.py` | `install_local_security()` | Host 白名单、同源 Origin、当前会话 CSRF、无 CORS |
| `openai_compatible_adapter.py` | `OpenAICompatibleAdapter.complete()/.stream()`、`RETRYABLE_STATUS` | SDK 自动重试关闭；能力验证后映射标准/受控 Provider 字段；正文已输出后不再重试 |
| `real_validation.py` | `run_real_validation()` | 仅显式确认后读取所选私有凭据；一项检查对应最多一次 SDK 请求尝试，输出脱敏结果 |
| `application.py` | `Orchestrator.analyze()`、`_build_model_request()`、`_parse_model_text()`、`result_to_dict()` | Chat/Advice 共用同一构建路径，仅任务句与 top_k 不同 |
| `observability.py` | `JsonlTraceSink.record()` | 显式字段白名单，附带线程锁 |

## 3. 数据流

```text
MockRepository(水质) → DiagnosisService(规则) → KnowledgeService(证据)
        ↓                                              ↓
        └─────────── Orchestrator 组装 prompt ─────────┘
                              ↓
                    ModelGateway 合同
                    ├── MockGateway（默认，离线）
                    └── ModelCapabilities 校验 → OpenAICompatibleAdapter → OpenAI 兼容服务
                              ↓
              AnalysisResult + JsonlTraceSink(白名单字段)
```

## 4. 当前尚未存在的模块

Agent Loop、Tool Calling、Memory、向量数据库、生产项目适配器、YOLO/Detection 接入编排、应用层流式接口（网关的 `stream()` 已实现但编排只用 `complete()`）、真实模型部署、自动跨 Provider failover 与费用计算。

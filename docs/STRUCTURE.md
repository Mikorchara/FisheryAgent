# 项目结构

本文件登记主要文件与目录的作用。行数随 V0.1.1-A1 持续变化，不作为架构合同。

## 1. 目录树（每项末尾为该条目作用）

```text
Fishery_AI_Prototype/
├─ README.md                      # 项目定位、V0.1 已实现/范围外、与其他项目的关系、命令速查
├─ AGENTS.md                      # AI 协作约定：生产项目只读、测试必须离线、文档用中文、禁止自动发起付费 LLM 调用
├─ pyproject.toml                 # 包元数据 + 运行依赖(openai/httpx/python-dotenv) + 包内资源声明
├─ .env.example                   # 环境变量模板，仅 DEEPSEEK_API_KEY 空占位；真实 Key 不入库
├─ .gitignore                     # 忽略 .venv/、.env、outputs/、*.egg-info/、build/、模型权重(*.pt 等)
├─ .venv/                         # 本地虚拟环境（不入库）
├─ src/
│  └─ fishery_ai/
│     ├─ __init__.py              # 包标识与 __version__ = "0.1.0"
│     ├─ __main__.py              # CLI 入口：离线 demo 与显式 validate-real；demo 覆写 socket 阻断联网
│     ├─ composition.py           # 装配根：把 Mock 仓库/诊断/检索/Profile/MockGateway/Trace 组装成 Orchestrator
│     ├─ application.py           # 编排：冻结 Profile → 取水质 → 诊断 → 检索 → 拼 prompt → 调网关 → 解析 → 落 Trace
│     ├─ contracts.py             # 领域/结果合同；Usage 来源与字段、内存 UsageAccumulator
│     ├─ domain.py                # 确定性水质诊断：11 条阈值规则，每指标只输出最严重的一条
│     ├─ knowledge.py             # 知识分块(31 块) + TF-IDF 检索 + 证据构建；三后端 portable/sklearn/keyword
│     ├─ model_gateway.py         # Profile 分类/身份、精确模型快照、请求/响应、Gateway 与 MockGateway
│     ├─ model_options.py         # 生成/思考选项、三态能力与严格校验
│     ├─ openai_compatible_adapter.py  # 唯一直接 import openai 的文件：选项翻译、Usage 映射、重试与流式响应
│     ├─ real_validation.py      # 仅显式入口使用：加载 .env、单项受控 Cloud 检查与脱敏输出
│     ├─ observability.py         # 白名单 JSONL Trace（不落 Key、不落 prompt、不落模型正文）
│     ├─ repositories.py          # 从 scenarios.json 读取固定 Mock 水质与检测输入
│     └─ resources/
│        ├─ knowledge/
│        │  ├─ eel_knowledge.json # ★ RAG 参考数据快照（源自生产 commit c400b7a，31 个知识块）
│        │  └─ SOURCE.md          # 该快照的来源、commit、SHA-256 溯源说明
│        ├─ mock/
│           ├─ scenarios.json     # 固定输入：5 个水质场景 + 2 组检测场景
│           └─ profiles.json      # 仅供 Mock 演示的 EXPERIMENTAL/CUSTOM Profile；没有真实 VERIFIED 预设
│        └─ profiles/
│           └─ deepseek_experimental.json # A2 真实验证用实验 Profile，无 Key、无 VERIFIED 宣称
├─ tests/
│  ├─ test_v01.py                 # V0.1 离线回归：合同/诊断/检索/网关/编排/Trace
│  ├─ test_v011_a1.py             # A1 离线测试：状态、能力、参数映射、Usage、安全与网络阻断
│  └─ test_v011_a2.py             # A2 真实入口的离线假网关测试；不读取 .env
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
│     └─ V0.1.1_A2_DEEPSEEK_VALIDATION_REPORT.md # A2 部分真实验证、失败与后续清单
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
| `openai_compatible_adapter.py` | `OpenAICompatibleAdapter.complete()/.stream()`、`RETRYABLE_STATUS` | SDK 自动重试关闭；能力验证后映射标准/受控 Provider 字段；正文已输出后不再重试 |
| `real_validation.py` | `run_real_validation()` | 仅显式确认后加载 .env；一项检查对应最多一次 SDK 请求尝试，输出脱敏结果 |
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

# 完整项目文件地图

文件地图按当前目录核对；docs、scripts 与 tests 已按实际文件重新列出，含未提交文档。缓存不展开，outputs 仅标运行数据类别，不读取生成记录或凭据内容。

```text
Fishery_AI_Prototype/                                            # 项目工作区
├─ .env                                                          # 旧本地配置，禁止运行时读取
├─ .gitignore                                                    # 生成数据、凭据与缓存忽略规则
├─ AGENTS.md                                                     # AI 助手操作与安全约束
├─ pyproject.toml                                                # 项目安装、依赖与包资源声明
├─ README.md                                                     # 项目目的、启动与文档入口
├─ .git/                                                         # Git 内部数据，不展开
├─ .venv/                                                        # 本地 Python 环境，不展开
├─ data/                                                         # 旧数据目录，当前为空目录结构
│  ├─ knowledge/                                                 # 空目录，运行数据已在包内
│  └─ mock/                                                      # 空目录，Mock 已在包内
├─ docs/                                                                    # 当前说明、专项技术合同与历史记录
│  ├─ deep-dive/                                                            # 当前专项技术文档与历史研究
│  │  ├─ architecture/                                                      # Analysis / Assistant 等跨模块架构
│  │  │  └─ ASSISTANT_MODEL_V1_DESIGN.md                                    # Analysis 与 Assistant 当前架构
│  │  ├─ data-domain/                                                       # 情景、Telemetry 与领域数据
│  │  │  └─ WATER_QUALITY_SCENARIO_AND_TELEMETRY_PREPARATION.md             # 水质输入与领域合同边界
│  │  ├─ models/                                                            # 模型合同与发布方案
│  │  │  ├─ PRESET_PUBLICATION.md                                           # Preset 发布方案与资格依据
│  │  │  └─ STREAMING_THINKING_OFF_COMBINATION.md                           # OFF + Streaming 组合验证
│  │  ├─ operations/                                                        # 凭据与运行数据位置
│  │  │  ├─ PRIVATE_CREDENTIAL_STORAGE.md                                   # 用户私有凭据安全边界
│  │  │  └─ PROJECT_DATA_AND_CONFIG_LOCATIONS.md                            # 数据与配置实际位置地图
│  │  ├─ research/                                                          # 带历史标记的研究与未来议题
│  │  │  ├─ BOUNDED_MULTI_ROUND_TOOL_RUNTIME.md                              # 多轮与流式研究，内部非流式两轮已实现
│  │  │  ├─ DEVELOPMENT_BACKLOG.md                                          # 未立项候选与用户原始笔记，保留历史
│  │  │  ├─ RUNTIME_PROMPT_AUDIT.md                                       # 运行 Prompt 来源与职责审计，含版本边界
│  │  │  └─ TOOL_ORCHESTRATION_ARCHITECTURE_REVIEW.md                       # 旧基线 Tool 编排研究
│  │  └─ tools/                                                             # 静态只读 Tool 执行层
│  │     ├─ ADDING_A_TOOL.md                                                # 新增正式只读 Tool 的通用规范
│  │     └─ READ_ONLY_TOOL_CALLING.md                                       # 三个 Tool 的协议与执行边界
│  ├─ records/                                                              # 迁移决策、独立审计与已结束阶段的归档
│  │  ├─ archive/                                                           # 历史 Markdown 与只含文档的 ZIP，不作为当前合同
│  │  │  ├─ history-v2-research/                                            # P1–P2E 已结束研究、真实结果及停止审计
│  │  │  │  ├─ 2026-10-assistant-history-projection-ab.md                   # P2C 模型无关投影 A/B 资格对照
│  │  │  │  ├─ 2026-10-assistant-history-projection-research.md             # P2B 固定历史实验与投影方案研究
│  │  │  │  ├─ 2026-10-assistant-history-tool-reliability-study.md          # Assistant 历史与 Tool 可靠性研究
│  │  │  │  ├─ 2026-10-assistant-turn-source-contract-p1.md                 # 本轮来源 Receipt 与操作完成合同
│  │  │  │  ├─ 2026-10-controlled-assistant-qualification-p2a.md            # 受控单次实验、dry-run 与安全报告
│  │  │  │  ├─ 2026-10-cross-model-history-projection-preparation.md        # P2D 双模型实验准备与独立授权边界
│  │  │  │  ├─ 2026-10-deepseek-history-projection-results.md               # DeepSeek 已完成的 30 run / 48 请求结果
│  │  │  │  ├─ 2026-10-history-projection-product-migration-qualification.md # P2E 冻结方案与执行合同，历史记录
│  │  │  │  └─ 2026-10-ollama-history-projection-results.md                 # Ollama 已完成的 30 run / 44 请求结果
│  │  │  ├─ knowledge-tool-v1/                                              # Tool 3 接入前设计、阶段总结与独立取证
│  │  │  │  ├─ 2026-10-codex-takeover-audit.md                              # 完整独立接管审计记录
│  │  │  │  ├─ 2026-10-knowledge-tool-v1-summary.md                         # Tool 3 接入范围与当时未验收项
│  │  │  │  ├─ 2026-10-qwen-tool-provider-evidence.md                       # Qwen 首轮取证的凭据预检阻塞
│  │  │  │  └─ KNOWLEDGE_TOOL_DESIGN.md                                     # Knowledge 接入前设计，历史 PAUSED 基线
│  │  │  ├─ copilot-tool3-records-2026-10.zip                               # 13 份施工记录，保留原目录结构
│  │  │  └─ pre-codex-handoff-2026-10.zip                                   # 3 份旧交接稿，保留原目录结构
│  │  ├─ 2026-10-history-v2-migration-decision.md                           # P2E 最终结果、证据边界与迁移判定
│  │  ├─ 2026-10-history-v2-product-migration.md                            # P2F 产品默认 B 与内部 A 回滚记录
│  │  ├─ 2026-10-repository-cleanup-audit.md                                # 未提交的只读仓库盘点，保留唯一信息
│  │  └─ README.md                                                          # 当前决策导航、历史归档边界与文件索引
│  ├─ BUILD_RUN.md                                                          # 构建、启动与验证命令
│  ├─ CODE_REVIEW.md                                                        # 工程复核与安全边界
│  ├─ ROADMAP.md                                                            # 稳定能力、剩余风险与研究路线
│  ├─ STRUCTURE.md                                                          # 完整项目文件地图
│  └─ TROUBLESHOOTING.md                                                    # 模型、凭据与页面故障排查
├─ outputs/                                                      # 本地生成数据，Git ignored，记录不逐项展开
│  ├─ assistant-qualification/                                   # 资格报告与 history、projection-ab、cross-model 分区
│  ├─ archive/                                                   # 用户本地历史运行数据，不展开
│  ├─ capability-evidence/                                       # Managed 能力证据与验证记录
│  ├─ custom_profiles/                                           # 用户 Managed Custom 连接
│  ├─ edge-a311-probe/                                           # 历史页面边界验证输出
│  ├─ edge-a312-probe/                                           # 历史 Profile 页面验证输出
│  ├─ manual-experiments/                                        # Manual V2 独立实验配置
│  ├─ package-check/                                             # 安装与打包检查输出
│  ├─ preset-qualification/                                      # 维护者 Preset 资格验证记录
│  ├─ qualification/                                             # 真实 Runtime 资格验证输出
│  ├─ scenario_templates/                                        # 用户自定义情景模板
│  ├─ tool-policies/                                             # 用户 Analysis 与 Assistant Tool 选择
│  ├─ mock-traces.jsonl                                          # 离线 Mock 请求 Trace
│  └─ web-traces.jsonl                                           # Web 请求安全 Trace
├─ scripts/                                                                 # 开发辅助与长期单次资格工具，不参与正常 Web 启动
│  ├─ dev/                                                                  # 离线测试入口与人工页面调试辅助
│  │  ├─ manual_edge_mock_probe.cjs                                         # 离线页面边界 Mock 验证辅助
│  │  └─ run_tests.py                                                       # FAST / 子系统 / FULL PRODUCT / FULL QUALIFICATION 入口
│  ├─ qualification/                                                        # 长期单次资格验证；默认不联网，无历史 batch
│  │  ├─ manifests/                                                         # Q1–Q4 单次维护计划示例，不含 H / P2E 批次
│  │  │  ├─ assistant-Q1.json                                               # 当前溶氧查询资格计划
│  │  │  ├─ assistant-Q2.json                                               # 当前评分资格计划
│  │  │  ├─ assistant-Q3.json                                               # 单 Knowledge Tool 资格计划
│  │  │  └─ assistant-Q4.json                                               # 三 Tool 选择 Knowledge 的资格计划
│  │  ├─ qualify_assistant_turn.py                                          # 单 manifest Assistant 资格入口，默认 dry-run
│  │  ├─ qualify_local_preset_request.py                                    # Local Preset 最小请求资格验证
│  │  ├─ qualify_multi_round.py                                             # 单案例有界多轮资格实验，默认 dry-run
│  │  └─ qualify_preset_tools.py                                            # Preset Tool Calling 资格验证入口
│  └─ README.md                                                             # 辅助工具用途与逐次真实联网授权边界
├─ src/                                                          # Runtime/Core 应用源码与安装 metadata
│  ├─ fishery_ai/                                                # 可安装 Python 应用包
│  │  ├─ __init__.py                                             # 应用包初始化
│  │  ├─ __main__.py                                             # CLI、Web 与真实验证入口
│  │  ├─ README.md                                               # 按职责分类的源码导航与开发边界
│  │  ├─ application.py                                          # 固定 Analysis 上下文与执行主流程
│  │  ├─ history_projection.py                                   # 产品默认 B 与原生 A 回滚的共享历史投影
│  │  ├─ assistant.py                                            # Assistant 上下文、历史与执行服务
│  │  ├─ assistant_activity.py                                   # 有序 Steps 的安全 Activity 投影
│  │  ├─ assistant_qualification.py                             # 旧路径模块别名，兼容历史导入与补丁
│  │  ├─ assistant_sources.py                                    # 逐执行 Receipt、Ledger 与来源满足关系
│  │  ├─ capability_probe.py                                     # 显式 Streaming 与 Thinking 验证
│  │  ├─ capability_store.py                                     # 精确模型能力证据存储
│  │  ├─ composition.py                                          # 离线 Demo 组合与包资源入口
│  │  ├─ contracts.py                                            # 领域事实、Evidence 与结果合同
│  │  ├─ credential_paths.py                                     # 固定用户私有凭据路径
│  │  ├─ credentials.py                                          # 凭据来源解析与不可变快照
│  │  ├─ custom_profiles.py                                      # Managed Custom 连接存储
│  │  ├─ domain.py                                               # 确定性水质诊断与阈值
│  │  ├─ evidence_resolver.py                                    # 能力证据合并与冲突解析
│  │  ├─ execution.py                                            # RequestHandle、请求状态与取消
│  │  ├─ knowledge.py                                            # 当前 TF-IDF 检索与 KnowledgeService        //!!!//
│  │  ├─ manual.py                                               # Raw 请求执行与安全响应                      //???//
│  │  ├─ manual_experiments.py                                   # Manual V2 独立实验配置存储                  //!!!//
│  │  ├─ model_gateway.py                                        # 模型消息、Tool 合同与 RuntimeSnapshot
│  │  ├─ model_options.py                                        # 生成选项、能力状态与校验
│  │  ├─ observability.py                                        # Usage 与安全 JSONL Trace
│  │  ├─ official_capabilities.py                                # 维护者记录的官方模型能力                    //!!!//
│  │  ├─ openai_compatible_adapter.py                            # OpenAI SDK 请求编码与传输
│  │  ├─ preset_tool_qualification.py                           # 旧路径模块别名，兼容历史导入与补丁
│  │  ├─ presets.py                                              # 固定 Preset 模板、Variant 与合同
│  │  ├─ project_env.py                                          # 私有凭据原子写入与 revision 检查
│  │  ├─ protocol_specs.py                                       # Provider 语义参数协议编码
│  │  ├─ providers.py                                            # Service、连接与 Auth 元数据
│  │  ├─ qualification_adapter.py                               # 旧路径模块别名，兼容历史导入与补丁
│  │  ├─ qualification_history.py                               # 旧路径模块别名，兼容历史导入与补丁
│  │  ├─ qualification_migration.py                             # 旧路径模块别名，兼容历史导入与补丁
│  │  ├─ qualification_projection.py                            # 旧路径模块别名，兼容历史导入与补丁
│  │  ├─ real_validation.py                                     # 旧路径模块别名，兼容历史导入与补丁
│  │  ├─ repositories.py                                         # 水质与 Detection Mock 资源读取
│  │  ├─ secure_files.py                                         # 安全文件操作与 Windows ACL 检查
│  │  ├─ tool_capability_probe.py                                # Managed Tool Calling 显式 Probe
│  │  ├─ tool_conversation.py                                    # 默认单轮与内部有界两轮共享协调
│  │  ├─ water_quality_scoring.py                                # 水质实验评分与等级规则
│  │  ├─ web.py                                                  # Web API、共享服务与页面入口
│  │  ├─ web_security.py                                         # Host、Origin 与 CSRF 防护
│  │  ├─ development/                                          # 显式开发工具，正式 Runtime 不加载
│  │  │  ├─ __init__.py                                         # 无副作用的开发包边界
│  │  │  └─ qualification/                                     # 资格实现，单向复用正式产品合同
│  │  │     ├─ __init__.py                                      # 无装配、凭据解析或联网的包入口
│  │  │     ├─ assistant_qualification.py                       # 单 manifest 授权、预算、运行与安全报告
│  │  │     ├─ multi_round_qualification.py                       # 隔离 Snapshot、多轮资格与安全来源报告
│  │  │     ├─ qualification_adapter.py                         # 资格输出预算与有限 Provider 观测
│  │  │     ├─ qualification_history.py                         # 冻结历史 fixture 与 case 兼容白名单
│  │  │     ├─ qualification_migration.py                       # 历史多轮资格 fixture 与矩阵兼容
│  │  │     ├─ qualification_projection.py                      # 产品投影复用与冻结资格指纹
│  │  │     ├─ preset_tool_qualification.py                      # Preset Tool 往返与概念题资格验证
│  │  │     └─ real_validation.py                               # validate-real 开发命令与安全诊断
│  │  ├─ resources/                                              # 随 Python 包发布的固定资源
│  │  │  ├─ knowledge/                                           # 现有渔业知识与来源
│  │  │  │  ├─ eel_knowledge.json                                # 项目渔业知识快照
│  │  │  │  └─ SOURCE.md                                         # 知识资源来源与 provenance 限制
│  │  │  ├─ mock/                                                # 离线 Mock Runtime 配置
│  │  │  │  └─ profiles.json                                     # 离线 Mock 模型配置
│  │  │  ├─ profiles/                                            # Preset 与开发连接模板
│  │  │  │  ├─ deepseek_experimental.json                        # DeepSeek 开发 Profile 模板
│  │  │  │  ├─ ollama_qwen35_local.json                          # Ollama 本地开发 Profile 模板
│  │  │  │  ├─ presets.json                                      # 维护者发布的 Preset 固定合同
│  │  │  │  └─ qwen_experimental.json                            # Qwen 开发 Profile 模板
│  │  │  ├─ scenarios/                                           # 确定性 Mock 场景资源
│  │  │  │  ├─ detection/                                        # Detection Mock 场景
│  │  │  │  │  ├─ count_jump.json                                # 检测数量变化 Mock 场景
│  │  │  │  │  └─ normal.json                                    # 正常检测 Mock 场景
│  │  │  │  └─ water_quality/                                    # 水质 Mock 场景
│  │  │  │     ├─ low_oxygen.json                                # 低溶氧水质 Mock 场景
│  │  │  │     ├─ normal.json                                    # 正常水质 Mock 场景
│  │  │  │     ├─ partial.json                                   # 部分水质数据缺失场景
│  │  │  │     ├─ partial_stale.json                             # 缺失且过期的水质场景
│  │  │  │     └─ stale.json                                     # 过期水质 Mock 场景
│  │  │  ├─ tools/                                               # 包内 Tool 默认权限
│  │  │  │  └─ tool_policies.json                                # 包内 Analysis 与 Assistant 默认权限
│  │  │  └─ web/                                                 # 本地 Web 静态页面资源
│  │  │     ├─ app.css                                           # 页面布局与视觉样式
│  │  │     ├─ app.js                                            # 页面状态、交互与安全文本展示
│  │  │     └─ index.html                                        # Analysis、Assistant 与开发页面
│  │  ├─ telemetry/                                              # 模拟输入、领域转换与当前快照                  //!!!//
│  │  │  ├─ __init__.py                                          # Telemetry 公共接口导出
│  │  │  ├─ adapter.py                                           # SimulationPacket 转换为领域水质
│  │  │  ├─ current.py                                           # 当前快照只读查询与 Freshness 重评
│  │  │  ├─ models.py                                            # Scenario 与 Simulation 数据合同
│  │  │  ├─ scenario_templates.py                                # 情景模板校验、存储与复制
│  │  │  ├─ simulator.py                                         # 确定性 Telemetry 模拟器
│  │  │  └─ snapshot.py                                          # 进程内当前水质 Snapshot Store
│  │  └─ tools/                                                  # 静态只读 Tool 执行层
│  │     ├─ __init__.py                                          # Tool 执行层公共接口导出
│  │     ├─ catalog.py                                           # Tool Manager 显示 metadata
│  │     ├─ contracts.py                                         # Tool 定义、结果、状态与安全错误
│  │     ├─ executor.py                                          # Tool 权限、参数与执行边界
│  │     ├─ policy.py                                            # Analysis 与 Assistant Tool 授权
│  │     ├─ registry.py                                          # 静态 Tool Definition 与 Handler 绑定
│  │     └─ handlers/                                            # 薄领域 Tool Handler
│  │        ├─ __init__.py                                       # 只读 Handler 子包入口
│  │        ├─ current_water_quality.py                          # 当前水质查询与诊断 Handler
│  │        ├─ knowledge_search.py                               # 只读知识检索 Handler 与 query validator（已注册）
│  │        └─ water_quality_score.py                            # 当前水质实验评分 Handler
│  └─ fishery_ai_prototype.egg-info/                             # 本地安装生成的包 metadata，Git ignored
│     ├─ dependency_links.txt                                    # 安装生成的依赖链接 metadata
│     ├─ PKG-INFO                                                # 安装生成的包说明 metadata
│     ├─ requires.txt                                            # 安装生成的依赖清单
│     ├─ SOURCES.txt                                             # 安装生成的打包文件清单
│     └─ top_level.txt                                           # 安装生成的顶层包名称
└─ tests/                                                                   # Development/Test 离线合同，产品与资格分层
   ├─ assistant/                                                            # Assistant、来源 Receipt 与正式 History 产品合同
   │  ├─ __init__.py                                                        # 测试子包标记，支持规范 unittest discovery
   │  ├─ test_assistant.py                                                  # Assistant 合同、选择规则 Prompt 契约、历史与执行回归测试
   │  ├─ test_assistant_activity.py                                         # 累积步骤、执行证明、取消与最终提交回归
   │  ├─ test_assistant_multi_round.py                                      # 内部 Assistant 两轮、Ledger、整 Turn deadline 与单轮兼容
   │  ├─ test_assistant_sources.py                                          # Receipt、Ledger 与来源提交合同测试
   │  └─ test_history_projection.py                                         # 产品默认 B、A 回滚、裁剪、JSON 与来源隔离回归
   ├─ domain/                                                               # 水质、Diagnosis、评分与 Scenario / Telemetry 回归
   │  ├─ __init__.py                                                        # 测试子包标记，支持规范 unittest discovery
   │  ├─ test_current_water_quality.py                                      # 当前水质查询与 Freshness 测试
   │  ├─ test_scenario_templates.py                                         # 情景模板 CRUD 与显式 Apply 测试
   │  ├─ test_telemetry_simulator.py                                        # Telemetry 合同、模拟与 Adapter 测试
   │  ├─ test_v01.py                                                        # 基础合同、诊断、Knowledge 与 Gateway 测试
   │  ├─ test_v011_a3_grounding.py                                          # 检索相关性、Grounding 与 Profile 测试
   │  ├─ test_water_quality_matrix.py                                       # 水质边界研究场景离线测试
   │  └─ test_water_quality_scoring.py                                      # 实验评分与评分 Tool 测试
   ├─ fixtures/                                                             # 虚构数据与历史兼容性夹具
   │  ├─ historical_model_assets/                                           # 仅测试使用的历史模型资源
   │  │  ├─ profiles/                                                       # 历史 Profile 与 Preset 夹具
   │  │  │  ├─ deepseek_experimental.json                                   # 历史 DeepSeek Profile 测试夹具
   │  │  │  ├─ ollama_qwen35_local.json                                     # 历史 Ollama Profile 测试夹具
   │  │  │  ├─ presets.json                                                 # 历史 Preset 固定合同测试夹具
   │  │  │  └─ qwen_experimental.json                                       # 历史 Qwen Profile 测试夹具
   │  │  ├─ official_declarations.json                                      # 历史官方能力声明测试夹具
   │  │  └─ README.md                                                       # 历史夹具用途与运行隔离说明
   │  └─ r0_runtime_baseline.json                                           # Runtime 兼容性基准夹具
   ├─ providers/                                                            # Gateway、Provider / Protocol、能力与 Preset 回归
   │  ├─ __init__.py                                                        # 测试子包标记，支持规范 unittest discovery
   │  ├─ test_cloud_capability.py                                           # Cloud 能力声明与显式 Probe 测试
   │  ├─ test_evidence_resolver.py                                          # 精确 Identity 证据解析与冲突测试
   │  ├─ test_gateway_tool_contract.py                                      # Tool 模型消息与 SDK 编解码测试
   │  ├─ test_off_streaming_combination.py                                  # OFF 加 Streaming 组合证据测试
   │  ├─ test_ollama_reasoning.py                                           # 精确 Ollama Thinking 参数测试
   │  ├─ test_output_parity.py                                              # Normal 与 Streaming 输出边界测试
   │  ├─ test_preset.py                                                     # Preset 固定合同与证据隔离测试
   │  ├─ test_preset_publication.py                                         # Preset 发布选项与默认模型测试
   │  ├─ test_protocol_specs.py                                             # Provider 请求体编码一致性测试
   │  ├─ test_tool_capability_probe.py                                      # Tool 能力 Probe 与 Web 门禁测试
   │  ├─ test_unknown_model_probe.py                                        # 未知能力显式 Probe 与证据写入测试
   │  ├─ test_v011_a1.py                                                    # 多模型能力、选项与 Usage 合同测试
   │  ├─ test_v011_a2.py                                                    # 真实验证入口的离线安全测试
   │  ├─ test_v011_a2_1.py                                                  # 安全诊断与 Cloud 兼容性测试
   │  └─ test_v011_a313_capability_identity.py                              # Service、Model Identity 与能力隔离测试
   ├─ qualification/                                                        # 长期单次资格验证；默认不联网，无历史 batch
   │  ├─ __init__.py                                                        # 测试子包标记，支持规范 unittest discovery
   │  ├─ test_assistant_qualification.py                                    # 单次实验、预算、取消与报告脱敏测试
   │  ├─ test_qualification_boundary.py                                      # 正式导入隔离、兼容别名与开发 CLI 边界测试
   │  ├─ test_multi_round_qualification.py                                   # 单案例预算、隔离 Snapshot、结果关联与安全报告
   │  ├─ test_local_preset_qualification.py                                 # Local Preset 验证入口安全测试
   │  └─ test_preset_tool_qualification.py                                  # Preset Tool 完整资格流程测试
   ├─ security/                                                             # Credential、安全写入、ACL、快照与请求取消
   │  ├─ __init__.py                                                        # 测试子包标记，支持规范 unittest discovery
   │  ├─ test_credential_compatibility.py                                   # 凭据迁移与 Runtime 兼容性测试
   │  ├─ test_credential_writer.py                                          # 凭据写入、revision 与安全回归测试
   │  ├─ test_credentials.py                                                # 凭据优先级与快照测试
   │  ├─ test_credentials_private_storage.py                                # 私有凭据路径、ACL 与隔离测试
   │  └─ test_execution.py                                                  # 取消、整轮超时、资源释放与 Raw 请求隔离测试
   ├─ support/                                                              # 共享路径与显式兼容性 fixture，零测试用例
   │  ├─ __init__.py                                                        # 测试子包标记，支持规范 unittest discovery
   │  ├─ historical_model_fixtures.py                                       # 历史模型测试夹具加载辅助
   │  └─ paths.py                                                           # 固定 PROJECT_ROOT / TESTS_ROOT，不依赖 cwd
   ├─ tools/                                                                # 静态只读 Tool 执行层
   │  ├─ __init__.py                                                        # 测试子包标记，支持规范 unittest discovery
   │  ├─ test_analysis_tools.py                                             # 固定 Analysis 与单轮 Tool 回归测试
   │  ├─ test_catalog_knowledge.py                                          # Catalog 条目 metadata、派生标志与授权边界测试
   │  ├─ test_knowledge_assembly.py                                         # 共享 KnowledgeService 装配、单例与可执行性测试
   │  ├─ test_knowledge_handler.py                                          # 薄 Knowledge Handler 映射、截断与 NO_MATCH 测试
   │  ├─ test_knowledge_registration.py                                     # Knowledge 注册、依赖注入与 query validator 测试
   │  ├─ test_mock_tool_gateway.py                                          # 离线 Mock 按工具名分派、方向性降级与安全兜底测试
   │  ├─ test_read_only_tools.py                                            # Registry、Executor 与只读 Handler 测试
   │  ├─ test_tool_argument_contract.py                                     # Tool 受控参数合同与旧工具兼容测试
   │  ├─ test_bounded_multi_round.py                                        # 内部两轮预算、模型决策、去重与取消测试
   │  ├─ test_tool_conversation.py                                          # steps、固定预算、单轮与兼容投影测试
   │  ├─ test_tool_policy.py                                                # Analysis 与 Assistant 授权测试
   │  ├─ test_tool_policy_manager.py                                        # Tool Manager、用户 Policy 存储与默认/override 不变性测试
   │  └─ test_tool_status_no_match.py                                       # NO_MATCH 非错误结果、二轮闭环与安全投影测试
   ├─ web/                                                                  # Web API、Session、Manual 与 Node 页面回归
   │  ├─ __init__.py                                                        # 测试子包标记，支持规范 unittest discovery
   │  ├─ test_a316_runtime_defaults.py                                      # 运行默认偏好与安全回退测试
   │  ├─ test_access_web.py                                                 # Preset、Manual 与取消 Web 边界测试
   │  ├─ test_analysis_tool_web.py                                          # 正式 Analysis Tool Web 接入测试
   │  ├─ test_browser_streaming.cjs                                         # 页面交互、状态与浏览器回归测试
   │  ├─ test_clean_room_reset.py                                           # Clean-room 空目录启动测试
   │  ├─ test_default_preference_ui.py                                      # 默认偏好与能力门禁同步测试
   │  ├─ test_local_profile_capability_ui.py                                # 本地 metadata 与 Capability UI 测试
   │  ├─ test_manual_v2.py                                                  # 实验 CRUD、独立凭据与 Raw 请求测试
   │  ├─ test_v011_a31_streaming.py                                         # 应用 Streaming 与 SSE 回归测试
   │  ├─ test_v011_a3_profile_manager.py                                    # Profile CRUD、连接与门禁测试
   │  ├─ test_v011_a3_web.py                                                # 开发 Web 页面与安全错误测试
   │  └─ test_web_tool_conversation.py                                      # 开发 Tool Conversation、Trace 与 Stop 测试
   ├─ __init__.py                                                           # 测试子包标记，支持规范 unittest discovery
   └─ README.md                                                             # 测试分类、四层策略与覆盖边界
```

**Runtime / Core：** src/fishery_ai 是运行源码，resources 是包内固定资源；源码根 .env 只标位置，不读取内容，也不参与运行时。

**Development / Test：** src/fishery_ai/development/qualification 集中资格实现，旧顶层模块仅为兼容别名；正式 Web / Assistant / Analysis 不导入资格实现，validate-real CLI 按需加载。tests 分为正式子系统与 qualification，support / fixtures 为共享测试资料。scripts/dev 保存开发辅助，scripts/qualification 保存单次维护验证；.egg-info 为安装生成 metadata。已删除 H / P2E manifests、历史 batch / continuation、preparation generator 和六份实验测试；产品 History 与安全合同仍在正式测试中，历史见 records 与 Git。

**Research / Records：** deep-dive 保存当前技术合同及明确标记的未来研究；records 根目录保留迁移依据与独立审计，已结束阶段进入 archive。历史文件中的状态、路径和测试数量适用于当时基线。History v2 已默认 B；有限真实资格实验不证明长期模型选择可靠性。

**Generated / User-private：** outputs 的 JSON/JSONL 验证记录、用户配置与历史内容不逐项展开；.git、.venv、__pycache__ 等内部文件与缓存不展开。%LOCALAPPDATA% 不属于仓库树，正式凭据与 Manual V2 凭据在固定用户私有目录中分文件存放，不读取或列出其内容。

## 推荐测试层级

- **FAST**：`python scripts/dev/run_tests.py fast`，显式核心合同集合。
- **TARGETED**：`python scripts/dev/run_tests.py assistant`（或 domain / providers / security / tools / web），单模块可用规范 tests 包名。
- **FULL PRODUCT**：`python scripts/dev/run_tests.py` 默认不收集 qualification；Browser 用 `node --test tests/web/test_browser_streaming.cjs`。
- **FULL QUALIFICATION**：`python scripts/dev/run_tests.py qualification`，仅基础设施改动时离线运行。

标准全部发现：`python -m unittest discover -s tests -t .`，包括产品与资格两层；不要省略 top-level 参数。详见[测试说明](../tests/README.md)与[维护工具](../scripts/README.md)。

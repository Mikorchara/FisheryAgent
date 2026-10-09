# 完整项目文件地图

按当前磁盘实际文件生成；含未跟踪文档与本地安装 metadata。目录数不含项目根；缓存不展开，outputs 仅列实际一级目录与两个固定 Trace 文件。

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
├─ docs/                                                         # 项目使用、技术与交接资料
│  ├─ BUILD_RUN.md                                               # 构建、启动与验证命令
│  ├─ CODE_REVIEW.md                                             # 工程复核与安全边界
│  ├─ ROADMAP.md                                                 # 稳定功能与后续阶段路线
│  ├─ STRUCTURE.md                                               # 完整项目文件地图
│  ├─ TROUBLESHOOTING.md                                         # 模型、凭据与页面故障排查
│  ├─ deep-dive/                                                 # 当前专项技术与研究文档
│  │  ├─ architecture/                                           # 跨模块架构文档
│  │  │  └─ ASSISTANT_MODEL_V1_DESIGN.md                         # Analysis 与 Assistant 稳定架构
│  │  ├─ data-domain/                                            # 情景与领域数据文档
│  │  │  └─ WATER_QUALITY_SCENARIO_AND_TELEMETRY_PREPARATION.md  # 情景、Telemetry 与水质数据边界
│  │  ├─ models/                                                 # 模型合同与发布文档
│  │  │  ├─ PRESET_PUBLICATION.md                                # 当前 Preset 发布合同与验证依据
│  │  │  └─ STREAMING_THINKING_OFF_COMBINATION.md                # OFF 加 Streaming 组合能力说明
│  │  ├─ operations/                                             # 凭据与运行数据位置文档
│  │  │  ├─ PRIVATE_CREDENTIAL_STORAGE.md                        # 用户私有凭据安全存储
│  │  │  └─ PROJECT_DATA_AND_CONFIG_LOCATIONS.md                 # 数据与配置实际位置地图
│  │  ├─ research/                                               # 暂停或未实现的研究
│  │  │  ├─ KNOWLEDGE_TOOL_DESIGN.md                             # 暂停的 Knowledge Tool 研究
│  │  │  └─ others.md                                            # 用户补充的研究笔记
│  │  └─ tools/                                                  # Tool 当前合同与新增规范
│  │     ├─ ADDING_A_TOOL.md                                     # 新增正式只读 Tool 的通用规范
│  │     └─ READ_ONLY_TOOL_CALLING.md                            # 当前 Tool 协议、执行与应用接入
│  ├─ handoff/                                                   # 人工接手与 Copilot 学习资料
│  │  ├─ KNOWLEDGE_TOOL_V1_WALKTHROUGH.md                        # 未实现 Knowledge Tool 的接手案例
│  │  ├─ README.md                                               # 代码接手阅读顺序与安全边界
│  │  └─ TOOL_CHANGE_MAP.md                                      # Tool 各层代码修改地图
│  └─ copilot/                                                   # Copilot 协作的过程记录，不是产品文档
│     ├─ KNOWLEDGE_TOOL_STEP_BY_STEP.md                          # Knowledge Tool 分步实施思路与已确认决定
│     ├─ STEP2_TOOL_ARGUMENT_CONTRACT_BEFORE_AFTER.md            # Step 2 受控参数合同的 before/after 对照记录
│     ├─ STEP3_TOOL_STATUS_NO_MATCH_BEFORE_AFTER.md              # Step 3 NO_MATCH 合同的 before/after 对照记录
│     ├─ STEP4_KNOWLEDGE_HANDLER_DESIGN.md                       # Step 4 薄 Knowledge Handler 设计与实施记录
│     ├─ STEP4_KNOWLEDGE_HANDLER_BEFORE_AFTER.md                 # Step 4 Handler 的 before/after 对照记录
│     ├─ D1_MOCK_TOOL_GATEWAY_BEFORE_AFTER.md                    # D1 Mock 按工具名分派的 before/after 对照记录
│     ├─ STEP5_KNOWLEDGE_REGISTRATION_BEFORE_AFTER.md            # Step 5 注册与 query validator 的 before/after 对照记录
│     ├─ STEP6_CATALOG_BEFORE_AFTER.md                           # Step 6 Catalog 新增 Knowledge 条目的 before/after 对照记录
│     ├─ STEP7_POLICY_DEFAULTS_BEFORE_AFTER.md                   # Step 7 Policy 默认与旧 override 兼容的核对记录
│     └─ STEP8_KNOWLEDGE_ASSEMBLY_BEFORE_AFTER.md                # Step 8 共享 KnowledgeService 装配的 before/after 对照记录
├─ outputs/                                                      # 本地生成数据，Git ignored，记录不逐项展开
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
├─ scripts/                                                      # 人工开发与资格验证辅助工具
│  ├─ qualify_local_preset_request.py                            # Local Preset 最小请求资格验证
│  └─ qualify_preset_tools.py                                    # Preset Tool Calling 资格验证入口
├─ src/                                                          # Runtime/Core 应用源码与安装 metadata
│  ├─ fishery_ai/                                                # 可安装 Python 应用包
│  │  ├─ __init__.py                                             # 应用包初始化
│  │  ├─ __main__.py                                             # CLI、Web 与真实验证入口
│  │  ├─ application.py                                          # 固定 Analysis 上下文与执行主流程
│  │  ├─ assistant.py                                            # Assistant 上下文、历史与执行服务
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
│  │  ├─ preset_tool_qualification.py                            # Preset Tool Calling 资格验证
│  │  ├─ presets.py                                              # 固定 Preset 模板、Variant 与合同
│  │  ├─ project_env.py                                          # 私有凭据原子写入与 revision 检查
│  │  ├─ protocol_specs.py                                       # Provider 语义参数协议编码
│  │  ├─ providers.py                                            # Service、连接与 Auth 元数据
│  │  ├─ real_validation.py                                      # 显式真实模型验证流程
│  │  ├─ repositories.py                                         # 水质与 Detection Mock 资源读取
│  │  ├─ secure_files.py                                         # 安全文件操作与 Windows ACL 检查
│  │  ├─ tool_capability_probe.py                                # Managed Tool Calling 显式 Probe
│  │  ├─ tool_conversation.py                                    # 单轮模型、Tool、模型协调
│  │  ├─ water_quality_scoring.py                                # 水质实验评分与等级规则
│  │  ├─ web.py                                                  # Web API、共享服务与页面入口
│  │  ├─ web_security.py                                         # Host、Origin 与 CSRF 防护
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
│  │        ├─ knowledge_search.py                               # 只读知识检索 Handler（未注册，Step 4 已实现）
│  │        └─ water_quality_score.py                            # 当前水质实验评分 Handler
│  └─ fishery_ai_prototype.egg-info/                             # 本地安装生成的包 metadata，Git ignored
│     ├─ dependency_links.txt                                    # 安装生成的依赖链接 metadata
│     ├─ PKG-INFO                                                # 安装生成的包说明 metadata
│     ├─ requires.txt                                            # 安装生成的依赖清单
│     ├─ SOURCES.txt                                             # 安装生成的打包文件清单
│     └─ top_level.txt                                           # 安装生成的顶层包名称
└─ tests/                                                        # Development/Test 离线回归体系
   ├─ historical_model_fixtures.py                               # 历史模型测试夹具加载辅助
   ├─ manual_edge_mock_probe.cjs                                 # 离线页面边界 Mock 验证辅助
   ├─ test_a316_runtime_defaults.py                              # 运行默认偏好与安全回退测试
   ├─ test_access_web.py                                         # Preset、Manual 与取消 Web 边界测试
   ├─ test_analysis_tool_web.py                                  # 正式 Analysis Tool Web 接入测试
   ├─ test_analysis_tools.py                                     # 固定 Analysis 与单轮 Tool 回归测试
   ├─ test_assistant.py                                          # Assistant 合同、历史与执行回归测试
   ├─ test_browser_streaming.cjs                                 # 页面交互、状态与浏览器回归测试
   ├─ test_catalog_knowledge.py                                  # Catalog 条目 metadata、派生标志与授权边界测试
   ├─ test_clean_room_reset.py                                   # Clean-room 空目录启动测试
   ├─ test_cloud_capability.py                                   # Cloud 能力声明与显式 Probe 测试
   ├─ test_credential_compatibility.py                           # 凭据迁移与 Runtime 兼容性测试
   ├─ test_credential_writer.py                                  # 凭据写入、revision 与安全回归测试
   ├─ test_credentials.py                                        # 凭据优先级与快照测试
   ├─ test_credentials_private_storage.py                        # 私有凭据路径、ACL 与隔离测试
   ├─ test_current_water_quality.py                              # 当前水质查询与 Freshness 测试
   ├─ test_default_preference_ui.py                              # 默认偏好与能力门禁同步测试
   ├─ test_evidence_resolver.py                                  # 精确 Identity 证据解析与冲突测试
   ├─ test_execution.py                                          # 取消、资源释放与 Raw 请求隔离测试
   ├─ test_gateway_tool_contract.py                              # Tool 模型消息与 SDK 编解码测试
   ├─ test_knowledge_assembly.py                                 # 共享 KnowledgeService 装配、单例与可执行性测试
   ├─ test_knowledge_handler.py                                  # 薄 Knowledge Handler 映射、截断与 NO_MATCH 测试
   ├─ test_knowledge_registration.py                             # Knowledge 注册、依赖注入与 query validator 测试
   ├─ test_local_preset_qualification.py                         # Local Preset 验证入口安全测试
   ├─ test_local_profile_capability_ui.py                        # 本地 metadata 与 Capability UI 测试
   ├─ test_manual_v2.py                                          # 实验 CRUD、独立凭据与 Raw 请求测试
   ├─ test_mock_tool_gateway.py                                  # 离线 Mock 按工具名分派与安全兜底测试
   ├─ test_off_streaming_combination.py                          # OFF 加 Streaming 组合证据测试
   ├─ test_ollama_reasoning.py                                   # 精确 Ollama Thinking 参数测试
   ├─ test_output_parity.py                                      # Normal 与 Streaming 输出边界测试
   ├─ test_preset.py                                             # Preset 固定合同与证据隔离测试
   ├─ test_preset_publication.py                                 # Preset 发布选项与默认模型测试
   ├─ test_preset_tool_qualification.py                          # Preset Tool 完整资格流程测试
   ├─ test_protocol_specs.py                                     # Provider 请求体编码一致性测试
   ├─ test_read_only_tools.py                                    # Registry、Executor 与只读 Handler 测试
   ├─ test_scenario_templates.py                                 # 情景模板 CRUD 与显式 Apply 测试
   ├─ test_telemetry_simulator.py                                # Telemetry 合同、模拟与 Adapter 测试
   ├─ test_tool_argument_contract.py                             # Tool 受控参数合同与旧工具兼容测试
   ├─ test_tool_capability_probe.py                              # Tool 能力 Probe 与 Web 门禁测试
   ├─ test_tool_conversation.py                                  # 单轮 Tool 闭环、Usage 与错误测试
   ├─ test_tool_policy.py                                        # Analysis 与 Assistant 授权测试
   ├─ test_tool_policy_manager.py                                # Tool Manager、用户 Policy 存储与默认/override 不变性测试
   ├─ test_tool_status_no_match.py                               # NO_MATCH 非错误结果、二轮闭环与安全投影测试
   ├─ test_unknown_model_probe.py                                # 未知能力显式 Probe 与证据写入测试
   ├─ test_v01.py                                                # 基础合同、诊断、Knowledge 与 Gateway 测试
   ├─ test_v011_a1.py                                            # 多模型能力、选项与 Usage 合同测试
   ├─ test_v011_a2.py                                            # 真实验证入口的离线安全测试
   ├─ test_v011_a2_1.py                                          # 安全诊断与 Cloud 兼容性测试
   ├─ test_v011_a313_capability_identity.py                      # Service、Model Identity 与能力隔离测试
   ├─ test_v011_a31_streaming.py                                 # 应用 Streaming 与 SSE 回归测试
   ├─ test_v011_a3_grounding.py                                  # 检索相关性、Grounding 与 Profile 测试
   ├─ test_v011_a3_profile_manager.py                            # Profile CRUD、连接与门禁测试
   ├─ test_v011_a3_web.py                                        # 开发 Web 页面与安全错误测试
   ├─ test_water_quality_matrix.py                               # 水质边界研究场景离线测试
   ├─ test_water_quality_scoring.py                              # 实验评分与评分 Tool 测试
   ├─ test_web_tool_conversation.py                              # 开发 Tool Conversation、Trace 与 Stop 测试
   └─ fixtures/                                                  # 虚构数据与历史兼容性夹具
      ├─ r0_runtime_baseline.json                                # Runtime 兼容性基准夹具
      └─ historical_model_assets/                                # 仅测试使用的历史模型资源
         ├─ official_declarations.json                           # 历史官方能力声明测试夹具
         ├─ README.md                                            # 历史夹具用途与运行隔离说明
         └─ profiles/                                            # 历史 Profile 与 Preset 夹具
            ├─ deepseek_experimental.json                        # 历史 DeepSeek Profile 测试夹具
            ├─ ollama_qwen35_local.json                          # 历史 Ollama Profile 测试夹具
            ├─ presets.json                                      # 历史 Preset 固定合同测试夹具
            └─ qwen_experimental.json                            # 历史 Qwen Profile 测试夹具
```

**Runtime / Core：** src/fishery_ai 是运行源码，resources 是包内固定资源；源码根 .env 只标位置，不读取内容，也不参与运行时。

**Development / Test：** tests 保留完整离线回归；scripts 是维护者辅助工具；.egg-info 是安装生成的 metadata。

**Research / Handoff：** deep-dive 的六个分类保存专项资料，handoff 提供接手路径，copilot 保存 Copilot 协作的过程记录（含 before/after 对照），不是产品文档；Knowledge Tool 仍为 PAUSED / NOT IMPLEMENTED。

**Generated / User-private：** outputs 的 JSON/JSONL 验证记录、用户配置与历史内容不逐项展开；.git、.venv、__pycache__ 等内部文件与缓存不展开。%LOCALAPPDATA% 不属于仓库树，正式凭据与 Manual V2 凭据在固定用户私有目录中分文件存放，不读取或列出其内容。

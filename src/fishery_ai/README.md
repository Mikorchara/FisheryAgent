# 源码导航

本页按当前目录定位文件，只说明主要职责，不重复架构设计。路径相对于 `src/fishery_ai/`。

**正式产品 Runtime** 包括 Analysis、Assistant、Tool、模型接入、凭据、Web，以及显式触发的 Managed Probe、Manual 和离线 Mock 支持。**Development / Qualification** 是维护者单独调用的开发工具，不由正常 Web / Assistant / Analysis 加载；旧顶层资格模块只保留兼容别名。

## 入口与离线组合

- [__init__.py](__init__.py)：应用包标记与版本。
- [__main__.py](__main__.py)：CLI 分派到 Web、离线 Demo 或按需加载的 `validate-real` 开发命令。
- [composition.py](composition.py)：组合离线 Demo 的 Mock Repository、诊断、Knowledge、Gateway 和 Trace。

## Assistant / Analysis · 正式 Runtime

- [assistant.py](assistant.py)：Assistant 请求、完整历史 pair 裁剪、上下文构造与执行服务。
- [assistant_streaming.py](assistant_streaming.py)：Web Streaming 的独立发布/本地实验门禁、固定配置加载、输出预算与临时 SSE 事件；默认关闭，无 Tool 执行循环。
- [assistant_activity.py](assistant_activity.py)：正式 Runtime 的有序步骤安全投影，供状态轮询、最终响应和 Trace 复用，不保存第二份 Tool payload。
- [assistant_execution.py](assistant_execution.py)：应用启动时冻结多轮发布范围，以精确合同与实际 Tool 集合决定模式，并绑定联网确认 revision；Prototype 已授权本地多轮试用：Qwen 为已验证发布，DeepSeek / Ollama 为独立实验范围。
- [assistant_sources.py](assistant_sources.py)：本轮来源要求、逐执行 Receipt / Ledger 与成功提交满足关系。
- [history_projection.py](history_projection.py)：正式默认的未受信任历史投影，以及原生投影回滚路径；资格工具复用同一投影。
- [application.py](application.py)：固定 Analysis 上下文、Normal / Streaming 执行、可选 Tool 接入与结果投影。

## Tool Runtime · 正式 Runtime

- [tool_conversation.py](tool_conversation.py)：默认 1/1/2 与显式 2/2/3 的共享协调；Normal / 组装后的 Streaming 复用同一循环，保留 steps、Usage / 安全 Trace；Web Streaming 由独立实验范围授权。
- [tools/__init__.py](tools/__init__.py)：Tool 执行层公共接口导出。
- [tools/contracts.py](tools/contracts.py)：Tool 定义、执行结果、业务状态与安全错误合同。
- [tools/registry.py](tools/registry.py)：静态 allowlist、正式模型 Tool Definition 及固定 Handler 绑定。
- [tools/executor.py](tools/executor.py)：校验授权与参数、检查取消、执行一次 Handler 并限制结果大小。
- [tools/policy.py](tools/policy.py)：Analysis / Assistant 授权策略、默认配置和用户覆盖存储。
- [tools/catalog.py](tools/catalog.py)：Tool Manager 展示元数据及安全 Activity 摘要；不授予执行权限。
- [tools/handlers/__init__.py](tools/handlers/__init__.py)：只读领域 Handler 子包标记，不做动态发现。
- [tools/handlers/current_water_quality.py](tools/handlers/current_water_quality.py)：从 Current Reader 查询水质，调用诊断并返回 canonical facts。
- [tools/handlers/water_quality_score.py](tools/handlers/water_quality_score.py)：读取当前水质并委托实验评分服务，保留数据状态。
- [tools/handlers/knowledge_search.py](tools/handlers/knowledge_search.py)：校验 query、复用 KnowledgeService 检索并生成有界结果与 NO_MATCH。

## Domain & Knowledge · 正式 Runtime

- [contracts.py](contracts.py)：canonical 水质、Quality / Freshness、Findings、Evidence、Usage 和 Analysis 输入输出合同。
- [domain.py](domain.py)：确定性水质阈值与 DiagnosisService，独立于模型和网络。
- [water_quality_scoring.py](water_quality_scoring.py)：实验性水质评分、等级与分项结果，不代表专业标准。
- [knowledge.py](knowledge.py)：当前 TF-IDF 检索及关键词 fallback，提供共享 KnowledgeService。
- [repositories.py](repositories.py)：确定性水质 / Detection Mock 资源读取；不是 Web 当前 Snapshot 的替代来源。

## Telemetry · 正式 Runtime

- [telemetry/__init__.py](telemetry/__init__.py)：模拟输入、Adapter、Snapshot Store 与 Current Reader 公共接口。
- [telemetry/models.py](telemetry/models.py)：SimulationRecipe / SimulationPacket 合同，尚非硬件协议。
- [telemetry/scenario_templates.py](telemetry/scenario_templates.py)：Scenario 意图校验、模板存储和显式 Apply 组合。
- [telemetry/simulator.py](telemetry/simulator.py)：把基线和用户覆盖生成模拟 Packet，不执行诊断。
- [telemetry/adapter.py](telemetry/adapter.py)：校验模拟输入并归一为 WaterQualityReading。
- [telemetry/snapshot.py](telemetry/snapshot.py)：进程内保存最后一次显式写入的当前水质 Snapshot。
- [telemetry/current.py](telemetry/current.py)：只读查询当前 Snapshot，在查询时重评 Freshness，不重采样或 fallback。

## Provider & Model · 正式 Runtime

- [model_gateway.py](model_gateway.py)：模型消息 / Tool 协议合同、ProfileRegistry、RuntimeSnapshot、Gateway 与离线 MockGateway。
- [model_options.py](model_options.py)：生成 / Reasoning 选项、能力三态、URL 归一与最终能力门禁。
- [providers.py](providers.py)：静态 Service / Provider、Auth 与协议引用，不据此推断模型能力。
- [protocol_specs.py](protocol_specs.py)：Provider 请求参数编码规则，回答怎么发送，不授予能力。
- [openai_compatible_adapter.py](openai_compatible_adapter.py)：SDK 传输、Normal / Streaming / Raw 请求、Tool 编解码与安全错误归一。
- [presets.py](presets.py)：加载维护者固定 Preset 模板、Variant、默认选择与发布合同。
- [custom_profiles.py](custom_profiles.py)：Managed Custom Profile 存储与字段校验，只保存 credential_ref。
- [official_capabilities.py](official_capabilities.py)：加载维护者审阅的精确官方能力声明。
- [capability_store.py](capability_store.py)：Managed 精确 Identity 的本地能力证据记录，不含 Secret。
- [evidence_resolver.py](evidence_resolver.py)：证据来源、精确 Identity 与保守合并 / 冲突解析。
- [capability_probe.py](capability_probe.py)：用户显式触发的 Thinking / Streaming 独立及组合能力 Probe。
- [tool_capability_probe.py](tool_capability_probe.py)：用户显式触发的 Managed Tool Calling Probe，复用正式单轮协调器。
- [manual.py](manual.py)：Manual Raw 请求 / 响应合同，不进入能力解析或 Fishery Analysis。
- [manual_experiments.py](manual_experiments.py)：Manual V2 独立 Experiment 存储、自定义 Target 和请求准备。

## Security & Config · 正式 Runtime

- [credential_paths.py](credential_paths.py)：稳定的用户私有正式凭据 / Manual V2 路径，不回退源码根 `.env`。
- [credentials.py](credentials.py)：按 Process Environment → 私有 PROJECT_ENV → Missing 解析，生成不可变 CredentialSnapshot。
- [project_env.py](project_env.py)：固定私有凭据文件 CRUD、内容保留、revision 冲突与原子写入。
- [secure_files.py](secure_files.py)：ACL、路径 / 链接、私有 staging、lock 和安全替换的操作系统边界。
- [execution.py](execution.py)：RequestHandle、请求登记、作用域和取消检查。
- [observability.py](observability.py)：allowlist JSONL Trace，不记录 Prompt、凭据或原始 Profile。
- [web_security.py](web_security.py)：本地 Host / Origin 校验及 Session CSRF 保护。

## Web · 正式 Runtime 与开发界面入口

- [web.py](web.py)：Flask 装配、共享服务、API、Session 和页面启动；业务执行委托既有服务。

页面资源在 [resources/web/](resources/web/)：`index.html` 为工作区结构，`app.js` 为页面状态与交互，`app.css` 为样式。Development / Test 页面复用产品服务，不等于导入下列维护者 Qualification 子包。

## Development / Qualification · 显式开发入口

Phase D 后实现集中在 `development/qualification/`，单向复用正式 Runtime。脚本入口在 [scripts/qualification/](../../scripts/qualification/)，正常产品启动不装配这些工具。

- [development/__init__.py](development/__init__.py)：无副作用的开发包标记。
- [development/qualification/__init__.py](development/qualification/__init__.py)：资格边界标记，导入包本身不装配服务、解析凭据或联网。
- [development/qualification/assistant_qualification.py](development/qualification/assistant_qualification.py)：单 manifest 授权、预算、Assistant 资格执行和安全报告。
- [development/qualification/multi_round_qualification.py](development/qualification/multi_round_qualification.py)：隔离合成 Snapshot 的单案例资格入口；保留旧实验模式，新增正式 Assistant Prompt / History / 来源门禁的 Qwen 精确范围验证，默认不联网。
- [development/qualification/qualification_adapter.py](development/qualification/qualification_adapter.py)：单次实验的输出预算与有限 Provider 原始 / 归一观测。
- [development/qualification/streaming_observation.py](development/qualification/streaming_observation.py)：开发资格专用的有限 SDK 分片计数、一致性与清理状态，未接 Web。
- [development/qualification/qualification_history.py](development/qualification/qualification_history.py)：冻结合成 History、H case 和兼容白名单，非产品 Session。
- [development/qualification/qualification_migration.py](development/qualification/qualification_migration.py)：已结束研究的多轮 fixture、矩阵与顺序兼容数据，不启动批次。
- [development/qualification/qualification_projection.py](development/qualification/qualification_projection.py)：包装共享产品投影并计算冻结资格指纹，不改变 Web History。
- [development/qualification/preset_tool_qualification.py](development/qualification/preset_tool_qualification.py)：维护者 Preset Tool 往返与概念题资格验证，不自动写 Evidence 或发布合同。
- [development/qualification/real_validation.py](development/qualification/real_validation.py)：`validate-real` 开发命令的网络诊断与显式模型参数 / 链路验证。

### 历史导入兼容层 · 不含独立实现

下列顶层文件指向开发子包中的同一个模块对象，保留历史导入和 monkeypatch；新代码使用上面的开发路径。

- [assistant_qualification.py](assistant_qualification.py)：Assistant 单次资格工具的旧路径别名。
- [qualification_adapter.py](qualification_adapter.py)：资格 Adapter 的旧路径别名。
- [qualification_history.py](qualification_history.py)：冻结资格 History 的旧路径别名。
- [qualification_migration.py](qualification_migration.py)：历史迁移资格 fixture 的旧路径别名。
- [qualification_projection.py](qualification_projection.py)：资格投影包装的旧路径别名。
- [preset_tool_qualification.py](preset_tool_qualification.py)：Preset 资格工具的旧路径别名。
- [real_validation.py](real_validation.py)：真实验证开发工具的旧路径别名。

## Resources · 随应用安装的固定资源

- [resources/knowledge/eel_knowledge.json](resources/knowledge/eel_knowledge.json)：当前项目渔业知识数据；[SOURCE.md](resources/knowledge/SOURCE.md) 记录来源限制。
- [resources/mock/profiles.json](resources/mock/profiles.json)：离线 Mock Runtime 配置。
- [resources/profiles/presets.json](resources/profiles/presets.json)：维护者发布的固定 Preset 合同。
- [resources/profiles/qwen_experimental.json](resources/profiles/qwen_experimental.json)、[deepseek_experimental.json](resources/profiles/deepseek_experimental.json)、[ollama_qwen35_local.json](resources/profiles/ollama_qwen35_local.json)：开发连接模板；不是用户 Saved Connection，也不自动恢复历史连接。
- [resources/scenarios/water_quality/](resources/scenarios/water_quality/)：`normal.json`、`low_oxygen.json`、`partial.json`、`stale.json`、`partial_stale.json` 五种确定性水质 Mock 场景。
- [resources/scenarios/detection/](resources/scenarios/detection/)：`normal.json`、`count_jump.json` 两种 Detection Mock 场景。
- [resources/tools/tool_policies.json](resources/tools/tool_policies.json)：包内 Analysis / Assistant 默认 Tool 权限。
- [resources/web/](resources/web/)：Web 页面、交互脚本与样式。

用户 Profile、Evidence、Experiment、Trace 在 Git ignored 的 `outputs/`；真实凭据在用户私有目录，均不是本页列出的包内资源。具体位置见[数据位置地图](../../docs/deep-dive/operations/PROJECT_DATA_AND_CONFIG_LOCATIONS.md)。

## 进一步阅读

- [完整项目地图](../../docs/STRUCTURE.md)：仓库中的源码、测试、脚本与文档位置。
- [Analysis / Assistant 架构](../../docs/deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md)：数据流与工作区边界。
- [只读 Tool 合同](../../docs/deep-dive/tools/READ_ONLY_TOOL_CALLING.md)：Registry / Policy / Executor 与单轮预算。
- [维护工具](../../scripts/README.md)：Qualification 入口、授权与开发边界。

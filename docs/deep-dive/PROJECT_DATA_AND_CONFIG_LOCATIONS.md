# 项目数据与配置位置地图

面向维护者的路径索引。Git 状态按仓库忽略规则与当前源码职责说明；outputs/ 和用户私有凭据的实际文件内容没有被读取。路径以项目根为基准，除明确标为用户私有路径外。

| 名称 | 作用 | 实际路径 | Git 跟踪 | 用户私有 | 运行时需要 | 可安全删除 / 重建 |
| --- | --- | --- | --- | --- | --- | --- |
| 水质诊断规则 / 阈值 | 温度、pH、DO 与 Quality/Freshness Finding | src/fishery_ai/domain.py | 是 | 否 | 是 | 否；源码合同 |
| 动态水质模拟入口 | sim-v1 合同、baseline / overrides、canonical Adapter | src/fishery_ai/telemetry/{models,simulator,adapter}.py；公共入口 __init__.py | 源码，本轮新增待提交 | 否 | 使用动态模拟时需要；现有 Web / Demo 不自动读取 | 不删除源码；模拟样本可重新生成，不产生本地数据文件 |
| 当前水质 Snapshot | 最后一次明确写入的 WaterQualityReading；未写入为 None | src/fishery_ai/telemetry/snapshot.py；实例数据仅在进程内存 | Store 源码待提交；内存数据不跟踪 | 否 | 新模拟入口 / 未来 current Tool 的共享数据源 | 进程退出即丢失；需再次明确写入，无自动 normal fallback |
| 水质 / Detection Mock Scenario | 固定演示数据与独立检测事件 | src/fishery_ai/resources/mock/scenarios.json | 是 | 否 | Demo / Web 测试需要 | 否；随包 fixture |
| Mock Profile 目录 | Mock / 开发连接定义 | src/fishery_ai/resources/mock/profiles.json；Composition 读取 | 是 | 否 | 离线 Demo 需要 | 否；源码资源 |
| RAG 检索实现 | TF-IDF baseline 与证据排序 | src/fishery_ai/knowledge.py | 是 | 否 | 是 | 否 |
| RAG / Knowledge 数据 | 知识条目和规则背景 | src/fishery_ai/resources/knowledge/eel_knowledge.json；来源缺口 src/fishery_ai/resources/knowledge/SOURCE.md | 是 | 否 | 是 | 否；无自动权威重建来源 |
| Preset 定义 / 版本 | 固定身份、Variants、允许组合、默认模型与维护 metadata | src/fishery_ai/resources/profiles/presets.json | 是 | 否 | Preset 模式需要 | 否；受审查的发布合同 |
| Provider 配置 | Provider / Auth / adapter 元信息 | src/fishery_ai/providers.py | 是 | 否 | Managed / Preset 连接校验需要 | 否 |
| 内置实验连接 | 开发 / Managed 兼容使用的 Qwen、DeepSeek、Ollama 连接模板 | src/fishery_ai/resources/profiles/qwen_experimental.json、deepseek_experimental.json、ollama_qwen35_local.json | 是 | 否 | 开发配置路径需要 | 否；不等同 Preset 发布合同 |
| ProtocolSpec | OpenAI-compatible 参数编码定义 | src/fishery_ai/protocol_specs.py | 是 | 否 | Managed 与 Preset 请求需要 | 否 |
| Managed Custom Profile | 用户连接参数、credential_ref 与运行偏好 | outputs/custom_profiles/custom-*.json | 否，Git 忽略 | 否；仅工作区本地数据 | 有已保存连接时需要 | 手动备份后可删除；不能由程序自动恢复 |
| Capability / Evidence | 精确 Identity 的 Probe / Metadata 证据 | outputs/capability-evidence/*.json | 否，Git 忽略 | 否；不含 Secret，但属本地验证数据 | Managed 高级选项解析需要 | 删除会丢失证据并锁定选项；不建议清理 |
| Runtime defaults | Custom 用户偏好；Preset 开发者默认值 | Custom：outputs/custom_profiles/*.json；Preset：src/fishery_ai/resources/profiles/presets.json 的 defaults | 分别否 / 是 | Custom 文件不是 ACL 私有凭据 | 有对应 Profile 时读取 | 删除 Custom Profile 会一起丢失偏好；谨慎 |
| 正式 Credential | Preset / Managed / Manual V1 的真实 Key 文件；本文不读取其值 | %LOCALAPPDATA%\Fishery_AI_Prototype\project-4e5f7b2702af5d742ab9\credentials\.env。ID 由固定项目根路径计算 | 否；在工作区外 | 是；用户私有 ACL | 需要 Cloud Auth 时 | 不可由清理任务删除；在 Web Credential Manager 显式管理 |
| Manual V2 Credential | Manual V2 独立 Key；不与正式凭据合并 | %LOCALAPPDATA%\Fishery_AI_Prototype\project-4e5f7b2702af5d742ab9\credentials\manual.env | 否；在工作区外 | 是；用户私有 ACL | 仅 V2 且目标需认证时 | 不可由清理任务删除；在 V2 页面显式管理 |
| Credential Writer 辅助文件 | revision lock、staging / recovery，和对应凭据同一私有目录 | credentials/.env.writer.lock、credentials/.env.stage-<id>/{new,original}；Manual 文件使用对应文件名 | 否 | 是 | 仅凭据写入期间 / 恢复时 | 仅确认 writer 已停止且无待恢复状态后人工处置 |
| Manual Experiment | V2 target、Raw Request、credential_ref 与说明 | outputs/manual-experiments/experiment-<id>.json | 否，Git 忽略 | 否；不存真实 Key | V2 选择该实验时 | 删除会丢失实验内容；先导出或备份 |
| Trace | Web、Mock CLI、real-validation 的安全运行追踪 | outputs/web-traces.jsonl、outputs/mock-traces.jsonl、outputs/real-validation-traces.jsonl | 否，Git 忽略 | 否；按字段白名单记录 | 运行分析时产生 | 停止应用并备份后可清理；无法自动重建历史 |
| Preset qualification 输出 | 维护者精确本地资格检查摘要 | outputs/preset-qualification/*.json | 否，Git 忽略 | 否；摘要不含 Key / 完整模型正文 | 仅维护者工具生成 | 先备份；如需重测可重新授权执行，但不会自动重建旧记录 |
| 保留的维护脚本 | 精确 Ollama 单项 qualification；不进入 Web 启动 | scripts/qualify_local_preset_request.py | 是 | 否 | 正常运行不需要 | 可从源码恢复；运行时输出另存 outputs/ |
| 自动测试及 fixture | 回归测试和兼容性历史夹具 | tests/、tests/fixtures/r0_runtime_baseline.json、tests/fixtures/historical_model_assets/ | 是 | 否 | 正常运行不需要；开发必须保留 | 不删除；fixture 用途见其 README |
| 虚拟环境 / Python 缓存 | 本机依赖和可重建字节码 | .venv/、__pycache__/、*.pyc | 否，Git 忽略 | 否 | 仅开发环境 | 停止相关进程后可删除；虚拟环境可按 BUILD_RUN 重建 |
| 旧源码根 .env | 历史本地文件；当前运行入口禁止读取、迁移或 fallback | 项目根 .env | 否，Git 忽略 | 否；应用不提供私有 ACL 保障 | 否 | 本轮未检查它是否存在，也不自动删除/迁移；仅由用户自行处置 |

## 路径规则

用户私有目录由 src/fishery_ai/credential_paths.py 从应用固定项目根和 LOCALAPPDATA 生成；网页、Profile 或 Model 输入不能指定目录。CredentialStore / ProjectEnvWriter 位于 credentials.py / project_env.py。PROCESS_ENV 是外部只读来源；应用不使用 load_dotenv。

outputs/ 虽被 Git 忽略，仍可能含用户维护的 Profile、Evidence、实验和历史 Trace，不可把“忽略”理解为“随时可删”。自动测试使用临时目录和虚构凭据，不读取真实 Credential。

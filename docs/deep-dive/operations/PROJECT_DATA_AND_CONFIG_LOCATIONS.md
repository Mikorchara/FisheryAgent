# 项目数据与配置位置地图

维护者索引。源码路径以仓库根目录为基准；用户私有凭据只记录固定位置规则与用途，不读取或记录其值。Git 跟踪状态以仓库清单和 `.gitignore` 为准。

| 名称 | 作用 | 实际路径 | Git 跟踪 | 用户私有 | 运行时需要 | 可安全删除 / 重建 |
| --- | --- | --- | --- | --- | --- | --- |
| 水质诊断阈值 | 温度、pH、DO finding 与规则版本 | `src/fishery_ai/domain.py` | 是 | 否 | Analysis / 查询 Tool 需要 | 不可删除；业务合同 |
| 水质 Scenario 模板 | 内置 normal、low_oxygen、partial、stale、partial_stale 输入 | `src/fishery_ai/resources/scenarios/water_quality/*.json` | 是 | 否 | Web / Demo 水质输入需要 | 源码资源，不应删除 |
| User Scenario 模板 | 用户保存的输入模板，不是当前 Snapshot | `outputs/scenario_templates/water_quality/<safe-id>.json` | 否（Git 忽略） | 否；本机用户数据 | 选择用户模板时需要 | 删除会丢失用户内容，先备份 |
| Telemetry / 当前 Snapshot | sim-v1 合同、模拟器、Adapter；Store 是进程内最后明确写入的 Reading | `src/fishery_ai/telemetry/` | 是 | 否 | Web / Demo 运行需源码；Snapshot 仅进程内 | 源码不可删；Snapshot 重启即空，需重新 Apply |
| Detection Mock | 固定 normal / count_jump DetectionEvent fixture；没有 Detection Simulator | `src/fishery_ai/resources/scenarios/detection/*.json` | 是 | 否 | 对应演示/测试需要 | 源码 fixture，不应删除 |
| Knowledge / RAG | TF-IDF 实现与鳗鱼知识条目 | `src/fishery_ai/knowledge.py`；`src/fishery_ai/resources/knowledge/eel_knowledge.json`、`SOURCE.md` | 是 | 否 | Analysis 需要 | 不应删除；没有自动恢复完整权威来源 |
| Preset 合同 | 精确身份、Capability、Variants、默认值、维护记录 | `src/fishery_ai/resources/profiles/presets.json`；加载器 `presets.py` | 是 | 否 | Preset / Assistant 需要 | 不应删除；发布合同 |
| Assistant 多轮发布配置 | 启动冻结的 Flag、candidate / released 精确范围与资格依据；不是用户 Policy | `src/fishery_ai/resources/profiles/assistant_execution.json`；`assistant_execution.py` | 随代码纳入 Git | 否；不含 Key | Web 启动需要 | 不应删除；默认关闭，可关 Flag 后重启回滚 |
| Provider 与 ProtocolSpec | Provider/Auth 元数据和请求参数编码 | `src/fishery_ai/providers.py`、`src/fishery_ai/protocol_specs.py` | 是 | 否 | 正式模型请求需要 | 不应删除 |
| Managed / 实验连接模板 | 包内开发连接 profile；不是发布 Preset | `src/fishery_ai/resources/profiles/{qwen_experimental,deepseek_experimental,ollama_qwen35_local}.json` | 是 | 否 | 对应开发连接使用时需要 | 源码资源，不应删除 |
| 用户 Managed Custom Profile | 用户连接参数、`credential_ref` 和 Runtime 偏好 | `outputs/custom_profiles/custom-*.json` | 否（Git 忽略） | 否；不含真实 Key | 选择用户连接时需要 | 删除会丢失 Profile / 偏好，先备份 |
| Capability Evidence | 精确 Identity 的 metadata / Probe 证据 | `outputs/capability-evidence/*.json` | 否（Git 忽略） | 否；本机维护证据 | Managed 高级能力解析需要 | 删除会丢失证据并锁定能力，勿常规清理 |
| User Tool Policy | Analysis / Assistant 对 Registry Tool 的用户选择 | `outputs/tool-policies/tool_policies.json` | 否（Git 忽略） | 否；本机用户设置 | Web 创建新请求时读取 | UI 可恢复包内默认；删除自定义选择前先确认 |
| Manual Experiment | Manual V2 目标、Raw JSON 与 `credential_ref` | `outputs/manual-experiments/experiment-*.json` | 否（Git 忽略） | 否；不存 Key | Manual V2 使用时需要 | 删除会丢失实验配置，先导出/备份 |
| 正式 Credential | Preset / Managed / Manual V1 Key；优先级 PROCESS_ENV > 私有 PROJECT_ENV > MISSING | `%LOCALAPPDATA%\Fishery_AI_Prototype\project-<stable-id>\credentials\.env` | 否；工作区外 | 是 | Cloud Auth 请求需要 | 不由项目清理删除；用 Credential Manager 管理 |
| Manual V2 Credential | V2 独立 Key，不与正式 Credential Store 合并 | `%LOCALAPPDATA%\Fishery_AI_Prototype\project-<stable-id>\credentials\manual.env` | 否；工作区外 | 是 | 仅需认证的 Manual V2 请求 | 不由项目清理删除；在 V2 页面管理 |
| Credential Writer 辅助文件 | 凭据写入锁、staging 与恢复资料 | 同一私有 `credentials/` 目录下的 `.env.writer.lock` / 对应 stage 文件 | 否；工作区外 | 是 | 写入 / 恢复期间 | 仅 writer 已停止且无恢复状态后人工处置 |
| Trace | Web、Mock Demo、真实验证的安全运行事件 | `outputs/web-traces.jsonl`、`mock-traces.jsonl`、`real-validation-traces.jsonl` | 否（Git 忽略） | 否；字段受白名单限制 | 相应运行路径产生 | 历史不可自动重建；清理前备份 |
| Preset Qualification 记录 | 维护者单项/Tool Qualification 安全摘要 | `outputs/preset-qualification/` | 否（Git 忽略） | 否；不含 Secret | 维护者脚本运行时产生 | 重测可产生新记录；旧证据不可自动重建，先备份 |
| Assistant Qualification 记录 | 单次来源验证与已结束的 History A/B 安全报告 | `outputs/assistant-qualification/` 下 `history/`、`projection-ab/`、`cross-model/`、`product-migration/`、`archive/` 等分区 | 否（Git 忽略） | 否；不保存模型正文或凭据 | 日常 Web 不需要；研究/审计产生 | 原样本不可自动重建；不可按旧授权重跑或自动清理 |
| History Projection / Source Contract | 默认 B、内部 A 回滚；真实执行 Receipt 与来源要求 | `src/fishery_ai/history_projection.py`、`src/fishery_ai/assistant_sources.py` | 是 | 否 | Assistant 需要 | 不应删除；当前产品合同 |
| 当前文档 / 历史记录 | 当前架构与运行说明；已结束阶段的证据原文 | `docs/deep-dive/`、`docs/records/`、`docs/records/archive/` | 是；新文档须显式纳入 Git | 否 | 运行时不读取 | 历史研究与独立审计先判断唯一信息，不自动删除 |
| 维护者脚本 | 显式单项 / Preset Tool Qualification | `scripts/qualification/qualify_local_preset_request.py`、`scripts/qualification/qualify_preset_tools.py` | 是 | 否 | 日常 Web 不需要 | 源码可从 Git 恢复；请求需用户显式确认 |
| 自动测试与 Fixtures | Python / Browser 回归和历史兼容性夹具 | `tests/`、`tests/fixtures/` | 是 | 否 | 正常运行不需要；开发回归需要 | 保留测试；夹具用途见 `tests/fixtures/historical_model_assets/README.md` |
| 虚拟环境 / Python 缓存 | 本机依赖与字节码 | `.venv/`、`__pycache__/`、`*.pyc` | 否（Git 忽略） | 否 | 仅开发环境 | 可重建；删除 venv 后按 BUILD_RUN 重装依赖 |
| 旧源码根 `.env` | 非运行时文件；不得被 CredentialStore fallback、迁移或自动删除 | 项目根 `.env` | 否（Git 忽略） | 不保证私有 ACL | 否 | 本地图不检查其存在或内容；仅由用户自行处置 |

## 路径与保留规则

- Credential 路径由 `src/fishery_ai/credential_paths.py` 根据应用固定项目根与用户目录生成；Web、Profile、model 或 experiment 不能指定任意路径。Flask 不加载 dotenv，不修改 `os.environ`。
- `outputs/` 被 Git 忽略但包含可恢复性不同的用户数据；忽略状态不等于可删除。先判断类型并备份。
- tests 使用临时存储与虚构凭据。它们不读取真实凭据文件，也不发真实模型请求。

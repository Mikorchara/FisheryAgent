# 管理 Assistant 业务 Runtime

R2C-1D后由正式ManagementAssistantService直接使用；通用执行由 [ai_backend](../../ai_backend/README.md) 负责，业务层不复制循环。

- `assistant.py`：原两版业务Prompt、History完整pair裁剪、Source/Trace Commit Gate。
- `sources.py`：原Requirement/Receipt/Ledger，只从本轮新Backend执行步骤认证来源。
- `tools.py`：两工具Definition、query validator与Knowledge映射；评分仅为已知存储名称，无Handler。
- `activity.py`、`catalog.py`：固定安全摘要和显示metadata，委托Backend通用步骤投影。
- `policy.py`：完整旧格式选择与安全存储，执行与实际绑定求交；评分项不丢失，不扩授权。
- `presets.py`、`resources/`：固定Preset和默认Policy，自有资源，不读取Prototype发布合同。
- `locations.py`：原project root身份/私有目录算法，用新Backend Location类型。
- `release_contracts.py`、`streaming_contracts.py`：原发布dataclass/精确Scope及hash，无第二套发布JSON。
- `tests/`：来源/History/执行/协议差分；顶层Service/Scope/管理资格测试在上一级tests。

唯一业务装配位于 [service.py](../service.py)；PreparedTurn在 [contracts.py](../contracts.py)，Monitoring/Knowledge绑定在 [bindings.py](../bindings.py)，管理发布文件由上一级execution.py/streaming.py加载。Phase I的assembly/contracts/bindings/execution/streaming重复模块已移除，不设置兼容别名。

依赖为Web → AI Service → Backend；Handler → Monitoring / 原KnowledgeService。暂留旧领域依赖仅包括Diagnosis/telemetry/Reading、Knowledge/Evidence/资源、sources中的Quality/Freshness，连带旧model_options；不调用旧Assistant/Gateway/Adapter/Executor/Handle/ContextVar。阻断这些旧执行模块后，实际HTTP/SSE及管理资格Fake测试仍通过。

资格观察器在上一级development，使用新Backend，正式启动不加载它。既有真实资格记录仍属于旧Runtime；新计划@2改变授权hash，不改Scope或既有记录，不自动联网。

R2C-1E：用户已报告新 Backend 的 Qwen Normal 水质查询、Streaming 水质 + Knowledge 与最终提交基本网页验收通过。迁移主线已结束；这不替代回答质量专项审核，不增加 Provider 资格或发布范围。Monitoring/Knowledge 领域独立化留待后续任务。

验证：`python scripts/dev/run_tests.py backend`。当前执行路径、指纹与回滚见 [实施记录](../../docs/deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md#14-r2c-1d-phase-ii-管理端整体切换)。

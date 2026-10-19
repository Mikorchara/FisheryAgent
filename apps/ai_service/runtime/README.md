# 管理 Assistant 业务 Runtime

R2C-1D后由正式ManagementAssistantService直接使用；通用执行由 [ai_backend](../../ai_backend/README.md) 负责，业务层不复制循环。

这里的 runtime 指业务 Assistant 合同，不是第二套通用 Runtime。Tool、Prompt、参数扩展步骤见 [开发指南](../../docs/deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)。不要在本目录添加 Gateway、Streaming Assembler 或新的执行循环。

- `assistant.py`：原两版业务Prompt、History完整pair裁剪、Source/Trace Commit Gate。
- `sources.py`：Requirement/Receipt/Ledger，只从本轮新Backend执行步骤认证来源；历史操作及可靠历史观测独立于当前观测。
- `activity.py`、`catalog.py`：固定安全摘要和显示metadata，委托Backend通用步骤投影。
- `policy.py`：默认/用户 Tool 选择校验与安全存储，执行与实际绑定求交；评分项不丢失，不扩授权。参数 validator 由各 business_tools 模块声明，不在 Policy 中。
- `presets.py`、`resources/`：固定Preset和默认Policy，自有资源，不读取Prototype发布合同。
- `locations.py`：原project root身份/私有目录算法，用新Backend Location类型。
- `release_contracts.py`、`streaming_contracts.py`：原发布dataclass/精确Scope及hash，无第二套发布JSON。
- `tests/`：来源/History/执行/协议差分；顶层Service/Scope/管理资格测试在上一级tests。

唯一业务 Service 装配位于 [service.py](../service.py)；PreparedTurn 在 [contracts.py](../contracts.py)，业务 Tool 统一由 [business_tools/registry.py](../business_tools/registry.py) 装配。水质 Definition / capture / DTO 在 [current_water_quality.py](../business_tools/current_water_quality.py)，Knowledge Definition / validator / Handler 在 [fishery_knowledge.py](../business_tools/fishery_knowledge.py)；评分只为 registry 中的已知 Policy 名称，无 Handler。管理发布文件由上一级 execution.py/streaming.py 加载。

旧顶层 bindings.py 和本目录 tools.py 已移除，真实调用方迁到各 Tool owner / registry，不留 re-export/Alias；Policy、Receipt/Ledger、Activity/Catalog 和提交职责仍留本目录。

R2D-1G 的 [历史 Tool](../business_tools/water_quality_history.py) 由 bind_tools(include_history=True) 显式装配，默认请求Registry仍仅两工具。history_execution.py 绑定Qwen OFF / Normal / 历史单工具 / 1024 / 1/1/2 / retry=0 / 120秒，local_experimental但默认关闭；`--assistant-history-trial`与管理Policy opt-in均必需。共享格式仍拒绝历史名称。管理HTTP只接受固定Profile及对应revision，不能指定预算；Service以同一Assistant/Executor和产品Adapter预算编码执行，不使用development Adapter。15个真实样本技术通过，回答质量未审、非released，见[资格与试用记录](../../docs/deep-dive/HISTORY_QUALIFICATION.md#9-r2d-1g真实批次通过与本地实验开放)。开发CLI保留独立关闭candidate计划，后续真实执行仍需新授权。

同名文件要按层定位：顶层 execution.py 是 Normal 发布/Scope/revision，streaming.py 是 Streaming 发布/Scope；通用请求取消/Deadline 在 ai_backend/execution.py，HTTP SSE worker 在 management_web/streaming.py。顶层 contracts.py 是进程内 PreparedAssistantTurn / AssistantBackend 业务合同，不是 Web DTO。

依赖为Web → AI Service → Backend；Handler → Monitoring / apps.knowledge统一SQLite与独立TF-IDF。MIG-1 将 sources 的 Quality/Freshness/Reading/parse_time 统一到 monitoring.water_contracts，Monitoring 自有 Diagnosis/Reader，正式管理链不再导入任何 fishery_ai 模块。新进程阻断整个旧包后验证管理 HTTP/SSE 三工具与知识 SQLite；历史资格/迁移及新旧差分测试另保留有意的旧依赖。

资格观察器在上一级development，使用新Backend，正式启动不加载它。既有真实资格记录仍属于旧Runtime；新计划@2改变授权hash，不改Scope或既有记录，不自动联网。

R2C-1E：用户已报告新 Backend 的 Qwen Normal 水质查询、Streaming 水质 + Knowledge 与最终提交基本网页验收通过。迁移主线已结束；这不替代回答质量专项审核，不增加 Provider 资格或发布范围。Monitoring 领域独立化已由 MIG-1 完成；Knowledge 在 R2D-3B 脱离旧实现，旧 JSON 仅作显式迁移/历史资格夹具。

验证：`python scripts/dev/run_tests.py backend`。当前执行路径、指纹与回滚见 [实施记录](../../docs/deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md#14-r2c-1d-phase-ii-管理端整体切换)。

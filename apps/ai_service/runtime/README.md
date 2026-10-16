# 新 Backend 的业务装配

R2C-1C Phase I 的真实业务实现，当前未被管理 Web 引用。顶层 `apps.ai_service.service.ManagementAssistantService` 和 Web 仍按原方式工作；这里没有旧 Runtime fallback 或每请求选择器。

- `assistant.py`：原业务 Assistant / 两版 Prompt、完整 pair 裁剪和最终 Trace/Source Commit Gate。
- `sources.py`：原 SourceRequirement / Receipt / Ledger，认证每次真实执行，不从正文或历史推断。
- `tools.py`、`bindings.py`：原两工具 Definition/query validator/Knowledge 映射及 Monitoring capture DTO；一个静态 Registry 只绑定水质/Knowledge。评分只有合法存储名称和来源合同，无 Handler。
- `activity.py`、`catalog.py`：原安全业务摘要；委托 Backend 的通用步骤投影。
- `presets.py`、`resources/`：自有固定 Preset 和默认 Policy 资源，初始逐字一致；不读取旧 Preset 发布资源。
- `policy.py`：保留完整旧格式选择，已知评分项不丢失；执行时与实际绑定求交，完整选择仍进入确认 revision；不读取/改写真实用户文件进行迁移。
- `locations.py`：原项目身份与私有目录算法，用新底层 Location 类型；不移动或读取凭据。
- `release_contracts.py`、`streaming_contracts.py`：原发布合同与哈希计算，无额外发布资源。
- `execution.py`、`streaming.py`：读取上一级现有管理发布 JSON，精确 Scope/预算/revision，默认关闭不变。
- `contracts.py`、`assembly.py`：Prepared Turn 和新侧 IndependentAssistantService；由显式配置装配 Backend，冻结设备/Policy/Runtime，复用原唯一循环。`request_registry()` 固定安全摘要；不是 Web 新入口。
- `tests/`：新 Fake SDK 端到端、History/来源、Policy/Scope、旧新差分和提交门禁。

依赖方向：新侧 Assistant / 装配 → [ai_backend](../../ai_backend/README.md)；业务 Handler → Monitoring / 原 KnowledgeService。Backend 不反向 import 本包。

明确保留的领域债务：Monitoring 的 Diagnosis/telemetry/canonical Reading，KnowledgeService 及其 Evidence/资源，业务 sources 的 Quality/Freshness/Reading。它们会连带加载旧 model_options，但新 Turn 不调用旧 Assistant/Gateway/Adapter/Executor/Credential/ContextVar；独立进程阻断这些旧 LLM 模块仍可完成六条 Fake Normal/Streaming 路径。它不表示已能卸载整个 fishery_ai distribution。

Phase II 才统一切换 Web、请求控制、管理 qualification 与服务合同；当前没有资格 CLI 调用本新侧实现。旧 qualification 报告继续属于旧 Runtime，不能改写证据归属。新侧真实 smoke 仍须新授权。

运行：`python scripts/dev/run_tests.py backend`。Prompt、History、Schema、Scope 指纹及安装限制见 [Backend 源码入口](../../ai_backend/README.md)。

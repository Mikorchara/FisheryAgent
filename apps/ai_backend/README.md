# AI Backend 源码入口

R2C-1C Phase I 已建立新侧闭包。起点为 `d88dbf34f6f20f7dcfe62f828bbf78970acfc7c2` 的既有实现，选择性分叉，不重写执行算法。旧 Prototype 保留自身实现；参数诊断已撤销共享 Alias。R2C-1D Phase II 已将管理 Web / ManagementAssistantService / SSE / 资格入口统一切到这里；旧 Prototype 仍独立。

扩展 Tool、Prompt 与执行配置先看 [AI Backend 与 Assistant 开发指南](../docs/deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)。本 README 只定位通用实现；业务 Assistant 在 ai_service/runtime，HTTP SSE worker 在 management_web。

## 模块与公共边界

| 模块 | 职责 |
|---|---|
| `contracts.py` | Mode / Status、Usage / SessionUsage / UsageAccumulator、RuntimeInfo 与 UTC 时间辅助，不含 Web Protocol 或领域 Facts |
| `model_options.py` | 生成/Thinking 选项、能力状态及校验，不负责业务授权 |
| `model_gateway.py`、`providers.py`、`protocol_specs.py` | 新消息/Tool/快照/错误类型、固定 Provider 元数据和原编码 |
| `openai_compatible_adapter.py`、`manual.py` | 原 SDK Normal/Streaming/Assembler/Raw 传输；不开放管理 Manual UI |
| `execution.py` | 独立 ContextVar、RequestHandle/Registry、唯一 claim、Stop、整 Turn deadline |
| `tool_conversation.py` | 原 Steps / Budget / ToolCallingService 循环；显式 Policy，1/1/2 或 2/2/3 |
| `tools/contracts.py` | ToolStatus / ToolError、Definition 的 Handler/validator 绑定、ToolExecutionResult，不是模型消息或 HTTP DTO |
| `tools/registry.py`、`policy.py`、`executor.py` | 静态绑定索引、不可变授权、参数/去重/执行/结果限额；无默认业务 Handler 或配置文件 |
| `history_projection.py` | 已裁剪完整 pair 的原 B 投影及 A 回滚，不二次裁剪 |
| `assistant_activity.py`、`assistant_events.py` | 有界安全 Steps、固定业务摘要回调、原有序事件与临时预览；不含发布配置或 HTTP |
| `observability.py` | Tool/Assistant 安全 JSONL，Tool 名单显式提供，不含 Analysis 专用入口 |
| `credentials.py`、`credential_paths.py`、`secure_files.py` | 原 Store/Snapshot、底层私有位置检查及文件安全；应用路径组合留服务层 |
| `project_env.py` | 沿用既有固定路径凭据写入算法：格式保留、CAS、互斥、私有 ACL、原子替换与失败恢复；不包含 HTTP 或业务 Provider 授权 |
| `tool_argument_diagnostics.py` | 独立的参数阶段/拒因及安全字段 |
| `tests/` | 独立 Fake SDK、协议/Assembler、取消/凭据、闭包与类型隔离测试；不打包 |

Backend 不导入 `fishery_ai`、业务、Flask、Monitoring、Knowledge、SQLite。不通过延迟导入绕过边界。SDK、httpx、dotenv 仍为原有依赖；导入不读取凭据或配置、不建立网络连接。

调用方提供新 `ModelProfile` / `CredentialStore`、静态 `ToolDefinition` 和显式 `ToolPolicy`，构造唯一 `ToolCallingService`，调用 `run_request(ModelRequest, RuntimeSnapshot)`。水质 Mock、默认业务 Prompt、`converse`、Managed Evidence JSON loader 和 Analysis Trace 未迁入；本包没有这些发布入口。

## 服务层装配

[apps/ai_service/runtime](../ai_service/runtime/README.md) 保存业务 Assistant、Prompt、Preset/Policy、领域 Receipt/Ledger、Commit Gate 及发布计算。顶层 `ai_service/service.py` 负责唯一业务装配，[business_tools/registry.py](../ai_service/business_tools/registry.py) 统一绑定 Monitoring/Knowledge，各 Tool 模块拥有 Definition / Handler / DTO；`execution.py` / `streaming.py` 加载管理发布配置。业务捕获仍允许既有领域/Knowledge 依赖，Backend 本身完全闭合。

RequestHandle/RequestRegistry 可在构造时固定 `summarize_tool`，只接收既有安全字段；不会接受浏览器或模型提供的回调/metadata。Trace 构造时显式传 `tool_names`。不共享旧对象、取消 Owner 或类异常；新 Registry 拒绝旧 Definition，ProfileRegistry/request_scope 拒绝旧运行类型。

## 合同基线

以下 SHA-256 仅记录迁移来源/合同，不授予新资格。Prompt 使用既有 canonical JSON hash；Notice 为 UTF-8 文本 hash；配置为原文件字节 hash。

| 项目 | SHA-256 |
|---|---|
| 单轮 Prompt ASSISTANT_V2@1 | `4452b6353dd3a20d34e0c2d741601ebdcfb155427e49245dcf48ac64ed8b60e8` |
| 多轮 Prompt ASSISTANT_BOUNDED_MULTI_ROUND@1 | `51906f193e00749e4a6cf6c1f067e65798252b49c9a352ddf1b44139cd54b066` |
| History UNTRUSTED_TRANSCRIPT_V1@1 Notice | `9e288b9965e7142bd2d817ad5571ec48e62679477a76ad3d830d34cb538ad42c` |
| 水质 + Knowledge Definition/schema | `5cd73fefcd80a73f1024f40f6eb60da9d302fe8bd2deb5bc578e0095ea91e854` |
| Qwen 管理 Streaming 完整 Scope | `fc476b2e9ac19046b0127e65d70dc1488016c04f9dde29698d681c6047708e90` |
| Preset 固定资源 | `30aa3ce86c42ffaf6e50adee6fbe3e3ab44cc5dccd2adfef7dd4d4d4207fce19` |
| 管理 Normal 发布文件 | `5e25d73888fb2bbac3501a196eaf9dc1269b1065503445e36201b008d750c17b` |
| 管理 Streaming 发布文件 | `b19ce6a36afb44ce6030302928356656bfe34fedaf20e24f1c7c4d43f5f2d903` |

固定 epoch、设备、完整 Policy 下新旧 Scope/revision 对拍一致；Qwen 仍为精确两 Tool local_experimental，Streaming 默认关闭、512 / request、2/2/3、retry=0、120 秒。迁移离线测试没有请求真实 Provider；R2C-1E 用户另行报告新侧 Normal / Streaming 基本网页验收通过，未因此改写历史资格或升级发布状态。

## 验证与安装

```powershell
.\.venv\Scripts\python.exe scripts/dev/run_tests.py backend
.\.venv\Scripts\python.exe scripts/dev/run_tests.py fast
.\.venv\Scripts\python.exe scripts/dev/run_tests.py product
```

`backend` 覆盖 Backend、runtime业务合同及顶层Service/发布/迁移边界；product 纳入该组一次，不重复继承收集。迁移差分以独立旧/新 Turn 比较协议、Tool JSON、Steps、Usage、Ledger、DTO/提交；仅剔除随机 ID 与运行耗时。它是本次迁移证据，不要求未来两个平台自动同步。

pyproject 明确打包 Backend、AI Service、Monitoring、Simulator、Management Web及业务JSON/静态资源，排除所有apps测试；没有使用宽泛apps.*。新旧平台在同一个wheel分发，但管理Turn不调用旧LLM实现。领域/Knowledge依赖仍在业务侧。

正式PEP517 wheel已用本机缓存的setuptools84.0.0在工作区隔离venv中构建/安装；没有联网或改现有.venv，build-system仍要求setuptools>=68。内容/CRC和隔离导入、Fake流程见 [实施记录§14](../docs/deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md#14-r2c-1d-phase-ii-管理端整体切换)。不是build_py替代验收。

## 当前装配与回滚

顶层 service.py 拥有唯一 ManagementAssistantService；contracts/execution/streaming 保留进程内合同与发布装配，business_tools/registry 统一装配各 Tool 模块。Phase I 重复装配及旧 bindings / runtime.tools 已移除，不留 Alias。Web 的 RequestRegistry、Handle、异常、SSE、worker ContextVar 全部来自本包；业务安全摘要由固定回调提供。

管理qualification观察器已独立到ai_service/development，继承这里的Adapter/Assembler；新计划为management-streaming-qualification@2并绑定apps.ai_backend@1，旧plan-sha授权失效。Scope/Prompt/Schema/预算未变，不改写既有真实报告或升级资格。

源码启动仍使用原project root；wheel安装入口从有效工作区定位，无法确认时拒绝WORKSPACE_REQUIRED，避免写到site-packages或改变私有凭据身份。应用启动与回滚见 [BUILD_RUN](../docs/BUILD_RUN.md)。

R2C-1E 已完成工程收尾：用户报告 Qwen Normal 水质 Tool / Final、Streaming 水质 + Knowledge / Final 提交，以及模拟来源 / PROTOTYPE 标签正常。它是基本人工观察，未生成新的 Provider 资格记录，回答质量专项审核仍独立进行。迁移主线结束，下一阶段可开展管理业务开发。

仅关闭试用时去掉 trial 启动参数并重启，仍使用本 Backend。代码整体回滚基线为 Phase I `0cf64f6`；应完整撤销 Phase II `a256569` 的切换范围并重启新 epoch，不单独替换 Adapter/Handle，不自动重发，不修改 SQLite、Policy、凭据或报告。本轮只核对回滚方案，不执行回滚；详见 [迁移收尾记录](../docs/deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md#15-r2c-1e-工程收尾与人工验收)。

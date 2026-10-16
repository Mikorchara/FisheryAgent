# AI Backend 源码入口

R2C-1C Phase I 已建立新侧闭包。起点为 `d88dbf34f6f20f7dcfe62f828bbf78970acfc7c2` 的既有实现，选择性分叉，不重写执行算法。旧 Prototype 保留自身实现；参数诊断已撤销共享 Alias。**现有管理 Web / ManagementAssistantService 尚未切换**，Phase II 另行批准。

## 模块与公共边界

| 模块 | 职责 |
|---|---|
| `contracts.py`、`model_options.py` | 中立 Usage / RuntimeInfo / 选项和能力合同，不含领域 Facts |
| `model_gateway.py`、`providers.py`、`protocol_specs.py` | 新消息/Tool/快照/错误类型、固定 Provider 元数据和原编码 |
| `openai_compatible_adapter.py`、`manual.py` | 原 SDK Normal/Streaming/Assembler/Raw 传输；不开放管理 Manual UI |
| `execution.py` | 独立 ContextVar、RequestHandle/Registry、唯一 claim、Stop、整 Turn deadline |
| `tool_conversation.py` | 原 Steps / Budget / ToolCallingService 循环；显式 Policy，1/1/2 或 2/2/3 |
| `tools/contracts.py`、`registry.py`、`policy.py`、`executor.py` | 显式静态绑定、参数与授权、去重、执行和结果限额；无业务 Handler/默认文件 |
| `history_projection.py` | 已裁剪完整 pair 的原 B 投影及 A 回滚，不二次裁剪 |
| `assistant_activity.py`、`assistant_events.py` | 有界安全 Steps、固定业务摘要回调、原有序事件与临时预览；不含发布配置或 HTTP |
| `observability.py` | Tool/Assistant 安全 JSONL，Tool 名单显式提供，不含 Analysis 专用入口 |
| `credentials.py`、`credential_paths.py`、`secure_files.py` | 原 Store/Snapshot、底层私有位置检查及文件安全；应用路径组合留服务层 |
| `tool_argument_diagnostics.py` | 独立的参数阶段/拒因及安全字段 |
| `tests/` | 独立 Fake SDK、协议/Assembler、取消/凭据、闭包与类型隔离测试；不打包 |

Backend 不导入 `fishery_ai`、业务、Flask、Monitoring、Knowledge、SQLite。不通过延迟导入绕过边界。SDK、httpx、dotenv 仍为原有依赖；导入不读取凭据或配置、不建立网络连接。

调用方提供新 `ModelProfile` / `CredentialStore`、静态 `ToolDefinition` 和显式 `ToolPolicy`，构造唯一 `ToolCallingService`，调用 `run_request(ModelRequest, RuntimeSnapshot)`。水质 Mock、默认业务 Prompt、`converse`、Managed Evidence JSON loader 和 Analysis Trace 未迁入；本包没有这些发布入口。

## 服务层装配

[apps/ai_service/runtime](../ai_service/runtime/README.md) 保存实际的新侧业务 Assistant、原 Prompt、Preset/Policy、领域 Receipt/Ledger、Commit Gate、Monitoring/Knowledge 绑定及发布解析。它调用本 Backend。业务捕获仍允许既有领域/Knowledge 依赖，Backend 本身完全闭合。

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

固定 epoch、设备、完整 Policy 下新旧 Scope/revision 对拍一致；Qwen 仍为精确两 Tool local_experimental，Streaming 默认关闭、512 / request、2/2/3、retry=0、120 秒。未修改资格记录，未请求真实 Provider；历史技术证据不等于新侧真实验收。

## 验证与安装

```powershell
.\.venv\Scripts\python.exe scripts/dev/run_tests.py backend
.\.venv\Scripts\python.exe scripts/dev/run_tests.py fast
.\.venv\Scripts\python.exe scripts/dev/run_tests.py product
```

`backend` 覆盖 Backend 与新业务合同；product 纳入该组一次，不重复继承收集。迁移差分以独立旧/新 Turn 比较协议、Tool JSON、Steps、Usage、Ledger、DTO/提交；仅剔除随机 ID 与运行耗时。它是本次迁移证据，不要求未来两个平台自动同步。

pyproject 明确打包 `apps.ai_backend.*` 并排除其 tests；没有用 `apps.*` 意外装入 Web/业务/运行数据。业务层当前仍从仓库运行，尚非完整安装包。独立进程禁止全部 fishery_ai 后，Backend Fake Normal/Streaming 均通过；安装布局所有 Backend 子包导入通过。

当前虚拟环境无 setuptools / wheel / build，离线 wheel 命令失败于缺少 build backend；未联网安装或降低 setuptools>=68 要求。系统 setuptools 65.5 的 build_py 可校核安装清单，但不替代正式 wheel 验收；Phase II 前需在具备要求的离线构建环境补齐。

## Phase II 与回滚

切换前统一处理 ai_service 顶层 contracts/service、Web RequestRegistry/异常/SSE、CLI 与管理 qualification 的新类型，补真实 HTTP Fake SDK/前端回归及安装清单。不能只替换 Adapter 或在同一 Session 混用两套 Handle。新的 epoch 使旧确认失效，不自动重发请求。

Phase I 没有修改管理生产入口，也未迁移用户数据；现有管理启动/回滚命令不变。撤销本轮时按本轮差异逐文件恢复工程/文档/测试和旧诊断，新增新侧文件可保留未引用；不重置工作树、不改 SQLite、Policy、凭据或既有报告。完整策略见 [获批方案](../docs/deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md)。

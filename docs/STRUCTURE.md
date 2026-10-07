# 项目结构

本页描述当前仓库的实际职责。更细的水质数据边界、模型合同和运行数据路径见下方专题文档。

```text
Fishery_AI_Prototype/
├─ src/fishery_ai/       Runtime + Core：可安装应用、领域逻辑、网关和包资源
├─ tests/                Development：离线自动回归与测试夹具
├─ scripts/              Development：需显式确认的维护者验证工具
├─ docs/                 用户与维护者文档
├─ outputs/              Generated：本机用户配置、trace 与验证输出，Git 忽略
└─ %LOCALAPPDATA%/...    User-private：正式凭据与 Manual V2 独立凭据
```

## 主要区域

| 区域 | 内容与边界 |
| --- | --- |
| Runtime | `__main__.py`、`web.py` 与 `resources/web/` 提供 CLI、Developer Web UI 和本地静态资源。Web 默认绑定本机回环地址。 |
| Core | `contracts.py`、`domain.py`、`application.py`、`knowledge.py`、`model_gateway.py`、`openai_compatible_adapter.py`、`presets.py`、`protocol_specs.py`、`credentials.py`、`assistant.py` 等实现领域合同、分析、模型调用与应用服务。 |
| Telemetry | `telemetry/` 将情景输入模拟并转换为 canonical `WaterQualityReading`；`CurrentSnapshotStore` 保存进程内最后一次明确写入，`CurrentWaterQualityReader` 在查询时重新评估 freshness。 |
| Tools | `tools/` 保存静态 allowlist、Catalog、Policy、Executor 和当前两个只读 Handler；`tool_conversation.py` 管理有限的单轮模型—工具—模型流程。没有 Agent loop。 |
| Development | `tests/` 保护回归；`scripts/` 是人工触发的维护工具，不是正常运行依赖。自动测试使用 mock 和临时虚构数据，不访问真实模型。 |
| Research | `docs/deep-dive/research/` 仅放未实现且仍值得讨论的设计；其中 Knowledge Tool 目前暂停。 |
| Generated | `outputs/` 存储忽略跟踪的本机运行数据。被 Git 忽略不代表可随意删除，清理前须确认用户数据。 |
| User-private | 用户私有凭据存放于固定 `%LOCALAPPDATA%` 项目目录；路径不由浏览器、Profile 或模型输入指定。正式凭据与 Manual V2 凭据分文件隔离。 |

## `src/fishery_ai/` 关键模块

| 文件 / 子目录 | 当前职责 |
| --- | --- |
| `contracts.py`、`domain.py` | 水质、质量、新鲜度、发现项与结果合同；确定性诊断阈值只在 Domain 服务维护。 |
| `telemetry/` | Scenario Template、Simulator、Adapter、进程内 Snapshot Store 与只读 Current Reader。 |
| `application.py` | 固定 Analysis：捕获水质 → Diagnosis → RAG → Analysis Context → Model；有授权时可进入受限 Tool 流程。 |
| `knowledge.py`、`resources/knowledge/` | TF-IDF baseline 与知识资源；仅 Analysis 自动检索。Knowledge Tool 未实现。 |
| `assistant.py` | 三个发布 Preset 的 Assistant 会话合同、有界页面历史与最终回答提交门禁；不调用 Analysis Orchestrator。 |
| `model_gateway.py`、`openai_compatible_adapter.py` | provider-neutral 请求合同、不可变 Runtime/Credential snapshot、OpenAI SDK 传输适配。 |
| `presets.py`、`protocol_specs.py`、`providers.py` | 固定 Preset 合同、协议参数编码和 Provider/Auth 元数据。 |
| `tools/`、`tool_conversation.py` | Tool 定义、授权、执行、只读 Handler，以及最多一个 Tool call / 一轮 / 两次模型请求的协调。 |
| `execution.py`、`observability.py` | 请求生命周期、取消、Usage 与安全 Trace。取消不证明远端模型计算已停止。 |
| `resources/` | 随包的 profile、Preset、Policy、Scenario、Knowledge、Mock 与 Web 静态资源。不是用户运行数据。 |

## 文档结构

- 根层：`BUILD_RUN.md`、`TROUBLESHOOTING.md`、`CODE_REVIEW.md`、`ROADMAP.md`、`STRUCTURE.md`。
- `deep-dive/architecture/`：Analysis 与 Assistant 边界。
- `deep-dive/models/`：Preset 发布与模型能力细节。
- `deep-dive/tools/`：Tool 当前合同和新增流程。
- `deep-dive/data-domain/`：Telemetry、水质与领域数据。
- `deep-dive/operations/`：凭据、运行数据与运维位置。
- `deep-dive/research/`：暂停或未实现的研究主题；不是当前开发承诺。

各运行数据的 Git 跟踪、保留与重建性质见[项目数据与配置位置地图](deep-dive/operations/PROJECT_DATA_AND_CONFIG_LOCATIONS.md)。

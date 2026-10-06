# 项目结构

目录职责以当前源码为准。更细的运行数据位置见[维护者文件位置地图](deep-dive/PROJECT_DATA_AND_CONFIG_LOCATIONS.md)。

    Fishery_AI_Prototype/
    ├─ src/fishery_ai/   可安装的 Python 包、业务代码和包内运行资源
    ├─ tests/            离线自动化回归，不参与正常运行，必须保留
    ├─ scripts/          开发 / 验证辅助工具，不是正常运行所必需
    ├─ docs/             用户指南、路线图和少量仍有价值的专项资料
    └─ outputs/          本机运行时配置和记录，Git 忽略；不是源码

## 根目录

pyproject.toml 定义安装包、Python 版本、依赖和包资源。README.md 是简要入口，AGENTS.md 约束开发边界。.venv/ 是可重建的本地环境。

## src/fishery_ai/

- contracts.py、domain.py、repositories.py：领域合同（含共享 Freshness 判断）、确定性诊断与 Mock / Demo 场景生成。
- telemetry/：内置 / 用户情景模板管理与动态模拟入口；Template 经 Simulator、SimulationAdapter 转成既有 WaterQualityReading，再写入进程内 CurrentSnapshotStore。Web 与 CLI 水质入口统一使用这条管线。
- application.py、model_gateway.py、openai_compatible_adapter.py：固定分析流程和模型传输；T1 增加 non-streaming tools / tool_calls / tool_call_id 消息合同与 SDK 编码归一，不执行工具。
- tools/：T2 显式静态 allowlist、有限执行器和当前水质只读 Handler。
- tool_policy.py、resources/tools/tool_policies.json：冻结的 analysis / assistant 默认授权策略及 UserToolPolicyStore；用户设置存 outputs/tool-policies/tool_policies.json，原子替换、启动校验、可恢复默认。Analysis 的用户选择仅作准备，实际仍暴露零工具；Assistant 新请求捕获有效 Policy，定义和执行均受限制。
- tools/catalog.py：固定 UI metadata；一个真实水质 Tool 与三个 DEV ONLY / NOT EXECUTABLE 占位。Catalog 不注册 Handler，用户不能把占位项保存到实际 Policy。
- tool_conversation.py：T3 独立应用层 ToolCallingService；最多一次 Tool 和一次 follow-up；T4 增加离线 MockToolGateway 示例，不替代固定 Analysis。observability.py 为其记录单独的 JSONL Trace。
- presets.py、protocol_specs.py、providers.py：固定 Preset、协议编码和 Provider 元信息。
- preset_tool_qualification.py：维护者独立 Preset Tool 资格验证，复用 T3 / T2；最多一次 Tool 闭环加一次概念问题，不写 Managed Evidence、不自动发布、不进入 Analysis。
- capability_store.py、evidence_resolver.py、capability_probe.py、tool_capability_probe.py：Managed Custom 的能力证据与显式验证；Tool Probe 位于 02 · 模型能力的高级验证操作，Development 只验证已有能力。
- credentials.py、credential_paths.py、project_env.py：凭据读取、用户私有路径和受控写入。
- manual.py、manual_experiments.py：Manual V1/V2 Raw 请求与实验存储。
- web.py、resources/web/：本地开发者界面。
- resources/scenarios/water_quality/：五个只读内置水质情景模板，保存输入意图与观测年龄。
- resources/scenarios/detection/：normal / count_jump 固定检测事件，未增加 Detection Simulator。
- resources/mock/、resources/knowledge/、resources/profiles/：Mock 模型 Profile、知识和固定连接/方案数据。

telemetry/ 的最小结构：

```text
telemetry/
├─ __init__.py   对外入口
├─ models.py     SimulationPacket / SimulationRecipe
├─ simulator.py  baseline + 数值覆盖 / missing / invalid
├─ adapter.py    sim-v1 校验与 canonical 合同转换
├─ snapshot.py   最后一次接收 / Apply 的原始 canonical reading；未写入时返回 None
├─ current.py    CurrentWaterQualityReader；只读捕获并生成 query-time view
└─ scenario_templates.py  Template 合同、Builtin / User CRUD 与统一 Apply 管线
```

依赖方向：Telemetry → WaterQualityReading → Domain / Diagnosis。WaterQualityReading、ObservedFacts、DiagnosisService 保留原位置，Domain 不依赖 Telemetry。详细用法见[水质与 telemetry](deep-dive/WATER_QUALITY_SCENARIO_AND_TELEMETRY_PREPARATION.md)。

tools/ 的最小结构：

```text
tools/
├─ __init__.py      对外入口
├─ contracts.py     ToolDefinition / ToolExecutionResult / 安全错误码
├─ registry.py      仅 get_current_water_quality 的固定 allowlist
├─ catalog.py       仅展示 metadata / DEV 占位；执行权限仍来自 Registry
├─ executor.py      显式执行、空参数校验、次数/结果大小限制、取消检查
└─ water_quality.py CurrentWaterQualityReader → DiagnosisService → JSON 数据
```

ModelToolDefinition / ModelToolCall 仍属于 T1 模型协议，T2 复用它们。Registry 由调用者注入 Reader / Diagnosis，Handler 只读取查询视图；不读取 Scenario、MockRepository、文件或硬件包，不修改 Snapshot。Executor 按请求创建，默认最多一次调用，不自动向模型发 Request #2。T4 Web API 通过 T3 发起单轮对话；没有 Agent 或 Streaming Tool Calling。

T3 单轮路径为：system / user / Policy-filtered Registry tools → Model Request #1 → 一个 assistant.tool_calls → T2 Executor → role=tool JSON → Model Request #2（tool_choice=none）→ 最终正文。首次请求不提前读取或注入当前水质。无 Tool Call 时直接结束；第二轮继续调用 Tool 返回 TOOL_ROUND_LIMIT。Tool Calling ≠ Agent。

ToolCallingService 接受调用者已经捕获的不可变 RuntimeSnapshot，两次请求共用它和现有 RequestHandle；不增加凭据读取或隐藏水质来源。T4 在独立 Development / Test 模式的 Read-only Tool Calling 区域调用 `/api/tool-conversation`，注入同一个 Web Reader / Diagnosis，复用凭据解析和 Stop。普通模式仅显示进入按钮；前端保存原模式 / Profile ID / 运行选项，返回时恢复，不复制凭据或构建第二套 Runtime。真实测试目标按原 Profile ID 从现有列表查找；开发顶部 Mock 与真实目标明确区分。默认使用独立的离线 Tool Mock，不注册成普通 Profile、不修改 Evidence。CLI 尚无专用 Tool Conversation 入口。

正式 Gateway 工具请求仍受精确 runtime 的能力门禁限制；Preset / Evidence 合同不因 T1/T2/T3/T4 改变。Web 选择当前 Runtime 时，未验证能力在创建 Gateway 前拒绝；服务和 Gateway 继续校验。普通固定 Analysis、Streaming 与 Manual Raw 保留原路径。见[T1–T5 只读工具说明](deep-dive/READ_ONLY_TOOL_CALLING.md)与[Analysis / Assistant 架构](deep-dive/ASSISTANT_MODEL_ARCHITECTURE.md)。模型接入方式与应用流程是两个维度；当前 Assistant 仍是单轮开发实验。

标题右侧 Tool 打开独立 Modal；Analysis / Assistant 两份草稿分开，默认折叠条目，保存前不改变有效策略。Analysis 勾选不启用 LLM Tool。右上 Assistant Model · Coming Soon 只提示尚未实现，不切换 Profile / Runtime。Web 的 Policy 写 API 复用 Host / Origin / CSRF，不接受文件路径。独立 Python 组件未注入 UserToolPolicyStore 时仍使用包内默认；Web 单轮对话与 T5 Probe 显式传入同一有效 Assistant Policy。

## tests/

使用虚构数据、临时存储和 Mock Transport；默认禁止真实网络。tests/fixtures/ 保存少量兼容性测试资产。测试保护运行边界，目录简洁不能替代回归覆盖。

## scripts/

qualify_local_preset_request.py 保留精确 Ollama Identity 的单项资格检查；qualify_preset_tools.py 对当前发布 Preset 执行有限 Tool 资格验证，一次只选一个模型。两者只供维护者使用，必须显式确认联网，不自动发布 Preset，也不是 Web 启动依赖。

## docs/ 与 outputs/

docs/ 顶层只保留构建运行、路线图、故障排查、评审和结构说明；deep-dive/ 放无法在结构概览中讲清的当前专题。outputs/ 中的自定义 Profile、Evidence、Experiment、scenario_templates/water_quality/、Trace 和资格摘要可能包含用户维护数据；不要由清理脚本一概删除。

Web application 创建一个共享 CurrentSnapshotStore 和一个 CurrentWaterQualityReader。Store 保留最后一次接收 / Apply 的原始 immutable reading，**Latest != Fresh**。Reader.query() 捕获一次原对象，按当前查询时间重新评估 Freshness，返回冻结的 CurrentWaterQualityView(reading, evaluated_at)；不改变 Store、数值、Quality 或原始时间。

observed_at 是观测时间；retrieved_at 是程序当时取得数据的时间；evaluated_at 是本次查询时间，**evaluated_at != retrieved_at**。年龄判断由 contracts.py 的 evaluate_freshness() 共享，age > stale_after_s 才 STALE；配置由 composition / create_app 注入。

Current API、Apply 后预览、Normal / Streaming 都经同一 Reader；Diagnosis 使用查询视图。分析开始时固定视图，进行中的请求不受后续 Apply 影响。重启为空；没有当前快照时返回 NO_DATA，Reader 不自动生成 normal。

**Scenario generation != Current state read**：显式 scenario 兼容调用仍先走模板生成 / Apply，再查询。CLI / Demo 的 Orchestrator 后备保留，用来生成模拟输入。MockRepository.demo_snapshots 惰性创建，旧 snapshots 属性仅是兼容别名；Web current Reader 不依赖该 Store。T2 Handler 只接受 CurrentWaterQualityReader；T4 已注入这个共享 Reader，Tool API 不接受 scenario/template 或水质值。没有 Snapshot 时 Tool 返回 NO_DATA，再由第二轮解释；不会 Apply normal。

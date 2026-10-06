# Analysis Model / Assistant Model 架构

## 当前状态（2026-10-06）

Analysis Model Tool Calling v1 已实现：保留固定 Snapshot → Diagnosis → RAG → Context，Analysis Policy 显式开启且精确 Runtime 支持时，复用同一个 ToolCallingService.run_request 单轮执行。右侧正式结果显示 Tool Activity；默认关闭工具，Streaming Tool Calling 不支持。Qwen / DeepSeek / Ollama 固定合同均已发布 Tool 协议支持。新增 score_current_water_quality 为实验评分，两个模式默认关闭；详见[新增 Tool 指南](ADDING_A_TOOL.md)。最新实现与验收见[Analysis v1](ANALYSIS_MODEL_TOOL_CALLING_V1.md)及[Preset 合同](PRESET_PUBLICATION.md)。

下文保留此前 Policy / UI 阶段的设计和验收过程，其中“Analysis 零工具 / 仅准备”描述属于历史阶段，已由上节的显式 opt-in 路径替代。Assistant 和 Manual 边界保持不变。

## 初始定位与阶段记录

**Analysis Model** 是程序控制的固定分析：Current Snapshot → Diagnosis → RAG → Analysis Context → LLM。`application.py::Orchestrator` 决定必要步骤；模型解释程序提供的事实，不自主获取事实。

**Assistant Model** 是按需调用模型的在线对话助手：System / User / 未来必要的对话历史 / 允许的 Tool Definitions → 模型选择是否调用 Tool → 程序受控执行 → 最终回答。持续可用不等于持续运行 LLM；没有用户请求时不调用模型。

当前已完成 Assistant S0/S1/S2：`assistant.py` 构造有界历史，正式聊天工作区复用 `tool_conversation.py::ToolCallingService`；Development / Test 单轮入口保留。历史仅存页面内存，没有长期历史存储、Scheduler 或 Agent。现有 Analysis 的 Chat / Advice 仍属于固定分析，不能等同于 Assistant。

Preset / Managed Custom / Manual 是**模型接入方式**；Analysis / Assistant 是**应用流程**，两者不是同一组模式。Manual Raw 不进入上述 Fishery 流程。

| 边界 | Analysis Model | Assistant Model |
| --- | --- | --- |
| 程序控制流程 | 固定执行全部必要步骤 | 控制授权、预算、执行与结束；模型选择是否需要 Tool |
| 事实预注入 | 是，固定当前查询视图 | 否；需要当前事实时调用 Tool |
| Diagnosis 预计算 | 是 | 不预计算；当前水质 Tool 内使用 DiagnosisService |
| RAG 自动执行 | 是 | 否；知识检索 Tool 仅规划 |
| LLM Tool Calling | Normal 显式 opt-in，保留固定上下文 | 仅 Policy 允许且模型能力支持的工具 |
| 定时 Advice | 当前没有调度器；固定 Advice 可供未来程序触发 | 不负责调度 |
| 交互问答 | 固定水质分析中的 Chat | 当前单轮开发验证；持续对话待设计 |

## Tool Policy 与 Registry

固定包资源：`src/fishery_ai/resources/tools/tool_policies.json`，由 `tools/policy.py` 使用 `importlib.resources` 加载。

```json
{
  "schema_version": 1,
  "modes": {
    "analysis": {"llm_tool_calling": false, "exposed_tools": []},
    "assistant": {
      "llm_tool_calling": true,
      "exposed_tools": ["get_current_water_quality"]
    }
  }
}
```

- Registry 是实际 Handler 的静态安全 allowlist；当前注册 `get_current_water_quality` 与 `score_current_water_quality`，不增加注册 API。
- Policy 只能限制 Registry 已有名称，不能添加 Handler、模块、函数路径、import、eval 或 exec。未知名称、额外字段、错误类型均 fail closed；Web 创建时校验。
- 有效执行必须满足 **Registry 已注册 AND 当前 Policy 允许**；模型能力门禁是另一个独立条件，不由 Policy 推导。
- ToolPolicy 冻结；定义直接取自 Registry，经 Policy 过滤，没有第二份 schema。Executor 再检查 Policy，避免只隐藏定义却仍允许越权执行。已注册但未授权返回 `TOOL_NOT_ALLOWED`，未知工具返回 `UNKNOWN_TOOL`。

Analysis 未授权时 `ModelRequest.tools=()`，意外调用拒绝；授权且 Runtime 支持时，Normal 使用共享协调器。首轮保留 Facts / Rules / RAG；第二轮追加明确 JSON 合同提醒，tool_choice=none。启用 Tool 的 Streaming 明确拒绝。

Assistant 首轮只提供 system / user / Policy-filtered Registry definitions，不预读 Snapshot、Diagnosis 或 RAG。当前预算仍是 **最多一个调用、一个 Tool round、两次模型请求**；第二轮 `tool_choice=none`，再请求 Tool 返回 `TOOL_ROUND_LIMIT`。这不是自主 Agent Loop。

## 当前事实与未来工具

当前查询 Tool：`get_current_water_quality()`，通过共享 CurrentWaterQualityReader 查询当前 Snapshot，复用 query-time Freshness 和 DiagnosisService。没有 Snapshot 返回 NO_DATA；invalid / stale / partial 是已有数据的状态，不是 NO_DATA。不读取 Scenario，不生成 normal，不修改 Store。

未来候选仅为规划，当前均没有注册、执行或发布：

| 候选 | 目的与限制 |
| --- | --- |
| search_fishery_knowledge(query) | Assistant 按需检索，替代自动预注入 RAG；证据不等于现场事实 |
| get_current_detection | 未来 canonical Detection 只读视图；不直接读取 YOLO 原包 |
| get_recent_water_quality | 未来有界历史查询；先定义时间范围、质量与预算 |

score_current_water_quality 已实现：共享 Reader → 独立 WaterQualityScoringService → JSON Result。不是专业标准；无自动 `<水质评分>` 触发器。Analysis / Assistant 均由模型在已授权 schema 中选择，最多一个调用。新工具默认关闭，Assistant 原默认仍只有查询工具。Handler / Registry / Catalog / Executor / Policy 在 tools/；服务层协调器不搬入 tools/。

## Capability UI 与验证职责

Managed Custom → **02 · 模型能力 → 高级验证操作** 提供“验证 Tool Calling”；有实际 Probe Evidence 时显示“重新验证 Tool Calling”。继续使用同一个 T5 API、精确 Identity、CredentialSnapshot、RuntimeSnapshot、RequestHandle、Resolver；每次显式确认 REAL NETWORK REQUEST，最多两次模型请求、retry=0。页面不会自动 Probe。

Development / Test 仅验证已有运行能力，保留 Mock / 真实 Runtime、Snapshot、最终回答、Tool Trace 和 Stop。真实能力不为 SUPPORTED 时，在联网前拒绝，并提示先到 Managed Custom 能力区验证。Probe 结果显示在能力区，不混入对话 Trace。成功后当前 Profile 能力即时刷新；不覆盖编辑草稿或切换后的其他 Profile。

用户已报告 QW_2 真实 Tool Calling 验证成功；本轮只读核对当前 Profile / Evidence：`dashscope / openai_chat / https://dashscope.aliyuncs.com/compatible-mode/v1 / qwen3.8-flash`，解析为 `tool_calling=SUPPORTED`、来源 `explicit_probe`。本轮没有新真实请求，不把该记录推广到其他 Identity 或 Preset。

## Preset 边界与下一步

Managed Custom 使用 Evidence-driven capability；Preset 使用 Maintainer-published 固定合同。QW_2 Evidence 不自动修改默认 Qwen Preset。该 UI / Policy 阶段没有改合同；后续独立维护者资格与用户真实验证已发布三个 Preset Tool 协议合同 1.0.2，详见[当前 Preset 发布说明](PRESET_PUBLICATION.md)。

新增 Preset 的 Tool Calling Qualification 应先确定精确 Identity 与候选合同，维护者逐项确认 NO_DATA / 正常 / 异常、合法 Tool Call、单轮结束、Usage、取消和安全失败，并检查 Manual V1 原始响应。只有确认需要发布且验证充分后才修改固定合同版本；不得自动 Custom → Preset。本轮不执行资格测试。

## 安全与后续决策

第一阶段只读：禁止 DB mutation、设备控制、阈值修改、Shell、任意文件访问和动态加载。复用当前取消、执行预算、结果大小限制、安全错误与 Trace 白名单；Tool Result 保持 role=tool 数据，不能提升为 system instruction。

Assistant + Tool Calling ≠ full Agent。未来若需要 planning、多轮、状态、预算与 termination policy，应另行评审；本轮不增加多轮、Streaming Tool Calling、历史、Scheduler 或第二个 Tool。

完成本轮人工 UI 验收后，可以单独设计实验评分：先固定输入/输出、算法版本、缺失/无效/陈旧语义，再增加 Handler、静态注册和新版 Policy，验证 Analysis 程序触发与 Assistant 模型选择。不能把这项建议当作已授权实施。

## 本轮实施与验证

本节后半保留初次架构整理的记录；最新 Tool 管理 UI 实施见下一节。

实现范围：Tool Policy 资源与冻结合同；Analysis 显式无 Tool；Assistant 定义与执行双重过滤；Tool Probe 移到 Managed 能力区，Development 只保留对话测试。没有更改 R3/R4/R5、Credential、Preset、Diagnosis、RAG、Freshness 或模型协议。

针对性结果：Tool Policy 15、T1 29、T2 35、T3 36、T4 22、T5 17、原 Application Streaming 13 项通过；相关 Browser 30 项通过。完整 Python 584 项通过（25.490 秒）；完整 Browser 144 项通过（Node DOM / fetch fixtures，不进行真实浏览器联网）。JS syntax、git diff --check 通过；37 个 Markdown 本地链接有效。131 个 Git 可见源码 / 文档敏感扫描无未解决风险，1 个既有 URL 凭据拒绝测试负例已核对；受管输出与凭据被跟踪数量为 0。自动测试均离线、临时存储 / 虚构凭据；本轮不读取真实 Secret、不调用模型、不 commit / push。

基于已提交 checkpoint 165f20e，最终工作树为 17 个已跟踪文件修改、4 个新文件；不删除文件，不修改 Preset、ProtocolSpec、Credential 或正式 Fishery_Project。

## Tool 管理 UI 与 User Policy Override（2026-10-06）

### 入口与 Catalog

左侧标题改为 **01 · Analysis Model**，同一行右侧 **Tool** 打开 Modal。入口独立于 Profile / Provider；此段原为 Policy UI 阶段记录；S2 已改为顶栏单个固定宽度切换按钮，Analysis 与 Assistant 独立工作区保留各自草稿，不改对方 Runtime。

`tools/catalog.py` 为只读展示 metadata：名称、简介、说明、access_type、参数摘要、DEV / planned 等。registered / executable 根据当前 Registry 和固定 Handler 计算，Catalog 不拥有 Handler 或函数路径，修改展示值不能注册工具。

当前正式列表为 get_current_water_quality / score_current_water_quality；原三个 DEV 占位已在 Assistant S0 删除。条目默认只显示 checkbox、名称、状态、展开按钮；详情默认折叠，可以展开/收起。Catalog 不注册 Handler 或授予执行权限。

### 两份设置与实际权限

Analysis / Assistant 标签保存两份独立草稿。计数如 1 / 4 同时标明只有 1 个可执行 Tool；Analysis 使用“准备选择”并提示实际暴露 0 个。未保存修改不改变当前策略，关闭前确认丢弃；切换标签保留草稿。

包内 tool_policies.json 仍是维护者默认策略，Web 不写源码。用户 Override 的 schema 与有效 ToolPolicy 有意分离：

```json
{
  "schema_version": 1,
  "modes": {
    "analysis": {"selected_tools": []},
    "assistant": {"selected_tools": ["get_current_water_quality"]}
  }
}
```

正式 Web 固定保存到 **outputs/tool-policies/tool_policies.json**（Git ignored，不含 Secret）。路径由启动 composition 选择；浏览器不能指定。没有 Override 用包内默认；坏 schema、未知/占位名称、符号链接、reparse point、硬链接文件 fail closed，不静默退回默认。可用 UI 恢复默认删除 Override；若磁盘配置已损坏导致启动失败，应先由维护者检查/修复该非凭据配置，再启动。

UserToolPolicyStore 复用 ToolPolicy 名称校验，独立记录 Analysis 准备选择；有效 Analysis 始终使用禁止 LLM Tool 的默认合同，不启用 Orchestrator Executor。有效 Assistant 使用用户选择，新的 Web Tool Conversation / 显式 T5 Probe 捕获冻结策略；在途请求不改变。独立 Python 组件没有注入 Store 时继续用包内默认，不隐式搜索磁盘设置。

有效定义仍须 Registry 已注册 AND Policy 允许 AND 固定 Handler 可执行，且正式请求 Runtime tool_calling=SUPPORTED。Explicit Probe 可临时越过 UNKNOWN 能力，**不能越过 Policy**；水质 Tool 被关闭时返回 TOOL_NOT_ALLOWED，不发送 Probe。DEV 项不可能通过这条链。

### 保存、安全与限制

`/api/tool-policies` GET / PUT / DELETE 复用现有本地 Host / Origin / CSRF；不开放 CORS，不返回异常或路径。严格只允许 schema_version / modes / selected_tools，无额外字段。写入同目录独占创建 staging，flush / fsync 后 os.replace；替换失败保留原文件，清理自建临时文件。恢复默认只删除该 Override，不修改 Profile、Credential、Evidence、Snapshot、源码默认或其他文件。

当前使用进程内锁，跨标签/进程并发保存按最后成功写入生效，没有 revision 合并；UI 失败保留草稿并提示重新读取实际状态。保存不追溯撤销已开始请求，需 Stop 使用现有取消机制。这是非 Secret 的模式配置，不引入 Credential ACL / 凭据迁移。

本轮没有新增正式 Tool、评分、Knowledge Tool、Assistant 主界面、Preset Tool 合同、Agent 或新联网请求。下一步优先人工验收管理面板与实际权限边界；随后可独立评审 Preset Tool Calling Qualification，或实验评分的程序 / 模型两种触发方式，均未在本轮实施。

### 最新验证

Tool Policy 15 项 + Manager 19 项通过；T1 / T2 / T3 / T4 / T5 targeted 分别 29 / 35 / 36 / 22 / 17 项通过。相关 Browser targeted 42 项通过，其中新 Tool Manager 12 项。

最终 Full Python **603 项通过（19.308 秒）**；Full Browser **156 项通过**（Node DOM / fetch fixtures，没有启动真实联网浏览器）。JS syntax、37 个 Markdown 本地链接、git diff --check 通过。133 个 Git 可见源码 / 文档敏感扫描无未解决风险；1 个既有 URL 凭据拒绝 fixture 已核对，受管凭据 / outputs 被 Git 跟踪数量为 0。

本轮开发曾发现新测试遗漏 Reader 必需参数、Browser fixture 把 HTTP 状态传作成功标志，以及旧标题断言未更新；已修正后完成上述全量回归，没有剩余失败。所有自动测试使用临时文件、虚构凭据与网络阻断，不读取真实凭据或调用模型。

工作树包含上一轮尚未提交的模式 / Policy 改动：累计 19 个已跟踪文件修改、6 个新文件。本轮新增 tools/catalog.py、tests/test_tool_policy_manager.py；其余复用现有文件。未删除文件、未联网、未 commit / push；正式项目未触碰。仍需用户检查真实浏览器的布局、键盘关闭、两份设置刷新持久化和 Analysis 零工具行为。

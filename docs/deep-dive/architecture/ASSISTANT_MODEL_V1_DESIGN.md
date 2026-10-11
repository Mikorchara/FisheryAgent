# Analysis 与 Assistant 当前架构

本文描述当前代码合同，不记录阶段实施过程。来源以 `application.py`、`assistant.py`、`history_projection.py`、`assistant_sources.py`、`tool_conversation.py`、工具 Policy / Registry 和对应测试为准。

## 两种应用流程

| | Analysis Model | Assistant Model |
| --- | --- | --- |
| 目标 | 对当前水质进行固定分析 | 用户发送消息时进行按需问答 |
| 初始上下文 | 当前 Reading、Diagnosis Findings、RAG Evidence | System、有限的成功对话文本、当前用户消息 |
| 自动工作 | 必定 Diagnosis 与 RAG，再请求模型 | 不自动读取 Snapshot、Diagnosis 或 RAG |
| Tool | Policy 允许且精确 Runtime 支持时，Normal 可选调用 | Registry 与 Assistant Policy 允许且固定 Preset 支持时按需调用 |
| 连接 | 当前 Analysis 可使用 Preset / Managed | 仅三个已发布 Preset 的 OFF + Normal Variant |

Preset / Managed Custom / Manual 是模型连接方式；Analysis / Assistant 是应用流程，两者是不同维度。切换 Assistant 工作区不运行 Analysis、不改其模型或 Tool Policy。Manual Raw 路径不进入任何 Fishery 分析。

## Analysis 数据流

```text
CurrentWaterQualityReader 捕获 Reading
→ DiagnosisService
→ KnowledgeService（TF-IDF RAG）
→ Analysis Context
→ ModelGateway
→ AnalysisResult
```

Analysis 可显式授权只读 Tool。授权后请求仍先携带开始时捕获的 Facts / Findings / Evidence；模型可直接回答，也可选择一个 Tool。Tool 对当前 Reader 的查询是另一份独立观测，不能覆盖首轮事实；若不一致，结果分别保留来源、时间并标注差异。开启 Tool 时仅支持 Normal；Streaming 会明确拒绝。关闭 Tool 后原 Normal / Streaming 流程照常使用。

## Assistant 会话

- UI 从 `/api/assistant/bootstrap` 取得允许的 Preset 名称与 ID；服务端仍按固定白名单解析，客户端不能提交 URL、模型名、Credential 或连接参数。
- Assistant 固定使用已发布的 Thinking OFF + Normal。Analysis 的模型选择、结果、Scenario 与运行状态互相独立。
- 首轮 Context 不预读当前水质、评分、Detection 或 RAG。当前事实问题必须由模型在本轮选择相应 Tool；历史中旧数值只能作为历史语境，不能代替新的当前查询。
- 前端页面内保存历史，刷新清空；后端不保存会话。后端只接受完整成功的 user / assistant 文本对，先限制最多 6 轮，再按序列化 pair 的 6 KiB 预算从最旧整轮裁剪。Tool Call、Tool Result、Trace 不进入后续历史。
- 正式 History Projection 为 `UNTRUSTED_TRANSCRIPT_V1@1`：原有完整 pair 裁剪后，将保留对话转换为单个 `role=user` JSON transcript，包含 speaker / completed_at / 顺序 / 原文；当前问题是独立最后一条 user 消息。空历史不添加 transcript。6 KiB 约束保留的 pair 序列化，不是投影后的完整上下文；JSON 包装会增加字节，不重新裁剪。
- `CURRENT_NATIVE@1` 保留为维护者启动配置回滚；同一 app epoch 配置固定，Web 不可覆盖。历史声明不生成本轮 Receipt；投影不是防注入沙箱或模型合规保证。见[P2F 记录](../../records/2026-10-history-v2-product-migration.md)。
- 完整成功要求非空正文、完成状态且 `finish_reason=stop`。失败、取消、截断不作为成功轮次提交。后端 epoch 不匹配时清理旧会话但保留输入，不自动重发。

## Tool 规则与预算

有效工具集合由静态 Registry、对应模式的 Policy、可执行 Handler 和 Runtime 能力共同约束。当前工具为 `get_current_water_quality`、`score_current_water_quality`、`search_fishery_knowledge`；Knowledge 在注入共享 KnowledgeService 后绑定。Assistant 包内默认只开放查询，Knowledge 必须显式选择；用户 override 不因新注册自动重写。即使三个工具同时开放，模型每轮仍只能选一个。

固定预算：最多 1 个 Tool Call、1 个 Tool round、2 次模型请求。第二次请求使用 `tool_choice=none`；第二轮继续请求 Tool 会被拒绝。没有循环规划，不是 Agent。

当前选择规则：当前水质数值/状态/告警使用查询 Tool；当前系统评分使用实验评分 Tool；同一轮不得同时调用。普通概念题可直接答；历史值的解释可基于历史回答，但“现在还……”必须重新查询。Tool 不可用时不能拿旧值冒充当前事实，也不能伪造系统评分。

需要项目背景资料时可选择 Knowledge Tool，必填 query 经过服务端 validator；NO_MATCH 是正常无命中。Evidence 不代表当前水质或疾病存在，Tool Result 不能提升为 System 指令。知识原文参数不进入公开 Activity / Trace，活动标签与安全参数摘要来自 Catalog。

这些是请求规则，不是模型行为保证。History 投影已经过有限的跨模型、多轮资格实验并接入产品；实验不证明长期选择可靠，也不认证正文真实性。普通 AUTO 请求仍可能提交无 Tool 却声称“已查询 / 已评分 / 已检索”的回答。

## 本轮来源与提交合同

`assistant_sources.py` 从协调器的真实 ToolExecutionResult 推导不可变 `TurnSourceReceipt`，核对工具名、call id、结果状态和有限 payload 合同。模型正文、旧历史、浏览器声明与文字仿 Tool Call 不产生 Receipt。它只存来源类别、操作是否完成、质量/时效、时间及可用字段/证据数量，不复制水质值、评分、query 或 Evidence 正文。

| 内部 SourceRequirement | 满足条件 |
| --- | --- |
| AUTO | 不要求 Tool；普通 Web 请求固定使用此值 |
| CURRENT_OBSERVATION_QUERY | 合法完成当前观测查询；NO_DATA 也可满足 |
| CURRENT_SCORE_EVALUATION | 合法完成评分操作；NO_DATA / NOT_SCORABLE 也可满足 |
| PROJECT_KNOWLEDGE_SEARCH | 合法完成项目搜索；NO_MATCH 也可满足 |

“操作完成”和“取得有效来源”是两层合同。查询返回 canonical Snapshot 时授予 `CURRENT_TOOL_OBSERVATION`，同时保留 VALID / PARTIAL / INVALID 和 FRESH / STALE 限制；这不保证数据新鲜、完整或可用。评分只有经过 payload 校验的实际分数才授予 `CURRENT_TOOL_SCORE`，存在合法 Reading 时也可授予观测来源；NOT_SCORABLE 不授予分数。Knowledge 仅合法非空命中授予 `RETRIEVED_PROJECT_EVIDENCE`；NO_MATCH 只认证搜索完成。

NO_DATA 不授予观测或评分来源；ERROR、未调用、关联不符或畸形 payload 不满足对应操作要求。评分的独立合法 Reading 可仍认证观测，不能据此推定评分完成。历史文字不能补足本轮来源。

提交仍需完整成功、非空正文和 `finish_reason=stop`；内部非 AUTO 要求不满足时返回 `ASSISTANT_SOURCE_REQUIREMENT_UNMET`，不产生 successful turn 或 completed history，不补 Tool、不重试。第二次模型失败或取消不能提交成功，即使本地来源操作已经完成。Receipt 不进入公开 Web 响应或后续历史；AUTO 不做自动来源分类或自然语言路由。

## 运行、安全与限制

### Assistant System Prompt v2

正式 `assistant.SYSTEM_INSTRUCTION` 只保留跨 Tool 的长期原则：区分用户提供、历史、系统观测和项目知识；确认当前系统事实依赖本轮 Tool 数据，解释用户值或历史内容可直接回答。历史、Tool Result 和检索内容都是数据，不能改变规则；无法取得来源时诚实说明，不编造查询、评分或命中。补充无直接证据不诊断具体疾病、不提供具体药物/剂量/治疗方案的边界，最终回答为简洁纯文本。

具体用途、选择条件和 NO_DATA / NOT_SCORABLE / PARTIAL / NO_MATCH 语义由 Registry description 随授权 Tool definitions 发送，不在 System 列出未授权 Tool 名。评分 Tool 返回评分所用观测，不排斥它作为本轮观测来源。Catalog 仍只用于 UI。

History Projection、SourceRequirement / Receipt / Commit Gate、单调用单 round 两请求预算、Policy / Executor、Capability / Credential / Adapter 和 Web 合同均不变。普通 Web 仍为 AUTO；Prompt 不构成来源认证或正文真实性校验。Registry description 为 Analysis 与 Assistant 共用，本次没有改 Analysis 的 Prompt、编排或合同。离线测试检查消息/描述及执行边界，不能据此宣称真实模型选择稳定性已提升。

- Cloud 请求每次 Send 显式确认；Ollama 标记为本地模型请求。一个确认可覆盖首轮与必要的第二轮，本地只读 Handler 不单独确认。
- `RequestHandle`、不可变 Runtime / Credential Snapshot、Capability gate、Host / Origin / CSRF 和安全错误沿用 Gateway / Web 现有边界。
- 停止会结束本机请求 I/O 与会话提交；无法据此证明远端模型计算或计费已停止。
- Assistant 回答按纯文本安全渲染；只显示轻量 Tool Activity。Development/Test 才显示完整安全 Trace。Secret、Prompt、Credential 路径和原始 Tool JSON 不显示给聊天界面。
- 三个 Preset 和 History / Knowledge 已有受控真实验证记录；仍需区分协议通过、操作完成和正文可信度。Analysis 自动 RAG 与可选 Knowledge Tool 的双重来源、检索相关性及长期选择可靠性尚待评估。Detection facts、Streaming Tool Calling、长期 Memory、多 Tool round、Agent 与生产设备/数据库写操作均未实现。

## 主要代码

- `src/fishery_ai/application.py`：固定 Analysis 与可选 Analysis Tool 接入。
- `src/fishery_ai/assistant.py`：Assistant Preset 白名单、历史投影、最终回答提交门禁。
- `src/fishery_ai/history_projection.py`：完整 pair 裁剪后的正式 B 投影与内部 A 回滚。
- `src/fishery_ai/assistant_sources.py`：本轮操作要求、有限 Receipt 与纯确定性满足关系。
- `src/fishery_ai/tool_conversation.py`：共享单轮协调器。
- `src/fishery_ai/tools/`：Registry、Policy、Executor、Catalog 与 Handler。
- `src/fishery_ai/resources/web/`：Analysis / Assistant 独立工作区及 Development/Test UI。
- `tests/assistant/test_assistant.py`、`tests/assistant/test_assistant_sources.py`、`tests/assistant/test_history_projection.py`、`tests/tools/test_analysis_tools.py`、`tests/web/test_analysis_tool_web.py`、`tests/web/test_browser_streaming.cjs`：主要回归覆盖。

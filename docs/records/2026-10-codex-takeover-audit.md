# Codex 接管审计：Tool / Knowledge Tool

日期：2026-10-09。审计基线：`44992a0`（`step_10`），开始时工作树干净。

## 1. 结论与审计边界

**结论：执行与协议链路基本具备第三个带参数 Tool 的支持，但 Knowledge Tool 的真实 Assistant 集成尚未验收通过。**

主要阻塞是：没有执行 Tool 时，应用仍可接受模型声称“已查询当前数据”“已得到当前系统评分”“根据项目检索结果”的回答。离线反例已确认这一接受路径；用户报告的真实 Qwen 异常与该风险一致。不能据此直接断言是 Provider 不支持带参数 Tool，或是 Gateway 丢失 Tool Call。

本轮只新增本报告。没有修改源码、测试、运行配置、Preset、其他文档或生产项目；没有读取真实凭据，没有发送真实模型请求。检查已有非敏感 Policy 配置，以及 Trace 的字段白名单；未回显完整 Prompt、原始响应、Secret 或私有凭据路径。

证据标记：

- **代码确认**：当前源码与测试断言核对。
- **离线复现**：本轮内存中的虚构凭据、响应或 HTTPX MockTransport 检查。
- **已有记录**：当前 Trace 或用户人工验收，不能当成本轮真实请求结果。
- **尚未确认**：真实 Provider 原始响应、历史上下文的因果影响。

## 2. 接管材料与变更范围

实际目录为 `docs/copilot/` 和 `docs/handoff/`，不存在用户提到的 `copilot/handoff/`。这些材料是审计入口，不是当前实现的权威来源。

| 顺序 / 主题 | `docs/copilot/` 文件 | 本轮处理 |
|---|---|---|
| 总计划 | KNOWLEDGE_TOOL_STEP_BY_STEP.md | 对照各 Step，识别过时总状态 |
| Step 2 | STEP2_TOOL_ARGUMENT_CONTRACT_BEFORE_AFTER.md | 参数合同 / Executor |
| Step 3 | STEP3_TOOL_STATUS_NO_MATCH_BEFORE_AFTER.md | NO_MATCH 语义 |
| Step 4 | STEP4_KNOWLEDGE_HANDLER_DESIGN.md；STEP4_KNOWLEDGE_HANDLER_BEFORE_AFTER.md | Handler / 字段 / 限额 |
| D1 | D1_MOCK_TOOL_GATEWAY_BEFORE_AFTER.md | Mock 可驱动集合 |
| Step 5 | STEP5_KNOWLEDGE_REGISTRATION_BEFORE_AFTER.md | Registry / validator |
| Step 6 | STEP6_CATALOG_BEFORE_AFTER.md | Catalog / 展示边界 |
| Step 7 | STEP7_POLICY_DEFAULTS_BEFORE_AFTER.md | 默认 / override |
| Step 8 | STEP8_KNOWLEDGE_ASSEMBLY_BEFORE_AFTER.md | Web 实际装配 |
| D1b | D1B_MOCK_DIRECTIONAL_FALLBACK_BEFORE_AFTER.md | 方向性 fallback |
| Step 9 | STEP9_ASSISTANT_SELECTION_RULES_BEFORE_AFTER.md | 当前 Prompt / 历史边界 |
| Step 10 | STEP10_UI_ACCURACY_BEFORE_AFTER.md | public projection / UI |

原 `docs/handoff/` 有三个文件：`README.md`、`TOOL_CHANGE_MAP.md`、`KNOWLEDGE_TOOL_V1_WALKTHROUGH.md`。均已纳入核对。

Git 顺序支持上述迭代：`6330264` Step 4 → `7c0942a` D1 → `2c95f28` / `388b5a7` Step 6 → `b8091bf` Step 8 → `67b2da5` D1b → `44992a0` Step 10。与前置基线 `6b9dad9` 比较，`src/`、`tests/` 共 24 个文件、1990 行新增、63 行删除。Adapter、ModelGateway、ProtocolSpec、Preset 在该区间没有改动，不能把这些原有模块的行为归因于本次 Copilot 新增代码。

## 3. 当前真实架构

### 3.1 Assistant

```text
Web Assistant API
  → 捕获 Preset Runtime / CredentialSnapshot / Assistant Policy
  → AssistantContextBuilder：System + 成功历史对 + User
  → ToolCallingService.run_request()
  → Policy.model_definitions(Registry)
  → ModelGateway → OpenAICompatibleAdapter → SDK
  → 无 tool_calls：首轮正文直接结束
  → 有 tool_calls：最多一个 → ToolExecutor → 固定 Handler
  → assistant(tool_calls) + tool(result)
  → Request #2，tool_choice=none → 最终正文
```

当前预算仍为一个 Tool Call、一个 Tool round、最多两次模型请求。Assistant 不自动注入 Snapshot、Diagnosis、RAG、Scenario；实时事实依赖显式 Tool 查询。

### 3.2 Analysis

固定 Snapshot → Diagnosis → KnowledgeService.search → Context → LLM 流程保留；授权开启 Tool 时可再经过单轮 Tool Calling。**自动 RAG 与可选 Knowledge Tool 的双重知识来源是后续议题，本轮不作为当前修复目标。**

### 3.3 实际装配

`web.py` 先创建一个 `KnowledgeService`，再执行 `ToolRegistry(current_reader, diagnosis, knowledge=knowledge)`，然后创建 `UserToolPolicyStore`。Analysis 与 Knowledge Handler 使用这一 Web app 内的同一个 KnowledgeService；不是新增第二份检索服务。Assistant 请求捕获有效 Policy 后，使用同一 Registry 构造 Coordinator。

普通演示 / real-validation 的独立进程装配不等于 Web app 内的第二份服务，不能据此报告重复实例 bug。

## 4. Step 2–10 逐项核对

| 项目 | 当前代码确认 | 限制 / 差异 |
|---|---|---|
| A：合同 | `tools/contracts.py` 的 ToolDefinition 有 model_definition、handler、可选 validate_arguments、bind(arguments) | 不采用通用 JSON Schema 执行器；服务器以显式 validator 为准 |
| A：Executor | 仅接受 JSON object；arguments UTF-8 上限 4096 bytes；validator 在 Handler 前执行；结果上限 32768 bytes；统一安全错误 | 保留 Registry / Policy / 预算 / Cancellation；未知 Tool 不执行 |
| B：query | 精确字段 query:string；strip 后非空；最多 512 字符；检查控制字符与 lone surrogate | 先 strip 再检查，边缘换行 / Tab 会被去掉并接受，见 §10 |
| B：Schema | Registry 的 query 为 required；additionalProperties=false | 客户端 Schema 与服务端 validator 双边存在 |
| C：Handler | 调用注入的 KnowledgeService.search(query, top_k=3) | 不直接读取任意文件，也不创建另一个 KnowledgeService |
| C：Evidence | 仅 id、category、source、source_version、text | 不输出 score、retrieved_at、source_title |
| C：截断 / 状态 | text 正文最多 800 字符，再附省略号；正常无结果 NO_MATCH；异常交给 Executor 安全转换为 ERROR | 最终显示长度可为 801；NO_MATCH 不阻止第二轮解释 |
| D：Registry | 静态三个注册名；Knowledge 实例有服务注入才绑定 executable Handler | 无动态发现、动态 import、Shell 或任意函数执行 |
| D：装配顺序 | Web 先绑定知识 Handler，再验证用户 Policy | 避免合法知识 override 在未绑定 Registry 上误报不可执行 |
| E：默认 | Analysis 关闭 / 空集合；Assistant 只开放查询 Tool；Knowledge 默认关闭 | 新 Tool 不自动迁移、重写既有 override |
| F：D1 / D1b | Mock 只驱动查询、评分；评分可降级到查询，查询不能反向降级；不 fallback 到 Knowledge | 没有合法 fallback 时返回正文；不是任意 request.tools[0] |
| G：Prompt | 已包含当前事实、评分、项目资料、一般概念、用户提供值、旧历史、NO_MATCH、单轮和数据边界 | Prompt 存在不等于真实模型遵守，见 §7 |
| H：UI | Catalog 提供 display_name / summary；前端取消固定两名称白名单；区分 registered / executable；modes 从后端获取 | 参数化 Tool 摘要不再伪装成 {}，不显示 query 原文 |
| H：Catalog 边界 | 不执行 Handler、不校验参数；Executor 仍用 Registry / Policy | **并非完全只用于展示**：Policy override 校验依赖 Catalog，见 §10 |

当前本地 override 确认 Assistant 已选中三个 Tool，Analysis 集合为空。这能解释 UI 的 3/3，但选中意味着允许模型调用，不意味着模型必然调用。

## 5. 真实请求构造与 Provider / Gateway 风险

### 5.1 当前 Qwen 精确配置

来自当前 `resources/profiles/presets.json`：

- Preset：`dashscope-qwen38-flash-r1`；合同 `1.0.2`。
- service：`dashscope`；adapter：`openai_chat`。
- base_url：`https://dashscope.aliyuncs.com/compatible-mode/v1`。
- exact model：`qwen3.8-flash`；Assistant 固定 OFF + Normal。
- Credential 只引用正式 credential_ref，本轮未解析真实值。

`ToolCallingService` 从 Registry / Policy 获取所有获准定义，首轮 `tool_choice=auto`。Adapter `_kwargs()` 将每个定义编码，不按名称、数量或是否带参数筛选。ProtocolSpec 负责现有生成参数编码，没有过滤第三个 Tool。第二轮保留消息关联并使用 `tool_choice=none`。

Knowledge 最终 Schema：

```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string", "minLength": 1, "maxLength": 512}
  },
  "required": ["query"],
  "additionalProperties": false
}
```

### 5.2 本轮离线 SDK 检查

使用正式 Assistant Context / Registry / Policy / Adapter，以及官方 OpenAI SDK + HTTPX MockTransport；所有凭据与响应均为虚构，真实网络被阻断。捕获 MockTransport 收到的请求体，仅输出安全字段。

确认结果：

1. 一次模拟 SDK 请求包含全部三个 Tool，包含完整 Knowledge required-query Schema。
2. 实际 SDK 请求体为 `tool_choice=auto`；OFF 编码为 `enable_thinking=false`。
3. 消息角色为 system / user，没有预注入现场事实。
4. 模拟 Provider 返回带 query 的 search_fishery_knowledge Tool Call 后，Adapter 保留 name、arguments、id，finish_reason=tool_calls。
5. 另行模拟三个 Tool 的合法响应：空参数和必填 query 两种均能归一化。

这排除了已检查的确定性代码路径中“第三个 Tool 被丢弃”“带参数定义被过滤”“标准 tool_calls 无法解析”的假设。**不等于取到了用户真实 Qwen Web 请求的网络报文，也不等于真实 Knowledge Tool 验收通过。**

### 5.3 尚缺的真实证据

已有 Trace 记录归一化后的 outcome，不保存 Provider 原始响应。故无法从旧日志核实某一次异常请求的原始 finish_reason、tool_calls、function.arguments，也无法证明那一次运行的 Schema / Policy 必然与本轮代码构造一致。

当前解析标准 message.tool_calls；未发现仅零参数 Tool 可解析的分支。非标准旧式 function_call 或不同 Provider 响应形式属于兼容性风险，但没有证据说明本次 Qwen 使用了这些格式。不能提前修改 Adapter 适配猜测中的响应。

## 6. 已有 Trace 与人工异常

安全筛选 `outputs/web-traces.jsonl`：2026-10-09 有 11 条 Qwen Assistant 完成记录；9 次首轮直接回答，2 次分别成功调用查询 / 评分 Tool 并完成第二轮；没有 Knowledge 调用。历史轮数从 0 增至 6。

日志不保存问题正文，因此不能逐条对应用户的每一个问题，也不能仅凭历史轮数证明 History 引起跳过 Tool。

| 用户报告 | 本轮可确认的边界 | 判定 |
|---|---|---|
| 0 Tool 却声称重新查询 DO=2.2 | Trace 确有多个无 Tool 的成功首轮；应用接受这类无依据声明的路径已离线复现 | 当前事实解释的可信性阻塞 |
| 无评分调用生成 49.0；实际评分约 81.3 | 数字来自用户人工观察，不是本轮 Provider 取证；无 Tool 评分声明可以被应用接受 | 不能把模型自拟评分当系统评分 |
| 未调用 Knowledge 却称“根据项目资料检索结果” | 当日没有知识调用；代码 / SDK 离线传输与解析正常 | 真实 Knowledge 集成未通过验收 |

三项都不能用“3/3 已授权”作为通过理由，也不能把“这次没调用 Tool”写成 Capability UNSUPPORTED。

## 7. Step 11 根因分析

### 7.1 已证明的应用接受问题

`ToolCallingService.run_request()` 无 tool_calls 时允许首轮正文直接结束；`AssistantService.send()` 在非空、正常 finish、未取消等条件满足后提交成功 turn，没有验证正文中“已查询 / 当前系统评分 / 检索结果”的事实来源。

本轮用虚构 Gateway 返回“本轮已重新查询当前数据，当前系统评分为49.0/100。”，且没有 tool_calls。结果仍为 successful_turn=true、used_tool=false、Request #1 final_answer、Request #2 not_started。

这是确定性反例。纯文本安全渲染防止 HTML 执行，但不防止模型陈述虚构操作。现有测试大多把合规最终文本预先放入 fixture，不能发现这一反例。

### 7.2 当前 Prompt 与模型选择

当前 System instruction 确实要求当前事实查询、当前评分调用、项目资料检索；没有旧“两 Tool”表述。使用 `tool_choice=auto` 时模型仍可以直接回答，规则不是协议强制。

Prompt 同时允许本轮用户给定值、历史解释、一般知识直接回答；“本轮尚未掌握”一类表述可能让模型将已出现的数值误当仍可使用。该解释只是候选，不是已确认根因。本轮不修改 Prompt，也不增加关键词 intent router 或预执行 Tool。

### 7.3 History 干扰

历史只传成功 user / assistant pair，有“历史不代表当前数据”的包装；不传 raw Tool Result、tool_calls 或 Trace。但历史最终回答中仍有旧观测值，而且被接受的虚构声明也能进入后续历史。

因此 History 放大错误是合理风险。已有日志不足以证明“首次调用，第二次必跳过”；需要同一问题的 fresh / repeated 对照。不能将 Provider 能力、Gateway 解析、Prompt 遵守和 History 干扰混为一种故障。

## 8. 测试质量审计

### 8.1 有效覆盖

现有离线测试覆盖参数对象、大小限制、validator 先于 Handler、拒绝额外字段、NO_MATCH 与错误区别、Registry 绑定、同一个 KnowledgeService、默认 / override、D1b 方向性 fallback、知识调用 public projection、安全参数摘要、单 Tool / 单 round / Cancellation。

`test_assistant.py` 已有 scripted Knowledge NO_MATCH 闭环；walkthrough 中“该测试尚未实现”的说法过时。网络阻断 fixtures 与虚构依赖仍存在，未发现新增测试必须读取真实 Secret 的要求。

### 8.2 未覆盖 / 不足

- Prompt 字句存在测试只能证明指令被传入，不能证明真实模型遵守。
- 三 Preset question matrix 使用预设正确选择的 scripted Gateway，不能证明多 Tool 下真实选择稳定。
- 未授权评分的测试让虚构模型预先给出拒绝回答，没有检验模型伪造评分时系统如何处理。
- 原有 Adapter 测试不足以独立代表三个 Tool 同时发送、required-query 标准 SDK 链路；本轮 MockTransport 已补充审计证据，但未提交新测试。
- 依赖 partial.keywords、绑定类型、固定集合顺序、AST 导入 / 构造形式的测试容易因等价实现改变而失败；有些能核实装配，但应与行为测试配合。

Copilot 报告最终为 827 Python / 187 Browser，以及 D1b、装配、名称拼写、UI whitelist 的 mutation 结果。这些是历史报告数字，**本轮没有重跑全量测试或重放 mutation，不能登记为本轮通过**。已核对相关断言与所述缺陷是否对应；没有修改测试来复现 mutation。

### 8.3 本轮实际执行

| 检查 | 结果 |
|---|---|
| 当前源码 / Git / 测试 / 文档对照 | 完成 |
| 三 Tool 请求构造 / 合法响应归一化 | 离线通过 |
| OpenAI SDK → HTTPX MockTransport → Adapter，required query | 离线通过，1 次模拟请求，0 次真实请求 |
| 无 Tool 却宣称查询 / 评分的回答 | 反例被当前服务接受，确认缺口 |
| query 边缘控制字符 / 截断语义 | 差异确认，见 §10 |
| 固定 query 的实际包内检索 | 有结果但相关性存疑，见 §10 |
| Full Python / Browser / 真实模型验证 | 未执行；不引用历史数字冒充当前结果 |

## 9. 文档与源码不一致

本轮仅记录，未同步改写其他文档。

| 文件 | 过时 / 冲突内容 |
|---|---|
| docs/copilot/KNOWLEDGE_TOOL_STEP_BY_STEP.md | 顶部 PAUSED / NOT IMPLEMENTED 与后续 Step 2–10、当前可执行注册不一致 |
| docs/handoff/README.md | 仍按两个 Tool、参数与 NO_MATCH / UI 尚待实现介绍 |
| docs/handoff/TOOL_CHANGE_MAP.md | 空参数限制、未来 query、固定两名称 whitelist、统一当前水质标签已过时 |
| docs/handoff/KNOWLEDGE_TOOL_V1_WALKTHROUGH.md | 混合未来与已实现内容；Registry 注入、参数执行、UI、scripted Assistant 测试描述未更新 |
| docs/deep-dive/tools/READ_ONLY_TOOL_CALLING.md | Knowledge 仍被描述为暂停 / 未注册 |
| docs/deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md | 两 Tool / Knowledge 未注册描述过时 |
| docs/STRUCTURE.md | 新 Handler 文件已入树，部分说明仍写 Knowledge 未实现 / handoff 为未实现设计 |
| docs/ROADMAP.md | STABLE 的两个 Tool 描述需要区分：第三个已离线实现，但真实集成尚未验收；PAUSED 文字不应掩盖此区别 |
| Step 9 before/after | 部分旧段落允许已有历史免查询，已与当前 Prompt 不同；“没有 timestamp 所以无法假装当前事实”的保证也不成立 |

research 中明确针对 `6b9dad9` 的旧审计可以作为历史研究；应保留基线标识，不能作为当前 Runtime 的描述。before/after 文档可以解释变更，但不应替代正式 CURRENT STATE 文档。

## 10. 非主要阻塞与代码质量风险

### P2：Catalog 与用户 Policy 校验耦合

`tools/policy.py::UserToolPolicyStore._validate()` 使用 `tool_catalog(registry)` 的 executable 集合约束用户选项。因此“Catalog 完全只参与展示”不成立。该依赖在 `6b9dad9` 已存在，不是 Step 10 新引入。

运行时 Executor 仍受 Registry / Policy 控制，Catalog 不执行函数或校验 query；没有发现由 Catalog 绕过 allowlist 的路径。但漏 Catalog 条目可能影响合法 Tool 授权配置。建议后续将 executable 判定归还 Registry，并保持 Catalog 仅投影；本轮不重构。

### P2：检索相关性独立风险

对实际包内 KnowledgeService 使用固定 query“鳗鲡低氧表现”，离线返回三个 life_cycle 条目：幼鳗 / 黑仔、成鳗、柳叶鳗。当前 intent 词表有“缺氧”，没有“低氧”。这些返回不足以直接证明命中了低氧表现资料，需小规模人工相关性核对。

它影响 Tool 调用后的证据质量，**不解释模型为什么没有调用 Tool**。本轮不实现 RAG v2、不修改排名；以后单独处理，不能把查询无合格结果与系统异常混淆。

### P3：合同边缘

- query 先 strip，输入边缘的换行 / Tab 被接受。若合同要求原始输入任何控制字符均拒绝，需要明确后调整；当前不是参数绕过执行权限。
- text 是 800 字符正文 + 省略号，展示最多 801；文档应精确写明。
- evidence 的 source_version 是知识来源版本，不等于检索算法版本；当前没有算法版本字段。
- 前端 `queried_this_turn` 以 used_tool 泛化记录，Knowledge 也可能令其为 true；当前没有发现据此展示“已查询水质”的消费路径，属于潜在命名风险。
- Tool 名称在 Registry、Catalog、Mock Renderer、评分专用业务显示中多处出现，有些是必要绑定，有些可后续减少；未发现需要为接管立即大规模重构的重复 Executor / 模型循环。
- public projection / UI 格式化处于应用和 Web 边界，没有发现检索显示字段进入 Diagnosis 规则的新增路径。

## 11. 阻塞与优先顺序

| 优先级 | 问题 | 当前是否需处理 |
|---|---|---|
| P1 | 无 Tool 的虚构查询 / 系统评分 / 项目检索声明仍被接受 | 阻塞真实 Knowledge / 多 Tool Assistant 验收；需用户决定修复边界 |
| P1 | 缺少异常请求的安全原始响应对照，无法区分模型选择与归一化 | 下一轮最小 Provider 取证；先解释请求数量 / 成本 |
| P2 | 检索“鳗鲡低氧表现”的相关性存疑 | 独立核对，不混入无 Tool 根因 |
| P2 | 当前文档大量未同步；Catalog 参与 override 校验 | 文档澄清 / 后续小调整，不要求立即改执行链 |
| P3 | 控制字符、截断、测试实现耦合、UI 命名 | 合同澄清与测试维护，可延期 |

未发现确定性“第三个 Tool 传不出去”或“必填 query 的标准 Tool Call 被丢掉”的代码阻塞。不建议回退整个 Step 2–10，也不建议通过开放多 Tool / 多 round 掩盖选择问题。

## 12. 推荐下一步：先取证，再决定修复

本轮停在审计。以下是待用户审查的最小真实请求计划，**尚未执行**。

### 12.1 第一组：Qwen 四次首轮请求

复用现有 Runtime / CredentialSnapshot / Gateway / Registry，retry=0、OFF + Normal、短问题、单次输出预算 256 tokens，不执行第二轮或完整 Fishery Analysis：

| 请求 | 可见 Tool | 问题目的 |
|---|---|---|
| 1 | 仅 get_current_water_quality | 明确要求查当前溶氧 |
| 2 | 仅 score_current_water_quality | 明确要求查当前系统评分 |
| 3 | 仅 search_fishery_knowledge | 明确要求 query=“鳗鲡低氧表现” |
| 4 | 全部三个 | 与第 3 项同一知识问题，比较多 Tool 选择 |

先保持正式路径的 tool_choice=auto，不偷偷改 required 来宣称选择问题已解决。总上限四次真实模型请求，输出预算合计 1024 tokens，另有输入 tokens；具体费用取决于账户计费，本轮未查价格、未产生费用。若有错误不重复探索。

每次只记录安全对照：实际 Tool 名称集合 / Schema、tool_choice、Provider 返回 model、finish_reason、原始 tool_calls 是否存在、name、arguments 是否通过 validator、归一化后是否一致、Usage。query 只核实是否匹配固定测试值，不将用户原文持久化。完整 Prompt、原始响应和认证头不进入报告 / Trace。

### 12.2 可选第二组：History 对照

如第一组不足，再单独说明并增加最多两次：同一当前事实问题，无历史与带旧值历史的首轮对照。需要明确记录测试历史的来源与时间，不自动采样 / Apply，不继承本轮诊断结果为新事实。评分 History 对照和跨 Provider 比较均不自动扩展。

### 12.3 修复方向需由用户选择

根据取证区分：请求编码、Provider 原始选择、response normalization、History、Prompt 合规。然后决定是否调整 Prompt / Tool 描述，以及如何限制“当前系统评分 / 已查询 / 检索来源”的无依据声明。仅追加更多文字指令不能视为已有确定性保证；也不能用关键词硬路由、自动预执行所有 Tool 代替模型选择。

## 13. 现在不要做

- 不修改真实 Preset / Managed Capability 合同，不以未调用 Tool 判 UNSUPPORTED。
- 不增加 Tool round、并行 Tool、Agent、第二套 Executor。
- 不修 Credential、不读源码根 .env、不复制 Secret、不改 ACL。
- 不做 RAG v2、Knowledge benchmark、Analysis 双重知识来源重构。
- 不重写 Mock 使其承担真实知识选择能力；scripted fixture 与模型真实能力分开登记。
- 不把历史 before/after 的测试数字或 mutation 声明当本轮回归结果。
- 不修改生产项目，不 commit / push。

本轮交付为这一审计报告；等待用户决定下一轮取证与修复范围。

核对入口：[Assistant](../../src/fishery_ai/assistant.py)、[Coordinator](../../src/fishery_ai/tool_conversation.py)、[Registry](../../src/fishery_ai/tools/registry.py)、[Executor](../../src/fishery_ai/tools/executor.py)、[Knowledge Handler](../../src/fishery_ai/tools/handlers/knowledge_search.py)、[Policy](../../src/fishery_ai/tools/policy.py)、[Preset](../../src/fishery_ai/resources/profiles/presets.json)。

## 14. 交付检查

报告 7 个本地 Markdown 链接均存在；未发现尾随空白或常见凭据字面量模式。`git diff --check` 无错误；新增未跟踪报告另以 no-index 检查，无空白错误（有 Git LF / CRLF 提示）。工作树仅新增本报告，原跟踪文件无 diff，`git diff --stat` 为空。没有 commit / push。

# Step 9 对照记录：Assistant 的 Tool 选择规则（before / after）

> 范围：**只改 `assistant.py::SYSTEM_INSTRUCTION` 一处常量文本**（纯新增 12 行，0 行删除）。不改 Registry / Policy / Handler / Mock / Analysis / `AssistantContextBuilder.build()` 的逻辑。
> 验证：`unittest discover -s tests` → **822 项通过**（821 → +1）；`node --test tests/test_browser_streaming.cjs` → **183 项通过**。
> **同日收尾**：按审阅意见做了 4 处语义修正（见 §7），产品改动仍在同一常量内，0 新增文件。

---

## 1. 本步的定位：文本在四处分生成

| 组件 | 位置 | 谁消费 |
| --- | --- | --- |
| **`assistant.SYSTEM_INSTRUCTION`** | `assistant.py:24` | **发布 Assistant**（`/api/assistant/chat` → `AssistantService.send` → `AssistantContextBuilder.build()` 把它设为 messages[0]） |
| `tool_conversation.SYSTEM_INSTRUCTION` | `tool_conversation.py:22` | 仅 Development/Test 的 `converse()`：工具 mock、capability probe、preset qualification |
| `ANALYSIS_TOOL_INSTRUCTION` | `application.py:26` | Analysis 工具路径（追加到 Analysis 自己的 system message） |
| 三份工具 description | `tools/registry.py` | 所有路径共用，经 `policy.model_definitions()` 过滤作为 `request.tools` |

**关键事实**：`ToolCallingService.run_request()` 只做 `replace(request, tools=definitions, tool_choice=…)`，**不会**插入自己的 system message。所以发布 Assistant 的 system prompt **就是** `assistant.SYSTEM_INSTRUCTION`，一处即可改全。

**改前的真实缺口**：该 prompt 对 `search_fishery_knowledge` **一字未提**；registry 的 `KNOWLEDGE_DESCRIPTION` 只说"是什么/不做什么"，**没有任何地方写"什么时候该用它"**。

## 2. before / after

| | |
| --- | --- |
| **before** | 规则全在讲「当前事实 vs 当前评分 vs 历史语境 vs NO_DATA/防伪造」，共 14 条短语（见 `test_selection_rules_are_in_program_system_for_every_question` 的清单） |
| **after** | 在原位置插入 **6 句**（12 行源码）知识相关规则；原 14 条短语**一字未动** |

`git diff --stat` = `1 file changed, 12 insertions(+)`。

## 3. Prompt 新增的规则（逐条）

| # | 新增内容 | 解决什么 |
| --- | --- | --- |
| 1 | 「选择 Tool 看当前回答**还缺什么信息**：需要当前评分用 `score_current_water_quality`；需要当前事实**而本轮尚未掌握**时用 `get_current_water_quality`；需要**项目特有**的养殖背景资料时用 `search_fishery_knowledge`；所需信息**已在本轮或历史上下文中**，或只是一般概念时，不调用任何 Tool。」 | 四个类目的判定依据 |
| 2 | 「同一问题确实需要两类尚未掌握的信息时，**只查询最关键的一项**，并在回答中**明确说明未查询的另一部分**；不得用一般常识冒充项目资料或现场事实。」 | 1 Tool / 1 Round 约束下的诚实降级 |
| 3 | 「**不要仅因为 Tool 可用就试探性检索**；用户**明确要求**查询项目资料，或回答**确实依赖**项目资料时，**可以**调用 `search_fishery_knowledge`。」 | 防过度调用，同时不禁止正当检索 |
| 4 | 「`search_fishery_knowledge` 返回的是**背景资料而非本轮观测**：不得据此给出当前数值、时间或状态，不得表述为当前系统数据。」 | 背景 ≠ 现场 |
| 5 | 「本轮**没有调用现场查询 Tool 时就没有当前数值**，不得从背景资料推断当前值。」 | 防"从资料推断当前值" |
| 6 | 「该 Tool 未授权或不可用时**说明无法查询项目资料**，不得凭印象编造项目内数据或标准。」 | 与既有"对应 Tool 未授权或不可用时说明…"同族；因为默认 Policy 不授权知识工具 |

## 4. 按用户要求做的四处修正

### 4.1 删除 `retrieved_at` 规则，并纠正字段表述

`retrieved_at` **不在 Knowledge Tool payload 里**（Step 4 已决定不发送：静态资料，时间对模型无信息量）。因此：
- 不带任何"时间语义"规则；
- **纠正此前的错误表述**：知识结果的实际字段是 **5 个** —— `id` / `category` / `source`（逻辑来源标识，如 `legacy:eel_knowledge.json`）/ `source_version` / `text`；**不含** `source_id`、**不含** `retrieved_at`、不含 `score`、不含 `source_title`。

因此"防背景当现场"的论证比原先更强：**payload 里根本没有任何时间字段，也没有传感器字段**，结构上不可能冒充当前快照。

同步修正了文档：`docs/handoff/KNOWLEDGE_TOOL_V1_WALKTHROUGH.md` 原写"条目保留 …、资源版本、**检索时间**与受限文本"（旧建议稿），已改为实际 5 字段并注明不发送 `retrieved_at`；同文件"未来可能新增 `knowledge_search.py`；当前文件不存在"也已标注为 Step 4 已创建。

### 4.2 不写"无条件全局优先级"

原提案是 `评分 > 现场事实 > 背景知识 > 不调用`，**已废弃**。改为按「**回答当前还缺什么信息**」判断（见 §3 第 1 条），并在确实需要两类缺失信息时要求**择一查询 + 明确说明未查询部分**，而不是让一个全局排序替用户做决定。

### 4.3 "禁止探索式检索" → "不要仅因为 Tool 可用而试探性检索"

措辞改为：不因"有 Tool"而试探；但**用户明确要求**或**回答确实依赖**项目资料时**可以**调用。避免把正当检索也一并禁掉。

### 4.4 工具名测试的边界

**不**要求 prompt 里的工具名集合等于 `ToolRegistry.registered_names()`。只要求：
- 本步涉及的三个名称确实出现在 prompt 中；
- prompt 里出现的**任何** snake_case 名称都必须是**已注册**的真实工具名（防止错拼/写入不存在的工具）。

## 5. 测试

| 层 | 测试 | 确定性 |
| --- | --- | --- |
| A 文本契约 | 扩展 `test_selection_rules_are_in_program_system_for_every_question`：短语清单从 14 条 → **28 条**（新增 14 条覆盖 §3 的 6 句），并对 5 个不同类型问题逐一断言 | ✅ |
| B 结构不变式 | 新增 `test_prompt_names_only_registered_tools_and_carries_no_schema_text`：提取 prompt 中所有 snake_case 名称，断言恰为三个真实工具名且都在 `registered_names()` 内；断言 prompt **不含** `additionalProperties` / `minLength` / `retrieved_at` / `source_id` / `raw score` | ✅ |
| C 装配不变式 | 既有：`messages[0]` 是程序 system、末条是问题、`tools` 为空（由 Policy 后续注入） | ✅ |
| D 链路安全 | 既有：模型请求 Knowledge 时链路安全渲染为 `UNRENDERED_TEXT`（D1 三条） | ✅ |
| E 真实模型是否照做 | **不进 CI**，Step 11 人工验收 | ❌ 随机/需付费 |

### 5.1 mutation check（实测）

在 prompt 中临时插入一个错名（`search_fishery_knowldege`）→ `AssistantSelectionRulesTests` **2 项失败**：结构不变式捕获错名，短语清单捕获被替换掉的那句。随后已还原（`git diff --stat` 复核为 `12 insertions(+)`，0 删除），全量重跑 822 OK。

### 5.2 这些测试**不**证明什么

- **不证明模型会照做**。它们只证明"规则确实写进了 prompt，且与结构一致"。
- 不证明检索质量（本步不碰检索）。
- 不证明 UI 呈现（`app.js` 仍会对所有已调用 Tool 显示"本轮已查询当前水质"，会把知识检索误标 → **Step 10**）。
- 零真实模型请求、零网络。

**测试过程中的一个坑（已解决）**：`\b` 不能用来提取提示词里的工具名 —— CJK 字符在 Python 的 `re` 里也算 `\w`，所以「用`get_current_…`」之间没有词边界。改用 ASCII 专用边界 `(?<![A-Za-z0-9_])…(?![A-Za-z0-9_])`。

## 6. 明确未做的改动

| 对象 | 状态 | 理由 |
| --- | --- | --- |
| `tools/registry.py`（三份 description） | 未改 | 逐字改动越界；且"何时使用"属**跨工具**规则，归 prompt（职责分工） |
| `application.py`（自动 RAG、`ANALYSIS_TOOL_INSTRUCTION`） | 未改 | Analysis 的检索无条件预取且已写明"固定上下文 vs Tool 观测""不必每次调用" |
| `tool_conversation.SYSTEM_INSTRUCTION` | 未改 | 只服务 mock / probe / qualification；mock 不学 Knowledge，改了无行为收益 |
| `policy.py` / Handler / `web.py` / `app.js` / `AssistantContextBuilder.build()` | 未改 | 越界或属 Step 10 |
| Multi-Tool / Multi-Round | 未做 | 1 Tool / 1 Round 上限不变 |

**登记的残余缺口（非本步）**：Analysis 的工具路径对 Knowledge **没有专门说明**——若用户为 Analysis 启用知识工具，模型只看到 registry description。Analysis 已有自动 RAG 在上下文里，叠加知识工具需要单独评审"双重知识来源"的语义。

## 7. 收尾（同日）：Prompt 语义修正 4 处

| # | 修正 | 改动前 | 改动后 |
| --- | --- | --- | --- |
| 1 | **区分“用户提供的当前值”与“系统观测值”** | 「本轮没有调用现场查询 Tool 时就没有当前数值，不得从背景资料推断当前值」——**过于绝对**，忽略了用户自己给了值的情况 | 「用户本轮明确提供的现场数值可作为用户提供的信息使用，但不得表述为系统当前观测值；当前值既未由用户明确提供、也未由 `get_current_water_quality` 返回时，不得声称系统掌握当前值」+ 保留「不得据此推断当前值」 |
| 2 | **收紧“历史上下文已有信息就不调用”** | 「所需信息已在本轮或历史上下文中……不调用任何 Tool」——会默许用历史旧值回答“现在”问题 | 「所需信息已由**用户本轮明确提供**、或只是一般概念、或只是在**解释历史内容本身**时，不调用任何 Tool；**历史中的旧现场值、旧状态、旧评分不能用于回答现在、当前或最新的事实问题**」 |
| 3 | **去掉两 Tool 时代措辞** | 「即使**两个** Tool 同时可用……不得并行或顺序请求**两个** Tool」 | 「即使**多个** Tool 同时可用……不得并行或顺序请求**多个** Tool」（已进入三 Tool 时代） |
| 4 | **明确 NO_MATCH 语义** | 未提及；prompt 的诚实性枚举只有 `NO_DATA、STALE、INVALID、PARTIAL` | 新增「`search_fishery_knowledge` 返回 NO_MATCH 表示检索正常完成但没有合格的项目知识证据，**不是 Tool 执行错误**；不得编造命中内容」 |

### 7.1 测试同步

短语契约清单 **14 → 38 条**（原 14 + Step 9 新增 14 + 收尾新增 10），仍对 5 个不同类型问题逐一断言；结构不变式（工具名 + 无 schema/无 `retrieved_at`/无 `source_id` 文本）不变。

**未新增测试文件**：本次只是收紧/替换已有规则的措辞，契约测试的短语清单已覆盖新表述。

### 7.2 范围保持

不改 Registry / Policy / Handler / Analysis / Mock；不新增 Tool 机制；不改 `AssistantContextBuilder` 逻辑。

## 8. 教训

1. **"优先级"和"缺什么"是两回事。** 全局排序会把两个都缺的信息强行排序，而正确的行为是"择一 + 说明另一部分"。写成"还缺什么"才能表达后者。
2. **先核对 payload 实际字段，再写约束。** 本步最初想加一条 `retrieved_at` 规则，核对后发现该字段根本没发给模型——凭空写规则会误导模型去引用不存在的东西。
3. **在 CJK 文本里提取 ASCII 标识符不能用 `\b`。** 中文字符是 `\w`，词边界不成立；必须用 ASCII 专用的前后否定。

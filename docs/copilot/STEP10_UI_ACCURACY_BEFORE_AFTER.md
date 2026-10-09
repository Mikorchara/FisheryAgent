# Step 10 对照记录：展示与公开活动信息准确性（before / after）

> 范围：**只改展示与公开活动投影**。不改检索算法、不改选择 Prompt、不改 Policy、不改 Registry / Handler、不实现 Multi-Tool、不处理 Analysis+Knowledge 双重 RAG。
> 验证：`unittest discover -s tests` → **827 项通过**（822 → +5）；`node --test tests/test_browser_streaming.cjs` → **187 项通过**（183 → +4）。

---

## 1. 修掉的问题

| # | 问题 | before | after |
| --- | --- | --- | --- |
| **A（新发现）** | Assistant 活动面板把 Knowledge 抹成 `unavailable`，并对**所有**已调用 Tool 统一标注"本轮已查询当前水质；读取快照，不等于新采样" | `app.js::safeAssistantActivity` 的名字白名单只有两个水质工具 → `search_fishery_knowledge` 被置 `null`；随后无条件追加水质语义行 | 名字改为**形状校验**（后端权威）；文案改为**后端下发的 Catalog 标签** + 一句对所有工具都成立的中性说明 |
| **U1** | 徽章忽略 `registered` / `executable`，对未绑定行谎报 "Registered / Executable" | 非 dev_only 行一律印刷常量串 | 分别投影两个布尔值 → 三种组合准确 |
| **U2** | "适用模式"是前端硬编码字符串，后端 `item["modes"]` 无消费者 | 常量 `"Analysis（Normal） / Assistant"` | 读 `item.modes`，前端只提供两个模式标签 |
| **B6** | 对带参工具显示假 `{}` | mock 路由 `"arguments": {}`；Analysis `arguments_summary="{}"` | 按**声明 schema** 生成摘要；参数值从不外泄 |
| 附属 | `queried_this_turn` 赋值后无消费者 | 死状态 | 保持原样（不改行为，本步不动它） |

## 2. before / after（逐处）

### 2.1 `tools/catalog.py`（新增两个**只读展示**助手）

| 函数 | 作用 |
| --- | --- |
| `catalog_display(name)` | 按名称返回 `display_name` + `display_summary`（= 该条目的 `short_description`）；**未知名返回 `{}`**，不编造标签 |
| `argument_summary(parameters)` | 声明参数为空 → `"{}"`；有声明参数 → `"参数已提供（内容未展示）"`。**永不包含参数值** |

两者都在 docstring 里写明：只参与"如何展示"，**不参与授权、校验或执行决策**。

### 2.2 投影层

| 文件 | before | after |
| --- | --- | --- |
| `assistant.py::AssistantResult.to_dict()` | `tool_activity` 只有 `used_tool/tool_name/tool_status/duration_ms`（+ 水质字段） | 名称已知时 `activity.update(catalog_display(name))` → 多出 `display_name` / `display_summary` |
| `web.py`（Development mock 响应） | `"tool_call": {..., "arguments": {} if 非 ERROR else None}` | `arguments_summary`（键名与 Analysis 一致）：`{}` / `参数已提供（内容未展示）` / `参数已拒绝` / `调用失败（内容未展示）` / `null` |
| `application.py::_analysis_tool_activity` | `arguments_summary="{}" if 非 ERROR else "参数已拒绝"` | 同上；新增 `registry` 参数以读取**声明 schema**（调用点 1 处同步） |

### 2.3 `resources/web/app.js`

| # | before | after |
| --- | --- | --- |
| 1 | `const names = ["get_current_water_quality","score_current_water_quality"]` → `names.includes(...)` | `^[a-z][a-z0-9_]{0,63}$` 形状校验；注释写明**是否已注册由后端保证**，此处只做防御性字符串校验 |
| 2 | 无条件 `["查询", "本轮已查询当前水质；读取快照，不等于新采样"]` | `["用途", tool.display_summary]`（有则显示）+ `["说明", "只读 Tool 调用；结果含义以工具说明为准"]`（中性） |
| 3 | `["Tool Name", tool.tool_name]` | 显示名与原名不同时渲染为 `知识检索（search_fishery_knowledge）`，否则只显示原名 |
| 4 | 徽章常量 `… Registered / Executable` | 新增 `toolRegistration(item)`，徽章与"执行状态"行**共用同一表达式** |
| 5 | `["适用模式", "Analysis（Normal） / Assistant"]` | 新增 `toolModes(item.modes)` + 2 项标签映射；注释写明 modes 只是展示 metadata |
| 6 | `arguments: ${… === null ? "未展示" : JSON.stringify(...)}` | 直接打印字符串摘要；`null`/空 → "未展示" |

## 3. 实际 UI 字段（改后）

### 3.1 Tool Manager（`/api/tool-policies` → `renderToolCatalog`）

| 页面元素 | 来源 | 硬编码 |
| --- | --- | --- |
| 复选框禁用 | `dev_only \|\| !registered \|\| !executable` | 否 |
| 标题 | `display_name` | 否 |
| **徽章** | `access_type` + `experimental` + `toolRegistration(item)` | 仅"DEV ONLY"占位串 |
| 用途 / 说明 / 类型 / 参数 | `short_description` / `detailed_description` / `access_type` / `parameter_summary` | 否 |
| **执行状态** | `toolRegistration(item)`（与徽章同源） | 否 |
| **适用模式** | `item.modes` + 2 项标签映射 | 仅模式**标签** |
| 来源 / 实验性质 / 规划状态 | `dev_only` / `experimental` / `planned` | 否 |
| 计数 | `catalog.length` + `filter(executable).length` | 否 |

### 3.2 Assistant 活动面板（`result.tool_activity` → `safeAssistantActivity` → `renderAssistantMessages`）

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `used_tool` / `tool_name` / `tool_status` / `duration_ms` | 后端 | 名字只做形状校验 |
| **`display_name` / `display_summary`** | **后端（Catalog）** | 前端不再持有任何工具名称/说明映射 |
| `quality` / `freshness` / `observed_at` / `evaluated_at` | 后端 | 仅当 payload 真的含 `water_quality` 时才有 → Knowledge 调用天然没有 |
| "用途" / "说明" 两行 | 后端摘要 + 常量中性句 | 不含任何水样采样语义 |
| "实验评分 EXPERIMENTAL…" | 常量，条件 `tool_name === score…` | 保持 |

### 3.3 Development 工具对话面板

`tool_call.name` + `arguments_summary`（不再有假 `{}`）+ 原始 `tool_result`。

## 4. 测试

**Python（+5）**

| 文件 | 测试 | 证明 |
| --- | --- | --- |
| `test_assistant.py` | `test_knowledge_activity_uses_catalog_labels_and_carries_no_water_fields` | Knowledge 调用：`tool_name` 正确、`display_name == 知识检索`、`display_summary` 含"不代表当前水质"、`tool_status == NO_MATCH`、**无** `observed_at/quality/freshness`、activity JSON 里**不含查询词** |
| `test_assistant.py` | `test_water_and_score_activity_labels_match_the_catalog` | 两个水质工具标签**等于 Catalog 条目**（单一来源，防漂移） |
| `test_analysis_tools.py` | `test_parameterized_tool_argument_summary_never_echoes_the_query` | 带参工具摘要为 `参数已提供（内容未展示）`、`result_status == NO_MATCH`、**查询原文不出现在投影里** |
| `test_catalog_knowledge.py` | `test_catalog_display_returns_labels_or_nothing_at_all` | 标签正确；未知名称返回 `{}` 而非编造 |
| `test_catalog_knowledge.py` | `test_argument_summary_follows_the_schema_and_never_echoes_values` | 无参 → `{}`；有参 → 未展示文案；**不含参数名** |

**浏览器（+4）**

| 测试 | 证明 |
| --- | --- |
| `Assistant knowledge activity shows catalog labels and never water snapshot semantics` | 面板含 `知识检索（search_fishery_knowledge）`、含"不代表当前水质"；**不含**"本轮已查询当前水质"、"读取快照"、"快照"、`unavailable`、`observed_at/quality/freshness`；`assistant-run-details` 里 `tool_name` 与 `NO_MATCH` 均正确 |
| `Assistant water activity keeps its catalog summary and gains no knowledge wording` | 水质调用仍显示水质摘要 + 中性说明 + `fresh`；**不含**知识措辞（不退化） |
| `Tool Manager badge and mode row project the backend booleans without guessing` | 3 条目录：可执行行徽章为 `Registered / Executable`，未绑定行为 `Not Registered / NOT EXECUTABLE` 且**不**含旧文案；勾选框按 `registered` 禁用；`modes:["assistant"]` 时该行只显示 `Assistant`；带参行显示 `query: string` |
| `Development tool trace shows a safe argument summary instead of a false empty object` | 显示 `arguments: 参数已提供（内容未展示）`，**不**出现 `arguments: {}`；无 schema/路径字样 |

**既有测试的同步改动（4 处断言 + 1 处 fixture）**

| 文件 | 改动 | 理由 |
| --- | --- | --- |
| `test_web_tool_conversation.py` ×2 | `tool_call["arguments"] == {}` → `arguments_summary == "{}"` | 字段改名（值类型已从"原始参数"变为"摘要字符串"，旧名会产生误导） |
| `test_browser_streaming.cjs` ×1 | dev 面板 fixture `arguments:{}` → `arguments_summary:'{}'` | 同上 |
| `test_browser_streaming.cjs` ×2 | `children.length,2` → `,3` | `toolManagerFixture` 扩到**真实的三条目录**（原本只镜像旧的两条） |
| `test_browser_streaming.cjs` ×3 | `0 / 2`、`1 / 2` → `0 / 3`、`1 / 3` | 同上（分母是 catalog 长度） |

### 4.1 mutation check（实测）

把 `safeAssistantActivity` 的名字校验改回原来的**两工具白名单** → 新增的 knowledge 浏览器用例立即失败，实测显示 `Tool Name 知识检索（null）`（即缺陷的实际表现）。已还原，全量重跑 827 + 187 通过。

### 4.2 这些测试**不**证明什么

- 不证明真实模型会按 Step 9 的规则选择工具（Step 11 人工验收）。
- 不证明检索质量。
- 浏览器测试断言的是**渲染文本**，不是真实模型输出。
- 零真实模型请求、零网络。

## 5. 明确未做

不改 Knowledge 检索算法；不改 `assistant.SYSTEM_INSTRUCTION`（Step 9 已定稿）；不改 Policy / 默认 JSON；不改 Registry / Handler；不实现 Multi-Tool；不处理 Analysis+Knowledge 双重 RAG；不改 Trace 记录（参数值仍不写入 Trace）；`queried_this_turn` 死状态保持原样。

## 6. 教训

1. **"对每个已调用 Tool 都加同一句话"是一类必然出错的写法。** 那句话里任何一个词（快照/采样/查询）只要带某个工具的语义，加到别的工具上就是假话。要么用真正的通用句，要么让后端下发每个工具自己的说明。
2. **加第三个工具时，要去检查"从来没被执行过的分支"。** 名字白名单、徽章常量串、`arguments: {}` 三处都是"之前只有两个无参同类工具"才成立的假设；前两处从未在真实场景显现，第三处从未被带参工具触发。
3. **`registered`/`executable` 是两个独立事实，不要合成一个布尔再用同一个文案输出。** 三种组合都要能显示，且徽章与详情必须同源。
4. **改前端 payload 字段名时，先 grep 全部消费者。** 这次 `arguments` → `arguments_summary` 只有 2 处 Python 断言 + 1 处 fixture + 1 处渲染，改动成本可控；若消费者更多，就该保留旧键。

# Step 6 对照记录：Catalog 新增 Knowledge 条目（before / after）

> 范围：**只改 Catalog 展示 metadata**。本步不注册、不授权、不改装配、不改 UI 文案。
> 验证：`unittest discover -s tests` → **806 项通过**（796 → +10）；`node --test tests/test_browser_streaming.cjs` → **183 项通过**。

---

## 0. 本步做什么、不做什么

| | 内容 |
| --- | --- |
| **做** | 在 `tools/catalog.py` 的 `CATALOG` 中新增 `search_fishery_knowledge` 条目，并给出真实 `parameter_summary` |
| **不做** | 不改 `registered_names()`、不改 `ToolRegistry` 绑定逻辑、**不改 `policy.py`**、不改包内默认 `tool_policies.json`、不改 `web.py` 装配、不改 `app.js`、不改 `assistant.py` |
| **不做（用户已决定）** | **不新增"仅 Assistant"服务端硬边界**；不制造第二份 `modes` 定义；Assistant-only 边界留作后续独立架构议题 |

Step 6 之后用户能做什么、仍然不能做什么，见 §5。

---

## 1. before / after

### 1.1 `src/fishery_ai/tools/catalog.py`

**Before**：`CATALOG` 只有 2 条；`SEARCH_FISHERY_KNOWLEDGE` 未 import。

**After**：

```python
from .registry import CURRENT_WATER_QUALITY, SEARCH_FISHERY_KNOWLEDGE, WATER_QUALITY_SCORE

CATALOG = (
    ToolCatalogEntry(CURRENT_WATER_QUALITY, ...),      # 原样未动
    ToolCatalogEntry(WATER_QUALITY_SCORE, ...),        # 原样未动
    ToolCatalogEntry(SEARCH_FISHERY_KNOWLEDGE, "知识检索",
        "只读检索项目内鳗鲡养殖背景知识；不代表当前水质，也不做现场诊断",
        "复用与 Analysis 相同的 KnowledgeService 与包内固定知识资源，来源标识为 legacy:eel_knowledge.json。"
        "结果是背景证据而非现场事实，无合格命中时返回NO_MATCH（不是错误）。检索基线尚未做评测，"
        "知识块也没有逐条文献出处，因此不得当作专业养殖或用药依据。",
        parameter_summary="query: string（必填，1–512 字符）"),
)
```

**`tool_catalog(registry)` 一行未改** —— 包括那行硬编码的 `"modes": ["analysis", "assistant"]`。这是刻意的：`modes` 的**单一权威来源**必须保持唯一，本步不引入任何按工具分支的模式逻辑。

### 1.2 三条新条目的字段取值与理由

| 字段 | 取值 | 理由 |
| --- | --- | --- |
| `name` | `search_fishery_knowledge` | 必须**逐字**等于 Registry 常量，否则 `registered` 永远为 False |
| `display_name` | `知识检索` | 与 `水质评分` 中文名风格一致；不用英文名 |
| `short_description` | 见上 | 一句话说清"是什么"和**最容易被误解的一点**（不代表当前水质） |
| `detailed_description` | 见上 | 写清数据来源、NO_MATCH 语义、以及**未经评测**的诚实声明 |
| `parameter_summary` | `query: string（必填，1–512 字符）` | **必须改**：默认值 `"无；参数必须为 {}"` 对这个工具有参数的工具是错的 |
| `access_type` | `READ ONLY`（默认） | 与 Handler 的真实行为一致 |
| `experimental` | **`False`**（默认） | 见 §2.1，反直觉但正确 |
| `dev_only` / `planned` | `False`（默认） | 它不是占位符，也不是未来规划 |

---

## 2. 两个需要单独说明的决定

### 2.1 `experimental=False`：名称不能机械照抄水质评分工具

水质评分工具设了 `experimental=True`，看起来"Knowledge 也没评测，也应该 True"。**不成立**，因为该字段在 UI 里被渲染成一个**固定的具体结论**：

```js
["实验性质", item.experimental ? "EXPERIMENTAL / NOT PROFESSIONAL STANDARD" : "否"]
```

`NOT PROFESSIONAL STANDARD`（不是专业标准）是一句**评分口径**的声明。知识检索**不做任何评分**，"不是专业标准"套在它身上是**无意义的错标**。它真正的风险是别的（检索基线未评测、知识块无逐条出处），所以该风险写进 `detailed_description` 文本，而不是复用这个评分语义的布尔位。

**代价**：Tool Manager 的"实验性质"行会显示"否"。这**低估**了该工具的成熟度风险 —— 但比显示一句**错误声明**要好，且正确措辞属于 Step 10（UI 文案）的职责。

### 2.2 `item["modes"]` 目前**没有任何消费者**（本步核对结论）

核对全部消费者后的实测结果：

| 消费者 | 是否读 `item["modes"]` |
| --- | --- |
| `tools/policy.py:109` | **否** —— 只读 `item["executable"]` |
| `web.py:259` | 否，只是原样 `jsonify` 整个 catalog |
| `resources/web/app.js` | **否** —— 2553/2576 等读的是 `toolPolicyDraft.modes`（即 `policy.modes`），而 2569 那行"适用模式"是**前端自己写死的字符串** `"Analysis（Normal） / Assistant"` |

即：`tool_catalog()` 生成的 `modes` 字段**当前是死输出**（输出但无人消费）。因此本步的"不动 `modes`"在语义上是安全的：它既不会给用户带来新权限，也不会有第二份定义与之冲突。
**遗留**：前端那句写死的"适用模式"与后端输出的 `modes` 是**两份内容相同但互不相干的字符串**。合并它们属于 Step 10。

---

## 3. 既有断言的改动（3 处，全部是"快照了条数"的断言）

| 文件 | before | after | 为什么必须改 |
| --- | --- | --- | --- |
| `tests/test_tool_policy_manager.py::test_catalog_only_two_real_tools` | `assertEqual(len(catalog), 2)` | 改名为 `test_catalog_lists_every_known_tool_without_granting_execution`，断言**名称列表** = 3 项 | 断言的是条数，而本步就是加一条 |
| `tests/test_tool_policy_manager.py::test_web_returns_catalog_and_no_profile_or_secret` | `assertEqual(len(...["catalog"]), 2)` | 断言**名称列表** = 3 项 | 同上（端点级快照） |
| `tests/test_knowledge_registration.py` | `test_catalog_exposes_no_knowledge_entry_yet`（断言 executable 只有两个）+ `test_user_override_cannot_select_knowledge_yet`（断言 `TOOL_NOT_EXECUTABLE`） | 换成 `test_registration_alone_never_authorizes`（断言默认 Policy 未授权）+ `test_override_cannot_select_an_unbound_tool`（断言 `UNKNOWN_POLICY_TOOL`） | 前者的断言**描述的是 Step 5 的临时状态**，被 Step 6 合法推翻；后者断言的错误码在注入服务后已不再出现 |

**把"条数"改成"名称列表"不是顺手美化**：条数断言只能证明"数量对得上"，改名后能证明"**是哪三个**、顺序是什么"。前者在顺序错乱或增删互抵时会假通过。

**后一处改动是一处真实语义变化，必须说清**：Knowledge 工具**已注册**（Step 5）且 **Catalog 现在承认它可执行**（Step 6），所以 `TOOL_NOT_EXECUTABLE`（"在名字表里但不可执行"）这条路径对该工具**已在注入服务的实例上关闭**。未注入服务的实例上，剩下的大门是 `lookup()` 失败 → `UNKNOWN_POLICY_TOOL`。两个错误码都不变，变的是**这个工具此后落在哪一个上**。

---

## 4. 新增测试 `tests/test_catalog_knowledge.py`（10 项）

| # | 测试 | 证明什么 |
| --- | --- | --- |
| 1 | `test_catalog_lists_every_known_tool_in_declared_order` | 三个名称、固定顺序；**且未绑定的实例也照样列出**（列表是静态的） |
| 2 | `test_knowledge_entry_metadata_is_explicit` | 显示名、READ ONLY、非 dev_only/planned、描述含 "不代表当前水质" / "NO_MATCH" / 来源标识 |
| 3 | `test_knowledge_entry_is_not_flagged_as_a_scoring_standard` | `experimental is False`（§2.1 的决定被测试锁住） |
| 4 | `test_knowledge_parameter_summary_is_not_the_parameterless_default` | 新条目的 `parameter_summary` ≠ 无参默认值；两个水质条目**仍等于**默认值 |
| 5 | `test_executable_flag_follows_the_registry_binding` | 注入服务 → `registered/executable` 均 True；未注入 → 均 False |
| 6 | `test_entry_names_stay_inside_the_registry_name_allowlist` | `CATALOG` 里的名称 ⊆ `registered_names()`（防止 Catalog 写出一个代码库里不存在的工具） |
| 7 | `test_modes_have_one_authority_and_no_per_tool_rule` | 三个条目 `modes` 全等；**且 `ToolCatalogEntry` 没有 `modes` 字段**（结构上排除"按工具配模式"） |
| 8 | `test_catalog_alone_cannot_grant_execution` | 未绑定实例 + 用户 override 选择它 → 抛 `ToolPolicyError` |
| 9 | `test_bound_knowledge_becomes_user_selectable` | 注入服务 + override 选择它 → 保存成功，`effective()["assistant"].exposed_tools == (知识工具,)` |
| 10 | `test_catalog_entry_does_not_change_package_defaults` | 包内默认 Policy 仍只授权水质查询；不建 override 文件；`defaults`/`effective()` 的 analysis 仍为空 |

### 4.1 这些测试**不**证明什么（诚实边界）

- 不证明**检索质量**：`FakeKnowledgeService.search()` 永远返回 `()`，它只验证 **metadata 与门禁**，不验证召回。
- 不证明**真实 KnowledgeService** 会被正确装配 —— 本步不碰 `web.py`，Step 8 才做。
- 不证明 **UI 渲染正确**：只断言后端 JSON 的字段值；`app.js` 怎么画由既有 mock fixture 覆盖，未新增前端断言。
- 不证明 **模型会选它**：那是提示词与真实调用的事（Step 9 / Step 11）。

---

## 5. Step 6 之后：用户实际能做什么 / 仍然不能做什么

**能**：

1. 打开 Tool Manager（`/api/tool-policies`）能看到**第三行 "知识检索"**，含名称、用途、说明、参数摘要（`query: string（必填，1–512 字符）`）、类型、执行状态、来源、实验性质、规划状态。
2. 当该实例**注入了 `KnowledgeService`** 时，这一行变为**可勾选**，用户的 override 可以保存并生效（测试 9 证明）。
3. 展开详情能看到**准确的执行状态**：`Registered / Executable` 或 `Not Registered / NOT EXECUTABLE`。

**不能**：

1. **默认不授权** —— 包内 `tool_policies.json` 未改，不勾选就不授权；未勾选时"注册存在"不产生任何行为。
2. **应用本体里勾不上** —— `web.py` 未注入（Step 8），所以真实运行时这一行是**禁用**的。
3. **不会被默认勾选** —— 没有任何代码会自动替用户勾上；旧 override 也不会被静默改写。
4. **UI 文案还不区分它** —— §6 的 U1/U2 未解，界面上对"知识检索"和"水质查询"的措辞没有区别。

---

## 6. 本步暴露的两个既有问题（**未修，只登记**）

| # | 问题 | 为什么现在才出现 | 归属 |
| --- | --- | --- | --- |
| **U1** | `app.js:2563` 的徽章 `badge.textContent` 忽略 `registered`/`executable`，**非 dev_only 行一律印刷 "… · Registered / Executable"**。未绑定实例上"知识检索"这行徽章会**谎报**可执行（详情区与禁用状态却是准确的） | 在 Step 6 之前，Catalog 里不存在"非 dev_only 但未注册"的行，这个分支**从未被执行过** | **Step 10**（UI 文案）；建议徽章改为按 `registered && executable` 分支 |
| **U2** | 详情区 `["适用模式","Analysis（Normal） / Assistant"]` 是**前端写死的字符串**，与后端 `item["modes"]` 无关联（§2.2） | 同上：两者至今恰好一致，所以看不出是两份来源 | **Step 10** |

两者都**不影响权限**（勾选框由 `!item.registered` 禁用，是 fail-closed 的），只影响**界面表述准确性**，因此不阻塞本步、也不值得为此扩大 Step 6 范围。

---

## 7. 后续登记（更新）

| # | 项目 | 状态 |
| --- | --- | --- |
| **D1b** | `MockToolGateway` Request #1 的 `request.tools[0]` fallback | 仍是 **BLOCKER BEFORE MOCK KNOWLEDGE ENABLEMENT**（Step 5 起就有，本步未动） |
| **U1** | UI 徽章忽略 `registered`/`executable`（§6） | 新增，Step 10 |
| **U2** | UI"适用模式"与后端 `item["modes"]` 双来源（§6） | 新增，Step 10 |
| **K1** | `KnowledgeService` 缺 `retrieval_version` | 未变 |
| **K2** | Handler 侧若引入总量预算，必须显式（`PARTIAL` / `truncated`），不得静默 | 未变 |
| **B6** | `web.py:1127` `"arguments"` 字段对带参工具不准确 | 未变 |

---

## 8. 验证命令与结果

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
# Ran 806 tests in 26.352s — OK

node --test tests/test_browser_streaming.cjs
# tests 183 / pass 183 / fail 0
```

本步**没有任何真实模型请求、没有网络访问**（测试在 `setUp` 中 patch `socket.*` 使其抛错）。

---

## 9. 教训

1. **一个布尔字段的含义由它的"渲染方式"决定，不由字段名决定。** `experimental` 名为"实验性"，实为"不是专业标准"。跨工具复用布尔位前，先看它被渲染成什么句子。
2. **先查"这个输出有没有消费者"。** 若先假定 `modes` 有权限含义，会为它设计一套根本不存在的约束。实测结论是它当前无人消费。
3. **"数量断言"会在增删时假通过。** 三处既有断言写的是 `len(catalog) == 2`，改成名称列表后才真正约束内容。
4. **新增可见行会暴露从未被执行过的 UI 分支。** U1 是一直存在的缺陷，但只有出现了"非 dev_only 且未注册"的行才第一次浮出水面 —— 加展示项时应当顺带问一句"界面上哪个分支是被这次新增第一次走到的"。

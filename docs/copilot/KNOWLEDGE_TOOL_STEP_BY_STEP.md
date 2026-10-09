# Knowledge Tool 分步实施思路

**状态：学习 / 规划稿。Knowledge Tool 仍是 PAUSED / NOT IMPLEMENTED。本文不是实施授权，也不改变任何已发布合同。**

本文只回答"如果要动手，按什么顺序动、每步改哪里、怎么验证"。设计依据和取舍不在这里重复：

- 设计研究（暂停）→ [`docs/deep-dive/research/KNOWLEDGE_TOOL_DESIGN.md`](../deep-dive/research/KNOWLEDGE_TOOL_DESIGN.md)
- 学习案例（含未来 schema 与逐层推演）→ [`docs/handoff/KNOWLEDGE_TOOL_V1_WALKTHROUGH.md`](../handoff/KNOWLEDGE_TOOL_V1_WALKTHROUGH.md)
- 通用新增规范 → [`docs/deep-dive/tools/ADDING_A_TOOL.md`](../deep-dive/tools/ADDING_A_TOOL.md)
- 层间关系 → [`docs/handoff/TOOL_CHANGE_MAP.md`](../handoff/TOOL_CHANGE_MAP.md)

---

## 0. 先回答三个前置判断

### 0.1 现在的 RAG 够用吗

**对当前规模够用；但它没有被测量过，所以"改进"目前无法验证。**

实测事实（来自源码与本次运行）：

| 观察 | 数值 / 现象 | 影响 |
| --- | --- | --- |
| 知识块数 | 31 | 规模小，人工调参可行 |
| portable 索引词表 | **正好 2000**（`max_features=2000` 已用满） | **语料一增长，特征选择就会漂移**，可能挤掉旧特征，检索质量反而下降 |
| 中文处理 | `char_wb` 2–4 gram，无分词 | 靠 `EXPANSIONS` 手工补口语词；新领域词必须人工维护 |
| 打分组成 | TF-IDF 相似度 + 关键词 +0.3 + 类别调整（+0.12 / +0.15 / +0.28 / ×0.1） | 分数**已经不是纯相似度**，是"相似度 + 类别先验"的混合信号 |
| 阈值 | 0.04，**只作用于 TF-IDF 路径** | keyword 路径没有同门槛，分数尺度不同（2.0/3.0 量级） |
| 评测集 | **不存在** | 无法回答"这次改动是变好还是变坏" |
| 意图判断 | 关键词表（`_intent()`） | 误判会直接改变证据构成（见 0.3） |

结论：

- **优点要保留**：零依赖、完全离线、确定可复现、有 `evidence_id`/`source_id` 溯源、31 块小到可以精确控制。
- **主要风险不是"检索太弱"，而是"没有基线"**：0.04、+0.3、+0.12 这些数字都没有数据支撑；`KNOWLEDGE_TOOL_DESIGN.md` 最后一句也写了"先测量当前 baseline，再决定是否改进检索"。
- **2000 特征上限是隐藏的时间炸弹**：知识库只要长大，检索行为就会无预警地变化。

### 0.2 该直接做这个 Tool 吗

**值得做，但不要和"升级 RAG"绑成一个项目。**

Tool 的价值和检索质量无关：

- 现在 Assistant **首轮完全不注入 Knowledge**（`READ_ONLY_TOOL_CALLING.md`：Assistant 不预注入 Snapshot / Diagnosis / RAG）。所以"鳗鱼缺氧有什么表现"这类概念问题，当前**根本拿不到项目资料**，只能靠模型自身知识。
- Tool 就是补上这个缺口的唯一途径，而且**复用现有 `KnowledgeService`**，不需要新的检索实现。

但要注意两件事：

1. Tool 会把检索质量**直接暴露给用户**。以前 Analysis 的 RAG 有 system prompt 兜底（"RAG Evidence 仅是背景知识 / 不得诊断具体疾病 / 不得直接推荐具体药物"），Assistant 直答时没有这层护栏，检索不到就必须诚实说"资料不足"。
2. `KNOWLEDGE_TOOL_DESIGN.md` 明确写了：**不要用"加入 Tool"来替代 RAG 评估**。两者是独立研究项。

**建议顺序（2026-10-08 更新）**：**baseline 暂缓**（见 §2 决定 1 —— 本项目目标是学习并完成 Tool 接入，不启动 RAG 改进项目），直接进入 Tool 实现；baseline 留作 future / research。两者本来也不互相阻塞，随时可以补测。

### 0.3 以后升级 RAG，Tool 要跟着变吗

**大部分情况不用。** 现在有一条很窄的接口把两者隔开了：

```text
Retriever 实现（TF-IDF / 未来 embedding）
        ↑ 被封装
KnowledgeService.search(query, *, top_k, retrieved_at, intent_text)
        → tuple[KnowledgeEvidence, ...]      ← 唯一出口、稳定合同
        ↑ 被调用
Knowledge Handler（薄映射）
        ↑
Executor / Policy / Registry / UI
```

只要 `search()` 的**签名和返回类型不变**，以下升级**Tool 一行都不用改**：

- 换 TF-IDF → embedding / 混合检索
- 调整 `max_features`、ngram、扩展词、类别权重、阈值
- 调整 top_k 默认值、加 rerank

会**真正波及 Tool 合同**的只有这几种情况，需要单独评审：

| 升级类型 | 是否改 Tool | 说明 |
| --- | --- | --- |
| 返回类型不再是 `KnowledgeEvidence` | 是 | 会改 `contracts.py` → 影响 Handler 映射与测试 |
| 需要新参数（category 过滤、时间范围等） | 是 | 参数 schema 与工具的 `validate_arguments` 要跟着动；**Executor 本身已支持带参数**（Step 2 已完成） |
| 需要多跳检索（query rewrite → 再检索） | **是，且更严重** | 会撞上当前 **1 call / 1 round / 2 requests** 的预算；这不是"Tool 变了"，而是**预算模型要重新讨论**（可能被误当成 Agent） |
| 索引需要异步重建 / 热更新 | 是 | Handler 要新增"索引未就绪"状态 |
| 分数语义变化 | **不需要改合同，但必须改结果里的版本标识** | 否则无法解释"这次回答基于哪版检索" |

所以本方案要求：**结果里从一开始就带 `retrieval_mode` + `retrieval_version`**（研究文档已建议），这样将来升级检索 = 改实现 + 改版本号，Tool 合同不动。

---

## 1. 分步计划

每一步都**独立可提交、可回滚**，且**先有测试再改产品代码**。

### Step 1：建立 RAG baseline 评测集（**已暂缓**，移入 future / research，不作为本计划前置步骤）

- **目标**：给"检索好不好"一个可重复的数字。
- **新增**：`tests/fixtures/knowledge_eval_queries.json`（约 25 条：`query` + 期望 `evidence_id` + 期望 `category` + 一句标注理由）、`tests/test_knowledge_baseline.py`（离线，只调用现有 `KnowledgeService`）。
- **产出指标**：Top-1 命中率、Top-3 命中率、空结果率、误命中疾病块的比例。
- **完成判据**：数字记录在测试输出里；成为后续任何检索改动的回归网。
- **风险**：期望值靠人工标注，规则要写清楚（例如"只标一个最强期望 id，不标模糊项"）。

### Step 2：Tool 框架最小演进 —— 受控参数合同（与 Knowledge 无关）—— **已实施 2026-10-08**

这一步就是 Walkthrough §8 说的"最小框架改动点"，**先做它、先证明旧工具完全兼容**。

- **目标**：让 Executor 支持"有参数的工具"。
- **实际改动（2 个源文件）**：
  - `tools/contracts.py`：`ToolDefinition` 新增 `validate_arguments: Callable[[dict], dict] | None = None` 与 `bind()` 方法。
  - `tools/executor.py`：`arguments` 必须为 JSON object（不再要求为空）→ `definition.bind(arguments)` → `invoke()`。
- **实施时的关键修正**：原计划写的是"统一为 `handler(validated_arguments)`，旧工具用固定包装"。实际**不可行**——既有测试依赖 `handler` 仍是 `functools.partial`（`test_web_tool_conversation.py` 读 `.handler.keywords["reader"]`），并有零参 `def handler():`。最终改为**两种形状并存**：未声明参数 → `handler()`；已声明 → `handler(validated)`。结果**零测试改动**。
- **硬约束（都已满足）**：旧两个工具仍严格只接受 `{}`；不引入反射 / `getattr` / 任意 `**arguments` / 第二套 Executor；Cancellation、Policy、预算、错误清洗、结果大小规则仍由同一个 Executor 负责。
- **测试**：新增 `tests/test_tool_argument_contract.py`（14 项）；未修改任何既有测试。
- **完成判据（已达成）**：`Ran 736 tests ... OK`。
- **详细 before/after** → [`STEP2_TOOL_ARGUMENT_CONTRACT_BEFORE_AFTER.md`](STEP2_TOOL_ARGUMENT_CONTRACT_BEFORE_AFTER.md)

### Step 3：新增 `ToolStatus.NO_MATCH` —— **已实施 2026-10-09**

- **实际改动（2 个文件）**：
  - `tools/contracts.py`：`ToolStatus` 新增 `NO_MATCH = "NO_MATCH"`，并在类文档串写明"非错误状态 `error_code is None`、只有 `ERROR` 终止第二轮"。
  - `resources/web/app.js`：`safeAssistantActivity()` 的 `tool_status` 白名单加入 `NO_MATCH` —— 后端合同已接受该状态，前端安全投影也同步认识它（这不等于开放 Knowledge Tool）。
- **明确未改动**：`tool_conversation.py`、`tools/executor.py`、`observability.py`、`assistant.py`、`web.py`、`tools/policy.py`、`tools/catalog.py`、`tools/registry.py`、`ToolErrorCode`、历史 Preset 证据。
- **验证（实测）**：
  - 新增 `tests/test_tool_status_no_match.py`（**10 项**），覆盖"非错误结果 → 继续 Request #2 → Assistant COMPLETED → Trace 安全记录 → UI 投影保留"，并证明旧五值语义不变；
  - `tests/test_browser_streaming.cjs` 的状态参数表加入 `NO_MATCH` 一行；
  - `unittest discover -s tests` → **746 项通过**；`node --test tests/test_browser_streaming.cjs` → **183 项通过**。
- **详细 before/after** → [`STEP3_TOOL_STATUS_NO_MATCH_BEFORE_AFTER.md`](STEP3_TOOL_STATUS_NO_MATCH_BEFORE_AFTER.md)

### Step 4：新增薄 Handler —— **已实施 2026-10-09**

设计与实施记录：设计稿 [`STEP4_KNOWLEDGE_HANDLER_DESIGN.md`](STEP4_KNOWLEDGE_HANDLER_DESIGN.md)（含 §0 三条实施前调整）；对照记录 [`STEP4_KNOWLEDGE_HANDLER_BEFORE_AFTER.md`](STEP4_KNOWLEDGE_HANDLER_BEFORE_AFTER.md)。

- **新增（只新增，未改任何既有文件）**：
  - `src/fishery_ai/tools/handlers/knowledge_search.py` —— `search_fishery_knowledge(arguments, *, service)`
  - `tests/test_knowledge_handler.py` —— 15 项
- **预算**：`top_k=3` 写死 + 单条 800 **字符**（超出加 `…`）+ Executor 既有 32768 B 兜底。**没有** Handler 侧总量裁剪。
- **版本信息**：`retrieval_mode` **纯透传** effective `service.backend`（已实测确认 sklearn 缺失时会就地变成 `keyword`）；**本步不提供** `retrieval_version`（Service 尚无稳定 metadata，见 §4 K1）。
- **不暴露**：`score` / `retrieved_at` / `source_title` / 本机 filesystem path。`source`（`legacy:eel_knowledge.json`）是逻辑来源标识，**可以**给模型。
- **异常**：服务异常**向上传播**，绝不被吞成 `NO_MATCH`。
- **未做**：Registry 注册、Catalog、Policy、装配、提示词、UI、`tools/__init__.py` 导出。
- **验证**：`tests.test_knowledge_handler` 15/15；全量 `unittest discover -s tests` → **761 项通过**；并用真实 `KnowledgeService` 冒烟（3 个查询 `OK` / 1 个 `NO_MATCH`，最大结果 2165 B）。

### Step 5：Registry 注册与依赖注入 —— **已实施 2026-10-09**

对照记录 → [`STEP5_KNOWLEDGE_REGISTRATION_BEFORE_AFTER.md`](STEP5_KNOWLEDGE_REGISTRATION_BEFORE_AFTER.md)

- **改动**：
  - `tools/registry.py`：新增名称常量 `SEARCH_FISHERY_KNOWLEDGE`、`KNOWLEDGE_DESCRIPTION`、`KNOWLEDGE_PARAMETERS`；`__init__` 增加 `knowledge: KnowledgeService | None = None`；**仅在注入服务时**绑定该 entry（含 `validate_arguments`）。
  - `tools/handlers/knowledge_search.py`：新增 `validate_arguments()` 与 `MAX_QUERY_CHARS = 512`（正式 validator 落地）。
- **决策（原待定项）**：**不拒绝组合、也不制造假状态**——未注入服务时该名称**不被这个实例暴露**；`lookup()` 与 `model_definitions()` 始终一致。
- **语义细化（重要）**：`registered_names()` 现在是**全部已知名称的固定 allowlist**（Policy 默认文件 + Trace/公开输出白名单），**不等于**单个实例的绑定集合。`ADDING_A_TOOL.md` 的"三者一致"表述已同步修正。
- **授权仍然关闭**：包内默认 Policy 未变（Assistant 只授权水质查询）；Catalog 仍只有两条 → 用户 override 选择 Knowledge 会被 `TOOL_NOT_EXECUTABLE` 拒绝（**注册存在 ≠ 已授权**）。
- **验证**：新增 `tests/test_knowledge_registration.py`（17 项）；全量 `unittest discover -s tests` → **796 项通过**；`node --test tests/test_browser_streaming.cjs` → **183 项通过**。
- **改了 4 行既有断言**：`test_tool_policy.py` ×2、`test_tool_policy_manager.py` ×2 —— 它们快照了 `registered_names()` 的内容，而"更新 `registered_names()`"本就是本步的既定动作（加第三项 + 一句注释说明 allowlist 与绑定集合的区别）。

### Step 6：Catalog 展示 —— **已实施 2026-10-09**

对照记录 → [`STEP6_CATALOG_BEFORE_AFTER.md`](STEP6_CATALOG_BEFORE_AFTER.md)

- **改** `tools/catalog.py`：新增第三条 `search_fishery_knowledge`；`parameter_summary` = `"query: string（必填，1–512 字符）"`（不再用无参默认值）。**`tool_catalog()` 一行未改**（含硬编码的 `"modes"`），刻意不引入按工具分支。
- **决定**：`experimental=False`。该字段在 UI 里被渲染成固定句子 `EXPERIMENTAL / NOT PROFESSIONAL STANDARD`，属**评分口径**声明；知识检索不做评分，套用即错标。真实风险（基线未评测、无逐条出处）写进 `detailed_description`。
- **实测发现**：`item["modes"]` **当前没有任何消费者**（`policy.py` 只读 `executable`；`app.js` 的"适用模式"是前端写死的字符串）→ 本步"不动 `modes`"语义安全。详见报告 §2.2。
- **授权仍然关闭**：包内默认 Policy 未变；未注入 `KnowledgeService` 的实例上该行**禁用**（`!registered`）；注入后用户**可以** override 勾选（测试已锁）。
- **验证**：新增 `tests/test_catalog_knowledge.py`（10 项）；全量 **806 项通过**（796 → +10）；浏览器 **183 项通过**。
- **改了 3 处既有断言**：`test_tool_policy_manager.py` ×3 行（`len(catalog)==2` → 名称列表）与 `test_knowledge_registration.py` 中 **2 个描述 Step 5 临时状态的测试**（被本步合法推翻）。
- **本步暴露的既有 UI 缺陷（未修，登记待 Step 10）**：**U1** 徽章 `app.js:2563` 忽略 `registered/executable`，对未注册的非 dev_only 行会谎报 "Registered / Executable"（该分支此前从未被执行过）；**U2** 详情区"适用模式"与后端 `item["modes"]` 是两份互不相干的来源。

### Step 7：Policy 默认 —— **已验证完成 2026-10-09（无产品代码改动）**

对照记录 → [`STEP7_POLICY_DEFAULTS_BEFORE_AFTER.md`](STEP7_POLICY_DEFAULTS_BEFORE_AFTER.md)

> **范围**：只决定**包内默认授权**与**旧 override 的兼容方式**。**不做**服务端"仅 Assistant"硬边界 —— 该议题按用户决定**暂缓**，列为后续独立架构议题，本轮**不得**因此扩展 `policy.py` / mode 权限模型。

| # | 设计点 | 结论 |
| --- | --- | --- |
| 1 | 包内默认是否授权 Knowledge | **否，两个模式都不授权**（实测确认）；"注册存在 ≠ 已授权"继续成立 |
| 2 | 是否新增错误码 | **否**。现有 `UNKNOWN_POLICY_TOOL` / `TOOL_NOT_EXECUTABLE` 足够 |
| 3 | 旧用户 override 怎么办 | **不得静默改写**。实测：`load()` 原样返回，文件字节与 mtime 不变；无任何 schema 迁移路径 |
| 4 | `modes` 归谁 | 仍是 `tools/catalog.py` 那行硬编码，**单一权威来源** |
| 5 | Analysis 能不能选 Knowledge | 本步不表态（无服务端限制），默认不勾选 |
| 6 | 测试 | **已补 2 条**：文件指纹不变、绑定新工具不改变已有 override 的 `exposed_tools` |

**结论：Step 7 无需修改任何产品代码。** 4 条要求（Analysis/Assistant 默认不新增、旧 override 不迁移、新注册工具不自动进入 `exposed_tools`）均已由现有设计结构性满足，证据见对照记录 §1–§2。

**本步暴露的运维后果（登记）**：已保存含 Knowledge 的 override 后，**任何未绑定 Knowledge 的实例启动即失败**（`UNKNOWN_POLICY_TOOL`），且文件完好无损（fail closed）。这是 Step 8 必须核对全部 `ToolRegistry(...)` 构造入口的具体理由。

### Step 8：装配 —— **已实施 2026-10-09**

对照记录 → [`STEP8_KNOWLEDGE_ASSEMBLY_BEFORE_AFTER.md`](STEP8_KNOWLEDGE_ASSEMBLY_BEFORE_AFTER.md)

- **改** `web.py` **一行**：`ToolRegistry(current_reader, diagnosis)` → `ToolRegistry(current_reader, diagnosis, knowledge=knowledge)`（+3 行注释）。净改动 `4 insertions(+), 1 deletion(-)`。
- **不新建服务**：复用 `web.py:228` 已有的唯一 `KnowledgeService`（它同时服务 Analysis 路径与只读 Tool）。实测 `create_app()` 期间只构造 **1** 次；已绑定 handler 持有的就是该对象（`is`）。
- **顺序是承载语义的**：`knowledge`(228) → `registry`(238) → `store`(243)。store 构造时用 `executable` 集合校验已存 override，若先建 store 再绑定，已保存过 Knowledge 选择的实例会启动即失败（Step 7 实测 `UNKNOWN_POLICY_TOOL`）。已写进注释并由测试锁定。
- **本步唯一可见变化**：真实应用的 Knowledge 行从 `executable=False` 变为 **`executable=True`** → 用户**可以勾选**；**包内默认 Policy 仍未变**（不授权）。
- **明确不做**：不动 `composition.py`（离线 demo 无 registry、永不走 Tool 路径）、`real_validation.py`（维护者专用独立进程）、qualification（复用 web registry，但 policy 是硬编码单工具）、任何无关测试 registry。
- **验证**：新增 `tests/test_knowledge_assembly.py`（7 项）；全量 **815 项通过**（808 → +7）；浏览器 **183 项通过**；**既有测试改动 0 处**。
- **空过检查**：临时移除 `knowledge=knowledge` 重跑 → 3 failures + 2 errors（只落在依赖绑定的用例），已还原并复核。
- **`functools.partial` 依赖边界**：全仓库只保留 **1 条**身份断言（`handler.keywords["service"] is <唯一实例>`），不再扩大到 partial 的其他形状。
- **⚠️ 阻塞项 D1b**：本步后 Knowledge 已在真实 Runtime 中 **executable**，但 `MockToolGateway` Request #1 的 `request.tools[0]` fallback **必须在 Mock Knowledge 的人工使用/验收之前解决**。

### Step 9：Assistant 选择规则（提示词层，不做硬路由）

- **改** `assistant.py::AssistantContextBuilder.build()`：补"何时值得检索项目资料"的说明。
- **不改**：仍然**不预注入** Snapshot / Diagnosis / RAG；模型自己决定是否调用。
- **接受**：模型可能不调用，或该调用时没调用 —— 提示词不保证行为，需人工验收。

### Step 10：UI 文案与安全渲染

- **改** `resources/web/app.js`：
  - `safeAssistantActivity()` 的名称 / 状态白名单；
  - `renderAssistantMessages()` 目前**对所有已调用 Tool 都显示"本轮已查询当前水质"** → 必须区分知识检索，不能误标成实时数据。
- **不改**：安全文本渲染方式。

### Step 11：离线测试 + 人工验收

按 Walkthrough §10 的表补齐（Contract / Handler / Registry / Policy / Executor / Assistant / UI / Security 回归），再走 §11 的人工验收清单。**真实模型请求须另行授权**，Mock 通过不等于真实资格。

---

## 2. 已确认的决定（2026-10-08）

| # | 决定 | 对计划的影响 |
| --- | --- | --- |
| 1 | **RAG baseline 暂缓**，不作为 Knowledge Tool 的前置步骤；留作 future / research | Step 1 移出主路径；本轮不改 RAG、不建评测集 |
| 2 | **新增 `NO_MATCH`**（同意），但实施前先核对全部消费者与测试 | **已实施 2026-10-09**；消费者清单已产出并分类，见 §4 |
| 3 | **不做服务端"仅 Assistant"硬边界**；`modes` 保持**单一权威来源**（`tools/catalog.py`）；Analysis 将来也可能开放 Knowledge，协调延后；现在只在 UI 默认**不勾选** | Step 7 降级为"不改 Policy 语义"；Step 6 不得新增第二份 modes 定义；默认 `tool_policies.json` 不含 Knowledge |
| 4 | `top_k` **暂定 3**；每段/总量上限在实测后定 | **已实施**：`top_k=3` 写死；单条 **800 字符**（不是字节）；**不做** Handler 侧总量裁剪（见 §4 K2） |

### 2.1 结果预算实测（2026-10-08，portable 后端，31 块）

| 指标 | 实测值 |
| --- | --- |
| chunk 字符数 | min 35 / 中位 142 / 均值 150.8 / **max 415** |
| chunk UTF-8 字节 | min 81 / 中位 262 / 均值 319.7 / **max 844** |
| 超过 800 字符的块 | **0 个** |
| 超过 400 字符的块 | 1 个（`relationships`：415 字符 = 844 字节） |

候选结果 JSON 大小（含 `id/category/source/source_version/text`，不含 raw score）：

| 查询 | 命中（top-3） | 结果 JSON |
| --- | --- | --- |
| 溶氧偏低怎么办 | relationships, wq_dissolved_oxygen, wq_temperature | 2219 B |
| 鳗鱼缺氧有什么表现 | problem_high_mortality, relationships, wq_dissolved_oxygen | 2108 B |
| 投喂率怎么定 | feeding_principles, feeding_freq, feeding_rate | 1066 B |
| 车轮虫病有哪些症状 | disease_车轮虫病, disease_气泡病, disease_赤鳍病 | 1983 B |
| pH 偏低如何调节 | wq_ph, relationships, wq_dissolved_oxygen | 2229 B |
| **最坏情况**（取最长的 3 块） | — | **2387 B** |

**建议**

1. **每段上限写成"800 字符"，不是字节。** 当前**永不触发**（最长 415 字符）。若误按字节，`relationships`（844 B）会被截断，而它恰是水质类问题的 Top-1 命中，伤害最大。
2. **总量上限保留 8 KiB，但它是兜底护栏而非当前约束**：top-3 最坏仅 2.4 KiB；真正生效的上限是 Executor 的 `max_result_bytes=32768`。8 KiB 的意义是"将来块数变多或 top_k 被调大时先撞到它"。
3. **Handler 必须主动裁剪，不要让结果撞上 `TOOL_RESULT_TOO_LARGE`**：后者会被 Executor 转成 `ERROR`，用户看到"工具失败"；而"知识偏多、只给前 3 条"应是正常 `OK` 状态。
4. **截断只作用于 `text`**；`id / category / source / source_version` 必须完整保留；截断处加标记（如 `…`）；不得产生损坏 JSON。
5. **结果不带 raw score**（研究文档建议）：JSON 更小，也避免分数被当概率。
6. 参数侧预算安全：512 个中文字符 = **1536 bytes** < Executor 的 4096 bytes 参数上限。

## 3. Step 2 设计稿与实施结果：受控参数合同（**已实施**）

### 3.1 现状（已核实）

- `tools/contracts.py`：`ToolDefinition(model_definition, handler: Callable[[], dict])` —— Handler **无参数**。
- `tools/executor.py`：解析 `arguments_json` 后**写死** `if not isinstance(arguments, dict) or arguments: raise ToolError(INVALID_TOOL_ARGUMENTS)`。
- `tools/registry.py`：依赖用 `partial(handler, reader=..., diagnosis=...)` 在**构造期**注入，与模型输入无关。
- 模型给的 `ModelToolCall.arguments_json` 是**不可信输入**（`__post_init__` 只校验它是个 JSON object）。

### 3.2 目标与非目标

- **目标**：让"带参数的只读工具"能被安全执行，且**旧两个工具行为一字不变**。
- **非目标**：不做通用 JSON Schema 引擎、不做反射或动态 import、不加第二套 Executor、不放开非空参数给旧工具。

### 3.3 要定下来的三件事

1. **声明放哪**：`ToolDefinition` 增加一个参数校验入口（形如 `validate_arguments: Callable[[dict], dict]`，返回**归一化后**的参数）。绑定点在 Registry（静态声明），不从配置加载。
2. **校验放哪**：仍然**只在 `ToolExecutor.execute()` 一处**。Executor 负责 UTF-8 字节上限 → JSON object → 交给 `validate_arguments` → 失败即 `INVALID_TOOL_ARGUMENTS`。
3. **传给 Handler 什么**：声明了参数 → `handler(validated_arguments)`（已归一化的单个 dict）；未声明参数 → 仍是 `handler()`。**实施时改为"两种形状并存"**，没有统一传参 —— 原因见 §3.7。

### 3.4 兼容与迁移

- 旧工具：校验器只允许空 dict；调用形状由包装保持 → `tests/test_read_only_tools.py` 现有断言必须**一字不改地通过**。
- 新工具：Handler 只收到**声明过的键**、已归一化的 dict。

### 3.5 验证（已实施）

新增 `tests/test_tool_argument_contract.py`：① 带参数工具能收到已校验参数；② 旧工具仍拒绝 `{"query":"x"}`；③ 参数超 4096 bytes 在校验**之前**被拒；④ 校验器抛 `ValueError` → `INVALID_TOOL_ARGUMENTS`，抛其它异常 → 安全 `TOOL_EXECUTION_ERROR`，两者都不外泄 traceback 且都不执行 Handler；⑤ 未声明字段被拒（由校验器决定）。

回归：全量 `unittest discover -s tests` → **736 项通过**。

### 3.6 风险

- 改 `ToolDefinition` 会触及所有构造点（Registry 及测试）→ 需一次性核对完整。**已核对：现有测试零改动通过。**
- 若把 `handler(arguments)` 改成必填参数，旧 Handler 签名会破 → **该风险已发生，改用"两种形状并存"规避**（见 §3.7）。

### 3.7 实施后的补充说明

- 枚举值域被**放宽**：以前 Handler 返回 `{"status":"NO_MATCH"}` 会被兜成 `TOOL_EXECUTION_ERROR`；Step 3 之后会被当成合法状态。这是有意为之，且目前没有 Handler 返回该值。
- `handler` 的类型注解由 `Callable[[], dict]` 放宽为 `Callable[..., dict]`，但**运行时形状不变**。
- 本次踩坑：测试辅助方法命名为 `run` 会覆盖 `unittest.TestCase.run`，导致 `setUp` 不执行。详见对照记录 §6。

## 4. 后续依赖登记（**本轮不改**，2026-10-09 分类）

Step 3 的消费者搜索发现三处"现在改是错的、但将来必须改"的位置。按用户决定分类登记：

| 编号 | 位置 | 分类 | 说明 |
| --- | --- | --- | --- |
| **D1** | `tool_conversation.py` 的 `MockToolGateway` **按 payload 键猜形状**（`status` + `scoring_version` 启发式） | **已解决 2026-10-09** | 改为**按 tool name 分派**；未知/畸形结果返回安全兜底 `离线 Mock：该 Tool 尚无离线渲染。`；工具名通过 **`tool_call_id` 关联**取得（不再假设 `tool_calls[0]`）。见 [`D1_MOCK_TOOL_GATEWAY_BEFORE_AFTER.md`](D1_MOCK_TOOL_GATEWAY_BEFORE_AFTER.md) |
| **D1b** | `tool_conversation.py` MockToolGateway **Request #1** 的 `request.tools[0]` fallback | **BLOCKER BEFORE MOCK KNOWLEDGE ENABLEMENT**（**Step 11 前置**） | 若策略只授权 Knowledge，问"现在…"会 fallback 到 Knowledge 并以 `"{}"` 调用 → 被 validator 拒（`INVALID_TOOL_ARGUMENTS`）。**Step 8 后 Knowledge 已在真实 Runtime 中 executable、用户可勾选**，因此本项已成为人工/ Mock 验收的硬前置。改它会变动现有行为（"只授权水质工具时问评分问题"走 `tools[0]`），需单独评审 |
| **D2** | `application.py:47-49` `snapshot_comparison` | 当前不改 | NO_MATCH 会被判成 `not_called`。Knowledge Tool 仍是 **Assistant-only**；只有未来真的允许 Analysis 使用时才重新评审。 |
| **D3** | `app.js:2759` 工具名白名单、`:2794` 硬编码文案"本轮已查询当前水质" | 当前不改，**Step 10 必须处理** | 否则 Knowledge 调用会被置 `null` / 误标成水质查询。 |
| **B6** | `web.py:1127` 的 `"arguments"` 字段（`!= "ERROR"` 时写 `{}`） | 移入「**参数型 Knowledge Tool 接入前依赖**」 | 这是"带参数工具"带来的既有不精确，**不是 NO_MATCH 本身的问题**，本步不顺便修改；接入带参工具前必须重新评审该字段。 |
| **K1** | `retrieval_version`（Step 4 新增登记） | 当前不提供 | `KnowledgeService` 目前没有稳定检索版本 metadata（只有 `source_version` = 知识资源版本）。理想形态是 Service 自己提供 `retrieval_mode` + `retrieval_version` + 参数指纹，Handler 纯透传。**等 RAG 研究重启时再做**，不为此扩大 Step 4 范围。 |
| **K2** | Handler 侧总预算（Step 4 新增登记） | 当前不做 | 第一版预算 = `top_k=3` + 单条 800 字符 + Executor 32768 B。**若将来引入更小的总量预算，必须显式标识裁剪**（`PARTIAL` 或 `truncated: true`），不得静默丢条后仍报完整 `OK`。 |

## 5. 本方案的自我约束

- 不复制 TF-IDF、不建第二份索引、不搬走 Analysis 的 RAG。
- 不把 Knowledge 检索接进 Analysis（Analysis 已有自动 RAG，重复检索只会占用单 Tool 预算）。
- 不引入 Agent、多 Tool 并行、第三轮请求、Streaming Tool Calling。
- 不改 `model_gateway.py` 的通用 Tool 协议，不为这个工具写 Provider 分支。
- 真实请求 / Preset 发布 / Managed Evidence 均不在本方案内。

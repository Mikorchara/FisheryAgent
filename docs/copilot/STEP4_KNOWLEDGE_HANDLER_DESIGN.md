# Step 4 设计登记：薄 Knowledge Handler

**状态：已实施 2026-10-09。** Handler 已落地并通过测试；**Registry 注册仍未开始**，因此 Knowledge Tool 作为"模型可调用的工具"仍是 **PAUSED / NOT IMPLEMENTED**。实施记录见 [`STEP4_KNOWLEDGE_HANDLER_BEFORE_AFTER.md`](STEP4_KNOWLEDGE_HANDLER_BEFORE_AFTER.md)。

上游依据：[`KNOWLEDGE_TOOL_STEP_BY_STEP.md`](KNOWLEDGE_TOOL_STEP_BY_STEP.md) Step 4、[`../handoff/KNOWLEDGE_TOOL_V1_WALKTHROUGH.md`](../handoff/KNOWLEDGE_TOOL_V1_WALKTHROUGH.md) §4、[`../deep-dive/tools/ADDING_A_TOOL.md`](../deep-dive/tools/ADDING_A_TOOL.md) §3–4。

**前置已就绪**：受控参数合同（Step 2）与 `ToolStatus.NO_MATCH`（Step 3）均已实施。

**本文件不含**：Registry 注册（Step 5）、Catalog（Step 6）、Policy 默认（Step 7）、装配（Step 8）、Assistant 提示词（Step 9）、UI 文案（Step 10）。

---

## 0. 实施前调整（2026-10-09，用户确认）

### 0.1 版本信息不再由 Handler 组装

- **不做**：在 Handler 里硬编码/拼接 `portable-charwb-2-4/eel-knowledge-1.0`。
- **核对结果（实测）**：`KnowledgeService.backend` 是 **effective backend**，不是 requested。实测请求 `backend="sklearn"` 而环境无 sklearn 时，构造期把它**就地改写成 `'keyword'`**，且 `_index is None`（走关键词回退路径）。所以 `service.backend` 可以安全地作为 `retrieval_mode` **透传**给模型。
- **`retrieval_version`**：当前 `KnowledgeService` **没有**稳定版本 metadata、也没有 `retrieval_version` 属性（仅 `source_version = "1.0"`，那是知识资源版本，不是检索算法版本）。**因此 Step 4 不提供该字段**，不为此扩大本步范围。
- **登记为后续项**：理想的长期形态是 `KnowledgeService` 自己提供一个检索 metadata（例如 `retrieval_mode` + `retrieval_version` + 参数指纹），Handler 纯透传。这属于 RAG 侧工作，等 RAG 研究重启时再做。

### 0.2 测试边界：Step 4 只测 Handler

Handler 假定**收到的 `arguments` 已经校验完成**。以下全部移到 **Step 5（Registry / validator）**：

- `query` 缺失 / 类型错误 / 空串 / 超 512 字符
- 额外字段（`top_k`、`backend`、`path` …）
- 控制字符与孤立代理项
- 归一化规则（strip 策略）
- `Executor → validator → Handler` 端到端

理由：正式 validator 本来就是 Step 5 才创建；Step 4 测它等于测不存在的东西。

### 0.3 不做"静默丢尾条"

**放弃**原设计里"总量超 8 KiB 就丢尾条但仍返回 OK"的逻辑。第一版预算就是：

```text
top_k = 3  +  单条 evidence 字符上限（800 字符）  +  Executor 已有的 32768 bytes 总上限
```

**硬规则（写在这里以免以后走偏）**：若将来确实需要更小的 Handler 侧总预算，**必须显式表达结果被裁剪**（例如 `PARTIAL`，或 `truncated: true`），**不得静默删除证据后仍表现为完整 `OK`**。

### 0.4 其余已确认项

| 项 | 决定 |
| --- | --- |
| 截断标记 | 加 `…` |
| `retrieved_at` | 不进入模型 payload |
| `retrieval_mode` | 用**真实 effective** `service.backend` |
| 控制字符 / 孤立代理项 | 拒绝（由 Step 5 validator 实现） |
| `MAX_TEXT_CHARS` 单位 | **字符**（写进常量名与注释，防被误改成字节） |
| `source`（`legacy:eel_knowledge.json`） | **可以给模型** —— 它是逻辑来源标识 |
| 真正禁止暴露 | **本机 filesystem path**（驱动器、绝对路径、`.venv`/`site-packages` 等） |

---

## 1. 新增文件与签名

新增一个文件，放在已有 Handler 同目录：

```text
src/fishery_ai/tools/handlers/knowledge_search.py
```

设计草案：

```python
"""Read-only project knowledge search; no model, no I/O, no second index."""

from ...contracts import utcnow
from ...knowledge import KnowledgeService

TOP_K = 3                 # fixed server-side budget; never a model parameter
MAX_TEXT_CHARS = 800      # per evidence text, in CHARACTERS (not bytes)
MAX_RESULT_BYTES = 8192   # Handler-side total guard; truncates, never errors

def search_fishery_knowledge(arguments: dict, *, service: KnowledgeService) -> dict:
    ...
```

为什么要独立文件：Handler 是"薄映射"层，和 `current_water_quality.py` / `water_quality_score.py` 并列；不塞进 `registry.py`（那里只做静态定义与绑定）。

---

## 2. Handler 接收什么

三层来源，**只有第一层来自模型**：

| 来源 | 内容 | 谁提供 | 时机 |
| --- | --- | --- | --- |
| ① 参数 | `arguments`（**已归一化**的 dict） | 模型写 JSON → Executor 校验/归一化 → 传进来 | 每次调用 |
| ② 依赖 | `service=KnowledgeService` | 组合层在构造 Registry 时注入（Step 5） | 构造期一次 |
| ③ 常量 | `TOP_K = 3`、`MAX_TEXT_CHARS`、`MAX_RESULT_BYTES` | 本文件 | 写死 |

调用形状由 Step 2 的合同决定：**声明了 `validate_arguments` 的工具，Handler 收到一个位置参数**（已归一化的 dict）。依赖用关键字注入，与现有两个 Handler 一致。

**模型能影响的只有 ① 里的 `query` 字符串**。它**不能**影响：检索条数、backend、阈值、资源路径、超时、重试。

---

## 3. `validated_arguments` 精确形状

归一化后**有且只有一个键**：

```python
{"query": "<已 strip 的查询文本>"}
```

校验器（Step 5 与 Registry 一起声明）必须保证：

| 规则 | 值 | 不满足时 |
| --- | --- | --- |
| 键集合 | 必须**恰好** `{"query"}` | 拒绝（未声明字段一律不接受） |
| 类型 | `str` | 拒绝 |
| 非空 | `strip()` 后非空 | 拒绝 |
| 字符数 | ≤ **512** 字符 | 拒绝 |
| 字节数 | 由 Executor 先保证 ≤ 4096 bytes（实测 512 个中文字符 = 1536 bytes） | 拒绝 |
| 控制字符 | 拒绝 C0/C1 控制字符 | 拒绝 |
| Unicode | 拒绝孤立代理项（`json.loads` 可产出，重新编码会炸） | 拒绝 |
| 归一化 | 返回 `{"query": stripped}`（**只 strip**，不折叠内部空白、不改大小写） | — |

**明确不接受**：`top_k`、`backend`、`threshold`、`category`、`path`、`url`、`file`、`module`、`limit`、`offset`。

拒绝的方式：校验器 `raise`，Executor 统一映射为 `INVALID_TOOL_ARGUMENTS`（Step 2 已实现），**Handler 根本不会被调用**。

---

## 4. 它如何调用 `KnowledgeService.search()`

```python
evidence = service.search(arguments["query"], top_k=TOP_K, retrieved_at=utcnow())
```

决定与理由：

| 决定 | 理由 |
| --- | --- |
| `query` 只传**用户查询本身** | Tool 场景里"检索文本"和"用户意图"是同一句话，不像 Analysis 需要把规则代码拼进 query |
| **不传** `intent_text` | 该参数用于把"拼接查询"与"原始问题"分开；这里没有拼接，默认即正确 |
| `top_k = TOP_K`（=3，写死） | 模型不能调；也不能被后续步骤改成从参数读 |
| `retrieved_at` 传当前时间 | 与 Analysis 的用法一致；但**不进入 payload**（见第 8 节） |
| **只调用一次** | 不做 query rewrite、不重试、不多跳；多跳会撞上"1 call / 1 round / 2 requests"预算 |
| 不 `except` 内部异常 | 见第 6 节：服务异常必须**向上传播**，由 Executor 变成安全错误 |

---

## 5. `KnowledgeEvidence` → Tool payload 映射

| `KnowledgeEvidence` 字段 | payload 字段 | 处理 |
| --- | --- | --- |
| `evidence_id` | `id` | 原样（稳定块 ID，如 `wq_dissolved_oxygen`） |
| `category` | `category` | 原样 |
| `source_id` | `source` | 原样（`legacy:eel_knowledge.json`） |
| `source_version` | `source_version` | 原样（`1.0`） |
| `text` | `text` | 截断到 `MAX_TEXT_CHARS` 字符，截断处加 `…` |
| `score` | — | **不发送**：不是概率，三种 backend 之间不可比 |
| `source_title` | — | **不发送**：当前为 `None`，禁止编造出处 |
| `retrieved_at` | — | **不发送**：静态知识，对模型无信息量 |

外层包装：

```json
{
  "status": "OK",
  "retrieval_mode": "portable",
  "result_count": 3,
  "evidence": [
    {"id": "wq_dissolved_oxygen", "category": "water_quality",
     "source": "legacy:eel_knowledge.json", "source_version": "1.0",
     "text": "水质参数 dissolved_oxygen：适宜范围 5-8 mg/L。……"}
  ]
}
```

- `retrieval_mode` = **`service.backend` 直接透传**（effective backend，见 §0.1）。Handler **不拼接、不推断、不硬编码** —— 分数尺度因 backend 而异，必须让回答能声明依据哪一套。
- **不提供 `retrieval_version`**（见 §0.1：Service 目前没有稳定版本 metadata；不为此扩大本步范围）。
- `source_version` 来自 `KnowledgeEvidence.source_version`（知识资源版本 `1.0`）—— 证据字段直传，不是 Handler 组装。
- payload 的键集合是固定的四个外层键 + 五个证据键，多一个少一个都算合同破坏（测试锁定）。

---

## 6. OK 与 NO_MATCH 分别返回什么

| 情况 | `search()` 返回 | Handler 返回 |
| --- | --- | --- |
| 有合格命中（通过 0.04 门槛） | 非空 tuple | `{"status": "OK", "result_count": N, "evidence": [...], ...}` |
| **没有任何合格命中** | **空 tuple** | `{"status": "NO_MATCH", "result_count": 0, "evidence": [], "retrieval_mode": ..., "retrieval_version": ...}` |
| 服务内部异常 | 抛异常 | **不捕获、不转换** → 由 Executor 变成安全 `TOOL_EXECUTION_ERROR` |

三条硬规则：

1. **两种业务结果都是正常返回**，都不抛异常。
2. **`NO_MATCH` 不是错误**：它的 `error_code is None`，会继续第二轮让模型解释"资料里没有"（Step 3 已实现）。
3. **"没查到" 与 "检索坏了" 必须区分**：把服务异常吞成 `NO_MATCH` 会骗用户"资料里没有"，这比报错更糟。资源损坏不是"没有命中"。

---

## 7. 哪些字段应该给模型

- `status` —— 让模型能区分"没查到"和"查到了"
- `retrieval_mode` + `retrieval_version` —— 让回答能声明依据的检索版本
- `result_count` —— 与 `evidence` 长度一致，便于模型自查
- 每条证据：`id`、`category`、`source`、`source_version`、`text`

## 8. 哪些字段不应该暴露

| 不暴露 | 理由 |
| --- | --- |
| `score` | 不是概率、不是置信度、跨 backend 不可比；给了会被误用 |
| `source_title` | 当前为 `None`；**没有出处就不写出处** |
| `retrieved_at` | 31 块是静态知识，时间对模型无价值，只是多余字节 |
| 未通过门槛 / 超出 top_k 的候选 | 不给模型"还有别的候选"的错觉 |
| 资源路径、文件名、Trace 路径 | 路径泄漏 |
| 异常文本、traceback | 由 Executor 统一脱敏 |
| 原始 `arguments_json`、prompt、系统指令 | 不进结果也不进 Trace |
| `top_k` / `backend` / `threshold` 参数 | 从不接受，也就无从暴露 |

---

## 9. 如何限制结果大小（两层 + Executor 兜底）

| 层 | 限制 | 行为 |
| --- | --- | --- |
| ① 条数 | `top_k = 3` | 模型无法覆盖 |
| ② 单段 | `MAX_TEXT_CHARS = 800` **字符** | 截断 `text` + 加 `…`；`id/category/source/source_version` **完整保留** |
| 兜底 | Executor `max_result_bytes = 32768` | 已存在；正常路径远不会撞上 |

**不做 Handler 侧总量裁剪**（见 §0.3）：第一版没有 8 KiB 逻辑，也不静默丢条。

关键取舍：

- **800 必须是"字符"不是"字节"**。实测最长 chunk 是 `relationships`：**415 字符 = 844 字节**，而它恰是水质类问题的 Top-1 命中；按字节会刚好把它切断。
- **将来若要更小的总预算，必须显式标识裁剪**（`PARTIAL` 或 `truncated: true`），不能让模型以为读到了完整证据集。
- 裁剪**不得产生损坏 JSON**：始终由 `json.dumps` 生成。
- 截断只作用于 `text`：来源标识必须完整，否则模型无法引用。

---

## 10. Handler 为什么不能自己实现 RAG

| # | 理由 |
| --- | --- |
| 1 | **单一索引**：`KnowledgeService` 由组合层构造一次并共享（`web.py` 已有实例）。自建索引 = 第二份 2000 特征向量表，内存翻倍 |
| 2 | **两份真相**：Analysis 的自动 RAG 与 Tool 检索会变成两套逻辑，同一个问题在报告里和聊天里给出不同依据 |
| 3 | **不变量会被复制**：`EXPANSIONS`、`_intent/_adjust_score`、0.04 门槛、稳定 `evidence_id` 都只在 `KnowledgeService` 维护 |
| 4 | **职责错位**：Handler 的定位是"受控输入 → 服务调用 → 有限 dict"；一旦开始做检索算法，Policy / Executor / 测试的边界就模糊了 |
| 5 | **可测性**：注入 fake service 才能断言"调了几次、top_k 是多少"；自己实现检索就无法用替身验证 |

配套规则：**Handler 也不负责 Tool loop、模型调用、UI、诊断、评分、动态选择资源。**

---

## 11. 计划怎么单元测试（只测 Handler）

新文件：`tests/test_knowledge_handler.py`（离线；沿用仓库惯例封锁 `socket.*`）。

**边界（见 §0.2）**：Handler 假定 `arguments` 已经校验完成。**不测**校验器、不测 Executor 端到端 —— 那些属于 Step 5。

用 **fake `KnowledgeService`**（记录调用、返回构造好的 `KnowledgeEvidence`，并提供 `backend` 属性）：

| # | 用例 | 断言 |
| --- | --- | --- |
| 1 | 调用契约 | `search` 恰好被调用 **1 次**；`query` 等于传入的字符串 |
| 2 | 固定预算 | `top_k` 恒为 **3**，即使 arguments 里塞了 `top_k=9` 也不改变（Handler 不读额外字段） |
| 3 | 字段映射 | `id/category/source/source_version/text` 映射正确；`result_count == len(evidence)` |
| 4 | 键集合固定 | 外层恰好 `{status, retrieval_mode, result_count, evidence}`；证据恰好 5 个键 |
| 5 | 空结果 | `search` 返回空 tuple → `status == "NO_MATCH"`、`result_count == 0`、`evidence == []` |
| 6 | 异常传播 | fake service 抛异常 → **原样向上传播**，**不被**吞成 `NO_MATCH` |
| 7 | 文本截断 | 1000 字符文本 → 800 字符 + `…`；`id/source` 完整；未超限时**不加**标记 |
| 8 | 不暴露 | 无 `score` / `retrieved_at` / `source_title` / `retrieval_version`；无驱动器号、绝对路径、`.venv`、`site-packages` |
| 9 | 合同可接受 | payload 经 `ToolExecutionResult.from_payload()` 成功，`error_code is None`，status 属合法枚举 |
| 10 | effective backend | `backend="keyword"` / `"sklearn"` 的 fake → `retrieval_mode` 对应透传 |
| 11 | 不可信内容 | 含"忽略以上指令"的 chunk 文本只是**数据**：原样出现在 `text`，payload 结构不变 |

**不改动任何既有测试文件。**

---

## 12. 开放问题的最终决定（2026-10-09）

| # | 问题 | 决定 |
| --- | --- | --- |
| 1 | 截断处是否加 `…` | **加** |
| 2 | 超总预算时丢尾条 vs 报错 | **两者都不做**：第一版没有 Handler 侧总量逻辑（§0.3）；将来要加必须显式标识裁剪 |
| 3 | 结果里是否放 `retrieved_at` | **不放** |
| 4 | `retrieval_mode` 用真实 effective `service.backend` | **是**（已实测确认 `backend` 是 effective，§0.1） |
| 5 | 控制字符 / 孤立代理项 | **拒绝**（Step 5 validator 实现） |
| 6 | `MAX_TEXT_CHARS` 单位 | **字符**（写进常量名与注释） |
| 7 | `retrieval_version` | **本步不提供**；等 Service 自己给 metadata（§0.1） |
| 8 | `source` 是否可给模型 | **可以**（逻辑来源标识）；禁止的是本机 filesystem path |

## 13. 明确不在本步做

- 不新增 Registry 定义或绑定（Step 5）
- 不新增 Catalog 条目（Step 6）
- 不改 Policy 默认（Step 7）；Knowledge 仍不被默认授权
- 不改 `web.py` 装配（Step 8）
- 不改 Assistant 提示词（Step 9）
- 不改 UI 工具名白名单与文案（Step 10）
- 不解决 D1（`MockToolGateway`）；D1 仍是 **BLOCKER BEFORE KNOWLEDGE REGISTRATION**，最迟在 Step 5 之前解决

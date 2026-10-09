# D1b 对照记录：Mock 的方向性降级（before / after）

> 范围：**只改 `MockToolGateway.complete()` 的 Request #1 工具选择，外加两个模块级常量**。不改真实 Model Gateway、Registry、Policy、Knowledge Handler、Multi-Tool、Request #2 renderer。
> 验证：`unittest discover -s tests` → **821 项通过**（815 → +6）；`node --test tests/test_browser_streaming.cjs` → **183 项通过**。

---

## 1. 缺陷回顾（D1 时登记的 D1b）

Request #1 原本这样选工具：

| | |
| --- | --- |
| desired | `"score_current_water_quality"` if 问句含 `评分\|打分\|打.*分`，否则 `"get_current_water_quality"` |
| 选择 | `next((t for t in request.tools if t.name == desired), request.tools[0])` ← **位置性兜底** |

后果：策略只授权 Knowledge 时问「现在水质怎么样？」→ `desired` 不在 `request.tools` → 取 `tools[0]` = Knowledge → 以 `"{}"` 调用 → 缺必填 `query` → `ToolStatus.ERROR` → `run_request()` 在**构造 `follow_up` 之前** `raise GatewayError` → 整轮 `Status.FAILED`、`generated_text=""`、**Request #2 根本不发**。

即：不是"调错工具"的轻微降级，而是**整轮硬失败**。

## 2. 设计调整（按用户要求，非"同族任意替代"）

原提案是「可驱动集合 ∩ `request.tools` 非空就取第一个」。**该提案被否决，理由成立**：它仍可能产生**无方向的同族替代**——用户问当前水质、只授权评分 Tool 时，mock 会用评分 Tool 顶替水质查询。

改为**显式方向性映射**：

```python
MOCK_DRIVABLE_TOOLS = (CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE)
FALLBACK_TOOLS = {WATER_QUALITY_SCORE: (CURRENT_WATER_QUALITY,), CURRENT_WATER_QUALITY: ()}
```

| desired | 允许的降级 | 禁止 |
| --- | --- | --- |
| `score_current_water_quality` | → `get_current_water_quality` | — |
| `get_current_water_quality` | **无（空元组）** | **→ `score_current_water_quality`** |
| 任何 | — | **Knowledge**（既不在可驱动集合，也不是任何工具的 fallback） |

## 3. before / after

### 3.1 常量（新增）

```python
UNAUTHORIZED_TOOL_TEXT = "离线 Mock：当前 Policy 未授权所需的水质 Tool，无法读取当前事实。"
MOCK_DRIVABLE_TOOLS = (CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE)
FALLBACK_TOOLS = {WATER_QUALITY_SCORE: (CURRENT_WATER_QUALITY,), CURRENT_WATER_QUALITY: ()}
```

### 3.2 选择逻辑

| | |
| --- | --- |
| **before** | `desired = "score_..." if … else "get_..."`（**字符串字面量**，不用常量）<br>`selected = next((t for t in request.tools if t.name == desired), request.tools[0])` |
| **after** | `desired = WATER_QUALITY_SCORE if … else CURRENT_WATER_QUALITY`（改用常量）<br>按**优先级顺序**遍历 `(desired, *FALLBACK_TOOLS[desired])`，逐个在 `request.tools` 里按名称查找；<br>都不存在 → `ModelResponse(UNAUTHORIZED_TOOL_TEXT, finish_reason="stop")`（**无 tool_calls、不抛异常**） |

**关键实现细节**：不能用"一次遍历 `request.tools`、条件写成 `name == desired or name in FALLBACK_TOOLS[desired]`"——那会**按 `request.tools` 的顺序**命中，等于把位置性 bug 换个写法。因此代码显式按 `desired` → 各 fallback 的**优先级顺序**查找，`desired` 永远先于它的 fallback。

## 4. 行为矩阵

| 场景 | before | after |
| --- | --- | --- |
| 默认策略（只授权水质查询）+「现在水质怎么样？」 | 调水质查询 | **不变** |
| 默认策略 +「当前水质评分多少？」 | 降级调水质查询 | **不变**（方向性映射显式保留） |
| 两水质工具都授权 + 评分问题 | 调评分工具 | **不变**（且与声明顺序无关） |
| 概念问题 | 无 tool_calls + 文本 | **不变** |
| 无任何工具 | 无 tool_calls +「当前 Policy 未允许…」 | **不变**（文案逐字未动） |
| Request #2（`tool_choice=="none"`） | 只渲染 | **不碰** |
| 水质/评分渲染文本 | 逐字节固定 | **不碰** |
| **只授权评分 Tool +「现在水质怎么样？」** | 错误调用评分 Tool | **无 tool_calls + 说明文本** |
| **只授权 Knowledge +「现在水质怎么样？」** | **整轮硬失败** `INVALID_TOOL_ARGUMENTS` | **`Status.COMPLETED` + 说明文本** |

**唯一的行为变化只发生在原本就会失败或语义错误的路径上。**

## 5. 新增测试（6 项）

| 文件 | 测试 | 证明什么 |
| --- | --- | --- |
| `test_mock_tool_gateway.py` | `test_current_question_never_degrades_to_the_score_tool` | **用户指定的回归**：当前水质问题 + 只授权评分 Tool → **不调用**评分 Tool，返回说明文本 |
| 同上 | `test_desired_tool_is_checked_before_its_fallback` | 声明顺序不决定结果：`tools=(水质, 评分)` + 评分问题 → 仍调**评分** |
| 同上 | `test_knowledge_is_never_chosen_or_borrowed` | 只授权 Knowledge 时，水质问题与评分问题都**不发调用** |
| 同上 | `test_knowledge_next_to_a_water_tool_is_still_ignored` | Knowledge 与水质工具并存时忽略 Knowledge |
| 同上 | `test_the_mock_never_emits_an_uncallable_tool_call` | **不变式**：遍历 4 个问题 × 8 种授权组合（含用**真实** `KNOWLEDGE_PARAMETERS` 构造的 Knowledge 定义），mock 产出的每个调用都必须落在 `MOCK_DRIVABLE_TOOLS` 内、且目标工具**无必填参数**、`arguments_json == "{}"` |
| `test_tool_conversation.py` | `test_mock_never_hard_fails_when_only_knowledge_is_authorized` | **端到端**：只授权 Knowledge +「现在水质怎么样？」→ `Status.COMPLETED`、`request_1.outcome == "final_answer"`、**`request_2.outcome == "not_started"`**、`tool_result/tool_name/tool_call_id` 全为 `None`、无 `error_code` |

同时更新了 `test_desired_tool_fallback_stays_unchanged` 的注释（原文写"D1 deliberately does not change this (registered as D1b)"）：D1b 已解决，该断言**本身未变**，语义由"位置兜底"变为"方向性降级"。

不变式测试里加了两条**防空过**断言：`set(FALLBACK_TOOLS) == set(MOCK_DRIVABLE_TOOLS)`（防止两者漂移）与 `KNOWLEDGE_PARAMETERS["required"] == ["query"]`（证明"不能调带参工具"这条约束真的被施加了）。

### 5.1 mutation check（实测）

把选择逻辑临时改回 `next((t for t in request.tools if t.name == desired), request.tools[0])` 后重跑两个模块 → **5 项失败**，其中包含端到端那条（`Status.FAILED != COMPLETED`，即 D1b 缺陷本身）。随后已还原，全量重跑 821 OK。

**诚实说明**：`test_desired_tool_is_checked_before_its_fallback` 在旧实现下**也是通过的**（旧代码里 `desired` 命中就返回，只有 `desired` 缺失时才走 `tools[0]`）。它防的是"用一次性条件过滤 `request.tools`"这种**新写法**引入的顺序错误，不是 D1b 本身的检测器。

## 6. 这些测试**不**证明什么

- 不证明 mock 会主动调用 Knowledge —— 它**不会**，这是本步刻意保留的边界（需要 Knowledge 离线渲染器与产品决策，属 Step 10/11）。
- 不证明真实模型会这样选工具：mock 是确定性 fixture，不是模型行为的证据。
- 不证明 UI 呈现：本步未加前端断言。
- 零真实模型请求、零网络（模块内 `setUp` patch `socket.*`）。

## 7. 明确未做的改动

真实 Model Gateway（`model_gateway.py`）、Registry（`registry.py`）、Policy（`policy.py`）、Knowledge Handler（`knowledge_search.py`）、Multi-Tool（`run_request` 的多调用限制）、Request #2 渲染路径（`_final_text` / `RENDERERS` / `tool_choice=="none"` 分支）**全部未动**。既有的"未知工具结果 → `UNRENDERED_TEXT`"三条测试仍在保护 mock 不越界。

## 8. 教训

1. **"从哪里取 fallback"和"能不能取 fallback"是两个问题。** 旧代码的错在于用**位置**（`tools[0]`）回答第二个问题；新代码用**显式映射**回答，并用空元组表达"没有 fallback"。
2. **把优先级写成遍历顺序，而不是写成过滤条件。** 一旦把 `desired` 和各 fallback 混进同一个条件去扫 `request.tools`，结果就会重新由容器顺序决定 —— 同一个 bug 换个写法。
3. **反向验证比正向验证更能说明问题。** "测试通过"只说明没坏；把缺陷还原回去看它变红，才说明测试真的在测这件事。

# D1 对照记录：MockToolGateway 不再猜 payload 形状（before / after）

- **日期**：2026-10-09
- **范围**：`src/fishery_ai/tool_conversation.py`（修改）、`tests/test_mock_tool_gateway.py`（新增）
- **状态**：已实施，`tests.test_mock_tool_gateway` **18/18**，全量 **779 项**通过
- **性质**：修的是**离线 UI 替身**的隐含假设，不是 Tool 协议、不是 Registry、不是 Policy

---

## 1. 问题是什么

`MockToolGateway` 是 `web.py` 开发页面在 `target == "mock"` 时使用的离线替身。它在 **Request #2**（`tool_choice == "none"`）里要把 tool 结果合成一句中文，但它是**用 payload 的键去反推"这是哪个工具的结果"**：

```python
if payload["status"] == "NO_DATA":            # ① 状态
    ...
elif "scoring_version" in payload:            # ② 再猜一次键
    ...
else:                                         # ③ 默认假定"当前水质"
    water = payload["water_quality"]          # ← 崩溃点
    payload["findings"]                       # ← 崩溃点
```

第 ② 层本身就是证据：光看 `status` 分不出两个水质工具，只能再猜一次键。

对 Knowledge 结果（`{status, retrieval_mode, result_count, evidence}`）：`NO_MATCH` 不匹配 ①、没有 `scoring_version` 不匹配 ② → 落进 ③ → `payload["water_quality"]` → **`KeyError`**。

---

## 2. before / after

### 2.1 导入

```python
# after（新增一行）
from .tools.policy import ToolPolicy, ToolPolicyError, load_tool_policies
from .tools.registry import CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE
```

用 Registry 的名称常量，避免在 Mock 里再写字面量工具名。

### 2.2 Request #2 的分支

**Before**

```python
        if request.tool_choice == "none":
            payload = json.loads(next(m.content for m in reversed(request.messages) if m.role == "tool"))
            if payload["status"] == "NO_DATA":
                text = "离线 Mock：没有当前水质数据，请先显式 Apply 情景或取得快照。"
            elif "scoring_version" in payload:
                text = (f"离线 Mock：实验评分 {payload['score']}，等级 {payload['grade']}，"
                        f"状态 {payload['status']}。EXPERIMENTAL / NOT PROFESSIONAL STANDARD；不是专业养殖标准。")
            else:
                water = payload["water_quality"]
                value = lambda key: "缺失" if water[key] is None else str(water[key])
                findings = "；".join(item["message"] for item in payload["findings"]) or "无阈值告警"
                text = (f"离线 Mock：水温 {value('temperature_c')} ℃，pH {value('ph')}，"
                        f"溶氧 {value('dissolved_oxygen_mg_l')} mg/L。"
                        f"质量 {water['quality']}；新鲜度 {water['freshness']}。确定性诊断：{findings}。")
            return ModelResponse(text, finish_reason="stop")
        question = request.messages[-1].content
```

**After**

```python
        if request.tool_choice == "none":
            return ModelResponse(_final_text(request.messages), finish_reason="stop")
        question = request.messages[-1].content
```

### 2.3 新增的模块级部件（Before：不存在）

```python
NO_DATA_TEXT = "离线 Mock：没有当前水质数据，请先显式 Apply 情景或取得快照。"
UNRENDERED_TEXT = "离线 Mock：该 Tool 尚无离线渲染。"


def _requested_tool_name(messages, tool_message) -> str | None:
    """Correlate a tool result with its own call through ``tool_call_id``.

    The id link is the protocol; "the first tool call in the list" is not.
    """
    call_id = getattr(tool_message, "tool_call_id", None)
    if not isinstance(call_id, str) or not call_id:
        return None
    for message in messages:
        if message.role != "assistant":
            continue
        for call in message.tool_calls:
            if call.id == call_id:
                return call.function_name
    return None


def _render_water_quality(payload: dict) -> str: ...   # 字符串与旧实现逐字一致
def _render_score(payload: dict) -> str: ...            # 字符串与旧实现逐字一致

RENDERERS = {CURRENT_WATER_QUALITY: _render_water_quality, WATER_QUALITY_SCORE: _render_score}


def _final_text(messages) -> str:
    tool_message = next((m for m in reversed(messages) if m.role == "tool"), None)
    if tool_message is None:
        return UNRENDERED_TEXT
    renderer = RENDERERS.get(_requested_tool_name(messages, tool_message))
    if renderer is None:
        return UNRENDERED_TEXT
    try:
        payload = json.loads(tool_message.content)
    except (TypeError, ValueError):
        return UNRENDERED_TEXT
    if not isinstance(payload, dict):
        return UNRENDERED_TEXT
    try:
        return renderer(payload)
    except (KeyError, TypeError, ValueError, AttributeError):
        return UNRENDERED_TEXT
```

---

## 3. 三条实现约定

| 约定 | 落实 |
| --- | --- |
| **按 tool name 分派，不按 status 猜形状** | `RENDERERS` 以 Registry 名称常量为键；status 只用于渲染器**内部**决定句子（`NO_DATA` 优先） |
| **用 `tool_call_id` 关联，不用 `tool_calls[0]`** | `_requested_tool_name()` 拿 `tool_message.tool_call_id`，回找 `assistant` 消息里 id 相同的 call 取 `function_name`；找不到 → 安全兜底 |
| **不引入 Multi-Tool** | 只在消息里找**关联的那一个** call；协调器仍是 1 call / 1 round / 2 requests，未改动 |

---

## 4. 行为等价与不变承诺

| 项 | 结论 |
| --- | --- |
| 水质工具 + `OK` | 句子**逐字不变**（测试锁定完整字符串） |
| 水质工具 + `NO_DATA` | 逐字不变 |
| 水质工具 + 缺值（`ph=None`） | 仍是"缺失"占位 |
| 水质工具 + `findings=[]` | 仍是"无阈值告警" |
| 评分工具 + 有分数 | 逐字不变 |
| **评分工具 + `NO_DATA`** | 仍是"没有当前水质数据…"句（保留旧实现的 "NO_DATA 优先" 顺序） |
| Request #1 | **完全未改**：概念问答、`现在/当前 → 工具调用`、desired 缺失时 fallback 到 `request.tools[0]` 全部保持（D1b 单独登记） |
| `finish_reason` | 仍为 `"stop"` |

只有"今天会崩溃的输入"改变了行为：从抛 `KeyError` 变成返回安全句。所有既有测试文件**一个都没有改**。

---

## 5. 新增测试：`tests/test_mock_tool_gateway.py`（18 项）

| 分组 | 测试 |
| --- | --- |
| 旧文本不变 | `test_water_quality_text_is_unchanged`、`test_water_quality_missing_value_keeps_the_placeholder`、`test_water_quality_without_findings_says_no_alarm`、`test_water_quality_no_data_text_is_unchanged`、`test_score_text_is_unchanged`、`test_score_no_data_keeps_the_same_no_data_text` |
| 按名字分派 | `test_unknown_tool_never_reads_another_tools_payload`（**完整水质 payload + Knowledge 名称 → 必须是兜底句，不得渲染水质**，此用例在旧代码上会失败）、`test_unknown_tool_payload_shape_does_not_raise`（Knowledge 形状不再 `KeyError`）、`test_water_tool_with_unexpected_shape_falls_back`、`test_score_tool_with_unexpected_shape_falls_back` |
| ID 关联 | `test_correlation_uses_the_tool_call_id`（assistant 声明 id 与 tool 消息 id 不一致 → 兜底）、`test_missing_tool_message_falls_back`、`test_non_object_tool_content_falls_back` |
| Request #1 不变 | `test_concept_question_still_answers_directly`、`test_current_question_still_calls_the_water_tool`、`test_scoring_question_prefers_the_score_tool_when_authorized`、`test_desired_tool_fallback_stays_unchanged`（锁定 D1b 现状）、`test_current_question_without_tools_explains_the_policy` |

---

## 6. 测试证据（实测）

```text
tests.test_mock_tool_gateway  → Ran 18 tests ... OK
unittest discover -s tests    → Ran 779 tests in 27.068s ... OK      (761 + 18)
```

## 7. 后续项

| 编号 | 内容 | 分类 |
| --- | --- | --- |
| **D1b** | Request #1 的 `request.tools[0]` fallback：策略只授权 Knowledge 时，问"现在…"会以 `"{}"` 调用 Knowledge 并被 validator 拒 | **已于 2026-10-09 解决** —— 改为显式方向性降级（`FALLBACK_TOOLS`）；见 [`D1B_MOCK_DIRECTIONAL_FALLBACK_BEFORE_AFTER.md`](D1B_MOCK_DIRECTIONAL_FALLBACK_BEFORE_AFTER.md) |
| — | 是否为 Knowledge 增加离线渲染器 | 明确**不在本步**（D1 只移除对水质 payload 的隐含假设）；Step 5 注册后再决定 |

## 8. 回滚

改动 = 1 个源文件的局部重写 + 1 个新增测试文件；`git diff` 可完整还原。

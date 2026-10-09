# Step 3 对照记录：`ToolStatus.NO_MATCH`（before / after）

- **日期**：2026-10-09
- **范围**：`src/fishery_ai/tools/contracts.py`、`src/fishery_ai/resources/web/app.js`，新增 `tests/test_tool_status_no_match.py`，扩展 `tests/test_browser_streaming.cjs`
- **状态**：已实施，Python 746 项 + 浏览器 183 项全部通过
- **未触碰**：`tool_conversation.py`、`tools/executor.py`、`observability.py`、`assistant.py`、`web.py`、`tools/policy.py`、`tools/catalog.py`、`tools/registry.py`、`ToolErrorCode`、历史 Preset 资格证据

---

## 1. 为什么只改这两个文件

先说清楚 NO_MATCH 到底动了什么：它只是**给一个已存在的"非错误结果"类别补上缺失的成员**。

- **后端**：`ToolStatus` 是 `ToolExecutionResult.from_payload()` 反序列化的**值域**。Handler 不能自己造枚举外的状态——`ToolStatus("NO_MATCH")` 会抛 `ValueError`，被兜成 `TOOL_EXECUTION_ERROR`。所以"不查到资料"会伪装成"工具故障"。**值域必须在这里扩**。
- **前端**：`safeAssistantActivity()` 是浏览器的**安全投影白名单**。白名单外的值一律置 `null`（fail-closed，不是漏洞），但用户会看到 `unavailable`。既然后端合同已经承认这个合法状态，投影也要认识它，否则"诚实说明资料不足"在界面上表现为"状态未知"。
- **其余消费者天然正确**，所以不动（第 3 节逐条给理由）。

---

## 2. before / after

### 2.1 `src/fishery_ai/tools/contracts.py`

**Before**

```python
class ToolStatus(str, Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    NOT_SCORABLE = "NOT_SCORABLE"
    NO_DATA = "NO_DATA"
    ERROR = "ERROR"
```

**After**

```python
class ToolStatus(str, Enum):
    """Business result of one tool execution.

    Every non-error status carries ``error_code is None`` and does not stop the
    follow-up model request; only ``ERROR`` does. ``NO_DATA`` means the subject
    itself has no current data (for example no applied snapshot). ``NO_MATCH``
    means the request was valid but nothing qualified (for example a read-only
    search whose hits did not meet the minimum). They are deliberately distinct.
    """

    OK = "OK"
    PARTIAL = "PARTIAL"
    NOT_SCORABLE = "NOT_SCORABLE"
    NO_DATA = "NO_DATA"
    NO_MATCH = "NO_MATCH"
    ERROR = "ERROR"
```

要点：
- **只新增成员**，原有五个成员的名字与值一个没动。
- 文档串把"非错误 / 只有 ERROR 终止第二轮"写成合同的一部分，避免下次再靠读代码推断。
- **没有**动 `ToolErrorCode`。

### 2.2 `src/fishery_ai/resources/web/app.js`

**Before**

```js
    tool_status: ["OK", "NO_DATA", "PARTIAL", "NOT_SCORABLE", "ERROR"].includes(value.tool_status) ? value.tool_status : null,
```

**After**

```js
    tool_status: ["OK", "NO_DATA", "NO_MATCH", "PARTIAL", "NOT_SCORABLE", "ERROR"].includes(value.tool_status) ? value.tool_status : null,
```

要点：仍然是**白名单包含判断** —— 白名单之外照样置 `null`。**没有**放开 `used_tool`、**没有**放开工具名白名单（那是 Step 10），**也没有**让前端获得任何新权限。

---

## 3. 消费者清单与分类（全量搜索结果）

搜索关键词：`ToolStatus`、`tool_result_status`、`tool_status`、`NO_DATA`、`NOT_SCORABLE`、`PARTIAL`、`from_payload`、`status.value`；范围 `src/**` + `tests/**` + `docs/**`。

### A. 必须修改（本次已改）

| # | 位置 | 不改会怎样 |
| --- | --- | --- |
| A1 | `tools/contracts.py` `class ToolStatus` | Handler 返回 `NO_MATCH` → `ValueError` → 被兜成 `TOOL_EXECUTION_ERROR` → 用户看到"工具失败"，真相是"没查到资料" |
| A2 | `app.js:2760` `safeAssistantActivity()` 白名单 | 被置 `null` → 前端显示 `unavailable`（fail-closed，但状态不可见） |

### B. 只需要补测试（代码已正确，本次用新测试锁定）

| # | 位置 | 为什么已正确 | 本次锁定的断言 |
| --- | --- | --- | --- |
| B1 | `tool_conversation.py:236` | 只比较 `ToolStatus.ERROR` | 首轮 `NO_MATCH` → **仍发 Request #2** → `COMPLETED`；对照：`ERROR` → `request_2 == "not_started"`、`FAILED` |
| B2 | `tools/contracts.py` `from_payload` | 按值查表，自动接受 | `NO_MATCH` 的 `error_code is None` |
| B3 | `tools/executor.py:58` | 直接透传 payload | 带参工具返回 `NO_MATCH` 时状态正确、结果大小上限仍生效 |
| B4 | `observability.py:77` | 只写 `status.value`，无值域校验 | Trace 出现 `"tool_result_status":"NO_MATCH"`，且**不含**问题原文与 `evidence` |
| B5 | `assistant.py:184` `to_dict()` | 透传 | `tool_activity.tool_status == "NO_MATCH"` 且 `successful_turn` 仍为 `True` |
| B6 | `web.py:1127` `arguments` 字段 | `!= "ERROR"` → 非错误状态写 `{}` | **本步不改**；已登记为"参数型 Knowledge Tool 接入前依赖"（见第 6 节） |

### C. 完全不需要变化（已核对，不机械修改）

| 位置 | 理由 |
| --- | --- |
| `tools/executor.py` `_error()` | `NO_MATCH` **不是** `ToolErrorCode`；错误路径不变 |
| `water_quality_scoring.py` | 它只**产出** `NO_DATA / NOT_SCORABLE / PARTIAL / OK` 字符串；加成员不影响它（是它约束枚举，不是反过来） |
| `application.py:47` `called` | `payload.get("status") != "ERROR"` → `NO_MATCH` 视为"已调用"，语义正确 |
| `application.py:227` + `app.js:1577` `snapshot_comparison == "no_data"` | 属于 Analysis 自有的比较结果，与 `ToolStatus` 无关 |
| `tool_capability_probe.py` / `preset_tool_qualification.py` 的 `("OK","NO_DATA")` 成功白名单 | 两处都**硬编码探测 `get_current_water_quality`**，`NO_MATCH` 不可能出现。**不改**，但已在文档写明：将来若用它探测 Knowledge，必须先评审这份白名单 |
| `resources/profiles/presets.json` 历史 `tool_result_status` | **历史资格证据，绝不能改** |
| `index.html` / `app.css` / `model_gateway.py` / `policy.py` / `catalog.py` / `registry.py` | 不含状态值域 |

### D. 本轮不改，登记为后续依赖

| 编号 | 位置 | 分类 | 触发条件 |
| --- | --- | --- | --- |
| **D1** | `tool_conversation.py:47` `MockToolGateway` 的 `NO_DATA` 分支 | **BLOCKER BEFORE KNOWLEDGE REGISTRATION** | 该分支的 `else` 读 `payload["water_quality"]` → `NO_MATCH` 会 `KeyError`。**必须在 Step 5 注册 Knowledge Tool 之前解决** |
| **D2** | `application.py:47-49` `snapshot_comparison` | 当前不改 | Knowledge Tool 仍是 Assistant-only；只有未来允许 Analysis 使用时才重新评审 |
| **D3** | `app.js:2759` 工具名白名单、`:2794` 硬编码文案 | 当前不改，**Step 10 必须处理** | 否则 Knowledge 调用会被置 `null` / 误标为"已查询当前水质" |

> 这三条都不是"忘了改"，而是**现在改才是错的**（Knowledge 尚未注册、Analysis 未开放）。已全部登记在 [`KNOWLEDGE_TOOL_STEP_BY_STEP.md`](KNOWLEDGE_TOOL_STEP_BY_STEP.md) §4。

---

## 4. 链路证明（要求逐项核对）

| 要求 | 结论 | 证据 |
| --- | --- | --- |
| `NO_MATCH` → `error_code is None` | ✅ | `test_no_match_is_a_non_error_result` |
| Executor 正常返回（不是 ERROR） | ✅ | 同上；且断言 `payload` 原样返回、`to_json()` 首字段为 `NO_MATCH` |
| `ToolCallingService` 继续 Request #2 | ✅ | `test_no_match_continues_to_request_2_and_completes`：`request_1 == tool_calls`、`request_2 == final_answer`、`tool_choice == "none"`、tool 消息含 `"status":"NO_MATCH"` |
| 对照：`ERROR` 仍然终止 | ✅ | `test_error_result_still_stops_before_request_2`：`request_2 == not_started`、`FAILED`、只发 1 次请求 |
| Assistant 最终可 `COMPLETED` | ✅ | `test_assistant_turn_with_no_match_is_completed_and_public_safe`：`Status.COMPLETED`、`successful_turn == True`、公开结果无 `tool_result` / 无 payload 字段 |
| Trace 安全记录 `NO_MATCH` | ✅ | `test_trace_records_no_match_without_prompt_or_arguments`：`tool_result_status == "NO_MATCH"`、`status == completed`、`error_code is None`，且**不含问题原文**、**不含 `arguments` 字段**、**不含 `evidence`** |
| UI 安全投影保留 `NO_MATCH` | ✅ | Python：`test_ui_safe_projection_keeps_no_match`（静态断言白名单含六个状态）；浏览器：`test_browser_streaming.cjs` 的状态参数表加入 `NO_MATCH` 一行后 **183 项通过** |

### 为什么 Trace 不需要白名单修改

`observability.py::record_tool_conversation()` 里，`tool_call_id` 走正则白名单、`tool_name` 走 `ToolRegistry.registered_names()` 白名单，而 `tool_result_status` 是 `tool.status.value` **直接写入**、没有值域校验。所以加成员后 Trace 自动写出新值——需要的是**补断言**，不是改代码。

---

## 5. 旧五值行为不变的证明

| 论据 | 说明 |
| --- | --- |
| 只新增成员 | `OK / PARTIAL / NOT_SCORABLE / NO_DATA / ERROR` 的名字与值一字未改 |
| 反序列化是按值查找 | `from_payload` 用 `ToolStatus(payload["status"])`，五个旧值仍解析到同一成员 |
| 错误路径未动 | `executor._error()` 仍只产 `ERROR`；`ToolErrorCode` 未动 |
| 判据是包含关系 | `tool_conversation` 只比较 `ERROR`；`app.js` 是 `includes`，加一项不影响其它项 |
| **有意的唯一放宽** | 以前返回 `{"status":"NO_MATCH"}` 会被兜成 `TOOL_EXECUTION_ERROR`，现在被当作合法状态 |

测试锁定（`test_tool_status_no_match.py`）：
- `test_existing_statuses_keep_their_exact_meaning`：逐值核对 `OK/PARTIAL/NOT_SCORABLE/NO_DATA` → `error_code is None`，`ERROR` → `TOOL_EXECUTION_ERROR`。
- `test_value_domain_is_not_widened_beyond_no_match`：`NO_RESULT / NONE / none / no_match / ""` **仍然**是 `TOOL_EXECUTION_ERROR` —— 证明这次只认 `NO_MATCH` 一个值，没有把值域整体放开。
- `test_no_data_and_no_match_are_distinct_members`：两者不相等。
- `test_no_match_still_obeys_the_result_size_limit`：非错误结果照样受结果大小上限约束。

---

## 6. 明确没有做的事

- **没有**注册任何工具、没有改 Registry / Catalog / Policy。
- **没有**创建 Knowledge Handler，也没有让任何现有 Handler 返回 `NO_MATCH`（所以线上行为零变化）。
- **没有**修 D1 / D2 / D3，也**没有**顺手改 `web.py` 的 `arguments` 字段（B6）——后者已归入"参数型 Knowledge Tool 接入前依赖"。
- **没有**改写带审查日期的历史研究报告结论：`TOOL_ORCHESTRATION_ARCHITECTURE_REVIEW.md`（基线 `6b9dad9`）只**追加了一段注明日期的后续状态注记**；`KNOWLEDGE_TOOL_DESIGN.md` 同理只加注记。

## 7. 文档同步清单

| 文件 | 处理方式 |
| --- | --- |
| `docs/deep-dive/tools/ADDING_A_TOOL.md` | **直接同步**（当前状态型规范）：状态清单加入 `NO_MATCH` 并说明语义；第二轮说明补 `NO_MATCH` |
| `docs/handoff/KNOWLEDGE_TOOL_V1_WALKTHROUGH.md` | **直接同步**：顶部加"前置步骤进度"注记；修正"当前 ToolStatus 没有 NO_MATCH"；文件修改清单两行改为实际状态 |
| `docs/deep-dive/research/KNOWLEDGE_TOOL_DESIGN.md` | **只加日期注记**，不改历史结论 |
| `docs/deep-dive/research/TOOL_ORCHESTRATION_ARCHITECTURE_REVIEW.md` | **只加日期注记**（该文有 2026-10-08 / `6b9dad9` 基线） |
| `docs/copilot/KNOWLEDGE_TOOL_STEP_BY_STEP.md` | Step 3 标为已实施；新增 §4 后续依赖登记（D1/D2/D3/B6） |
| `docs/STRUCTURE.md` | 登记新增测试文件 |

## 8. 测试证据（实测）

```text
tests.test_tool_status_no_match            → Ran 10 tests  ... OK
unittest discover -s tests                 → Ran 746 tests in 61.144s ... OK
node --test tests/test_browser_streaming.cjs → tests 183 / pass 183 / fail 0
```

| 新增测试 | 保护什么 |
| --- | --- |
| `test_no_match_is_a_non_error_result` | 非错误结果 + `error_code is None` |
| `test_no_match_still_obeys_the_result_size_limit` | 结果大小上限仍生效 |
| `test_value_domain_is_not_widened_beyond_no_match` | 值域只放开一个成员 |
| `test_existing_statuses_keep_their_exact_meaning` | 旧五值语义不变 |
| `test_no_data_and_no_match_are_distinct_members` | `NO_DATA` ≠ `NO_MATCH` |
| `test_no_match_continues_to_request_2_and_completes` | 继续第二轮并完成 |
| `test_error_result_still_stops_before_request_2` | `ERROR` 仍终止 |
| `test_assistant_turn_with_no_match_is_completed_and_public_safe` | Assistant 可完成且公开结果不含原始 payload |
| `test_trace_records_no_match_without_prompt_or_arguments` | Trace 记录状态但不记录 prompt/参数/证据 |
| `test_ui_safe_projection_keeps_no_match` | 前端白名单保留该状态 |

## 9. 回滚

改动集中在 2 个源文件 + 1 个新增测试文件 + 1 处浏览器测试参数表，`git diff` 即可完整还原；未涉及数据、凭据、配置或产物。

## 10. 下一步

**Step 4（新增薄 Handler）尚未开始。** 开始前需要先处理 **D1**（`MockToolGateway` 的 `NO_DATA` 分支），它被标记为 *BLOCKER BEFORE KNOWLEDGE REGISTRATION*，最迟必须在 Step 5 注册 Registry 之前完成。

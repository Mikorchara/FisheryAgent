# Step 2 对照记录：Tool 受控参数合同（before / after）

- **日期**：2026-10-08
- **范围**：`src/fishery_ai/tools/contracts.py`、`src/fishery_ai/tools/executor.py`，新增 `tests/test_tool_argument_contract.py`
- **状态**：已实施，离线测试全绿
- **未触碰**：Knowledge / Registry / Catalog / Policy / Gateway / Application / 任何 Handler

---

## 1. 为什么只改这两个文件

- **`tools/contracts.py`**：`ToolDefinition` 是"定义 ←→ 可执行函数"的唯一绑定类型。它现在**没有地方描述参数**，所以 Executor 只能把"参数必须为空 `{}`"写死在自己肚子里。要把这个规则交还给工具自己声明，必须动这个类型。
- **`tools/executor.py`**：`execute()` 是**唯一**执行入口（Policy、预算、取消、结果大小、错误脱敏都在它身上）。参数校验必须留在它内部，**不能**下放到 Handler——否则就绕过了同一道门。

两个文件之外**没有**任何间接改动，所以"旧工具行为不变"是可验证的。

---

## 2. `tools/contracts.py`

### Before

```python
from dataclasses import dataclass, field
from enum import Enum
import json
from typing import Callable

from ..model_gateway import ModelToolDefinition
...
@dataclass(frozen=True)
class ToolDefinition:
    model_definition: ModelToolDefinition
    handler: Callable[[], dict] = field(repr=False, compare=False)
```

### After

```python
from dataclasses import dataclass, field
from enum import Enum
from functools import partial          # ← 新增
import json
from typing import Callable

from ..model_gateway import ModelToolDefinition
...
@dataclass(frozen=True)
class ToolDefinition:
    """Static binding of one model-visible definition to one server-side handler.

    Parameterless tools (the current default) leave ``validate_arguments`` unset:
    the Executor only accepts an empty ``{}`` object and calls ``handler()``.

    A tool that accepts parameters supplies ``validate_arguments``. The Executor
    parses the model's JSON, hands that object to the callable, and calls the
    handler with the **normalized** arguments as a single positional argument.
    Rejection is expressed by raising; the Executor maps it to a safe error.
    """

    model_definition: ModelToolDefinition
    handler: Callable[..., dict] = field(repr=False, compare=False)          # 原 Callable[[], dict]
    validate_arguments: Callable[[dict], dict] | None = field(default=None, repr=False, compare=False)

    def bind(self, arguments: dict) -> Callable[[], dict]:
        """Return the zero-argument invocation for already-parsed arguments.

        This is the whole server-side parameter contract: reject, normalize, and
        only then hand arguments to the bound handler. Bound once per call.
        """
        if self.validate_arguments is None:
            if arguments:
                raise ValueError("this tool accepts no parameters")
            return self.handler
        validated = self.validate_arguments(arguments)
        if not isinstance(validated, dict):
            raise ValueError("validated arguments must be a JSON object")
        return partial(self.handler, validated)
```

要点：

- **新字段带默认值**，所以 `ToolDefinition(definition, handler)` 这种两参数构造（Registry 与旧测试都在用）**完全不变**。
- 默认行为就是旧行为：`validate_arguments is None` → 非空参数即拒绝。
- 提供参数的形状**只有一种**：`handler(validated_arguments)`，一个位置参数、一个 dict。不做反射、不做 `**kwargs`、不按名字猜。

---

## 3. `tools/executor.py`

### Before

```python
            try:
                if len(call.arguments_json.encode("utf-8")) > 4096:
                    raise ValueError
                arguments = json.loads(call.arguments_json)
                if not isinstance(arguments, dict) or arguments:   # ← 「必须为空」写死在这里
                    raise ValueError
            except (ValueError, TypeError, RecursionError, UnicodeError, AttributeError):
                raise ToolError(ToolErrorCode.INVALID_TOOL_ARGUMENTS) from None
            check_cancelled()
            payload = definition.handler()                          # ← 无参调用
            check_cancelled()
```

### After

```python
            try:
                if len(call.arguments_json.encode("utf-8")) > 4096:
                    raise ValueError
                arguments = json.loads(call.arguments_json)
                if not isinstance(arguments, dict):                 # ← 只保留「必须是 JSON object」
                    raise ValueError
                # The definition owns its parameter contract; the Executor only
                # enforces size, JSON shape and the safe error mapping.
                invoke = definition.bind(arguments)
            except (ValueError, TypeError, RecursionError, UnicodeError, AttributeError):
                raise ToolError(ToolErrorCode.INVALID_TOOL_ARGUMENTS) from None
            check_cancelled()
            payload = invoke()                                      # ← 统一零参调用
            check_cancelled()
```

执行顺序（**其余一律未动**）：

```text
check_cancelled
→ 预算 / 重复 call ID
→ Registry.lookup
→ Policy.allows
→ arguments_json ≤ 4096 UTF-8 bytes
→ 必须是 JSON object
→ definition.bind(arguments)   ← 新增：拒绝或归一化（在 Executor 内、Handler 之前）
→ check_cancelled
→ invoke()                      ← Handler 真正执行
→ check_cancelled
→ ToolExecutionResult.from_payload（status 校验）
→ 结果 ≤ max_result_bytes
→ check_cancelled
```

---

## 4. 行为对照

| 场景 | Before | After | 是否变化 |
| --- | --- | --- | --- |
| 旧工具 + `{}` | `handler()` | `handler()`（`bind` 直接返回 handler） | **不变** |
| 旧工具 + `{"x":1}` | `INVALID_TOOL_ARGUMENTS` | 同左（改由 `bind` 抛出，仍映射为同一错误码） | **不变** |
| 非 JSON object | `INVALID_TOOL_ARGUMENTS` | 同左 | 不变 |
| 参数 > 4096 bytes | `INVALID_TOOL_ARGUMENTS`，**不解析** | 同左，且**不会调用校验器** | 不变 |
| Registry 中 `handler` 的类型 | `functools.partial`（`keywords` 含 `reader`） | **仍是 `partial`** | **不变** |
| 声明了参数的工具 + 合法参数 | 不支持（必然拒绝） | 校验器收到 dict → 归一化 → `handler(validated)` | **新增能力** |
| 校验器抛 `ValueError` / `TypeError` | — | `INVALID_TOOL_ARGUMENTS`，Handler **不执行** | 新增 |
| 校验器抛其它异常 | — | `TOOL_EXECUTION_ERROR`（脱敏），Handler **不执行** | 新增 |
| 校验器返回非 dict | — | `INVALID_TOOL_ARGUMENTS`，Handler **不执行** | 新增 |

> 注意这一条差异是有意保留的：**`ValueError`/`TypeError` = "参数不合格"；其它异常 = 框架故障。** 两者都是安全错误码，都不外泄原文，都不执行 Handler。

---

## 5. 设计取舍：为什么 `handler` 没有统一改成 `handler(arguments)`

最初的计划是"统一采用 `handler(validated_arguments)`，为旧工具加固定包装"。**实际无法这样做**，因为既有测试依赖两个具体形状：

1. `tests/test_web_tool_conversation.py` 直接读 `registry.lookup(NAME).handler.keywords["reader"]` → **`handler` 必须仍是 `functools.partial`**。套一层包装函数就会失去 `.keywords`。
2. `tests/test_read_only_tools.py` 里有 `def handler(): ...`（零参函数）与 `Mock(return_value=...)` 直接构造 `ToolDefinition` → 若统一传参，零参 Handler 会抛 `TypeError`，反而变成 `TOOL_EXECUTION_ERROR`。

因此改成"**两种调用形状，由 `validate_arguments` 是否声明来区分**"：

- 没声明 → 旧形状 `handler()`（字节级兼容，零测试改动）
- 声明了 → 新形状 `handler(validated_arguments)`

结果是**没有修改任何既有测试**，同时新能力可用。这也符合项目"先保护旧工具、再最小演进"的要求。

---

## 6. 踩坑记录（本次真实发生）

**现象**：新增测试文件一运行就报 `AttributeError: 'ToolArgumentContractTests' object has no attribute 'registry'`，且 `setUp` 看起来"没执行"。

**原因**：我把测试内的辅助方法命名为 `run`，**覆盖了 `unittest.TestCase.run`**。unittest 是通过 `test.run(result)` 驱动整个生命周期的；被覆盖后 `setUp` 根本不会被调用。

**解法**：辅助方法改名 `execute_with`。

> 通用教训：在 `unittest.TestCase` 子类里，**不要定义** `run` / `setUp` / `tearDown` / `__call__` 这些同名成员。

---

## 7. 测试证据（本次实测）

```powershell
# 新增文件
.\.venv\Scripts\python.exe -B -m unittest tests.test_tool_argument_contract -v
→ Ran 14 tests ... OK

# 全量离线回归
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
→ Ran 736 tests in 28.753s ... OK
```

新增 14 项覆盖：

| 测试 | 保护什么 |
| --- | --- |
| `test_legacy_tool_still_rejects_any_argument` | 旧工具仍拒绝非空参数，且 Handler 不被调用 |
| `test_legacy_tool_is_invoked_without_arguments` | 旧工具仍以**零参**调用（形状不变） |
| `test_registry_handlers_keep_their_partial_shape` | `handler` 仍是 `partial` 且保留 `reader`（锁住上面的兼容取舍） |
| `test_definition_stays_immutable` | `ToolDefinition` 仍不可变 |
| `test_declared_contract_receives_normalized_arguments` | 校验器输出**原样**交给 Handler，未声明字段不进入结果 |
| `test_declared_contract_may_accept_an_empty_object` | 参数化工具也允许 `{}` |
| `test_validator_rejection_is_safe_and_handler_never_runs` | 拒绝 → `INVALID_TOOL_ARGUMENTS`，Handler 不执行 |
| `test_validator_unexpected_error_is_redacted` | 意外异常 → 安全 `TOOL_EXECUTION_ERROR`，不含 secret / 路径 |
| `test_validator_must_return_an_object` | 校验器返回非 dict（4 种）一律拒绝 |
| `test_argument_size_limit_applies_before_validation` | 4096 bytes 上限在校验**之前**，校验器不被调用 |
| `test_non_object_arguments_are_rejected_before_validation` | 非 object JSON 在校验之前被拒 |
| `test_result_size_limit_still_applies_to_parameterized_tools` | 结果大小上限对参数化工具同样生效 |
| `test_unsupported_status_from_parameterized_tool_is_safe_error` | 伪造 status 仍是安全错误 |
| `test_rejected_arguments_still_consume_the_call_budget` | 被拒的尝试仍消耗调用预算（旧规则保持） |

---

## 8. 本次明确没有做的事

- 没有新增 `ToolStatus.NO_MATCH`（那是 Step 3，且要先核对消费者）
- 没有注册任何新工具、没有改 Registry / Catalog / Policy
- 没有动 Knowledge 相关代码，也没有改动 Analysis 或 Assistant 流程
- 没有放宽旧工具的 `{}` 限制

## 9. 下一步

**Step 3**：新增 `ToolStatus.NO_MATCH`，先产出消费者清单（`tools/contracts.py`、`tool_conversation.py`、`observability.py`、`resources/web/app.js`、相关测试），确认"只有 `ERROR` 会终止第二轮、`NO_MATCH` 必须继续交给模型解释"。

## 10. 回滚

本次改动集中在 2 个源文件 + 1 个新增测试文件，`git diff` 即可完整还原；未涉及数据、凭据、配置或产物。

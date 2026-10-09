# Step 5 对照记录：Knowledge Tool 注册、依赖注入与 query validator（before / after）

- **日期**：2026-10-09
- **范围**：`src/fishery_ai/tools/registry.py`、`src/fishery_ai/tools/handlers/knowledge_search.py`（修改）；`tests/test_knowledge_registration.py`（新增）；`tests/test_tool_policy.py`、`tests/test_tool_policy_manager.py`（4 行断言同步）
- **状态**：已实施，Python **796 项**、浏览器 **183 项**全部通过
- **关键性质**：**注册 ≠ 授权**。本步让 Registry 能绑定并执行该工具，但没有任何模式默认授权它。

---

## 1. 本步解决的三个问题

| # | 问题 | 结论 |
| --- | --- | --- |
| 1 | 未注入 `KnowledgeService` 时怎么办？（原待定） | **不拒绝组合、也不制造假状态**：未注入 → 该名称**不被这个实例暴露**；`lookup()` 与 `model_definitions()` 始终一致 |
| 2 | 正式 validator 谁来做（Step 4 留给本步） | 落在 Handler 模块：`validate_arguments()` + `MAX_QUERY_CHARS = 512`，由 Registry 绑定给 `ToolDefinition` |
| 3 | `registered_names()` 语义 | 变为**全部已知名称的固定 allowlist**（Policy 默认文件 + Trace/公开输出白名单），**不等于**实例绑定集合 |

---

## 2. before / after

### 2.1 `tools/registry.py`

**Before**

```python
CURRENT_WATER_QUALITY = "get_current_water_quality"
WATER_QUALITY_SCORE = "score_current_water_quality"


class ToolRegistry:
    @staticmethod
    def registered_names() -> tuple[str, ...]:
        """Same fixed name used below; Policy may only restrict this allowlist."""
        return (CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE)

    def __init__(self, reader, diagnosis, scoring=None):
        definition = ModelToolDefinition(...)
        score_definition = ModelToolDefinition(...)
        self._entries = MappingProxyType({definition.name: ToolDefinition(...),
            score_definition.name: ToolDefinition(...)})
```

**After**

```python
CURRENT_WATER_QUALITY = "get_current_water_quality"
WATER_QUALITY_SCORE = "score_current_water_quality"
SEARCH_FISHERY_KNOWLEDGE = "search_fishery_knowledge"

KNOWLEDGE_DESCRIPTION = (
    "只读检索项目内鳗鲡养殖背景知识。不代表当前传感器状态，不诊断现场疾病，不负责当前评分；"
    "结果是有限背景证据而非现场事实，无合格命中时返回NO_MATCH。"
)
KNOWLEDGE_PARAMETERS = {
    "type": "object",
    "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 512}},
    "required": ["query"],
    "additionalProperties": False,
}


class ToolRegistry:
    @staticmethod
    def registered_names() -> tuple[str, ...]:
        """Complete fixed name allowlist: Policy defaults and safe-output sanitizers.

        This is every name this codebase knows, not the set one instance can run.
        An instance binds only the tools whose dependencies it was given, so
        `model_definitions()` and `lookup()` stay consistent with each other and
        never advertise something they cannot resolve.
        """
        return (CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE, SEARCH_FISHERY_KNOWLEDGE)

    def __init__(self, reader, diagnosis, scoring=None, knowledge: KnowledgeService | None = None):
        definition = ModelToolDefinition(...)        # 两个水质定义：字符串一字未改
        score_definition = ModelToolDefinition(...)
        entries = {definition.name: ToolDefinition(...), score_definition.name: ToolDefinition(...)}
        if knowledge is not None:
            # Bound only when the shared service is supplied: a registered entry
            # always has an executable handler, and an unbound name is simply not
            # exposed by this instance.
            entries[SEARCH_FISHERY_KNOWLEDGE] = ToolDefinition(
                ModelToolDefinition(SEARCH_FISHERY_KNOWLEDGE, KNOWLEDGE_DESCRIPTION, KNOWLEDGE_PARAMETERS),
                partial(search_fishery_knowledge, service=knowledge),
                validate_arguments=validate_knowledge_arguments)
        self._entries = MappingProxyType(entries)
```

要点：
- 两个水质工具的 **description / parameters / 绑定方式一字未改**，只是从内联 dict 改成先建 `entries` 再按条件追加。
- 名字常量复用，不在别处再写字面量。
- 条件绑定写在**构造期**，静态、无配置驱动、无动态加载。

### 2.2 `tools/handlers/knowledge_search.py`（新增 validator）

```python
MAX_QUERY_CHARS = 512   # Declared parameter bound; 512 CJK chars is 1536 UTF-8 bytes.

def _is_rejected_character(character: str) -> bool:
    """True for C0/C1 controls (Cc) and lone surrogates (Cs).

    Written as explicit code-point ranges so this module keeps zero imports: it
    depends only on the injected service.
    """
    code = ord(character)
    return code <= 0x1F or 0x7F <= code <= 0x9F or 0xD800 <= code <= 0xDFFF


def validate_arguments(arguments: dict) -> dict:
    if not isinstance(arguments, dict) or set(arguments) != {"query"}:
        raise ValueError("only the query field is accepted")
    query = arguments["query"]
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    query = query.strip()
    if not query:
        raise ValueError("query must not be blank")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError("query is too long")
    if any(_is_rejected_character(character) for character in query):
        raise ValueError("query must not contain control or surrogate characters")
    return {"query": query}
```

> **实现选择**：一开始用了 `unicodedata.category(...) in ("Cc", "Cs")`，但那样会给该模块引入一个 `import`，而 Step 4 的既有断言 `test_handler_module_keeps_no_io_or_model_imports` 要求它**零绝对导入**。改用显式码点区间后，**该不变式保持不变**，且语义等价（Cc = `≤0x1F` 与 `0x7F–0x9F`；Cs = `0xD800–0xDFFF`），比调库更直白。

### 2.3 4 行既有断言的同步

`test_tool_policy.py` ×2、`test_tool_policy_manager.py` ×2 都**快照了** `registered_names()` 的内容：

```python
# before
self.assertEqual(self.registry.registered_names(), (NAME, "score_current_water_quality"))
# after（另加一句注释说明 allowlist 与绑定集合的区别）
self.assertEqual(self.registry.registered_names(),
                 (NAME, "score_current_water_quality", "search_fishery_knowledge"))
```

这是**本步既定动作**（Walkthrough §5 第 2 条即"更新 `registered_names()`"），不是为了让测试变绿而改。除这 4 行外，**没有任何既有测试被修改**。

---

## 3. 为什么"注册 ≠ 授权"

| 层次 | 本步状态 |
| --- | --- |
| Registry 绑定 | 注入服务后**可以执行**（`lookup()` 拿得到 handler） |
| 包内默认 Policy | **未变**：`assistant.exposed_tools == (get_current_water_quality,)`，`analysis` 空 |
| Catalog | **仍只有两条** → 用户 override 选中 Knowledge 会被 `UserToolPolicyStore` 判为 `TOOL_NOT_EXECUTABLE` |
| 应用装配 | `web.py` **尚未注入**（Step 8）→ 应用里根本不绑定该 entry |

所以：即使有人手动把名字写进用户 override，也会被 Catalog 的 executable 集合挡下（fail-closed）；即使绕过，`web.py` 没注入服务，实例里也没有这个 entry。

---

## 4. 新增测试：`tests/test_knowledge_registration.py`（17 项）

| 分组 | 测试 | 保护什么 |
| --- | --- | --- |
| A 注册与注入 | `test_name_allowlist_covers_every_known_tool` | 白名单含三名 |
| | `test_registry_without_the_service_does_not_expose_knowledge` | 未注入 → 不暴露；`lookup` → `UNKNOWN_TOOL` |
| | `test_registry_binds_knowledge_once_when_the_service_is_injected` | handler 是 `partial` 且 `service` 是同一实例；validator 已绑定 |
| | `test_declared_schema_is_exactly_the_query_contract` | schema == 常量；`required==["query"]`；`additionalProperties is False`；`maxLength==512` |
| | `test_advertised_names_are_always_resolvable` | 两个实例都不出现"注册但不可执行" |
| | `test_existing_tools_are_untouched_by_the_new_entry` | 前两条名字/空 schema/`validate_arguments is None`/`reader` 绑定不变 |
| B validator（经真实 Executor） | `test_legal_query_reaches_the_service_normalized` | 归一化（strip）后到达服务；`top_k==3`；payload `OK` |
| | `test_missing_unknown_and_extra_fields_are_rejected` | `{}`、`{"q":…}`、`top_k`、`backend`、`path` 全部拒绝且**不触达服务** |
| | `test_wrong_type_is_rejected` | 非字符串四种 |
| | `test_blank_query_is_rejected` | 空白/制表/换行 |
| | `test_query_length_boundary` | 512 通过 / 513 拒绝 |
| | `test_control_and_surrogate_characters_are_rejected` | 内部换行、`\x7f`、**孤立代理项**（`\ud800`） |
| | `test_oversized_arguments_never_reach_validation` | >4096 bytes 由 Executor 先拦 |
| | `test_unauthorized_knowledge_call_is_still_refused` | 未授权时 `TOOL_NOT_ALLOWED`，服务零调用 |
| C 默认关闭 | `test_package_defaults_grant_nothing_new` | 包内默认 Policy 未被改写 |
| | `test_catalog_exposes_no_knowledge_entry_yet` | executable 集合仍只有两条 |
| | `test_user_override_cannot_select_knowledge_yet` | 用户 override 选中 → `TOOL_NOT_EXECUTABLE` |

---

## 5. 测试证据（实测）

```text
tests.test_knowledge_registration          → Ran 17 tests ... OK
unittest discover -s tests                 → Ran 796 tests in 26.481s ... OK      (779 + 17)
node --test tests/test_browser_streaming.cjs → tests 183 / pass 183 / fail 0
```

中途出现 1 次失败（我自己 Step 4 写的"零绝对导入"断言因 `import unicodedata` 失败），已按第 2.2 节改成显式码点区间修复——**没有削弱那条不变式**。

---

## 6. 明确没有做的事

- **没有**改 `web.py` 装配（Step 8）：应用里仍不注入 KnowledgeService
- **没有**加 Catalog 条目（Step 6）→ 因此**用户还不能勾选**该工具
- **没有**改包内默认 Policy（Step 7）
- **没有**改 `tools/__init__.py` 导出（本步不需要；是否导出留待需要时再定）
- **没有**改 Assistant 提示词（Step 9）、UI 文案（Step 10）
- **没有**动 `knowledge.py`、`ToolExecutor`、`ToolDefinition`、`ToolStatus`、`model_gateway.py`

## 7. 后续项

| 编号 | 内容 | 触发 |
| --- | --- | --- |
| **D1b** | `MockToolGateway` Request #1 的 `tools[0]` fallback | **BLOCKER BEFORE MOCK KNOWLEDGE ENABLEMENT**（本行记录当时状态；**已于 2026-10-09 解决**，见 [`D1B_MOCK_DIRECTIONAL_FALLBACK_BEFORE_AFTER.md`](D1B_MOCK_DIRECTIONAL_FALLBACK_BEFORE_AFTER.md)） |
| **K1** | `retrieval_version` 由 `KnowledgeService` 提供 metadata | RAG 研究重启 |
| **K2** | Handler 侧总预算若引入，必须显式标识裁剪 | 需要更小总预算时 |
| — | Catalog 条目（Step 6）会让用户**可以**勾选；届时"仅 Assistant"是否要服务端硬边界按下述决定：**不做**（只在 UI 默认不勾选），但 `modes` 必须保持单一权威来源 | Step 6 |

## 8. 回滚

改动为 1 个 registry 局部重写 + 1 个 validator 新增 + 1 个新测试文件 + 4 行断言同步；`git diff` 可完整还原。

# Step 4 对照记录：薄 Knowledge Handler（before / after）

- **日期**：2026-10-09
- **范围**：新增 `src/fishery_ai/tools/handlers/knowledge_search.py`、`tests/test_knowledge_handler.py`
- **状态**：已实施，Python **761 项**通过（746 + 15）
- **性质**：这是**新增文件**，没有修改任何既有源文件或测试文件。因此本文的 "before" 是"该文件不存在"，"after" 是完整内容。

---

## 1. 三条实施前调整的落实

| 调整 | 落实 |
| --- | --- |
| ① Handler 不组装版本串 | `retrieval_mode` **只透传** `service.backend`；**不提供** `retrieval_version`；不硬编码任何版本字符串。设计文档新增 §0.1 记录核对结论 |
| ② 测试边界分开 | 只测 Handler：假定 `arguments` 已校验。**不测** validator、不测 Executor 端到端 —— 全部留给 Step 5 |
| ③ 不做静默丢尾条 | 取消 8 KiB 逻辑。预算 = `top_k=3` + 单条 800 字符 + Executor 既有 32768 B。设计文档 §0.3 写明"将来若加更小总预算必须显式标识裁剪（PARTIAL / truncated）" |

### 1.1 关键核对：`service.backend` 是 effective 还是 requested

实测（本机**未安装** sklearn）：

| 请求 `backend=` | 构造后 `service.backend` | `_index` |
| --- | --- | --- |
| `portable` | `'portable'` | `_PortableTfidf` |
| `sklearn` | **`'keyword'`** | `None`（走关键词回退） |
| `keyword` | `'keyword'` | `None` |
| 默认 | `'portable'` | `_PortableTfidf` |

结论：**`service.backend` 是 effective backend**（sklearn 缺失时构造期就地改写），可以安全地作为 `retrieval_mode` 透传给模型。

同时确认：`KnowledgeService` **没有** `retrieval_version`（只有 `source_version = "1.0"`，那是知识资源版本）。因此本步不提供该字段。

---

## 2. 新增文件：`src/fishery_ai/tools/handlers/knowledge_search.py`

**Before**：不存在。

**After**（完整内容）：

```python
"""Read-only project knowledge search; no model, no I/O, no second index."""

from ...knowledge import KnowledgeService


TOP_K = 3               # Fixed server-side budget; never a model-supplied parameter.
MAX_TEXT_CHARS = 800    # Per evidence text, counted in CHARACTERS (not UTF-8 bytes).
TRUNCATION_MARK = "\u2026"


def search_fishery_knowledge(arguments: dict, *, service: KnowledgeService) -> dict:
    """Map one validated query to bounded background evidence.
    ...
    """
    evidence = service.search(arguments["query"], top_k=TOP_K)
    items = [{"id": item.evidence_id, "category": item.category, "source": item.source_id,
              "source_version": item.source_version, "text": _bounded_text(item.text)}
             for item in evidence]
    return {"status": "OK" if items else "NO_MATCH",
            "retrieval_mode": service.backend,
            "result_count": len(items),
            "evidence": items}


def _bounded_text(text: str) -> str:
    """Truncate in characters. The longest live chunk is 415 chars / 844 bytes."""
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS] + TRUNCATION_MARK
```

设计要点回顾：

| 点 | 实现 |
| --- | --- |
| 调用形状 | `handler(arguments, *, service)` —— 位置参数是 Step 2 合同规定的已归一化 dict |
| 检索次数 | 恰好一次；不传 `retrieved_at` / `intent_text`（服务自身默认即可） |
| 固定预算 | `top_k=TOP_K`（3）写死，模型无法覆盖 |
| 结果键 | 外层 4 个键 + 每条证据 5 个键，多一个少一个都算合同破坏（测试锁定） |
| 不给模型 | `score`、`retrieved_at`、`source_title`、`retrieval_version` |
| 允许给模型 | `source`（`legacy:eel_knowledge.json`）—— 逻辑来源标识；禁止的是本机 filesystem path |
| 异常 | **不捕获** —— "没查到" 与 "检索坏了" 必须区分 |
| 截断 | 800 **字符** + `…`；只作用于 `text`，来源字段完整 |

---

## 3. 新增测试：`tests/test_knowledge_handler.py`（15 项）

| 测试 | 保护什么 |
| --- | --- |
| `test_service_is_called_once_with_the_query_and_no_extra_options` | 恰好 1 次调用；只传 query + top_k，**不传** `retrieved_at` / `intent_text` |
| `test_top_k_is_fixed_and_extra_keys_are_not_read` | 即使 arguments 里有 `top_k=9`，仍用 3（Handler 不读额外字段） |
| `test_evidence_maps_to_the_exact_declared_field_set` | 外层与证据的键集合、映射值 |
| `test_all_evidence_items_keep_the_same_shape` | 多条证据形状一致 |
| `test_no_match_when_nothing_qualifies` | 空结果 → `NO_MATCH`、`result_count=0`、形状不变 |
| `test_service_failure_propagates_and_is_never_reported_as_no_match` | 服务异常**向上传播**，不被吞成 NO_MATCH |
| `test_long_text_is_truncated_in_characters_and_keeps_its_source` | 1000 字符 → 800 + `…`；`id/source/source_version` 完整 |
| `test_text_within_the_limit_is_not_marked` | 恰好 800 字符**不**加标记（边界） |
| `test_payload_omits_internal_fields` | 无 `score` / `retrieved_at` / `source_title` / `retrieval_version` |
| `test_handler_generated_fields_are_logical_names_not_local_paths` | Handler 生成的字段无 `\`、无驱动器号 |
| `test_payload_is_accepted_by_the_tool_result_contract` | `ToolExecutionResult.from_payload()` 接受 OK 与 NO_MATCH；`error_code is None` |
| `test_retrieval_mode_is_the_effective_backend` | `portable/sklearn/keyword` 三种 backend 原样透传 |
| `test_retrieval_version_is_intentionally_absent_in_this_step` | 显式锁定"本步不提供该字段" |
| `test_untrusted_evidence_text_is_passed_through_as_data_only` | 含"忽略以上指令"的文本只是数据，payload 结构不变 |
| `test_handler_module_keeps_no_io_or_model_imports` | AST 扫描：该模块**零**绝对导入（不碰 `os`/`socket`/`json`/`openai`/`pathlib`） |

---

## 4. 真实服务冒烟（离线，未联网）

用真实 `KnowledgeService`（portable）直接调用 Handler：

| 查询 | status | mode | n | 结果 JSON 字节 | 命中 |
| --- | --- | --- | --- | --- | --- |
| 溶氧偏低怎么办 | `OK` | portable | 3 | 2165 | relationships, wq_dissolved_oxygen, wq_temperature |
| 车轮虫病有哪些症状 | `OK` | portable | 3 | 1929 | disease_车轮虫…, disease_气泡病…, disease_赤鳍病… |
| 投喂率怎么定 | `OK` | portable | 3 | 1012 | feeding_principles, feeding_freq, feeding_rate |
| `zzz 完全无关 zzz` | **`NO_MATCH`** | portable | 0 | 80 | — |

payload 键：`['evidence', 'result_count', 'retrieval_mode', 'status']` —— 与设计一致。

对照 Step 3 的实测：单条最长 415 字符 = 844 字节，从未触发 800 字符截断；实际最大结果 2165 B，远低于 Executor 的 32768 B 上限 —— 也印证了取消 8 KiB 逻辑是对的。

---

## 5. 明确没有做的事

- **没有**注册到 Registry（Step 5）、**没有** Catalog 条目（Step 6）
- **没有**改 Policy 默认；Knowledge 仍不被任何模式默认授权（Step 7）
- **没有**改 `web.py` 装配（Step 8）
- **没有**改 Assistant 提示词（Step 9）
- **没有**改 UI 工具名白名单与文案（Step 10）
- **没有**改 `tools/__init__.py`（是否导出由 Step 5 决定）
- **没有**解决 **D1**（`MockToolGateway` 的 `NO_DATA` 分支）—— 它仍是 **BLOCKER BEFORE KNOWLEDGE REGISTRATION**，最迟在 Step 5 之前处理
- **没有**触碰 `knowledge.py`（包括"给 Service 加 metadata"这件事，见第 6 节）

## 6. 后续项登记

| 编号 | 内容 | 触发条件 |
| --- | --- | --- |
| **K1** | `retrieval_version` 由 `KnowledgeService` 作为检索 metadata 提供（含参数指纹），Handler 纯透传 | RAG 研究重启时；**不在本步扩大范围** |
| **K2** | 若将来需要更小的 Handler 侧总预算，**必须显式标识裁剪**（`PARTIAL` 或 `truncated: true`），不得静默丢条后仍报完整 `OK` | 引入总量预算时 |
| **D1** | `tool_conversation.py` 的 `MockToolGateway` 会在 NO_MATCH 上 `KeyError` | **Step 5 注册之前必须解决** |

## 7. 测试证据（实测）

```text
tests.test_knowledge_handler   → Ran 15 tests  ... OK
unittest discover -s tests     → Ran 761 tests in 82.018s ... OK
```

## 8. 回滚

本步只**新增两个文件**，未修改任何既有文件；删除这两个文件即可完全回滚。

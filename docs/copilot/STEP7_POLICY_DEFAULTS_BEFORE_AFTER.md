# Step 7 对照记录：Policy 默认与旧 override 兼容（验证完成，**无产品代码改动**）

> 结论：**Step 7 不需要修改任何产品代码。** 4 条要求已由现有设计满足，本轮只补了 2 条回归保护测试。
> 验证：`unittest discover -s tests` → **808 项通过**（806 → +2，全部为本步新增）。

---

## 1. 核对结果

| # | 要求 | 静态核对 | 实证探针 | 结论 |
| --- | --- | --- | --- | --- |
| 1 | Analysis 默认不新增 Knowledge | ✓ | `load_tool_policies()["analysis"].exposed_tools == ()`，`llm_tool_calling is False` | 已满足 |
| 2 | Assistant 默认不新增 Knowledge | ✓ | `load_tool_policies()["assistant"].exposed_tools == ('get_current_water_quality',)`（**精确相等**） | 已满足 |
| 3 | 旧 override 不自动迁移 | ✓ | `load()`/`effective()`/`public()` 及"重启"后，文件**字节与 mtime 均不变**；读回值 = 文件原值 | 已满足 |
| 4 | 新注册 Tool 不自动进入 `exposed_tools` | ✓ | 同一 override 配"未绑定/已绑定 Knowledge"的 Registry → 两模式 `exposed_tools` 完全相同 | 已满足 |

包内 `resources/tools/tool_policies.json` 全文不含 `search_fishery_knowledge`：`analysis` = `llm_tool_calling: false` / `[]`；`assistant` = `true` / `["get_current_water_quality"]`。

## 2. 为什么已经满足（结构性原因，非巧合）

1. **`exposed_tools` 只有两个来源**：包内 JSON 与用户 override 文件。**没有任何路径从 Registry 生成它。** `registered_names()` 的 4 处消费者全是白名单过滤（`assistant.py:182`、`observability.py:75` 输出脱敏；`policy.py:64` 名称存在性校验；`registry.py:35` 定义本身）。
2. `default_selections()` 只从 `self.defaults`（包内文件）派生，**不接触 registry**。
3. `load()` 命中文件即**原样返回**：没有 merge / 补齐缺失项 / 版本迁移分支；`schema_version` 只做 `== 1` 断言。当前代码**不存在**任何 schema 迁移路径（不兼容版本是拒绝，不是静默改写）。
4. 新注册工具只让 Catalog 的 `executable` 集合变大 —— 那是**可选上限**的扩大，授权仍需显式 `save()`。实测：显式保存含 Knowledge 的选择后 `effective()` 才变为 `('get_current_water_quality', 'search_fishery_knowledge')`；`reset()` 后回到 `('get_current_water_quality',)`。

## 3. 新增的 2 条回归保护（`tests/test_tool_policy_manager.py`）

| 测试 | 锁住什么 | 为什么原有测试不够 |
| --- | --- | --- |
| `test_reading_an_override_never_rewrites_the_file` | `load()`/`effective()`/`public()` 以及"重启"（新 store 实例）之后，文件 `(st_ino, st_size, st_mtime_ns, st_ctime_ns)` 与 bytes 完全不变 | 原有断言只看**解析后的值**：若有人在 `load()` 里加"补齐缺失字段"，读回的值仍正确，**测试发现不了** |
| `test_binding_a_new_tool_never_changes_an_existing_override` | 同一 override 文件，Registry 从"未绑定 Knowledge"变为"已绑定 Knowledge"后，两模式 `exposed_tools` 与文件内容都不变 | 原有用例的 Registry **全部未绑定** Knowledge，该场景从未被执行 |

两条都刻意加了**防空过**断言：第 2 条先断言两个 Registry 的 `model_definitions()` 真的不同（一个含 Knowledge、一个不含），否则该用例可能在"两个 Registry 其实一样"时假通过。

**仍然不证明**：不证明 UI 层、不证明真实模型行为、不证明检索质量；零网络、零真实请求。

## 4. 实证发现：fail-closed 矩阵

| 场景 | 结果 |
| --- | --- |
| 已绑定 Knowledge 的实例 + override 选了 Knowledge | 保存成功，`effective()` = `('search_fishery_knowledge',)` |
| **未绑定** Knowledge 的实例 + 同一 override | **启动即失败**，错误码 `UNKNOWN_POLICY_TOOL`（不是 `TOOL_NOT_EXECUTABLE`，因为 `lookup()` 先失败） |
| 上述两种情况下文件 | **完好无损**，不回退、不清空、不改写 |
| 损坏的 override（非法 JSON） | 启动失败 `TOOL_POLICY_STORAGE_ERROR`，**文件保持原样**（不静默用默认值覆盖） |

这是"fail closed + 不破坏用户数据"的正确组合，但意味着 **Step 8 必须核对所有 `ToolRegistry(...)` 构造入口的绑定一致性**：某个入口不绑定 Knowledge，而用户已保存含 Knowledge 的 override，该入口就会启动失败。这为计划里 Step 8 的"核对所有构造入口"提供了具体机制上的理由。

## 5. 本步「不做」清单（刻意）

不改 `tools/policy.py`、不改 `resources/tools/tool_policies.json`、不改 `web.py`、不改 `tools/catalog.py`、不改 `app.js`、不新增 `modes` 映射、不新增错误码、不实现"仅 Assistant"服务端硬边界（该议题仍按决定暂缓为独立架构议题）。

`modes` 的单一权威来源继续留在 `tools/catalog.py`。

## 6. 验证命令

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_tool_policy_manager -v   # 21 项通过
.\.venv\Scripts\python.exe -B -m unittest discover -s tests                    # 808 项通过
```

## 7. 教训

1. **"值不变"不等于"文件不变"。** 断言读回的值无法发现"读了但顺手重写"的副作用；只有文件指纹能发现。
2. **回归测试要防空过。** 第 2 条若不断言两个 Registry 确有差异，就可能在装配错误时依然通过。
3. **核对结论要写进文档，否则只存在于对话里。** 本次 4 条要求的证据（含未绑定/已绑定的对照）若不落盘，Step 8 会重新问一遍同样的问题。

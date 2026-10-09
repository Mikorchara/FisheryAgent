# Step 8 对照记录：装配——真实 Runtime 注入共享 KnowledgeService（before / after）

> 范围：**只改 `web.py` 一行的装配**。不改 Registry 定义、不改 Policy 语义与默认值、不改 Catalog、不改 `composition.py` / `real_validation.py` / qualification / 无关测试 registry、不改 UI。
> 验证：`unittest discover -s tests` → **815 项通过**（808 → +7）；`node --test tests/test_browser_streaming.cjs` → **183 项通过**。

---

## 0. 本步做什么

把 `create_app()` 里**已经存在**的那一份 `KnowledgeService` 注入 `ToolRegistry`，使 Knowledge Tool 在真实应用中从"已注册但不可执行"变为**可执行**（用户可勾选）。**不新建第二份服务实例。**

## 1. before / after

### 1.1 `src/fishery_ai/web.py`

| | 内容 |
| --- | --- |
| **before** | `tool_registry = ToolRegistry(current_reader, diagnosis)` |
| **after** | `tool_registry = ToolRegistry(current_reader, diagnosis, knowledge=knowledge)` |

并补了 3 行注释说明两件事：① 这一份服务同时服务 Analysis 路径与只读 Tool；② **绑定顺序是承载语义的**。

`git diff --stat` = `1 file changed, 4 insertions(+), 1 deletion(-)`。**产品代码净改动 = 1 行 + 3 行注释。**

### 1.2 顺序（无需移动任何行，但被测试锁定）

```
228  knowledge = KnowledgeService(...)      ← 已存在，唯一实例
238  tool_registry = ToolRegistry(..., knowledge=knowledge)   ← 本步
240-241  load_tool_policies() + validate_registry             ← 未动
243  policy_store = UserToolPolicyStore(..., tool_registry)   ← 未动
```

`knowledge`(228) → `registry`(238) → 默认校验 → `store`(243) 天然正确。**为什么顺序是承载语义的**：store 构造时用 Catalog 的 `executable` 集合与 `lookup()` 校验已存 override。若先建 store 再绑定，用户已保存过 Knowledge 选择的实例会**启动即失败**（Step 7 实测为 `UNKNOWN_POLICY_TOOL`）。因此本步把顺序写成注释，并用测试锁定（§3 第 2 条）。

## 2. 实测的装配效果

| 观察点 | before | after |
| --- | --- | --- |
| `create_app()` 构造 `KnowledgeService` 次数 | 1 | **1**（未变，本步不新增构造） |
| handler 持有的 service | —（未绑定） | **`is` 那一个实例**（同一对象，非副本） |
| Catalog 中 Knowledge 行 `registered` / `executable` | `True` / **`False`** | `True` / **`True`** |
| 用户能否在 Tool Manager 勾选 | 否（前端 `!item.registered` 禁用） | **是** |
| 包内默认 Policy | 不授权 | **不授权**（未改） |
| 未注入场景（其余入口） | 不受影响 | **不受影响** |

**本步对既有行为的唯一可见变化**：真实应用的 `/api/tool-policies` 中，Knowledge 行变为可勾选。

## 3. 新增测试 `tests/test_knowledge_assembly.py`（7 项）

| # | 测试 | 证明什么 |
| --- | --- | --- |
| 1 | `test_application_builds_exactly_one_shared_service` | `create_app` 期间 `KnowledgeService` 只被构造 **1** 次；且已绑定 handler 持有的 service **`is`** 该实例（**全仓库唯一一处** `functools.partial` 形状断言） |
| 2 | `test_policy_store_and_http_surface_share_one_registry` | 经 HTTP 得到的 catalog 与经 `store.registry` 得到的 catalog **逐项一致** → store 校验用的 registry **就是**路由实际执行的 registry（锁定绑定/构造顺序） |
| 3 | `test_no_second_service_is_constructed_in_the_package` | AST 扫描 `src/fishery_ai/**/*.py`：`KnowledgeService(...)` **调用**只出现在 3 个 composition root（`web.py` / `composition.py` / `real_validation.py`）且各 1 次 |
| 4 | `test_real_runtime_marks_the_knowledge_tool_executable` | 真实 Runtime 的 Knowledge 行为 `registered=True, executable=True, dev_only=False, READ ONLY`；两个水质工具仍可执行 |
| 5 | `test_defaults_still_authorize_nothing_new` | `policy.source == BUILTIN_DEFAULT`；assistant 仍只 `[水质查询]`、analysis 仍 `[]`；`allows(Knowledge)` 两模式均 `False`；**未创建 override 文件** |
| 6 | `test_user_opt_in_and_reset_round_trip` | 经 HTTP `PUT` 保存含 Knowledge 的 override → 200 且 `effective()` 生效；`GET` 报 `USER_OVERRIDE`；`DELETE {}` 复位且文件消失 |
| 7 | `test_restart_keeps_the_saved_opt_in` | 重启（第二次 `create_app`）后选择仍生效、**文件字节不变**、catalog 三项均可执行 |

### 3.1 关于 `functools.partial` 的边界（按你的要求）

只保留**一条**装配身份断言：`handler.keywords["service"] is <唯一实例>`。**没有**进一步断言 `handler.func`、`handler.args`、参数名以外的 partial 形状，也没有在其他测试里重复这种依赖。将来若改变绑定实现（例如换成一个闭包工厂），**只需要改这一条断言**。

### 3.2 空过检查（mutation check，实测）

把 `knowledge=knowledge` 临时移除后重跑本模块：**3 failures + 2 errors**，全部落在依赖绑定的用例上（`executable` 变 `False`、identity 取不到、PUT 返回 400）。随后已还原（`git diff --stat` 复核为 `4 insertions(+), 1 deletion(-)`），全量重跑 815 OK。→ 这些测试**确实对装配敏感**，不是空过。

### 3.3 这些测试**不**证明什么

- 不证明检索质量：本模块**没有**调用 `search()`，只验证装配、可执行性与授权门禁。
- 不证明模型会选择该工具（Step 9 提示词 + Step 11 人工验收）。
- 不证明 UI 渲染正确（前端由既有 mock fixture 覆盖，本步未加前端断言）。
- 零真实模型请求、零网络（`setUp` 中 patch `socket.*`；`real_gateway_factory` 为"一调用就报错"的 Mock）。

## 4. 既有测试的改动：**0**

预期零改动，实跑确认为零。最容易受影响的断言逐条核对过：

| 断言 | 为什么不受影响 |
| --- | --- |
| `test_tool_policy_manager.py:52`（catalog 可执行名单） | 用的是该文件**自有未绑定** registry，不是 app 的 |
| `test_assistant.py:406`、`test_water_quality_scoring.py:105` | 同上，自有 registry |
| `test_web_returns_catalog_and_no_profile_or_secret` | 断言的是**名称列表**，不是可执行集合 |
| 28 个测试文件的 35 处 `create_app(...)` | 每个 app 都构造一份 `KnowledgeService` —— **本步之前就已如此**，本步不增加任何构造成本 |

## 5. 遗留登记（更新）

| # | 项目 | 状态与本步关系 |
| --- | --- | --- |
| **D1b** | `tool_conversation.py` `MockToolGateway` **Request #1** 的 `request.tools[0]` fallback | **仍未解决。** Step 8 后 Knowledge 已在真实 Runtime 中 **executable**，即用户"已可勾选"；但 **D1b 必须在 Mock Knowledge 的人工使用/验收之前解决**：若策略只授权 Knowledge 而用户问"现在水质怎么样"，fallback 会以 `"{}"` 调 Knowledge 并被 validator 拒（`INVALID_TOOL_ARGUMENTS`）。**这是进入 Step 11（人工验收）的阻塞项。** |
| **U1** | `app.js` 徽章忽略 `registered`/`executable`，对未注册的非 dev_only 行会谎报 "Registered / Executable" | 本步之后**真实应用中该行确实可执行**，所以 U1 在真实应用里不再显现；但"某入口未绑定"的场景仍会谎报 → 仍归 Step 10 |
| **U2** | UI"适用模式"与后端 `item["modes"]` 双来源 | 未变，归 Step 10 |
| **K1** | `KnowledgeService` 缺 `retrieval_version` | 未变 |
| **K2** | Handler 侧若引入总量预算必须显式（`PARTIAL` / `truncated`） | 未变 |
| **B6** | `web.py` 中 `"arguments"` 字段对带参工具不准确 | 未变；本步后该字段首次可能被带参工具触及 → 建议在 Step 10/11 一并核对 |

## 6. 验证命令与结果

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_knowledge_assembly -v   # 7 项通过
.\.venv\Scripts\python.exe -B -m unittest discover -s tests                   # 815 项通过
node --test tests/test_browser_streaming.cjs                                  # 183 项通过
```

## 7. 教训

1. **"只有一个实例"要用身份断言，不要用数量断言。** `call_count == 1` 只能证明构造了一次；`handler...is instance` 才能证明**消费者拿到的是同一个**。
2. **装配顺序在"校验型初始化"里是语义，不是风格。** store 在构造时校验 override，所以"先绑定后建 store"必须写进注释并由测试锁定，否则将来一次无害的重排就会让老用户启动失败。
3. **产品代码改一行，测试要能证明这一行有用。** mutation check 用一次临时删除换来了"这些测试确实敏感"的事实，成本极低。
4. **扫描型结构断言要按相对路径记账**，不能用文件名：同名文件在不同子目录会让断言静默漏判。

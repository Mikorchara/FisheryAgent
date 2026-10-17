# R2D-1F：历史 Tool 工程成本与批量验收准备

状态：离线准备完成；本轮真实请求 **0**。历史 Web 仍为 candidate / 默认关闭，未获得 local_experimental。本文只提出架构简化建议，不实施架构重构。

## 1. 统计口径与结论

审计基线是本轮开始时的 HEAD `d72420c`（Tool 模块化）到工作树，不包含 R2D-1F 自身新增代码。R2D-1B～1E 尚未逐阶段提交，因此 Git 无法精确还原每阶段行数；下面按实际文件主职责做互斥归类，不能将一个文件的每行强行归因于某个阶段。

- **39 个文件：23 个修改、16 个新增；+3575 / -98 行，净增 3477 行。**
- 其中可执行代码、配置、测试为 32 文件 +3272 / -34；文档为 7 文件 +303 / -64。这里的“行”是物理文本行，包含注释/空行/JSON，不冒充可执行语句数。
- 测试/夹具/测试入口占新增行 1805/3575（约 50.5%），不能把全部新增量当成运行时复杂度。
- 另有先行研究 `R2D1A_WATER_HISTORY_TOOL_DESIGN.md` 312 行；不计入 1B～1E。若把它也计入当前未提交历史主题，总计 40 文件 +3887 / -98。
- 没有删除文件；未读取真实 SQLite、用户 Policy 或凭据。既有未提交文件全部保留。

| 主职责 | 文件数 | 新增 / 删除行 |
|---|---|---|
| Monitoring 业务能力 | 3（新增 1） | +323 / -1 |
| Tool Definition / Handler / Registry | 2（新增 1） | +158 / -4 |
| 权限、来源与管理设置 UI | 12（新增 2） | +393 / -24 |
| 候选发布配置 | 2（新增 2） | +137 / -0 |
| 测试、夹具与测试入口 | 9（新增 7） | +1805 / -2 |
| 资格工具 | 4（新增 2） | +456 / -3 |
| 文档 | 7（新增 1） | +303 / -64 |

**判断：工程量偏大，但主要是业务基础和首次授权/资格设施，不是一个 Handler 本身需要三千多行。** 后续简单 Tool 不应再重复建立历史统计、Policy 存储、设置 API 和一整套资格执行骨架。当前不存在第二套 ToolCallingService / Executor；真正可减少的是显式名单、展示元数据和资格外围的重复维护。

## 2. 哪些成本应保留

| 成本 | 必要性与实际理由 |
|---|---|
| 真实时间范围 SQL、720+1 有界读取、完整窗口、质量/覆盖/Session/重叠统计 | 必需的 Monitoring 业务能力。旧 history(limit) 只有最后 N 条，不能回答过去30分钟；缺口/无效数据不能填正常值 |
| 严格 Schema / validator、设备绑定、Handler 单次委托 | 必需；模型不能选设备、注入额外参数或自行计算权威统计 |
| Receipt 区分“查询完成”和“存在可靠历史证据” | 必需；NO_DATA 可合法完成操作，但历史不得满足 CURRENT_OBSERVATION |
| Registry / Policy / 发布 Scope 三道独立校验 | 必需；可装配、用户授权、维护者发布不是同一权限，不能合成一个自动开放开关 |
| Trace / Stop / Deadline / Commit Gate 回归 | 必需；失败不提交、真实执行才产生来源仍是硬合同 |
| 管理专用 Policy 文件、只读继承、CAS/原子写/锁 | 首次基础设施，保护旧 Prototype 和用户选择；之后新增名字复用同一设施，不再新建 Policy Store/API |
| 历史候选 Scope、正式/逐 Turn Registry 一致性 | 必需的本次隔离；不应让第三 Tool 改写已批准两工具范围 |
| 三个夹具、SDK 安全观察、单案例 CLI | 首次 Normal 历史资格设施，可复用；不是生产查询路径的一部分 |
| 对原两工具六路径与三计划的黄金基线 | 有价值的迁移防回归证据；不因新功能失败而重写基线 |

`water_quality_history.py::result_metadata()` 对 Monitoring DTO 再验证是来源认证边界，不是重新统计。它同时用于 Receipt 和 Activity，会重复遍历有限 payload；目前最多24 KiB，没有证据表明这是主要耗时，不值得先加缓存或改执行生命周期。

## 3. 重复维护与可衡量的简化建议

### 3.1 工具名称的维护点

正式运行侧有 **9 个 Python/JS 文件**直接引用历史 Tool owner/名称：business_tools 的 owner、registry；management_policy；history_execution；service；runtime 的 sources/activity/catalog；前端 tool-policy.js。另有候选 JSON，开发资格代码和测试不属于产品执行。

- Registry 负责定义/Handler，Policy 负责已知可存储名称，Scope 负责精确发布集合：语义不同，保留分离。
- Service 的 Trace allowlist 已复用 `HISTORY_CANDIDATE_TOOL_NAMES`，通用 Backend **没有新增硬编码历史名称**。
- Catalog 与前端 labels 都保存显示名称；前端额外硬编码“恰好4个工具”和名单，确实增加每个 Tool 的维护成本。
- sources 的显式工具认证分支必需；不能从 Registry 自动推断“执行即拥有所有来源”。
- history_execution、JSON、资格 plan 对预算重复核验是防漂移；但常量不应多处手工填写。1F 已让历史 token ceiling 由 history_execution 唯一拥有，资格引用；JSON 是受测发布快照。

### 3.2 现在值得做／下次接入前的小改进（本轮仅建议）

1. **展示名单集中到服务端 Catalog。** 设置 API 返回有界 name/label/状态；前端用 textContent 展示，校验数组上限、唯一性和字段类型，取消“恰好4个”和另一份 labels。验收目标：下一 Tool 不再修改 tool-policy.js 及其固定数量断言；服务器权限检查完全保留。
2. **沿用单一管理授权设施。** 下一 Tool 只扩管理已知名单，不新增 Policy Store、文件格式、保存路由或独立权限 UI。验收目标：新增 Policy 文件/API 数量均为0。
3. **资格外围只抽实际重复步骤。** history 与 streaming 的计划核对、临时装配、报告收尾/人工预览有相似代码。下次需要第三个资格入口时，先提炼这几项 helper，保留具体案例、Scope 和来源断言；不重写 Runtime、不建通用实验平台。验收目标：新入口不再复制整段 run()。
4. **合并操作说明。** 当前 INTEGRATION、BUILD_RUN 和资格指南有阶段性重复。BUILD_RUN 只留入口链接，操作步骤由 HISTORY_QUALIFICATION 维护；一次审核可批准固定15样本，不再为每个样本单独做研究阶段。
5. **共享测试 fixture/helper，按层运行。** 统计边界测 Monitoring；参数/Receipt 测业务 Tool；HTTP 测装配；旧六路径只保留一份完整基线。不要把每个统计边界再次放进所有 HTTP/Provider 测试。

### 3.3 以后再考虑

- 工具达到约6～8个、出现多处相同装配分支后，再考虑小型静态业务描述表；不得用动态扫描或自动授权替代显式 Registry。
- 不先引入通用来源推断引擎、插件系统、Agent、数据库迁移框架或大规模 Source 类型重写。
- 不为缩短文件数合并 Registry/Policy/Receipt/发布门禁。关闭安全合同不会解决业务统计和测试的真实成本。

## 4. 下一简单只读 Tool 的最小路径

假设已有稳定的领域读取服务，不增加统计引擎或存储：

1. **仅可离线执行并认证来源：约4个文件。** 新 business_tools/<name>.py；registry.py 显式装配；runtime/sources.py 明确认证；一个集中测试文件。不需要每 Tool 修改通用 Backend、Executor、Prompt、Adapter。
2. **管理授权/安全展示：再涉及5个实现点。** management_policy.py、catalog.py、activity.py（仅新增专用摘要时）、service.py 的可用项/受控候选分支、当前前端 tool-policy.js。补管理/前端合同测试与一处开发指南。现在并非“一文件即接入”；第3节建议可去掉前端逐 Tool 修改。
3. **真实模型候选/试用：再绑定精确 Scope 配置与计划。** 复用统一批准、报告和 CLI 骨架；不重复创建 Policy/UI/HTTP 基础设施，不沿用不匹配的资格。实际文件数随新来源能力/发布组合变化，不能承诺固定值。
4. 如果没有领域读取能力，先把那部分列为业务服务成本；历史 Tool 的 Monitoring 323新增行及对应统计测试不应再次成为每个 Tool 的固定模板。

本轮未实施上述清理；只修改明确获批的历史资格预算和固定批次准备。

## 5. 1024-token 新候选

- `water_history_candidate@2`，`management-history-qualification@2`；旧256计划失效。
- Qwen `dashscope-qwen38-flash-r1` / OFF / Normal，只暴露历史 Tool；1/1/2，retry=0，120秒，candidate/关闭。
- Scope budget 显式绑定1024；资格 Adapter 通过原 ProtocolSpec 编码 **max_tokens=1024**，两次请求均由 Fake SDK 验证。
- Profile 的 default_generation.max_output_tokens 为 None；max_output_tokens capability 为 UNKNOWN。1024是批准的资格成本上限，不是伪造 Provider Capability。计划记录默认值，继承原 Normal 编码后写入批准预算；原 Normal 省略stream字段。
- 原通用 Normal qualification 仍上限256、Streaming qualification 仍512；只在历史专用 Adapter 使用1024校验，构造及实际编码前均拒绝 bool/float/string/越界。
- Scope SHA256：`765f109a71a4ea8b338cd938ded3a7a16a60cf02f00b17e5ab3cff502dcda97d`。
- 配置 SHA256：`153631bcf857db1015b0244048aa83726460ff5f28c0410a7587938c58e1992b`。
- 原两工具配置文件 SHA256 未变，原六条HTTP行为和三份计划基线测试通过；不更新旧黄金文件。

## 6. 一次性固定15样本计划

详见 [操作指南](../HISTORY_QUALIFICATION.md#7-r2d-1f固定15样本批次)。单案例 CLI 不改为批处理器；薄 [批次脚本](../../../../scripts/qualification/qualify_management_history_batch.py) 每次启动一个独立单案例子进程。

| case | 新 plan_sha256 | 独立 Turn | 最多请求 |
|---|---|---|---|
| valid-history | `a422db6965dac29cfcbeca3805fa5ef4b4d8de417ade72543e312f6d12b2f7e5` | 5 | 10 |
| no-data | `91fbd13859b1cdfeb7669f8cf7f7ea182cc2c2db08009ed53a6d580a92699c39` | 5 | 10 |
| partial-history | `bcd3755ad3ddd6596a2ba0f836c1d2c2aa2b4fcc18580ff796d77d948cd04305` | 5 | 10 |

每轮固定顺序为 valid-history → no-data → partial-history，重复5轮（索引1～15），不随机、不自适应追加。每 Turn 最多2模型请求，总上限30；按请求cap计算输出总上限30720 tokens，非费用或实际消耗估计。每次独立临时 SQLite/Policy/Handle/Runtime，Question/fixture/Schema/Prompt/History 不随结果调整。

- 普通 no-tool、参数错误、Provider错误、截断等保留失败样本，继续固定下一项，不重试该项。
- 凭据/零请求预检、取消、未知退出码、损坏/不匹配报告或无法确认请求数时停止；保留已生成样本，不能假设未知为0，也没有自动恢复/从头重跑。
- 汇总仅引用本批新报告，按case记录真实样本分母（actual_network_requests>0）、选择/参数/查询完成/SourceGate/产品提交/技术通过/截断、业务状态、错误、延迟及Usage。未知Usage保留None/观测数量，不补成已知0。
- NO_DATA/PARTIAL/OK 都可合法完成历史查询；技术资格仍核对所选范围、真实Result传递及对应固定夹具。不分析模型正文判定技术成功。
- 每个子报告和批次汇总都独占创建，不覆盖历史。Ctrl+C/异常中止可能留下无法确认消耗的当前子样本，应先本地盘点，再另行授权剩余顺序。
- 可选终端回答预览不保存，不等于人工通过；未改变自动发布资格。此处没有实际15样本结果。

## 7. 技术通过后的最短本地开放路径

下一轮获批后直接实施，不另开大型研究：

1. 在现有 history_execution/config 上增加维护者默认关闭的启动开关（如 --assistant-history-trial）与local_experimental状态；仍精确绑定Qwen OFF/Normal/H单工具、1024、1/1/2/120秒/来源和定义版本。技术批次只作证据引用，不伪造人工审核或released。
2. 将 history-only profile 接入现有页面受控选择及网络确认，使用其独立revision。当前前端从不发送 execution_profile，仅把JSON status改掉不会使历史对话可用；授权、维护者许可和模式必须分别通过。
3. **补实际Normal产品预算编码。** 现有Service仅在Streaming设置 transport_output_token_limit，Backend该字段也只接受Streaming≤512；不能直接把1024塞给它。下一轮需在应用层复用现有Adapter编码入口建立受Scope约束的Normal预算投影（不导入development Adapter、不改通用执行循环），Fake SDK证明实际max_tokens=1024。当前资格专用Adapter已验证这一编码；Web目前仍关闭，未声称产品预算已生效。
4. 复用设置区历史 opt-in、冻结设备/Policy、确认、Stop、History与提交；拒绝其他Provider、Streaming或多工具组合。保持原两工具默认路径与资格独立。
5. 跑历史HTTP/Fake SDK预算及原六路径回归；去掉开关并重启即可回滚。已执行失败不回退Normal重跑。

## 8. 本轮离线验证与边界

- 历史资格/批次已纳入完整离线qualification层：213项，212通过、1项本机符号链接限制跳过，37.739秒。
- History Tool / candidate HTTP / 管理Policy：38项通过，7.497秒；含原两工具六路径和三资格指纹比较。
- FAST：164项通过，1.393秒。以上测试层有重叠，不相加为唯一测试数。
- 三个正式单案例CLI Dry-run与固定批次Dry-run：零真实请求，无凭据预检/报告写入；尚未批准或执行批量真实请求。
- Python AST 26文件、JSON 2文件通过；43个改动文本文件无行尾空白。apps的19份Markdown共275条本地链接、36个锚点检查通过，无broken local links；git diff --check通过。
- 43个工作树改动文件的API Key/Bearer/private-key模式扫描无命中（模式扫描不是无泄漏的绝对证明）；原两工具两份配置字节hash不变。未运行无关全量产品或历史真实实验。

## 附：逐文件基线清单

M为tracked修改，A为untracked新文件。新增文件按全部物理行计；修改文件采用git diff --numstat。横跨职责的文件仅归一类，故类别不表示逐行语义归属。

### Monitoring 业务能力

```text
M + 35 / - 1  apps/monitoring/repository.py
M +  9 / - 0  apps/monitoring/service.py
A +279 / - 0  apps/monitoring/history.py
```

### Tool Definition / Handler / Registry

```text
M + 20 / - 4  apps/ai_service/business_tools/registry.py
A +138 / - 0  apps/ai_service/business_tools/water_quality_history.py
```

### 权限、来源与管理设置 UI

```text
M +  4 / - 0  apps/ai_service/contracts.py
M + 17 / - 2  apps/ai_service/runtime/activity.py
M +  6 / - 0  apps/ai_service/runtime/catalog.py
M + 58 / - 4  apps/ai_service/runtime/sources.py
M + 70 / -14  apps/ai_service/service.py
M +  7 / - 1  apps/management_web/ai_adapter.py
M +  9 / - 0  apps/management_web/app.py
M +  4 / - 2  apps/management_web/static/app.js
M +  3 / - 1  apps/management_web/static/assistant.js
M +  2 / - 0  apps/management_web/static/services.js
A +167 / - 0  apps/ai_service/management_policy.py
A + 46 / - 0  apps/management_web/static/tool-policy.js
```

### 候选发布配置

```text
A + 78 / - 0  apps/ai_service/history_execution.py
A + 59 / - 0  apps/ai_service/resources/water_history_candidate.json
```

### 测试、夹具与测试入口

```text
M +  4 / - 1  apps/management_web/tests/monitoring-ui.test.mjs
M +  3 / - 1  scripts/dev/run_tests.py
A +156 / - 0  apps/ai_service/tests/fixtures/r2d1c_two_tools.json
A +269 / - 0  apps/ai_service/tests/test_history_candidate.py
A +338 / - 0  apps/ai_service/tests/test_history_qualification.py
A + 97 / - 0  apps/ai_service/tests/test_management_policy.py
A +389 / - 0  apps/ai_service/tests/test_water_history_tool.py
A + 63 / - 0  apps/management_web/tests/tool-policy.test.mjs
A +486 / - 0  apps/monitoring/tests/test_water_history.py
```

### 资格工具

```text
M +  1 / - 1  apps/ai_service/development/qualification_adapter.py
M +  2 / - 2  apps/ai_service/development/qualification_support.py
A +391 / - 0  apps/ai_service/development/history_qualification.py
A + 62 / - 0  scripts/qualification/qualify_management_history.py
```

### 文档

```text
M +  3 / - 1  apps/ai_service/runtime/README.md
M + 41 / -54  apps/docs/AI_BACKEND_DEVELOPMENT_GUIDE.md
M + 31 / - 0  apps/docs/BUILD_RUN.md
M +100 / - 1  apps/docs/INTEGRATION.md
M +  2 / - 1  apps/docs/README.md
M + 25 / - 7  apps/docs/STRUCTURE.md
A +101 / - 0  apps/docs/deep-dive/HISTORY_QUALIFICATION.md
```


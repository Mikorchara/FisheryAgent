# P1 / P1.1：Assistant Turn Source Contract / Receipt Foundation

日期：2026-10-09；基线 `81c050e`。本阶段是内部来源合同实施记录，不替代源码；依据[History / Tool Reliability 研究](2026-10-assistant-history-tool-reliability-study.md)。开始时该研究报告已为 untracked，本轮保留原文。

P1.1 合同收口日期：2026-10-10。以下合同与矩阵已更新为最终操作语义；原 P1 把观测 / 评分的“取得结果”与检索的“完成操作”混用，现已修正。未进入 Qualification Harness。

## 1. Before / After

| 项目 | Before | After |
| --- | --- | --- |
| 来源判断 | 只有执行结果和展示 Activity，没有统一满足关系 | 从实际执行结果生成有限 TurnSourceReceipt，分别认证操作完成与实际取得来源 |
| 产品请求 | 首轮 auto，模型可直答 / 调一个 Tool | 完全保留；Web 不接收 SourceRequirement / Receipt，默认 AUTO |
| 内部非 AUTO 请求 | 没有来源提交门禁 | 所需操作未合法完成返回 ASSISTANT_SOURCE_REQUIREMENT_UNMET；successful_turn=false，正文为空、completed_at=null |
| 模仿调用正文 | 没有协议调用则不执行 Tool，但正常正文仍可成功 | Receipt 必为空；AUTO 行为保留，内部非 AUTO 要求不能被模仿文本满足 |
| Score 的双来源 | payload 有 score 与 water_quality，缺少统一判断 | 依据实际 status、canonical reading 与有限评分字段校验分别授予来源 |
| Knowledge NO_MATCH | 合法 Tool 状态 | 明确“完成检索”为 true，“有 Evidence”为 false，count=0 |
| P1.1 负向业务结果 | 原 P1 查询 NO_DATA、评分 NOT_SCORABLE / NO_DATA 无法满足相应要求 | 合法完成查询 / 评分即可满足操作要求；观测 / 评分存在性仍独立且如实为空 |
| UI / History / Prompt | 页面成功 pair、既有标签与指令 | 未修改，不增加 Requirement UI 或 Receipt 展示 |

本阶段不能宣称已阻止 AUTO 正文虚构查询 / 评分 / 检索。AUTO 无 Tool 仍可以提交正常正文，这是本轮明确保留的行为；Receipt 只如实证明本轮获得的来源。

## 2. 先设计，再实现的最小合同

新增 [assistant_sources.py](../../../../src/fishery_ai/assistant_sources.py)，仅包含来源类型、不可变 Receipt、派生函数和纯满足函数；不执行 Tool，不读取 Store，不调用模型，不解析自然语言。

### SourceRequirement

- AUTO：不要求系统来源，概念回答无需 Tool。
- CURRENT_OBSERVATION_QUERY：需要本轮合法完成当前观测查询；NO_DATA 可以满足，并不承诺 Snapshot 或具体测量字段存在。
- CURRENT_SCORE_EVALUATION：需要本轮合法完成当前评分评估；OK / PARTIAL / NOT_SCORABLE / NO_DATA 可以满足，并不承诺存在评分。
- PROJECT_KNOWLEDGE_SEARCH：需要本轮合法完成项目知识检索；OK / NO_MATCH 可以满足，证据命中单独表达。

旧内部枚举 CURRENT_OBSERVATION / CURRENT_SCORE / PROJECT_EVIDENCE 已重命名，不保留含混别名；它们没有 Web / 持久化消费者。Requirement 表示必须完成哪类操作，TurnSource 表示实际得到什么内容，两者不共用枚举。

EXACT_TOOL 暂不发布。当前没有自然语言 Router，也不根据问题文本设置非 AUTO。内部测试可通过 `AssistantRequest(source_requirement=...)` 指定；`from_dict()` 的 Web 输入白名单不允许这个字段，History 同样不能回传 Receipt。

### TurnSourceReceipt

有限来源集合：CURRENT_TOOL_OBSERVATION、CURRENT_TOOL_SCORE、RETRIEVED_PROJECT_EVIDENCE。空集合表示 NONE，不代表所有空集合都没有执行过 Tool。

只保留：固定 Tool 名、Tool status、quality、freshness、observed_at / evaluated_at、可用字段名、observation_query_completed、score_evaluation_completed、project_search_completed、evidence_count。has_observation / has_score / has_project_evidence 是来源集合的只读派生属性。没有读数、分数、等级、Findings 正文、query、Evidence 文本 / ID / source、Prompt、Credential 或私有路径。

`sources` 是 frozenset，字段名集合冻结为 tuple；Receipt 与原始结果脱离。`to_dict()` 提供有限 JSON 摘要，供内部测试和将来资格验证使用；没有加入 Assistant Web JSON、Development UI 或新 Trace 字段。

Receipt 与本次 AssistantResult 关联，生命周期仅本轮。它不是可由浏览器提交的授权令牌，也不是签名证书；本阶段没有跨轮持久化或可信 History receipt。

## 3. 由真实后端执行结果派生

```text
现有 ToolCallingService / Registry / Policy / Executor
  → ToolConversationResult.tool_result
  → receipt_from_execution(run)
       核对首轮 tool_calls outcome
       核对 run 与 Tool Result 的名称 / call ID 关联
       核对合法 Tool status 与有限 payload 形态
       canonical water_quality 复用 WaterQualityReading 合同校验
  → requirement_satisfied(requirement, receipt)
  → Assistant 既有最终提交门禁 / RequestHandle
```

没有第二份 Executor 或 Tool lifecycle。没有从模型正文、客户端状态、历史回答或“Tool 可用”推导执行来源。Receipt 不认证模型引用的文本正确性，也不计算新的诊断或评分。

观测时间由原结果验证 / 规范化，不重新评 freshness、不复制 stale 阈值、不写 Store；query-time Freshness 仍由现有 Reader 完成。NO_DATA 原结果无 evaluated_at 时不伪造数据时间，可通过既有运行记录说明本轮执行范围。

## 4. Receipt 状态矩阵

| 实际结果 | Sources | 已完成操作 | 结果限制 |
| --- | --- | --- | --- |
| 无 protocol Tool Call / 正文模仿调用 | NONE | 无；仅 AUTO 满足 | 不由正文认证来源 |
| 查询 OK + VALID / FRESH | OBSERVATION | 观测查询 | 原时间、三个字段名；不复制读数 |
| 查询 OK + PARTIAL | OBSERVATION | 观测查询 | quality=partial，缺失字段不补足 |
| 查询 OK + INVALID | OBSERVATION | 观测查询 | quality=invalid，不表示有效测量 |
| 查询 OK + STALE / PARTIAL + STALE | OBSERVATION | 观测查询 | 保留 stale 与 partial；不是新采样 |
| 查询合法 NO_DATA | NONE | 观测查询 | has_observation=false；无时间则不伪造 |
| Score OK + 合法评分 / canonical water_quality | SCORE + OBSERVATION | 观测查询、评分评估 | 原 quality / freshness；不复制评分 |
| Score PARTIAL + 合法局部评分 | SCORE + OBSERVATION | 观测查询、评分评估 | 局部评分，不是完整专业评分 |
| Score 合法 NOT_SCORABLE + INVALID reading | OBSERVATION | 观测查询、评分评估 | has_score=false，保留 invalid |
| Score 合法 NO_DATA | NONE | 观测查询、评分评估 | has_observation=false、has_score=false |
| Score 畸形评分但独立 canonical reading 合法 | OBSERVATION | 仅观测查询 | 评分评估不满足，不能按名称认证 |
| NO_DATA / NOT_SCORABLE 的状态与 payload 矛盾 | 不认证评分；合法 reading 可独立保留观测 | 仅独立可证明的操作 | 负向业务 status 本身不够 |
| Knowledge OK + 合法非空 Evidence | RETRIEVED_PROJECT_EVIDENCE | 项目检索 | count=1–3，has_project_evidence=true |
| Knowledge 合法 NO_MATCH + count=0 / [] | NONE | 项目检索 | has_project_evidence=false；不提供命中证据 |
| Knowledge count / items / status 不一致 | NONE | 无 | 畸形 payload 不认证完成 |
| Tool ERROR | NONE | 无 | 不满足非 AUTO；原错误优先 |
| 第二次模型请求失败 / 取消，但 Tool 已完成 | 保留已取得来源 | 保留已合法完成操作 | 仍不能提交成功回答，原失败 / USER_CANCELLED 优先 |

表中 OBSERVATION / SCORE 是来源枚举简称。requirement_satisfied 只读取相应 operation-completed 字段，不从来源集合或 status 单独推断。将来如要求 DO 必须存在、必须 FRESH、必须有评分 / Evidence，需要另行定义结果要求，不改变本次操作枚举。

评分的交叉满足不是按名字机械继承：当前固定 Handler 实际先调用 Reader.query，再评分；合法 canonical reading 证明已完成观测查询。合法 Score NO_DATA 必须同时具备 water_quality=null、score=null、grade=null、components={}、quality=null、freshness=null、evaluated_at=null，才认证评估与查询完成。查询 Tool 的 NO_DATA 必须有 water_quality=null、findings=[]；畸形负向结果不认证。

评分来源要求有限检查：status 为 OK / PARTIAL，与 reading quality 一致；score 为有限 0–100 数值、grade 为当前合法值、components 与实际可用测量字段对应且分项评分合法，quality / freshness 与 reading 一致。不重新计算算法；仍是 Experimental / NOT PROFESSIONAL STANDARD。NOT_SCORABLE 还须无 score / grade / components，且 root quality / freshness 与 INVALID reading 一致，才能认证评估完成；即使合法，也不授予 SCORE。

## 5. 提交与安全边界

在 [AssistantService.send()](../../../../src/fishery_ai/assistant.py) 中，执行后立即生成 Receipt。既有模型失败、非空、finish_reason、Trace 和 Cancellation 门禁保持；操作要求不满足时，在最终 `RequestHandle.finish()` 前设安全错误码。合法 NO_DATA / NOT_SCORABLE / NO_MATCH 不因没有正向结果而触发此错误；操作完成也不能覆盖后续模型失败。

`ASSISTANT_SOURCE_REQUIREMENT_UNMET` 导致 `status=failed`、`successful_turn=false`、`final_text=""`、`completed_at=null`，现有 Browser 不提交 completed history。Coordinator Trace 可以记录模型 / Tool 已正常结束，Assistant Trace 则记录提交失败；两者表示不同层次，不是丢失失败。

不重试、不补执行另一个 Tool、不发送第三次模型请求。首轮仍 auto，第二轮仍 none。P1 的 Requirement 是提交要求，不是强制模型选择指令；P2 再讨论协议 choice，不在本阶段提前实现。

Web 返回结构与 UI 不变；安全 Receipt 暂不公开。模型可以生成一般知识正文，不能生成 Receipt。内部来源字段不进入 History。真实 Credential / ACL、Adapter、Provider Capability、Preset、Policy、Handler、RAG 与 Analysis 没有修改。

## 6. 受控 Real Model Qualification 接口设计（未实施、未执行）

### 6.1 现有入口可复用什么

[qualify_preset_tools.py](../../../../scripts/qualify_preset_tools.py) 已有显式 `--confirm-network`、单个 Preset 选择、正式私有 CredentialStore → ProfileRegistry.snapshot、RequestHandle、Gateway 和 Git ignored 输出位置，可复用其 composition / 安全错误 / JSON 输出模式。正常入口不读取源码根 .env，不直接打开 / 打印 Key。

[preset_tool_qualification.py](../../../../src/fishery_ai/preset_tool_qualification.py) 提供单轮 Coordinator 和计数 Gateway 思路，但当前固定查询 Tool、固定问题，并另发概念题，最多 3 次请求；使用诊断 Runtime 的局部 capability 设置。**不能直接调用它来声称满足新的任意来源要求 / 两次请求预算**，不能照搬诊断授权去更改发布合同。

建议未来保留旧 Preset qualification 原语义；新增一个小型、独立的 Assistant 单次 qualification 编排入口，复用既有服务，而非重写 Credential 或模型—Tool—模型栈。没有实现这个新入口。

### 6.2 一次 qualification run 的输入合同

| 参数 | 建议约束 |
| --- | --- |
| preset_id | 当前 Assistant 允许的发布 Preset，固定 OFF + Normal，捕获精确 Identity / 合同 / ProtocolSpec |
| question | 本次批准的固定短测试问题，不自动附加真实历史；2 KiB 内，可要求更小测试上限 |
| exposed_tools | Registry 中可执行且本次批准的静态名称集合；显式冻结 ToolPolicy，仅缩小授权范围 |
| source_requirement | 本阶段四种类型；直接传内部 AssistantRequest，不做自然语言 Router |
| max_requests | 默认 / 硬上限 2；计数在发出 Gateway 请求前扣除；错误不补探索请求 |
| max_output_tokens | 每次最多批准的有限值，例如 256；明确覆盖两轮的生成预算，不假称输入 tokens 免费 |
| retry | 固定 0，Gateway 与 SDK 均如此；transport attempts 单独计数 |
| approval | 本轮用户明确授权 + 本次命令 `confirm_network`；无确认退出，授权不保存成以后自动联网开关 |

若选择 max_requests=1，则只允许首轮协议取证；不能认证完成 Model → Tool → Model，也不能自动执行原 qualification 的额外概念题。完整 Assistant 来源闭环使用两次预算；没有 Tool 时实际只有一次。达到预算、取消或任何失败立即结束，不转模型、不增加 round。

Runtime / CredentialSnapshot 由正式 composition 内部创建，调用方只取得安全状态，不调用 `_for_adapter()` 检查或打印 Secret。若 Store 无法读取，报告安全错误、真实请求 0，不修改 ACL、复制凭据、创建项目 .env 或要求绕过权限。一个 run 内继续使用同一不可变 RuntimeSnapshot。

### 6.3 安全结果与原始 / 归一化对照

建议结果白名单：run / request ID、配置精确 Identity 与合同版本、实际 definitions 名称、choice、每轮安全 outcome / finish_reason、Provider model 的精确匹配状态、实际 protocol calls 的存在 / 数量 / 获准名称、call ID 是否合法、参数对象 / Schema 校验是否通过、normalized call 一致性、Receipt 安全摘要、request count、transport attempts、数值 Usage 与来源、最终 success / safe failure reason。

`actual tool_calls` 记录执行事实的摘要，不转储完整响应：未知名称显示 unknown_tool；ID 只记录合法 / 已关联；无参为 {} 摘要，Knowledge 只记录 query 字段存在 / 合法，不保存 query 原文。Receipt 不带完整 Evidence、读数或评分。Provider 返回 model 不匹配时安全报告 mismatch，不把任意原始字符串直接输出。

当前 Gateway 和旧 qualification 已能取得 normalized ModelResponse、usage、finish、outcome；没有公开保存 Provider 原始响应的 hook。若下一阶段需要证明 raw / normalized 一致，可设计 Adapter 客户端工厂中的受控只读观测包装，仅提取上述有限字段并与归一化结果比较；不得启用全量 HTTP / SDK debug logging，不能从旧 Trace 伪造 raw 对照。该观测接口也需离线 fixtures 验证后再批准实施，P1 没有修改 Adapter。

禁止输出或持久化 Secret、Authorization Header、完整 CredentialSnapshot、Credential 路径、不必要的完整 Prompt / 用户历史、原始 Tool Result 或模型完整内部响应。本地报告按固定工作区输出目录生成，参数不能指定 Credential 文件位置。

### 6.4 授权不是永久权限

每次由用户批准一个具体 manifest：模型、问题、tools、requirement、请求数与 token 上限；执行前展示安全计划与网络性质，匹配批准内容再执行。确认不写入 Profile / Capability / Credential，不在失败后自动重发，不自动运行下一个模型或第二组历史实验。

一次确认覆盖该 run 必要的两次请求及本地只读 Tool，不向用户对每个 Handler 重复确认。结果不自动写 Capability Evidence、发布 Preset 或重启另一个 run。当前 Codex 可访问公开研究文档不等于真实模型权限；本阶段实际模型请求 **0 次**。

## 7. 修改文件与测试

- 新增 `src/fishery_ai/assistant_sources.py`：内部类型、Receipt、派生和满足函数。
- 修改 `src/fishery_ai/assistant.py`：内部 Request 默认 AUTO、Result 持有 Receipt、非 AUTO 提交门禁。
- 新增 `tests/test_assistant_sources.py`：P1 原有 25 项、P1.1 更新并新增 8 项，共 33 项 deterministic / scripted 测试，复用临时 Store / 虚构响应和网络阻断 fixture。
- 修改 `tests/test_browser_streaming.cjs`：新增来源要求失败不提交历史、不显示被拒正文的回归；前端不发送 Receipt / Requirement。
- 新增本文；records 索引补导航。之前的研究报告原样保留，产品前端源码未变。

### 最终 P1.1 已执行验证

| 命令 / 范围 | 结果 |
| --- | --- |
| `.venv/Scripts/python.exe -m unittest discover -s tests -p test_assistant_sources.py` | 33 通过 |
| 同入口 `-p test_assistant.py` | 49 通过 |
| 同入口 `-p test_tool_conversation.py` | 37 通过 |
| 同入口 `-p test_gateway_tool_contract.py` | 29 通过 |
| `node --test --test-name-pattern='Assistant' tests/test_browser_streaming.cjs` | 25 通过 |
| `.venv/Scripts/python.exe -m unittest discover -s tests` | 860 通过，约 23.2 秒 |
| `node --test tests/test_browser_streaming.cjs` | 188 通过 |
| `node --check src/fishery_ai/resources/web/app.js` | 通过 |
| 本次 records 文档与索引的本地 Markdown 链接 | 28 个有效，0 个失效 |
| `git diff --check` 与新增文件空白检查 | 通过 |
| 修改 / 新增文本的 Secret 风险扫描 | 7 个文件，0 个风险文件；不输出匹配值 |
| Git 跟踪的 outputs / 凭据文件检查 | 0 个受管运行数据或凭据文件 |

对照 HEAD 的 AST 检查确认：Assistant SYSTEM_INSTRUCTION、AssistantHistoryTurn、AssistantContextBuilder 均未改变。产品 app.js 未修改；真实 qualification 只设计，不实现。

开发时首次运行发现新测试误用了不存在的 Evidence 名称；另一个测试把异常放在 response 序列里而没有实际 raise。均修正虚构 fixture 后通过，没有因此修改业务实现或放宽断言。测试检查 NO_DATA / invalid / partial / stale、评分双来源、NO_MATCH、错误、模仿调用、关联错误、有限 payload 形态、取消、不可变性、来源要求失败、Web 输入拒绝及原 AUTO 兼容。

P1 原回归为 Python 852 / Browser 188 通过；P1.1 新增 8 项，Python 860 / Browser 188 通过。明确覆盖：合法负向结果满足操作要求但没有正向来源；评分真实读取可满足查询要求且不增加执行；畸形 NO_DATA / NOT_SCORABLE 不认证；来源集合本身不替代操作完成；畸形 JSON fail closed；查询完成不覆盖第二轮 READ_TIMEOUT；旧内部枚举不再接受。源码改动仅限 assistant_sources.py，Assistant 提交门禁与 Browser 行为沿用 P1，不修改 Prompt / History / UI / Policy / Handler / Adapter。

## 8. 当前限制与交付状态

Receipt 是可信后端结果的有限投影，不能验证所有自然语言真假，不代替检索 relevance 或专业评分标准。INVALID / STALE 的来源认证不意味着数据合格；NO_MATCH 的完成认证不意味着存在命中。本阶段没有可供用户选择 Requirement 的 UI、没有 History receipt、没有新的真实 qualification 命令。

产品仍为 AUTO；普通正文包括未遵守 Prompt 的来源声明仍可能成功。这个已知风险没有被隐藏为“P1 已彻底解决”。下一阶段须另行审阅 Requirement 产品入口、协议强制选择或 History 方案，不能自动进入实施。

没有读取 / 修改真实凭据或源码根 .env，没有真实模型请求、生产项目修改、commit / push。最终工作树包含本轮代码 / 测试 / 记录，以及此前尚未提交的研究报告；等待用户审查。

最终 Git 状态：3 个已跟踪文件修改、4 个未跟踪文件。其中旧研究报告是开始本轮前已有的未跟踪文件，原样保留；其余 6 个文件为本轮交付。`git diff --stat` 仅统计已跟踪文件：3 files changed, 26 insertions(+), 1 deletion(-)，不包含未跟踪的新模块、测试与报告。

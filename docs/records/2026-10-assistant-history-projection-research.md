# P2B：Assistant History Projection 与 Tool Reliability 研究

查询及结果分析日期：2026-10-10。项目基线：`756f6e57ca58d3401374ffaf497930aad680a8fc`。前阶段仅扩展 qualification 实验入口；本次只分析正常用户进程完成的安全报告，未实施正式 History v2，未新增模型请求。

## 1. Executive Summary

- 当前浏览器已区分显示记录与模型历史；主要研究边界是 `AssistantHistoryTurn → AssistantContextBuilder → ModelMessage`，无需推倒 Web Session。
- 当前旧回答确实以 `role=assistant` 重放，并带“不代表当前数据”的程序标签。标签是提示，不是可验证来源；历史文本不能产生本轮 Receipt。
- 已核对 Q3/Q4 的安全 JSON：Knowledge 首轮正确选择均为 6/6。Q4 最终完成 5/6；唯一失败为第二轮 `length`，不是 Tool 选择失败。
- 已实现固定 H0–H6 manifest 和五种不可变 synthetic fixture；离线回归通过。
- **真实 H 批次已完成**：正常用户 PowerShell 产生 H0–H6 各 6 个真实样本，共 42 runs / 69 Provider requests。H0/H1/H3/H4/H5 各完成 6/6，H2 完成 0/6，H6 完成 3/6。H2/H6 共 9 次失败均为首轮无 Tool 的直接回答，来源操作未执行；没有错误 Tool、参数错误、截断或 raw/normalized 不一致。
- 保留 Codex 先前的 `CREDENTIAL_FILE_ERROR` 记录：它是 0-request preflight，已排除，不计入任何六样本分母。
- 查阅 Open WebUI、LibreChat、AnythingLLM 的官方文档和固定 revision 源码。三者都存在 Context projection；都不是本项目传感器 query-time Freshness 的替代方案。
- H0/H2 的相同当前问题对照强烈支持 OLD_NO_DATA 历史会降低本轮当前观测重查可靠性；H1/H4 的正向结果反对“只要有历史就失败”的概括。建议进入 **qualification-only projection A/B 设计与审阅**；不能据此认定 assistant role 是唯一根因或立即改产品。

## 2. 当前 Assistant History 实际实现

### 2.1 源码地图

| 位置 | 代码事实 |
|---|---|
| [assistant.py](../../src/fishery_ai/assistant.py)，23–26、87–146 | 模型历史上限 6 turns / 6 KiB；History 只接受 `user / assistant / completed_at`，无任意 role、系统指令或 Tool 字段。客户端时间只校验格式，不认证来源。 |
| 同文件 172–186 | 每次 `build()` 都重新加入完整 `SYSTEM_INSTRUCTION`；历史 user 为 user，历史 assistant 为 assistant；最后追加当前 user question。 |
| 同文件 174–184 | 先保留最近 6 个完整 pair，再按 UTF-8 JSON 字节超限移除最旧 pair。两条历史消息均附程序生成的历史/客户端时间标签。 |
| 同文件 199–234、240 后 | Receipt 来自实际执行，成功提交由最终正文、finish reason、取消状态和 Requirement 决定；公开 Assistant Result 当前不输出内部 Receipt。 |
| [assistant_sources.py](../../src/fishery_ai/assistant_sources.py) | 操作完成与来源 payload 存在性独立；NO_DATA 可以认证查询完成，NO_MATCH 可以认证搜索完成，均不认证实际值/命中。 |
| [tool_conversation.py](../../src/fishery_ai/tool_conversation.py)，`run_request` | 本轮追加 assistant.tool_calls 与匹配 role=tool；第二轮 `tool_choice=none`；预算 1 call / 1 round / 2 requests。这些协议消息不进入下一轮 History pair。 |
| [app.js](../../src/fishery_ai/resources/web/app.js)，2648、2897–2950 | `displayEntries` 与 `completedTurns` 分开；仅完整成功 pair 提交，completed 保留最近 20，display 最多 60 entries，发送时进一步裁剪为 6 turns / 6 KiB。 |
| [web.py](../../src/fishery_ai/web.py)，1040–1056 | Web 通过 `AssistantRequest.from_dict` 和正式 AssistantService；不接受 qualification fixture、SourceRequirement、Receipt 等客户端升级字段。 |
| [application.py](../../src/fishery_ai/application.py)，97–124 | Analysis 自己构建固定事实/规则/RAG ModelRequest，不使用 AssistantContextBuilder、AssistantHistoryTurn 或 Assistant SYSTEM_INSTRUCTION。 |

6 KiB 是历史 pair 的序列化字节预算，**不是 token 预算**；后加历史标签、System、当前问题、Tools schema 和第二轮 Tool Result 不包含在这项历史预算中。此处是未来预算评估点，本轮未改变。

### 2.2 跨轮边界

UI Activity 可以显示本轮查询时间、freshness、工具与耗时；下一次发送的 History 只含自然语言 pair。Tool calls、role=tool、Raw Tool Result、TurnSourceReceipt、开发 Trace 不跨轮重放。页面刷新、模型切换、epoch 过期仍清理 Session；不使用 DB 或 LocalStorage History。

浏览器提供的 pair 不可信。把文本放进 assistant role 是对话投影，并不能认证“它来自真实执行”或“它现在仍有效”。模型可能依赖旧答案是**待检验行为假设**，不是代码可直接证明的结论。

## 3. Q3 / Q4 Fresh baseline

核对 `outputs/assistant-qualification/q3/` 五份、根目录一份 Q3 正常用户 JSON，以及 `q4/` 六份；按 run_id 去重。早先 Codex 凭据阻塞记录为 0 请求，不混入真实六样本分母。

| 基线 | 首轮 protocol call | 正确 Knowledge / 合法 query | Search completed / Requirement | 完整完成 | 模型请求 | Usage：input / output / total |
|---|---|---|---|---|---|---|
| Q3：单 Knowledge、EMPTY | 6/6 | 6/6 / 6/6 | 6/6 / 6/6 | 6/6 | 12 | 12860 / 1006 / 13866 |
| Q4：三 Tool、EMPTY | 6/6 | 6/6 / 6/6 | 6/6 / 6/6 | 5/6 | 12 | 14177 / 1349 / 15526 |

两组 Provider model match、raw/normalized call consistency 均正常；每次 Knowledge status=OK，evidence_count=3。Q4 截断 run 为 `4ee9dcee82334cf59d26413edd94b8a7`：Request #1 tool_calls、搜索与 Receipt 成功，Request #2 `length`。两请求合计输出 297 tokens 不代表每请求超过 256；限制分别作用于两次请求。

这支持“本轮 Fresh 条件下 parameterized Knowledge Tool 可工作”，不等于长期稳定性保证，也不解释真实 Web 多轮异常。

## 4. H0–H6 实验设计与 qualification-only 实现

所有条件固定：Qwen 3.8 Flash / DashScope、Thinking OFF、Normal、三 Tool 同时暴露、retry=0、单 run 最多 2 次模型请求、每请求最多 256 output tokens、1 Tool / 1 round。每条件授权 6 次独立进程；最大 42 runs / 84 Provider requests。System、工具 schema、Provider、Preset、Policy 业务定义冻结。

| Case | fixture_id | 当前问题 | SourceRequirement | 预期执行 |
|---|---|---|---|---|
| H0 | EMPTY | 现在溶氧是多少？ | CURRENT_OBSERVATION_QUERY | 当前查询；空 CLI Store 的 NO_DATA 合法 |
| H1 | OLD_DO_2_2 | 现在还是 2.2 吗？ | CURRENT_OBSERVATION_QUERY | 旧值只是比较对象，本轮重新查询 |
| H2 | OLD_NO_DATA | 现在溶氧是多少？ | CURRENT_OBSERVATION_QUERY | 旧 NO_DATA 不能代替本轮查询 |
| H3 | EMPTY | 当前水质评分多少？ | CURRENT_SCORE_EVALUATION | 当前评分；NO_DATA 合法 |
| H4 | OLD_SCORE_25 | 当前水质评分多少？ | CURRENT_SCORE_EVALUATION | 旧评分不能代替本轮评估 |
| H5 | OLD_DO_2_2 | 刚才 2.2 是什么意思？ | AUTO | 无 Tool 直接回答合法 |
| H6 | OLD_KNOWLEDGE_CLAIM | 项目资料里鳗鲡低氧有什么表现？ | PROJECT_KNOWLEDGE_SEARCH | 本轮重新搜索；旧声明不是 Receipt |

新增 [qualification_history.py](../../src/fishery_ai/qualification_history.py)：固定时间 `2026-10-01T00:00:00+00:00`、固定文本、tuple + frozen turn + MappingProxyType 白名单。非 EMPTY fixture 均只有一个 pair、小于 512 bytes。不读取外部历史文件，不接受自由 role/System/历史文本。

[assistant_qualification.py](../../src/fishery_ai/assistant_qualification.py) 只接受 `history_fixture_id`；`history` 仍必须为空。H case ID 同时校验固定问题、fixture、Preset、工具集合、Requirement 和 2-request 预算，防止结果被误标为另一个条件。报表增加 fixture ID/hash、turn count、System hash，以及实际 Context 裁剪计数；不保存 fixture 正文。

H fixture 真正通过当前正式 AssistantContextBuilder。Q3/Q4 EMPTY 的 safe plan / plan_sha256 保持原值：Q3 `82502a1fccc5a6af53cf9f184bd20cf6d4aa2134f4284302ab1e60950dc27849`，Q4 `3660d5515b3e7d2701a62b176139b40e0b7e8c18ca6e29114f9b9dc1ed041c69`。仍一进程一 manifest，不添加批处理 Harness。

## 5. H0–H6 真实结果

### 5.1 样本与统计口径

读取 `outputs/assistant-qualification/history/h0/` 至 `h6/` 的 Harness 安全 JSON；仅纳入 `actual_network_requests > 0`，按 run_id 去重。H0 目录有 7 份报告，其余目录各 6 份；排除下面这一份后，每 case **正好 6 个真实样本**：

- Codex 早先 H0 run：`a053e04f064145418a7d932e7d3fdd7d`。
- 安全错误：`CREDENTIAL_FILE_ERROR`；request_count / actual_network_requests / transport_attempts 均为 0。
- 它只证明当时 Codex 进程的凭据预检阻塞，不是 Provider 失败，不计入分母；之后的 42 份报告由正常用户 PowerShell 完成。

真实批次时间为 2026-10-10 15:54:48–15:58:26（Asia/Shanghai），按 H0 至 H6 顺序执行。本次分析没有重新调用 Provider，没有读取凭据、模型正文、Raw Tool Result、query 原文或 Evidence 正文。

所有 H 报告的精确 Identity 均为 `dashscope / openai_chat / https://dashscope.aliyuncs.com/compatible-mode/v1 / qwen3.8-flash`，Preset 合同 1.0.2，ProtocolSpec `dashscope_chat@1`。每组 plan hash 唯一；全组 System hash 相同：`974cc942da1a909ee2f41c74aeb329fbfafe7aacd309aaeff90c9541e2843bc5`。核对 OFF / Normal、三个 Tool、每请求 256 tokens、retry=0、最多两请求均一致；首轮 tool_choice=auto，第二轮（发生时）为 none。

EMPTY 组实际发送 0 个历史 pair；其余组实际发送 1 个 pair，均未裁剪。H0/H2 当前问题 hash 相同；H3/H4 当前问题 hash 相同。问题措辞的比较来自固定 manifest 与 hash，不来自回答正文。

统计定义：

- protocol call / direct answer：首轮协议有调用 / 首轮 outcome=final_answer 且零调用。直接回答不等于 qualification completed。
- correct / wrong：按 case 指定的 Tool 名判断；无调用不计 wrong。
- arguments valid：实际调用满足合法 JSON/Schema 和 call ID；无调用记 0 次合法调用，**不意味着参数无效**。
- operation completed：对应 Receipt 的 observation_query_completed / score_evaluation_completed / project_search_completed；不是“得到实际数值、评分或命中”。
- truncated：任一轮 finish_reason=length；inconsistency：Provider 与 normalized 的调用/元数据不一致。模型 identity match 另核对。
- H5 为 AUTO，没有 required Tool 或 required operation，因此 correct/wrong/operation 不适用。

### 5.2 每 case 结果

每个计数的分母均为该 case 的 6 个真实 run。

| Case | protocol call | direct answer | selected Tool | correct | wrong | arguments valid |
|---|---|---|---|---|---|---|
| H0 | 6/6 | 0/6 | get_current_water_quality × 6 | 6/6 | 0/6 | 6/6 |
| H1 | 6/6 | 0/6 | get_current_water_quality × 6 | 6/6 | 0/6 | 6/6 |
| H2 | 0/6 | 6/6 | 无 | 0/6 | 0/6 | 0/6（无调用） |
| H3 | 6/6 | 0/6 | score_current_water_quality × 6 | 6/6 | 0/6 | 6/6 |
| H4 | 6/6 | 0/6 | score_current_water_quality × 6 | 6/6 | 0/6 | 6/6 |
| H5 | 0/6 | 6/6 | 无 | 不适用 | 不适用 | 0/6（无调用） |
| H6 | 3/6 | 3/6 | search_fishery_knowledge × 3；无 × 3 | 3/6 | 0/6 | 3/6 |

| Case | operation completed | requirement_satisfied | final completed | response truncated | Provider / normalized inconsistency | model mismatch |
|---|---|---|---|---|---|---|
| H0 | 6/6 | 6/6 | 6/6 | 0/6 | 0/6 | 0/6 |
| H1 | 6/6 | 6/6 | 6/6 | 0/6 | 0/6 | 0/6 |
| H2 | 0/6 | 0/6 | 0/6 | 0/6 | 0/6 | 0/6 |
| H3 | 6/6 | 6/6 | 6/6 | 0/6 | 0/6 | 0/6 |
| H4 | 6/6 | 6/6 | 6/6 | 0/6 | 0/6 | 0/6 |
| H5 | 不适用 | 6/6（AUTO） | 6/6 | 0/6 | 0/6 | 0/6 |
| H6 | 3/6 | 3/6 | 3/6 | 0/6 | 0/6 | 0/6 |

H0/H1 的 12 次查询、H3/H4 的 12 次评分均得到合法 **NO_DATA**：CLI 当前 Store 为空，Receipt 认证操作完成，但没有实际 observation 或 score，sources 为空。不能把 6/6 requirement 解释为取得了六份新传感器读数/评分。

H6 三次真正搜索均为 OK、has_project_evidence=true、evidence_count=3；另三次没有执行搜索，receipt sources 为空、evidence_count=0。全部 69 个真实请求都有可用 Provider observation，call consistency、metadata consistency 和 model match 均为 true；没有 transport 重试、Provider 请求错误或截断。

| Case | request_count / actual_network_requests / transport_attempts | Usage input / output / total |
|---|---|---|
| H0 | 12 / 12 / 12 | 10920 / 189 / 11109 |
| H1 | 12 / 12 / 12 | 12350 / 421 / 12771 |
| H2 | 6 / 6 / 6 | 7518 / 152 / 7670 |
| H3 | 12 / 12 / 12 | 11268 / 338 / 11606 |
| H4 | 12 / 12 / 12 | 12664 / 442 / 13106 |
| H5 | 6 / 6 / 6 | 7524 / 779 / 8303 |
| H6 | 9 / 9 / 9 | 11531 / 1085 / 12616 |
| 合计 | **69 / 69 / 69** | **73775 / 3406 / 77181** |

共 27 runs 执行一次 Tool 和第二轮模型请求，15 runs 首轮直接回答；最终 33 completed、9 source requirement unmet。每请求输出均不超过 256 tokens；不能把两轮合计输出和单请求预算混为一谈。

### 5.3 H2：全部失败都是 no-tool direct answer

| Run（按开始时间） | run_id | 首轮 call count / finish | observation_query_completed | Requirement | 请求数 / 最终状态 |
|---|---|---|---|---|---|
| 1 | bd44d476535949a5b7a606c15ed3334c | 0 / stop | false | false | 1 / UNMET |
| 2 | 430445dc02eb4c7d9c93208e9e90dc04 | 0 / stop | false | false | 1 / UNMET |
| 3 | 56637cff25fb4e05866033c086605d52 | 0 / stop | false | false | 1 / UNMET |
| 4 | 9d5b15ba8f28471a87c6b2a49a351f3f | 0 / stop | false | false | 1 / UNMET |
| 5 | 84a2ef59c8034501812cece58d6aac39 | 0 / stop | false | false | 1 / UNMET |
| 6 | 463534c3fe154ecd8b3eda98ac171ade | 0 / stop | false | false | 1 / UNMET |

UNMET 均为 `ASSISTANT_SOURCE_REQUIREMENT_UNMET`。六次 Provider 原始观察与 normalized 都没有 protocol tool_calls，首轮 outcome=final_answer、finish_reason=stop，第二轮没有发生。错误 Tool、无效参数、执行错误及其他失败各为 0；没有“Adapter 丢掉原始 Tool Call”的证据。Requirement 在应用提交边界准确拒绝未经本轮查询的答案。

没有读取正文，因此不能断言模型原样复述旧 NO_DATA，也不能判断它是否声称已经查询；可确定的是 **本轮没有任何可信查询执行来源**。

### 5.4 H6：三次搜索成功，三次直接回答

| Run（按开始时间） | run_id | tool_call | selected Tool | project_search_completed | Evidence | Requirement | 首轮 / 第二轮 finish | 最终状态 |
|---|---|---|---|---|---|---|---|---|
| 1 | 0beef8b73f1f453d8f1d9a2f20bf4fe8 | 是 | search_fishery_knowledge | true | 3 | true | tool_calls / stop | completed |
| 2 | 688392b6012e44e1b1840549d75686fd | 否 | 无 | false | 0 | false | stop / 未发生 | UNMET |
| 3 | 3734bd21005e493e83e06bb6fb82f5f8 | 是 | search_fishery_knowledge | true | 3 | true | tool_calls / stop | completed |
| 4 | ae6a9be349d04d57a38e5a223c9adc71 | 否 | 无 | false | 0 | false | stop / 未发生 | UNMET |
| 5 | c24e13f6794d4297b887141902e479b5 | 是 | search_fishery_knowledge | true | 3 | true | tool_calls / stop | completed |
| 6 | 484ddb17fa464cd985a3a1c9578ca58a | 否 | 无 | false | 0 | false | stop / 未发生 | UNMET |

三次调用的 query_present、query_valid、arguments_valid、call_id_valid 均为 true，Tool status=OK。三次 UNMET 都是一次模型请求后无调用的直接回答；不是 wrong Tool、NO_MATCH、非法 query、Handler 错误或第二轮失败。Provider 和 normalized 一致，因此问题发生在模型是否发起调用的选择阶段，不是本组已观察到的 normalization 丢失。

单次序列呈交替结果不等于发现了交替规律或缓存根因。成功调用证明带 query 的 Knowledge 协议仍可工作；目前没有这组数据支持“parameterized Tool 不受支持”。

### 5.5 H5：防止过度修复

H5 **direct no-tool=6/6，Tool Call=0/6**，所以本组不必要 Tool Call 的观察计数为 0/6。AUTO requirement 与 final completed 均为 6/6。没有读取正文，不认证解释内容的质量。

这是下一轮必须保留的正向约束：“刚才 2.2 是什么意思？”可以依赖历史语境解释，不能因为出现旧数值就强制查询。投影调整若提升 H2/H6，却让 H5 开始频繁调用 Tool 或失去“刚才”的语境，不应直接进入产品迁移。

## 6. Fresh vs History 对照与证据边界

| 对照 | 当前问题是否相同 | 正确 Tool / operation / Requirement | final completed | 可支持的解释 |
|---|---|---|---|---|
| H0 EMPTY → H2 OLD_NO_DATA | 是；question hash 相同 | 6/6 → 0/6 | 6/6 → 0/6 | 本轮 OLD_NO_DATA 历史伴随完全停止重查 |
| H3 EMPTY → H4 OLD_SCORE_25 | 是；question hash 相同 | 6/6 → 6/6 | 6/6 → 6/6 | 本轮旧评分没有抑制重新评估 |
| Q4 Fresh Knowledge → H6 OLD_KNOWLEDGE_CLAIM | 否；问题措辞、执行时间不同 | 6/6 → 3/6 | 5/6 → 3/6 | 历史来源声明与较少重新搜索相关；不是干净因果对照 |
| H0 EMPTY → H1 OLD_DO_2_2 | 否；H1 询问旧值是否仍成立 | 6/6 → 6/6 | 6/6 → 6/6 | 本轮旧正值/明确当前追问没有阻止重查 |

### 6.1 H0 / H2：最强的当前证据

**本轮 6+6 受控真实样本强烈支持 OLD_NO_DATA History 会降低当前观测 Tool re-query reliability。** 两组当前问题、System hash、三 Tool 集合、Identity、ProtocolSpec、预算均相同；H2 fixture 实际进入 Context，未被裁剪。H0 的新查询即使也是 NO_DATA，仍合法完成；H2 则根本未查询，区别是操作执行，而不是“有没有数值”。

但这不证明 `role=assistant` 是唯一根因：尚未在保持历史内容相同的情况下单独比较不同 projection。History 内容、角色与 framing、模型对旧答案充分性的判断、顺序/缓存/Provider 随机性仍可能共同影响结果。

### 6.2 H1 / H4：不是“有 History 就坏”

H1 与 H4 都发送了实际历史 pair，仍六次正确调用。尤其 H3/H4 当前评分问题完全相同，加入旧 25 分没有出现本轮抑制。因此不能把问题归结为 History 存在本身。

值得继续检验的假设是：旧正值/旧评分可能更容易被理解为需要确认的易变结果，而“没有 Snapshot”或“根据项目知识库”的旧回答可能被模型视为已经解决了问题、无需重新执行操作的语义锚。H1 的“现在还是”措辞也可能增强重查需求。以上是候选解释，不能从调用计数读出模型内部动机，更不能认定所有 NO_DATA 历史都会如此。

### 6.3 Q4 / H6：Knowledge 信号与预算问题分开

Q4 的六次均真正搜索且 requirement satisfied；唯一未 completed 是第二轮 length。H6 的三次失败都是首轮零调用且 stop，**不是输出预算导致的截断**。本轮观察到搜索完成率从 6/6 降至 3/6，与 OLD_KNOWLEDGE_CLAIM 存在相关信号。

但 Q4 与 H6 的当前问题不同，Q4 还是较早批次。下一轮应在同一 H6 问题、同一 fixture 下比较 A/B，并另设相同 H6 问题的 EMPTY 条件；不能把 Q4 当成严格等价的 Fresh control，不能断言一定是历史而不是措辞/时间导致。

### 6.4 结论范围

- 42 个真实 run 都保留在分母，包括失败；本次未补跑，排除的仅是一份 0-request Codex preflight。
- 每条件只有 6 样本、同一模型、固定 synthetic 单 pair、按组顺序运行；不能作长期稳定性、其他 Provider 或完整 Web History 的证明。
- 当前报表可证明 protocol → Executor → Receipt；不读取正文，故不评估“未调用却声称已查/已评分/已检索”、解释正确性或 Retrieval relevance。
- Provider observation 与 normalized 全部一致，未观察到 Adapter 丢失调用；这不能排除所有其他场景中的 Adapter 问题。
- 旧 NO_DATA / 项目来源声明是值得做 projection 对照的线索；**产品 History、Prompt、Policy 和能力合同暂不改**。

## 7. 成熟项目调研

三项目都在近期维护；以下固定 GitHub revision 的事实与查询当日滚动官方文档分开。选择 AnythingLLM 是因为其普通 RAG Chat 与 Agent/Tool 路径不同，最接近本项目 Analysis / Assistant 的边界。没有把第三方博客作为依据。

| 项目 / 仓库 | 本轮读取 revision | commit 日期 UTC |
|---|---|---|
| [Open WebUI](https://github.com/open-webui/open-webui) | `8bd8b4fac5e059578ac0c74b3c18d11139f88b7d` | 2026-09-21 |
| [LibreChat](https://github.com/danny-avila/LibreChat) | `e1dfc10449ff713faffacd60273fddcfe2c0a698` | 2026-10-06 |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | `2a10d052a1812d7be12c43f9024072cf26a27a8b` | 2026-10-09 |

### 7.1 Open WebUI

UI/persistence messages 不是直接原样送模型。`process_messages_with_output` 把 output items 重建为 OpenAI assistant.tool_calls / tool results，并去除 id/files/output/model/contextSummary/usage 等非协议字段；`sanitize_tool_pairs` 清理孤立调用与孤立结果。仍保留 assistant role 和完整工具配对，目的首先是协议合法性。[middleware.py 2271–2337](https://github.com/open-webui/open-webui/blob/8bd8b4fac5e059578ac0c74b3c18d11139f88b7d/backend/open_webui/utils/middleware.py#L2271)

Context compaction 在 token threshold 超限时切旧/新消息，以 user-turn 边界保留近期段，使用配置的模型生成摘要，checkpoint 写回持久消息；摘要与近期消息并存。Middleware 将摘要追加到 system，**不能将这种位置当作事实认证**；所查路径没有为每条旧传感器事实配置失效/强制重查规则。[context_compaction.py 42–147、300–395](https://github.com/open-webui/open-webui/blob/8bd8b4fac5e059578ac0c74b3c18d11139f88b7d/backend/open_webui/utils/context_compaction.py#L42)、[summary injection 2493–2512](https://github.com/open-webui/open-webui/blob/8bd8b4fac5e059578ac0c74b3c18d11139f88b7d/backend/open_webui/utils/middleware.py#L2493)

长期 Memory 是独立的用户存储与受权限管理工具，可注入 system，也可关闭注入；后台 review 与每轮原始对话窗口不同。这种 Memory 不适合替代实时 Snapshot。[官方 Memory 文档](https://docs.openwebui.com/features/chat-conversations/memory/)

### 7.2 LibreChat

`formatMessage` 由保存的 sender/role 映射 user/assistant；agent content projection 能重建 AIMessage.tool_calls 与对应 ToolMessage，而 UI-only activity labels、错误/agent-update parts 不进入模型。不是只保存 final text，也不是把 UI 全量组件原样重放。[formatMessages.js 65–137、201–324](https://github.com/danny-avila/LibreChat/blob/e1dfc10449ff713faffacd60273fddcfe2c0a698/api/app/clients/prompts/formatMessages.js#L65)

`BaseClient.getMessagesForConversation` 沿 parent 链取得当前分支，可在 summary checkpoint 截断；AgentClient 重算 provider projection token 数、配置 maxContextTokens，pruning/summary 实际委托 Agent SDK。项目具有模型生成摘要/持久 checkpoint 的接入点，但本轮没有审计外部 SDK 的全部规则，不能声称所有 endpoint 使用同一种阈值或摘要信任等级。[BaseClient.js 1476–1540](https://github.com/danny-avila/LibreChat/blob/e1dfc10449ff713faffacd60273fddcfe2c0a698/api/app/clients/BaseClient.js#L1476)、[AgentClient 2079、2349、2704–2780](https://github.com/danny-avila/LibreChat/blob/e1dfc10449ff713faffacd60273fddcfe2c0a698/api/server/controllers/agents/client.js#L2079)

官方明确 User Memory 是 opt-in 的持久 key/value，区别于单 conversation 消息窗口，不是对所有旧聊天做语义检索。Memory 有独立权限/内容过滤；过滤不等于证明旧现场事实仍然有效。[官方 User Memory](https://www.librechat.ai/docs/features/memory)、[memory/protection.ts](https://github.com/danny-avila/LibreChat/blob/e1dfc10449ff713faffacd60273fddcfe2c0a698/packages/api/src/memory/protection.ts)

### 7.3 AnythingLLM

普通 Chat 从 WorkspaceChats 持久记录选近期 include=true 数据；`convertToPromptHistory` 投影为 user prompt + assistant final text，过滤格式异常并处理引用/调查内容。独立 `constructPrompt` 组 system/context、历史与当前 user；普通路径不是把所有 Agent 中间步骤永久当 role=tool 重放。[chats/index.js 82–104](https://github.com/Mintplex-Labs/anything-llm/blob/2a10d052a1812d7be12c43f9024072cf26a27a8b/server/utils/chats/index.js#L82)、[responses.js 283–332](https://github.com/Mintplex-Labs/anything-llm/blob/2a10d052a1812d7be12c43f9024072cf26a27a8b/server/utils/helpers/chat/responses.js#L283)、[OpenAI constructPrompt 116–134](https://github.com/Mintplex-Labs/anything-llm/blob/2a10d052a1812d7be12c43f9024072cf26a27a8b/server/utils/AiProviders/openAi/index.js#L116)

普通 Chat 的 `messageArrayCompressor` 按 token、输出余量与区域预算裁剪；优先近期 pair，超限时可对最近三 pair 文本做 middle-out 压缩。它不是 LLM 生成摘要，可能丢内容；不能把 truncation.js 或任意文件概述函数误说成聊天自动摘要。[compressor 49–191](https://github.com/Mintplex-Labs/anything-llm/blob/2a10d052a1812d7be12c43f9024072cf26a27a8b/server/utils/helpers/chat/index.js#L49)

Agent provider formatter 把内部 function 消息转 assistant.tool_calls + role=tool，保留 originalFunctionCall.id；再生成回答时重放工具结果。`chat-history` 插件在 regeneration 前显式裁掉上一轮中间消息，源码注释指出旧 Tool Result 留下会影响 re-call；这是**重生成路径处理**，不是通用 current-state freshness 保证。[tooled.js 80–158](https://github.com/Mintplex-Labs/anything-llm/blob/2a10d052a1812d7be12c43f9024072cf26a27a8b/server/utils/agents/aibitat/providers/helpers/tooled.js#L80)、[chat-history.js 28–47](https://github.com/Mintplex-Labs/anything-llm/blob/2a10d052a1812d7be12c43f9024072cf26a27a8b/server/utils/agents/aibitat/plugins/chat-history.js#L28)

用户/Workspace 的长期 Memory 单独管理，可把选择后的记忆注入 system。其内容摘要工具会用模型处理文档片段，不能推导普通 Chat 也执行相同摘要流程。[官方 Memories](https://docs.anythingllm.com/features/memories)、[内容 summarize.js](https://github.com/Mintplex-Labs/anything-llm/blob/2a10d052a1812d7be12c43f9024072cf26a27a8b/server/utils/agents/aibitat/utils/summarize.js#L108)

### 7.4 对本项目的可用结论

| 问题 | 查阅结果 |
|---|---|
| Transcript = Model Context？ | 三项目都有单独转换/过滤/裁剪，不能按 UI 外观判断传输内容。 |
| assistant role replay？ | 三者查阅路径均存在；它不是天然错误设计，也不是可信来源凭证。 |
| Tool History？ | Open WebUI/LibreChat Agent 路径保留配对；AnythingLLM 普通 final-pair 与 Agent 工具路径不同。 |
| Summary？ | Open WebUI 有模型摘要与近期消息；LibreChat接SDK摘要/裁剪；AnythingLLM普通 Chat主要token剪裁，文档摘要另一路。 |
| Trust？ | 存储/权限/结构校验可保护系统边界；未发现能把每条历史内容转成“当轮可信事实”的普遍保证。摘要放system存在指令提升风险，需要额外framing。 |
| Current external facts？ | 本轮所查文档/源码没有提供与本项目同等的 current sensor freshness / mandatory re-query 保证。 |

没有因此建议引入三项目的 DB、Agent SDK、Memory、Vector DB 或多 Tool loops。

## 8. 官方协议调研

全部为 2026-10-10 读取；协议支持不自动等于本项目具体模型的发布 Capability。

| 来源 | 确认内容 | 对本项目含义 |
|---|---|---|
| [OpenAI Conversation state](https://developers.openai.com/api/docs/guides/conversation-state) | 可自行发送 user/assistant 历史；Responses 的 previous_response_id / Conversations 是其他状态管理机制。 | History projection 是应用职责；本轮不迁移 API，也不引入服务端永久 History。 |
| [OpenAI Chat Completions](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create) | roles 区分消息作者；assistant可输出tool_calls；tool结果以对应call ID返回；auto允许正文或调用，none禁止调用。 | auto 不保证查询；来源必须由实际执行认证，旧 assistant role 本身不是来源凭证。 |
| [DashScope Function Calling](https://help.aliyun.com/zh/model-studio/qwen-function-calling) | 官方多轮示例保留system/user/assistant-call/tool/final；auto由模型选择，none禁止；required与强制策略有模型/Thinking限制。 | 不用强制选择来“修好”本轮实验。没有文档承诺旧工具数据自动过期。 |
| [DeepSeek Multi-round](https://api-docs.deepseek.com/guides/multi_round_chat/) | Chat Completions 无状态，由调用方拼接历史。 | 当前pair裁剪策略属于本项目，不是Provider强制要求。 |
| [DeepSeek Chat API](https://api-docs.deepseek.com/api/create-chat-completion/) | system/user/assistant/tool、tool_call_id、tools、auto/none/required、函数arguments；参数需本地校验。 | 可表达现有单round协议；文档不证明本项目History不会抑制重查。 |

DeepSeek独立Tool guide本轮超时/旧URL跳转，未把错误页面当证据；以上使用成功读取的官方 API reference。本阶段无需额外 Ollama API 研究或模型实验。

## 9. 证据分层

| 类别 | 可以说什么 | 不能说什么 |
|---|---|---|
| 本项目源码事实 | 原生assistant replay、历史标签、只重放pair、无History Receipt、模型6/6KiB | 模型必然信任某个role；某段Prompt必然有效 |
| 公共项目事实 | 固定revision里的projection/compaction/tool配对/Memory分离 | 成熟项目已经解决本项目当前事实过期 |
| 真模型数据 | Q3/Q4 首轮正确选择6/6；42个H样本的调用/执行/Receipt；H0/H2重查6/6→0/6；H6搜索3/6 | 回答正文正确性、History角色唯一因果、其他模型或长期可靠性 |
| 推断 | OLD_NO_DATA/旧项目来源声明可能成为语义锚；framing/投影值得对照测试 | role=assistant唯一根因；更换role必然解决；所有历史都会抑制调用 |

## 10. History Projection 候选 A / B / C

以下均未实施。不把不可信浏览器文字提升为新的 system instruction，也不从回答关键字猜 Tool 来源。

| 维度 | A：保留native role，增强provenance | B：历史作为不可信transcript | C：Hybrid |
|---|---|---|---|
| 设计 | 保留当前pair，只增加明确来源/历史边界 | 旧pair成为单一有界数据块，近期/当前问题明确分隔 | 最近语言pair保留role；旧执行来源独立historical metadata，正文仍作不可信材料 |
| 连续性/刚才指代 | 最接近当前行为 | 需保留顺序、speaker、时间，否则代词退化 | 较好，但界定“近期”必须固定可测 |
| 当前事实重查 | 仍依赖模型理解；Receipt提交门禁独立 | 可减少旧assistant权威感，效果未验证 | 分离历史出处/当轮操作；仍不能单靠metadata强制重查 |
| 注入风险 | role文本仍可包含指令 | transcript分隔符/转义不能消除注入，严禁放高权限system | 错误信任client来源标签会造成伪认证 |
| Browser History | 全部不可信 | 全部不可信，不接受自由role | 无server Receipt时全部标unknown，不能从文本分类出可信facts |
| Server Receipt | 可选；若认证历史出处则必要 | 不需要它做普通文本上下文；认证来源另做 | 可信执行metadata需要server-owned receipt或可验证turn reference |
| 摘要 | 不需要 | 本项目短窗口先不摘要 | 先不做模型摘要，不提取自然语言为事实 |
| token/复杂度 | 小增量、最低实现/测试成本 | 单块framing开销；角色变化需做pronoun/provider对照 | metadata增加预算；版本/turn对应与降级测试最多 |
| 1 call/1 round/2requests | 保持 | 保持 | 保持 |
| Analysis | 无需影响 | Assistant-only | Assistant-only；共享协议若变动须单独评估 |
| 长期Memory/DB | 无必需 | 无必需 | 可用有界epoch内存ledger，无需DB；长期Memory另议 |

B 可以先对整个最多6pair窗口做qualification-only替代projection对照，不增加摘要、文本分类器或产品开关；未来是否只包较旧段由测量决定。C不能通过“回答中有DO/score字样”判为Tool来源，必须使用后端执行证明；Receipt是小型执行证明，不是第二份Raw Tool payload。

本节 A/B/C 是产品设计候选名称。下一阶段实验的 **控制 A** 必须是完全未修改的 current/native projection，不能提前套用本节候选 A 的“增强 provenance”，否则不再是当前行为的干净控制。

## 11. 推荐方案（基于本轮真实结果）

当前推荐**进入 Qualification-only Projection A/B 的设计审阅，暂不迁移产品**。H2 6/6 无调用、H6 3/6 无调用的真实信号已经足够值得做针对性对照；不再等待 H 样本，也不补跑本批次。

实验 A 保留当前原生历史 roles 与程序标签，实验 B 把相同历史投影为有界、不可信 transcript；仅比较投影方式。H2/H6 为主要目标，H5 为防过度重查约束，H1/H4 为正向历史控制。B 可以检验角色与 framing 的整体变化，但不是已证明更优的方案，不能从其成功进一步推出“只有 role 起作用”。

若需长期认证旧回答出处，再考虑 C 的小型 server-owned epoch receipt ledger。它应证明“过去执行过”，仍不能满足本轮 CURRENT_* Requirement。避免同时推出 History角色重构、来源ledger和Prompt改写，无法知道哪项起作用。

若 B 没有改善重查，或破坏 H5 的历史解释路径，保留当前产品投影，继续分离内容类型、措辞与历史边界的假设。不要为架构美观强推 B。

## 12. System Prompt 后续精简建议（仅研究）

当前 `SYSTEM_INSTRUCTION` 本轮未改，报告与plan记录SHA-256，可与基线对照。

| 规则组 | 建议 |
|---|---|
| 只读、授权Tool、单call/round、Tool Result不是指令、NO_DATA等诚实状态 | 长期规则，应保留；预算仍由程序独立执行。 |
| 当前查询/当前评分/项目背景的来源分工；Knowledge≠当前事实；Experimental评分 | 产品合同，应保留，但可合并重复句。 |
| 多次“旧值不能当前”“当前追问重查”“历史不是事实” | 部分弥补projection缺陷；History v2验证后压缩为统一historical/current边界，不直接全部删掉。 |
| “信息已经掌握则不调用”与“旧project-source claim” | 潜在歧义：历史提供的信息不等于本轮认证来源；未来明确区分历史解释与当前项目来源操作，不能本轮偷偷改Prompt。 |
| 普通知识、用户本轮提供值、项目知识依赖条件 | 可收敛为一次来源说明，保留“用户提供≠系统测量”。 |
| 纯文本格式、完成后不再Tool | 保留简短输出/协议要求；避免堆叠更多MUST。 |

来源Requirement目前不由自然语言router产生，产品默认AUTO；未来如何指定非AUTO属于另一个产品决策。Prompt不能替代确定性来源提交门禁。

## 13. Analysis 影响评估

Analysis使用固定Snapshot/Diagnosis/RAG捕获与自己的Prompt builder；本轮查阅代码没有上述Assistant History依赖。因此未来History v2应Assistant-only；共享Gateway、ModelMessage、ToolCallingService、RequestHandle与CredentialSnapshot无需为投影变化重写。Analysis已经捕获的Facts不得被历史/Tool覆盖。

## 14. Migration / Compatibility 风险

- 浏览器pair可伪造历史：任何server来源认证必须独立于客户端声明，不能把新增receipt JSON信任为真实后端执行。
- 有界server receipt ledger若被考虑：需明确epoch/model切换/清会话/刷新时的生命周期，不能因此默认引入账户、DB或Memory。
- 角色改变可能影响“刚才”、否定句、对话连续性；使用H5及更长synthetic fixtures测，不预判性能。
- 历史转structured block需限长、转义、明示不可信；不能把旧摘要升级为高权限指令。
- 新来源operation要求不得把合法NO_DATA/NOT_SCORABLE/NO_MATCH误拒绝；维持P1.1完成操作与payload区分。
- 当前历史字节预算并非完整输入token预算；未来按真实Usage评估，但本轮不新增自动tokenizer/摘要模型。
- 本轮H组只有每条件6个Qwen真实样本，不能把其统计或脚本化Mock扩大为跨模型/长期可靠性；未来投影变化须单独授权真实对照。

## 15. 下一阶段最小实验设计与验证记录

### 15.1 Qualification-only Projection A/B（仅提案）

| 维度 | A：Current/native projection | B：Untrusted historical transcript projection |
|---|---|---|
| 历史内容 | 原固定 fixture，不修改任何历史文本/顺序/时间 | 同一 fixture，同样的文本/顺序/时间 |
| 投影 | 完全复用当前 AssistantContextBuilder，历史 user/assistant roles 与当前程序标签均不变 | 在 qualification-only 边界把历史变成单一低权限 user 数据块，显式标识 untrusted historical transcript，保留 speaker/text/completed_at；最后独立追加当前 user question |
| System | 固定当前 System 与 hash | 相同 System，不增加新的系统规则/强制 Tool 指令 |
| 不允许 | 改措辞、强化Prompt、required tool_choice、自动执行或路由 | 提升到system、把旧声明认证成来源、摘要/删改历史、自然语言Intent Router |
| 来源提交 | 当前 P1.1 Requirement 与真实 Receipt | 相同合同；历史块不能生成 Receipt |

B 的容器应使用固定结构和 JSON 转义，不接受任意 role 或额外高权限字段。为识别“不可信历史”所需的固定数据 framing 属于投影变量；不得同时调整 SYSTEM_INSTRUCTION、Tool descriptions 或用户问题。该实验比较的是 **role/framing/表示方式整体**，不能声称单独隔离了 role 的贡献。两臂输入 tokens 可能不同，必须记录实际 Usage 与投影字节数，不能把额外 framing 成本隐藏。

产品 AssistantContextBuilder / Web 不加开关、不改生命周期。将来获准实现时，仅在 Harness 选择投影；正式 Runtime、CredentialSnapshot、Gateway、Registry、Executor、Receipt 和 1 call / 1 round / 2 requests 不变。EMPTY 在两臂应产生相同消息序列，先用离线 parity 锁定。

**建议最小真实授权单元（尚未授权、尚未实施）：**

- H2：同一 OLD_NO_DATA fixture、同一当前溶氧问题、CURRENT_OBSERVATION_QUERY；观察重查恢复。
- H6：同一 OLD_KNOWLEDGE_CLAIM fixture、同一项目知识问题、PROJECT_KNOWLEDGE_SEARCH；观察搜索恢复。
- H5：同一 OLD_DO_2_2 fixture、同一历史解释问题、AUTO；防止过度重查。
- 三条件各 A×6、B×6，共 36 独立 runs，最多 72 模型请求；retry=0、每请求输出最多256，不补跑失败。这是建议预算，**本轮不消耗任何次数**。
- 每个 case 六对交替 AB / BA，三 case 按轮交错，而非先跑完一臂。每 run 仍独立进程、只处理一个固定 manifest；安排顺序在执行前固定。
- 必须同时重新测 A，不以旧的本轮样本替代同期控制。若 A 不再复现 H2/H6 信号，应先报告变化，不能把前后批次差异当成 B 的效果。

**可选控制，需另列授权：** H1/H4 的 A/B 正向历史控制；使用 H6 完全相同当前问题的 EMPTY fresh 对照（建议6 runs、最多12请求），排除 Q4/H6 不同措辞的混杂。H0/H3 EMPTY 的协议 parity 先离线确认；若需要真实 Fresh control，也单列预算，不能自动扩大核心36 runs。

### 15.2 安全记录、验收与停止条件

记录 projection_id/version/hash、fixture/hash、当前问题hash、System/schema hash、精确模型/合同/协议、执行顺序、每轮 protocol calls/参数合法形状、operation Receipt、requirement、finish reason、request/network/transport counts、Usage 与安全错误。不保存历史/模型正文、query原文、Raw Tool Result、完整Prompt、Secret或Credential路径。

主要指标为 H2 的 observation_query_completed、H6 的 project_search_completed，以及 requirement satisfied；final completed、length 和 Provider/parity 错误独立报告。H5 要保留 no-tool direct answer 的合法 AUTO 路径；即使无调用全部通过，也只能证明协议层没有过度查，不能代替历史解释质量的人工评估。

先做离线资格验证：A保持当前消息与hash；B不把transcript提升成指令、不生成Receipt；EMPTY两臂相同；固定budgets/retry0；现有业务ContextBuilder未改。只有用户明确批准具体 manifest/臂/次数/预算后，才启动真实资格批次。凭据预检失败立即停；不改ACL、不复制Secret、不读源码根.env。普通失败保留，不补样本，不扩大到其他模型。

若 B 在同期对照中提升 H2/H6 且不破坏 H5，再提交产品迁移建议；不自动上线，也不把每臂6样本说成稳定性证明。若结果含糊、A漂移或B有回归，停止扩展并重新审阅假设。本阶段不创建A/B代码、manifest或新的授权执行命令。

### 15.3 上一阶段自动验证（历史记录，不是本次重跑）

| 检查 | 前阶段结果 |
|---|---|
| History fixture targeted | 18/18 |
| 原 Qualification targeted | 48/48 |
| Full Python | 926/926，31.350s |
| Full Browser | 188/188 |
| JS syntax | 通过；app.js未修改 |
| git diff --check | 通过 |
| 产品冻结核对 | Assistant/Source/Coordinator/Web/JS/Adapter/Policy/Preset内容与HEAD一致；忽略checkout换行差异 |
| Markdown / changed-file sensitive scan | 通过；不扫描或输出真实凭据内容 |

历史测试覆盖白名单fixture、禁止任意history/path/role/system、实际Web拒绝内部字段、当前builder投影、历史不认证Receipt、NO_DATA/AUTO、H6搜索、第二轮限制、脱敏、6turn/6KiB及Q3/Q4 plan hash保持。它们不代替本节真实实验。

### 15.4 本次结果分析检查与工作树

本次只更新这份研究记录，核对42份真实安全报告及Q4基线，未修改源码/测试/manifest，也没有执行Python/Browser回归或重新请求模型。检查各组6个独立run、69个真实请求、条件/预算、Tool choice、Provider parity、Receipt与总Usage；文档本地链接、diff空白检查与新增内容敏感检查通过。

分析前已有工作树变更继续保留：`assistant_qualification.py`、`qualification_history.py`、七个H manifest、qualification tests，以及STRUCTURE/records导航和本记录。3个tracked修改、10个untracked文件；本记录仍untracked。对src/tests/scripts共159个文件的内容指纹在分析前后保持一致；未commit/push。

## 16. Non-goals / 停止点

未实现History v2、Prompt调整、Intent Router、History语义黑名单、强制自动Tool、Multi-Tool/Multi-Round、Agent、Memory、DB、Knowledge/RAG改动、其他Provider实验、协议/Capability/Preset变更。正常用户H0–H6真实批次已经完成；Codex旧的零请求预检记录已排除。本次停止在结果分析和qualification-only A/B设计，等待用户审核，不自行实施投影、补跑或请求模型。

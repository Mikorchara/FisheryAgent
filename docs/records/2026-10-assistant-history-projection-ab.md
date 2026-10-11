# P2C：Model-Agnostic Assistant History Projection A/B Qualification

日期：2026-10-10。状态：正常用户 PowerShell 的 42 个真实 run 已完成；安全报告分析完成。只研究 qualification 投影，不迁移正式产品，不补跑。

## 1. Executive Summary

P2B 的 42 个真实样本发现：H2 OLD_NO_DATA 六次均直接回答、未查询；H6 OLD_KNOWLEDGE_CLAIM 三次搜索、三次直接回答。H1/H4 正向历史仍六次重查，H5 历史解释六次无 Tool。数据支持有针对性的投影对照，不能证明 assistant role 是唯一根因。前阶段数据见 [P2B 记录](2026-10-assistant-history-projection-research.md)。

本阶段新增 qualification-only 的 CURRENT_NATIVE 与 UNTRUSTED_TRANSCRIPT_V1，以及七个固定 manifest。A 调用现有 builder；B 只替换历史消息表示。正式 Assistant、System、Web、Analysis、Policy、Registry、Executor、来源合同和凭据架构保持不变。模型是否选 Tool 仍是概率行为，最终接受结果的规则不随模型改变。

Codex 早先 run `ee239f5bf61f4a9d903e314e7fe6eae0` 返回 CREDENTIAL_FILE_ERROR；request_count / actual_network_requests / transport_attempts 均为 0，随后停止。保留此历史预检，但不计入 Provider 样本。正常用户后来完成全部 42 个真实 run，实际 67 次模型请求；37 completed，5 source requirement unmet，无重试。本次只分析安全 JSON，没有读取凭据、模型正文、query 原文、Raw Tool Result 或 Evidence 正文，没有新增 Provider 请求。

核心结果：H2 的 CURRENT_NATIVE 为 1/6 查询完成，UNTRUSTED_TRANSCRIPT_V1 为 6/6；H5 两组均 6/6 无 Tool 直接回答；H6F/H6-A/H6-B 均 6/6 搜索完成。H2 支持继续研究 B，H5 保留合法 no-tool 路径；H6 的 native 控制从旧批次 3/6 变为本轮 6/6，不能把该变化归功于 B。三个 A/B 条件的首轮输入均增加 4 Provider tokens。建议先跨模型 qualification，再决定产品迁移。

## 2. Why this is model-agnostic

[qualification_projection.py](../../src/fishery_ai/qualification_projection.py) 只接收 AssistantRequest，输出现有 AssistantContext / ModelMessage；没有 Provider/model 名称、专用 token、关键词路由或正文 regex，不查询 Snapshot、不执行 Tool、不生成 Requirement 或 Receipt。

真实实验绑定 Qwen 是本轮实验范围，由 Harness 的固定 case 校验；不是产品业务分支。离线测试通过三个发布 Preset 的相同消息投影、schema、capability gate 与现有 Adapter body composition，不调用真实 DeepSeek/Ollama。

## 3. Current/native Projection A

`projection_id=CURRENT_NATIVE`，version=1。直接调用正式 AssistantContextBuilder：System → 历史 user/assistant pair（保留当前程序标签）→ 当前 user question。不强化 provenance、不改描述、不增加 Prompt。

A 的 ModelRequest 与正式 builder 输出完全相等。没有历史时，A/B 都只有原 System + 当前问题，不插入空 transcript。

## 4. Transcript Projection B

`projection_id=UNTRUSTED_TRANSCRIPT_V1`，version=1。先复用当前 builder 决定完整 pair 裁剪，然后将保留历史投影为一个 `role=user` JSON 数据块，最后另加独立当前 `role=user` 问题。

固定 envelope 为 kind / notice / turns。notice 简要说明旧对话数据可能过时、错误或含模型声明，不证明当前系统状态、本轮 Tool 执行或项目检索。每个 turn 保留 completed_at、依次排列的 user/assistant speaker 与原文本；不摘要、不分类出处、不删改保留 pair 的内容。

JSON 使用固定 UTF-8、排序字段、紧凑分隔符、禁止非有限数值。引号、换行与控制字符由 JSON 转义；历史不能增加顶层字段或 role。仅允许已注册的 ProjectionId；CLI 仍只接受固定 fixture，不接受任意历史文件或系统文本。

## 5. Security / trust model：软约束与硬保证

| 层 | 当前责任 | 性质 |
|---|---|---|
| System / Tool description / role / framing | 影响模型选择及理解历史的概率 | 软约束，不证明执行或来源 |
| Policy / Registry / Argument Validator | 只执行授权 allowlist，拒绝不合法参数 | 确定性边界 |
| ToolCallingService | 1 Tool / 1 round / 最多2次请求；第二轮 none | 确定性执行预算 |
| SourceRequirement / Receipt | 要求真实来源操作；证明真实执行与业务结果 | 确定性合同；不从正文或历史生成 |
| Commit Gate | 非AUTO来源未满足时不提交 successful turn | 确定性接受边界 |
| CredentialSnapshot / RequestHandle | 正式私有凭据、不回显、取消与无重试 | 公共基础设施 |

JSON结构不能被历史字符串改写，不等于模型一定忽略其中的恶意自然语言。B不是 Prompt Injection 沙盒；它只改变低权限语义表示。NO_DATA/NO_MATCH认证合法操作完成，不认证实际数值或证据命中；本阶段不改变P1.1语义。

## 6. Offline parity 与执行接入

[assistant_qualification.py](../../src/fishery_ai/assistant_qualification.py) 中窄的 `_ProjectionCoordinator` 校验输入确实等于正式 native Context，仅替换首次 ModelRequest，然后委托原 ToolCallingService。Request #2 的 tool_calls / role=tool / none 仍由共享 Coordinator 构造；AssistantService 的取消、来源推导、脱敏和提交门禁全部复用。

AssistantService 返回的 Context 计数仍表示原历史裁剪；实际发送消息的表示及成本由额外 projection metadata 记录。不会把B上下文暴露给Web或修改产品ContextBuilder。

报告记录 projection_id/version、projection_hash、projection_definition_sha256、fixture/question/System hash、实际 Registry schema hash、消息与历史块字节数。projection_hash 是首轮投影消息序列的 SHA-256，不含后来由Policy注入的tools；schema单独认证。definition hash认证固定framing定义，不认证模型可靠性。

System hash：`974cc942da1a909ee2f41c74aeb329fbfafe7aacd309aaeff90c9541e2843bc5`。

实际三Tool schema hash（含描述和参数）：`2f1c15a25dcfceb5225f52ba544656c08242fed3c6e1b118775f8b37c233a050`。凭据预检前 schema 不可用，报告为null，不能伪称已发送。

Q3/Q4 和P2B H0–H6的既有manifest文件及plan hash保持不变；旧H case不能通过新增字段偷偷变成A/B。本轮新增manifest如下，文件中的confirm_network仍为false：

| Case | Projection / fixture | plan_sha256 |
|---|---|---|
| H6F | CURRENT_NATIVE / EMPTY | 0195c180988b0090f255a0e68a9a41b54a2aca53419e332f1e2333aeaacce8bb |
| H2-A | CURRENT_NATIVE / OLD_NO_DATA | d793ea7e597bc52ce966d877358c59473144e3f5d6e5d4ad85551c9a1daf6a7f |
| H2-B | UNTRUSTED_TRANSCRIPT_V1 / OLD_NO_DATA | 75074ffc507ebac65887cdcc10f0931e3211122463fa3702daee090eee78a3f6 |
| H6-A | CURRENT_NATIVE / OLD_KNOWLEDGE_CLAIM | 03ba942052fdeb6e0a1dd60627bdbf1090f9e1585ded3705811ce60ad8c55620 |
| H6-B | UNTRUSTED_TRANSCRIPT_V1 / OLD_KNOWLEDGE_CLAIM | 811f4824187dbcddc7c612ebdc76c75a4accc88b0790bb24eff22fd65e1affd6 |
| H5-A | CURRENT_NATIVE / OLD_DO_2_2 | d16ae69be0c1d84206e7e70eba9395146baa988f2b8754ba6e6c535235342ef4 |
| H5-B | UNTRUSTED_TRANSCRIPT_V1 / OLD_DO_2_2 | c9667e3e59f9d13a3e0fc010b106a8a8074e878ee22c455882fcb5f14c7d6d3a |

## 7. H6-FRESH 与固定真实运行顺序

H6F 的当前问题、问题hash与Requirement完全等于H6，只移除历史；三个Tool保持同时暴露。它补足Q4/H6措辞不同的控制缺口。

本轮仅授权 `dashscope / openai_chat / https://dashscope.aliyuncs.com/compatible-mode/v1 / qwen3.8-flash`，Preset `dashscope-qwen38-flash-r1@1.0.2`，ProtocolSpec `dashscope_chat@1`。OFF / Normal、retry=0、每请求最多256 output tokens、每run最多2请求。42 runs最多84请求；普通失败保留不补跑。

在首次真实启动前固定以下顺序；每项均为新进程，只运行一个manifest：

| 位置 | 顺序 |
|---|---|
| 1–3 | H6F，H6F，H6F |
| 4–9 | H2-A，H2-B，H6-A，H6-B，H5-A，H5-B |
| 10–15 | H2-B，H2-A，H6-B，H6-A，H5-B，H5-A |
| 16–21 | H2-A，H2-B，H6-A，H6-B，H5-A，H5-B |
| 22–27 | H2-B，H2-A，H6-B，H6-A，H5-B，H5-A |
| 28–33 | H2-A，H2-B，H6-A，H6-B，H5-A，H5-B |
| 34–39 | H2-B，H2-A，H6-B，H6-A，H5-B，H5-A |
| 40–42 | H6F，H6F，H6F |

H6F三次在前、三次在后；各case有六对交替AB/BA，并按H2/H6/H5交错。该安排降低时间/缓存/负载混杂，不声称消除了混杂。旧P2B样本不能代替本轮A。

早先 Codex 第1项 H6F 在凭据预检停止。安全报告：`outputs/assistant-qualification/projection-ab/h6fresh/ee239f5bf61f4a9d903e314e7fe6eae0.json`；其 plan hash 与预登记值相同，tool_schema_sha256=null，因为实际 Registry 尚未组成。它不占后续真实批次的分母。

### 7.1 实验身份与顺序核验

七个指定目录共有 43 份 JSON；仅纳入 actual_network_requests > 0，按 run_id 去重后为 **42 个真实 run，每条件恰好6个，重复0个**。真实批次时间：2026-10-10 23:04:43–23:09:04（Asia/Shanghai）。

逐字段与当前七个固定 manifest 的 safe_plan、§6 预登记 plan hash 对照，并重新计算每份报告的 plan hash：preset、service/model/adapter/base_url、contract、ProtocolSpec、OFF、Normal、retry=0、2-request/256-token 预算、三 Tool、System、fixture/question hash、projection ID/version/hash/definition hash 均一致。报告中的实际 projection metadata 与 plan 一致；全部 67 请求的实际 Tool schema hash 等于 §6 的固定值，Knowledge required query=true；首轮 tool_choice=auto，第二轮为 none。

所有 A 都是 CURRENT_NATIVE@1，所有 B 都是 UNTRUSTED_TRANSCRIPT_V1@1。按 started_at 排序的 42 个 case 与 `run-order.txt` 及上表完全一致，run 之间无时间重叠。没有发现 manifest、身份、schema 或运行顺序漂移，故进入结果统计。

### 7.2 每条件结果

分母均为该条件6个真实 run。protocol call / direct answer 取首轮；direct answer 不等于 successful commit。correct/wrong 按指定 Tool 名判断，无调用不算 wrong。合法参数计数要求合法 call ID、arguments 形状及 Knowledge query；无调用记0，不能解释为参数无效。operation 来自真实 Receipt：H2 为 observation_query_completed，H6/H6F 为 project_search_completed；H5 AUTO 不要求 Tool 或操作，相关项不适用。

| 条件 | protocol Tool Call | direct answer | selected Tool | correct | wrong | arguments valid |
|---|---|---|---|---|---|---|
| H6F | 6/6 | 0/6 | search_fishery_knowledge × 6 | 6/6 | 0/6 | 6/6 |
| H2-A | 1/6 | 5/6 | get_current_water_quality × 1；无 × 5 | 1/6 | 0/6 | 1/6 |
| H2-B | 6/6 | 0/6 | get_current_water_quality × 6 | 6/6 | 0/6 | 6/6 |
| H6-A | 6/6 | 0/6 | search_fishery_knowledge × 6 | 6/6 | 0/6 | 6/6 |
| H6-B | 6/6 | 0/6 | search_fishery_knowledge × 6 | 6/6 | 0/6 | 6/6 |
| H5-A | 0/6 | 6/6 | 无 | 不适用 | 不适用 | 0/6（无调用） |
| H5-B | 0/6 | 6/6 | 无 | 不适用 | 不适用 | 0/6（无调用） |

| 条件 | operation completed | requirement_satisfied | final completed | truncated | Provider / normalized inconsistency | model mismatch |
|---|---|---|---|---|---|---|
| H6F | 6/6 | 6/6 | 6/6 | 0/6 | 0/6 | 0/6 |
| H2-A | 1/6 | 1/6 | 1/6 | 0/6 | 0/6 | 0/6 |
| H2-B | 6/6 | 6/6 | 6/6 | 0/6 | 0/6 | 0/6 |
| H6-A | 6/6 | 6/6 | 6/6 | 0/6 | 0/6 | 0/6 |
| H6-B | 6/6 | 6/6 | 6/6 | 0/6 | 0/6 | 0/6 |
| H5-A | 不适用 | 6/6（AUTO） | 6/6 | 0/6 | 0/6 | 0/6 |
| H5-B | 不适用 | 6/6（AUTO） | 6/6 | 0/6 | 0/6 | 0/6 |

| 条件 | request_count / actual_network_requests / transport_attempts | Provider Usage input / output / total |
|---|---|---|
| H6F | 12 / 12 / 12 | 14402 / 1114 / 15516 |
| H2-A | 7 / 7 / 7 | 8307 / 144 / 8451 |
| H2-B | 12 / 12 / 12 | 12300 / 169 / 12469 |
| H6-A | 12 / 12 / 12 | 15639 / 1118 / 16757 |
| H6-B | 12 / 12 / 12 | 14742 / 802 / 15544 |
| H5-A | 6 / 6 / 6 | 7524 / 628 / 8152 |
| H5-B | 6 / 6 / 6 | 7548 / 698 / 8246 |
| 合计 | **67 / 67 / 67** | **80462 / 4673 / 85135** |

共25 runs 进入 Tool 和第二请求，17 runs 首轮直接回答；后者12个 H5 AUTO 合法成功、5个 H2-A 未满足来源要求。每请求输出均不超过256 tokens，没有自动重试、补跑或额外探索。

## 8. H2 A/B

主要指标为 observation_query_completed；另统计 protocol call、correct Tool、arguments valid、Requirement、completed、direct answer、truncation/parity。CLI Store为空，合法NO_DATA也是查询完成，目标不是一定得到DO值。

### 8.1 H2-A 逐 run

序号为该条件内开始时间顺序；UNMET 表示 ASSISTANT_SOURCE_REQUIREMENT_UNMET。

| Run | run_id | Request #1 outcome / calls / finish | query completed / Requirement | Tool Result | Request #2 | 最终 |
|---|---|---|---|---|---|---|
| 1 | 075c9d1a7c77417593e2664af4c5cf10 | final_answer / 0 / stop | false / false | 未执行 | 未发生 | UNMET |
| 2 | 96df73f7f5f843838d0b5ba1312efb2d | tool_calls / 1 / tool_calls | true / true | NO_DATA | stop | completed |
| 3 | db9e77714f274266ad94fde4facb9b2f | final_answer / 0 / stop | false / false | 未执行 | 未发生 | UNMET |
| 4 | d2aba612ef5f4422a22392ba4baebaf6 | final_answer / 0 / stop | false / false | 未执行 | 未发生 | UNMET |
| 5 | 38fa41565faf46389fe6bc792f757108 | final_answer / 0 / stop | false / false | 未执行 | 未发生 | UNMET |
| 6 | aea57c27e0d947feba7265c2c7caedef | final_answer / 0 / stop | false / false | 未执行 | 未发生 | UNMET |

五次失败全部是 Provider 原始与 normalized 都无 tool_calls 的直接回答；错误 Tool、参数错误、执行错误、截断和归一丢失均未发生。唯一成功合法调用 get_current_water_quality，参数有效、call ID 合法，NO_DATA 查询完成且 Requirement 满足，第二轮 stop。提交门禁准确拒绝没有本轮查询来源的五个答案；不读取正文，不能推断答案是否复述旧 NO_DATA 或宣称已查询。

### 8.2 H2-B 逐 run

| Run | run_id | Tool / arguments / call ID | query completed / Requirement | Tool Result | 两请求 finish | 最终 |
|---|---|---|---|---|---|---|
| 1 | fe293db9e1a84383a721af4d98ad5933 | 查询 / 合法 / 合法 | true / true | NO_DATA | tool_calls / stop | completed |
| 2 | bde2edb14bf9460ab37f583f744fd308 | 查询 / 合法 / 合法 | true / true | NO_DATA | tool_calls / stop | completed |
| 3 | 2184bf33ab5943a591a62132fdf5ca27 | 查询 / 合法 / 合法 | true / true | NO_DATA | tool_calls / stop | completed |
| 4 | 83e68cbcabe84c5198912e1a567ea5de | 查询 / 合法 / 合法 | true / true | NO_DATA | tool_calls / stop | completed |
| 5 | a134c96be5d44116a0599552325d9bd7 | 查询 / 合法 / 合法 | true / true | NO_DATA | tool_calls / stop | completed |
| 6 | f464eb4fa3894695a1c83342efdc2116 | 查询 / 合法 / 合法 | true / true | NO_DATA | tool_calls / stop | completed |

“查询”均指 get_current_water_quality。A/B 共7次合法查询的 Receipt 都是 observation_query_completed=true、has_observation=false、sources=[]：NO_DATA 证明本轮真的查过，不证明取得了新传感器数值。

**本轮受控 Qwen 真实样本支持 UNTRUSTED_TRANSCRIPT_V1 相较 CURRENT_NATIVE 明显改善 OLD_NO_DATA 场景下的 current observation re-query reliability。** 同期为1/6→6/6，观察比例增加83.3个百分点；六对中五对为 A 未查询/B 查询、一对都查询。这里的明显改善是小样本观察差异，未进行统计显著性检验，也不证明长期成功率。B 同时改变 role、framing、representation，不能据此证明 role=assistant 是唯一根因。

## 9. H6 A/B

主要指标为 project_search_completed；另统计正确Knowledge、合法query、has_project_evidence / evidence_count、Requirement、final completed。NO_MATCH是合法搜索完成，不能与实际命中合并。

H6F、H6-A、H6-B 各6/6首轮合法调用 search_fishery_knowledge，query 存在且合法，call ID 合法。18次检索均 status=OK、project_search_completed=true、has_project_evidence=true、evidence_count=3，Requirement满足，第二轮 stop、最终 completed。没有 NO_MATCH、错误 Tool 或参数错误；命中数量不认证检索相关性、证据内容或最终答案质量。

H6F 前三次/后三次均成功，说明本轮 Fresh 同措辞条件可以触发搜索，但六个样本不是长期稳定性保证。本轮 H6-A/B 都为6/6，没有区分度，不能估计 B 对该条件的额外收益。

## 10. H5 A/B

AUTO历史解释可以无Tool完成。主要统计 direct no-tool 与Tool Call；B若导致频繁当前查询，属于回归信号。安全报表不读取正文，因此不能认证“刚才”的解释质量。

H5-A/B 均0/6 Tool Call、6/6 direct no-tool、6/6 AUTO completed；每run只有一次请求，finish_reason=stop，Receipt 无执行来源。unnecessary Tool Call 观察数两组均0/6。

这是重要 non-regression：本轮 B 未表现出“只要历史有旧水质数字就重新查”的过度查询，协议层保留合法 no-tool path。因未读取模型正文，不能认证历史解释的语言质量、是否准确理解语境或是否作出不实当前来源声明。

## 11. Control drift

| 来源操作指标 | 旧 P2B native | 本轮同期 A | 本轮同期 B | 本轮 Fresh |
|---|---|---|---|---|
| H2 当前查询完成 | 0/6 | 1/6 | 6/6 | 未新增 H2 Fresh；旧 H0 为6/6，仅历史参照 |
| H6 项目搜索完成 | 3/6 | 6/6 | 6/6 | H6F 6/6，同当前问题 hash |
| H5 合法 no-tool | 6/6 | 6/6 | 6/6 | 不适用 |

H2 native 从0/6到1/6已有批次波动，B 的判断仍只使用本轮同期1/6 vs6/6。H6 native 从旧3/6到新6/6出现 **control drift**；不得写“B 将 H6 从3/6提高到6/6”。H6F支持当前措辞本轮 Fresh 可用，本轮 H6 只能说明 A/B 都正常，没有额外收益估计。

原因尚未定位；Provider行为波动、批次时间/负载/缓存等均是未隔离因素，不能宣称其中任何一个已确认。相同hash和交替顺序降低实验输入漂移与时间混杂，不消除概率波动。旧Q4与H6问题措辞不同，也不能替代本轮 H6F。

## 12. Provider / normalized parity

仍使用现有QualificationAdapter的临时原始观察、安全归一摘要与精确一致性校验；不保存完整Provider response。记录finish_reason、model match、protocol调用计数、允许Tool名、参数合法形状、raw/normalized call与metadata consistency。正文模仿Tool Call不产生Receipt。

本批次67次请求的 Provider observation 全部可用，normalized_call_consistent、normalized_metadata_consistent、provider_model_matches 均为true；normalized同样model match。逐run inconsistency / model mismatch / truncated均0/6，全部实际call ID及参数合法；所有第二轮零 Tool Call、finish=stop。H2-A 五次无调用在原始与normalized两侧完全一致，没有Adapter吞掉Tool Call的证据。未发现本批次归一异常，不代表所有Provider响应形状均已覆盖。

## 13. Usage / token overhead

| Case | A消息序列字节 | B消息序列字节 | B额外字节 | B历史JSON块字节 |
|---|---|---|---|---|
| H2 | 3634 | 3760 | 126 | 443 |
| H6 | 3676 | 3802 | 126 | 464 |
| H5 | 3600 | 3726 | 126 | 404 |

H6F原生序列为3241 bytes；EMPTY下B字节/hash与A完全相同。这是canonical消息序列的UTF-8字节量，包含原System/当前问题，不含tools或Provider编码；不是tokens，也不是最终HTTP请求长度。

### 13.1 首轮输入开销

| 条件 | Request #1 input A 均值（范围） | B 均值（范围） | 六对 B−A 均值（范围） |
|---|---|---|---|
| H2 | 1253（1253–1253） | 1257（1257–1257） | +4（4–4）tokens |
| H6 | 1269（1269–1269） | 1273（1273–1273） | +4（4–4）tokens |
| H5 | 1254（1254–1254） | 1258（1258–1258） | +4（4–4）tokens |

三条件18对首轮输入都多4 tokens，这是本批次 Provider Usage 对投影整体改动的测量，不是把126 bytes换算成tokens，也不是所有模型/历史长度的通用开销。

### 13.2 Whole-run 成本与缓存

| 条件 | A 全run总tokens均值 | B 全run总tokens均值 | A/B 请求数分布 |
|---|---|---|---|
| H2 | 1408.50 | 2078.17 | A：五个1请求、一个2请求；B：六个2请求 |
| H6 | 2792.83 | 2590.67 | 两组均六个2请求 |
| H5 | 1358.67 | 1374.33 | 两组均六个1请求 |

各组 input/output/total 总量见§7.2。H2-B 多发生五次第二轮请求，whole-run差异包含恢复Tool闭环的成本，不能当作 transcript framing overhead。H6 的 whole-run 总量反而较低，但第二轮上下文及生成量不是固定相等，不能据此认定 B 必然节省成本。H5 多出的94总tokens中，输入增加24、输出增加70；输出波动不属于输入framing开销。

67请求 Usage 全部来自 Provider，每run合计与逐请求字段求和一致。cached_input_tokens 可用：H6F=9216、H2-A=6144、H2-B=6144、H6-A=10240、H6-B=11264、H5-A=6144、H5-B=6144，共55296；它是80462 input tokens中的缓存统计，不另加到total，不推算费用。reasoning_tokens 未返回，记 unavailable，不记0。

## 14. Evidence limits 与产品迁移建议

B同时改变role、framing和表示方式；成功不能证明role=assistant是唯一根因。每条件6样本、一个模型、单pair固定synthetic历史，不能推广到长期/跨模型/Web复杂对话。结构转义也不能证明模型免疫指令注入。

| 决策 | 本轮建议 | 依据 |
|---|---|---|
| A：B是否值得继续？ | 是，进入受控跨模型qualification设计 | H2同期1/6 vs6/6；H5保留6/6合法无Tool；首轮开销+4tokens |
| B：是否足够直接迁移正式产品？ | 否，当前产品History保持不变 | 仅Qwen、每条件6个样本、H6控制漂移、未审阅正文质量，尚未验证复杂/长历史 |
| C：迁移前是否需要跨模型qualification？ | 是，优先DeepSeek和Ollama的H2/H5对照 | 项目目标是模型无关Runtime，不能用Qwen结果替代其他模型真实证据 |

本轮支持的是候选投影的可研究性，不是长期可靠性、恶意历史防护或发布资格。真实验证仅覆盖Qwen 3.8 Flash；不能宣称DeepSeek/Ollama真实行为已通过或B对所有LLM有效。Source Contract / Receipt / Commit Gate 的确定性约束仍须保留，projection不能代替它们。

## 15. Model-Agnostic Reliability Architecture

| Layer | 边界 |
|---|---|
| 1 Provider Adapter | 协议编码、传输、响应归一；真实协议兼容差异归此层 |
| 2 Capability Contract | 精确模型Tool/Thinking/Streaming支持及组合限制 |
| 3 Conversation Projection | 统一历史、当前问题、来源framing，不按模型名改变业务语义 |
| 4 Tool Runtime | Policy ∩ Registry ∩ Executor，静态allowlist及参数/预算 |
| 5 Source Contract | Requirement定义操作要求；Receipt来自真实执行 |
| 6 Commit Gate | 按完整响应、取消、来源要求决定是否接受successful turn |

**Model behavior can vary. Application invariants must not.** 软约束可优化选择概率；确定性正确性/安全约束不能靠不断堆Prompt“必须”来替代。

## 16. Cross-model qualification plan

以下仅为下一阶段设计，未创建新manifest、未授权或执行真实请求。优先模型：DeepSeek Flash、Ollama Qwen3.5 4B；从届时正式Preset加载精确Identity与OFF/Normal合同，使用现有Runtime / CredentialSnapshot / Gateway，不能复制Qwen资格。当前H case校验仍固定Qwen，不能直接改现有manifest的preset执行；未来需先在qualification-only计划校验中登记各模型独立case/预算，离线通过后再申请一次有限批次授权，不改产品业务层。

建议先做一个模型，再审阅另一模型的独立预算。每模型核心四条件 H2-A/H2-B/H5-A/H5-B 各6次：**24 runs、最多48模型请求**。保留原固定问题、fixture、三Tool、System/schema、Requirement、每请求≤256 tokens、retry=0、1 Tool/1 round/最多2请求；唯一实验变量仍为A/B projection。模型间不要求回答文字相同，实际序列化消息hash可核对一致，模型Identity/ProtocolSpec/plan hash则须分别预登记。

**建议增加每模型H2 Fresh控制6次**：与H2相同当前问题、EMPTY history、同三Tool和查询Requirement，前三次/后三次包围交替的四条件批次。这样能区别基础Tool调用失败与OLD_NO_DATA历史影响；旧Qwen H0不能替代新模型Fresh。含Fresh为每模型30 runs/最多60请求，两模型合计60 runs/最多120请求。若只批准核心四条件，则48 runs/最多96请求，明确缺少Fresh归因控制。H6本轮没有区分度，首批不扩展H6矩阵。

模型选择和预算属于一次明确批准的qualification run/batch，不是永久联网权限。真实失败不补样本、不自动修改Prompt/合同；凭据预检错误按原规则停止。交替AB/BA、条件交错，每run独立进程；分析前核对计划、实际schema、顺序和模型一致性，零请求预检不入分母。

指标：当前问题正确查询/Requirement满足、H5合法no-tool、参数/归一一致性、截断/取消/错误、首轮与whole-run Usage；安全JSON不能认证自然语言质量。根据每模型结果给研究资格 Qualified / Conditional / Not Qualified 及证据边界，不自动改变发布合同。失败时考虑qualification状态、UI warning、feature restriction或safer mode；不在核心写 `if model == ...` 特殊业务路由。

架构层面：projection helper无模型/Provider分支、ModelMessage通用、三Preset离线composition兼容，来源和提交合同也与模型无关。行为层面：本轮只有Qwen真实样本，**离线composition通过不等于跨模型真实qualification通过**。

## 17. Analysis impact / Prompt implications

正式AssistantContextBuilder、SYSTEM_INSTRUCTION、app.js、Analysis未修改。Projection helper只供Harness使用；既有固定Analysis与Assistant公共执行栈仍完整复用。本阶段不精简或强化System，不改Tool描述，不从自然语言推导Requirement。

## 18. 自动验证与本次分析检查

下表是P2C实现阶段已完成的回归记录；本次只更新分析文档，未重跑Python/Browser，不把历史结果写成本次新执行。

| 检查 | 结果 |
|---|---|
| 新Projection targeted | 29项：28通过、1跳过 |
| P2B History targeted | 18/18 |
| 原Qualification targeted | 48/48 |
| Full Python | 955项：954通过、1跳过，31.136s |
| Full Browser | 188/188 |
| JS syntax | 通过；JS未修改 |

跳过项是真实目录symlink建立（当前Windows环境无法创建测试所需的链接）；替代的reparse拒绝测试通过。其余覆盖A parity、EMPTY parity、顺序/speaker/时间、JSON注入形状、模型无关、三Preset离线composition、Web拒绝内部字段、老manifest/hash、无来源提交拒绝、NO_DATA、Knowledge、H5无预取、预算、取消、私有Credential优先级、报告脱敏和固定输出边界。

P2C实现阶段新增helper、29项测试、七个manifest与本记录；修改Harness与文档导航。前阶段未提交工作树继续保留，不覆盖P2B报告与旧manifest。实现阶段相对当时基线的唯一既有Python修改是assistant_qualification.py。本次结果分析没有再次改动该文件；本次前后指纹检查单独记录于§21。

实现阶段Codex仅产生一份ignored安全preflight JSON；后续正常用户产生42份真实安全报告。本次分析只读取这些安全报告、固定manifest和相关源码/文档，未接触真实凭据、源码.env、ACL或生产项目。身份/顺序/Usage校验均通过；只修改本记录，其他src/tests/scripts/docs文件以本次分析前后的SHA-256核对。Markdown本地链接、记录敏感/空白扫描、git diff --check及最终工作树检查见§21。

## 19. Non-goals / 停止点

不实施正式History v2、Prompt/Web迁移、Intent/keyword router、第二套Assistant或Tool loop、Memory/DB、Agent、Multi-Tool/Multi-Round、Capability/Preset/Policy/Handler变更。当前批次已结束，**不再调用任何Provider，不补跑，不执行§20历史命令**；跨模型方案仅供审阅。没有读取/复制Key、改ACL或读源码.env。等待用户审核，不commit/push。

## 20. 历史：已结束批次的正常用户PowerShell命令

**HISTORICAL / 已完成，以下仅保留批次执行证据，不可用于补跑。** 当时授权七条件各6次、42个真实run、最多84请求；正常用户现已执行完整批次，实际67请求。五次普通失败也是已执行样本，不得补第7次。此旧命令及旧授权均不赋予新的联网资格；下一阶段必须另行明确批准。本次没有执行以下代码。

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
$abRoot = (Get-Location).Path
$abReports = Join-Path $abRoot 'outputs\assistant-qualification\projection-ab'
if (Test-Path -LiteralPath $abReports) {
    foreach ($abFile in (Get-ChildItem -LiteralPath $abReports -Filter '*.json' -File -Recurse)) {
        $abOld = Get-Content -LiteralPath $abFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($abOld.actual_network_requests -gt 0) {
            throw '已有真实P2C样本；先盘点剩余授权，不得从头重跑。'
        }
    }
}
$abHashes = @{
    'H6F' = '0195c180988b0090f255a0e68a9a41b54a2aca53419e332f1e2333aeaacce8bb'
    'H2-A' = 'd793ea7e597bc52ce966d877358c59473144e3f5d6e5d4ad85551c9a1daf6a7f'
    'H2-B' = '75074ffc507ebac65887cdcc10f0931e3211122463fa3702daee090eee78a3f6'
    'H6-A' = '03ba942052fdeb6e0a1dd60627bdbf1090f9e1585ded3705811ce60ad8c55620'
    'H6-B' = '811f4824187dbcddc7c612ebdc76c75a4accc88b0790bb24eff22fd65e1affd6'
    'H5-A' = 'd16ae69be0c1d84206e7e70eba9395146baa988f2b8754ba6e6c535235342ef4'
    'H5-B' = 'c9667e3e59f9d13a3e0fc010b106a8a8074e878ee22c455882fcb5f14c7d6d3a'
}
$abOrder = @('H6F', 'H6F', 'H6F')
for ($abPair = 1; $abPair -le 6; $abPair++) {
    $abArms = if ($abPair % 2 -eq 1) { @('A', 'B') } else { @('B', 'A') }
    foreach ($abCase in @('H2', 'H6', 'H5')) {
        foreach ($abArm in $abArms) { $abOrder += "$abCase-$abArm" }
    }
}
$abOrder += @('H6F', 'H6F', 'H6F')
if ($abOrder.Count -ne 42) { throw '固定顺序异常。' }
New-Item -ItemType Directory -Path $abReports -Force | Out-Null
$abSchedule = Join-Path $abReports 'run-order.txt'
if (-not (Test-Path -LiteralPath $abSchedule)) {
    $abOrder | Set-Content -LiteralPath $abSchedule -Encoding UTF8
} else {
    $abSavedOrder = @(Get-Content -LiteralPath $abSchedule -Encoding UTF8)
    if (($abSavedOrder -join ',') -ne ($abOrder -join ',')) { throw '已有顺序记录不一致，停止。' }
}
for ($abIndex = 0; $abIndex -lt $abOrder.Count; $abIndex++) {
    $abId = $abOrder[$abIndex]
    $abManifest = "scripts/manifests/assistant-$abId.json"
    $abPlanText = & .\.venv\Scripts\python.exe scripts/qualify_assistant_turn.py --manifest $abManifest --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'dry-run失败，停止。' }
    $abPlan = $abPlanText | ConvertFrom-Json
    if ($abPlan.plan.plan_sha256 -ne $abHashes[$abId]) { throw '实验plan变化，停止。' }
    $abLine = & .\.venv\Scripts\python.exe scripts/qualify_assistant_turn.py --manifest $abManifest --confirm-network
    $abExit = $LASTEXITCODE
    $abSummary = $abLine | ConvertFrom-Json
    if (-not $abSummary.report -or $abExit -notin @(0, 1)) { throw 'CLI未留下正常安全报告，停止。' }
    $abPath = [IO.Path]::GetFullPath((Join-Path $abRoot $abSummary.report))
    if (-not $abPath.StartsWith($abReports + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw '安全报告路径异常，停止。'
    }
    $abSafe = Get-Content -LiteralPath $abPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($abSafe.plan.plan_sha256 -ne $abHashes[$abId] -or $abSafe.actual_network_requests -gt 2) {
        throw '报告身份或预算异常，停止。'
    }
    Write-Host "$($abIndex + 1)/42 $abId : $($abSummary.status) / $($abSummary.error_code) / requests=$($abSafe.actual_network_requests)"
    if ($abSummary.error_code -eq 'CREDENTIAL_FILE_ERROR') { throw '凭据预检失败，停止全部剩余运行。' }
    if ($abSummary.error_code -in @('SECRET_MISSING', 'QUALIFICATION_UNSAFE_LOGGING', 'QUALIFICATION_REPORT_ERROR')) {
        throw '本地安全预检或存储异常，停止。'
    }
}
```

当时每次confirm是独立进程、一个manifest，报告写入h6fresh或h2/h6/h5的a/b目录；dry-run不请求Provider。此说明只解释已结束批次的产生方式。本报告不提供读取凭据的命令。

## 21. 最终工作树

未commit/push。保留原有P2B工作树，同时增加P2C文件：

`git diff --stat`（仅tracked，包含原P2B变更）：3 files changed，127 insertions，8 deletions。untracked共20个文件，不计入该stat。

- tracked修改：docs/STRUCTURE.md、docs/records/README.md、src/fishery_ai/assistant_qualification.py。
- 原untracked：P2B研究记录、七个H0–H6 manifest、qualification_history.py、test_qualification_history.py。
- 新untracked：本记录、七个P2C manifest、qualification_projection.py、test_qualification_projection.py。
- ignored生成：projection-ab下42份真实安全JSON、一份0-request preflight及run-order.txt；均保留原文件，不进入Git。

本次新增变更只有本记录内容；其他既有未提交变更完整保留。真实结论为：Qwen的H2支持继续研究B，H5无协议层回归，H6有control drift且无同期A/B收益差异；尚不足发布正式History v2或宣称跨模型Qualified。完成后停止，等待审阅，不改任何发布合同。

本次检查：195个非缓存src/tests/scripts/docs文件中只有本记录SHA-256改变，其他194个不变、无删除。100个本地Markdown链接全部有效；本记录敏感字面量/私有凭据路径/尾随空白扫描无发现；git diff --check通过，仅提示已有tracked文件将按Git设置转换LF/CRLF。ignored报告与顺序文件未跟踪。因本次仅改Markdown，未重跑Python/Browser；§18保留的是实现阶段既有955项Python、188项Browser回归结果。未commit/push。

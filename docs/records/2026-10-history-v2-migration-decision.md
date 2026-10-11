# P2E 结果审计与 History v2 迁移决策

日期：2026-10-11。数据：用户完成的30份真实安全JSON；本次Codex新增Provider请求 **0**。

## 1. Executive Summary

最终决策：**READY_FOR_FEATURE_FLAGGED_MIGRATION**。

这仅表示B有资格进入可回滚、受内部feature flag控制的产品迁移阶段。本轮没有迁移正式History，没有删除A，没有重新资格认证Preset，也不保证长期可靠。

P2E严格执行30个固定position，实际50次Provider请求/50次transport attempts。26个资格结果completed，4个failed；四次失败均为A的首轮直接回答、没有Tool，因当前查询Requirement未满足被Commit Gate拒绝。不存在Provider/Adapter/Tool执行异常。

B的15个run全部completed：12个来源操作要求全部满足，3个历史解释样本均无Tool。**本轮migration screening未观察到阻塞性回归**。但Ollama P2D曾有B漏查和历史解释额外查询，不能用本轮单次样本抹去该风险。

## 2. Experimental Integrity

安全报告目录：`outputs/assistant-qualification/product-migration/<model>/<scenario>/<arm>/<run_id>.json`。

- JSON总数30，`actual_network_requests>0`恰好30，0-request报告0，无法解析0；run_id唯一，无重复/遗漏/第31项。
- 按`started_at`排序的case与[冻结索引](../../scripts/manifests/product-migration/qualification-plan.json)position 1–30完全一致；相邻run无时间重叠。
- 每份plan与其当前冻结manifest的safe_plan逐字段相等，唯一预期授权变化为`network=AUTHORIZED_FOR_THIS_RUN`；30个plan_sha256与索引一致。
- OFF / Normal / retry=0 / max_requests=2 / 每请求输出上限256；实际每run为1或2请求，每次Usage报告的输出均未超过256。
- 首轮auto、第二轮none；每请求暴露同样三个正式Tool，Knowledge schema包含required query。20个实际调用均只有一个合法Tool Call；第二轮Tool Call为0。
- 50个Provider安全观测均available、model match=true、raw/normalized calls与metadata一致；无调用摘要截断。
- fixture/question、projection definition/messages、裁剪与保留pair哈希均与冻结manifest及本地确定性重建一致。未读取模型正文来判定成功。

| 模型 | 精确Identity：service / adapter / normalized URL / model | Preset合同 | ProtocolSpec |
|---|---|---|---|
| Qwen 3.8 Flash | dashscope / openai_chat / https://dashscope.aliyuncs.com/compatible-mode/v1 / qwen3.8-flash | dashscope-qwen38-flash-r1@1.0.2 | dashscope_chat@1 |
| DeepSeek Flash | deepseek_api / openai_chat / https://api.deepseek.com / deepseek-flash | deepseek-flash-r1@1.0.2 | deepseek_chat@1 |
| Ollama Qwen3.5 4B | ollama / generic_openai_chat / http://127.0.0.1:11434/v1 / qwen3.5:4b | ollama-qwen35-4b-r1@1.0.2 | ollama_openai_chat@1 |

固定System SHA256：`974cc942da1a909ee2f41c74aeb329fbfafe7aacd309aaeff90c9541e2843bc5`。

固定三Tool schema SHA256：`2f1c15a25dcfceb5225f52ba544656c08242fed3c6e1b118775f8b37c233a050`。

索引字节SHA256：`5153dd52f3f0e335493c1abe9b8ab2a1d5579cd29a82b515bd48960e98bd1718`。

真实执行时间为UTC 05:53:47.737608至05:56:53.275504（北京时间13:53:47至13:56:53）。按执行时间顺序对相对文件名与文件字节串累计SHA256：`6c46c6e3174f815c629c3b888854e895f2a39aa803f6e9f2d31da3700afd4a59`，用于确认本次只读审计未改变原始报告；它不替代各plan验证。

## 3. P2E Results

总体仅作描述性计数，不把不同模型/场景合并为“统一成功率”。completed表示资格合同通过，不表示正文正确。

| 项目 | 数量 |
|---|---:|
| 实际run / 固定position | 30 / 30 |
| completed / failed | 26 / 4 |
| Provider请求 / transport attempts | 50 / 50 |
| 首轮protocol Tool Call / 无Tool直接回答 | 20 / 10 |
| 当前水质查询 / Knowledge搜索 / 评分 | 18 / 2 / 0 |
| 合法参数 / 非法参数 | 20 / 0 |
| wrong Tool / 截断 | 0 / 0 |
| raw-normalized不一致 / model mismatch / 网络错误 | 0 / 0 / 0 |
| Input / Output / Total tokens | 77,211 / 2,067 / 79,278 |

10个无Tool样本中，6个是S3合法历史解释，4个是来源要求不满足的失败。18次水质查询全部NO_DATA；2次Knowledge均OK、每次3条Evidence。各run的实际请求数、Usage合计均与其request行一致，50次请求都有Provider Usage。

| 模型/arm | run | 来源操作要求满足（不含AUTO） | completed | Tool / no-tool | 请求 |
|---|---:|---:|---:|---:|---:|
| Qwen A | 8 | 4/7 | 5 | 4 / 4 | 12 |
| Qwen B | 8 | 7/7 | 8 | 7 / 1 | 15 |
| DeepSeek A | 3 | 2/2 | 3 | 2 / 1 | 5 |
| DeepSeek B | 3 | 2/2 | 3 | 2 / 1 | 5 |
| Ollama A | 4 | 2/3 | 3 | 2 / 2 | 6 |
| Ollama B | 4 | 3/3 | 4 | 3 / 1 | 7 |

## 4. Scenario-by-Scenario Review

每格只有**1个样本**。Q=合法get_current_water_quality调用、查询操作完成、Requirement满足、最终completed；K=同样条件下的search_fishery_knowledge；D=无Tool直接回答、AUTO满足、completed；F=无Tool直接回答、查询Requirement未满足、failed。

| 场景 | 模型 | A | B | 核对结论 |
|---|---|---|---|---|
| S1 多轮OLD_NO_DATA | Qwen | F | Q | B恢复本轮查询 |
| S1 | DeepSeek | Q | Q | 两种表示兼容 |
| S1 | Ollama | F | Q | B恢复本轮查询 |
| S2 旧有效值+NO_DATA | Qwen | F | Q | A没有调用Tool，B真实查询 |
| S3 历史解释 | Qwen | D | D | 无额外查询 |
| S3 | DeepSeek | D | D | 无额外查询 |
| S3 | Ollama | D | D | 无额外查询 |
| S4 当前省略式追问 | Qwen | F | Q | B用历史理解当前追问，并取得本轮查询Receipt |
| S4 | Ollama | Q | Q | A/B均重新查询 |
| S5O 旧来源声明+当前观测 | Qwen | Q | Q | 本轮protocol调用与查询Receipt对应 |
| S5K 旧来源声明+Knowledge | Qwen | K | K | 本轮真实搜索，非历史声明认证 |
| S6 文字仿Tool Call | Qwen | Q | Q | 当前合法调用来自Provider protocol，未额外执行历史文字 |
| S7 长History裁剪 | Qwen | Q | Q | 保留pair一致，查询/提交均正常 |
| S7 | DeepSeek | Q | Q | 同上 |
| S7 | Ollama | Q | Q | 同上 |

S3六个样本均首轮无Tool、finish_reason=stop、AUTO satisfied、completed，这是重要no-tool non-regression；不评价解释质量。S4支持“历史用于理解指代，当前事实仍需新操作”的设计，不能仅凭安全报告确认模型内部如何理解指代。

### 四次失败

| position | Case | run_id |
|---:|---|---|
| 1 | Qwen S1-A | 41f663a991ae46469c15f10eaf82f4d8 |
| 5 | Ollama S1-A | 0ad0686eb86543e199b6d1c2d974a333 |
| 20 | Qwen S2-A | 47faab84ff684a62af5e197b4ed9d22a |
| 21 | Qwen S4-A | 37240a5c798b4b3e8edd698ecc3d2985 |

四者完全相同的协议/执行模式：Request #1 outcome=final_answer，Provider原始与normalized tool_calls均0，finish_reason=stop；没有本地Tool执行，Receipt等于空Receipt，operation_completed=false、requirement_satisfied=false；仅1次请求，无Request #2；safe code均为`ASSISTANT_SOURCE_REQUIREMENT_UNMET`。

因此分类为 **Model selection / context behavior failure**。不是Provider失败、Adapter吞调用、参数非法、Tool Runtime失败、来源合同失败或截断。Commit Gate正确阻止其作为来源要求已满足的successful turn提交。未读取正文，不能判断这四个回答具体复用了什么值或作了什么声明。

## 5. Source / Receipt Invariants

- 10个无protocol调用的run全部空Receipt，包括4个Requirement失败与6个AUTO成功；没有由模型文字或历史自动授予来源。
- 18次查询得到NO_DATA：`observation_query_completed=true`，`has_observation=false`，sources为空。查过但无Snapshot是合法业务结果，不是“没有执行”。
- S5K两次搜索得到OK：`project_search_completed=true`、`has_project_evidence=true`、evidence_count=3、来源仅RETRIEVED_PROJECT_EVIDENCE；不能推广为当前水质事实，也没有评价Evidence相关性。
- 20个非空操作Receipt的tool_name/status与本轮合法protocol调用、实际tool_execution_status对应；Request #2正常stop且无新Tool。
- 重建有限typed Receipt后，纯确定性`requirement_satisfied()`与所有报告的布尔一致。所有successful run均满足本次Requirement；未满足的4轮全部failed。
- 当前`receipt_from_execution()`只接受T3实际执行对象与关联call_id/ToolResult，不检查模型正文或History。历史仿调用、旧来源声明不能创建执行对象；此前P1/P2E的scripted测试锁定无协议调用时的拒绝语义。

**证明范围：** S5/S6真实样本均选择了Tool，能确认本轮Receipt有真实操作支撑、历史文字没有增加执行次数。它们不是“模型漏调时的同一场景”真实反事实测试；硬边界还依据当前源码与既有离线imitation/claim测试，而非仅凭30个正负样本推断。没有声称模型正文从未虚构“已查询”。

## 6. Trimming / Projection Integrity

15对A/B在进入投影差异前的保留pair数量、顺序、逐pair hash、原生history bytes与trimmed count全部一致。System与当前问题保持独立，最后一条仍是当前user question。B envelope解析为正确turns/messages结构，不产生半turn；A消息数为2×保留轮数+2，B为System/transcript-user/current-user三条。

S7三个模型六个run一致：收到7轮，先取最后6轮，再按6KiB裁掉完整最旧pair，保留原fixture序号2–6共5轮，trimmed=2；native pair序列5,390 bytes，B transcript=5,879 bytes。6KiB限制针对native pair序列，不是B包装或整个请求；不再为B额外裁剪。

保留pair按顺序的SHA256：

```text
a8bc430ef392f62462bccc24bf8b3af6f731ea2aba4b7a66097ab4915cfe8bbc
e52aa938ed3f488665264c5c17cf7725a0c73171918e5b1a2fd5febb249d92b6
982c9cdc67c1ca62703ea788c29bf0ee8e78ac79b45f09dabe5d0702ae350100
712970a0587227731c426179148b75765f4f753e9d3b18ee4612553a0e0c0776
5c6266dee494fbb36e13e7414182ab3c23c025de163d2405aa5328fb876d0275
```

S7全部6个run均合法查询NO_DATA、Requirement满足、completed。报告保存消息/fixture哈希，不保存实际发送正文；边界核验通过确定性重建、报告元数据与`_ProjectionCoordinator`的原生上下文相等检查相互印证，不宣称进行了Provider wire全文重放。

## 7. Cross-Model Evidence

依据：[Qwen P2C](archive/history-v2-research/2026-10-assistant-history-projection-ab.md)、[DeepSeek P2D](archive/history-v2-research/2026-10-deepseek-history-projection-results.md)、[Ollama P2D](archive/history-v2-research/2026-10-ollama-history-projection-results.md)。跨阶段只比较方向，不累加为统计显著率。

| 模型 | 既有阶段 | P2E | 解读 |
|---|---|---|---|
| Qwen | P2C OLD_NO_DATA：A查询1/6、B 6/6；H5两组no-tool 6/6 | S1/S2/S4 A漏查、B查询；S3两组no-tool；其他选中场景兼容 | 在更复杂形状中重复出现有利于B的方向，仍非长期稳定性证明 |
| DeepSeek | P2D Fresh/A/B查询均6/6；H5两组no-tool | S1/S7两组查询，S3两组no-tool | 至少兼容B，没有观察到改善或退化 |
| Ollama | P2D Fresh 6/6、A 2/6、B 5/6；H5-B 1/6额外查询 | S1 A漏查/B查询；S4/S7两组查询；S3两组no-tool | 支持B的总体方向，但既有B漏查/过度查询风险仍存在 |

Control drift：Qwen Knowledge native组从P2B H6的3/6变为P2C H6-A的6/6，P2C同期A/B均6/6；该变化不能归功于B。P2E S5K两组各一次搜索成功同样不能证明Knowledge选择被B改善。

P2E每条件只有一次，没有同期Fresh组，不与P2D/P2C不同时间、不同History的Fresh样本冒充完全相同对照。单次S3无额外查询不能否定Ollama此前的regression signal。

## 8. Behavioral Trade-offs

CURRENT_NATIVE保留原生user/assistant交互结构与较强对话连续性；DeepSeek等模型在当前固定条件下本来就能正确工作。风险是Qwen/Ollama若干旧NO_DATA/混合/省略追问条件下选择了无Tool路径。报告支持context行为相关的失败，不能证明“assistant role是唯一根因”或模型确实认为旧答复已解决问题。

UNTRUSTED_TRANSCRIPT_V1把同样保留的历史表达为带speaker/时间的未受信任JSON数据，明确区分当前问题。Qwen/Ollama多个条件下重查改善，DeepSeek未观察到破坏。风险包括历史解释额外查询、漏查仍可能出现、包装/标签成本依History和tokenizer而变，以及未受检验的对话连续性/解释质量。

B是提高正确路径选择概率的**Context Architecture**，仍是soft context mechanism，不是执行保证或注入防御沙箱。Tool Policy/Validator限制可执行操作，Receipt证明真实操作，Requirement与Commit Gate限定成功提交；这些硬边界不能由B代替。

## 9. Usage Cost

`canonical bytes`指safe metadata中的UTF-8 canonical ModelMessage序列（含System/当前问题），不是HTTP请求体字节，也不含tools schema。native history pair bytes与B transcript bytes是另两个指标。首轮input tokens来自Provider Usage；whole-run包含实际Request #2，不能当作framing成本。

| 模型/场景 | canonical bytes A→B | Request #1 input A→B | 差值 | whole-run Total A→B | 请求 A/B |
|---|---:|---:|---:|---:|---:|
| Qwen S1 | 4,428→4,186 | 1,474→1,384 | -90 | 1,521→2,332 | 1/2 |
| Qwen S2 | 4,411→4,169 | 1,472→1,382 | -90 | 1,486→2,346 | 1/2 |
| Qwen S3 | 4,388→4,146 | 1,470→1,380 | -90 | 1,592→1,523 | 1/1 |
| Qwen S4 | 4,376→4,134 | 1,468→1,378 | -90 | 1,482→2,340 | 1/2 |
| Qwen S5O | 4,451→4,209 | 1,479→1,389 | -90 | 2,574→2,362 | 2/2 |
| Qwen S5K | 4,472→4,230 | 1,486→1,396 | -90 | 3,311→3,115 | 2/2 |
| Qwen S6 | 4,452→4,232 | 1,489→1,401 | -88 | 2,600→2,404 | 2/2 |
| Qwen S7 | 9,894→9,284 | 2,547→2,363 | -184 | 4,686→4,315 | 2/2 |
| DeepSeek S1 | 4,428→4,186 | 1,402→1,390 | -12 | 2,412→2,378 | 2/2 |
| DeepSeek S3 | 4,388→4,146 | 1,399→1,387 | -12 | 1,457→1,440 | 1/1 |
| DeepSeek S7 | 9,894→9,284 | 2,415→2,355 | -60 | 4,450→4,352 | 2/2 |
| Ollama S1 | 4,428→4,186 | 1,434→1,360 | -74 | 1,499→2,834 | 1/2 |
| Ollama S3 | 4,388→4,146 | 1,430→1,356 | -74 | 1,489→1,416 | 1/1 |
| Ollama S4 | 4,376→4,134 | 1,428→1,354 | -74 | 2,963→2,784 | 2/2 |
| Ollama S7 | 9,894→9,284 | 2,499→2,339 | -160 | 5,069→4,746 | 2/2 |

| 模型/arm | 首轮Input合计 | whole-run Input / Output / Total | 请求 |
|---|---:|---|---:|
| Qwen A | 12,885 | 18,629 / 623 / 19,252 | 12 |
| Qwen B | 12,073 | 20,108 / 629 / 20,737 | 15 |
| DeepSeek A | 5,216 | 8,115 / 204 / 8,319 | 5 |
| DeepSeek B | 5,132 | 7,959 / 211 / 8,170 | 5 |
| Ollama A | 6,791 | 10,806 / 214 / 11,020 | 6 |
| Ollama B | 6,409 | 11,594 / 186 / 11,780 | 7 |

本轮15对首轮input全部B更低：按各模型选中矩阵分别合计，Qwen -812（约-6.30%）、DeepSeek -84（约-1.61%）、Ollama -382（约-5.63%）。不能机械沿用“B总会增加tokens”的预期。

源码可解释的一部分原因是A对每条旧user/assistant都重复时间/非当前数据标签，B合并为一个envelope、一次notice与每pair时间；多轮时这些节省可能抵消JSON包装。不同tokenizer与Provider framing也有影响，不能将全部差值归因于单一因素。P2C较短History曾观测B首轮多4 tokens，说明成本依输入形状变化。

Qwen/Ollama B的whole-run总tokens略增，主要混入了A漏查时没有发生、B成功查询后新增的Request #2；Qwen多3次请求、Ollama多1次。不能把该差值当作B包装开销。未计算货币费用、缓存折扣或推理质量收益，也不把三种tokenizer合并成单位成本。

## 10. Evidence Limits

- 每个选中模型/场景/arm仅一次P2E screening；未覆盖全部矩阵，Knowledge/source imitation仅Qwen，DeepSeek/Ollama无相同Knowledge挑战；本批没有CURRENT_SCORE_EVALUATION或Tool权限关闭的场景。
- 当前事实Tool均使用空Snapshot返回NO_DATA；证明本轮重新执行操作，不证明取得新传感器值。非空Snapshot的fresh/stale/invalid/partial与真实生产数据仍需迁移验收。
- 不读取/分析模型正文、query原文或Evidence正文，因此不能判定自然语言质量、答案真实性、检索相关性，或“没调用却声称调用”的发生率。
- 不证明长期100%可靠、所有模型有效、恶意Prompt Injection完全防御、所有未来History形状或Provider版本稳定。没有统计显著性结论。
- B不改变模型能力合同；本研究不是Tool/Thinking/Streaming新Qualification。
- **产品边界仍重要：** 当前Web请求不接受source_requirement，正式Assistant默认AUTO。本实验显式非AUTO Requirement能发现漏查；单独迁移B不会让正式产品自动具有自然语言来源分类/强制查询门禁。不得将实验里的提交拒绝保证推广为所有AUTO产品问题的来源保证。

证据只支持当前三个精确模型、当前固定架构、当前受控场景下的迁移决策。

## 11. Migration Gates

| Gate | 结果 | 依据/限制 |
|---|---|---|
| 1 Hard Invariants | PASS | 10个no-call空Receipt；20个真实执行Receipt关联正确，Requirement确定性一致；历史/仿调用不进入Executor；15对完整pair/裁剪一致；System/当前问题边界不变；50请求model/normalization异常0。硬边界同时依赖源码与既有scripted测试，而非只看正向真实样本 |
| 2 Behavioral Regression | PASS FOR SCREENING | B共15run，来源要求12/12；S3 no-tool 3/3；B漏查/wrong Tool/invalid args/来源/裁剪结构违例均0。本轮无新的阻塞性回归，但Ollama P2D额外查询与漏查保留为rollout风险 |
| 3 Cross-model Evidence | SUFFICIENT FOR FLAGGED STAGE | Qwen重复支持B；DeepSeek至少兼容B；Ollama总体支持且存在概率性trade-off；P2E复杂History继续支持方向。不同模型不必表现完全相同 |

## 12. Final Decision

**READY_FOR_FEATURE_FLAGGED_MIGRATION**。

理由：实验完整，硬合同无违例；Qwen/Ollama改善方向在不同History形状中重复出现，DeepSeek未观察到退化；S3与S7保留了no-tool和完整pair约束。本轮没有出现需要Projection V2或追加真实样本才能解释的阻塞。

许可范围仅为**下一阶段设计/实现可控迁移**，必须保留CURRENT_NATIVE回滚。不能直接替换产品、删除A、宣称三个模型长期Qualified，或扩大Tool调用预算。本轮结束后等待用户审阅，不执行P2F。

## 13. Recommended P2F Scope（仅设计）

### 接入与flag

- 内部product-level配置，例如`assistant_history_projection`，值只允许CURRENT_NATIVE@1 / UNTRUSTED_TRANSCRIPT_V1@1；不由浏览器提交，不新增用户下拉框，也不按Provider硬路由。
- 初始部署默认CURRENT_NATIVE以保留原行为；用户验收后由维护者显式开启B。非法值fail closed，不静默猜测或自动fallback。开关固定在app生命周期内，避免同一在途请求或会话中途改变表示。
- 正式接入点为AssistantContextBuilder完成原有pair裁剪之后、ToolCallingService首轮调用之前。抽取/复用无manifest、无case和无Provider依赖的纯投影组件，以message parity证明B与本次冻结语义相同；不让Web构造LLM消息，也不让产品依赖qualification执行栈。
- System/current question保持原位；A逐字段兼容当前builder；EMPTY时B不添加空envelope。所有Source/Policy/Registry/Executor、CredentialSnapshot、RuntimeSnapshot、Cancellation、预算与Analysis保持原合同。

### History与Session

- completedTurns仍保存成功user/assistant/completed_at pair；displayEntries继续独立，失败/取消/截断与Raw Tool Result不进入History。只改变送模型的表示，不改变显示或存储结构。
- 保留最多6轮/6KiB、整pair裁剪、后台History metadata及前端trim提示；不能因B字节变多再丢一次pair。
- 清空/切Preset沿用当前确认及reset行为，draft保留，Analysis状态不动。页面reload仍不持久化History；backend restart或切换启动flag产生新epoch，按现有ASSISTANT_SESSION_EXPIRED清会话并保留draft，不自动resend。
- 回滚通过启动配置切回A并重启，使用既有epoch边界；不要在正在生成时切换，也不要自动以A重试B失败。

### 观察与回滚

- 安全运行元数据可记录projection id/version、裁剪数量/bytes、Tool名与实际操作状态、有限Receipt标志、request_count、finish/error、Usage和latency；不记录Prompt、History/模型正文、query、Raw Result、Secret或凭据路径。
- 默认AUTO的线上数据只描述“实际执行了什么”，不能自动统计“应该调却没调”；明确来源要求的资格样本/人工验收才提供这一分母。不增加Intent Router或正文断言检测。
- 若出现Receipt/边界/裁剪/身份硬违例立即回滚并阻塞；若当前事实漏查、历史解释额外查询或稳定模型退化重复出现，暂停扩大开启范围、保留安全样本并单独授权targeted requalification。Ollama的已知trade-off须保留观察项。
- 每模型分别比较首轮input与whole-run请求量，不能把正确新增的Tool round计作framing回归；费用/latency显著上升交维护者审核，不做自动fallback或补跑。

### 产品测试与人工验收

- 离线：A parity、B冻结语义/JSON escaping、EMPTY、完整pair/6KiB parity、System/当前问题边界、no-call空Receipt、source imitation不授予来源、非AUTO unmet拒绝与AUTO知识直答、cancel/迟到响应/第二轮限制、History/UI独立、epoch/reset/model switch、Analysis/Manual不回归；flag无法由Web输入覆盖、日志脱敏及默认A/显式B/回滚均覆盖。
- 后续真实验收须新授权且预算有限：三个已有Preset的当前重查、历史解释、非空与NO_DATA Snapshot、旧值变新值的省略追问、Knowledge来源、Tool disabled、Stop与回滚。不得依据本报告自动发Provider请求。
- 验收标准：原显示与Session合同不变；A可回滚；B与冻结消息语义一致；所有硬合同通过；源操作要求明确的样本可检测漏查；对历史解释无明显新增过度查询；模型/成本差异可解释。保留AUTO局限，不能承诺B消除所有模型行为失败。

## 14. Non-goals

本轮不改任何产品代码/测试/配置，不调用Provider、不补样本、不改Prompt、Projection、Source Contract、Tool、Policy、Preset、Capability、Credential/ACL、Analysis或Web History；不新增Router、Memory、Agent或多Tool/multi-round，不修改正式Fishery_Project，不commit/push。

## 15. Work Tree / Validation

本次只新增本决策报告，更新[P2E准备与完成记录](archive/history-v2-research/2026-10-history-projection-product-migration-qualification.md)的当前状态及追加结果，不重写准备阶段历史。已有未提交P2B–P2E代码/脚本/测试/文档完整保留；历史0-request预检和P2D归档不计入本次30份分母。

执行了只读safe JSON/manifest/source审计与纯确定性投影、Receipt/Requirement/Usage校验；没有运行qualification CLI或Provider。未重跑Python/Browser：本轮仅Markdown，P2E-RUN既有全量结果仍为1,044通过/1跳过、Browser188通过，不能冒充本轮新回归。

最终检查：134个Markdown本地链接、broken=0；两份报告敏感字面量/尾随空白扫描通过；`git diff --check`通过，仅既有LF/CRLF提示。阶段前后SHA256比较确认src81文件、tests71文件、scripts68文件、其他docs30文件均不变；30份原始JSON累计指纹不变。

tracked git diff --stat仍为既有4文件332行增加/8行删除，不含untracked报告；它不是本轮改动量。新决策报告与P2E完成记录均为untracked，其他既有未提交文件保留；没有commit/push。

# BOT-3G：Hybrid Source / 输出 / Commit 独立合同提案

状态：**已获批Fake-only离线实施，无真实执行/General发布资格**。日期：2026-10-28。实现与兼容性见 [BOT-3G-B](../../patches/2026-10-31-stages/BOT3GB_HYBRID_OFFLINE.md)；下文保留设计推导与真实发布风险审阅边界。
配套：[Hybrid 架构与 Prompt](BOT3G_HYBRID_AGENT_DESIGN.md)。本提案不能用来修改当前旧合同或生成有效批准。

## 1. 为什么需要新合同

旧QQ证明的是“本轮当前水质查询已执行，再按闭合计划解释”；General需要合法的“没有查询现场数据的一般交流”。两者是不同任务，不能把旧 CURRENT_OBSERVATION_QUERY 改为 AUTO 后继续称作原资格。

离线探针证明 Web AUTO 接受无Tool的最终回答，甚至会接受Fake提供的无证据当前断言。因此不得直接把Web的成功 DTO、model.kind 或“已加免责声明”当成QQ事实核验证据。

## 2. 候选封装与实际步骤分支

候选内部合同名 `qq-hybrid-channel@1`、展示封装 `qq-hybrid-reply@1`；名称仅用于设计，当前代码不支持。

```json
{"contract":"qq-hybrid-reply@1","kind":"general","text":"溶解氧是水中溶解的氧气。这里是一般概念说明。"}
```

```json
{"contract":"qq-hybrid-reply@1","kind":"water","plan":{"contract":"qq-water-explanation@1","source":"simulator","context":"limited","metrics":["dissolved_oxygen_mg_l"],"rules":[],"advice":["check_reporting"]}}
```

第二个对象的context/rules/advice仍必须匹配实际SourceSummary；示例不是任意场景均合法。严格拒绝重复字段、额外字段、错误类型/版本、超长/不完整JSON及非有限值。

**分支权威是本轮实际ToolExecutionSteps和Receipt，不是模型自报kind：**

| 实际执行 | 模型最终结构 | 候选处理 |
|---|---|---|
| 0 Tool | general | 仅General草稿；无任何监测Receipt或SourceSummary，需独立General发布许可 |
| 1次授权当前Tool，Receipt完整 | water | 运行原水质计划校验；可信数值与状态仍只从Tool生成 |
| 0 Tool | water/声称查过当前状态 | 拒绝现场回答，不造Receipt，不补推理 |
| 已执行当前Tool | general或错误计划 | 不将其自由文本放行；可沿用原“只展示本轮可信事实”的安全降级，明确解释未通过 |
| 未授权Tool、参数越权、多Tool、Tool失败 | 任意 | 保持原错误/预算/权限结果，不退化为“模型说查过也算” |

Prompt要求当前问题必须取Tool，但Prompt不是证明。复杂隐含当前问题且模型不调用Tool时，不能仅因声明general就认为内容安全，见第4节。

## 3. Source / Commit 改动边界

旧Web、旧QQ和当前水质严格profile保持原样；只允许新类型化Hybrid计划进入新装配。模式、Scope和授权由服务器冻结，聊天、JSON中的 can_send/can_deliver 或用户指令不能选择。

共享Assistant的AUTO可作为**新Hybrid profile内部执行阶段**的工具可选机制，不能作为最终发布条件；它不替代Hybrid Source Gate。Water分支必须验证本轮 CURRENT_OBSERVATION_QUERY 的真实Receipt；General分支必须明确无现场来源且通过独立输出决策，不伪造空的“成功观测”。不在执行中改写冻结的SourceRequirement来迎合模型结果。

共享 RequestHandle.finalize_result 的取消、期限、SDK关闭和线程退出检查不动；Backend completed 只是后续发布候选。新Result用明确的 GeneralDraft / WaterResult 变体，使Delivery和History不能因 source=None 崩溃，也不能用虚假Source填充。

新Run报告根据分支核对：General合法1请求/0Tool，Water合法2请求/1Tool；上限仍为2请求，零重试。分别记录 backend_completed、source_contract、presentation_valid、safe_fallback、SDK状态、API接受、history_commit，不能把“发送了安全拒绝”写成“模型解释验证通过”。旧verified==2的含义不改。

## 4. General输出：不能假装完成通用语义核验

建议General正文短句、一到两段、建议60～180中文字符，硬上限600字符；最终QQ总长仍受原限制。程序附紧凑标记“一般说明，非现场结论”；不标为“已核验系统事实”，不声称RAG检索。

General允许一般交流和有限概念解释，不允许本轮现场读数、当前正常/恢复/风险命中、已执行查询/操作、专业确诊/用药或设备控制。用户自报数据只能标为用户提供的假设，不能升级为系统观测。

最低发布防护：严格结构/长度/字符校验；实际工具步骤与kind一致；明显现场断言、伪造操作、检索来源冲突则拒绝或返回程序说明“本轮没有取得可核实的现场证据”；不重试模型或重复QQ回复。此处的文本冲突检查是**发布防护**，不是恢复关键词业务准入白名单。

**关键限制：** JSON结构、Prompt和免责声明都不能证明任意自由文本没有隐含现场结论；有限规则也不是通用逐句事实验证器。把“你那边这会儿可以放心了”换一种说法，仍可能漏检。普通知识正确率可以作为实验质量问题，但不能把漏过的现场断言宣传为可信监测结论。

因此需要独立审核General真实发布策略：

- 第一阶段只在Fake环境收集General草稿，真实QQ不自动放行；本轮采用此停止点。
- 后续若批准实验级一般文本自动显示，需要明确接受有限语义防护的剩余风险，保留“非现场”标记、保守拒绝、用合成对抗集验证，并保持现场事实专用通道；它不具有强保证或专业事实核验资格。
- 若要求严格保证任何未经核验现场断言都绝不出现，当前自由文本方案不足，需要人工审阅或更窄输出；不能通过多加几个关键词宣称问题已解决，也不能偷偷增加第二次审核模型请求。

这项安全选择须在真实General发布前解决。用户“不追求生产级回答质量”不等于自动授权放宽当前事实门禁。

## 5. 多轮、交付与额度

General历史允许保留最小用户原句与实际已发送安全答复，用于概念追问；Water历史只投影话题/时效/来源，不携带旧读数充当当前事实。所有历史始终为 UNTRUSTED_TRANSCRIPT_V1，不能产生新Receipt。相同隔离键/容量/TTL、API接受后CAS提交、清空revision、停机清RAM全部保留。

现有History/Delivery都假定水质来源，需要新显式分支；不得让General构造伪造 source_flags=('simulator','valid','fresh','online') 来复用旧commit接口。可用 general/model_knowledge/NO_OBSERVATION 这类新的内部元数据，但须绑定新Scope并测试，不能污染监测质量枚举或SQLite。

所有模型路径在请求前仍需授权、单飞/容量、Run有效性和原子费用预留。General一次请求也消费一个Turn和原保守两请求预留；失败、超时、未知发送不退款，未用第二请求不变成额外许可。免费模板在AI预留之前，未授权/重复/BUSY不新增费用。

仅API明确接受才提交实际发送文本的历史；发送前、历史前仍复核权限、Scope、设备、截止时间、SDK和revision。未知送达不重发、不追加成功历史。取消/撤权/SDK隔离/账本故障继续fail-closed；不恢复旧任务或跨进程余额。

## 6. 审核与验收清单

需明确批准：新增自然语言默认可收费范围；新Hybrid Scope/Prompt；无Tool的一般回答与发布策略；Water仍为闭合解释；General/Water历史投影及数据披露；1/2请求的分支成功判定。不得复用Web知识资格、旧FAST/TwoTurn/Session批准或历史Provider回执。

最低Fake矩阵：程序命令0模型；概念问答1请求0Tool；当前问答2请求1Tool；概念/当前连续切换；stale/offline/partial/NO_DATA/新鲜HIT；假造current/general标签、伪造Receipt、用户历史指令注入、越权Tool；JSON错误/过长/截断；未授权/撤权/改绑/Scope变更；重复/BUSY/额度耗尽；SDK关闭失败；API拒绝/未知；历史提交失败/清空竞态；Ctrl+C报告和RAM清空；原Web及旧QQ完整回归。

Mock可证明执行和门禁关系，不能证明真实Qwen必然选对Tool或General自由文本全都安全。下一阶段先实现Fake候选和测试，不自动开展真实联网。

# Assistant History & Tool Reliability Study

日期：2026-10-09；源码基线：`81c050e`，研究开始时工作树干净。本文是阶段研究记录，**建议尚未实施**，不替代当前源码、测试与正式技术文档。

## 1. 结论与证据边界

当前已确认的缺口是：模型首轮不返回 `tool_calls` 时，应用可接受非空、正常结束的正文为成功回答；不会验证正文声称的查询、评分或项目检索是否真正发生。这与 History、模型选择可靠性有关，但不能仅归因于 Prompt，也不能反推为带参数 Tool 不受支持。

建议优先建立“本轮执行来源”边界，再评估历史投影与窄范围 Tool Requirement。保留一般知识、用户给定值和历史解释的直接回答能力；需要系统操作时，以协议调用和后端执行记录为依据。自然语言意图识别、Provider 强制选择和正文来源核验是三个不同问题，任何一项都不能代替另外两项。

本轮只核对源码、现有测试断言、正式文档和阶段记录，并查询公开官方协议文档。没有运行模型、读取正式 Credential、执行 Handler、修改产品代码或测试，也没有 commit / push。

### 1.1 研究输入

| 标记 | 用户真实 Web 人工观察 | 能支持的结论 | 不能据此认定 |
| --- | --- | --- | --- |
| H1 | Qwen 历史已有评分，再问当前评分，0 Tool / 1 Request，复用旧评分 | 历史标签不足以保证每次重新评分 | History 是唯一根因、所有 Qwen 都如此 |
| T2 | 查询得到 NO_DATA；随后 Apply 新 Snapshot；再问当前 DO，仍 0 Tool / 1 Request | 旧无数据回答可能影响本轮选择；NO_DATA 不能长期沿用 | Store 未更新或 query-time Freshness 失效 |
| B1 / B2 | 明确点名评分或知识 Tool，正文模仿调用，协议无调用 | 文本宣称与实际操作不一致 | Adapter 把合法调用丢掉 |
| B3 | 清空 / 刷新后 Qwen 知识调用成功，1 Tool / 2 Requests | 此模型能够完成带 query 的知识闭环；不能判定完全不支持 | 清空历史必然解决、已完成受控因果实验 |
| B4 | Ollama 明确知识调用成功；用户观察其他模型更稳定 | 值得按精确模型分别测量可靠性 | 已得到跨模型统计排名 |
| K1 | 新页面没有 Knowledge 调用，却声称“根据项目检索结果” | 来源伪造不只发生在有历史时 | 内容必然错误，或已证明内容来自特定训练资料 |

这些是人工观察，不登记为本轮自动测试通过。[接管审计](../knowledge-tool-v1/2026-10-codex-takeover-audit.md)中的 SDK 模拟与无 Tool 来源反例是既有离线证据；[四项 Provider 取证记录](../knowledge-tool-v1/2026-10-qwen-tool-provider-evidence.md)实际为凭据预检阻塞、0 次模型请求，不能用作真实 Provider 报文对照。

## 2. Session lifecycle：当前实际行为

依据 [app.js](../../../../src/fishery_ai/resources/web/app.js) 的 `assistantState`、`switchApplicationMode()`、`resetAssistantSession()`、`changeAssistantPreset()`、`sendAssistant()`，以及 [Web API](../../../../src/fishery_ai/web.py) 的 bootstrap / epoch 检查。

```text
新文档加载，执行 app.js
  completedTurns=[]，displayEntries=[]，historyTrimmed=0
  selectedPresetId=""，presets=[]，draft=""，epoch=null
  pendingRequest=null，toolActivity=null，run=null
  busy=false，loading=false，两个滚动位置=0
        ↓ 第一次进入 Assistant
GET /api/assistant/bootstrap
  获取允许的 Preset、默认模型和当前进程 epoch
  有有效 default_preset_id → 选择默认；否则保持“请选择模型”
        ↓ 用户确认并 Send
pending user → Model / optional Tool → 完整成功
        ↓
completedTurns 加入 user / assistant / completed_at
displayEntries 加入最终回答与安全 Activity
        ├─ Analysis ↔ Assistant：保留这份页面内状态，不发送模型请求
        ├─ 清空对话：清除历史、显示条目和本次运行；保留模型、draft、epoch
        ├─ 确认切换模型：同样清除历史；更换模型，保留 draft / epoch
        ├─ 真正刷新 / 新文档打开：重新初始化内存状态
        └─ 后端重启：旧 epoch 下一次 Send 被拒绝
             清历史 / Activity → 保留输入 → 重新 bootstrap → 等待用户重新 Send
```

### 2.1 精确状态变化

| 操作 | 清除 / 更新 | 保留 / 限制 |
| --- | --- | --- |
| 首次加载 | 所有 Assistant 内存状态按上述初值建立 | bootstrap 在进入工作区且没有 epoch 时执行；不恢复历史 |
| 工作区来回切换 | 保存 / 恢复 draft 与滚动位置，切换 DOM 可见性 | 成功历史、模型、结果、epoch 保留；Analysis 状态独立 |
| F5 / Ctrl+R | 新执行的 JS 重新建立空历史 | 浏览器可能恢复表单输入，但代码没有恢复 completedTurns 的机制 |
| 关闭后正常重新打开 URL | 新文档空历史 | 浏览器返回缓存或恢复既有页面不是新文档加载；代码没有针对这种恢复强制清空的处理，不能承诺所有浏览器恢复动作都等同刷新 |
| 清空对话 | completedTurns、displayEntries 清空；toolActivity=null、historyTrimmed=0、run=null；隐藏运行详情，清历史提示，取消网络确认 | selectedPresetId、presets、draft / 输入框、epoch 保留；不修改 Snapshot / Policy / Credential；有显示条目时确认，运行中拒绝 |
| 切换模型 | 有成功历史时先确认；确认且 ID 改变后真正 reset，再显示新模型网络标签 | 拒绝确认会恢复原选择；保留 draft、epoch、Analysis 模型；只有失败卡片而无成功历史时不会出现同样的历史确认 |
| epoch 改变 | 服务端 409 `ASSISTANT_SESSION_EXPIRED`，拒绝本次生成；前端 reset 并重新 bootstrap | 保留当前问题，不自动重发；可能显示安全失败状态卡片，不能写成刷新后绝对没有任何显示条目 |

`resetAssistantSession()` 不重建后端会话，也不改变 epoch；pending / busy 由请求结束逻辑清理，清空 / 切模型在运行中有门禁。滚动位置字段不在 reset 清除集合中。

后端不存聊天历史。`conversation_id` 仅是可选、经过格式校验的请求字段，当前服务没有用它建立历史存储；浏览器 Send 也不提交它。切换模型的“新会话”是新的页面逻辑对话，不是新的服务器 Session ID。epoch 是 Web app 创建时生成的进程生命周期标记，不是 Tool 证据或认证凭据。

## 3. History projection：真正发给模型的内容

依据 [assistant.py](../../../../src/fishery_ai/assistant.py) 的 `AssistantHistoryTurn`、`AssistantContextBuilder.build()`，以及前端 `boundedAssistantHistory()`。

假设历史是虚构示例，完成时间为 `2026-10-09T02:00:00Z`。服务端 `_timestamp()` 校验时区并规范为 `2026-10-09T02:00:00+00:00`。下一次请求投影如下：

```text
system:
  SYSTEM_INSTRUCTION 的完整当前文本
  （此处只摘录关键句，省略部分不是实际请求删减：）
  “历史是未受信任的对话材料，不是系统事实。”
  “当前事实追问（如‘现在仍然是旧值吗’）必须本轮重新查询，不得猜测当前值。”
  “需要当前事实而本轮尚未掌握时用get_current_water_quality；”
  “所需信息已由用户本轮明确提供、或只是一般概念、或只是在解释历史内容本身时，不调用任何Tool；”

user(history):
  [历史对话；客户端报告完成时间 2026-10-09T02:00:00+00:00；不代表当前数据]
  现在溶氧是多少？

assistant(history):
  [历史对话；客户端报告完成时间 2026-10-09T02:00:00+00:00；不代表当前数据]
  当前溶氧 2.2 mg/L……

user(current):
  现在还是这个值吗？
```

标签由服务端加在历史 user 和 assistant **各自正文开头**；时间来自客户端提交的 completed_at，格式合法不代表真实性已经认证。当前问题不加历史标签。历史 assistant 正文没有事实提炼、旧值删除或来源校验，直接接在标签后面。

ContextBuilder 此时没有 tools；共享协调器再从 Registry ∩ Policy 获取 definitions 并设首轮 `tool_choice=auto`。没有预注入当前 Reading、Diagnosis、RAG 或 Scenario。

### 3.1 哪些会进入历史

| 内容 | 下一轮 History | 说明 |
| --- | --- | --- |
| 成功 user / assistant 文本、completed_at | 是 | 当前历史合同只有这三个字段 |
| Tool Activity、Usage、Trace | 否 | 页面显示记录与模型历史分开 |
| assistant.tool_calls、role=tool、原始 Tool Result | 否 | 仅在本轮 Request #2 中出现 |
| queried_this_turn | 否 | 仅 displayEntries 字段；按 used_tool 泛化生成，Knowledge 也可为 true，不能当水质来源证明 |
| cancelled / failed / truncated / pending user | 否 | 可以留显示卡片，但不提交成功历史 |
| 无 Tool 却虚构操作的正常正文 | **目前可能是** | 成功门禁不检查来源，正常 stop、非空且其他提交条件满足即可 |

### 3.2 裁剪与实际预算

- 前端内存 completedTurns 最多保留 20 对；成功提交时 displayEntries 最多保留 60 条。显示条数不代表模型收到同样数量。
- Send 先取最近 6 对；对 `{user, assistant, completed_at}` 数组进行 JSON.stringify + UTF-8 编码，超过 6144 bytes 就从最旧整对开始删除。
- 后端独立取最近 6 对，再对紧凑、非 ASCII 转义的 JSON 序列化做同样 6144-byte 裁剪；时间规范化可能使两端字节数略有差别。另有输入历史最多 64 对 / 16 KiB、单文本 16 KiB、当前问题 2 KiB 的合同校验。
- 前端显示裁剪提示时合并本地裁剪数和后端 `history_trimmed`。超大整对可以全部裁掉，不保留半条。
- **6 KiB 是历史记录 JSON 的预算，不是完整 Provider messages 或 token 上限。** 历史标签、System、当前问题和 Tool definitions 都在它之外。正式架构文档的“序列化上下文最多 6 KiB”应按这个更精确含义理解；本轮不修改正式文档。

## 4. H1 / T2 根因候选

以下区分“代码机制成立”和“是否造成这一次真实选择”，后者没有受控对照，不宣称已确认根因。

| 候选 | 支持证据 | 反证 / 证据限制 | 可离线验证 | 后续用户人工对照 |
| --- | --- | --- | --- | --- |
| A 旧正文让模型认为答案足够 | 旧 DO / score / NO_DATA 原文保留；H1、T2 与此相容 | B3 清空成功不是同输入随机性控制；K1 空历史也会伪造来源 | 验证投影保留值、模拟错误正文的接受路径 | 同问题、同 Snapshot、同 Policy：无历史 / 旧值 / 旧 NO_DATA |
| B 历史标签力度不足 | H1 已有标签仍失败 | 标签可能降低风险，缺乏有无标签同条件统计 | 验证标签位置与时间，不能验证模型遵守 | 比较同等长度的标签与历史摘要版本 |
| C System 存在语义模糊 | 同时有“必须本轮查询”“本轮尚未掌握”“用户本轮提供”“解释历史” | 明确禁止旧值的句子已存在；无证据说明模型具体采用哪句 | 检查规则冲突示例与 Prompt 投影 | 明确当前追问 / 历史解释 / 用户给定值对照 |
| D 模型选择 / 遵循差异 | 用户报告 Qwen 更不稳定，Ollama 明确知识调用成功 | 未控制历史、Policy、预算、Provider 版本；没有可靠性统计排名 | 验证同合同 fixture，不能比较真实模型强弱 | 精确 Identity 与同版本输入的小样本比较，报告分子 / 分母 |
| E auto 允许直答 | 首轮固定 auto；无 call 直接结束，确定性代码事实 | auto 本来是为了保留概念直答；不说明 Provider 为何这次选择直答 | 请求编码、无 call postcondition、模拟 required / exact 合同 | 在 Provider 已确认兼容的前提下比较 auto / 指定 Tool |
| F 长历史削弱规则遵循 | 历史增长可增加竞争信息，合理研究假设 | 当前无注意力测量；6 轮上限不等于已验证长度无影响，K1 空历史也失败 | 测长度与裁剪；不能证明“注意力权重下降” | 相同内容：短 / 长历史，另设等长非事实历史控制 |
| G 错误成功回答自强化 | 缺少来源门禁；错误正常正文可进入成功 pair，再次原样发送 | 路径存在不等于每轮一定强化；并非所有历史错误都源于本系统 | scripted no-call 伪造回答 → success → 下一轮含错误文本 | 人工观察同会话后续行为；不制造大量真实错误记录 |

当前最强代码结论是 E 的机制与 G 的可达路径；A / B / C / D / F 对真实异常的贡献仍待测量。Snapshot 更新本身不会通知模型，只有本轮 Tool 执行才读取当前 Store；这解释了为什么沿用旧 NO_DATA 不等同于 Reader 失效。

## 5. 三条路线比较

### 5.1 A：只加强 Prompt

当前 System 通过源码 AST 字面量核对为 **1309 字符、3063 UTF-8 bytes**，尚未计算模型 token 数；没有证据证明接近上下文上限。问题是同一限制多处重复，且边界规则需要模型做语义判断，继续堆句子会增加维护与相互冲突风险。

可压缩为按来源组织的少量规则，减少“本轮尚未掌握”的歧义。它可能提高成功比例，不能保证当前查询、评分或检索真实执行。Tool 越多，按每个名称堆规则越难扩展；单纯提示“必须”不能改变 auto 的协议许可，也不能验证自由正文。

适合作为配套优化，不建议作为唯一修复或验收依据。本轮不改 Prompt。

### 5.2 B：History projection

| 思路 | 价值 | 复杂度 / 副作用 | 建议 |
| --- | --- | --- | --- |
| B1 保留全文，加强 provenance wrapper | 对解释历史最兼容；成本低 | 本质仍是文本约束；旧数值仍显著可见；客户端时间不可信 | 可作过渡，不能宣称解决 H1 / T2 |
| B2 当前事实 / 评分回答变成结构化历史摘要 | 将观测时间、查询时间、来源、状态与解释分离；旧 NO_DATA 不再像永久结论 | 当前历史合同没有执行 metadata；不能靠抽取模型正文制造可信事实；需要受控 receipt 或始终标为未认证历史 | 推荐评估，先解决摘要来源真实性 |
| B3 当前问题暂时弱化旧实时值 | 降低“答案已知”的诱因 | 何时是“当前问题”仍需判断；全部去数字会破坏“现在还是2.2吗”的指代；清空历史也不能解决 K1 | 不作为默认全局清除策略 |
| B4 保留历史解释，当前比较必须新查询 | “刚才2.2是什么意思”保留；“现在仍是2.2吗”同时保留旧值作比较并强制新来源 | 需要分开历史参考值与本轮数据；不能把二者混成一个 current facts 字段 | 作为新投影的目标行为 |
| B5 隔离错误 / 未支撑来源声明 | 阻止错误声明继续作为成功事实传播 | 普通知识无 Tool 本来合法，不能把所有 no-tool 回答删除；自由文本全面识别不可确定 | 对已确认违反运行要求的轮次不提交成功历史；其他 no-tool 文本仅为模型回答 |

建议的 B2 示例是“历史用户问了什么；当时执行了什么；当时记录 DO=2.2、observed_at / evaluated_at；这不是当前读数；解释文本仅作历史参考”。NO_DATA 应是“当时查询无 Snapshot”，不是“当前仍无数据”。不要跨轮保留 `role=tool` 作为新鲜观测，不提升历史材料为 System instruction。

**信任问题必须先解决：** 后端当前无会话存储，History 由浏览器回传。把 tool_name / 数值 / 时间加到客户端 JSON 并校验格式，不能证明它来自真实执行。最小第一步只认证本轮后端运行结果，旧历史继续不受信任；若需要可信 B2 数值摘要，再评估进程期、短寿命的服务端签发 receipt（限定字段、epoch、有效期、签名校验），或有界进程内 receipt 索引。二者都不需要 DB / 长期 Memory，但会增加合同与生命周期复杂度，应另行批准；未认证摘要一律只算 HISTORICAL_CONVERSATION。

### 5.3 C：窄范围确定性 Tool Requirement

需要区分：程序确定“本轮必须取得哪类来源”、协议要求模型返回调用、返回后验证所需操作真的成功。只设置 required 不够，也不能授权 Policy 外的 Tool。

#### 当前 SDK / 项目 / Provider 的实际限制

公开文档查询日期均为 2026-10-09；只访问文档，没有模型请求。

| 层 | 核对结果 | 对设计的影响 |
| --- | --- | --- |
| 本机 OpenAI Python SDK | `.venv` 包版本 2.54.0；`ChatCompletionToolChoiceOptionParam` 有 auto / none / required，以及 named-function 对象 | SDK 类型能表达指定函数；不等于当前 Gateway 或每个服务均可用 |
| ModelRequest | 仅接受 None / auto / none / required 字符串；指定函数对象被拒绝 | exact Tool 需要将来最小合同扩展，本轮不能假装已有 |
| Adapter | tools 按 Registry schema 编码；tool_choice 直接传给 SDK | 未发现按 query 参数过滤 Tool 的分支；协议支持不是选择保证 |
| Coordinator | 有 definitions 时覆盖首轮 choice 为 auto；第二轮设 none | 上层即使构造 required，也不能直接用当前协调器达成强制调用 |
| OpenAI 官方 Chat Completions | auto 可直答；required 要求一个或多个；named-function 可指定函数 | required 不保证单调用预算；仍要后端检查数量。见[官方 API Reference](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create) |
| DashScope / Qwen | 官方特别说明 Qwen 的 required 在非思考模式无法保证调用；思考模式不支持 required 或强制指定函数。非思考模式描述了 named-function 方式 | **不能推荐 required 作为 Qwen 的确定性修复。** OFF 下 exact Tool 是待人工验证候选，不写成 qwen3.8-flash 已实测。见[官方 OpenAI 兼容 Chat 文档](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions/) |
| DeepSeek 官方 API | 描述 required 与 named-function；思考模式下这两者返回 400 | 当前 OFF + Normal 与文档条件相容；精确模型实际行为仍需用户验证。见[官方 Chat Completions API](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/) |
| Ollama | 官方兼容页列 tools 和 tool_choice 请求字段，但该页不足以确认本机版本 + qwen3.5:4b 的全部 choice 值及强制语义 | 不能由字段存在推出 required / exact 保证；保留待人工验证。见[官方兼容文档](https://docs.ollama.com/api/openai-compatibility) |

以上 API 文档描述不能自动修改 Preset 合同，也不能推广到不同模型或 endpoint。即使 Provider 承诺强制调用，应用仍必须拒绝无调用、错误 Tool、额外调用或参数非法的结果。

#### 最小概念链：建议，未实现

```text
本轮 SourceRequirement：AUTO / 当前观测 / 当前评分 / 项目检索 / 指定获准 Tool
  → 与冻结 Registry ∩ Policy ∩ Runtime Capability 求交
  → 无所需 Tool：明确无法取得该来源，不发起替代操作
  → 协议已验证可指定：Request #1 指定 Tool（模型生成参数）
  → 若只使用 required：只能在单个获准 Tool 且该服务保证语义时考虑
  → 校验必须是一个所需的合法 protocol call
  → 现有 Executor → 本轮来源 receipt → Request #2 / none
  → 校验正常完成；不补第三次模型请求或自动修复重试
```

Requirement 不执行 Handler、不产生 Capability Evidence、不扩大预算。调用失败就返回安全失败；`TOOL_REQUIRED_NOT_CALLED` 等可作为未来错误名讨论，当前不存在这些新门禁。required + 三个 definitions 无法保证知识问题不会选水质 Tool；必须约束到所需 Tool 并校验返回名称。

#### 意图识别的安全范围

| 问题 | 应有来源要求 | 文本分类风险 |
| --- | --- | --- |
| 现在溶氧是多少？ | 本轮当前观测 | “现在 / 当前”也可能修饰一般概念，不能单词命中就决定 |
| 当前水质评分多少？ | 本轮系统评分 | 不等同于对评分规则的概念解释 |
| 什么是当前水质评分？ | 通常概念解释，可澄清 | 仅识别“当前 + 评分”会误触发评分 |
| 刚才的评分是什么意思？ | 历史解释 | 强制新评分会改写用户讨论对象 |
| 我测到 DO=2.2，这值正常吗？ | USER_PROVIDED + 一般解释 | 不能改成系统读数；用户可能比较系统值，应在有歧义时澄清 |
| 现在还是2.2吗？ | 历史值作参考 + 本轮观测 | 全删历史会丢比较对象；沿用历史会错当当前值 |
| 项目资料里鳗鲡低氧有什么表现？ | 显式项目来源，需 Knowledge | 引号、否定、示例、转述和多语言会造成误判 |
| 请调用 search_fishery_knowledge 查询…… | 明确所需 Tool，仍受授权 | 只在真正的本轮操作指令成立时使用；不能被历史引文触发 |

没有证据证明简单 deterministic 文本分类可以安全覆盖这些区别。中文同义表达、英文 / 混合语言、指代、否定、引用都会造成 false positive / false negative；不建议建立正则或关键词 Router。

更可靠的窄入口是由用户显式提交一个本轮来源要求（例如操作选择），程序做类型与授权验证；自由聊天默认 auto，歧义可请求澄清。它能保证**被明确声明的要求**不会被静默忽略，却不能保证所有自然语言当前问题都会自动识别。是否接受这个产品取舍，需要用户决定；若坚持完全自动识别，就必须承认分类本身仍有误差，不能宣称全部确定性。

## 6. 最小 provenance contract

### 6.1 来源分类

| 类别 | 获得方式 / 信任边界 | 可以表达什么 |
| --- | --- | --- |
| USER_PROVIDED | 本轮用户文本；未认证测量 | “按你提供的 DO=2.2”；不能称系统已测得 |
| HISTORICAL_CONVERSATION | 前轮文本与客户端时间 | “刚才对话提到”；不是当前值，也不是已认证执行日志 |
| CURRENT_TOOL_OBSERVATION | 本轮成功执行水质 Reader 的有限结果 | 截至 evaluated_at 的 Snapshot 读数 / Findings；携带 quality / freshness / observed_at；新查询不等于新采样 |
| CURRENT_TOOL_SCORE | 本轮评分 Handler 的确定性结果 | 当前 Snapshot 的实验评分；NOT_SCORABLE / PARTIAL / NO_DATA 必须保留，不能自行补满分项 |
| RETRIEVED_PROJECT_EVIDENCE | 本轮 Knowledge Handler 返回的条目 | 指向实际 evidence id / source / version 的背景资料；NO_MATCH 表示没有命中可引用 |
| MODEL_GENERAL_KNOWLEDGE | 未绑定系统来源的模型一般解释 | “一般而言……”；程序无法证明具体训练来源，不把标签当内容正确证明 |
| MODEL_INFERENCE | 对已说明来源的材料作推断 | 明确推断与不确定性；不是新的观测、系统评分或检索命中 |

类别不是互斥的单字段：一段回答可以同时参考历史值、用户输入、当前 Tool 与一般解释；需要按声明 / 引用片段区分。分类不升级为知识图谱。

### 6.2 程序应先保证什么

建议最小本轮 receipt 直接由协调器 / Executor 的真实结果生成：request_id、工具名、执行状态、有限来源类别、数据时间，以及必要的规则 / 评分版本或 Evidence 标识。可复用现有 `ToolConversationResult.tool_result` 和安全 Activity；不让模型或浏览器自行签发操作事实，不向历史复制完整 Tool JSON。

- 没有本轮 Reader 结果，不认证“当前系统读数”。**评分 Tool 也返回 canonical water_quality 与 evaluated_at**，所以不能机械规定必须调用 get 才能引用读数；应按实际 payload 与状态授予来源能力，避免迫使同轮执行两个 Tool。
- 没有本轮评分结果，不认证“当前系统评分 / 等级 / 分项分数”。有查询 Tool 仍不能认证系统评分；模型自拟估计只能明确是非系统推断。
- 没有 Knowledge 执行，不认证“已检索项目资料”。执行返回 NO_MATCH 可认证“已检索但无命中”，不能认证任何命中文献；OK 也只能引用结果里存在的条目，不能凭空加出处。
- NO_DATA 可认证“本轮读取时没有 Snapshot”，不是长期事实。当前 Handler 的 NO_DATA payload 没有观测时间，receipt 应以本轮执行时间标明范围，不伪造采样时间。
- STALE / INVALID / PARTIAL 仍是成功读取的真实数据状态；不能授予“当前有效 / 新鲜读数”的额外保证。

首先核验系统操作及有限结构化来源声明；暂不做通用事实真伪或医学 / 养殖知识验证。随后可对数值引用、评分引用、Evidence ID 作简单“是否存在于本轮有限结果”的一致性检查，不能把允许集合误称所有自由文本都正确。

### 6.3 自由正文的保证限度

当前输出是纯文本。程序仅凭 tool_calls=[] 能确定没有执行 Tool，不能普遍理解每一种自然语言来源声明。给 UI 增加“未查询当前数据 / 未评分 / 未检索”的后端标识可提高透明度，**但不会自动阻止正文说谎**。

如果要对官方来源声明形成更强保证，需要一个很小的回答合同：模型声明的来源类别 / 引用先与 receipt 校验，用户看到的系统来源标签和权威数值由程序生成。模型返回结构化字段本身仍不可信；无 receipt 的来源必须拒绝或降为未认证模型说明。保留的自由说明也可能隐含错误来源，不能承诺已解决所有语义伪造。

对明确要求查询 / 评分 / 检索的轮次，若所需 receipt 不存在，最小可靠行为是本轮不提交成功，不让伪造答案进入历史；不自动补执行 Tool 或第三次生成。这与 C 的要求合同互补，不靠自由文本黑名单。

## 7. Tool Call imitation

当前行为已从代码确认：

```text
Provider content = “[调用工具 search_fishery_knowledge ...]”
Provider protocol tool_calls = []
  → Adapter 保留为普通 ModelResponse.text，无 ModelToolCall
  → Coordinator 首轮 final_answer，不执行 Executor、不发送 Request #2
  → Assistant 正常 stop + 非空等门禁通过时可提交成功
  → UI Activity 准确显示未调用，但正文仍按 textContent 原样显示
```

不能将这段文本解析成真实调用，也不能把“看起来像调用”传给 Handler。没有协议调用时，执行事实只能是零 Tool。

建议区分：

1. 普通概念正文无 Tool：合法，不一律拒绝。
2. 本轮已有明确 Tool Requirement，却没有所需调用 / receipt：确定性拒绝成功，显示协议要求未满足。
3. auto 下疑似模仿：UI 固定展示实际执行状态；可研究非阻断异常提示，但不要假称已可靠识别所有语言。合法引用教程也可能包含类似文本，不能靠不断增补 regex 黑名单。

如果未来回答合同明确声称执行某操作，却没有对应 receipt，可确定显示“模型声明与实际执行不一致”。当前纯文本没有这种显式声明字段，因此不能承诺程序已能普遍给出“模型声称调用”的判断。协议一致性检查验证的是真实 call / result / receipt 关联，不是任意自由正文的语义。

## 8. 模型差异与 Capability 的含义

`tool_calling=SUPPORTED` 表示该精确运行合同具备已发布的 Tool 协议能力，不表示模型面对所有问题、历史与多个 Tool 都能正确选择。B3 / B4 是成功实例；H1 / K1 是可靠性反例，二者可以同时成立。

未来区分 `protocol_supported` 与 selection reliability 有价值，但后者不宜再变成一个永久布尔 Capability。建议独立的评测记录：exact Identity、Preset contract、Prompt / History projection 版本、授权 Tool 集合、choice 模式、预算、场景、日期、成功数 / 总数、错误类型与虚构来源次数。没有样本就标未评估，不将一次成功称“稳定”。

不能依据此次没调用 Knowledge 把 parameterized Tool 判 UNSUPPORTED：现有 Schema 声明 required query，Adapter 按标准 function.arguments 归一化；用户已观察 Qwen 与 Ollama 知识闭环成功。仍没有真实失败报文可以排除所有非标准响应风险，但当前不支持“带参数 Tool 普遍无法解析”的结论。

检索 relevance 是 **调用成功以后** 的证据质量问题，不解释选择阶段的零 Tool，也不由 protocol_supported 保证。本轮不修改 Capability / Preset，也不比较新模型。

## 9. 推荐方案与最小实施阶段

推荐顺序：**本轮来源 receipt / 提交边界 → 窄范围显式 Requirement 与 Provider 校验 → 有证据的 History projection → 精简 Prompt**。不建议先加大量 Prompt 文字或全局强制所有问题用 Tool。

| 阶段（未来，需批准） | 最小范围 | 稳定条件 |
| --- | --- | --- |
| P0 设计决定 | 确认来源要求如何输入、自由正文保证范围、历史摘要是否需要可信 receipt | 明确哪些承诺可确定实现；不假装自然语言 intent 已确定 |
| P1 本轮来源边界 | 从现有执行结果生成有限 receipt；当前查询 / 评分 / 检索声明与实际操作分离；设计必要的成功门禁 | scripted no-call 假声明不能被认证为系统来源；概念回答仍合法 |
| P2 显式 Tool Requirement | 最小 exact-choice 合同；协调器保留本轮要求；授权筛选、返回名称 / 参数 / 数量校验 | Provider 不兼容或无 call 时安全结束，不 silent auto fallback、不第三次请求 |
| P3 History 投影 | 优先区分历史事实参考与模型解释；NO_DATA 带历史范围；需要可信摘要时再加有界 receipt 校验 | “刚才”能解释，“现在仍是”必须新来源；客户端伪造 metadata 不升权 |
| P4 Prompt 与人工对照 | 合并重复规则；用户正常 Web 进程执行小规模模型对照 | 按场景报告比例和失败，不把随机行为变成 CI 硬保证 |

P1 不需要先改变 Reader、Handler、Registry、Credential、Capability、Analysis 或 RAG。P2 必须核实每个精确 Provider 的 choice 语义，Qwen 不用 required 充当保证；用户决定是否为自由聊天增加显式来源操作入口。P3 不能通过 LLM 摘要“修复”为当前事实，也不能仅从不可信历史正文解析数字形成权威记录。

待决定：

- 是否接受显式本轮来源要求作为高可靠入口，auto 自由聊天保留概率性选择？
- 对未认证的来源声明，拒绝整个成功轮次、降级为模型说明，还是只提供标识？三者保证不同。
- 是否需要最小结构化来源声明以增强正文边界；不能同时承诺完全自由文本和全面确定性语义检查。
- B2 是否值得引入短寿命可信 receipt；如暂不引入，历史只能作为未认证对话参考。
- 指定 Tool 不兼容时采用明确安全失败 / 用户澄清，而不是静默回退 auto，是否作为统一策略？

## 10. 未来最小回归矩阵

### 10.1 场景矩阵

| # | 场景 | 目标行为 | 离线 / scripted 检查 | 用户真实模型验收 |
| --- | --- | --- | --- | --- |
| 1 | Fresh：什么是溶氧？ | 直答，无系统来源声明 | auto 无 call 合法；不读 Store / RAG | 概念回答是否避免无意义 Tool |
| 2 | Fresh：现在溶氧是多少？ | 本轮查询 | Requirement 若明确，合法单 call → Reader → 第二轮；no call 拒绝认证 | 自动选择和指定选择分别测量 |
| 3 | Fresh：当前水质评分多少？ | 本轮 score | 查询结果不能认证评分；评分 Tool 自带水质，无额外 get | 是否择一评分而非同时两 Tool |
| 4 | Fresh：项目资料里鳗鲡低氧表现？ | Knowledge 或明确项目资料不可查询 | query 必填、授权、结果来源；无 call 不认证项目检索 | 记录有效 query 与实际调用，区分 relevance |
| 5 | 旧 DO=2.2 → 刚才2.2是什么意思？ | 可解释历史，无需重查询 | 保留历史数值，标为历史，不授予当前 receipt | 不强迫无意义新查询 |
| 6 | 旧2.2 → Apply6.4 → 现在还是2.2吗？ | 新查询后对比 | Store 改值、历史不改；scripted 调用取6.4；scripted 跳过不能认证当前 | 同一会话是否重新调用，保留失败次数 |
| 7 | 旧 NO_DATA → Apply Snapshot → 再问当前值 | 新查询，不能沿用旧无数据 | 旧 NO_DATA 范围仅历史；当前查询有数据 | 复现 T2，对照 fresh / history |
| 8 | 历史评分 → 再问当前评分 | 新 score，不复用旧分数 | 旧文本不是新 score receipt；用户自报分数也不能认证系统评分 | 复现 H1，记录 Tool 名称和轮数 |
| 9 | 无 Knowledge，却声称项目检索 | 来源不可认证 | 伪造结构化来源被拒；纯文本保证限度明确；错误不升为可信摘要 | 复现 K1，记录虚构来源，不只看答案似乎正确 |
| 10 | Knowledge NO_MATCH | 说明无命中，不编造出处 | 可认证执行但无 Evidence ID 可引用；合法第二轮 | 是否把常识伪装成命中资料 |
| 11 | content 模仿调用，tool_calls=[] | 不执行、不认证操作 | 明确 requirement 未满足；auto 标识零 Tool，不 regex 执行 | B1 / B2，同问题清空前后比较 |

### 10.2 测试层级与不足

- **纯离线 deterministic**：History 投影 / 裁剪、receipt 来源与字段、NO_DATA 时间范围、Policy / Capability gate、choice 编码、指定 Tool 返回检查、来源允许集合、客户端 metadata 伪造、单调用 / 单 round / 取消预算。
- **Scripted model tests**：显式安排 no call 假声明、错误 Tool、多个 call、合法 query、NO_MATCH、第二轮继续调用；验证应用应接受 / 拒绝什么，不拿 fixture 的正确选择证明真实 LLM 会选择。
- **Browser tests**：工作区保留、真实 reload 初始化与清空、模型切换确认、epoch 过期不重发；实际 Activity 与声明区别；失败不进成功 History；显示历史可多于模型 Context；textContent 与安全错误不回归。真实浏览器恢复缓存须另测，VM DOM fixture 不足以证明该行为。
- **用户人工真实模型验收**：固定精确模型、OFF + Normal、授权集合与预算；对 fresh / history、旧值 / NO_DATA、auto / 已验证 exact 分组，记录请求数、实际调用、结果状态和虚构来源。后续另行制定有限请求预算，本轮不发请求，不测试未授权模型。

现有 [Assistant tests](../../../../tests/assistant/test_assistant.py) 的 question matrix 预先选择正确 scripted response；未授权 score 测试预先返回合规拒绝正文。现有 [Browser tests](../../../../tests/web/test_browser_streaming.cjs) 的旧值追问 fixture 根据问题返回新值，验证了 UI 与历史传输，不证明真实模型必然重新调用。应补入“模型不遵守规则”的反例，而非继续只测正确回答。

[T1 tests](../../../../tests/providers/test_gateway_tool_contract.py) 已检查字符串 choice 编码与标准调用协议；[Coordinator tests](../../../../tests/tools/test_tool_conversation.py) 覆盖限额、取消、错误和 follow-up。未来修改需保持这些行为，但本轮只阅读断言，未执行测试，不能引用旧通过数量为本轮结果。

## 11. 风险与限制

- 强制错误 Tool 会错误理解概念、历史解释和用户提供值；未授权 Tool 不能被 Requirement 自动开放。
- required 可能允许多个 calls，Qwen 还存在官方保证限制；指定函数也要验证实际 call，不能只看请求参数。
- History 摘要可能损失指代、用户修正与解释背景；从模型全文抽取“事实”会把错误包装成权威。
- 浏览器回传的时间、工具名、来源类别、数值都不天然可信；需要新合同却不做信任校验会扩大问题。
- 执行 receipt 证明操作发生，不证明模型忠实引用、Evidence 相关性、诊断绝对正确或专业标准。
- 纯文本自由回答无法通过简单协议检查全面验证 provenance；结构化声明也不是全部正文的真伪证明。不得把来源 badge 当成问题已全部解决。
- 一个 Tool 预算不满足“同时查当前水质、评分、项目资料”的所有需求；应说明未查询项，不扩成 Agent 或自动第三次请求。
- 模型、Provider API 与别名版本会变化；可靠性记录需要绑定输入和版本，不从单次 smoke test 推导长期保证。

## 12. 不实施项与本轮交付检查

本轮不修改产品代码、Prompt、History、Policy、Registry、Handler、Adapter、Capability / Preset 合同或 UI；不增加 Tool、Multi-Tool、Multi-Round、Agent、长期 Memory、RAG v2、Analysis + Knowledge 双重来源改造、Credential / ACL 操作。不访问正式凭据、不自动请求真实 Provider、不修改生产项目、不 commit / push。

只新增本文；正式 deep-dive 与 STRUCTURE 保持原状。依据包含 [ROADMAP](../../../ROADMAP.md)、[阶段总结](../knowledge-tool-v1/2026-10-knowledge-tool-v1-summary.md)、[当前 Assistant 架构](../../../deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md)、[只读 Tool 实现](../../../deep-dive/tools/READ_ONLY_TOOL_CALLING.md)和[新增 Tool 规范](../../../deep-dive/tools/ADDING_A_TOOL.md)。

交付检查：14 个本地链接全部存在；4 个外部链接为本轮已查阅的官方文档。本文无尾随空白，常见凭据字面量扫描无命中，`git diff --check` 无错误。开始时工作树干净，结束时仅本文为 untracked；跟踪文件没有 diff。新增文件另行检查空白，不把 `git diff --stat` 不显示 untracked 误写成没有新增内容。

没有运行 Python / Browser 产品测试，也没有真实 Provider 请求或凭据读取。研究完成后等待用户与 ChatGPT 审阅，不自动进入修复。

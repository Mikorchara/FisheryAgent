# 多模型 API、能力与参数架构评审计划

状态：**设计提案，尚未批准或实现**。本轮只依据当前源码和官方接口文档分析；没有读取正式项目保存真实 Key 的 `llm_settings.json`，也没有调用任何模型 API。正式项目 `D:\Fishery_Project` 始终只读。本文优先服务于受硬件条件限制时的外接 LLM 连接与结果显示；本地运行时验证仍按 [V0.1.1 计划](V0.1.1_LOCAL_RUNTIME_VALIDATION.md)在条件具备时进行。

## 1. 正式项目：当前配置与请求链

**代码确认：**`core/llm_settings.py` 将每个方案保存为 `id/name/base_url/api_key/model/created_at`，另用 `active_id` 表示当前方案；未启用自定义方案时使用 `config.py` 的默认地址、环境变量 Key 和模型。界面可新增、编辑、保存、启用、禁用、删除方案，也能手填任意 Base URL。预设选择只填入地址，用户仍可改写。后端 `/llm_models` 用 SDK 的 `models.list()` 获取模型 ID，`/llm_test` 用 `max_tokens=1` 发起真实探针。模型列表只是便捷输入，不能证明某个模型支持哪些参数。证据：`core/llm_settings.py:24-36,80-114,130-190`、`app.py:434-443,572-686`、`templates/index.html:1620-1629,1735-1858`。

| 当前问题 | 代码所示行为 |
| --- | --- |
| Provider 如何配置？ | 方案记录**名称、地址、Key、模型**；没有独立的协议类型或规范化 Provider ID。前后端各有一份服务预设名单。 |
| 用户可调哪些字段？ | UI 可调方案名、Base URL、API Key、模型 ID；不能设置 temperature、top_p、max tokens 或 reasoning。 |
| Key 如何处理？ | 已保存方案的 Key 以**明文**存在被 `.gitignore` 忽略的 `llm_settings.json`。列表接口返回首尾部分可见的打码值；编辑留空表示沿用原 Key。默认 Key 来自环境变量。忽略 Git 与界面打码不等于静态加密或完整密钥管理。 |
| 如何切换？ | 启用方案时持久化 `active_id`，并对全局 `llm_advisor` 调用 `reconfigure(base_url, api_key, model)`；启动时恢复，禁用时回到默认。进行中的请求没有不可变 RuntimeSnapshot。 |
| Provider 差异在哪里？ | `FisheryAdvisor._extra_no_thinking()` 根据**模型名前缀**对 DeepSeek V4 与 Qwen 分别构造 `thinking.type=disabled`、`enable_thinking=False`；其他模型不发送关闭参数。该逻辑不检查实际托管服务或模型能力。 |
| 生成参数是什么？ | Advice/Chat 在源码里固定 `temperature=0.7`、各自的 max tokens；Advice 另设 `top_p=0.95`。非流式与流式方法重复构造请求。 |
| 输出如何显示？ | 流式方法只把 `delta.content` 作为正文，忽略 `reasoning_content`；`app.py` 包装成 SSE 给前端，同时存在旧非流式路由。 |

**可确认的预设，不等于使用记录：**源码列有 DeepSeek、OpenAI、智谱 GLM、通义千问、Kimi、火山方舟、小米 MiMo 和“自定义”。用户报告曾成功使用三家 API，但源码不能证明是哪三家，也不能证明当前版本每个预设都已成功连接。本评审不猜测，也不读取含明文 Key 的保存文件。证据：`core/llm_settings.py:26-36` 与 `templates/index.html:1620-1629`。

**可保留的经验：**任意 OpenAI-compatible Base URL、可选择实际模型 ID、可并存多个方案、手动连接探针、启用状态可见、正文显示不依赖思考输出。**不宜复制的实现：**全局可变 Advisor、明文 Key 文件、前后端重复预设、按名称前缀推断能力、固定参数跨模型发送、重复的流式/非流式请求构造，以及将原始异常文字直接用于用户响应的做法。证据：`core/llm_advisor.py:32-60,99-112,139-157,186-259`、`app.py:447-464,529-546`。

## 2. Prototype：当前合同与边界

**代码确认：**`ModelProfile` 包含 `profile_id/display_name/provider_kind/base_url/model/secret_env`、超时、重试和仅 `streaming/tool_calling` 两个布尔能力字段。`provider_kind` 示例值是 `openai-compatible-cloud/local`，表达部署类别，既不是具体服务商，也不是独立协议 ID。`ProfileRegistry.snapshot()` 在请求开始时读取环境变量并创建冻结的 `RuntimeSnapshot`；Key 不进入 `RuntimeInfo` 或 Trace。`ModelRequest` 只有 `mode/messages/max_tokens`，默认 1024；应用编排对 Advice/Chat 分别固定 4096/2048。适配器始终发送 `model/messages/max_tokens/stream`，尚无 temperature、top_p、reasoning 或条件能力验证。证据：`src/fishery_ai/model_gateway.py:17-127`、`application.py:30-59,99-139`、`openai_compatible_adapter.py:27-70`、`resources/mock/profiles.json`。

`ModelGateway` 已有 `complete()` 和 `stream()`，SDK 只在 `OpenAICompatibleAdapter` 中导入；SDK 自身重试已关闭，适配器按“正文尚未输出”边界重试。`Orchestrator.analyze()` 目前只调用 `complete()`；默认 Demo 只装配 `MockGateway`，因此 Cloud/Local 示例 Profile 的路由测试不等于真实连接或应用层流式显示。`ModelEvent` 仅有 `delta/usage`。证据：`src/fishery_ai/openai_compatible_adapter.py:27-135`、`model_gateway.py:109-160`、`composition.py:15-29`。

本计划与现有 [README](../../README.md)、[路线图](../ROADMAP.md)、[结构说明](../STRUCTURE.md)和 [V0.1.1 验证计划](V0.1.1_LOCAL_RUNTIME_VALIDATION.md)保持一致。此处不把尚未实现的能力描述成现有功能。

## 3. 五个必须分开的概念

| 概念 | 回答的问题 | 例子及边界 |
| --- | --- | --- |
| Provider identity | 谁提供或运营接口？ | OpenAI、DeepSeek、自定义厂商、某本地 Runtime。它是来源/管理身份，不等于协议。 |
| API protocol / adapter type | 请求与响应遵循什么接口？ | `openai_chat` 对应 OpenAI-compatible Chat Completions；将来其他协议需另有适配器。相同协议可由多个 Provider 实现。 |
| Model identity | 当前请求选择哪个模型？ | 同一地址可托管多个模型；模型 ID 应与 Base URL 一起确定，不能单凭名称前缀判定能力。 |
| Model capabilities | 该模型在这个运行时上能做什么？ | 流式、结构化输出、思考开关/档位、采样参数、工具调用；服务可支持某字段，但具体模型可能不支持。 |
| Request-time options | 这一次希望怎样生成？ | 思考 `AUTO/ON/OFF`、effort、temperature、输出上限。选项是意图，不是 Provider 原始字段。 |

**推论：**当前 `provider_kind` 同时承担部署标签和“似乎代表兼容协议”的暗示，无法表达“同一厂商的不同协议”或“同一协议的多个模型能力”。后续字段应分别表达这些概念，不能仅把所有参数塞进 `provider_kind` 或一个原始字典。

## 4. 三层参数模型：评估与建议

### 第一层：Provider-neutral 语义选项

建议先考虑**可选且能区分未设置与显式设置**的生成选项，以及小型 `ReasoningOptions`：`mode=AUTO/ON/OFF`，`effort=AUTO/LOW/MEDIUM/HIGH` 仅作为初步语义集合。`AUTO` 表示沿用模型/服务默认行为、通常不发控制字段；`OFF` 是明确关闭请求，只有明确支持关闭时才能发送。`None`/未设置与显式数值也应区分。当前 `ModelRequest.max_tokens` 及 Advice/Chat 固定值需要迁移策略；不能把语义名称换成 `max_output_tokens` 就假定所有服务对“可见输出”与“思考预算”的含义相同。

`presence_penalty`、`frequency_penalty` 可以进入候选清单，但在没有真实场景和已验证模型前，不必一次性做成公共合同。原始模型 ID、Key、协议字段不属于 `GenerationOptions`。**替代方案**是每次请求携带 Provider 原始 dict：接入快，但业务层将知道厂商字段且无法可靠校验；不推荐作为主路径。

### 第二层：能力与组合约束

对显式参数，区分 `SUPPORTED`、`UNSUPPORTED`、`UNKNOWN`；`CONFLICT` 是一次请求在组合校验后的**结果**，不是模型永久能力。条件能力只记录少数已确认的约束，例如某模型开启思考时不接受或不生效的 temperature；不建立通用规则引擎。当前 `Capabilities(streaming, tool_calling)` 两个布尔值无法表示“未知”、思考档位或参数冲突。

这个问题有实际依据：DeepSeek 官方文档说明思考模式下 `temperature`、`presence_penalty`、`frequency_penalty` 不生效，`top_p` 还有模式相关范围；阿里云百炼的 OpenAI-compatible 文档说明 `enable_thinking` 是非标准参数，模型间默认值与可用范围不同。它们支持“**按接口 + 精确模型 + 模式**校验”的必要性，但不能替代在本项目选定服务上实测。参见 [DeepSeek 思考模式说明](https://api-docs.deepseek.com/guides/thinking_mode/)与[阿里云百炼 Chat Completions 文档](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)。

### 第三层：适配器翻译

验证通过后，适配器把语义意图映射为标准 SDK 字段或该 Provider 的受控 `extra_body`。例如 `ReasoningOptions(mode=ON, effort=HIGH)` 可能映射为 `reasoning_effort`、`thinking.type`、`enable_thinking`，也可能根本无法映射而被拒绝。映射取决于所选协议、Provider 与精确模型；不在 Orchestrator 中写 `if provider == "DeepSeek"` 或 `if provider == "Ollama"`。

**判断：**三层结构适合本项目，但应逐步引入。先实现真正需要的选项和少量明确约束；“任何 Provider 都能归一成同一组档位”尚未得到证实，不能把上述示例字段视为已定合同。

## 5. Provider 与 Model 能力如何合并

同一 Provider/Runtime 可能提供 Model A（支持思考和工具）、Model B（不支持思考）及 Model C（档位不同）。`/models` 通常只解决“模型 ID 存在吗”，不能自动推断完整能力。V0.1.1 不建立在线能力发现服务。

**最小方案：**每个 Profile 仍绑定一个 `base_url + model`。协议适配器给出它**能够翻译的字段集合**；可选的 Provider 预设提供有证据的缺省约束；Profile 对当前**精确模型 ID**保存经文档或人工验证的能力声明及来源/版本。换模型或换地址时，原模型声明失效，重新回到 `UNKNOWN`，不能把旧模型能力继承给新模型。暂不需要独立 Model Registry 类；多模型可先使用多个 Profile。

有效能力按协议可表达范围、Provider 限制与精确模型声明收敛：任一层明确 `UNSUPPORTED` 则拒绝；缺少证明时保持 `UNKNOWN`；只有目标组合有证据才视为 `SUPPORTED`。若来源声明互相矛盾，禁止请求并要求校正配置，而不是猜测优先级。能力声明也应包含证据来源、测试时间和适用模型版本，避免“永久支持”的误解。

## 6. 通用自定义 API：保守基线

建议支持一个语义为 `generic_openai_chat` 的配置值，映射到现有 `OpenAICompatibleAdapter`。Profile 至少记录 `profile_id/display_name/adapter_id/base_url/model/secret_env`；Provider 身份可选或写为 `custom`。本地兼容服务可以不需要真实 Key；Cloud 服务的 Key 仍通过环境变量引用，Profile 不存明文。

**最小可假设范围：**对自称兼容 Chat Completions 的服务，只假设可尝试 `model + messages` 并验证返回的正文结构。`stream`、`max_tokens` 或 `max_completion_tokens`、采样字段、思考控制、JSON 模式、工具调用都需显式声明或实测。当前适配器无条件发送 `max_tokens` 和 `stream`，因此它是**现有基线行为**，不是通用兼容性的保证。迁移时必须解决：当通用服务尚未确认输出上限字段时，内部默认预算如何处理；用户**显式**要求的预算不得在不告知的情况下被省略。

如果接口并不实现 Chat Completions，不能仅换 Base URL 强行接入；等实际需求出现时再新增协议适配器。通用 Profile 的高级能力默认 `UNKNOWN`，不能因为厂商名称相似而自动开启。

## 7. Provider-specific 参数与原始覆盖

确需特殊字段时，建议使用**由适配器识别的命名空间**，例如概念上的 `provider_options.deepseek`，且只能在 `adapter_id` 与 `provider_id` 匹配、精确模型能力允许时使用。适配器负责生成 SDK 的 `extra_body`；Orchestrator 和规则/RAG 服务看不到这些字段。不同命名空间互斥，不能把 DeepSeek 的 `thinking` 发送给 Qwen 或自定义服务。

首版**不建议开放全局原始 `extra_body`**。它可绕过校验、覆盖标准字段，也容易把敏感信息写进配置。若未来 Developer Validation 确有需求，可作为默认关闭的高级实验入口：仅在明确协议/Provider 下启用；限制允许键；拒绝与语义选项冲突的键；不得包含密钥或 URL；输出有效负载预览时脱敏；不自动持久化；所有使用都标注“未保证兼容”。是否引入仍需用户批准。

## 8. 验证策略

| 策略 | 好处 | 代价与判断 |
| --- | --- | --- |
| A. 静默丢弃不支持字段 | 某些请求可能继续成功。 | 用户以为选项生效，排障困难；不推荐。 |
| B. 全部发送给服务 | 实现最快。 | 服务可能拒绝，也可能悄悄忽略；无法保证 UI 显示与实际行为一致；不推荐作为默认。 |
| C. 发送前严格校验 | 配置错误可解释、可测试。 | 需要维护已验证的能力声明；**推荐**。 |

建议规则：显式选项为 `UNSUPPORTED` 时返回 `OPTION_UNSUPPORTED`；为 `UNKNOWN` 时返回 `OPTION_UNKNOWN` 并说明如何验证或配置；组合不成立时返回 `OPTION_CONFLICT`，指出字段和模型。`AUTO`/未设置不等于显式 `OFF`，前者可保持不发送控制字段。示例：已确认所选模型思考模式下 temperature 无效，用户同时显式要求 `reasoning=ON` 与 `temperature=0.7`，则在发请求前报冲突；不得自动删 temperature，也不得把无效组合发给 Provider。错误码名称只是提案，不是现有实现。

严格校验不意味着替服务承诺成功：只校验本地已知约束，仍需记录真实 API 拒绝与静默忽略。未知能力的“先试后记”只能放在明确标记的受控验证流程，不能成为普通业务默认行为。

## 9. 未来 Developer Validation UI 的含义

本轮不实现 UI。未来切换 Profile/Model 时，界面应按有效能力显示**有意义的控件**：通用输出上限、可用的 temperature/top_p、思考 `Auto/On/Off` 与该模型允许的 effort 档位；Provider 专项设置只出现在匹配的适配器区域。未知或不支持的高级项宜禁用并解释原因；完全无关的项可隐藏。更换模型后，旧模型专用设置应失效并明确提示，而不是暗中沿用。

正式项目“自定义地址、获取模型、测试连接、当前启用方案可见”的体验值得保留为设计目标，但 Prototype 的 UI 不能沿用其明文 Key 持久化方式。连接探针可能消耗 Cloud Token；未来执行时需由用户明确发起，并把 Key 排除在响应、Trace 和普通日志之外。

## 10. Streaming 与 Reasoning 输出

`reasoning.mode/effort` 是**输入控制**；`reasoning_content` 或 reasoning delta 是**可选输出**。模型可能无法关闭思考，也可能不公开思考文本。应用正确性只依赖正式正文、确定性事实和结构化结果，不依赖思考文本。正式项目在 SSE 中只转发 `delta.content` 的做法体现了这条边界；Prototype 当前适配器也只读取正文 delta。证据：正式项目 `core/llm_advisor.py:193-210,239-256`；Prototype `openai_compatible_adapter.py:107-125`。

未来如有明确显示需求，`ModelEvent` 可区分 `content_delta`、可选 `reasoning_delta`、`usage`、完成事件和错误事件。但当前合同只有 `delta/usage`，应用编排尚未调用 `stream()`；不应为未实现的 UI 提前引入复杂事件层。思考文本的保存、展示和隐私策略也应另行决定，默认不写 Trace。

## 11. 对 V0.2 Tool Calling 的兼容性检查

本轮不设计工具，也不发送工具请求。架构上只要求保留：协议适配器可翻译未来的工具字段；有效能力由**精确模型**决定；Gateway 的结果合同将来能够表达非正文的工具调用，而不把工具调用混进纯文本 `generated_text`；应用层始终决定权限和是否执行。当前 `ModelResponse.text` 与 `ModelEvent.delta` 还不足以承载工具调用，这是 V0.2 的明确扩展点，不要求现在重写整个 Gateway。

## 12. 正式项目、当前 Prototype 与提案对比

| 维度 | 正式 Fishery_Project（代码确认） | 当前 Fishery_AI_Prototype（代码确认） | 提案（未实现） |
| --- | --- | --- | --- |
| 自定义 API | UI 可手填任意兼容 Base URL。 | Profile 可配置 HTTP(S) Base URL；默认仅 Mock Demo。 | 保留 `generic_openai_chat`，但高级能力默认未知。 |
| 模型选择 | 可手填，也可请求 `/models` 列表。 | Profile 固定模型 ID，示例有占位符。 | 多模型先用多个 Profile；列表只辅助选择，不代替能力声明。 |
| Secret | 保存方案含明文 Key；列表打码。 | Profile 只存 `secret_env`，RuntimeSnapshot 解析 Key；Trace 白名单。 | 继续环境变量引用；UI 密钥持久化另议。 |
| Provider 参数 | 模型名前缀分支构造关闭思考的 `extra_body`。 | 尚无 Provider 参数。 | 经匹配的适配器专属映射，不进入业务层。 |
| Runtime 快照 | 全局 Advisor 可热切换，进行中请求无不可变快照。 | 请求开始创建冻结 Snapshot。 | 保留冻结语义，并冻结选项和有效能力。 |
| 参数校验 | 仅检查地址/Key/模型非空；参数组合主要交给 API。 | Profile 基本字段校验；无生成/思考能力校验。 | 对显式选项严格校验，明确不支持/未知/冲突。 |
| Reasoning | 尝试默认关闭部分模型；输出思考不进正文。 | 无输入控制；流事件只保留正文。 | 将输入控制与可选输出分开。 |
| Streaming | 生产 SSE 路由和前端已使用。 | Gateway 有 `stream()`；Orchestrator 尚未接入。 | 先验证网关，再设计应用层显示。 |
| Tool Calling | 此评审不确认其业务工具链。 | 未实现。 | 仅保留能力与类型扩展边界，V0.2 再设计。 |
| 可扩展性 | 多兼容地址方便，但全局状态及模型名启发式耦合。 | 网关边界清楚，但能力和参数语义过少。 | 小型语义选项 + 精确模型能力 + 适配器翻译。 |

**GOOD IDEAS TO RETAIN：**自定义地址、多方案、模型可选择、明确测试入口、正文独立显示。**LEGACY BEHAVIOR NOT TO COPY：**全局可变 LLM client、明文 Key 文件、重复预设/请求逻辑、模型名前缀决定参数、跨模型固定采样值、对不支持参数无本地提示。

## 13. 最小架构提案：每个抽象的必要性

| 候选 | 解决的具体问题 | 现状为何不足 | 时机 |
| --- | --- | --- | --- |
| `ModelProfile` / `RuntimeSnapshot` | 固定地址、模型、Key 引用和请求身份。 | 已存在；需把协议身份与 Provider 身份分开，并冻结后续能力声明。 | **保留并小幅扩展**，不重建。 |
| 可选 `GenerationOptions` | 表达“显式设置”与“不设置”的差别，承载少量通用生成意图。 | 目前仅有始终发送的 `max_tokens`，temperature 等无合同。 | 外接多模型确有差异时引入最少字段；惩罚系数可延后。 |
| 小型 `ReasoningOptions` | 区分 `AUTO/ON/OFF` 和可验证的 effort 档位。 | 现状没有思考请求合同；正式项目的模型名前缀策略不能复制。 | 连接到第二种有差异的模型前设计，具体档位可按证据收窄。 |
| `ModelCapabilities` 数据声明 | 记录精确模型的支持/不支持/未知与少量冲突。 | 当前两个布尔值无法支持严格校验。 | 与显式选项同时引入；先放在 Profile 对应模型的配置中，不建在线发现。 |
| `CapabilityValidator` | 在发请求前给出明确冲突。 | 当前 Gateway 直接构造 SDK 请求。 | 先实现一个纯函数/小模块；无需独立规则引擎或 DI。 |
| `AdapterRegistry` | 在多个协议适配器之间选择。 | 当前只有一个真实协议适配器。 | **推迟**到确实出现第二种协议。现阶段一个受控 `adapter_id` 分支即可，不能出现在业务层。 |

提案的数据流是：`AnalysisRequest + 语义选项 → 当前 Profile/精确模型能力快照 → 校验 → OpenAICompatibleAdapter 翻译 → SDK`。Orchestrator 保持诊断/RAG 的固定顺序，不读 Provider 原始字段。大多数新增字段均可选，未显式设置时保持现有 Mock 流程；如何处理当前固定 `max_tokens` 是迁移中的优先设计点。

## 14. 分阶段迁移计划

1. **证据清单（先做）**：记录要接入的外接 API、准确模型 ID、官方参数范围与当前生产使用经验；用户报告的“三家”需由用户确认，不从预设推断。与 [V0.1.1 验证计划](V0.1.1_LOCAL_RUNTIME_VALIDATION.md)区分“Mock 已通过”和“真实 API 已通过”。
2. **合同与 Profile（后续实施）**：以兼容旧 JSON/离线测试的方式增加协议身份、可选语义选项与精确模型能力声明。切换模型时使旧能力声明失效。明确 `max_tokens` 默认值迁移，避免现有 Advice/Chat 的固定上限导致通用服务误报或静默省略。
3. **校验与翻译**：先做纯离线严格校验，再让适配器映射标准参数及少数有证据的 Provider 专项参数。SDK 仍只在适配器中；默认 MockGateway 与 JSONL 脱敏保持不变。
4. **外接 Cloud API 受控验证**：在明确授权、实际 Key 与费用边界下，逐个验证 Provider/模型的非流式、网关流式、错误与显示字段；不把一次成功连接推广为该 Provider 所有模型的能力。
5. **Developer Validation UI（可后置）**：先确认需要哪些控件和错误说明，再实现。此阶段之前可以用受控 CLI/脚本验证，不必复制生产 Flask 页面。
6. **Local Runtime 验证（硬件可用时）**：执行既有 V0.1.1 本地验证计划；协议与能力合同复用，不添加 Ollama/vLLM 业务分支。

每阶段保持已有离线测试通过；真实 API 检查与默认测试分离。此迁移顺序是提案，实际开始编码前需确认第 16 节决策。

## 15. 后续离线测试计划（本轮不实现）

| 测试组 | 最少用例与预期 |
| --- | --- |
| Profile/身份 | 通用 OpenAI-compatible Profile、自定义地址、已知 Provider Profile；协议、Provider、模型三者分别保留。 |
| Reasoning | `AUTO` 不发送强制开关；`OFF` 仅在可关闭时翻译；不支持思考时显式 `ON` 报错；努力档位仅允许声明的值。 |
| 采样与冲突 | 不支持 temperature/top_p 时显式请求被拒绝；思考 ON + temperature 的已声明冲突报错；参数不会被静默删除。 |
| 未知能力 | 显式高级选项遇 `UNKNOWN` 给清晰错误；普通未设置选项保持默认路径；无能力资料时不得按模型名前缀猜测。 |
| Provider 隔离 | DeepSeek 专项设置不会送到 Qwen/自定义端点；不同适配器的命名空间不串用；原始覆盖默认关闭。 |
| 快照与密钥 | 请求开始后修改 Profile 不改变在途 Runtime；Key 不出现在 `repr`、公开结果、异常、Trace 或请求调试输出中。 |
| 传输与网络 | 假 SDK 客户端检查实际发送字段与重试边界；默认测试阻断 socket，不调用真实 API。 |
| 回归 | 当前 `MockGateway`、Chat/Advice、JSON 解析、规则/RAG 及全部既有离线测试继续通过。 |

## 16. 需用户拍板的决策

1. **能力资料放哪里？**建议 V0.1.1 先随“精确模型对应的 Profile”保存有来源的能力声明；Provider 预设只给保守约束。是否需要单独的模型登记表，可在多个 Profile 重复且维护困难后再决定。
2. **是否需要通用自定义 API Profile？**建议需要，但只保证最小 Chat Completions 握手；未知高级能力不自动开启。
3. **显式参数遇 `UNKNOWN` 怎么办？**建议默认拒绝并提示如何验证；受控开发测试可另设显式探测路径，不作为普通业务请求默认。
4. **允许原始 Provider 覆盖吗？**建议首版不开放；如确需实验性 `extra_body`，须先批准其范围、隔离、脱敏与持久化规则。
5. **Reasoning 归一化到什么程度？**建议先保留 `AUTO/ON/OFF`，effort 只覆盖已有证据的交集；不强行把所有厂商档位对应为同一语义。
6. **现在需要哪些专项适配器？**建议真实验证前仍只有 `OpenAICompatibleAdapter`；若某个已确认 Provider 的差异无法由该适配器的受控映射承载，再决定是否拆分。请用户确认最先验证的外接 Provider 与准确模型 ID；现有代码不能判定“三家”具体是谁。
7. **当前固定输出上限如何迁移？**建议显式请求必须可校验；对于通用服务尚未知的 `max_tokens`/`max_completion_tokens`，需先决定是要求 Profile 声明支持、还是将未指定预算交由服务默认值处理。不可悄悄丢弃用户显式选项。

## 评审结论（供决策）

### CODE-CONFIRMED

- 正式项目的持久化方案为地址、明文 Key 和模型，UI 支持自定义地址、模型列表与连接测试；Provider 预设不是成功使用记录。正式项目按模型名前缀构造关闭思考字段，固定发送采样参数，流式 UI 只显示正文。
- Prototype 已有冻结 RuntimeSnapshot、环境变量 Key 引用与 SDK 适配器；还没有请求时采样/思考能力合同，默认 Mock 演示也不连接真实服务。当前应用层未接入流式接口。

### PRODUCTION PROJECT LESSONS

- 保留多方案、自定义 OpenAI-compatible 地址、模型选择、受控连接测试与清晰的启用状态；把正文与可选思考内容分开。
- 不复制全局可变客户端、明文 Key 持久化、名称前缀启发式或重复的前后端参数/预设逻辑。

### PROBLEMS

- 现有 Prototype 将 Cloud/Local 部署标签放在 `provider_kind`，不能表达 Provider、协议和精确模型能力三者的差别；适配器无条件发送 `max_tokens`，高级能力只有两个布尔值。
- 真实 Provider/模型的参数支持仍未在本项目验证；同名语义参数可能被拒绝，也可能被静默忽略。

### PROPOSED DESIGN

- 采用少量 Provider-neutral 语义选项、精确模型的有来源能力声明、发请求前的严格校验，以及适配器内的受控翻译。`AUTO` 与 `OFF` 保持不同；未知的显式高级选项默认拒绝。保留现有 Gateway/Mock/Snapshot，不为单一适配器建立复杂 Registry。

### ALTERNATIVES

- 单一原始 dict 和“全部透传”接入快，但 Provider 参数易串用、不可保证用户设置生效；静默丢弃虽能降低部分报错，却会隐瞒配置结果。单独模型登记表适合未来多模型重复配置增多时；当前每个 Profile 绑定一个模型已足够。原始 `extra_body` 仅考虑受控实验入口。

### DEFERRED

- UI、在线能力发现、第二协议适配器、通用规则引擎、应用层流式显示、Tool Calling、Agent Loop、Memory、生产适配器及本地模型部署均不在本轮实施。

### DECISIONS NEEDED

- 请确认第 16 节七项决策，尤其是首先验证的外接 Provider/模型、通用 Profile 的能力来源、未知参数策略、原始覆盖范围，以及当前输出上限的迁移语义。本文仅提出推荐，不代替批准或真实 API 验证。

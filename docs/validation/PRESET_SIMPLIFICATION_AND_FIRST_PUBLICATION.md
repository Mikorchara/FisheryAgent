# Preset 简化与首个正式方案发布

> 文档分类：**CURRENT**。当前指南 / 维护依据；其中明确标记的旧阶段内容仍为历史。当前源码高于文档。 第 12 节登记当前三个固定合同与人工依据；其余章节明确保留历史。 当前边界见[架构总览](../architecture/CURRENT_ARCHITECTURE.md)。

日期：2026-10-03。当前状态：Qwen 3.8 Flash、DeepSeek Flash、Ollama Qwen3.5 4B 已登记发布合同，各为 1.0.0；离线验证完成，工作树等待最终人工验收；不 commit / push。

**阅读说明：第 1–11 节保留首轮发布及上轮资格验证的历史；当前发布状态以第 12 节为准。用户随后已在正常 Web 进程完成人工验证。旧 CREDENTIAL_FILE_ERROR / READ_TIMEOUT 与未发布候选结论不再代表当前登记状态。**

## 1. 最终用户定位

Preset 是项目开发者验证并发布的固定模型方案。用户只选择 Model、Thinking、Response Mode，继续使用现有水质场景、问题和开始分析入口。页面不显示 Capability、Evidence、Probe、Resolver、ProtocolSpec、Base URL 或 Credential Ref。RAG Evidence 是分析背景知识，仍保留在结果区，与模型能力 Evidence 无关。

未发布模式显示“此 Preset 未提供该模式”，不显示 UNKNOWN。真实请求仍需要明确确认 REAL NETWORK REQUEST。凭据缺失安全失败，用户应到开发侧凭据管理设置 Key。

## 2. Template / Variant / Contract

包内 `src/fishery_ai/resources/profiles/presets.json` 使用 schema 2：

- Template：一个固定连接，包含 service、adapter、Base URL、精确 Model、Auth / credential_ref、有限 timeout、contract_version、固定 ProtocolSpec、固定 Capability Contract 和维护摘要。
- Variant：只保存 Thinking 模式及已发布 Response Mode 列表，不复制整套连接。
- 本轮 `preset_id=dashscope-qwen38-flash-r1`，`contract_version=1.0.0`，`protocol_spec_id=dashscope_chat` / version 1。
- Timeout 固定 connect 5s、read 30s、total 120s；Gateway / SDK retry=0。
- 加载时校验精确 Identity、协议编码、默认组合及已发布组合的一致性。运行 Snapshot 持有不可变固定 ProtocolSpec，不按本地 Evidence 重新选择。

旧 schema 的读取仅保留为历史回归兼容；活动目录不加载历史 fixture 或归档。以后协议编码改变需要维护者明确更新合同，不能静默改变已发布请求。

## 3. Default Preset

开发者配置 `default_preset_id` 指向已发布模板。当前默认新 Qwen 3.8 Flash，默认 Thinking OFF + Normal。

设为 null 或移除时显示“请选择模型”，不偷偷选第一项；无效或未发布默认 ID 拒绝加载。Thinking 与 Response Mode 独立：ON 不会自动变 Streaming，OFF 不等于 Normal。

## 4. 首个候选审计与依据

本轮审计当前源码、活动 Custom Profile、精确 Evidence 和成功 Trace，没有恢复 Clean-room 前资产。

| 项目 | 审计结果 |
| --- | --- |
| 精确 Identity | dashscope / openai_chat / https://dashscope.aliyuncs.com/compatible-mode/v1 / qwen3.8-flash |
| 当前来源 | Clean-room 后用户新建 QW_1 / QW_2；连接与凭据引用由代码实际确认 |
| 凭据引用 | DASHSCOPE_API_KEY；只复制引用名，不复制 Secret 或文件路径 |
| ProtocolSpec | 当前 R3 dashscope_chat：ON/OFF → enable_thinking true/false，AUTO 不发送开关 |
| ON Normal | 2026-10-02 17:58:12 UTC，USER_VERIFIED，返回 qwen3.8-flash，1312ms，78 total tokens |
| OFF Normal | 2026-10-02 17:58:15 UTC，独立 USER_VERIFIED，返回同一模型，859ms |
| Streaming | 2026-10-02 17:58:18 UTC，独立 USER_VERIFIED，有有效正文 delta |
| ON Streaming 组合 | 2026-10-02 17:58:24 UTC，独立 USER_VERIFIED，正文 delta 1、reasoning delta 8、usage 64/22/86，reasoning tokens 19 |
| 组合时间 | 首个模型 delta 2532ms，首个正文 delta 2938ms，总耗时 2969ms；不混淆两种 TTFT |
| 完整分析 | 当前 web-traces 中存在该精确模型和活动 Profile 的 completed 分析记录；不从 Trace 推断未记录的 Thinking 组合 |
| Manual V1 原始响应 | 不持久化，无法事后复原；本轮补查被 CREDENTIAL_FILE_ERROR 拦截，列入人工验收，不宣称已复查 |

维护者发布判断：这些精确单项 / 组合 Probe，加上成功分析记录，为以下三种发布模式提供直接运行依据；不把 SUPPORTED 扩大成全部模式已验证。上述时间和统计是既有用户验证记录，不是本轮新增请求。

## 5. 发布与未发布

| Thinking | Normal | Streaming |
| --- | --- | --- |
| OFF | 已发布，默认 | 未发布 |
| ON | 已发布 | 已发布 |
| AUTO | 未发布 | 未发布 |

AUTO 代表服务默认行为，不伪装成 OFF；未单独完成默认行为验证，因此暂不发布。OFF + Streaming 未单独形成足够组合验证记录，暂不发布。Effort、采样参数、Tool Calling、Structured Output 及模型默认 Thinking 未纳入首版用户合同，相应高级能力保持 UNKNOWN。未新增或恢复 DeepSeek / Ollama Preset。

## 6. 与 R4 / R5 / Manual 的边界

Preset：加载发布合同 → CredentialStore → 检查已发布组合 → 固定 ProtocolSpec → 原有 Adapter / Gateway → Orchestrator / AnalysisResult / Trace。

Preset 不进入 R4 Resolver、R5 Probe、Metadata 授权或 Runtime Defaults 的 Managed 安全回退。固定 Capability 仅供既有请求校验器内部使用；本地矛盾 Evidence 不能修改它。失败只返回错误，不写合同。

Managed Custom：继续使用 R3 / R4 / R5，精确 Identity 与共享 Evidence 规则不变。用户偏好不是发布默认值。

Manual V1：仍可选择已保存的 Preset 连接进行开发检查；只在这个独立开发视图读取只读连接详情，不把详情合并回用户 Preset 目录。Raw JSON 不自动套用固定 ProtocolSpec。

Manual V2：独立实验和 manual.env 不变，不产生 Preset。没有自动 Custom → Preset、Publisher UI 或新能力。

## 7. 本轮真实检查与安全

本轮允许受控联网，计划用三次短 Manual V1 请求复查 OFF Normal、ON Normal、ON Streaming，每次最多 128 output tokens，retry=0。实际在正式私有 CredentialStore 的 resolve 阶段返回 CREDENTIAL_FILE_ERROR，尚未创建 SDK 请求；本轮模型生成请求数 **0**，新增 Token 消耗 **0**。

另只检查了既有本地 Web 是否可用，未建立连接，无法通过用户运行进程补查。没有绕过私有存储安全检查、修改 ACL、读取旧源码 .env、迁移或修改任何真实 Key；不将该错误判断为模型能力不支持。当前执行环境凭据读取为何失败未在本轮扩大调查，用户正常启动后的人工验证仍必要。

## 8. 测试

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Preset targeted Python | `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_preset*.py"` | 13 项通过（新发布 9 + 历史兼容 4） |
| targeted Browser | `node --test --test-name-pattern="published Preset\|Manual V1 reads Preset\|three-mode" tests/test_browser_streaming.cjs` | 20 项通过 |
| full Python | `.venv\Scripts\python.exe -m unittest discover -s tests` | 349 项通过 |
| full Browser | `node --test tests/test_browser_streaming.cjs` | 100 项通过 |
| JS syntax | `node --check src/fishery_ai/resources/web/app.js` | 通过 |
| Diff | `git diff --check` | 通过；Git CRLF 转换提示不是测试失败 |
| Secret / 敏感路径扫描 | 仅 Git 跟踪及未忽略新增文本，输出路径与类型，不输出匹配值 | 129 个文本文件，0 风险；2 个明确虚构测试 fixture 排除 |

覆盖：Evidence 隔离、缺失凭据、未发布 Variant / 组合、固定编码与 Snapshot、默认 / 无默认、Preset 开发字段不泄露到用户目录、Managed / Manual / Stop 原路径回归。自动测试使用临时 Store、虚构 Key，网络被禁止。Browser 测试为离线 DOM 行为测试，不替代实际浏览器验收。

## 9. 人工验收清单

1. 重启 Web，Preset 默认 Qwen 3.8 Flash / OFF / Normal；不出现连接配置、能力证据或 Probe。
2. 在用户私有正式凭据存在时完成 OFF Normal、ON Normal、ON Streaming；观察结构化结果、正文 / reasoning 分离、Usage、Stop。
3. OFF 时 Streaming 禁用且提示未提供；ON 可独立选 Normal 或 Streaming，无 AUTO。
4. 缺失凭据时安全返回 SECRET_MISSING；不 fallback 到旧源码 .env。
5. Managed 同 Identity 的 Probe / Evidence 更新不改变 Preset；其他模型不继承此合同。
6. Manual V1 选该连接，显式短 Raw JSON 检查原始响应、精确返回 Model 和 Usage；该项本轮未完成真实复查。
7. Manual V2 实验、独立 Key、Save / Send / Stop 正常，不进入正式连接列表。
8. 开发者将 default_preset_id 设为 null 时，重新启动后要求显式选模型；恢复 ID 后默认组合正确。

## 10. 修改范围与 Git

本轮修改：presets.py、model_gateway.py、openai_compatible_adapter.py、resources/profiles/presets.json、web.py、Web app.js / index.html、test_clean_room_reset.py、test_browser_streaming.cjs、BUILD_RUN / deep-dive 导航。

新增：test_preset_publication.py、本文。保留进入本轮前已有的 Manual V2 未提交修改，未覆盖、回滚或提交。没有修改 production Fishery_Project、R3 / R4 / R5 实现、RAG / Grounding、CredentialStore 或 Cancellation。

Git：13 个已修改、5 个未跟踪文件（包含进入本轮前的 Manual V2 修改）。新增报告和测试均保留在工作树；未 commit / push，不移动 tag。`git ls-files -- .env outputs` 为空，没有将源码旧 .env 或 outputs 加入跟踪。源码搜索只发现私有 Store / Writer 的 StringIO 解析和 Flask `load_dotenv=False`，没有新增旧源码 .env fallback。

## 11. 多模型资格验证（2026-10-03 后续轮次）

第 1–10 节保留首轮发布历史；本节记录用户反馈及本轮真实结果。用户已明确人工验证 Qwen OFF Normal、ON Normal、ON Streaming 均正常，OFF Streaming 仍按合同禁用。此反馈已加入维护 metadata，不扩大成未测试组合已通过。

### 11.1 本轮资格与发布结论

| 模型 | 本轮真实结果 | 发布结果 | 合同版本 |
| --- | --- | --- | --- |
| Qwen qwen3.8-flash | 正式私有凭据解析 CREDENTIAL_FILE_ERROR，尚未进入 SDK | 保留三种已发布组合；OFF Streaming 未发布 | 保持 1.0.0 |
| DeepSeek deepseek-v4-pro | 正式私有凭据解析 CREDENTIAL_FILE_ERROR，尚未进入 SDK | 保留 Managed 候选，不发布 Preset | 候选计划 1.0.0，未形成有效发布合同 |
| Ollama qwen3.5:4b | 模型列表可访问；一次 OFF Normal 生成 READ_TIMEOUT | 保留 Managed 候选，不发布 Preset | 候选计划 1.0.0，未形成有效发布合同 |

默认仍是 `dashscope-qwen38-flash-r1` / OFF Normal。没有恢复旧 Preset 或归档 Evidence，没有为了三个模型界面对称而建立未验证合同。

### 11.2 Qwen OFF + Streaming

- 目标 Identity 保持 dashscope / openai_chat / 官方 compatible-mode/v1 / qwen3.8-flash。
- 当前 R3 映射明确 OFF → enable_thinking=false，Streaming → stream=true；计划要求有效正文 delta、正常 finish、无意外暴露的 reasoning，以及可用 Usage。
- DASHSCOPE_API_KEY 的值从未打印或检查；当前执行环境未能确认 PRESENT，返回 CREDENTIAL_FILE_ERROR。用户正常 Web 进程中可用与 Codex 执行环境中的解析失败是不同事实。
- 本轮没有发送 Qwen 请求、没有新 OFF Streaming 证据，合同不变，不升级版本。
- 后续取得 OFF Streaming 的直接成功记录后，维护者才能把该组合加入合同并升级到 **1.0.1**；不能静默修改 1.0.0。AUTO 未测试、未发布。

### 11.3 DeepSeek 候选审计

精确 Identity：**deepseek_api / openai_chat / https://api.deepseek.com / deepseek-v4-pro**。复用当前用户保存的 DS_1，credential_ref=DEEPSEEK_API_KEY，Auth REQUIRED_BEARER。

当前 ProviderRegistry 指向 deepseek_chat / version 1；R3 Thinking ON/OFF 使用 thinking.type=enabled/disabled，AUTO 不发送开关。该模型 ID 来自当前保存配置，不使用旧 deepseek-flash Preset，也不通过模型名猜能力。

当前精确 R4 结果已有 ON、OFF、Streaming、ON Streaming 组合的 USER_VERIFIED / SUPPORTED；这些仅是既有用户证据，不是本轮新验证，更不是自动发布许可。本轮凭据解析失败，尚未完成所要求的基础 AUTO Normal、正式 Fishery Analysis 或 Manual V1 Raw 检查，因此不发布任何 DeepSeek Variant。

Manual V1：未执行，content、reasoning_content、finish_reason、返回 Model 和 Usage 均没有本轮观察结果。凭据阻塞解除后先做基础请求 / 正式分析 / 同一连接 Raw 检查；如果仅默认 Normal 可靠，就仅发布 AUTO Normal，不强行制造 ON/OFF。

### 11.4 Ollama 本地资格验证

精确 Identity：**ollama / generic_openai_chat / http://127.0.0.1:11434/v1 / qwen3.5:4b**。`/v1/models` 在约 **15ms** 内成功返回并列出该精确模型。Auth NONE，无 Cloud Credential，没有设置 Key。

在 Git ignored 的 outputs/custom_profiles 中新建正式 Managed 候选“**Ollama Qwen3.5 4B 资格验证**”；没有套用旧 Metadata 或旧 Evidence。R3 为 ollama_openai_chat / version 1，精确模型 Thinking OFF → reasoning_effort=none，ON → high。协议编码知识本身不证明真实服务接受、执行或关闭 Thinking。

实际只执行 **OFF + Normal** 一次，覆盖基础 Normal 路径与可编码的 OFF：

- Prompt 极短；max_tokens=64；SDK / Gateway retry=0；read 30s、total 60s。
- 通过 ModelRequest → 正式 Gateway / Adapter → OpenAI SDK 执行；诊断副本仅绕过本次指定能力的 UNKNOWN，并设置请求预算，不改变正常业务门禁。
- 结果 **READ_TIMEOUT**，耗时 **30485ms**，SDK attempts=1。
- 没有正文、完成原因或 Usage；Token 数是 **unavailable**，不能写成 0，也不能保证远端没计算。
- 不能确认 Thinking 真正关闭，不能确定是模型加载、推理、传输或其他原因。本轮不调整代理、ACL、timeout 策略或 R3 协议来掩盖超时。

按预算遇到 timeout 后停止后续生成：ON、Streaming、组合、Manual V1 都未执行，没有循环重试。Ollama 的四项高级 Capability 经 R4 仍为 UNKNOWN；没有把网络失败记录成 UNSUPPORTED。它保留为 Managed 候选，普通 Preset 列表不出现。

### 11.5 单次验证工具与安全边界

新增 `scripts/qualify_local_preset_request.py`：每次必须指定一个现有 Saved Connection、ON 或 OFF、可选 Streaming / Manual V1，并传 --confirm-network。只允许上述精确 Ollama Identity / Auth NONE；错误身份在解析 Credential 前拒绝。没有批量模式、AUTO 扫描、Publisher、自动创建连接或自动写 Capability Evidence。

其请求复用现有 Gateway / Adapter、R3 参数映射与 R4 已有解析；Manual V1 使用同一个 Saved Connection 和现有 manual_complete。单次输出只存日期、Identity、完成状态、finish_reason、计数、Latency、Usage 等安全摘要，存入 Git ignored 的 outputs/preset-qualification。原始 Prompt / Output / Secret 不持久化。

资格通过标准比 HTTP 200 严格：有效正文、finish_reason=stop、精确返回模型；OFF 不得暴露 reasoning 或返回正 reasoning token 数。耗尽 token 上限不算本次完整资格通过。工具只产生统计，发布和成功 Evidence 写入必须由维护者审查后另行决定。

初版自动多模式脚本被自动审批以超出最小验证范围为由拒绝，未写入或执行。当前采用上述单次工具，实际只运行一次 OFF Normal。

### 11.6 请求预算汇总

| 类型 | 请求数 | Retry | 大致耗时 | Usage |
| --- | --- | --- | --- | --- |
| Qwen 生成 | 0 | 未进入 SDK | 凭据阶段阻塞 | 无新消耗 |
| DeepSeek 生成 / Analysis / Manual | 0 | 未进入 SDK | 凭据阶段阻塞 | 无新消耗 |
| Ollama 模型列表 | 1（非生成） | 0 | 15ms | 不适用 |
| Ollama OFF Normal | 1 | 0 | 30.485s | unavailable |
| 本地 Web 可用性检查 | 1（非生成） | 0 | 约 2.094s，未建立连接 | 不适用 |

两个 Cloud 凭据各进行一次正式解析，没有修改文件、复制 Key、读取旧 root .env、绕过 ACL 或改环境变量。正式 project credential 与 Manual V2 manual.env 的隔离不变。

### 11.7 本轮测试与工作树

- Preset targeted Python：13 项通过。
- Provider / Protocol targeted：3 项通过，含现有 DashScope、DeepSeek、Ollama、Generic 编码与 legacy 兼容。
- 单请求资格安全 targeted：11 项通过，含精确 Identity、Auth NONE、显式确认、OFF / ON 映射、64-token预算、零重试、delta / finish、timeout 与原始响应不持久化。
- full Python：360 项通过；full Browser：100 项通过；JS syntax / diff check 通过。
- 敏感扫描：131 个 Git 可提交文本，0 风险，排除 2 个明确虚构 fixture；不扫描真实凭据与 outputs。

本轮只更新 Qwen 维护 metadata、本文和运行说明，补充当前 DeepSeek 精确模型的 Protocol parity 测试，新增单次本地资格工具及离线测试；生成的 Managed 候选和资格统计位于 ignored outputs。固定 Variant / 默认合同未扩展，R3 / R4 / R5、CredentialStore、Orchestrator、Manual V2、RAG / Grounding 均未改动。工作树保留前轮修改；不 commit / push。

该历史轮次的最终工作树：14 个修改文件、7 个未跟踪文件，另出现 `.env.example` 删除状态。用户已在后续轮次明确确认是本人主动删除；当前保留删除、不恢复文件，当前结构说明已移除该条目。旧根 `.env` 未读未改。候选连接及资格统计通过 git check-ignore，git ls-files 的 .env / outputs 结果为空。

### 11.8 用户后续人工项目

1. 使用正常用户 Web 进程及正式 Saved Connection 验证 Qwen OFF Streaming，提供安全统计：正文 delta、finish、是否暴露 reasoning、Usage、Latency；不要提供 Key 或完整响应。
2. DeepSeek 复用 DS_1，先验证基础 AUTO Normal，再一次正式分析和同一连接 Manual V1 Raw 检查；仅补缺少直接依据的模式，不批量重跑已有 Probe。
3. Ollama 在本机确认生成服务状态后，先排查本次 OFF Normal 超时，再授权单次重新验证；未通过前不要发布稳定 Preset。CLI 示例（仅在用户明确准备测试时执行）：

   ```powershell
   python scripts/qualify_local_preset_request.py --confirm-network --profile-id <已保存的精确本地连接ID> --thinking off
   ```

4. 提供充分成功记录后，维护者再决定 Qwen 1.0.1、DeepSeek / Ollama 1.0.0 的精确已发布组合。不会通过 SUPPORTED 自动生成合同。

## 12. 用户人工验收后的精确多模型登记（当前状态）

### 12.1 审计范围和依据

本轮只读取当前 `outputs/custom_profiles/` 的连接元数据及 `outputs/capability-evidence/` 的非敏感活动记录，再用当前 R4 解析器核对精确身份的结果。未读取归档恢复旧资产，未解析任何真实 Credential，未发 Cloud / Ollama / Web 请求。模型、连接和 Probe 数字来自既有记录，人工可运行结论来自用户本轮明确反馈。

四元 Identity 为 service + adapter + normalized base_url + exact model。Template 将维护者审查后的证据摘要固化，运行时仍不读取 CapabilityStore / Evidence Resolver / Probe；本地 USER_VERIFIED 不能修改发布合同。

| 模型 | 当前 Saved Connection | 精确 Identity | 凭据 / 协议 |
| --- | --- | --- | --- |
| Qwen 3.8 Flash | QW_1 / QW_2 | dashscope / openai_chat / https://dashscope.aliyuncs.com/compatible-mode/v1 / qwen3.8-flash | DASHSCOPE_API_KEY；dashscope_chat v1 |
| DeepSeek Flash | DS_2（custom-a7109e8c55e24900a47890a825b84343） | deepseek_api / openai_chat / https://api.deepseek.com / deepseek-flash | DEEPSEEK_API_KEY；deepseek_chat v1 |
| Ollama Qwen3.5 4B | Ollama Qwen3.5 4B 资格验证（custom-b291d8a7148342ebb462f8a19f398cee） | ollama / generic_openai_chat / http://127.0.0.1:11434/v1 / qwen3.5:4b | Auth NONE，无凭据；ollama_openai_chat v1 |

**DeepSeek 本轮发布的是 deepseek-flash，不是 DS_1 的 deepseek-v4-pro。** DS_1 的四项 Probe 与任何 Clean-room 前合同均未用于本次发布。三个精确身份的 R4 当前结果分别为 ON、OFF、Streaming、ON + Streaming 四项 SUPPORTED · USER_VERIFIED；仍不把它们扩展成未验证的所有排列组合。

### 12.2 各模型实际发布合同

| 模型 / Preset ID | 合同 | OFF + Normal | ON + Normal | ON + Streaming | OFF + Streaming | AUTO |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen 3.8 Flash / dashscope-qwen38-flash-r1 | 1.0.0（不升级） | 发布，默认 | 发布 | 发布 | 不发布 | 不发布 |
| DeepSeek Flash / deepseek-flash-r1 | 1.0.0（新登记） | 发布，默认 | 发布 | 发布 | 不发布 | 不发布 |
| Ollama Qwen3.5 4B / ollama-qwen35-4b-r1 | 1.0.0（新登记） | 发布，默认 | 发布 | 发布 | 不发布 | 不发布 |

Qwen 没有当前活动 OFF + Streaming 的直接成功组合记录，本轮用户反馈亦没有明确报告该组合已通过，因此保持 1.0.0。后续维护者确认该组合成功才能加入合同并升为 1.0.1。DeepSeek / Ollama 同样没有 OFF Streaming 直接记录，不能从独立 OFF 与 Streaming 成功推导该组合。AUTO 仍表示默认行为，不伪装为 OFF，不补齐 UI 对称组合。

`default_preset_id` 仍为 dashscope-qwen38-flash-r1。三个 Template 各使用一个连接 + OFF / ON 两个 Variant，ON 单独允许 Normal / Streaming；Response Mode 与 Thinking 分离。Effort、Tool Calling、Structured Output、模型默认 Thinking 等未发布功能保持 UNKNOWN，不增加新能力或自动 Publisher。

### 12.3 DeepSeek / Ollama 的直接验证摘要

以下时间均为活动 Evidence 的 UTC 时间，统计不是本轮新增消耗；原始 Record ID 和指标已保存在 Template 的开发维护 metadata 中。

| 精确模型 | 独立能力 / 对应模式 | 验证时间 | 关键统计 |
| --- | --- | --- | --- |
| deepseek-flash | ON Normal | 2026-10-02 18:16:13 | 735ms；33/32/65 tokens；返回 deepseek-flash |
| deepseek-flash | OFF Normal | 2026-10-02 18:16:15 | 360ms；7/1/8 tokens；返回 deepseek-flash |
| deepseek-flash | Streaming | 2026-10-02 18:16:17 | 正文 delta 1；reasoning delta 23；provider Usage |
| deepseek-flash | ON Streaming 组合 | 2026-10-02 18:16:20 | 正文 delta 1；reasoning delta 23；首个模型 delta 766ms、首个正文 891ms、总 891ms；33/25/58 tokens |
| qwen3.5:4b | ON Normal | 2026-10-03 14:45:18 | 9531ms；13/243/256 tokens；返回 qwen3.5:4b |
| qwen3.5:4b | OFF Normal | 2026-10-03 14:45:24 | 328ms；15/2/17 tokens；返回 qwen3.5:4b |
| qwen3.5:4b | Streaming | 2026-10-03 14:45:29 | 正文 delta 1；TTFT 2375ms；总 2390ms；Usage unavailable |
| qwen3.5:4b | ON Streaming 组合 | 2026-10-03 14:45:33 | 正文 delta 1；reasoning delta 0；TTFT / 总 2297ms；Usage unavailable |

用户已在**正常用户 Web 进程**人工验证 Ollama 可运行。ON 较慢是性能现象，不能把 Thinking 记成不支持。组合 Probe 中没有 reasoning delta 也不等于 Thinking 不支持；这里只记录当前协议请求被接受及有效正文，不证明模型内部完整推理行为。历史 agent 环境一次 READ_TIMEOUT 保留作为排查历史，不覆盖新的成功证据。

DeepSeek Streaming 已返回 provider Usage，固定合同据此与现有 Qwen 一样允许 stream_options.include_usage；这是维护者的发布判断，未修改 R4 对 streaming_usage 的 UNKNOWN 解析。Ollama 没有 Usage 支持的直接依据，该项保持 UNKNOWN，不注入 include_usage，页面缺失项继续显示 unavailable 而非 0。

Cloud 保留 connect/read/total 5/30/120 秒；Ollama 复用现有 Local 默认 5/120/180 秒，不加无限超时。所有 Preset max_retries=0。Qwen OFF → enable_thinking=false，DeepSeek OFF → thinking.type=disabled，Ollama OFF → reasoning_effort=none；ON 使用原有相应编码，不改 R3 / Adapter。

Manual V1 原始响应没有持久化记录，本轮没有重新调用，不能伪造 finish_reason 或 Raw 观察。用户可运行反馈与活动 Probe 是这次维护者登记依据；Manual V1 / V2 保持原隔离，不从 Raw 实验自动制作 Preset。

### 12.4 页面与凭据边界

- Model 下拉显示 Qwen 3.8 Flash、DeepSeek Flash、Ollama Qwen3.5 4B，Qwen 默认。
- 仍只有 Model / Thinking / Response Mode；未发布组合禁用，提示“此 Preset 未提供该模式”。不暴露 Capability、Evidence、Probe、URL 或 Credential Ref。
- 不需要新增 UI 实现：沿用已有固定合同目录加载与组合门禁，只增加离线浏览器测试。
- Cloud 只保存正式 credential_ref，Ollama Auth NONE。没有读取、复制或修改真实 Key、CredentialStore、正式 .env、manual.env。
- 用户确认删除 `.env.example`，保持删除；历史初版目录树明确标注已删除，当前 STRUCTURE 不再列出它。用户私有 Credential Manager 仍是当前正式录入路径。

### 12.5 本轮验证结果与改动范围

| 检查 | 命令 / 范围 | 结果 |
| --- | --- | --- |
| Preset targeted Python | .venv/Scripts/python.exe -m unittest discover -s tests -p 'test_preset*.py' -v | 18 项通过 |
| Preset targeted Browser | node --test --test-name-pattern 'published\|Preset' tests/test_browser_streaming.cjs | 14 项通过 |
| full Python | .venv/Scripts/python.exe -m unittest discover -s tests | 365 项通过，12.779 秒 |
| full Browser | node --test tests/test_browser_streaming.cjs | 102 项通过 |
| JS syntax | node --check src/fishery_ai/resources/web/app.js | 通过 |
| 格式检查 | git diff --check | 通过 |
| Secret / 敏感路径 | 仅扫描 Git 可提交公共文本；禁止扫描真实 .env、私有文件与 outputs | 131 文件，0 风险；4 个已核实虚构测试命中排除 |

定向 Browser 初次测试遗漏现有“请选择模型”占位项，修正断言后全部通过，没有因此改动页面行为。扫描命中既有非法 Key 输入拒绝夹具，核实为虚构测试并按精确函数和值排除，未关闭整个测试目录的检查。

本轮修改：固定 presets.json、test_preset_publication.py、test_clean_room_reset.py、test_browser_streaming.cjs、BUILD_RUN、STRUCTURE、deep-dive README、V0.1 初始报告的历史条目标注、本文。没有修改 R3/R4/R5、CredentialStore、Adapter、Orchestrator、Manual、RAG / Grounding、Cancellation 或 production Fishery_Project。

最终工作树保留前轮未提交改动：16 个修改、1 个用户确认删除、7 个未跟踪文件。真实 .env / outputs 均未被 Git 跟踪；用户私有凭据、lock / stage / recovery 未出现在可提交路径中。未 commit / push，未移动 tag。

### 12.6 最终人工验收清单

1. 重启正常用户 Web 进程加载包内新合同，确认三个模型且默认 Qwen OFF + Normal。
2. 每个模型只显示 OFF Normal、ON Normal、ON Streaming 三种组合；OFF Streaming / AUTO 不可发送，普通 Preset 不显示研发能力面板。
3. 使用现有 Cloud 私有凭据 / Ollama Auth NONE 验收新增 Preset 的正式分析与 Stop；无需再批量 Probe，也不更改 Managed Evidence。
4. 按需检查同一精确连接的 Manual V1 Raw 展示；当前报告没有伪称事后复原 Raw。
5. 若需发布 Qwen OFF Streaming，请另行提供该组合的直接成功记录，再明确维护 1.0.1。

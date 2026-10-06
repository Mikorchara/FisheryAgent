# Preset 发布合同

Preset 是维护者发布的固定方案。普通用户只选择 Model、Thinking 和 Response Mode；不显示 Base URL、凭据引用、ProtocolSpec、Evidence 或 Probe。运行时 Managed Evidence 不改变 Preset 合同。

## 当前发布

| Preset | exact model | 合同 | Thinking × Response Mode | 默认 |
| --- | --- | --- | --- | --- |
| Qwen 3.8 Flash | qwen3.8-flash | 1.0.2 | OFF/ON × Normal/Streaming | Qwen，OFF + Normal |
| DeepSeek Flash | deepseek-flash | 1.0.2 | OFF/ON × Normal/Streaming | 否 |
| Ollama Qwen3.5 4B | qwen3.5:4b | 1.0.2 | OFF/ON × Normal/Streaming | 否 |

AUTO、Reasoning Effort 与其他未发布组合不在用户选项内。各 Preset 使用自己的固定服务身份、适配器、URL、精确模型、凭据引用、超时与协议编码；Ollama 使用 Auth NONE。定义位于 src/fishery_ai/resources/profiles/presets.json。

## OFF + Streaming 的发布依据

2026-10-04，用户确认 Qwen 3.8 Flash 与 DeepSeek Flash 在正常 Web 进程中 OFF + Streaming 均可工作。维护 metadata 将其标为用户人工验收来源；Codex 本轮没有重发 Cloud 请求。两者从合同 1.0.0 升至 1.0.1，只添加 thinking_off_streaming_combination 固定支持状态及 OFF Variant 的 Streaming 选项。

Ollama Qwen3.5 4B 的 OFF + Streaming 在此前单次 R5 Probe 成功后已发布于 1.0.1。本轮未重测。其他已发布模式和默认 Qwen 选择保持不变。

这些维护记录不等同于本机 R4 Evidence 文件；Preset 使用静态发布合同。新增能力若无精确证据，不得以同 Provider、相似型号或单项能力推导。

## 验收

- 普通界面三个模型均可选择 OFF/ON 与 Normal/Streaming。
- 选择 Qwen 后仍默认 OFF + Normal。
- Preset 页面不出现 Probe、Evidence、连接编辑和 Secret 控件。
- Managed Custom 能力状态不能改写这些静态合同。

## 最新资格与 Analysis 接入（2026-10-06）

用户已在正常凭据进程产生新的独立维护者资格记录。本轮核对 exact Identity、固定 ProtocolSpec、对应 Tool Trace 及所有成功条件；Codex 不再联网。

| Preset | 最新结果 | 固定 Tool 能力 / 合同 |
| --- | --- | --- |
| Qwen 3.8 Flash | 合法唯一 Tool Call、空参数、有效 call id、NO_DATA、第二轮非空 stop、概念题直接回答 stop；三个返回模型均为 qwen3.8-flash | SUPPORTED，1.0.1 → 1.0.2 |
| DeepSeek Flash | 最新独立资格记录完整通过：唯一 get_current_water_quality({})、有效 call id、NO_DATA、第二轮非空 stop、概念题直接回答 stop，三个返回模型均为 deepseek-flash | SUPPORTED，1.0.1 → 1.0.2 |
| Ollama Qwen3.5 4B | 上轮资格已完整通过 | SUPPORTED / 1.0.2 完全不变 |

Qwen 用户验证时间 2026-10-06T04:53:25.594374+00:00，3 次请求，总耗时 7.172 秒；Usage 881 input / 78 output / 959 total。安全维护记录保存于 Qwen Template 的 maintenance.tool_calling_qualification，不复制 Managed Evidence。其他能力及四种 Thinking / Response 组合不变。

DeepSeek 新资格记录为 outputs/preset-qualification/deepseek-flash-r1-tools-20261006T061029872004.json；validated_at=2026-10-06T06:10:26.722638+00:00。exact Identity 为 deepseek_api / openai_chat / https://api.deepseek.com / deepseek-flash，固定 ProtocolSpec=deepseek_chat v1。对应安全 Trace 确认唯一合法调用、NO_DATA 与正常 stop；概念题 32 output tokens、无 Tool、正常 stop。用户共发送 3 次请求，耗时 3156 ms，Usage input 871 / output 69 / total 940。maintenance.tool_calling_qualification 保留这份独立资格依据，未复制 Managed Evidence。

此前 192-token 概念题截断属于历史失败记录；简短提示及独立 384 上限后，本次用户资格成功。只增加 DeepSeek tool_calling 固定能力、1.0.2 与维护记录，其他能力、Thinking / Streaming 组合和 Qwen 默认不变；Codex 本轮没有真实模型请求。

Analysis v1 默认工具关闭，用户授权且 Runtime 支持后 Normal 执行单轮；Tool 协议资格在 OFF + Normal 验证，不代表 Streaming Tool Calling 已实现。新实验评分是程序 Tool，不是新模型 Capability，也不会改写合同。当前自动结果见[Analysis v1](ANALYSIS_MODEL_TOOL_CALLING_V1.md)。

## 首次独立资格验证（历史记录）

以下为用户新增记录之前的首次执行过程及当时的合同、测试和工作树状态；当前结论以上节为准，历史“Analysis 尚未接入”已经由 v1 替代。

资格验证直接读取当前发布 Template、固定 ProtocolSpec 和 Provider 配置；不复制 Managed Custom Evidence。维护者入口为 [qualify_preset_tools.py](../../scripts/qualify_preset_tools.py)，执行组件为 [preset_tool_qualification.py](../../src/fishery_ai/preset_tool_qualification.py)。一次显式确认只验证一个 Preset：Tool 闭环最多两次请求，随后概念问题最多一次请求。SDK / Gateway retry=0，每次最多 192 输出 token。运行脚本不会自动发布合同或写 Capability Evidence。

| Preset | exact Identity：service / adapter / normalized base_url / model | 固定 ProtocolSpec | Auth / Credential Ref |
| --- | --- | --- | --- |
| Qwen 3.8 Flash | dashscope / openai_chat / https://dashscope.aliyuncs.com/compatible-mode/v1 / qwen3.8-flash | dashscope_chat v1 | REQUIRED_BEARER / DASHSCOPE_API_KEY |
| DeepSeek Flash | deepseek_api / openai_chat / https://api.deepseek.com / deepseek-flash | deepseek_chat v1 | REQUIRED_BEARER / DEEPSEEK_API_KEY |
| Ollama Qwen3.5 4B | ollama / generic_openai_chat / http://127.0.0.1:11434/v1 / qwen3.5:4b | ollama_openai_chat v1 | NONE；不需要凭据 |

| Preset | Request #1 / Tool | Tool Result | Request #2 | 概念问题「什么是溶氧？」 | 实际模型请求 | verdict / 固定合同 |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen 3.8 Flash | 未开始；CREDENTIAL_FILE_ERROR | 未执行 | 未开始 | 未开始 | 0 | UNKNOWN；保留 1.0.1，不发布 Tool Calling |
| DeepSeek Flash | 未开始；CREDENTIAL_FILE_ERROR | 未执行 | 未开始 | 未开始 | 0 | UNKNOWN；保留 1.0.1，不发布 Tool Calling |
| Ollama Qwen3.5 4B | 合法唯一 get_current_water_quality({})，合法 call id | NO_DATA | role=tool 被接受；非空最终正文，finish_reason=stop，无后续 Tool | 首轮直接回答，finish_reason=stop；不执行 Tool | 3；其中闭环 2 次，概念 1 次 | SUPPORTED；1.0.1 → 1.0.2 |

两项 Cloud 在现有私有 CredentialStore 安全检查处被阻止，没有发出任何模型请求；未更改 ACL、复制 Secret、创建源码根 .env 或重复测试。需要用户正常 Web 进程的独立维护者资格验收；已有 Managed SUPPORTED 不能代替本表空缺。

Ollama 验证时间为 2026-10-05T17:32:58.687693+00:00（北京时间 2026-10-06）。三次返回模型均为 qwen3.5:4b，总耗时 9.109 秒。资格进程使用独立空 CurrentSnapshotStore，并经正式 CurrentWaterQualityReader / Registry / Executor 得到 NO_DATA；未 Apply 情景，也未提前把水质值注入首轮请求。NO_DATA 是有效 Tool Result，不是现场正常水质证明。

| Ollama 请求 | Input Tokens | Output Tokens | Total Tokens |
| --- | --- | --- | --- |
| Request #1 | 362 | 16 | 378 |
| Request #2 | 406 | 12 | 418 |
| 概念问题 | 358 | 158 | 516 |
| 合计 | 1126 | 186 | 1312 |

Usage 来源为 Provider；cached input 合计 358，reasoning tokens 未返回。逐次 Usage、安全结果摘要和维护者决定保存在 Template 的 maintenance.tool_calling_qualification；本机资格记录与 Tool Trace 在 Git ignored 的 outputs/preset-qualification/。不保存完整 Prompt、模型正文、Secret 或私有凭据路径。

Ollama 固定 capabilities 增加 tool_calling=supported，其他能力、连接配置、默认 Qwen 和已有四种组合未改。Tool 协议支持在 OFF + Normal 条件下得到独立确认；不据此发布 Thinking ON + Tool 或 Streaming Tool Calling 组合。普通 Preset 界面仍不展示 Evidence / Probe；当前 Analysis ModelRequest.tools 仍为空，**本轮没有接入 Analysis Tool Calling**。

### 首次资格阶段验收与下一步（历史）

- 确认 Ollama 固定合同加载 SUPPORTED，Cloud 两项仍 UNKNOWN；相似模型和其他 Base URL 不继承结果。
- 确认 Managed Evidence 不修改固定合同；正常 Normal / Streaming Analysis 与 Manual 保持原路径。
- Cloud 先在可访问私有凭据的正常用户进程完成同样闭环及概念问题，再单独审查发布合同。
- Analysis Model Tool Calling v1 尚未实现；本轮仅 Ollama 具备已发布协议资格，不能宣称三个 Preset 均已准备完成。

### 自动回归与工作树

自动测试全部离线，只用临时存储、虚构凭据和 Mock；真实资格请求不进入测试。

| 检查 | 命令 / 范围 | 结果 |
| --- | --- | --- |
| Preset targeted | `python -m unittest discover -s tests -p "test_preset*.py"` | 40 项通过；其中新增资格测试 21 项 |
| T1–T5 targeted | test_gateway_tool_contract / test_read_only_tools / test_tool_conversation / test_web_tool_conversation / test_tool_capability_probe | 29 / 35 / 36 / 23 / 17 项通过 |
| Tool Policy targeted | `python -m unittest discover -s tests -p "test_tool_policy*.py"` | 34 项通过 |
| Full Python | `python -m unittest discover -s tests` | 625 项通过，27.478 秒 |
| Full Browser | `node --test tests/test_browser_streaming.cjs` | 156 项通过；Node DOM / fetch fixtures，无真实浏览器联网 |
| JS syntax | `node --check` 检查 app.js 与 Browser 测试文件 | 通过 |
| Markdown links | Git 可见 Markdown 本地文件链接 | 41 项有效，无失效链接 |
| Diff | `git diff --check` | 通过 |
| Sensitive scan | 136 个 Git 可见源码 / 文档；不读取真实 .env、私有凭据或 outputs | 无未解决风险；1 个既有虚构 URL 凭据拒绝 fixture 已核对；受保护凭据 / outputs 被跟踪数为 0 |

旧 T4 测试曾假设所有真实 Preset 都没有 Tool 能力；按当前合同调整为未发布模型继续被阻止，并新增已发布 Ollama 经现有路径完成离线 NO_DATA 闭环的测试。没有为了通过测试而修改 Web / Gateway / Analysis 的行为。

本轮工作树：10 个已跟踪文件修改、3 个新文件。新增维护者组件、单个 Preset 显式资格脚本、离线资格测试；修改固定合同、既有测试与中文文档。没有修改正式 Fishery_Project、CredentialStore、Managed Evidence、Analysis ModelRequest.tools、Thinking / Streaming 合同组合或 Manual；不 commit / push。

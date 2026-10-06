# 构建与运行

## 环境

Python 3.11+。运行和安装依赖由 pyproject.toml 声明。

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e .

## 离线演示与测试

    .\.venv\Scripts\python.exe -m fishery_ai demo --scenario normal
    .\.venv\Scripts\python.exe -m fishery_ai demo --scenario low_oxygen
    .\.venv\Scripts\python.exe -m unittest discover -s tests
    node --test tests/test_browser_streaming.cjs
    node --check src/fishery_ai/resources/web/app.js

Demo 使用 MockGateway，不访问模型。tests/ 是自动化回归，不参与普通运行。

## Web

    .\.venv\Scripts\python.exe -m fishery_ai web

访问 http://127.0.0.1:8765。服务只监听本机。Mock 分析离线；Cloud / Local 真实请求、连接测试和 Capability Probe 必须由用户显式确认，Cloud 请求可能收费。

普通 Preset / Managed / Manual 模式的 Development / Test 只显示说明与“进入开发验证”。点击进入后显示完整实验区域，默认使用 Mock；“返回正常模式”恢复原模式、模型和运行选择。Read-only Tool Calling 的真实目标明确显示进入前的连接名，不使用顶部开发 Mock 冒充真实目标。先不 Apply 可验证 NO_DATA；随后显式 Apply 情景并问“现在水质怎么样？”，查看 Tool Result 与最终回答。“什么是溶氧？”直接回答。该入口仅支持 Normal；“更新快照状态显示”只读、不采样、不 Apply。真实 Tool 能力未验证时仍阻止发送。验收清单见[只读工具说明](deep-dive/READ_ONLY_TOOL_CALLING.md)。

## Tool 管理

左侧 **01 · Analysis Model → Tool** 打开应用级 Tool 管理：可查看两份 Policy，勾选真实 Tool 并保存、恢复默认；详情默认折叠。Analysis 设置影响新的 Normal 分析请求，仍要求精确 Runtime 的 Tool capability=SUPPORTED；启用后选择 Streaming 会明确拒绝，不自动降级。Assistant 设置影响新的开发 Tool Conversation 和正式 Assistant 请求。正式列表只含水质查询、实验评分两个真实 Tool。右上固定按钮可切换至 Assistant 工作区。

Apply 水质情景 → 选择已发布 Qwen / Ollama Preset（建议 OFF + Normal）→ 在 Analysis 标签勾选并保存水质 Tool → 开始分析。右侧结果区的 **Tool Activity · 工具调用记录** 默认折叠：显示允许列表、是否实际调用、Tool Result、耗时、两次请求状态及 Usage。不保证模型一定调用；未调用时会明确说明。详情及离线 / 人工验收见[Analysis v1](deep-dive/ANALYSIS_MODEL_TOOL_CALLING_V1.md)。

## Preset

用户可选模型、Thinking 和 Response Mode。Qwen 3.8 Flash、DeepSeek Flash、Ollama Qwen3.5 4B 当前各发布 OFF/ON 与 Normal/Streaming 四种组合；默认 Qwen OFF + Normal。Preset 不显示 URL、凭据引用、Capability Evidence 或 Probe。合同依据见[Preset 发布说明](deep-dive/PRESET_PUBLICATION.md)。

维护者独立 Tool 资格验证入口（真实联网，最多两次闭环请求加一次概念请求；不是普通启动或自动测试）：

    .\.venv\Scripts\python.exe scripts/qualify_preset_tools.py --preset-id ollama-qwen35-4b-r1 --confirm-network

一次只指定一个发布 Preset，固定使用 OFF + Normal、retry=0；无确认不读取凭据、不联网。复用正式私有 CredentialStore，无源码 .env 回退。脚本只输出安全摘要并保存到 outputs/preset-qualification/，不会自动修改发布合同；不要把重复运行当作无需授权的日常测试。

DeepSeek 的 Tool 闭环已通过，但概念题在 192 输出 tokens 时被截断，尚未发布 Tool 支持。当前概念题要求一两句话，并独立使用 384 输出 token 上限；闭环两次请求仍各为 192。用户需要在正常凭据进程显式重测 `--preset-id deepseek-flash-r1`；本轮 Codex 不重新联网。

## Managed Custom

在模型配置中创建连接并填写 Base URL、精确 Model、凭据引用。真实 Key 只在本机凭据管理入口设置；不填入 Profile。Normal + AUTO 可在高级能力未验证时使用。Thinking / Streaming 等选项只有精确身份证据支持时才可运行；Probe 由用户逐项触发。

Tool Calling 在 **02 · 模型能力 → 高级验证操作** 中显式验证或重新验证；每次确认 REAL NETWORK REQUEST，最多两次模型请求、retry=0。成功后精确 Profile 能力即时刷新。Development / Test 不管理能力；UNKNOWN 真实目标会提示先回到 Managed Custom 验证，不自动 Probe。详情见[Analysis / Assistant 架构](deep-dive/ASSISTANT_MODEL_ARCHITECTURE.md)。

配置保存在被 Git 忽略的 outputs/custom_profiles/；能力 Evidence 保存在 outputs/capability-evidence/。它们不是密钥仓库，也不是 Preset 合同。

## Manual Expert V1 / V2

V1 对已保存连接发送 Raw Request。V2 使用独立 Experiment、目标和请求 JSON。V2 Key 只存用户私有 manual.env；Experiment 只保存 credential_ref。两种模式都不进入 RAG、Diagnosis 或 AnalysisResult，不执行返回的 tool_calls。

## 凭据与取消

正式凭据优先级为 PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING。Windows 用户私有路径及 Manual V2 分离文件见[凭据存储说明](deep-dive/PRIVATE_CREDENTIAL_STORAGE.md)。旧源码根 .env 不参与运行。新请求可读取轮换后的凭据，在途请求持有开始时的快照。

Stop 会关闭本地 SDK I/O；不能据此断言远端服务已停止推理或计费。没有 Usage 时显示 unavailable，不等于零。

## Assistant 聊天工作区（S2）

GET /api/assistant/bootstrap 返回三个 OFF/Normal Preset 和 epoch；POST /api/assistant/chat 接收 preset_id、question、完整文本对 history、epoch 和现有 confirm_network/request_id/control_token envelope。调用方先使用现有 /api/credential-session 和 /api/requests，遵守 Host/Origin/CSRF。点击顶部“切换到 Assistant Model”，选择 Preset，勾选本次网络确认，Send 或 Ctrl+Enter 发送。只允许三个发布 Preset，固定 Thinking OFF · Normal；Tool 按钮打开共享管理面板的 Assistant 标签。不要用 Development Mock 或 Managed Profile 冒充正式 Assistant 目标。

对话只存页面内存；切换回 Analysis 保留原页面，刷新页面清空。只有完整成功轮次进入后续历史，最多发送6轮/6 KiB；失败、取消或截断不入成功历史。模型切换/清空有确认，后端重启会提示重新发送，不自动重试。消息下只显示轻量 Tool Activity；输入区“本次运行”展开查看安全统计。Stop 使用原请求控制，不证明远端已停止计算或计费。Cloud 显示 REAL NETWORK REQUEST；Ollama 显示 LOCAL MODEL REQUEST。

历史/请求字段、预算和测试说明见[Assistant v1](deep-dive/ASSISTANT_MODEL_V1_DESIGN.md)。离线针对性测试：

    .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_assistant.py

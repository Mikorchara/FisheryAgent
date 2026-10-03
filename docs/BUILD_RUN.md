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

## Preset

用户可选模型、Thinking 和 Response Mode。Qwen 3.8 Flash、DeepSeek Flash、Ollama Qwen3.5 4B 当前各发布 OFF/ON 与 Normal/Streaming 四种组合；默认 Qwen OFF + Normal。Preset 不显示 URL、凭据引用、Capability Evidence 或 Probe。合同依据见[Preset 发布说明](deep-dive/PRESET_PUBLICATION.md)。

## Managed Custom

在模型配置中创建连接并填写 Base URL、精确 Model、凭据引用。真实 Key 只在本机凭据管理入口设置；不填入 Profile。Normal + AUTO 可在高级能力未验证时使用。Thinking / Streaming 等选项只有精确身份证据支持时才可运行；Probe 由用户逐项触发。

配置保存在被 Git 忽略的 outputs/custom_profiles/；能力 Evidence 保存在 outputs/capability-evidence/。它们不是密钥仓库，也不是 Preset 合同。

## Manual Expert V1 / V2

V1 对已保存连接发送 Raw Request。V2 使用独立 Experiment、目标和请求 JSON。V2 Key 只存用户私有 manual.env；Experiment 只保存 credential_ref。两种模式都不进入 RAG、Diagnosis 或 AnalysisResult，不执行返回的 tool_calls。

## 凭据与取消

正式凭据优先级为 PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING。Windows 用户私有路径及 Manual V2 分离文件见[凭据存储说明](deep-dive/PRIVATE_CREDENTIAL_STORAGE.md)。旧源码根 .env 不参与运行。新请求可读取轮换后的凭据，在途请求持有开始时的快照。

Stop 会关闭本地 SDK I/O；不能据此断言远端服务已停止推理或计费。没有 Usage 时显示 unavailable，不等于零。

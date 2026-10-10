# 构建与运行

## 环境与启动

Python 3.11+；依赖由 `pyproject.toml` 声明。PowerShell 在项目根目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m fishery_ai web
```

默认访问 `http://127.0.0.1:8765`。服务只监听本机。离线 Demo：

```powershell
.\.venv\Scripts\python.exe -m fishery_ai demo --scenario normal
.\.venv\Scripts\python.exe -m fishery_ai demo --scenario low_oxygen
```

Demo 使用 MockGateway。自动测试不发送真实网络请求；Cloud / Local 模型、连接测试和 Probe 由界面显式确认。

## 当前工作区

- **Analysis**：固定 Snapshot → Diagnosis → RAG → Model；Normal / Streaming 可用。用户可在 Tool Manager 明确授权只读 Tool；启用 Tool 时仅支持 Normal，且要求精确 Runtime Tool capability 为 SUPPORTED。
- **Assistant**：仅 Qwen 3.8 Flash、DeepSeek Flash、Ollama Qwen3.5 4B 三个发布 Preset；固定 Thinking OFF + Normal。页面历史不持久化。Cloud Send 显示 REAL NETWORK REQUEST；Ollama 显示 LOCAL MODEL REQUEST。
- **Development / Test**：支持离线 Mock 与能力门禁下的真实 Tool Conversation；完整安全 Trace 仅在开发区显示。
- **Managed Custom**：高级能力依赖精确 Identity 的 Evidence / Resolver；Probe 必须由用户逐项触发。
- **Manual V1/V2**：Raw 请求路径；不进入 Fishery Analysis，不自动执行返回的 Tool Calls。

只读 Tool 当前为 `get_current_water_quality`、Experimental `score_current_water_quality` 和默认关闭的 `search_fishery_knowledge`。最多一个 Tool call、一轮、两次模型请求；不是 Agent。当前设计与限制见[Analysis / Assistant 当前架构](deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md)和[只读 Tool 当前实现](deep-dive/tools/READ_ONLY_TOOL_CALLING.md)。

## Tool / Preset 维护

Tool 管理入口在左侧 **01 · Analysis Model → Tool**，分 Analysis / Assistant 两个授权视图。Catalog 展示不等于注册或授权；真实执行还受 Registry、Policy、Handler 与 Runtime capability 约束。

维护者资格脚本需单独确认网络并一次指定一个 Preset：

```powershell
.\.venv\Scripts\python.exe scripts/qualify_preset_tools.py --preset-id ollama-qwen35-4b-r1 --confirm-network
```

脚本 retry=0，不自动发布合同；输出写入被 Git 忽略的 `outputs/preset-qualification/`。该脚本不是普通启动或自动测试步骤。Presets 当前发布内容见[Preset 合同](deep-dive/models/PRESET_PUBLICATION.md)。

Assistant 来源资格验证使用独立单次入口，默认 dry-run：

```powershell
.\.venv\Scripts\python.exe scripts/qualify_assistant_turn.py --manifest scripts/manifests/assistant-Q3.json --dry-run
```

只有本次具体 manifest 获得用户明确授权后才加 `--confirm-network`。最多两次请求、每请求最多 256 输出 tokens、retry=0、空 History；安全结果写入 `outputs/assistant-qualification/`。CLI Snapshot 初始为空，不读取 Web 已 Apply 的状态。凭据受阻时安全停止，不改 ACL 或回退源码 `.env`；合同与安全字段见 [P2A-1 记录](records/2026-10-controlled-assistant-qualification-p2a.md)。

## Managed Custom 凭据与取消

正式凭据优先级为 `PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING`。Windows 私有目录、Manual V2 凭据分离和热加载语义见[凭据存储说明](deep-dive/operations/PRIVATE_CREDENTIAL_STORAGE.md)。旧源码根 `.env` 不参与运行，Flask 不加载 dotenv。在途请求持有创建时不可变的 CredentialSnapshot。

Stop 会关闭本地 SDK I/O；不能据此断言远端服务已停止推理或计费。Usage 不可用显示为 unavailable，不等于零。

## 离线回归

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --test tests/test_browser_streaming.cjs
node --check src/fishery_ai/resources/web/app.js
```

测试只使用 Mock、临时文件和虚构凭据。完整路径、运行目录与数据保留规则见[项目结构](STRUCTURE.md)及[数据位置地图](deep-dive/operations/PROJECT_DATA_AND_CONFIG_LOCATIONS.md)。

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

## 跨模型 History Qualification（开发实验）

两套独立准备入口；在项目根目录运行下列命令只做离线 plan 核对并保存各自的固定 `run-order.txt`，不会解析Credential或请求Provider：

```powershell
.\scripts\run_deepseek_projection_qualification.ps1
.\scripts\run_ollama_projection_qualification.ps1
```

DeepSeek：**COMPLETED — DO NOT REPEAT**，本轮30 runs / 48请求已完成，见[真实结果](records/2026-10-deepseek-history-projection-results.md)。Ollama入口已准备，内容与DeepSeek相同：H2F、H2-A/B、H5-A/B各6次，固定顺序30个独立进程，最多60模型请求，Thinking OFF / Normal、每请求最多256输出tokens、retry=0；普通失败不补跑，不与DeepSeek联动。

2026-10-11：用户明确批准旧DeepSeek批次归档后重新开始；5个旧run / 10次请求保存在 `outputs/assistant-qualification/archive/deepseek-stopped-20261011-122242/`，不计入新批次。当时清空活动目录并从第1项重跑，新批次现已完成；不要再运行原入口或历史 `run_deepseek_projection_qualification_remaining.ps1`。校验修复与归档见P2D记录§18。

Ollama测试使用现有 `ollama-qwen35-4b-r1` Preset，精确模型 `qwen3.5:4b`、`http://127.0.0.1:11434/v1`，Auth NONE。不要求API Key，不启动服务或下载模型。用户自行确认本地服务与模型已就绪后，可在正常PowerShell明确执行：

```powershell
# 默认仅检查五个固定plan与顺序，不请求本地模型
.\scripts\run_ollama_projection_qualification.ps1

# 用户确认开始本地模型真实测试，最多30 runs / 60请求
.\scripts\run_ollama_projection_qualification.ps1 -ConfirmNetwork
```

Ollama结果写入 `outputs/assistant-qualification/cross-model/ollama/`，与DeepSeek分开。Local请求会真实运行模型；若中途超时、连接失败或其他安全停止，保留报告并先审计，不能从头重跑。本轮脚本准备不包含Codex真实生成授权。

每个模型已有真实样本时拒绝重新开始；本地安全错误立即停止。Ollama连接/超时等传输错误也停止，保留安全报告，绝不启动服务或下载模型。输出分区为 `outputs/assistant-qualification/cross-model/{deepseek,ollama}/`。逐模型身份、hash、预算和解释边界见 [P2D preparation](records/2026-10-cross-model-history-projection-preparation.md)。本轮Codex没有执行真实批次；旧Qwen批次不得重跑。

## P2E History Qualification（仅准备）

P2E多轮History迁移资格实验当前仅准备，不迁移正式产品；冻结30个case，真实请求未执行。只读准备检查：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_product_migration_qualification.py
```

该入口不能联网。P2E 专用 runner 默认同样只审计全部30份冻结计划：

```powershell
.\scripts\run_product_migration_qualification.ps1
```

应显示 `PREPARED: 30 runs / max 60 requests / Provider requests = 0`。用户另行决定真实执行时才使用：

```powershell
.\scripts\run_product_migration_qualification.ps1 -ConfirmNetwork
```

固定跨模型顺序来自冻结索引，每个position独立Python进程、retry=0、最多两次请求。普通模型行为失败保留并继续；凭据、网络、安全或报告异常立即停止。已有真实P2E样本时拒绝重启；中断后先盘点，不resume、不补跑。矩阵、预算、固定顺序及判定见[P2E准备报告](records/2026-10-history-projection-product-migration-qualification.md)。不要用P2D runner运行P2E。P2E 真实结果已完成，迁移决策见[History v2 判定](records/2026-10-history-v2-migration-decision.md)。

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

## Assistant History v2

正式默认 `UNTRUSTED_TRANSCRIPT_V1@1`：先沿用完整 pair 裁剪（6 轮 / 6 KiB），再投影为未受信任 JSON 历史；当前问题独立。Web 无配置开关。

维护者回滚需先停止 Web，再以启动配置选择旧原生投影，重启产生新 epoch：

```powershell
python -c "from fishery_ai.web import run_web; from fishery_ai.history_projection import ProjectionId; run_web(assistant_history_projection=ProjectionId.CURRENT_NATIVE)"
```

恢复 B 使用正常 `python -m fishery_ai web`。不在进行中的会话内切换，不因请求失败自动回滚或重发。见[P2F 迁移记录](records/2026-10-history-v2-product-migration.md)。

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

只读 Tool 当前为 `get_current_water_quality`、Experimental `score_current_water_quality` 和默认关闭的 `search_fishery_knowledge`。默认最多一个 Tool call、一轮、两次模型请求；不是 Agent。Assistant 多轮启动配置位于 `src/fishery_ai/resources/profiles/assistant_execution.json`。当前 Prototype 的 Flag 已按用户授权开启：Qwen 查询+Knowledge 为 `released`（六案例真实资格），DeepSeek / Ollama 为 `local_experimental`（尚无真实多轮资格证据，不填资格编号/验证时间）。仅 OFF + Normal 且 Assistant 恰好授权查询+Knowledge，或查询+评分+Knowledge 三项时启用 2/2/3。三 Tool 范围在三个 Preset 下均为独立 local_experimental，不继承 Qwen 两 Tool 资格；其他未登记组合或范围失配则执行并显示单轮。Web 显示当前有效的最多两次或三次模型请求，确认 revision 失配时联网前拒绝并要求重新确认。关闭 Flag 并完整重启可回滚；当前仅供本地开发体验，未推广到其他模型或 Analysis。操作方法见[三模型本地试用](deep-dive/research/ASSISTANT_MULTI_ROUND_INTEGRATION.md#11-phase-4c-三预设本地试用发布)。当前设计与限制见[Analysis / Assistant 当前架构](deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md)和[只读 Tool 当前实现](deep-dive/tools/READ_ONLY_TOOL_CALLING.md)。

## Tool / Preset 维护

资格工具的实现位于 `src/fishery_ai/development/qualification/`，维护入口仍在 `scripts/qualification/`。正常 Web / Assistant / Analysis 不加载该开发子包；它单向复用正式产品合同。旧模块路径保留兼容别名，新代码使用开发子包路径，详见[维护工具说明](../scripts/README.md)。`validate-real` CLI 仅在选中该命令时加载开发实现；当前 experimental Profile 为空时安全返回 `INACTIVE_VALIDATION_PROFILE`，不自动恢复旧连接。

Tool 管理入口在左侧 **01 · Analysis Model → Tool**，分 Analysis / Assistant 两个授权视图。Catalog 展示不等于注册或授权；真实执行还受 Registry、Policy、Handler 与 Runtime capability 约束。

维护者资格脚本需单独确认网络并一次指定一个 Preset：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_preset_tools.py --preset-id ollama-qwen35-4b-r1 --confirm-network
```

脚本 retry=0，不自动发布合同；输出写入被 Git 忽略的 `outputs/preset-qualification/`。该脚本不是普通启动或自动测试步骤。Presets 当前发布内容见[Preset 合同](deep-dive/models/PRESET_PUBLICATION.md)。

Assistant 来源资格验证使用独立单次入口，默认 dry-run：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_assistant_turn.py --manifest scripts/qualification/manifests/assistant-Q3.json --dry-run
```

Q1–Q4 保留为单次维护计划示例，使用空 History；不包含已结束的 H / P2E 批次。真实运行必须针对具体计划和次数获得本轮明确授权，才使用 `--confirm-network`。Harness 最多两次请求、每请求最多 256 输出 tokens、retry=0；安全结果写入 `outputs/assistant-qualification/`。CLI Snapshot 初始为空，不读取 Web 已 Apply 的状态。凭据受阻时安全停止，不改 ACL 或回退源码 `.env`。

内部有界多轮使用新的单案例入口，默认 Qwen 3.8 Flash / OFF / Normal。先检查计划，不读取凭据、不联网、不写报告：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_multi_round.py --case low-oxygen --dry-run
```

可选 case：`low-oxygen`（当前水质→异常知识→Final，最多 3 次请求）、`normal`（查询→Final，最多 2 次）、`current-do`（查询→Final，最多 2 次）、`concept`（无 Tool 直答，最多 1 次）。每次只选择一个 case；没有批次、自动重试或 failover。独立进程使用合成 Snapshot，不读取或修改 Web Snapshot / Policy。该旧实验入口不决定 Web 的发布范围。

真实运行需用户针对该 case 单独授权，再将 `--dry-run` 换成 `--confirm-network`；默认每请求最多 256 输出 tokens，retry=0。其他已发布 Preset 可用 `--preset` 指定，但不能沿用 Qwen 授权。安全报告仍写入固定 `outputs/assistant-qualification/`，以 `bounded-multi-round@1` 标记；不保存最终正文、query、完整 Tool Result 或 Prompt。详见[实验边界和通过条件](deep-dive/tools/READ_ONLY_TOOL_CALLING.md#单案例多轮资格入口)。

上述不带 `--assistant-product` 的入口仍是旧实验指令。正式多轮资格必须明确添加 `--assistant-product`，只允许当前 Qwen 精确范围，直接复用正式 AssistantService / Prompt / History / Commit Gate；每案例最多 2 calls / 2 rounds / 3 requests。准备命令如下（不联网、不解析凭据）：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_multi_round.py --assistant-product --case low-oxygen --dry-run
```

可选 case 为 low-oxygen / normal / current-do / concept / history-current / history-explanation。真实执行仍需逐案例单独批准才改用 `--confirm-network`；可添加 `--review-answer` 在终端 stderr 查看完整成功回答，JSON 报告不保存正文。不要重定向预览或开启终端 transcript。技术检查通过仅为 `PENDING_MANUAL_REVIEW`，不会发布 candidate 或打开 Web Flag。详见[Phase 4C 计划、预算与人工标准](deep-dive/research/ASSISTANT_MULTI_ROUND_INTEGRATION.md#10-phase-4c-正式-assistant-资格准备)。

History 的 Qwen、DeepSeek、Ollama A/B 批次和 P2E 多轮历史资格实验均已结束，正式产品迁移也已完成；对应一次性 runner、manifest / index / generator 和实验测试已移除。实验合同、结果及停止事故保留在[记录索引](records/README.md)与 Git；迁移依据见[History v2 判定](records/2026-10-history-v2-migration-decision.md)。不得按旧授权重跑或补样本。

## Managed Custom 凭据与取消

正式凭据优先级为 `PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING`。Windows 私有目录、Manual V2 凭据分离和热加载语义见[凭据存储说明](deep-dive/operations/PRIVATE_CREDENTIAL_STORAGE.md)。旧源码根 `.env` 不参与运行，Flask 不加载 dotenv。在途请求持有创建时不可变的 CredentialSnapshot。

Stop 会关闭本地 SDK I/O；不能据此断言远端服务已停止推理或计费。Usage 不可用显示为 unavailable，不等于零。

## 离线回归

```powershell
# 日常核心；按改动选 assistant / tools / providers / domain / security / web
.\.venv\Scripts\python.exe scripts/dev/run_tests.py fast

# 完整产品回归（默认入口），不包含资格基础设施
.\.venv\Scripts\python.exe scripts/dev/run_tests.py product
node --test tests/web/test_browser_streaming.cjs

# 仅资格基础设施修改时；仍然全离线
.\.venv\Scripts\python.exe scripts/dev/run_tests.py qualification

node --check src/fishery_ai/resources/web/app.js
```

测试只使用 Mock、临时文件和虚构凭据。标准全发现命令为 `python -m unittest discover -s tests -t .`，包括产品与 qualification；单模块可用 `python -m unittest tests.assistant.test_history_projection`。层级、发现路径与覆盖边界见[测试说明](../tests/README.md)。完整路径、运行目录与数据保留规则见[项目结构](STRUCTURE.md)及[数据位置地图](deep-dive/operations/PROJECT_DATA_AND_CONFIG_LOCATIONS.md)。

## Assistant History v2

正式默认 `UNTRUSTED_TRANSCRIPT_V1@1`：先沿用完整 pair 裁剪（6 轮 / 6 KiB），再投影为未受信任 JSON 历史；当前问题独立。Web 无配置开关。

维护者回滚需先停止 Web，再以启动配置选择旧原生投影，重启产生新 epoch：

```powershell
python -c "from fishery_ai.web import run_web; from fishery_ai.history_projection import ProjectionId; run_web(assistant_history_projection=ProjectionId.CURRENT_NATIVE)"
```

恢复 B 使用正常 `python -m fishery_ai web`。不在进行中的会话内切换，不因请求失败自动回滚或重发。见[P2F 迁移记录](records/2026-10-history-v2-product-migration.md)。

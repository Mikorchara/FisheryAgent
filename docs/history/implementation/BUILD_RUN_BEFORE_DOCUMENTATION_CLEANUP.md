# 构建与运行

> 文档分类：**HISTORICAL**。2026-10-03 文档整理前的入口快照，保留旧 A1/A2/A3 流水账和操作描述，不作为当前指南。当前入口见[项目 README](../../../README.md)及[构建运行](../../BUILD_RUN.md)。

## 当前 Preset 发布（2026-10-03）

当前发布 **Qwen 3.8 Flash、DeepSeek Flash、Ollama Qwen3.5 4B**，均为 contract **1.0.0**，来自 Clean-room 后的精确活动 Evidence 与用户正常 Web 进程人工验收，不恢复旧 Preset。三个模型均发布 **OFF + Normal、ON + Normal、ON + Streaming**；AUTO、OFF + Streaming 暂未发布。Qwen 仍是默认模型，默认 **Thinking OFF + Normal**。启动页面不会自动联网。

Preset 页仅选择 Model、Thinking、Response Mode，再选择水质场景和问题、确认 REAL NETWORK REQUEST 后开始分析。不显示连接参数、Capability Evidence 或 Probe。凭据缺失返回 SECRET_MISSING；请在 Managed Custom 的凭据管理入口设置用户私有凭据，Preset 页不录入 Key。

开发者在包内 `resources/profiles/presets.json` 维护固定 Template / Variant / ProtocolSpec / contract；`default_preset_id` 设为已发布 ID 时自动选择对应默认组合，设为 null 或移除时显示“请选择模型”。不提供 Publisher UI，不从本地 Evidence 自动更新合同。详见 [Preset 简化与首次发布](../../validation/PRESET_SIMPLIFICATION_AND_FIRST_PUBLICATION.md)。

DeepSeek 发布对象为 **deepseek-flash**（Saved Connection DS_2），不是 deepseek-v4-pro；凭据引用 DEEPSEEK_API_KEY。Ollama 发布对象为 **qwen3.5:4b / http://127.0.0.1:11434/v1 / generic_openai_chat**，Auth NONE，connect/read/total 为 5/120/180 秒。Thinking 较慢是性能现象，不等于不支持；Streaming Usage 未证实，显示 unavailable。

历史资格验证中 Codex 的 CREDENTIAL_FILE_ERROR 与本地 READ_TIMEOUT 记录仍保留，已由本轮用户正常 Web 进程人工验收和新活动 Evidence 补充。Qwen 没有 OFF + Streaming 的直接组合成功记录，未升级至 1.0.1。本轮仅登记合同，没有重新联网、解析真实凭据或修改 CredentialStore。详见发布报告第 12 节。

`scripts/qualify_local_preset_request.py` 是开发者**单次**本地资格检查工具，需显式 --confirm-network、现有精确本地 Saved Connection、--thinking on/off，可选 --streaming 或 --manual-v1。每次最多一个 64-token请求、retry=0；不自动重试、扫描、写 Evidence 或发布合同。超时后应先诊断，不能循环执行；摘要存于 ignored outputs/preset-qualification，不存完整正文。

## Clean-room 重置历史（2026-10-03）

以下记录重置当时的空目录状态；随后用户创建的连接、Evidence 和上述新 Preset 均不再为空。旧模型资产仍只在历史 fixture / 归档中保留，正常启动不恢复。

活动真实模型目录已重置：没有已发布 Preset、Legacy Built-in 或 User Custom 模型；模型级官方声明表和本地活动 Evidence 均为空。Provider 连接模板、ProtocolSpec、凭据、Resolver、Probe、Cancellation 和 Manual V1 保留。

使用 `python -m fishery_ai web`；默认 Preset 页显示空状态。切换 **Managed Custom → 新建**，选择 Provider、填写精确 Model 和 credential_ref；在本地凭据管理中只查看状态或显式设置私有凭据。原凭据未清除，无须重新录入仍有效的 Key。完成显式连接测试并保存后，高级能力仍为 UNKNOWN；先运行 Normal + AUTO，再按需单项 Probe。模型列表成功不解锁 Capability。Manual V1 在有 Saved Connection 后仍可用；Development / Test 保留 Mock。

历史模型数据只保存在 Git、报告、`tests/fixtures/historical_model_assets/` 和非活动 `outputs/archive/model-validation-reset-20261003/`。正常启动从不读取这些测试或归档目录。详见 [Clean-room Reset 报告](CLEAN_ROOM_MODEL_VALIDATION_RESET.md)。

## Preset / Stop / Manual Expert

一级入口仍为 **Preset / Managed Custom / Manual Expert**，默认显示 Preset；默认选择新发布的 Qwen 3.8 Flash，启动不会发送生成请求。Thinking 与 Response Mode 保持独立。**Development / Test** 当前只保留 Mock；Clean-room 前的模型方案未恢复，相关旧合同仅在显式历史 fixture 测试中加载。当前 DeepSeek Flash 与 Ollama 是新登记的固定合同。

点击“停止生成”会先向后端请求取消 SDK I/O，再停止浏览器读取；页面分别显示后端关闭状态与远端计算 UNKNOWN，不能据此保证停止云端计费。

在一级运行方式中选择 **Manual Expert**，默认 **Saved Connection / V1** 使用最小的 Connection / Target 选择器，进入独立 Raw Request / Raw Response 页面。V1 的 Capability、Probe、水质场景、Thinking、Response Mode 和连接 CRUD 均隐藏。直接编辑 Raw JSON body；model 必须一致，禁止自定义 Header / URL / Credential / transport 配置。点击 Send 后显式确认 REAL NETWORK REQUEST。Normal 与 `stream:true` 都支持 Stop。V1 不执行水质分析、RAG、Capability / 默认值注入或 tool_calls；Raw response、Usage 与耗时只在调试区显示，不存模板。

**Manual V2 基础版**：在 Manual Expert 页面选择 **Manual V2 · 独立实验**。自行填写 Experiment Name、Service Name（自由标签）、Base URL、Model、Timeout、Raw JSON。页面 Model 是权威 ID；Raw JSON 可省略 model，后端请求准备时补入，不改编辑器或保存内容；显式 model 必须相同，否则返回 MANUAL_MODEL_MISMATCH。可 New / Save / Save As / Delete；Save 保存/更新当前实验，Save As 用当前内容创建新实验并保留原实验。保存位置为 Git ignored 的 `outputs/manual-experiments/`。

V2 的 Credential Ref / 凭据名称（例如 `DASHSCOPE_MANUAL_KEY`）只引用独立用户私有 `credentials/manual.env`。填写引用名 → 刷新状态 → 在 New Key / API Key Value 中仅输入真实 Key 值（不填 NAME=value）→ Create / Set Key（已有时 Replace / Delete）。Experiment 只保存 credential_ref，不保存 Key。输入提交即清空，旧 Key 永不回显；空引用表示无需凭据。V2 不读取正式 `credentials/.env`、进程 Key 或源码根 `.env`。V1 与 Managed 继续使用原凭据来源，不读取 manual.env。

Send 必须确认 REAL NETWORK REQUEST；Raw `stream:true` 使用同一流式传输，Stop 复用后端取消机制。不会自动注入 Thinking / Effort / include_usage，不生成 Evidence，不执行 tool_calls。切换 V1 / V2 保留双方草稿；V2 不要求先有 Saved Connection。实验资产不等于正式连接，转换机制仍 NOT DECIDED。详见 [Manual V2 实施报告](MANUAL_EXPERT_V2_IMPLEMENTATION.md)；原[三模式设计校正](../../research/MODEL_ACCESS_THREE_MODE_PLAN.md)保留为设计历史。

凭据仍统一来自 **PROCESS_ENV > user-private PROJECT_ENV > MISSING**。上一实施阶段的受控联网阻塞记录保留在[阶段实施报告](PRESET_CANCELLATION_MANUAL_IMPLEMENTATION.md)；用户随后已反馈主要功能人工验证正常。该 UI 整理轮次未发真实请求；用户已反馈当前界面人工验收基本正常，历史待验收记录保留在[三模式 UI 整理报告](MODEL_SELECTION_UI_THREE_MODE_CLEANUP.md)。

历史 `validate_access_modes.py` 仍保留确认/retry/timeout 合同，其旧目标未恢复，返回 `INACTIVE_VALIDATION_PROFILE`，不发送请求。它不会从测试 fixture、归档或旧根 `.env` 恢复模型。新一轮验证使用 Managed Custom 的显式 UI；不要将 `outputs/` 记录加入 Git。

## Managed Custom：凭据与高级能力验证

在 **Managed Custom → 新建 → Provider** 填写连接和凭据引用。展开 **本地凭据管理**，刷新后可设置 / 替换 / 删除用户私有 Key；无须先保存 Profile，查询模型前可先设置凭据。真正外部 PROCESS_ENV 只读，Auth NONE 不要求 Key；页面不返回已有 Secret，也不编辑源码根 `.env`。

高级能力由精确 Identity 的 Evidence 经 Resolver 判断。UNKNOWN 时 Normal + AUTO 仍可用，Streaming / Thinking 的显式选项保持禁用。点击单项 Probe 并确认 REAL NETWORK REQUEST 才联网，每次一个最小请求、retry=0；结果写 Evidence，再重新解析并更新页面。相反证据保持 UNKNOWN，网络失败不写 UNSUPPORTED。Generic Thinking 不猜开关；已知 DashScope/DeepSeek 协议中的未知模型可以显式验证，其他未知 Ollama 模型暂仅开放 Streaming Probe。

Preset 合同不被本地 Evidence 修改，Manual V1 Raw 请求不经过上述编码/解析。阶段测试、限制与人工验收见 [R3/R4/R5 实施报告](PROTOCOL_EVIDENCE_PROBE_R3_R4_R5.md)。本轮没有自动执行真实 Probe。

## 环境要求

- Python 3.11 或更新版本。
- 在仓库根目录打开 Windows PowerShell。

## Windows 环境准备

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -e .
```

如果 PowerShell 无法识别不带扩展名的激活命令，可改用 `.\.venv\Scripts\Activate.ps1`；也可以不激活环境，直接调用 `.\.venv\Scripts\python.exe`。

`pyproject.toml` 声明运行时依赖：官方 `openai` SDK、用于超时配置的 `httpx`、读取本地 `.env` 的 `python-dotenv`，以及开发验证页面使用的 Flask。默认 TF-IDF 实现只使用 Python；替代检索后端可选用 `scikit-learn`，默认流程和测试不依赖它。项目不另行维护 `requirements.txt`。
Web、`validate-real` 及三个 `scripts/validate_qwen_*.py` 入口均复用 `private_project_location`，只在启动边界根据项目绝对路径确定用户私有凭据路径。只读 `CredentialStore` 在每次新请求开始时解析所选单一文件，使用 `dotenv_values(interpolate=False)`，不会把内容导入 `os.environ`；Flask 启动显式 `load_dotenv=False`，没有旧根目录 `.env` fallback。普通 Demo 和离线测试不读取真实凭据。

## 离线测试

```powershell
python -m unittest discover -s tests -v
```

测试使用假 SDK 客户端并阻断 socket 连接，不使用真实 API Key，不调用真实 API，也不启动模型。

V0.1.1-A1 的测试覆盖 Profile 状态、精确模型能力、参数校验、适配器映射和 Token Usage。上述命令仍是默认 Python 测试入口；真实 API 验证须另行安排。

浏览器逻辑测试与语法检查使用 Node 内置工具，不需要安装前端依赖：

```powershell
node --test tests/test_browser_streaming.cjs
node --check src/fishery_ai/resources/web/app.js
git diff --check
```

R0/R1 凭据定向测试：`python -m unittest discover -s tests -p 'test_credential*.py' -v`。这些测试只使用临时 `.env`、虚构 Key 和禁网保护。

上述定向命令现在也覆盖 R2 Writer 与 Credential Web API。浏览器凭据定向命令：`node --test --test-name-pattern 'R2|Credential' tests/test_browser_streaming.cjs`。Windows 测试会显式创建私有 ACL 的临时子目录，禁止读写真实项目 `.env`。

## Mock 演示

```powershell
python -m fishery_ai demo
python -m fishery_ai demo --profile local-demo --scenario partial_stale
```

无论选择哪种 Profile，演示都使用 `MockGateway`，不会调用 Cloud 或本地模型。JSONL Trace 写入当前工作目录的 `outputs/`。

输出 JSON 后会打印 **Request Usage** 与 **Validation Session Usage**。Mock 不返回真实 Token 统计，因此显示 `unavailable`，含义是服务没有提供数据，并非消耗为 0。会话累计只在当前进程内存中；本 Demo 只有一次请求。Profile 示例为 EXPERIMENTAL/CUSTOM，没有真实 VERIFIED 预设。

## 历史显式真实 Cloud 验证（当前停用）

仅在拥有明确授权、确认可能产生费用时使用。例如从项目根目录执行：

```powershell
python -m fishery_ai validate-real --check basic --confirm-network
```

当前该命令所用的 DeepSeek EXPERIMENTAL Profile 已退出活动目录；确认参数存在时也只返回 `INACTIVE_VALIDATION_PROFILE`，不会联网或回退到归档。三个 `scripts/validate_qwen_*.py` 同样停用。以下是历史行为说明，不代表当前模型已验证：该命令曾使用单独的 DeepSeek EXPERIMENTAL Profile，不改变 `demo` 的离线语义。真实入口每次只执行指定的一项检查，自动重试设为 0；输出仅显示 `Secret: PRESENT/MISSING`，不显示 Key。缺失 Secret 时不会调用 API。当前可用检查与已实测结果见 [A2 报告](../validation/V0.1.1_A2_DEEPSEEK_VALIDATION_REPORT.md)；不要把实验探测能力当作已验证的普通业务配置。

## 本地 Developer Validation Web UI

先在项目虚拟环境安装当前包（已有环境也需在新增 Flask 依赖后重新执行）：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m fishery_ai web
```

启动后浏览器访问 `http://127.0.0.1:8765`；可用 `--port 8766` 更换端口。默认只绑定 `127.0.0.1`，只接受当前端口的 loopback Host，默认展示 Preset，不自动生成；Mock 需从 Development / Test 入口显式选择。页面分析仍使用已有水质 Mock 场景。Qwen 3.8 Flash / DeepSeek Flash / Ollama Qwen3.5 4B 使用已发布的固定 Variant，只对合同中的组合负责，不宣称其他高级能力已验证。真实分析需勾选 **REAL NETWORK REQUEST**，Cloud 可能产生费用；请求使用固定用户私有文件或进程环境中的 Secret，Ollama Auth NONE 不需要 Key。凭据管理接收用户新输入的 Key，不返回已有 Key。启动终端输出固定凭据文件位置（不输出值）。关闭终端即可停止本地服务。

仅 Managed Custom 显示“管理模型配置”，可选择 Qwen、DeepSeek、Ollama 或 Custom OpenAI-compatible 的连接预设。这些 Provider 连接预设不是项目维护的模型 Preset Contract。高级设置包含 `service_id`、Adapter、Secret 环境变量名与 `AuthSpec`；认证要求与 Cloud/Local 类型独立。Provider 注册和 Profile、Capability、Evidence 不依赖凭据是否存在。

凭据优先级为 **Process Environment > 私有项目凭据文件 > Missing**。外部环境明确存在变量，即使值为空也不会回退文件。状态接口只返回变量名、PRESENT/MISSING/NONE_REQUIRED、来源、位置类型及编辑权限，不返回 Key、长度、片段或 Hash。`PROCESS_ENV` 外部只读；`PROJECT_ENV / 用户私有存储` 可通过本地凭据管理设置、替换或删除。首次设置也可先填写未保存的 Custom Profile，再打开凭据管理。

设置/替换前填写新 Key，删除需确认；提交后输入立即清空，不把 Key 存入 Profile 或 LocalStorage。写 API 要求匹配的本地 Host、同源 Origin 和当前会话 CSRF，不开放 CORS。修改成功后新请求立即生效，旧连接测试授权和页面模型列表清空；Capability Evidence 与 Runtime Defaults 保留。

Writer 固定目标为 `%LOCALAPPDATA%\Fishery_AI_Prototype\project-<项目路径哈希>\credentials\.env`；保留注释、未知变量、换行和 BOM。锁、私有暂存与恢复文件跟随同一目录，同卷原子替换。Windows 检查 LOCALAPPDATA 基目录及已存在专用目录的 owner/DACL、路径和卷，首次显式写入才创建新私有目录；不更改现有 ACL。外部存储不要求 Git ignore，旧项目内 Writer 的 Git 检查保留。无法确认安全时拒绝，revision 冲突请刷新；恢复失败时由用户检查私有 `.env.stage-*`，禁止外传内容。详见 [迁移说明](../../guides/R2_PRIVATE_CREDENTIAL_STORAGE_MIGRATION.md)。

**首次升级需重启旧 Web 进程一次**，并在页面手动重新设置凭据。旧项目 `.env` 不读取、不迁移、不删除，不合并其他文件来源。之后修改私有凭据文件，新请求立即读取，无需重启，进行中的请求仍使用旧快照。外部进程变量仍优先。必需凭据缺失返回 `SECRET_MISSING`；私有路径/ACL 不安全、文件不可读或格式错误返回脱敏的 `CREDENTIAL_FILE_ERROR`；LOCALAPPDATA 缺失或路径无效时启动停止并显示 `CREDENTIAL_STORAGE_UNAVAILABLE`。

Development / Local Experimental 入口使用的旧 loopback Ollama 定义显式为 `AuthSpec.NONE`，显示“不需要凭据”，不显示 Key 编辑，不读取任何凭据来源。旧 Local Custom Profile 的 `secret_env` 引用仍保留；不会根据 Local 类型自动改成 NONE。详情见 [R0/R1 实施报告](PROVIDER_CREDENTIAL_REFACTOR_R0_R1.md)。

“查询可用模型”仅在点击后访问所选服务的模型列表接口；若不支持，可手动填写 Model ID。“测试连接”默认检查模型列表；必要时手动切换到可能收费的最小 Chat。Cloud Profile 保存前必须完成当前连接字段的一次成功测试；Local 可直接保存。Managed Custom 的模型连接选择会同步显示所选配置；User Custom 可编辑连接参数或删除，Preset 不显示 CRUD。新建需填写唯一 Display Name，创建后不可改名；重名返回 `PROFILE_NAME_EXISTS`，如需改名须删除后重建。不再自动生成副本名称或显示冲突操作面板。删除移入 `outputs/custom_profiles/archive/`。用户配置文件位于被 Git 忽略的 `outputs/custom_profiles/`，不含 Key；高级 Capability 仍为 UNKNOWN。历史流程见 [A3.0.4 实施记录](../obsolete/V0.1.1_A3_0_4_CUSTOM_PROFILE_MANAGER.md)，当前规则见 [A3.1.2 实施记录](V0.1.1_A3_1_2_PROFILE_MANAGER_SIMPLIFICATION.md)。

页面复用固定 Orchestrator，可选择 **Normal** 或 **Streaming** Chat 分析。Streaming 先显示事实、规则和 RAG 证据，再逐段显示模型正文；完成后显示结构化结果、TTFT、总耗时和 Usage。运行选项由当前精确 Profile 的 Capability 驱动，证据可来自官方文档、模型 Metadata 或独立用户验证；UNKNOWN 的显式高级选项会在传输前返回 `OPTION_UNKNOWN`，基础 Normal + AUTO/UNSET 仍可使用。RAG 证据是背景知识，模型推断与建议单独标注；证据和原始模型正文默认折叠。运行时 Trace 写入被 Git 忽略的 `outputs/web-traces.jsonl`，不写 Prompt、模型正文或 Secret。离线测试使用 Flask 进程内测试客户端与假 Gateway，绝不请求 Cloud。详情见 [A3.2 Capability 报告](V0.1.1_A3_2_CLOUD_CAPABILITY_STREAMING_THINKING.md)与 [R0/R1 实施报告](PROVIDER_CREDENTIAL_REFACTOR_R0_R1.md)。

需要明确授权后复测 Qwen `low_oxygen` 时，可从项目根目录运行 `python scripts/validate_qwen_grounding.py --confirm-network`。此命令可能产生费用，每次运行只发送一次真实请求；结果以 UTF-8 写入被 Git 忽略的 `outputs/qwen-grounding-*.json`，终端只显示 ASCII 状态，避免 Windows GBK 编码问题。不要把验证记录加入 Git。当前实测结果和仍需检查的建议数值见 [A3.0.3 记录](V0.1.1_A3_0_3_UTF8_CUSTOM_PROFILE_QWEN_VALIDATION.md)。

### Qwen 手动验证脚本的统一凭据边界

以下只列出供用户另行授权后手动执行的命令，默认测试不会执行真实请求：

| 脚本 | 显式确认 | 原有请求预算 |
|---|---|---|
| `python scripts/validate_qwen_grounding.py` | `--confirm-network` | 1 次 Grounding 分析 |
| `python scripts/validate_qwen_streaming.py` | `--confirm-network` | 1 次应用级 Streaming 分析 |
| `python scripts/validate_qwen_output_parity.py` | `--confirm-four-network-requests` | 4 次固定 Normal/Streaming 与 Thinking 对照 |

三个入口均从项目根目录启动，使用 **PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING**，和 Web / `validate-real` 相同；不读取旧源码 `.env`，不自动迁移、不接受凭据文件路径参数。原有零重试、Profile timeout 和验证业务不变。缺失凭据只报告 `QWEN_SECRET MISSING` 并退出，私有路径不可用/权限错误返回安全错误，不回退旧文件。修复与回归见 [Post-R2 审计](POST_R2_STRUCTURAL_AUDIT.md)。

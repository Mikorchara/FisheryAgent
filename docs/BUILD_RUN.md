# 构建与运行

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
Web 启动与显式真实验证入口只在启动边界确定当前工作目录的 `.env` 路径。只读 `CredentialStore` 在每次新请求开始时解析凭据，使用 `dotenv_values(interpolate=False)`，不会把文件内容导入 `os.environ`；普通 Demo 和离线测试不读取真实项目 `.env`。

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

## Mock 演示

```powershell
python -m fishery_ai demo
python -m fishery_ai demo --profile local-demo --scenario partial_stale
```

无论选择哪种 Profile，演示都使用 `MockGateway`，不会调用 Cloud 或本地模型。JSONL Trace 写入当前工作目录的 `outputs/`。

输出 JSON 后会打印 **Request Usage** 与 **Validation Session Usage**。Mock 不返回真实 Token 统计，因此显示 `unavailable`，含义是服务没有提供数据，并非消耗为 0。会话累计只在当前进程内存中；本 Demo 只有一次请求。Profile 示例为 EXPERIMENTAL/CUSTOM，没有真实 VERIFIED 预设。

## 显式真实 Cloud 验证

仅在拥有明确授权、确认可能产生费用时使用。例如从项目根目录执行：

```powershell
python -m fishery_ai validate-real --check basic --confirm-network
```

该命令使用单独的 DeepSeek EXPERIMENTAL Profile，不改变 `demo` 的离线语义。真实入口每次只执行指定的一项检查，自动重试设为 0；输出仅显示 `Secret: PRESENT/MISSING`，不显示 Key。缺失 Secret 时不会调用 API。当前可用检查与已实测结果见 [A2 报告](deep-dive/V0.1.1_A2_DEEPSEEK_VALIDATION_REPORT.md)；不要把实验探测能力当作已验证的普通业务配置。

## 本地 Developer Validation Web UI

先在项目虚拟环境安装当前包（已有环境也需在新增 Flask 依赖后重新执行）：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m fishery_ai web
```

启动后浏览器访问 `http://127.0.0.1:8765`；可用 `--port 8766` 更换端口。默认只绑定 `127.0.0.1`，默认选中 Mock，完全离线。页面可选已有水质 Mock 场景，也可选 Qwen Plus 与 DeepSeek Flash 的 **EXPERIMENTAL** Cloud Profile。真实分析需勾选 **REAL NETWORK REQUEST**，Cloud 可能产生费用；请求使用当前工作目录 `.env` 或进程环境中的 Secret，页面不会提供 Key 输入框或返回 Key。关闭终端即可停止本地服务。

页面的“管理模型配置”区域可选择 Qwen、DeepSeek、Ollama 或 Custom OpenAI-compatible 预设。高级设置包含 `service_id`、Adapter、Secret 环境变量名与 `AuthSpec`；认证要求与 Cloud/Local 类型独立。Provider 注册和 Profile、Capability、Evidence 不依赖凭据是否存在。

凭据优先级为 **Process Environment > Project .env > Missing**。外部环境明确存在变量，即使值为空也不会回退文件。页面只显示变量名、PRESENT/MISSING、来源和只读范围，不显示 Key、长度、片段或 Hash。`PROCESS_ENV` 标注“外部只读”；`PROJECT_ENV` 标注“未来可编辑（本轮只读）”，当前没有 Key 编辑接口。

**首次升级需重启旧 Web 进程一次**，结束旧 `load_dotenv` 导入的环境状态；之后修改项目 `.env`，新请求立即重新读取，无需重启，进行中的请求仍使用旧凭据快照。若启动进程继承了外部环境变量，文件修改不会覆盖该来源。必须认证的配置缺失凭据返回 `SECRET_MISSING`；文件不可读或格式错误返回脱敏的 `CREDENTIAL_FILE_ERROR`。

Built-in loopback Ollama 显式为 `AuthSpec.NONE`，不显示 Secret 输入或状态，不读取任何凭据来源。旧 Local Custom Profile 的 `secret_env` 引用仍保留；不会根据 Local 类型自动改成 NONE。详情见 [R0/R1 实施报告](deep-dive/PROVIDER_CREDENTIAL_REFACTOR_R0_R1.md)。

“查询可用模型”仅在点击后访问所选服务的模型列表接口；若不支持，可手动填写 Model ID。“测试连接”默认检查模型列表；必要时手动切换到可能收费的最小 Chat。Cloud Profile 保存前必须完成当前连接字段的一次成功测试；Local 可直接保存。顶部 Runtime / Model 切换会同步显示所选配置；Built-in 只能查看，User Custom 可编辑连接参数或删除。新建需填写唯一 Display Name，创建后不可改名；重名返回 `PROFILE_NAME_EXISTS`，如需改名须删除后重建。不再自动生成副本名称或显示冲突操作面板。删除移入 `outputs/custom_profiles/archive/`。用户配置文件位于被 Git 忽略的 `outputs/custom_profiles/`，不含 Key；高级 Capability 仍为 UNKNOWN。历史流程见 [A3.0.4 实施记录](deep-dive/V0.1.1_A3_0_4_CUSTOM_PROFILE_MANAGER.md)，当前规则见 [A3.1.2 实施记录](deep-dive/V0.1.1_A3_1_2_PROFILE_MANAGER_SIMPLIFICATION.md)。

页面复用固定 Orchestrator，可选择 **Normal** 或 **Streaming** Chat 分析。Streaming 先显示事实、规则和 RAG 证据，再逐段显示模型正文；完成后显示结构化结果、TTFT、总耗时和 Usage。运行选项由当前精确 Profile 的 Capability 驱动，证据可来自官方文档、模型 Metadata 或独立用户验证；UNKNOWN 的显式高级选项会在传输前返回 `OPTION_UNKNOWN`，基础 Normal + AUTO/UNSET 仍可使用。RAG 证据是背景知识，模型推断与建议单独标注；证据和原始模型正文默认折叠。运行时 Trace 写入被 Git 忽略的 `outputs/web-traces.jsonl`，不写 Prompt、模型正文或 Secret。离线测试使用 Flask 进程内测试客户端与假 Gateway，绝不请求 Cloud。详情见 [A3.2 Capability 报告](deep-dive/V0.1.1_A3_2_CLOUD_CAPABILITY_STREAMING_THINKING.md)与 [R0/R1 实施报告](deep-dive/PROVIDER_CREDENTIAL_REFACTOR_R0_R1.md)。

需要明确授权后复测 Qwen `low_oxygen` 时，可从项目根目录运行 `python scripts/validate_qwen_grounding.py --confirm-network`。此命令可能产生费用，每次运行只发送一次真实请求；结果以 UTF-8 写入被 Git 忽略的 `outputs/qwen-grounding-*.json`，终端只显示 ASCII 状态，避免 Windows GBK 编码问题。不要把验证记录加入 Git。当前实测结果和仍需检查的建议数值见 [A3.0.3 记录](deep-dive/V0.1.1_A3_0_3_UTF8_CUSTOM_PROFILE_QWEN_VALIDATION.md)。

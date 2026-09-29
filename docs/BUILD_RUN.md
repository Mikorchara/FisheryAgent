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

`pyproject.toml` 声明运行时依赖：官方 `openai` SDK，以及用于超时配置的 `httpx`。默认 TF-IDF 实现只使用 Python；替代检索后端可选用 `scikit-learn`，默认流程和测试不依赖它。项目不另行维护 `requirements.txt`。
`python-dotenv` 仅由显式真实验证入口在 CLI 边界加载当前工作目录的 `.env`；普通 Demo 和测试不读取该文件。

## 离线测试

```powershell
python -m unittest discover -s tests -v
```

测试使用假 SDK 客户端并阻断 socket 连接，不使用真实 API Key，不调用真实 API，也不启动模型。

V0.1.1-A1 的测试覆盖 Profile 状态、精确模型能力、参数校验、适配器映射和 Token Usage。上述命令仍是唯一默认测试入口；真实 API 验证须另行安排。

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

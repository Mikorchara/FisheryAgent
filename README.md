# Fishery AI Prototype V0.1 / V0.1.1-A1

这是独立的智慧渔业 AI 架构原型，用固定流程验证数据合同、水质规则、知识检索、模型配置切换和结构化输出。默认运行路径完全离线。生产项目 `D:\Fishery_Project` 仅作为只读参考和知识快照来源。

文档入口：[docs/README.md](docs/README.md)。新开发者建议先阅读 [构建与运行](docs/BUILD_RUN.md)，再阅读 [项目结构](docs/STRUCTURE.md)。

## 与其他项目的关系

- **Fishery_Project** 是现有生产应用，包含 Flask、传感器上报、SQLite、视频处理、YOLO/SAM 和实际 UI。本原型不导入其模块、不连接其数据库，也不修改该项目。
- **Fishery_AI_Prototype** 独立运行，使用固定 Mock 水质与检测场景。未来可在合同边界接入生产系统适配器。
- **LLM_Lab** 用于学习和试验通用 LLM 原理；本原型只处理智慧渔业业务合同与集成路径。

## V0.1 已实现

1. 不可变水质、Detection、规则、证据、Runtime 与 AnalysisResult 合同。
2. 数据有效性 `valid`、`partial`、`invalid` 与新鲜度 `fresh`、`stale` 分开表示；可配置 `stale_after_s`，可表达 `partial + stale`。
3. 正常、低溶氧、部分缺失、过期、部分缺失且过期水质，以及正常/数量变化检测的固定 Mock 数据。
4. 单一 `DiagnosisService`，参考生产阈值输出结构化 `RuleFinding`。每个指标只输出最严重的一条阈值结果；这是相对生产 `get_alarms()` 可叠加告警的有意收敛。
5. 打包在 Python 包内的生产知识 JSON 只读快照及 31 个稳定知识块 ID。快照来源见 [SOURCE.md](src/fishery_ai/resources/knowledge/SOURCE.md)。
6. 可离线运行的纯 Python `char_wb` TF-IDF 基线，使用 2–4 gram、最多 2,000 特征、查询扩展、关键词加分、0.04 门槛。也提供可选 scikit-learn 后端；该后端缺少 scikit-learn 时按生产行为降级到关键词检索。纯 Python 与 scikit-learn 的边缘分数可能不同，尚未做逐项等价验证。
7. Cloud/Local OpenAI 兼容 Profile、请求开始时冻结的 Runtime、Mock Gateway 和基于官方 OpenAI Python SDK 的适配器。默认 CLI 只用 Mock Gateway。
8. 固定 Chat/Advice 编排。两种模式共用当前水质快照、确定性规则和证据，使用不同任务意图；历史与 Detection 不进入默认提示词。
9. 分离观察事实、规则、证据、推论、建议、不确定性、Runtime 和 Usage 的 `AnalysisResult`。`ObservedFacts` 为水质与可选 Detection Summary 留出扩展点。支持纯 JSON 和完整 Markdown JSON 代码块；解析失败时保留原文并标记。
10. 只记录允许字段的 JSONL trace；不记录 Key、完整 Profile、完整提示词或模型正文。

## V0.1 范围外

- 真实 Cloud API 调用、下载或启动本地模型、生产项目适配器、传感器历史输入、YOLO 接入。
- Tool Calling: planned for V0.2
- Agent Loop: not implemented
- Fine-tuning: pending task definition and additional data

## V0.1.1-A1：多模型参数与 Usage 合同

- Profile 分开记录部署位置（原 `provider_kind`）、`adapter_id`、`provider_id` 与精确模型；状态为 `verified`、`experimental` 或 `custom`。当前没有真实 VERIFIED 预设。示例 `cloud-demo` 为 EXPERIMENTAL，`local-demo` 为 CUSTOM，均未经过本项目真实 API 验证。
- `GenerationOptions` 的输出上限、temperature、top_p 默认均不发送；`ReasoningOptions.AUTO` 不强制开关。显式高级参数遇未知或不支持能力会在发送前失败，冲突组合也不会静默删改。Capability 声明绑定 Base URL 与精确模型；修改模型或地址不能继承旧声明。
- 通用自定义 `generic_openai_chat` 默认只发送 `model/messages`；有证据的字段由同一个 `OpenAICompatibleAdapter` 翻译。DeepSeek/Qwen 的思考开关仅在相应 Provider 身份且精确模型 Capability 允许时映射，当前示例均未声明其已验证可用。
- 每请求 `AnalysisResult.usage` 显示 Provider 返回的输入、输出、总 Token 与可选思考/缓存 Token。缺失用 `unavailable` 表示，不伪造为 0。离线 CLI 同时显示一次请求和当前验证会话累计；累计仅驻留内存，不是对话 Memory。没有费用估算或跨 Provider 自动故障切换。

实现范围、风险与待验证资料见 [V0.1.1-A1 实施报告](docs/deep-dive/V0.1.1_A1_MULTI_MODEL_IMPLEMENTATION_REPORT.md)。

## Profile 与 Secret

离线示例位于 `src/fishery_ai/resources/mock/profiles.json`。`cloud-demo` 使用远程 OpenAI 兼容 URL，仅保存 `secret_env: DEEPSEEK_API_KEY` 引用；`local-demo` 使用 `http://localhost:11434/v1`，Key 可为空，模型名是待替换占位符。这个文件是 Mock 演示输入，不是 VERIFIED 预设列表。默认超时为 connect 5 秒、read/stream idle 30 秒、total 120 秒，最多重试一次。仅在尚未输出正文且错误可重试时重试。

**Mock Demo 会选择并冻结相应 Profile，但始终由 Mock Gateway 生成回答。** Demo 不解析真实 Secret，并显式拦截 socket 连接。真实 Adapter 已实现最小 OpenAI 兼容 `complete`/`stream`；SDK 仅在适配器中使用，其自动重试关闭，由 Gateway 控制重试边界。自动测试使用假 SDK 客户端。

## 运行离线测试

需要 Python 3.11 或更高版本。在项目根目录建立虚拟环境，并安装 `pyproject.toml` 中声明的运行依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

测试在导入原型代码之前拦截 `socket.connect`、`connect_ex`、`sendto` 和 `create_connection`。网络访问尝试会使测试失败。测试不会读取 `.env`、生产数据库或生产配置文件。

## 运行 Mock Demo

```powershell
.\.venv\Scripts\python.exe -B -m fishery_ai demo --profile cloud-demo --scenario low_oxygen --mode advice
.\.venv\Scripts\python.exe -B -m fishery_ai demo --profile local-demo --scenario partial_stale --mode chat --question "当前水质如何？"
```

可选场景：`normal`、`low_oxygen`、`partial`、`stale`、`partial_stale`。Demo 展示水质事实、规则、RAG 证据、Mock 生成结果、Runtime 和 Usage；Mock 不返回 Token 统计，因此各字段显示 `unavailable`。它会在当前工作目录的 `outputs/mock-traces.jsonl` 追加 trace，已安装后可从其他目录运行。Mock 输入固定，便于复现。工作区的 `outputs/` 被 `.gitignore` 忽略。

## 后续在 GPU 工作站验证本地模型

先在工作站独立安装并启动一个支持 OpenAI 兼容接口的本地服务，确认模型 ID 和 `/v1/chat/completions` 能力，再修改工作站上的本地 Profile 副本。应先以离线 Mock 测试确认路由，然后单独执行受控的真实连接验证，记录响应、首字延迟、总耗时和错误。不要将真实 Key 写进 Profile；Cloud Key 由环境变量解析。本轮没有做这一步。

## 知识来源与记录保留

知识 JSON 来自生产项目 commit `c400b7abf298d3f05e2b8859b51ceee6553b685d`。原始 JSON 没有逐块文献来源，因此 V0.1 使用 `legacy:eel_knowledge.json`，`source_title` 留空。不能将当前检索分数解释为医学或养殖结论的可信度。

Trace 默认保存在当前工作目录的 `outputs/`，V0.1 不自动清理。演示或评审后由使用者根据本地数据保留要求决定归档/删除；本轮不实现保留期限和自动清理。实现详情及风险见 [V0.1 实现报告](docs/deep-dive/V0.1_IMPLEMENTATION_REPORT.md) 与 [V0.1 工程加固报告](docs/deep-dive/V0.1_HARDENING_REPORT.md)。

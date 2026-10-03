# AI 编码助手工作说明

## 项目目的

本项目是智慧渔业 AI 架构原型，用于研究 LLM 集成、RAG、工具架构及 Agent 演进。当前 V0.1 采用固定的、可离线运行的分析流程。

## 架构原则

1. 确定性事实来自程序和数据源。
2. LLM 负责推理、解释和自然语言交互。
3. 不允许 LLM 编造传感器数值、检测结果或数据库事实。
4. 将 RAG、Tools、Memory、Database 和 Agent 作为不同概念处理。
5. 没有具体需求时，不引入框架。

## 当前接入与后续边界

- 当前源码 > 当前文档 > 历史报告；先查 `docs/README.md`，不从归档恢复旧模型资产或能力。
- Preset 使用开发者发布的固定合同，运行时 Evidence / Metadata / Probe 不改合同。
- Managed Custom：R3 ProtocolSpec 只编码参数；R4 Resolver 解释精确 service/adapter/URL/model 的证据；R5 仅做显式单项 Probe。UNKNOWN 不等于 UNSUPPORTED，网络失败不写否定证据。
- Manual V1 使用 Saved Connection，V2 使用独立 Experiment；Raw 请求不经 Capability、Runtime Defaults 或 Fishery Analysis，不执行返回的 tool_calls。
- Provider 参数仅在协议/Adapter 边界翻译。RuntimeSnapshot / CredentialSnapshot 在请求开始时冻结。
- 正式凭据优先级为 PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING，外部进程变量只读，Profile 只引用 credential_ref；Auth NONE 不要求 Key。Manual V2 独立使用私有 `manual.env`，不混入正式凭据或进程 Key。
- 真实网络验证仅在用户明确授权后按次数、retry 与费用约束执行；自动测试始终离线，不从历史授权自动续测。Secret 不进入 Profile、Experiment、Evidence、LocalStorage 或其他输出。
- Tool Calling 第一阶段只读，读取 canonical Domain 数据，不直接解释硬件 packet；当前尚未实现 Tool Calling / Agent。Agent 不得直接操作硬件、执行 DB mutation 或修改阈值，后续实现须另行授权。

## 开发规则

- 重大修改前，说明原因、指出受影响模块，并更新文档。
- Windows 路径中的 `_` 是普通字符；文件操作优先使用 PowerShell `-LiteralPath`。
- 不得修改 `D:\Fishery_Project`；它仅是只读参考。
- 不得提交密钥或本地模型文件。
- 旧根目录 `.env` 含本地 Secret，继续保持 Git ignored，不得提交或自动读取/迁移/删除。Web 与真实验证入口的受管凭据改用启动边界确定的用户私有、每项目固定路径；CredentialStore 只读解析，仅允许受控 ProjectEnvWriter 在显式用户操作、路径/权限/并发/Web 安全检查通过后写入所选私有存储。不得用 load_dotenv 污染全局 os.environ。开发与自动测试只使用临时文件和虚构值，不读取或修改任何真实凭据。
- 不得打印、检查或记录 Secret 值及其片段；仅可报告必需环境变量是否存在。Secret 不得写入日志、Trace、文档、错误或测试输出。
- 不得增加未使用的抽象或不必要的空模块。

## 测试规则

- 每次修改都应保持离线测试可用。
- 测试不得调用真实 API。
- 新行为应增加相应测试。

## 文档语言

- 新增或更新的项目文档使用中文；代码标识符、协议名称和命令可保留原文。

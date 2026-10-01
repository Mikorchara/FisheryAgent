# Provider / Credential 渐进重构 R0–R1

日期：2026-10-02。实施范围：R0 Compatibility Baseline、R1 ProviderRegistry 与只读 CredentialStore。

## 实施边界

本轮不实施 `.env` Writer、Credential CRUD、协议参数迁移、Evidence Resolver、未知模型 Thinking Probe、Cancellation、Manual Mode 或 Tool Calling。正式项目保持只读。

主要改动模块：Provider/Auth 定义、Credential 解析、RuntimeSnapshot、启动入口及 Web 凭据状态。现有 RAG、Grounding、Domain Rule、Capability gate 与 Adapter 请求体保持一致。

## Checkpoint

- 基线：Python 139 项、Browser 28 项通过，JS syntax 与 Git diff 检查通过。
- 用户明确批准了受控 Secret 风险扫描：不读取项目 `.env`，不输出匹配值。
- 当前跟踪文件 81 个、待推送历史 blob 175 个；未发现扫描规则命中的风险或敏感路径。
- `.env`、`outputs/`、真实验证记录被 Git 忽略且未被跟踪。
- `docs/CODE_REVIEW.md` 已在此前提交中，本轮没有独立修改；内容为空白评审模板，不需要额外提交。
- Checkpoint：`0d55cbc`，`feat: complete cloud capability validation baseline`；已 push 到现有 main，未创建或移动 tag。

## R0 兼容保护

从 checkpoint 捕获包内 4 个 Profile 的公开信息和 16 组 Adapter 请求体。新增离线保护覆盖旧身份字段、Custom JSON、Secret Env 引用、运行默认值、USER_VERIFIED 与官方证据共存、Identity 隔离、公开 RuntimeInfo 及 Local 行为。

基线文件：`tests/fixtures/r0_runtime_baseline.json`；测试：`tests/test_credential_compatibility.py`。公开 DTO 对旧字段逐项比较，允许追加 AuthSpec / credential_ref；`RuntimeInfo` 保持原合同。请求体比较覆盖 Normal/Streaming、Thinking AUTO/ON/OFF、DeepSeek Effort，Ollama 只覆盖原来允许的 Normal 路径，不绕过 UNKNOWN Streaming gate。

## 1. 原 Credential 路径

原 Web 启动、真实验证入口与验证脚本使用 `load_dotenv(override=False)`，将项目文件导入进程全局环境。`ProfileRegistry.snapshot()` 再从 `os.environ` 取值；Web 使用另一段环境检查作为请求前置校验。文件值进入旧进程后，无法区分最初的文件来源与外部环境来源，修改文件也不会即时替换旧值。

本轮只替换 Credential 获取路径和相关认证状态展示。Adapter 请求参数、Thinking/Streaming 映射、Retry policy、Parser、RAG、Grounding、Domain Rules 和 Orchestrator 业务流程未修改。

## 2. 新 ProviderRegistry

`src/fishery_ai/providers.py` 提供静态、不可变 `ProviderSpec` 和小型 Registry，无插件、在线 Discovery 或注册服务。

| service_id | adapter_id | protocol_spec_id | 默认 AuthSpec | 默认凭据名 |
|---|---|---|---|---|
| dashscope | openai_chat | dashscope_chat | REQUIRED_BEARER | DASHSCOPE_API_KEY |
| deepseek_api | openai_chat | deepseek_chat | REQUIRED_BEARER | DEEPSEEK_API_KEY |
| ollama | generic_openai_chat | ollama_openai_chat | NONE | 无 |
| generic_openai | generic_openai_chat | generic_openai_chat | OPTIONAL_BEARER | 无 |

ProviderSpec 还包含 display_name、default_base_url、metadata_method、default_deployment。Generic 的默认 URL 为空。Web config 返回安全 Provider 元数据；Provider 注册不检查任何 Credential。

`protocol_spec_id` 本轮只是引用，尚未迁移参数映射。旧 `custom` 只在 Registry 查询时兼容到 generic 描述，Profile 本身的 service_id 与 Capability Identity 不被重写。Provider 默认值不会强行覆盖旧 Local Custom Profile 的认证引用；新 Custom 仍由连接配置决定 AuthSpec。

## 3. AuthSpec

| 类型 | 行为 |
|---|---|
| NONE | 不查 Process / Project Credential；返回 NONE_REQUIRED |
| REQUIRED_BEARER | 必须有可用凭据；缺失时 SECRET_MISSING，传输不启动 |
| OPTIONAL_BEARER | 可带凭据，也可无凭据执行兼容请求 |

AuthSpec 与 Cloud / Local 分开；ENV_SECRET 只是凭据来源。旧 Profile 无 AuthSpec 时按兼容规则处理：已配置引用或 Cloud 使用 REQUIRED_BEARER，其他使用 OPTIONAL_BEARER。不会根据 Local 推断 NONE。

## 4. 只读 CredentialStore

`src/fishery_ai/credentials.py` 提供 `resolve(ref, auth_spec)` 和 `status(ref, auth_spec)`。启动入口固定项目 `.env` 路径，Store 只读、不自动搜索其他文件、不写文件、不缓存值、不更新 `os.environ`。默认构造不读取项目文件；Web 启动和显式真实验证入口显式注入路径。

项目文件按 UTF-8（兼容 BOM / CRLF）读取，用 `dotenv_values(interpolate=False)` 解析。解析前检查格式，防止 parser warning 输出原始行。缺失文件视为 Missing；权限、编码或格式错误返回固定 `CREDENTIAL_FILE_ERROR`，不附加原始异常或文件内容。

## 5. Process / Project 优先级

| 条件 | availability | source | editable |
|---|---|---|---|
| Process 变量存在且非空 | PRESENT | PROCESS_ENV | false |
| Process 变量存在但为空 | MISSING | PROCESS_ENV | false |
| Process 不存在、文件变量非空 | PRESENT | PROJECT_ENV | true |
| Process 不存在、文件变量为空 | MISSING | PROJECT_ENV | true |
| 两处均无变量或没有配置引用 | MISSING | MISSING | true |
| auth=NONE | NONE_REQUIRED | NONE_REQUIRED | false |

空 Process 变量明确阻断文件回退。`editable=true` 只描述未来 R2 的来源归属，本轮没有写 API。显式传入旧 `environ={}` 的离线调用只查该映射，绝不回退真实项目文件。

## 6. Hot Reload

每次 resolve 重新解析项目文件，不引入 mtime cache、watcher 或后台线程。新请求获取新的 CredentialSnapshot；运行中的请求继续使用原快照。

Web 的请求前置校验和 Orchestrator / Adapter 共用同一 RuntimeSnapshot，不再次从环境取值；Normal、Streaming、Probe 已用离线计数测试确认单次 resolve。独立状态查询反映查询时的状态，不能保证以后所有请求都使用该时刻值。

**从旧实现升级时应正常重启应用一次**，结束旧 `load_dotenv` 导入的环境状态。此后修改文件无需重启。真正外部 Process Environment 仍优先于文件，文件热读取不会覆盖外部变量。

## 7. CredentialSnapshot

CredentialSnapshot 是不可变的私有对象，使用 slots 保存内部 Secret 与安全 CredentialStatus。repr / str 为固定脱敏内容，拒绝 deepcopy、pickle、通用 JSON 与 `asdict` 导出。RuntimeSnapshot 的凭据字段不参与 repr / compare；对整个 RuntimeSnapshot 使用 `asdict` 会明确失败。

公共序列化继续只使用 `runtime.public_info()`，`RuntimeInfo` 没有新增 Secret 或来源字段。兼容内部 `runtime.api_key` 只读 accessor；Adapter 改为从私有 CredentialSnapshot 获取值。Python 对象并非加密容器，进程内代码仍需遵守私有边界；未实现 Key vault 或内存清零。

## 8. Built-in Ollama NONE

包内 `ollama_qwen35_local.json` 明确配置 `auth_spec: NONE`。Built-in loopback Ollama 不查任一 Credential 来源，不要求 Key；页面即时隐藏 Secret 输入与状态，基础配置仍只读。

SDK 所需 `local-no-key` 占位只由 Adapter 在构造客户端时设置，不进入 Profile、CredentialSnapshot、Web DTO、Trace 或 Evidence。旧 Local Custom 已配置的 `secret_env` 原样保留，不自动改成 NONE。

## 9. Web Credential Status

`POST /api/secret-status` 支持精确 profile_id，兼容旧 secret_env；返回变量名、availability、source、editable 和旧 status 别名。编辑草稿使用同样 Store 语义和显式 AuthSpec。

页面显示：`PRESENT · PROJECT_ENV · 未来可编辑（本轮只读）` 或 `PRESENT/MISSING · PROCESS_ENV · 外部只读`。不显示 Key 值、长度、片段、Hash 或 Fingerprint。切换 Profile 时旧异步状态不能覆盖新配置。AuthSpec 变更会使旧连接测试结果失效；连接字段 Fingerprint 只包含配置字段，不包含凭据。

没有 Set/Replace/Delete Key 按钮；没有 Credential CRUD API。原 Custom Profile 配置管理保留，只保存引用和 AuthSpec，不保存 Secret。

## 10. Secret 安全措施

- 所有 Credential 离线测试只读取临时 `.env`，使用虚构值；测试额外拦截真实项目 `.env` 读取和 socket。
- RuntimeInfo、Profile / Capability DTO、Evidence、Web JSON、Normal/Streaming 结果、JSONL Trace 均由测试确认不包含虚构 Secret。
- CredentialSnapshot 与 RuntimeSnapshot 的 repr、str、通用序列化路径有明确防护。
- 文件错误、SDK 错误使用安全错误码，不返回原始行、Authorization 或敏感异常。
- 启动不再导入文件内容到全局环境；模型请求、诊断、Metadata、Probe 使用同一个 CredentialStore 语义。
- Git checkpoint 前按用户授权扫描跟踪文件与待推送历史，未读取 `.env`；扫描范围与结果见 Checkpoint 小节。规则未命中不等于绝对安全证明。

## 11. 向后兼容

旧 `provider_id`、`service_id`、adapter_id、`secret_env`、旧 Custom JSON 继续读取；新 `credential_ref` 与 legacy 名称一致时接受，不一致时拒绝。加载旧文件不自动重写磁盘。

Runtime Defaults 和 Capability Evidence 未改变语义。Credential 缺失不删除 Provider、Profile、Capability、Evidence 或偏好。已有 profile_id 保持不变，包括历史 DeepSeek Profile ID。

唯一有意统一的 Credential 错误名称为 `SECRET_MISSING`，替代 Adapter 原来的 `SECRET_UNAVAILABLE`；Web 仍保留旧错误名称兼容转换。Cloud transport 的旧 Mock 测试补上虚构认证引用，未放宽 REQUIRED_BEARER gate。

## 12. Targeted tests

新增 R0 Python 6 项（含 16 组请求体 subtest）、R1 Python 27 项、Browser Credential 5 项均通过。还定向复核基础 Adapter 21 项、多模型合同 20 项、Cloud Capability 21 项、Profile Manager 8 项、真实入口 Mock 4 项、输出一致性 Mock 5 项；Profile 切换等 Browser 9 项定向子集通过。

开发期命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p 'test_credential*.py' -v
node --test --test-name-pattern='Credential|Auth requirements|Built-in Ollama auth' tests/test_browser_streaming.cjs
```

一次 Probe fixture 最初触发 409，是已验证 Built-in 要求显式 reverify 的正常保护；测试补齐 reverify=true 后通过，未改变门禁。一次旧 Cloud 假 SDK fixture 缺少凭据被新认证规则阻止，补上虚构凭据后通过。

## 13. Full regression

| 检查 | 命令 | 最终结果 |
|---|---|---|
| Python | `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests` | **172 项通过**，约 4.07 秒 |
| Browser / JavaScript | `node --test tests/test_browser_streaming.cjs` | **33 项通过** |
| JS syntax | `node --check src/fishery_ai/resources/web/app.js` | 通过 |
| Git diff 格式 | `git diff --check` | 通过，仅 Git LF/CRLF 提示 |

完整 Python 首次有 1 项旧 UI 文案断言失败，仍要求“Cloud 必填”。根据独立 AuthSpec 更新为“认证必填”并确认 Auth 控件后，相关 9 项和完整 172 项重新通过。没有为修复断言改动 Grounding 或认证 gate。Browser 完整回归一次通过，未反复重跑。

对比 checkpoint：Python 139 → 172（新增 R0 6、R1 27）；Browser 28 → 33（新增 Credential 5）。所有真实模型请求均在最终离线回归通过后执行，未进入自动测试。

## 14. 真实验证请求

日期：2026-10-02（Asia/Shanghai）；原始记录使用 UTC。用户授权的 **Cloud 2 次 + Ollama 1 次**全部执行，SDK / Gateway retries 均为 0。使用现有精确 Profile、CredentialStore、ModelGateway / Adapter / OpenAI SDK，以“只回复 OK”作最小输入；未执行 Fishery 长 Prompt 或 Thinking 性能测试。

| 请求 | 凭据状态 / 来源 | 结果 | 延迟 ms | TTFT ms | Input / Output / Total |
|---|---|---|---:|---:|---|
| qwen-plus Normal，AUTO | PRESENT / PROJECT_ENV | 成功，返回 qwen-plus | 3828 | 不适用 | 11 / 1 / 12 |
| qwen-plus Streaming，AUTO | PRESENT / PROJECT_ENV | 成功，收到 1 个正文 delta | 1063 | 1031 | 11 / 1 / 12 |
| Ollama qwen3.5:4b Normal，OFF | NONE_REQUIRED / NONE_REQUIRED | 成功，返回 qwen3.5:4b | 6829 | 不适用 | 15 / 2 / 17 |

Usage 由 Provider 返回，cached input tokens 都为 0；reasoning tokens 未提供，保留 unavailable。Streaming 的现有 ModelEvent 不包含返回模型字段，所以不从请求模型伪造 returned_model。每项 request_attempts=1，Cloud 总计 24 tokens；未修改 `.env` 或 `os.environ`，未增加请求、更新 Capability Evidence 或调整代理 / SDK / HTTPX。

真实记录只包含安全元数据、Usage、凭据来源、计数与耗时，以 UTF-8 写到已 Git ignored 的：

- `outputs/credential-r1-qwen-normal-a1fed578.json`
- `outputs/credential-r1-qwen-streaming-07330450.json`
- `outputs/credential-r1-ollama-normal-1c2f4745.json`

不保存或输出 Key、Header、模型正文、完整 Prompt。Hot Reload 的凭据轮换在临时文件离线测试中验证，真实项目 `.env` 没有为此修改。

## 主要文件变更

| 范围 | 文件 |
|---|---|
| 新增运行模块 | `src/fishery_ai/providers.py`、`src/fishery_ai/credentials.py` |
| Credential / Runtime 集成 | `model_gateway.py`、`openai_compatible_adapter.py`、`web.py`、`capability_probe.py`、`custom_profiles.py` |
| 启动与验证入口 | `real_validation.py`、3 个既有 Qwen 验证脚本 |
| 包内明确认证配置 | `resources/profiles/ollama_qwen35_local.json` |
| 页面与状态展示 | `resources/web/app.js`、`resources/web/index.html` |
| 新增兼容与安全测试 | `tests/test_credential_compatibility.py`、`tests/test_credentials.py`、`tests/fixtures/r0_runtime_baseline.json` |
| 原测试兼容更新 | Browser 测试与 Cloud / UI / CLI Mock tests 的断言、虚构认证和启动 stub |
| 文档 | 本报告、README、BUILD_RUN、deep-dive 导航、AGENTS 凭据规则 |

RAG、application.py、Domain Rules、CapabilityValidator、协议映射与 Parser 源码未改变。所有新增/修改均在 Prototype 工作区；正式项目未修改。

## 15. 尚未实施 R2–R7 / 风险

- R2：`.env` Writer、Credential CRUD、Key 编辑 UI、CSRF Writer 均未实施。
- R3：ProtocolSpec 参数迁移未实施，当前 protocol_spec_id 只是引用。
- R4：Evidence Resolver / 冲突裁决未实施。
- R5：Unknown Model Thinking Probe 未扩展。
- R6：Cancellation 未实施。
- R7：Manual Mode 未实施。
- Tool Calling 未实施；正式项目未修改；本轮 refactor 尚未 commit / push。

R2 前需要处理安全写入、受限路径 / 文件权限、并发和原子替换、外部环境只读拒绝、CSRF / Origin 校验与失败回滚。当前连接测试 token 没有 Credential revision：凭据旋转后旧测试可能仍在 TTL 内有效，R2 需明确失效策略。只读 Store 的文件内容格式错误会阻止相关新请求，应保持固定安全错误，避免为排错回显原始内容。保留的 api_key accessor 应继续收窄内部使用；禁止改用通用 RuntimeSnapshot 序列化。

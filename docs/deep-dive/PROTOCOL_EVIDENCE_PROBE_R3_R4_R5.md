# R3 / R4 / R5 分阶段实施报告

日期：2026-10-02。起点：`62bf8451b09b2361252d6bb7c633c8e9c0b7026a`，main 工作树干净。

## 0. Credential UI 审计（完成）

现有入口完整，不重做 R2。操作：选择 **Managed Custom → 新建 → Provider**，填写连接、唯一名称和 `secret_env`（即 `credential_ref`）；展开 **本地凭据管理** 并刷新状态。MISSING 可“设置 Key”，用户私有 PROJECT_ENV 可替换/删除，PROCESS_ENV 只读，NONE 不要求凭据。尚未保存连接也可以设置 Key，查询模型前无需先成功测试连接；草稿状态查询允许暂未填写 Model。

密码框只接收新值，提交前清空，不返回已有值；认证变更使旧模型列表/连接测试授权失效。只引用凭据名，存储仍为 PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING。未读取真实凭据、源码根 `.env` 或正式项目。

定向验证：Python `test_credentials*.py` **72 通过**；Browser `Credential|R2` **12 通过**。

## 1. R3 ProtocolSpec（完成）

新增小型不可变 `ProtocolSpec`，沿用 ProviderRegistry 已有 `protocol_spec_id`。Adapter 校验能力后才调用协议编码；AUTO 不发送开关，ON/OFF 按已存在的精确模型映射，Streaming / include_usage / token 字段 / effort 编码集中管理。RuntimeSnapshot 的协议视图只由冻结连接决定，不读取文件或 Evidence。

`ModelCapabilities.max_tokens_field` 保留为 **废弃的历史编码兼容字段**，不再作为“支持 token 上限”的条件。新合同可以分别表达能力与协议；旧 `max_completion_tokens` 请求体仍保留。不改 SDK 传输、Cancellation、Manual Raw 或 R2。

本阶段不扩大 Thinking 映射模型范围。定向：`test_protocol_specs.py` 3、`test_credential_compatibility.py` 6、`test_cloud_capability.py` 21、`test_ollama_reasoning.py` 7、`test_preset.py` 4，共 **41 通过**。其中矩阵覆盖 5 个已有精确模型 × AUTO/ON/OFF × Normal/Streaming；历史 golden body 原样通过。

## 2. R4 Evidence Resolver

**IMPLEMENTED / TESTED**。原 Store 按顺序覆盖官方/Metadata/Probe，相反证据缺少解释；旧实现也可能让已经解析过的 Profile 再成为“新证据”。

新增 `CapabilityIdentity`、`CapabilityEvidence` 与小型纯函数 Resolver：

- 精确 `service_id + adapter_id + normalized base_url + exact model`，不使用名称、family 或相似 URL。
- 原始项目声明保存在 `capability_basis`；解析视图与原始声明分开，不把上次结果当新证据。
- 收集项目精确声明、既有官方声明表、本地 Metadata 与 Probe。每条含 source、status、observed_at、origin；历史记录无时间就显示“时间未记录”，不补造日期。
- 同一项结论一致 → SUPPORTED 或 UNSUPPORTED；无证据 → UNKNOWN；状态、默认 Thinking 或 Effort 值相反 → UNKNOWN + `EVIDENCE_CONFLICT`。来源优先级仅用于主来源展示，不用于覆盖相反事实。
- 规范文件和 trailing-slash legacy 文件都参与合并，文件名优先级不再隐藏冲突。原当前 Probe 文件仍按每项替换，未新增全历史数据库或自动过期系统。
- `CapabilityStore.apply()`、官方兼容 helper、`ProfileRegistry.from_json()` 使用同一 Resolver。Web 加载、创建/编辑连接、Probe 完成时解析，正式请求冻结当前有效视图；不在每个请求中自动查询服务。
- Preset 合同与 Mock 固定离线合同直接返回，Store 拒绝写入 Preset。Runtime Defaults 保留偏好，冲突/未知时安全回退。
- UI 展示来源、时间与冲突原因，保留 UNKNOWN 下拉锁定。Probe 请求成功不等于 Resolver 一定得到 SUPPORTED。

阶段初版定向 **43 项**（8 Resolver + 21 Cloud + 8 Local UI + 6 compatibility）；更改两处兼容测试：旧“Metadata 被拒绝结果直接覆盖”改为冲突 UNKNOWN，公开 JSON golden 允许新增证据字段、仍逐层冻结原字段和所有请求体。

进入 R5 前：full Python **291 通过（12.436 秒）**，Browser **63 通过**，JS syntax / diff check 通过。最终审计补充 JSON 统一入口、Mock UI 合同及 legacy 同身份冲突覆盖后，Resolver 定向为 **12 项**；完整回归结果见下表。

## 3. R5 Unknown Model Probe

**IMPLEMENTED / TESTED**。复用原显式 Probe 服务/API/UI，不建立第二套探测系统，不自动扫描能力。

- UNKNOWN Streaming 可显式 Probe；DashScope / DeepSeek 使用 R3 已有服务协议的 Thinking 开关，未知 exact model 不再被模型白名单阻断。精确 Omni 特例保留，协议可编码不代表模型支持。
- Generic 服务未知 Thinking 编码不猜测；Ollama 保留已存在的 `qwen3.5:4b` 映射，其他未知模型只开放 Streaming Probe。无安全编码时返回 `CAPABILITY_PROBE_UNSUPPORTED`，基础 Normal + AUTO 仍可运行。
- ON / OFF 独立，一次只写被验证项；原 Streaming + Thinking 组合 Probe 保留，并继续要求独立支持作为前置条件。
- 显式 `REAL NETWORK REQUEST` 确认后仅一个最短请求，SDK 与 Gateway retry=0；不运行 Analysis/RAG/Diagnosis，不执行 tool_calls。临时绕过仅存在于 Probe 的 Runtime 副本，不改业务门禁。
- Probe 的 read timeout 至多 30 秒、total 至多 60 秒；不改变 Profile、业务 timeout 或在途 CredentialSnapshot。token 上限已确认支持时限制 64；上限 UNKNOWN 时不擅自绕过另一项能力或发送该字段。
- Streaming 必须收到非空 content delta 并正常结束；只收到 reasoning/usage 不算成功。记录计数、TTFT、耗时、Usage，不保存正文或 reasoning trace。
- 明确参数拒绝可写 UNSUPPORTED Evidence；网络/TLS/代理/timeout、普通 HTTP 错误、空响应/流中断不写否定证据。已有证据不因网络失败被删除，无证据的项保持 UNKNOWN。
- 成功/明确拒绝先写原 Evidence 格式，再由 R4 解析。页面重读精确 Profile，立即解锁或显示冲突；不再因单次请求成功就硬写“能力 SUPPORTED”。

R5 Python 定向 **9 项**（未知精确模型、独立 ON/OFF、普通 gate、Generic/Ollama 保守边界、显式确认、网络/HTTP 错误、delta、精确持久化、临时虚构凭据脱敏）；兼容 Cloud 21、Identity 6、Protocol 3 通过。Browser 定向 `R4|R5|Thinking Probe|Streaming Probe|combination Probe` **11 通过**，含新增 3 项。

## 4. 最终数据流与三模式边界

```text
Managed Connection 的精确 Identity
  → 项目声明 / Official / Metadata / Probe Evidence
  → R4 Resolver 的有效视图
  → Runtime Defaults 安全回退 + 本次显式选项
  → 不可变 RuntimeSnapshot / CredentialSnapshot
  → CapabilityValidator
  → R3 ProtocolSpec 编码（Adapter 边界）
  → 现有 SDK / Gateway

UNKNOWN → 用户显式 R5 Probe → 单项 Evidence → R4 重算 → UI 更新
```

Preset：固定发布合同 → 同一 Gateway / ProtocolSpec / 传输，Resolver 不改合同。

Manual Expert V1：独立 Raw request → 原传输/安全/Credential/Stop；不进入 Resolver、Probe、ProtocolSpec.encode、默认值注入或 Fishery Analysis。没有实施 Manual Experiment V2。

R2 路径与优先级、CredentialStore/Writer、Flask dotenv 禁用、Cancellation、RAG、Grounding、Domain Rule、Orchestrator 均未修改；未新增 Provider、Preset、Tool Calling 或 Structured Output 功能。

## 5. 最终回归与审查

| 检查 | 命令 | 结果 |
|---|---|---|
| Python | `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q` | **304 通过，12.046 秒** |
| Browser | `node --test tests/test_browser_streaming.cjs` | **66 通过** |
| JS syntax | `node --check src/fishery_ai/resources/web/app.js` | 通过 |
| Diff | `git -c core.safecrlf=false diff --check` | 通过 |
| 受控 Secret / 敏感路径扫描 | 仅 Git 跟踪与未忽略的公开源码/文档；不输出匹配值 | **116 文件，未发现规则内风险；4 个已确认虚构测试 fixture 排除** |

自动测试仅用临时文件、虚构 Secret 与 fake SDK/socket 禁网保护。本轮真实模型请求 **0**；没有安装依赖或读取/修改真实凭据、旧 `.env`、生产项目。

## 6. 剩余 UNKNOWN / 技术债

1. Generic 与未知 Ollama 模型的 Thinking 编码没有可靠映射，继续 UNKNOWN，不借模型名猜测。Generic Streaming 可单独显式验证。
2. Probe 成功只证明服务接受该请求并返回内容，不能排除服务静默忽略 Thinking 参数；ON/OFF 真实行为仍需 Metadata/模型行为人工核对。reasoning_content 缺失不能直接判定不支持。
3. 未确认 token 上限的模型不发送上限字段；即使 prompt 很短，Thinking 仍可能产生较多 Token，需人工确认预算。timeout 只控制客户端等待，不保证远端停止计费。
4. 官方精确记录延用现有已审阅资料，本轮没有新增联网研究结论。模型别名变化、证据过期、官方资料修订需维护者复审；不实现 TTL 或自动更新。
5. 相反证据保守锁定；即使 Probe 较新，也不自动覆盖官方/Metadata。需人工核对后修订相应来源；没有增加“强制相信用户”按钮或全历史清理 UI。
6. `max_tokens_field` 仅为 legacy 兼容保留；未来移除前需显式版本迁移，不能删除仍使用 `max_completion_tokens` 的旧配置。
7. 本地单进程 Profile 集合沿用现状；没有跨进程 Evidence 通知或复杂并发事务。当前同能力 Probe 文件保留最新一次结果，legacy 重复记录发生冲突时可见，不擅自删除。

## 7. 人工验证项目（本轮未执行）

1. Managed Custom 新建已知 Provider 的连接，引用缺失 credential；展开“本地凭据管理”设置新 Key，再查模型/测试/保存。确认只显示 PRESENT 和 source，不回显 Key。
2. 任意未收录模型先用 Normal + AUTO，确认没有高级字段；UNKNOWN 高级选项仍禁用。
3. 显式确认一次 Streaming Probe；检查 exact Identity、delta、TTFT、Usage、Evidence 时间、刷新后即时解锁；另一模型或另一服务不继承。
4. 对有协议映射的模型分别确认 Thinking ON / OFF，核对实际 API/模型行为而不只看 HTTP 成功；独立结果不能推导组合能力。
5. 网络失败不新增 UNSUPPORTED；冲突记录显示 UNKNOWN 和各来源，并临时回退安全运行选项。
6. Preset 不显示可写 Probe；Manual Raw 请求不被协议系统改写；Mock Streaming 能继续选择并完成。

## 8. 改动文件与 Git

新增：`protocol_specs.py`、`evidence_resolver.py`、3 个阶段测试文件和本报告。

修改：`model_gateway.py`、`model_options.py`、`openai_compatible_adapter.py`、`official_capabilities.py`、`capability_store.py`、`capability_probe.py`、`web.py`、Web `app.js`；Browser/Local UI/历史 compatibility 测试；BUILD_RUN 与 deep-dive 导航。

HEAD 保持 `62bf8451b09b2361252d6bb7c633c8e9c0b7026a`，**13 个 modified + 6 个 untracked**（均为上述源码、离线测试或中文文档），所有变更留在工作树供用户审查；**未 commit / push，未移动 tag**。

Git 公共文件清单没有 `.env`、`outputs/`、凭据目录、writer lock/staging 或模型权重。扫描只检查公开文件的常见 Key / 私钥 / Authorization 字面量与敏感路径，并非“证明任何形式 Secret 都不可能存在”；没有读取 ignored 内容或外部私有存储。冻结模块 diff 为空：R2 Store/path/Writer/权限/Web 安全，以及 application/knowledge/domain/execution/manual。最终源码差异已审阅，不存在源码根 `.env` fallback 或环境 mutation 的新增代码。

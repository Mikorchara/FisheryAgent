# Preset 小迁移、R6 Cancellation 与 R7 Manual Expert

> 文档分类：**HISTORICAL**。历史实施 / 验证记录；数字、限制与能力结论只对应当时版本，不是当前全局状态。 保留 Stop 后端 I/O 语义和 Manual V1 产品校正；首批旧 Preset 已被 Clean-room 替代。 当前边界见[架构总览](../../architecture/CURRENT_ARCHITECTURE.md)。

初次实施日期：2026-10-02。起点：`main` / `20744631dc627b48657ce19e6b62818bd064d67a`。第 1–9 节记录原实施轮次，当时不 commit / push；第 10 节是用户人工验收后追加的产品校正、架构审计与收尾授权，checkpoint 状态以该节及实际 Git 为准，v0.1 tag 不移动。

## 1. 范围与审计结论

**CODE-CONFIRMED**：原 Built-in 和 Custom 都通过本地 CapabilityStore 合入证据；同步 SDK Normal 调用不能可靠地通过 Flask 另一线程取消。原 ModelRequest 会合并默认值、校验能力，不适合作为 Manual passthrough。

本轮保留 R2 凭据架构、现有 Adapter 参数编码、Diagnosis、RAG、Grounding 与固定分析流程。只在应用传输调用前后增加取消检查，不改变分析业务。没有实施 R3 ProtocolSpec、R4 Resolver、R5 Unknown Model Probe、Tool Calling、Agent、生产项目修改。

## 2. Preset Template + Variant

`resources/profiles/presets.json` 保存模板、精确 identity、合同版本、维护依据与少量 Variant。连接引用原包内连接资源一次；Thinking Variant 不复制完整 Profile。`presets.py` 将其生成不可变 Profile / RuntimeSnapshot。精确连接变化会导致合同校验失败，不能静默继承。

| 模板 | 发布 Variant | 固定能力与依据 | 尚未发布 / UNKNOWN |
|---|---|---|---|
| Qwen Plus | OFF / ON / AUTO | A3.2.1 报告记录 2026-10-01 四组 ON/OFF × Normal/Streaming 实测；固定 Thinking、Streaming、组合及 Streaming Usage | Effort、采样、Tools、Structured Output 保持 UNKNOWN |
| DeepSeek Flash | AUTO + Normal | A2/A2.2 最小基础请求既有成功记录；默认 Thinking 使用现有官方记录 | 不发布 OFF / ON；Streaming 及高级能力 UNKNOWN |
| Ollama qwen3.5:4b | **未发布** | 保留 OFF 候选模板；已有 MODEL_METADATA 支持布尔开关，但本轮 API smoke 返回 HTTP_502 | 候选不出现在 Web Preset 分组；ON / Streaming 不发布 |

Qwen / Ollama 候选的输出上限字段固定为现有 `max_tokens`，依据下述官方兼容 API 文档，单独标记 OFFICIAL_DOCS。Qwen 默认 Thinking 依据官方记录，不把显式 ON/OFF 实测冒充默认行为验证。

- [阿里云 OpenAI 兼容 Chat API](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)，查询 2026-10-02；现有 max_tokens 仍可用，文档建议新接入采用 max_completion_tokens。本轮不改变已有编码。
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)，查询 2026-10-02；列出 max_tokens 和模型 metadata 驱动的 reasoning_effort。当前布尔模型 OFF 的既有编码保持 none。
- [DeepSeek Thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/)，沿用项目 2026-10-01 已审阅记录，仅作为固定默认行为依据；本轮未做新的 DeepSeek 请求。

**IMPLEMENTED**：Web 加载 Preset 时跳过 CapabilityStore；Probe / Metadata 不能改 Preset。Thinking 由 Variant 固定，Response Mode 独立；固定合同支持 Streaming 时仍可选择。显式覆盖 Variant 返回 PRESET_OPTION_LOCKED。AUTO 不发送开关，不等于 OFF。旧 Built-in ID 和 Managed Custom 行为保留，Builtin 仍为 EXPERIMENTAL，不因只读配置而升级为稳定模型。

RuntimeInfo 增加模式、Preset / Variant / 合同版本安全元数据；保留旧 R0/R2 字段和请求体基线。没有改动原 golden fixture，只增加兼容测试中的新字段断言。

## 3. R6 请求生命周期与真正的 I/O 取消

```text
页面登记 Request ID + 随机 control token（仅内存）
→ Normal / Streaming / Manual 执行绑定 RequestHandle
→ Adapter 的 AsyncOpenAI bridge
→ Stop 独立请求 cancel
→ 线程安全地取消 asyncio Task
→ finally 关闭 SDK stream + client
→ CANCELLED / USER_CANCELLED
```

RequestRegistry 是本地单进程注册表，最多 8 个活动请求，未执行登记 300 秒过期，终态保留数量有限。状态包括 RUNNING、CANCEL_REQUESTED、CANCELLED、COMPLETED、FAILED。控制接口使用既有 Host / Origin / CSRF 门禁，并要求匹配随机 control token；没有任意 credential path 或 Header 输入。

同步 Flask / Gateway 接口保留；仅有可取消 handle 的执行走 Adapter 内请求专属事件循环和异步 SDK。SDK retry=0，Managed 的 Gateway 原有重试规则保留：正文或 reasoning 输出后不重试，USER_CANCELLED 永不重试。无 handle 的历史 CLI / API 调用继续兼容同步路径，**不能凭空获得 Stop**；Web 新执行总是先登记。

Stop 先向后端发独立 cancel，再 Abort 浏览器读取，并查询后端状态。旧请求晚到的 Abort/error 回调不会覆盖取消确认，也不会清掉新请求。请求开始时的 CredentialSnapshot 不改变；R2 rotation 仅影响新请求。

| 路径 | 已实现 / 离线验证 | 本轮真实证据 |
|---|---|---|
| Normal | 取消被阻塞的 SDK await，关闭 client，USER_CANCELLED | Ollama 目标请求实际取消后 worker 结束、client 关闭；不能确认服务已开始生成 |
| Streaming | 取消阻塞读取，关闭 iterator / SDK stream / client；取消后的部分 JSON 不解析成最终结果 | 本轮未做真实 Cloud / Local Streaming cancellation |
| Cloud | 与 Local 共用同一异步传输和取消机制，假 transport 测试通过 | 私有凭据解析失败，真实 Cloud 请求未执行 |
| Local | AuthSpec.NONE 继续不要求凭据 | 目标端 HTTP_502，成功生成仍待用户环境验证 |

浏览器停止显示、后端 SDK I/O 关闭、远端停止计算是不同证据层。公开状态分别提供 backend_io_closed 与 remote_compute_stopped=unknown。**不声称云端已停止推理或计费；不声称 Ollama GPU 已停止计算。** 仅关闭标签页时，Normal 后端不能凭浏览器断开可靠获知取消，显式 Stop 才是保证路径；Streaming 断开在 WSGI 获知后关闭迭代器，等待中的读取仍可能受 timeout 约束。

## 4. R7 Manual Expert 边界

独立 `ManualRequest` / `ManualResponse` 与 `/api/manual`，使用顶部保存的 Cloud / Local 连接。页面显示 Service、Base URL、Model、Credential 引用；如需新连接，先用现有 Profile Manager 保存。第一版不开放临时任意 URL / Header / 凭据路径。

Manual 不调用 Orchestrator、Diagnosis、RAG、AnalysisResult、CapabilityValidator、Probe 或 Runtime Defaults；不写 Capability Evidence。ProfileRegistry 只复用相同凭据解析和不可变快照，显式跳过默认值解析。Adapter 用 SDK 的原始 JSON body 请求入口，不用 managed 参数翻译：不自动注入 Thinking、effort、include_usage 或 tools。SDK 不是字节级 HTTP 透传，Raw response 是 SDK 的 JSON 表示。

系统仍控制：固定保存的目标和 exact model、Credential / Authorization、连接与读取及总 timeout、retry=0、12 KiB 请求体与嵌套深度限制、取消和安全错误。禁止递归出现认证、URL、Header、SDK transport 配置类保留字段，因此首版也不支持包含这些保留名称的嵌套 schema / 多模态 URL。

返回的 tool_calls **只显示，不执行**。Normal 显示 Raw response / Usage / Latency；`stream:true` 逐个显示原始 chunk。正文不进入 Trace、Evidence、Profile 或 LocalStorage，不持久化请求模板。Raw 输出若回显当前凭据会被 Adapter 脱敏；请求和响应载体 repr 不包含正文。

## 5. R2 回归与安全审查

- CredentialStore、私有路径算法、Writer、ACL / revision / recovery、优先级与缓存失效架构均未修改。
- Web、validate-real、三个历史 Qwen 验证脚本仍为 PROCESS_ENV > user-private PROJECT_ENV > MISSING。
- 新受控脚本同样复用 private_project_location + CredentialStore，不读 root .env，不接受 credential path 参数。
- AuthSpec.NONE、Mock、请求快照、热读取继续通过离线测试；测试只用临时文件与虚构 Secret。
- 取消不会调用 Probe 或写入能力证据；HTTP_502 和 CredentialFileError 不转成 UNSUPPORTED。
- 本轮没有修改真实 Key、ACL、代理配置、正式项目，未自动迁移旧 .env。

## 6. 受控真实验证

首次入口在 Cloud snapshot 前失败；安全阶段检查确认为 CredentialFileError，**零 SDK 请求**。随后按同一授权预算执行，Cloud 仍安全跳过，其余 3 个目标请求各一次，retry=0。

| 场景 | 结果 | SDK attempts | 耗时 | Usage |
|---|---|---:|---:|---|
| Qwen OFF Cloud Preset | CREDENTIAL_FILE_ERROR / blocked | 0 | 未发请求 | unavailable |
| Ollama OFF 候选 | HTTP_502 | 1 | 3110 ms | unavailable |
| Ollama Thinking ON 后取消 | USER_CANCELLED，worker 已结束，SDK client 已关闭 | 1 | 1047 ms | unavailable |
| Ollama Manual OFF | HTTP_502；实际发出的 raw body 与用户模板相等 | 1 | 2109 ms | unavailable |

输出上限为 32；取消请求为 256。共 **3 次 SDK/HTTP 尝试**，没有成功 completion、没有 Provider Usage，不把未知 token 消耗写成 0。无法证明 502 来自 Ollama 而非本机路由/代理，也无法确认取消请求已进入模型计算；未改网络配置、未重复请求。未执行可选 Cloud Streaming cancellation。

安全记录位于 Git ignored 的 `outputs/access-modes-validation.json`，只含状态、计数、字段名、耗时和公开 Usage，不含完整 Prompt / Output / Credential。手动复测入口 `scripts/validate_access_modes.py --confirm-real-network` 每次最多四次生成尝试；无确认参数立即退出且不解析凭据。自动测试不执行真实入口。

## 7. 修改文件

- 新增：`presets.py`、`resources/profiles/presets.json`、`execution.py`、`manual.py`、`scripts/validate_access_modes.py`。
- 集成：`model_gateway.py`、`openai_compatible_adapter.py`、`application.py`（仅取消检查）、`contracts.py`（CANCELLED / 安全运行元数据）、`web.py`。
- UI：`resources/web/app.js`、`index.html`。未改 RAG / Grounding / 规则。
- 测试：新增 `test_preset.py`、`test_execution.py`、`test_access_web.py`；更新 Browser 与兼容测试中的新增元数据 / Preset 数量断言。
- 文档：本报告、BUILD_RUN、deep-dive 导航。

## 8. 测试结果

针对性 Python：Preset 4、取消/Manual transport 9、Web 7、受控入口 3；R2 credential targeted 118 项通过。Browser 新模式 / R6 / Manual 及旧 reasoning 请求 targeted 通过，新增晚到取消回调隔离测试通过。

Windows asyncio 内部 socketpair 是事件循环的唤醒机制；测试只允许 stdlib socketpair 范围内的本机连接，DNS、模型连接和其他 socket connect 继续禁止。曾发现内部通信被全网络 guard 拦截导致 loop startup 失败，现补安全退出测试；不以放开本地 LLM 网络解决测试。

| 最终检查 | 命令 / 范围 | 结果 |
|---|---|---|
| Python | `python -X utf8 -m unittest discover -s tests -q` | 280 项通过 |
| Browser | `node --test tests/test_browser_streaming.cjs` | 48 项通过；Node 内置 VM + DOM / fetch mocks，无真实 HTTP |
| JS syntax | `node --check src/fishery_ai/resources/web/app.js` | 通过 |
| diff check | `git diff --check` | 通过；Git 的 LF/CRLF 提示不是错误 |
| Secret / 敏感路径 | 108 个 Git 公共/未忽略新增文本文件；不读真实 .env、outputs 或外部私有文件 | 无风险命中；该扫描是特征检查，不是完整安全证明 |
| R2 冻结 | credentials / credential_paths / project_env / secure_files / web_security | 无修改 |
| Git | HEAD / tag / tracked paths | HEAD 仍为起始 checkpoint，v0.1 未动，Secret / outputs / lock / stage 未被跟踪 |

受控联网属于单独授权的人工 smoke，不纳入上述离线测试成功数量。未进行真实浏览器界面或 GPU 行为观察，不能以 DOM mocks 替代实际用户验收。

## 9. 已知风险与下一步

1. Cloud 真实 Preset / cancellation 仍需在能通过私有凭据安全校验的用户启动环境验收；不调整冻结 R2 来绕过。
2. Ollama OFF 真实生成和 Manual 成功结果仍待网络路径正常后人工验收；通过前不发布本地 Preset。
3. 云端账单与服务端计算没有停止证明；本地 GPU 行为未测量。
4. RequestRegistry 仅单进程，Flask 开发服务器不启用 reloader；多 worker / 多机取消不在本轮范围。
5. Provider alias 更新可能破坏固定合同，维护者需复验和升级版本；本地 Evidence 不自动改合同。
6. Manual 专家自行负责语义参数与费用。保留字段限制可能拒绝合法复杂请求，后续单独评审，不通过 allow_unknown 改 Managed。
7. 没有实施 R3/R4/R5、自动 failover、Tool Calling 或 Agent。当前实现不需要这些阶段才能安全工作，但真实模型成功验收仍未完成。

最终 `git status`：13 个已跟踪文件修改、10 个新增文件，共 23 个未提交条目；新增安全联网记录仍被 outputs/ 忽略。主要改动在上述清单，无正式项目修改。HEAD 保持 `20744631dc627b48657ce19e6b62818bd064d67a`，v0.1 保持 `5cc274021da44fdae198e6250be81023c185888e`。

工作树保留供用户审查；无 commit / push，tag 未移动。


## 10. Manual Expert 产品定义校正与架构兼容性审计

日期：2026-10-02。用户报告已完成当前 Preset / Managed Custom / Manual Expert UI 人工测试，已有功能基本正常（USER-VERIFIED）；不覆盖第 6 节历史失败记录，不把人工反馈扩大为所有模型 / 参数组合已验证。本轮无真实请求，无真实凭据读取或修改。

### A. 当前真实数据流（CODE-CONFIRMED）

```text
独立 Manual 页面：已保存 Connection/Target + Raw JSON
→ sendManual()：JSON 解析 + REAL NETWORK REQUEST 确认
→ /api/requests：登记 RequestHandle / control token
→ POST /api/manual：Host / Origin / CSRF / 16 KiB HTTP 请求限制
→ profiles[profile_id]：只取已保存目标，拒绝 Mock
→ request_runtime(manual=True)
   → ProfileRegistry.snapshot(apply_runtime_defaults=False)
   → CredentialStore.resolve(credential_ref, AuthSpec)
   → 不可变 RuntimeSnapshot / CredentialSnapshot，retry=0，清除 Preset 标记
→ ManualRequest.from_dict()：精确 model、一份 JSON body、12 KiB、深度 32、保留字段检查
→ request_scope(handle)
→ ModelGateway.manual_complete() / manual_stream()
→ OpenAICompatibleAdapter._bridge(manual=True)
   → AsyncOpenAI.post('/chat/completions', body=原请求语义, SDK max_retries=0)
   → 专属 SDK Task / timeout / finally 关闭 stream 与 client
→ _manual_response()：SDK model_dump、4 MiB 单响应/单 chunk 限制、当前 Credential 回显脱敏
→ ManualResponse：Raw + 可用 Usage
→ 普通 JSON 或 SSE raw_delta / completed / failed
→ 页面 textContent 显示 Raw、Usage、Latency
```

Stop 使用独立 `/api/requests/<id>/cancel`，取消 SDK Task 并关闭 I/O，再 Abort 浏览器读取；状态仍区分 backend_io_closed 和 remote_compute_stopped=unknown。Manual 的 Raw `stream` 决定请求路径，不读取隐藏的 Managed Response Mode。

代码依据：`web.py` 的 `request_runtime()` / `manual_execution()`；`model_gateway.py` 的 `ProfileRegistry.snapshot()`、`ModelGateway`；`manual.py` 的 `ManualRequest` / `ManualResponse`；`openai_compatible_adapter.py` 的 `_bridge()` / `_manual_response()` / `manual_complete()` / `manual_stream()`；`execution.py`；`resources/web/app.js` 的 `visibleProfiles()` / `updateManualTarget()` / `sendManual()` / `stopGeneration()`。

### B. 与 Managed Custom 的耦合分类

| 耦合点 | 分类 | 实际影响 / 未来处理 |
|---|---|---|
| 同一 CredentialStore、AuthSpec、CredentialSnapshot | 合理复用 | `resolve(ref, auth)` 不要求 Profile；未来独立实验可直接使用同一正式 Store，不改变文件路径或优先级 |
| 同一 SDK / timeout / 安全错误 / RequestHandle / Stop | 合理复用 | 传输只接收准备好的 Runtime 与 Raw request；不依赖 CustomProfileStore 或凭据文件位置 |
| Web endpoint 当前必需 profile_id，目标来自 profiles 字典 | 暂时可接受的 V1 耦合 | 是 V1 输入范围限制；将来在目标解析处增加实验来源，仍可兼容原 Saved Connection 调用，不是不可扩展的持久化合同 |
| RuntimeSnapshot 保留 capabilities、Profile ID、默认值等字段 | 暂时可接受的 V1 耦合 | 作为请求内连接快照使用；默认值解析已跳过，Adapter 的 Manual 分支不读 Capability；不把它作为 ManualExperiment schema |
| 同一验证台启动预加载 Profile / CapabilityStore、Diagnosis、KnowledgeService | 应用装配复用 / V1 耦合 | Manual 请求不执行这些服务，但共享 app 初始化仍会加载配置；未来独立来源可按需调整装配，不必现在拆独立 Web 服务 |
| Manual public_response 导入 application._public_data | 小型工具复用 | 仅序列化 Usage / RuntimeInfo，不调用 Orchestrator、结果解析或 Trace；未来若确有需要再移到通用序列化工具，不因此重构 |
| 前端通过 selectedProfile / manualTargetId 使用保存连接 | 局部 UI 耦合 | 将来只在目标选择/解析和发送 envelope 增加来源区分；Raw 编辑器、结果显示和 Stop 可保留 |
| SDK cast 到 ChatCompletion / ChatCompletionChunk | 当前协议范围限制 | 仅支持 OpenAI-compatible Chat Completions；未知 JSON 字段经 SDK 表示保留，不承诺任意协议、非对象 / 非 JSON 响应或字节级 Raw；未来协议/HTTP 元数据变化在传输边界处理 |

**INFERENCE：没有必须现在修复的结构 blocker。** “还不能填写临时 URL / 保存实验”是未实现功能，不等于已有结构使其无法实现。独立 Raw 请求、分离的执行方法、共享凭据与取消边界已提供局部扩展位置，不应现在引入 V2 类或空 Service。

### C. 独立 Manual Experiment 的可行性与最小未来方向

Manual Experiment 是独立实验资产，可有 id/name、独立 target/transport（provider/protocol、base_url、model、credential reference）、raw request 和必要创建/更新/说明信息。具体 schema、存储格式和目录尚不定案，本轮不创建 CRUD 或数据库。

当前 ManualRequest 只有不可变 JSON 字符串，**没有 profile_id 或持久化路径**；ManualResponse 不属于 AnalysisResult。V1 是由 Web 解析已保存目标，随后调用这对独立合同；并没有调用 CustomProfileStore 来保存 Raw 模板或实验。

未来增加 Saved Connection / Manual Experiment 两种目标来源，由准备边界解析受控 transport，固定 CredentialSnapshot / timeout，再复用同一 Raw 执行通道。不要通过把实验包装成 ModelProfile / 保存进 CustomProfileStore 来满足旧 profile_id 参数。不同协议真有需求时再调整 request/adapter 选择，不默认要求 R3/R4/R5，也不现在实现它们。

实验不自动出现在正式模型列表，不写 Capability Evidence / Runtime Defaults。实验成功不代表正式 Fishery 兼容；转换机制 **NOT DECIDED**。若以后实施临时 target，还须明确 URL/目标授权及凭据发送边界，仍不能接受任意凭据文件路径或认证 Header。

### D. Credential 复用与安全（CODE-CONFIRMED）

CredentialStore 只要求合法变量引用和 AuthSpec，不要求来自 Managed Profile；启动 composition 固定唯一用户私有文件。优先级仍为 PROCESS_ENV > user-private PROJECT_ENV > MISSING，AuthSpec.NONE 不读取凭据，外部 Process 只读。请求只保存开始时的 CredentialSnapshot，新请求 hot reload，在途请求不变。

当前 Manual 不写凭据、不接受 Secret/body credential 字段、不回显 Key；Raw 回显中的当前凭据会脱敏，Secret 不进 repr/Trace/Evidence/日志。反射其他未知 Secret 或用户把敏感数据放入任意文字字段并非通用可识别场景，未来实验持久化需另行明确内容安全检查；不能宣称现有字段限制能识别所有敏感字符串。

未来 Experiment 只保存 credential reference/identity，不保存真实 Key、Headers、credential path 或 private storage 内容；不增加 Secret 存储，不恢复源码根 .env。R2 架构、ACL、Writer、缓存失效、Host/Origin/CSRF 不变。

### E. Response / Cancellation 可复用范围

- **直接可复用**：Raw JSON 编辑与 ManualRequest 大小/结构保护、现有 OpenAI-compatible Manual complete/stream、SDK Task 的取消与资源关闭、Request ID / ownership token、safe error、Raw Response 的安全显示和 Usage/Latency。
- **当前限制**：body 必须为 Chat Completions 对象，messages 非空、model 与目标一致；保留名称检查递归执行，可能拒绝合法复杂 schema / 多模态 URL。SDK 返回按 Chat 类型解释；Raw 是 SDK JSON 表示且会脱敏，不保留原始 HTTP Header、任意错误 body 或全部非 JSON 结构。
- **未来小扩展**：HTTP Status 应来自实际 Provider 传输，而不是 Flask 的 200；在始终保留安全 Raw 的基础上 best-effort 展示 content、reasoning_content、finish_reason、usage、tool_calls，缺失不报错不伪造。Unknown 结构不因可选摘要失败而丢 Raw，不建立 canonical parser/framework。
- **不变的边界**：Manual 不进入 Fishery AnalysisResult 或结构化业务解析，不执行 tools；Raw 保留不意味着自动写历史、Trace 或文件。当前 4 MiB 是单响应/单 chunk 限制，不是累计 Streaming 大小上限；累计显示和实验内容策略待实际需要时评审。
- **取消限制**：进程内注册表，显式 Stop 才有可靠控制；关闭页面与远端停止计算不是同一事件；云端推理/计费是否停止仍 UNKNOWN，不因人工功能正常而宣称远端停止已证明。

### F. 隔离审计结论与当前处理

Manual endpoint 不构造 AnalysisRequest/AnalysisResult，不调用 Orchestrator、RAG、Diagnosis、CapabilityValidator、Probe、Runtime Defaults 或 `_parse_model_text()`；不调用 traces.record()，没有 Fishery analysis history 写入。RequestRegistry 只在内存保留有限生命周期状态，不是实验或分析历史。

Manual 分支 `attempts=0`，SDK `max_retries=0`；网络失败及 USER_CANCELLED 不触发生成重试，也不写 Capability Evidence。收到 tool_calls 保留 Raw，仅显示。`_public_data()` 的工具导入不改变这些边界。

**本轮处理：只更新已有设计、实施和运行文档；核心代码、测试、现有 Profile 不修改；Manual Expert V2 = DEFERRED。** 用户真实模型/UI 人工验收已记录，本轮不重复联网验证。允许开始下一项经用户明确指定的任务，不自动进入 V2 / R3 / R4 / R5。

### G. 本阶段收尾验证与 checkpoint

用户本次明确授权：审计无 blocker 且回归 / 安全检查通过后，将当前累计工作树 checkpoint commit 并 push main；不移动 v0.1。提交范围包含前两轮已有 Preset / Cancellation / Manual / UI 整理，不将其当成本轮新开发。

| 检查 | 结果 |
|---|---|
| Targeted Python（Preset / execution / access Web / private credentials / validation） | 141 项通过 |
| Full Python | 280 项通过；约 11.7 秒 |
| Targeted / Full Browser | 37 / 63 项通过；Node VM + DOM / fetch mocks，无真实 HTTP |
| JS syntax / diff --check | 均通过；换行提示不是错误 |
| Secret / sensitive path scan | 110 个 Git 公共文本文件；无未解决风险，Secret / outputs / credential lock / stage / 模型文件均未被跟踪 |
| R2 Frozen / 未读取或修改真实凭据 / 真实模型请求 | 五个冻结模块无修改；未读写真实凭据或 ACL；0 次真实模型请求 |
| Git checkpoint | 提交条件已满足；按本次授权对 main 创建并推送累计阶段 checkpoint，实际 hash / push / clean status 以 Git 与最终汇报为准 |


本轮审查前工作树含 26 个上一阶段未提交条目；产品校正追加一个既有设计文档修改，目前累计 27 个条目（16 个修改、11 个新增）。本轮新增变更仅为五份已有文档的修订，没有源码、测试、Profile 修改或新报告/功能。

安全扫描增加了具名 Secret 字面量规则，唯一额外命中为 `tests/test_cloud_capability.py:307` 的既有离线假 SDK fixture；已用全部字符串字面量脱敏的 AST 上下文确认，并核对该测试文件相对 HEAD 未修改。复核后无未解决命中；扫描不输出值、不读 ignored 输出或任何真实凭据，只是特征检查，不是完整安全证明。提交前再次核对暂存文件名单、格式、敏感路径和最终 diff，tag 保持原值。

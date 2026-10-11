# P2A-1：受控 Assistant 单次真实模型 Qualification Harness

日期：2026-10-10；基线 `4ab3afa`。依据已确认的 [P1 / P1.1](2026-10-assistant-turn-source-contract-p1.md)。本阶段仅实现、离线验证和 dry-run；**真实 Provider 请求为 0，真实凭据未读取，等待用户对具体 manifest 再次授权**。

## 1. 新入口与边界

入口：[qualify_assistant_turn.py](../../../../scripts/qualification/qualify_assistant_turn.py)。它不是 CI、Capability 自动 Probe、Publisher、Agent 或永久联网许可。一次进程只接收一个 manifest，没有批量参数或下一案例循环。

```text
Manifest（正式 Preset / Registry 白名单）
  → 默认 dry-run：安全计划，停止，不构建凭据 / SDK / Handler
  → 本次明确 --confirm-network
  → 正式 private_project_location / CredentialStore
  → ProfileRegistry.snapshot → 同一不可变 Runtime / CredentialSnapshot
  → AssistantService（原 Prompt、空 History、P1.1 提交合同）
  → 单次预算 Gateway 包装 → QualificationAdapter → 原 Adapter / SDK
  → 原 ToolCallingService / Registry / 本轮冻结 Policy / Executor
  → 原 Receipt 派生 / requirement_satisfied
  → 有限 JSON 报告
```

[assistant_qualification.py](../../../../src/fishery_ai/assistant_qualification.py) 负责 manifest、composition、预算与报告；[qualification_adapter.py](../../../../src/fishery_ai/qualification_adapter.py) 是仅该 run 使用的小型 Adapter 子类，继承现有编码、HTTP、错误映射、retry=0 和 AsyncOpenAI Cancellation。没有重写 Tool loop、Credential loader、Registry、Executor 或 Policy machinery。

旧 [Preset qualification](../../../../scripts/qualification/qualify_preset_tools.py) / [服务](../../../../src/fishery_ai/preset_tool_qualification.py)保持原行为：固定水质闭环加概念题，最多三次请求；新入口不调用其三请求流程。`real_validation.py`、Web 和正式 Assistant 入口均未修改。

## 2. Manifest 合同

| 字段 | 当前约束 |
| --- | --- |
| preset_id | Assistant 已发布白名单中的 OFF + Normal Preset；不能是 Custom / DS_1 / 任意 model |
| question | 单个非空问题，复用 Assistant 的 2 KiB 限制；repr 不显示，报告仅 hash |
| exposed_tools | Registry 的可执行名称集合，最多三个定义，不代表可执行三个调用；可以为空 |
| source_requirement | AUTO / CURRENT_OBSERVATION_QUERY / CURRENT_SCORE_EVALUATION / PROJECT_KNOWLEDGE_SEARCH |
| max_requests | 严格整数 1 或 2；硬上限 2 |
| max_output_tokens | 严格正整数，默认 256，本版硬上限 256 / request |
| retry | 严格整数 0；SDK / Gateway 不补发 |
| history | 必须空；不加载真实对话 |
| confirm_network | 保存文件为 false；true 不接受。CLI flag 仅在当前进程内授权一次 |
| case_id | 可省略；本批仅接受 Q1–Q4，防止把任意输入标签记录为报告内容 |

禁止额外字段：base_url、Credential 文件、credential_ref、Key、arbitrary model / Tool、System Prompt、Registry / Policy 配置。拒绝重复 JSON key、超过 8 KiB 的 manifest、非法 JSON / 类型；错误不回显输入。

CLI manifest 路径必须是当前工作区内 `.json`，解析路径后检查工作区边界；不能把用户私有凭据文件或源码 `.env` 当作 manifest。输出路径没有 CLI 参数。

`safe_plan` 包含当前发布的精确 service / adapter / normalized URL / model、合同与 ProtocolSpec 版本、工具名、要求和预算；包含 question_sha256、plan_sha256。plan hash 对问题、模型、合同、工具、要求与预算绑定，不受当前确认开关影响。Hash 不是匿名化或授权令牌；用户批准以具体计划为准，问题 / 合同等改变后须重新审阅授权。

## 3. 请求预算与输出预算

- 每次 Gateway 转发前消耗请求额度，不因失败退回，不自动 retry / 换模型 / 加问题。
- max_requests=1：若首轮普通回答，可按 AUTO / Requirement 判断；若首轮返回 Tool Call，保存首轮安全取证后返回 QUALIFICATION_REQUEST_LIMIT，不执行 Handler、不发第二轮。
- max_requests=2：复用原一个 Tool Call / 一个 round / 最多两次模型请求。多个调用拒绝；第二轮 tool_choice=none，继续调用则 TOOL_ROUND_LIMIT。
- 原普通 Assistant / SourceRequirement 提交门禁保留：非 AUTO 未满足、取消、length / 非法结束 / 空正文都不成功。
- 两轮每次都由固定 ProtocolSpec 的 max-output 字段施加预算。当前 Preset 没有声明 max_output_tokens capability；这只是维护者受控传输预算，不修改 Capability、Preset 或 Validator，也不认证模型实际支持新能力。字段不可编码时 fail closed；Provider 拒绝则报告安全错误、不补发。
- 输出上限不限制 Prompt tokens；复用现有 Assistant System 和有限 Tool Result，会产生输入 tokens。报告保留真实返回的数值 Usage。

## 4. Credential 与 Cancellation

正式 composition 继续 `PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING`。Harness 只交由 CredentialStore 解析和 ProfileRegistry 捕获快照；不查看、打印、复制 Secret，不使用 legacy `.env`、load_dotenv 或 os.environ mutation。

CredentialFileError / CredentialLocationError → CREDENTIAL_FILE_ERROR，Gateway / transport 计数均为 0。不修改 ACL、不创建替代凭据、不改来源重试。MISSING → SECRET_MISSING。Ollama Auth.NONE 仍由正式合同处理。

复用 RequestHandle / request_scope；模型 I/O、Tool 前后和第二轮都经过既有取消检查。CLI Ctrl+C 最终化为 USER_CANCELLED 并输出安全报告。SDK I/O 是否关闭单独记录；远端计算与计费是否停止始终 UNKNOWN，不作推断。若 SDK / HTTP debug logging 已开启，本入口在读取凭据前返回 QUALIFICATION_UNSAFE_LOGGING，不改全局 logger 设置。

## 5. 安全报告与窄观测

真实执行或凭据预检失败产生一个 UTF-8 JSON：`outputs/assistant-qualification/<run-id>.json`，Git ignored。固定生成边界、随机 run ID、独占创建，不覆盖已有记录；拒绝输出目录 symlink / Windows reparse。写入失败报告安全错误，并保留已发生的请求计数，不宣称 0、不自动再跑。Dry-run 只打印计划，不创建输出记录。

报告白名单：

- run / request ID、时间、精确 Identity、Preset / ProtocolSpec 合同版本、OFF / Normal。
- 案例 ID / 问题与计划 hash、实际 definitions 名称、Knowledge required query、tool_choice。
- request_count（Gateway 转发尝试）、transport_attempts / actual_network_requests（SDK 生成调用尝试），不是服务端成功 / 已计费次数；预检失败为 0。
- 每轮 outcome / safe error / finish_reason、Provider model 是否精确匹配。
- protocol tool_calls 是否存在、数量；只保留获准名称，否则 unknown_tool；call ID 仅合法性，不保留 ID。
- 无参调用仅 {}；Knowledge 仅 query_present / query_valid，不保存 query 内容。
- Tool 执行 status / duration、P1.1 Receipt 摘要、requirement_satisfied、最终提交 success / safe reason。
- 每轮和累计 Usage；首轮在预算 / Identity 拒绝前已返回的 Usage 也保留，不因 wrapper 拒绝丢失。

不保存 question、System / History、Secret / Authorization / Credential / 私有路径、SDK / HTTP body、模型正文或 reasoning、Raw Tool Result、Evidence 内容、当前读数、评分值。Trace 复用现有 JsonlTraceSink record_*，仅在内存收集 kind / status / safe error 并汇入该报告，不写另一份可含模型 call ID 的 Trace。

资格专用 Adapter 的 `_response` 窄包装只观察首 choice 的有限协议字段，再调用原归一化。原始 ID / arguments 只在函数内短暂比较，不保留；报告记录 raw / normalized call 和有限 metadata 一致性。观测不到则 available=false / consistency=null，不假称已证明一致。第二轮网络失败不能复用第一轮观测。检测到不一致直接结束，不执行后续 Tool / 请求；不开 HTTP debug。

## 6. Dry-run 与用户手工执行

在项目根目录正常 PowerShell 中运行，先查看计划：

```powershell
.\.venv\Scripts\python.exe scripts/qualify_assistant_turn.py --manifest scripts/manifests/assistant-Q3.json --dry-run
```

安全计划示例（省略 hash）：

```text
Preset: Qwen 3.8 Flash · OFF
Identity: dashscope / openai_chat / qwen3.8-flash
Contract: 1.0.2
Thinking: OFF
Mode: Normal
Tools: search_fishery_knowledge
Requirement: PROJECT_KNOWLEDGE_SEARCH
Max requests: 2
Max output: 256/request
Retry: 0
History: EMPTY
Network: NOT_YET_AUTHORIZED
actual_network_requests: 0
```

不加任何确认 flag 也默认 dry-run。`--dry-run` 和 `--confirm-network` 互斥，不能由文件中 true 持久授予网络资格。

只有用户另行明确批准对应具体 manifest 后，才手动运行（本阶段没有执行）：

```powershell
.\.venv\Scripts\python.exe scripts/qualify_assistant_turn.py --manifest scripts/manifests/assistant-Q3.json --confirm-network
```

一次 flag 仅覆盖这一进程 / manifest 的最多两次请求。Codex 本阶段没有真实运行授权；未来须用户针对计划另行批准，不能把上述命令当作授权。Codex 无法访问正式私有凭据时，安全记录 0 请求；用户可在自己的正常 PowerShell 执行同一命令，再交安全报告分析，不改 ACL / 复制 Key。

CLI 与 Flask 是独立进程，默认 Reader 绑定新的空 CurrentSnapshotStore，无法取得 Web 中已 Apply 的数据。Q1 / Q2 预计本地业务结果为 NO_DATA，合法完成操作仍可满足 P1.1；这不认证存在测量或评分。CLI 不提供 Scenario / Snapshot 导入选项；没有为了真实实验偷偷生成 normal。测试仅通过可信 fixture 注入临时 Store / 虚构 reading。

## 7. 第一批固定 manifest（尚未真实执行）

| 案例 | 文件 | 工具 | Requirement | 问题 |
| --- | --- | --- | --- | --- |
| Q1 | [assistant-Q1.json](../../../../scripts/qualification/manifests/assistant-Q1.json) | get_current_water_quality | CURRENT_OBSERVATION_QUERY | 请查询当前溶氧。 |
| Q2 | [assistant-Q2.json](../../../../scripts/qualification/manifests/assistant-Q2.json) | score_current_water_quality | CURRENT_SCORE_EVALUATION | 请查询当前系统水质评分。 |
| Q3 | [assistant-Q3.json](../../../../scripts/qualification/manifests/assistant-Q3.json) | search_fishery_knowledge | PROJECT_KNOWLEDGE_SEARCH | 请查询项目资料中鳗鲡低氧表现。 |
| Q4 | [assistant-Q4.json](../../../../scripts/qualification/manifests/assistant-Q4.json) | 全部三个定义 | PROJECT_KNOWLEDGE_SEARCH | 与 Q3 相同 |

均为当前 Qwen 3.8 Flash 发布 Preset，OFF / Normal、history=[]、retry=0、最多两请求、每请求最多 256 output tokens。Q4 只增加可选定义，执行仍最多一个 Tool。System / history / Handler / Policy 默认 / Registry / Capability / RAG 均没有修改。

四个案例分别 dry-run，不自动批量真实执行。用户可批准其中一个，完成后停止；不因为失败再次探索。报告里的静态问题是已发布实验案例说明，生成 run JSON 不保留问题全文。

## 8. 测试与交付

新增 [test_assistant_qualification.py](../../../../tests/qualification/test_assistant_qualification.py)：manifest / consent / credential boundary、预算、实际来源 Receipt、raw / normalized 对照、错误、Stop、JSON 脱敏、Web 不获得 Requirement 输入、原 Preset qualification 不回归。参数必须是 JSON object，空数组也不能被安全摘要误记为合法；未知 finish_reason 不复制进报告。

完整回归发现旧 Knowledge 装配结构检查只有三个 composition root 白名单，新独立 CLI 不在名单中。将 `assistant_qualification.py` 作为第四个 root 登记，并补测此入口只创建、绑定一个 KnowledgeService；没有改变 Web 共享实例、Registry 或 Handler。Dry-run 仍不构建任何服务。

自动测试全离线：临时文件、虚构 Secret / SDK、现有网络阻断；仅允许 asyncio 的内部 wakeup socketpair，不允许 Provider / DNS / Ollama。

| 检查 | 结果 |
| --- | --- |
| 新资格入口 targeted | 48 项通过 |
| Assistant / P1.1 Receipt | 49 / 33 项通过 |
| 旧 Preset qualification / Knowledge assembly | 22 / 7 项通过 |
| Tool conversation / Gateway Tool contract | 37 / 29 项通过 |
| Assistant Browser targeted | 25 项通过 |
| full Python | 908 项通过（23.949 秒） |
| full Browser | 188 项通过 |
| JS syntax | 通过，app.js 未修改 |
| Markdown 本地链接 | 87 条检查，无断链 |
| diff / 敏感扫描 | diff --check 通过；新增/修改文本未发现凭据字面量；无受跟踪的凭据或 outputs |
| Q1 / Q2 / Q3 / Q4 dry-run | 全部通过，均未授权联网、实际请求 0 |

真实 Provider 0 请求，真实凭据 0 次读取；没有 Preset / Evidence 发布，没有 commit / push。

### 工作树交付范围

- 新增：资格入口两个模块、CLI、四个固定 JSON manifest、48 项离线测试、本文阶段记录。
- 更新：BUILD_RUN、STRUCTURE、records 导航，以及 Knowledge composition root 的结构测试名单。
- 现有 Prompt / History、Web / JS、Policy / Registry / Handler、Adapter、Credential / ACL、Capability / Preset、Analysis / RAG 均未修改。
- 基线干净；改动留在工作树。普通 `git diff --stat` 只统计四个已跟踪文件，新文件另见 `git status --short`，不为统计而暂存。
- 最终状态：4 个已跟踪文件修改，9 个新文件未跟踪；tracked diff 为 26 行新增 / 2 行删除。输出路径经 `git check-ignore` 确认被忽略，dry-run 未创建真实资格报告。

## 9. 当前限制

- 只测试单个发布 Preset、空历史、OFF + Normal；不包含 History 对照、Intent Router、Requirement UI、第二个 round、Agent 或能力发现。
- max_requests=1 可以观察首轮协议，但没有执行来源证明，不是闭环资格通过。
- Receipt 只认证后端操作与结果来源，不证明模型正文每个来源声明真实。
- 返回 model 不匹配是安全失败；别名不自动猜测。
- CLI 初始 Snapshot 为空，不能替代 Web 当前现场值的人工验收。
- 高层 Gateway fake 没有 raw hook 时报告 unavailable；不会用 normalized 数据假冒 Provider 原始证据。
- 凭据或网络阻塞不判 UNSUPPORTED、不写 Capability Evidence、不发布合同；用户批准下一次实验前须重新核对具体计划。

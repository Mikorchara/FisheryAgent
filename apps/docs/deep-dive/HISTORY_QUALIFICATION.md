# Qwen 历史水质 Tool 单案例资格

**当前：固定15个真实样本技术通过，用户已完成真实管理网页基本验收；Qwen Normal历史单工具仍为local_experimental、Web默认关闭、非released。回答质量独立抽样，不阻塞普通功能开发；用户观察不等于正式资格。操作见第9～11节及BUILD_RUN。下文1～8节保留准备/停止记录，不代表永久网络授权。**

入口：[qualify_management_history.py](../../../scripts/qualification/qualify_management_history.py)。实现位于 [history_qualification.py](../../ai_service/development/history_qualification.py)，只复用正式管理 Service / Assistant / ToolCallingService；没有第二个执行循环或自动重试。固定批次薄入口见第7节。旧 [Streaming 资格](STREAMING_QUALIFICATION.md) 与其授权独立。

## 1. 精确范围

- Qwen `dashscope-qwen38-flash-r1`，OFF / Normal；Identity、ProtocolSpec 与 Preset 合同来自维护者固定配置。
- 只暴露 `get_water_quality_history`；1 Call / 1 Round / 最多 2 Requests，retry=0、整 Turn 120 秒。
- 使用正式 `ASSISTANT_V2@1`，不加实验 System Prompt；正式 B History Projection，三个案例均 EMPTY。
- 复用 [历史 candidate Scope](../../ai_service/resources/water_history_candidate.json)：Monitoring `management-water-history@1`、720 行 / 12 条明细 / 24 KiB、`historical-water-receipt@1`、冻结设备。
- 历史专用候选/资格每请求1024 output tokens，通过原 Adapter / ProtocolSpec 编码为 `max_tokens`；`water_history_candidate@2` / `management-history-qualification@2`，旧256计划不可复用。Profile默认输出预算为None，不会压低该值；未知Capability不伪造为已支持。其他Normal资格仍限256、Streaming资格仍512；未改变已开放两工具。Normal省略`stream`字段，使用SDK默认false。
- Scope、配置、Schema、Prompt/History、固定问题、夹具数据集、版本、SDK 版本、Policy 与预算均进入计划 hash。与两工具 Normal / Streaming 的 Scope、revision、资格记录独立。

## 2. 三个固定案例

三个案例使用相同问题：查询隔离设备过去 30 分钟的 DO 历史，简短说明窗口均值变化、极值时间与覆盖限制；无匹配时如实说明，不推断当前状态。

| case | 固定夹具 | 预期 | 人工核对重点 |
|---|---|---|---|
| `valid-history`（A） | 连续 30 个有效窗口，完整 30 分钟 | History → Final；OK | DO 首值 6.4、末值 4.4、差值约 -2.0 mg/L；最低 4.4、最高 6.4，时间与实际窗口引用一致 |
| `no-data`（B） | 只有区间外旧记录；请求区间内没有匹配窗口 | History → Final；NO_DATA | 明确无匹配历史；不能拿区间外旧值或常识编造 30 分钟观测 |
| `partial-history`（C） | 五分钟缺口，加一个 DO 无效窗口 | History → Final；PARTIAL | 25 个接收窗口中 DO 可靠 24 个；接收覆盖 1500/1800 秒，DO 可靠覆盖 1440/1800 秒；缺口/无效不能解释为正常或连续观测 |

夹具版本 `management-history-fixture@1`，Seed=42，设备 `history-qualification-pond`。固定查询时刻为 `2026-10-17T00:30:00+00:00`，请求区间 UTC 00:00–00:30（北京时间 08:00–08:30）。这是隔离测试时间，不是实际运行当天的最近 30 分钟。

为快速、可重复验证，使用 Simulator 快进生成 **60 秒窗口、每秒有效水质样本**；不等待真实时间，不改变生产模拟器默认 10 秒上报。完整夹具每五个窗口 DO 依次为 6.4 / 6.0 / 5.6 / 5.2 / 4.8 / 4.4。数值是窗口均值，不能称为瞬时采样值。C 不连接缺口；不判断持续低氧或恢复。

每次运行创建独立 SQLite 和管理 Policy，位于固定生成目录 `outputs/assistant-qualification/.management-work/` 的临时子目录，结束清理。只授权历史 Tool；不访问用户监测库、共享 Policy 或管理覆盖配置。正式 CredentialStore 在获得明确网络确认且计划匹配后才用于执行；不打印或复制 Secret。

## 3. Dry-run 与逐案例批准

仓库根目录执行以下任一命令；省略 `--dry-run` 也不联网：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_history.py --case valid-history --dry-run
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_history.py --case no-data --dry-run
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_history.py --case partial-history --dry-run
```

Dry-run 不构造凭据存储/SDK，不创建 SQLite、Policy 或报告。单案例运行需批准**某一个案例的一次运行及其hash**；固定15样本可按第7节一次批准三个新hash和各5次。当前尚未取得这项真实授权。

以 A 为例，先获取安全计划：

```powershell
$historyPlan = .\.venv\Scripts\python.exe scripts/qualification/qualify_management_history.py --case valid-history --dry-run | ConvertFrom-Json
$historyPlan.plan | ConvertTo-Json -Depth 12
```

**仅在用户已批准该案例及该计划之后**，手工执行一次：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_history.py --case valid-history --confirm-network --plan-sha256 ($historyPlan.plan.plan_sha256) --review-answer
```

B/C 分别重新 Dry-run、审阅、批准；命令的 `--case` 和获批 hash 必须匹配。hash 绑定内容，不是一次性令牌，也不是永久网络授权；重新启动同一案例仍须另行批准。不能使用旧两工具计划、另一个 case 的 hash，或为了失败补跑。

每次最多 2 次模型请求；首轮不调用 Tool 时可能只有 1 次，资格失败即为该次结果，不重试、不换模型、不额外补请求。三个案例若未来分别各获批一次，理论合计最多 6 次请求；这不是本轮授权。

`CREDENTIAL_FILE_ERROR` / Secret 缺失时停止，由用户检查正常 PowerShell 环境，不改 ACL、不读源码根 .env。Ctrl+C 复用 RequestHandle 取消；远端计算/费用是否停止仍为 UNKNOWN。若进程意外结束、没有完整报告或 CLI 返回未知请求数，不能推断为零请求，也不能自动重跑。

## 4. 安全报告与人工预览

报告仅由固定 `write_report()` 入口写入 `outputs/assistant-qualification/<run_id>.json`，使用独占创建，不覆盖已有记录。Dry-run 不写报告。

| 字段组 | 安全内容 |
|---|---|
| `plan` | case/身份、合同/Schema、Scope/计划/夹具指纹、固定时间、预算、Policy，不含 Prompt 正文或历史记录 |
| `requests` | Request 序号、tool_choice、finish reason、有限调用名称/参数合法性标志、Provider/normalized 一致性、Usage、实际输出预算编码 |
| `executions` | 实际 Tool、Handler 是否开始、业务状态、耗时、Result 是否逐字进入下一请求、清理先于执行、统计/时间/批次/覆盖核对布尔值 |
| `ledger` | 正式 Steps 推导的小型 Receipt；查询完成与可靠历史来源分开，不能认证当前观测 |
| 结论 | 产品 Commit Gate、资格路径检查、请求/传输计数、Trace、History 投影、清理与候选仍关闭状态 |
| 人工状态 | `PENDING_MANUAL_REVIEW` / `PREVIEWED_NOT_APPROVED`；`release_eligible=false`；回答质量与真实性均未自动评估 |

不保存回答正文、原始参数、原始 Tool Result、历史明细、完整 Prompt、Reasoning、凭据或 Authorization。统计核对来自真实 Tool payload 与独立夹具期望，结果只保存布尔标志；不是从模型正文判断成功。`formal_result_available=false` 表示中途证据可能不完整，不能把空 Ledger/执行列表当作“Tool 肯定未执行”的证明。

请求数与传输次数分开：`request_count` 是逻辑模型步骤，`transport_attempts` 是 Adapter SDK 尝试，真实模式 `actual_network_requests` 使用该计数；它不证明 Provider 已收费或已成功收到。Fake SDK 报告标记 `evidence_kind=offline_fixture / actual_network_requests=0`，不能计作真实样本。

`--review-answer` 仅在交互式 stderr 临时预览经正式提交门禁和 Secret 脱敏的答案，并过滤终端控制字符；不会持久保存，也不代表批准。不要开启 PowerShell Transcript、Tee 或重定向保存预览。若未预览，不为了取回答正文自动补跑。模型 Turn 已完成后中断预览只记 `PREVIEW_INTERRUPTED`，不伪装为模型 Stop。

人工必须核对：A 的值/时间/单位/来源；B 是否编造观测；C 是否如实解释覆盖限制。技术 PASS 仅证明执行与来源合同，不证明语言质量、最终真实性或无幻觉。合法执行了错误时间范围/指标时，产品来源门禁可能通过，但资格的夹具检查仍失败；二者分别记录。

## 5. Web 门禁与后续发布

资格入口仅在批准后的固定案例中构造服务器内一次执行许可，沿用同一 RequestHandle / 冻结 Policy / Registry / CredentialSnapshot / Assistant / Executor。它不修改 Scope 文件、状态、用户 Policy 或 Web 准入；正式 `prepare_turn()` 仍拒绝历史 candidate。

真实技术通过后仍先人工审核，再单独申请 exact `local_experimental`：仅 Qwen OFF / Normal / 历史单工具，明确请求/token/deadline 预算及设备/来源版本。下一阶段需经批准实施维护者控制、默认关闭且随 epoch 冻结的启动开关与精确 matcher；不能只改 JSON。用户历史 Policy opt-in 仍单独必需，不继承 Current + Knowledge、Streaming 或其他 Provider 的资格，也不自动开放三工具组合。

## 6. 离线验证

```powershell
.\.venv\Scripts\python.exe -m unittest apps.ai_service.tests.test_history_qualification apps.ai_service.tests.test_streaming_qualification
.\.venv\Scripts\python.exe -m unittest apps.ai_service.tests.test_water_history_tool apps.ai_service.tests.test_history_candidate
.\.venv\Scripts\python.exe scripts/dev/run_tests.py qualification
node --test apps/management_web/tests/*.test.mjs
```

覆盖三种真实业务状态、完整 Result 传递、统计/时间/覆盖/来源、Schema 拒绝、未知/多调用、2 请求封顶、Stop/Deadline/Trace/清理失败、精确批准、CLI 预览/报告脱敏与计数。旧两工具六条 Normal/Streaming HTTP 路径及三个资格计划保留原基线；不更新黄金文件来适配本次变化。离线结果不构成真实 Qwen 资格。

R2D-1E 离线基线：新增历史资格 21 项、既有管理 Streaming 资格 17 项通过；完整离线资格层 205 项中 204 通过、1 项因本机不能创建目录符号链接而跳过；历史 Tool / candidate 回归 31 项通过；管理前端 Node 55 项通过。三个 CLI Dry-run 均为零请求，计划 hash 彼此独立。Python/Markdown/敏感模式/diff 检查通过；未运行真实 Provider，不生成新的真实资格结论。

## 7. R2D-1F：固定15样本批次

**历史执行说明：本节固定批次授权现已执行完毕，结果见第9节。下列真实命令不应再次运行；后续任何新批次均需用户重新明确批准。**

不更改问题、夹具、Prompt、Schema、工具或运行预算。固定顺序 `valid-history → no-data → partial-history`，重复5轮，共15个独立子进程/Turn，最多30模型请求，每请求1024输出tokens（输出上限合计30720，不代表实际消耗）。每次仍用上面的单案例CLI和独立临时SQLite/Policy。批次脚本不是新模型执行循环。

| case | 当前 plan_sha256 | 次数 | 请求上限 |
|---|---|---|---|
| valid-history | `a422db6965dac29cfcbeca3805fa5ef4b4d8de417ade72543e312f6d12b2f7e5` | 5 | 10 |
| no-data | `91fbd13859b1cdfeb7669f8cf7f7ea182cc2c2db08009ed53a6d580a92699c39` | 5 | 10 |
| partial-history | `bcd3755ad3ddd6596a2ba0f836c1d2c2aa2b4fcc18580ff796d77d948cd04305` | 5 | 10 |

先Dry-run，未批准前停在这里：

```powershell
$historyBatch = .\.venv\Scripts\python.exe scripts/qualification/qualify_management_history_batch.py --dry-run | ConvertFrom-Json
$historyBatch.batch.plans | ConvertTo-Json -Depth 15
```

建议明确授权语句：“批准R2D-1F表中三个1024-token计划各独立运行5次，总共15 Turns/最多30模型请求；失败不补跑，其他案例/模型不在授权范围。”授权需对应表中完整hash；若Dry-run hash变化，先重新审阅，不能自动使用新的计划替代已批准计划。

**仅在获得上述一次性批准后**运行（不把计划参数本身当作永久授权）：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_history_batch.py --confirm-network `
  --valid-history-plan a422db6965dac29cfcbeca3805fa5ef4b4d8de417ade72543e312f6d12b2f7e5 `
  --no-data-plan 91fbd13859b1cdfeb7669f8cf7f7ea182cc2c2db08009ed53a6d580a92699c39 `
  --partial-history-plan bcd3755ad3ddd6596a2ba0f836c1d2c2aa2b4fcc18580ff796d77d948cd04305 `
  --review-answer
```

去掉`--review-answer`即不预览；保留时stderr必须是交互终端，不要录制Transcript/Tee或保存正文。批次本身始终只保存安全摘要与子报告引用，不存回答或原始参数。各子报告及批次汇总位于`outputs/assistant-qualification/<run_id>.json`，独占创建；不扫描旧结果凑样本。

每case汇总真实样本数、protocol调用/正确工具/合法参数、query operation、Source Gate、产品Commit Gate、技术完成、截断、业务状态、错误类型、时长与Usage。Final完成率以`product_commit_gate_passed`计，技术资格额外检查固定路径与夹具，不从模型正文判断。`mean_wall_latency_ms`含子进程/临时夹具开销；`mean_runtime_latency_ms`是正式Turn记录，缺失不补零。Usage按已知字段求和，同时记录observed_runs。NO_DATA/PARTIAL都是合法完成状态，不作为Tool执行错误。

普通样本失败保留结果并继续下一固定项；`CREDENTIAL_FILE_ERROR`、零请求preflight、取消、报告/计数异常立即停止。未知请求数用`requests_may_be_unreported=true`，`known_actual_network_requests`仅是下界；不得推断为0、自动resume或从头重跑。先盘点新生成安全报告，再申请剩余顺序的新授权。

技术完成不会自动开放Web。下一轮最小开放改动与当前Normal产品预算编码缺口见[成本审计](research/R2D1F_TOOL_INTEGRATION_COST_AUDIT.md#7-技术通过后的最短本地开放路径)。本轮仍candidate/关闭，不继承旧资格。

离线：`python -m unittest apps.ai_service.tests.test_history_batch apps.ai_service.tests.test_history_qualification`。完整qualification层213项（212通过、1跳过），History Tool/candidate/Policy 38项与FAST164项通过；三单案例及批次Dry-run为0请求。这些结果不构成真实模型稳定性证据。

## 8. R2D-1G：获批批次的零请求预检停止

2026-10-17，用户批准上述三个精确计划各5次及全部通过后的条件式本地开放。执行前重新Dry-run，三个hash与1024/1/1/2/retry=0/120秒条件全部匹配。

实际批次在首个valid-history的凭据预检返回`CREDENTIAL_FILE_ERROR`后按规则停止，没有启动后续14项。安全批次报告：`outputs/assistant-qualification/037c295c3d5a454a9c5435ec11ca658f.json`；单项报告：`outputs/assistant-qualification/769d53fa20d44975a0d4301672dc9421.json`。两个报告均保留，不覆盖、不删除。

- request_count、actual_network_requests、transport_attempts均为0；requests_may_be_unreported=false，无模型/Tool步骤或Ledger来源。
- 这是1次零请求preflight失败，不计入真实Provider样本；三个case的真实分母均为0，成功率、Final率、业务状态、模型耗时和Token Usage均不可评估，不能记作0/15技术成功或Qwen Tool失败。
- 错误发生在正式凭据装配阶段，早于Adapter构造；未调查Secret内容、修改凭据来源或ACL，也未重新尝试。
- 条件式开放未执行；历史仍candidate/默认关闭。未修改产品代码、启动开关、Scope或原两工具配置，未新增真实资格或人工质量结论。
- 若后续由用户在正常PowerShell手动执行，第7节的完整命令仍对应同一批准范围和未消耗的15个真实样本；再次执行前仍核对三个hash。不得在Codex中自动重启、扩展样本或绕过凭据错误。手工完成后先审查安全报告，再判断能否实施条件式开放。

## 9. R2D-1G：真实批次通过与本地实验开放

2026-10-18核对用户手工完成的安全批次`80e47502fe6f46e1bf4a11d8b430dac0`及15份子报告。与第8节零请求preflight分开，不合并其分母，也未重新调用Provider。

| case | 技术/Tool选择/参数/Source Gate/Commit Gate | 实际业务状态 | 模型请求 | 输入/输出/总tokens | 平均Turn耗时 |
|---|---|---|---|---|---|
| valid-history | 各5/5 | OK ×5 | 10 | 25470 / 1309 / 26779 | 5624.8 ms |
| no-data | 各5/5 | NO_DATA ×5 | 10 | 9535 / 886 / 10421 | 4725.0 ms |
| partial-history | 各5/5 | PARTIAL ×5 | 10 | 26360 / 1760 / 28120 | 6981.2 ms |

合计15独立真实Turn、30请求、65320 tokens（输入61365、输出3955）。15/15的Tool Result传递、固定夹具、Provider一致性、历史来源隔离、Trace与清理均通过；无截断或报告错误。是本轮15样本证据，不是长期稳定性或回答真实性证明；未持久保存回答。

用户随后明确批准以下产品Scope：Qwen `dashscope-qwen38-flash-r1` / OFF / Normal / **仅历史Tool** / 1 Call、1 Round、2 Requests / 每请求1024 / retry=0 / 120秒，local_experimental、默认关闭。固定Scope内容不变，产品状态与开关进入独立revision；无qualification_id或人工审核通过的伪造记录。

- 配置仍在`water_history_candidate.json`，为兼容已批准计划保留文件及`water_history_candidate@2`标识。资源登记local_experimental、enabled=false；只有维护者`--assistant-history-trial`可在进程内启用，不能仅改JSON enabled或浏览器参数开放。
- 管理设置显式opt-in历史，原选择保留；页面选择独立历史Profile，服务器只暴露H。该授权不修改默认两工具Registry/Scope，也不开放Streaming/其他Provider。
- 正式Service使用现有Adapter的内部传输预算字段，Normal编码`max_tokens=1024`；不是development Adapter，不伪造Capability。通用执行循环未变；原Streaming上限512不放宽。
- 资格CLI继续构造获批的**关闭candidate**配置快照，不把产品local_experimental批准改写成技术/人工资格。其Scope、三个计划hash保持原值；产品revision另行包含发布状态、开关、Policy、设备和epoch。未来再运行仍需新的明确网络授权。
- Profile切换只影响下一条消息、清除确认，保留成功pairs；pending期间冻结。错误/截断/Stop/Trace失败不提交，History不含Tool协议、Ledger或原始历史数据。

启动、网页步骤与关闭命令以[BUILD_RUN](../BUILD_RUN.md#r2d-1g历史水质单工具本地试用)为唯一操作入口。关闭开关并重启、刷新页面即可回滚；不删除数据库/报告/用户Policy。本轮Fake SDK覆盖实际管理HTTP中的OK/NO_DATA/PARTIAL、真实编码、权限与Scope拒绝、Stop/超时/失败/重放、设备冻结及原六路径；前端覆盖Profile选择与确认/History。最终真实网页验收由用户进行，本轮不自动联网。

### 本轮实现与离线结果

| 修改范围 | 实际文件（组内省略重复目录前缀） |
|---|---|
| 精确Scope/默认关闭的发布状态 | apps/ai_service/history_execution.py、resources/water_history_candidate.json |
| 产品装配与启动参数 | apps/ai_service/service.py、apps/management_web/ai_adapter.py、__main__.py |
| 实际Normal预算编码 | apps/ai_backend/openai_compatible_adapter.py（仅现有_kwargs，未改循环） |
| Profile/确认/安全展示 | apps/management_web/static/assistant.js、tool-policy.js；apps/ai_service/runtime/catalog.py（展示目录，不是模型Tool Description） |
| 原计划兼容 | apps/ai_service/development/history_qualification.py（显式关闭candidate快照，不供产品调用） |
| 回归 | apps/ai_backend/tests/test_protocol_specs.py；apps/ai_service/tests/test_history_candidate.py；apps/ai_service/runtime/tests/test_differential.py；apps/management_web/tests/test_ai_boundary.py、assistant-ui.test.mjs、monitoring-ui.test.mjs |

## 10. R2D-1H：交互修复与独立三工具候选

旧页面的问题是将服务器执行范围暴露为下拉选项，同时在开关关闭或未授权时仍提示重新确认。确认框没有按 `can_send` 禁用，勾选状态也没有绑定实际执行范围；因此勾选无法解除服务端门禁，却容易被误认作前端卡住。启动参数经CLI→Web Adapter→Service的传递正确，Fake HTTP分别复现：未授权、已授权但试用关闭、revision过期；条件齐全的历史查询正常成功。

本轮只读检查当前本机安全授权/Bootstrap API：用户仅授权Current + Knowledge，历史未授权；历史试用`enabled=false`，许可为local_experimental，`can_send=false`、`mode_reason=HISTORY_TOOL_NOT_AUTHORIZED`。原Qwen Normal多轮为active、可发送。两个历史条件均需用户处理，仅重新勾选确认无效。检查没有发送模型请求、没有打开监测SQLite或私有凭据/Policy文件，也没有更改用户选择。

现移除执行Profile控件和旧 selection state。历史查询为明确的下一条业务操作，显示所需开关、授权、模型和模式；成功后恢复普通提问。失败保留原操作、不自动换模式。配置不可用时确认框与发送同步禁用/清空；revision变更须重新勾选。服务端只接受有限业务action，不允许浏览器指定内部Profile、Scope或预算。

三工具候选 `management-normal-three-tools@1` 使用正式多轮Prompt/History及原Registry/循环，精确Qwen OFF、Normal、2/2/3、1024 tokens、retry=0、120秒。Scope额外绑定历史数据合同和来源版本；candidate、enabled=false，既不加入普通请求，也不开放Streaming。离线Fake证明模型响应可以选择任一工具、按首个真实结果继续选择第二个、提前Final及拒绝第三个调用；不证明真实LLM的选择稳定性。开放条件和启动操作见[BUILD_RUN](../BUILD_RUN.md#r2d-1h可用状态与三工具候选)。

离线验收（各层含重叠，不相加）：Backend 175项通过（28.382秒）；随后候选专项7项通过（1.885秒，含追加的JSON不得自行升级/启用门禁）；FAST 165项通过；管理HTTP/API 93项通过；历史/Streaming/批次资格基础设施46项通过；前端Node 60项通过。原六条Normal/Streaming路径与已冻结资格计划哈希对比通过，未改写基线。浏览器Fake SDK经真实HTTP完成历史查询并恢复普通提问；1280×900和390×844下无横向溢出，长禁用原因与输入/发送均未被卡片裁切，页面JS错误为0。Markdown本地链接/锚点、Python/JS/JSON语法、常见敏感模式和diff检查通过。未调用真实Provider/NPU，未更改真实数据、用户授权或现有发布范围。
| 当前文档 | apps/docs 的BUILD_RUN、HISTORY_QUALIFICATION、INTEGRATION、STRUCTURE、README、AI_BACKEND_DEVELOPMENT_GUIDE；apps/ai_service/runtime/README.md |

- Backend 169项通过（28.169秒），FAST 165项通过（1.523秒）；管理HTTP/API 93项通过（19.045秒）。测试层有重叠，不相加为唯一总数。
- 完整离线Qualification 213项：212通过、1项因本机符号链接限制跳过（41.151秒）；没有任何真实Provider/Ollama/NPU请求。
- 管理前端Node 58项通过；隔离Fake SDK浏览器HTTP实跑历史单工具PARTIAL → Final，界面自动提交一条回答。1280×900、390×844无页面横向溢出，浏览器JS错误0；测试服务/标签页已关闭，没有使用真实SQLite/用户Policy/凭据。
- 迁移差分测试原先把512 Streaming专用预算同时设给Normal，旧Normal侧因此未进入SDK。修正为只给Streaming设置后，增加每条比较至少一次SDK请求断言；新旧真正执行结果仍相等，未更新黄金基线或修改旧Prototype。
- 原两工具六条HTTP路径与三份资格计划、Scope/定义/Prompt/History/Monitoring统计保持既有基线。历史三个candidate计划hash保持第7节原值；本次仅批准产品local_experimental，不新增或篡改真实资格记录。
- Python AST 31文件、JSON 2文件、JS语法7文件和新增2段PowerShell启动/回滚示例通过；280个Markdown本地链接、42个锚点无损坏，diff/行尾空白检查通过。工作树改动文件的API Key/Bearer/private-key模式扫描无命中；9个受保护实现/配置字节hash未变，旧Prototype无diff。模式扫描不等于绝对无泄漏证明。
- 1G当时尚未完成：真实网页最终人工验收、回答质量/真实性专项审核、History Streaming、其他Provider/组合、持续异常/恢复分析和生产鉴权。网页基本人工验收随后由用户确认，见第11节；其他边界不变。

## 11. R2D-1I：人工网页验收与后续测试

用户确认：Qwen在真实管理网页成功选择历史Tool，Monitoring返回实际统计，Tool Execution与Source Gate正常，生成完整Final；管理设置和启动开关可禁用。此处记录用户观察，本轮没有读取真实报告、数据库或私有配置，没有新增qualification_id、人工回答质量批准或released状态。

历史Tool作为可长期维护的有限业务模块保留；模型组合发布、默认开关与用户授权继续分别控制。后续真实连接由用户从[manual_real_tests](../../../scripts/manual_real_tests/README.md)亲自执行，原单案例/批次CLI不搬迁；默认Dry-run，真实执行需要本次计划与明确确认，旧hash不作为永久授权。完整复盘及并发保存问题见[R2D-1最终审计](research/R2D1_TOOL_RETROSPECTIVE_AUDIT.md)。

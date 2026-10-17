# 管理平台启动、联调与验证

## 环境

Python 3.11+，使用根项目已有 Flask 依赖；SQLite、生成器和 HTTP transport 使用标准库。Node 用于前端测试，无需 npm install 或构建。所有命令在 `D:\CodexProject\Fishery_AI_Prototype` 执行；首次环境配置见根 [BUILD_RUN](../../docs/BUILD_RUN.md#环境与启动)。

## 一行式常用命令

以下从仓库根目录、同一个正常用户PowerShell执行。先查看现有8766服务；若已运行，不另启第二个，也不强杀未知进程。以下只启动本地网页和模拟数据，不发送LLM请求、不修改用户Policy。三个已批准试用开关分别启用既有精确范围，不开放三工具统一candidate。

第一行启动自己的服务器并让子进程继承临时开发接入令牌；端口占用时直接停止该命令，不覆盖令牌。令牌不是Provider Key，不打印、不落盘：

```powershell
if (Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue) { throw '8766已有服务，请先核对并停止自己启动的实例。' }; $env:FISHERY_SIM_INGEST_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'); $managementServer = Start-Process -FilePath .\.venv\Scripts\python.exe -ArgumentList '-m','apps.management_web','--enable-ingestion','--enable-assistant','--assistant-multi-round-trial','--assistant-streaming-trial','--assistant-history-trial' -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru
```

随后在**同一终端**运行模拟器，让它使用相同令牌；默认每10秒上报，不触发LLM：

```powershell
.\.venv\Scripts\python.exe -m apps.simulator --scenario normal --seed 42 --interval 10
```

访问`http://127.0.0.1:8766`。默认Normal；在管理系统设置中授权Tool，历史问题点击“历史查询”。退出模拟器按Ctrl+C；只停止自己保存的服务器进程：

```powershell
if ($managementServer -and -not $managementServer.HasExited) { Stop-Process -Id $managementServer.Id }; Remove-Item Env:\FISHERY_SIM_INGEST_TOKEN -ErrorAction SilentlyContinue
```

关闭历史试用：停止自己的服务器，保留所需其他参数但去掉`--assistant-history-trial`后重启、刷新页面；也可在管理设置撤销历史授权（影响尚未领取的新请求，已领取Turn保持冻结；需停止它时用Stop）。关闭全部AI试用则去掉三个trial参数，Normal单轮仍可由`--enable-assistant`启用。不删除数据或改JSON。

日常小改动只跑受影响层；以下每条均为一行，全部离线（HTTP测试使用本机Fake/临时数据）：

```powershell
.\.venv\Scripts\python.exe scripts/dev/run_tests.py fast
.\.venv\Scripts\python.exe -m unittest apps.monitoring.tests.test_water_history apps.ai_service.tests.test_water_history_tool apps.ai_service.tests.test_history_candidate apps.ai_service.tests.test_management_policy
.\.venv\Scripts\python.exe -m unittest discover -s apps/management_web/tests -p 'test_*.py'
node --test apps/management_web/tests/*.test.mjs
```

现有`product`包含旧Prototype与新Backend/AI业务层，**不含Monitoring、Simulator、管理HTTP与Node**。只有这些层受到影响时追加对应测试；不用每个小步骤都重复所有层。资格入口改变时运行离线`python scripts/dev/run_tests.py qualification`；本轮新增薄入口可只跑`python -m unittest tests.qualification.test_manual_real_tests`。不要将`FULL QUALIFICATION`误解为真实请求。

真实外部连接由用户从[统一人工入口](../../scripts/manual_real_tests/README.md)亲自执行。这里没有新增启动框架；一行启动命令沿用既有模块和参数。本轮验证参数传递及PowerShell语法，没有启动真实服务、模拟器或Provider。

## 只读启动

```powershell
.\.venv\Scripts\python.exe -m apps.management_web
```

访问 `http://127.0.0.1:8766`。读取已保存的监测数据或明确 NO_DATA；默认拒绝设备写入。可使用 `--port 8767`。原 Prototype 8765 独立保留；Flask debug/dotenv 关闭。

## Normal Assistant（R2B-3）

```powershell
.\.venv\Scripts\python.exe -m apps.management_web --enable-assistant
```

需同时接收模拟数据时使用 --enable-assistant --enable-ingestion，并按下文先设置开发令牌。AI 关闭方式：停止自己启动的服务器，去掉 --enable-assistant 重启；已有 SQLite 不删除，原 Prototype 不受影响。

启动、刷新和切换页面不发模型请求。网页进入“AI 智能助手”，选择 Qwen 或 Ollama、监测设备，输入问题并勾选本次请求确认后发送。云端显示 REAL NETWORK REQUEST / 可能费用；Ollama 显示 LOCAL MODEL REQUEST，不是 Mock。默认单轮一次确认覆盖最多两次模型请求；多轮试用显示最多三次；结束后取消勾选。按 Ctrl+Enter 可发送，普通 Enter 换行。

Qwen 使用现有正式用户私有凭据，不需要复制 Key、创建项目 .env 或调整 ACL；缺失/权限错误只显示安全错误码。Ollama 须由用户正常启动既有本地服务与模型，本轮自动测试没有启动或请求它。

人工验收（真实模型调用须另行明确授权）：

1. 未收到上报时问“现在水质怎么样？”，观察 NO_DATA，不得出现 Demo 正常值。
2. 启动模拟器 normal/low_oxygen；比较网页与 Tool 的同设备观测时间、来源、数据质量和 PROTOTYPE 规则。持续上报期间批次可更新，不声称不同查询原子同步。
3. 停止模拟器，超过 30 秒观察 stale、超过 90 秒 offline；缺失/无效/部分窗口按实际状态解释。
4. 问“什么是溶氧？”，允许直接回答、未调用 Tool；再次询问当前值时应查询当前设备，不将历史当本轮来源。
5. 验证 History、模型/设备切换确认、清空、切出页面再返回、Stop 与错误重发；取消/截断不提交成功回答，Stop 不保证远端计费停止。
6. 仅暴露实际授权的水质/项目知识；无授权时显示“无”，不得越权。Policy、装配 Tool 集合或定义变化使旧确认失效，需要重新确认。

### 项目 Knowledge Tool 使用

默认仍只授权水质。需要Knowledge时，在**新管理系统 → 系统设置 → Assistant Tool授权**中保留既有选择、勾选项目知识并保存，再返回聊天刷新/确认。管理端独立Policy存在后，不再跟随旧Prototype Tool Manager的后续改动；没有独立文件时仅只读继承旧选择。保存管理授权不会修改旧Prototype，不需发送模型请求。

管理端执行 `python -m apps.management_web --enable-assistant`，打开 `http://127.0.0.1:8766` → AI 智能助手，刷新后核对“可用 Tool”含 `search_fishery_knowledge`。选择 Qwen/Ollama，逐次确认模型请求，再问“请检索项目资料，说明鳗鲡低氧表现”；观察项目背景 Knowledge 卡片、命中数/NO_MATCH。当前水质问题仍用 Monitoring Tool，不得把知识命中解释为当前 DO 或疾病确诊。真实模型请求须有用户授权；启动与授权配置本身不联网。

默认仍为 1/1/2。若模型同轮请求两项，TOOL_CALL_LIMIT 是安全拒绝；单轮配置第二次请求继续调用 Tool 为 TOOL_ROUND_LIMIT。双 Tool 顺序试用须按下一节显式开启。

离线专项：`python -m unittest apps.management_web.tests.test_assistant` 与 `node --test apps/management_web/tests/assistant-ui.test.mjs`。前者在临时 SQLite 上通过正式 Assistant/Registry/Executor/Source Gate/Trace 执行 Fake Provider HTTP 闭环，阻断所有外部 socket；后者运行实际前端模块的离线 DOM 行为。不是模型真实资格或回答质量证明。

## R2B-4：Normal Multi-Round 本地试用

```powershell
.\.venv\Scripts\python.exe -m apps.management_web --enable-assistant --assistant-multi-round-trial
```

访问 `http://127.0.0.1:8766` → AI 智能助手。同时接入模拟器时，在设置下文开发令牌后追加 `--enable-ingestion`。启动本身不调用模型；每次发送仍须明确确认。

- 在新管理系统设置中授权当前水质与项目知识，实际执行集合仍须精确匹配；授权历史不将其加入普通两工具请求。评分无Handler。页面显示“多轮 · 本地实验”、最多三次模型请求。
- Qwen优先，已有管理网页基本人工观察；Ollama有独立实验Scope，不继承Qwen或旧Prototype资格。二者仍是local_experimental，人工观察不等于正式released。固定OFF / Normal，每轮最多一个Tool，整Turn最多2 Calls / 2 Rounds / 3 Requests、retry=0。
- 开关启用但 Scope/Policy 不匹配时禁用发送；服务端联网前拒绝 `ASSISTANT_MULTI_ROUND_SCOPE_MISMATCH`。Policy/定义/配置/设备/epoch 改变时旧 revision 失效，刷新并重新确认；不自动重发、降级或切换 Provider。
- 配置来自 [管理专用 Scope](../ai_service/resources/assistant_execution.json)，在应用启动时冻结。文件的 `multi_round_enabled` 默认为 false，上述命令仅在本进程启用；浏览器不能指定模式、预算、Prompt 或配置路径。

人工验收（本轮未执行真实请求）：

1. normal 水质问“当前溶氧是多少？”：预期一次水质查询后 Final，也允许模型提前结束；记录实际路径。
2. low_oxygen 问“先查询当前水质，如果异常再检索项目资料解释低氧风险”：观察水质 → Request #2 → Knowledge → Request #3 → 唯一 Final。Tool B 必须由模型看到 Result A 后选择，不保证每次模型都按预期选择。
3. “什么是溶氧？”允许 Direct Final；NO_DATA/STALE/INVALID 如实解释，不补造正常值。Knowledge 卡片是背景来源，不替代当前观测。
4. 核对两个独立 Tool 卡片、完整有序 Steps、聚合 Usage；中途 Stop/Timeout/错误不得进入成功 History，清空/模型/设备切换及 epoch 语义不变。

回滚：停止自己启动的管理服务器，确认管理配置 `multi_round_enabled=false`，去掉 `--assistant-multi-round-trial`，用 `--enable-assistant` 重启。新 epoch 清理旧会话/确认，恢复 1/1/2；无需修改 Policy、SQLite、凭据或 Prototype 配置。执行失败不会自动按单轮重跑。

离线专项：`python -m unittest apps.ai_service.tests.test_execution apps.management_web.tests.test_multi_round`。使用正式 Assistant 多轮 Prompt、History、Registry、Executor、Ledger 与提交门禁，Fake Provider 根据真实临时 Monitoring Result 决定下一 Tool；不是实际模型质量或资格证据。

## 连续模拟器本机联调

同一 PowerShell 中创建仅本次开发会话使用的访问令牌，让服务器子进程继承；不显示、不落盘、不使用真实 API Key：

```powershell
$env:FISHERY_SIM_INGEST_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$managementServer = Start-Process -FilePath .\.venv\Scripts\python.exe -ArgumentList '-m','apps.management_web','--enable-ingestion' -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru
.\.venv\Scripts\python.exe -m apps.simulator --scenario low_oxygen
```

先打开网页，初次上报等待约 10 秒；约 60–120 秒观察溶氧逐渐降低和关联事件。也可选择 normal、suspected_disease、reduced_feeding、combined_anomaly、device_offline。device_offline 在场景 30 秒处停止上报，但进程继续等待，便于观察过期/中断。

停止模拟器按 Ctrl+C；服务器继续保存和显示末次数据。停止自己启动的服务器：

```powershell
Stop-Process -Id $managementServer.Id
Remove-Item Env:\FISHERY_SIM_INGEST_TOKEN
```

不要停止未由当前会话启动的进程。若 8766 已占用，服务器加 `--port 8767`，模拟器加 `--server http://127.0.0.1:8767`。可在独立终端分别启动，但双方必须继承同一个开发令牌；不要打印令牌或写入项目 .env。

可选参数：

```powershell
.\.venv\Scripts\python.exe -m apps.simulator --scenario normal --seed 42 --interval 10 --sample-period 1 --frame-period 0.5 --windows 6
.\.venv\Scripts\python.exe -m apps.simulator --scenario normal --switch-to combined_anomaly --switch-after 60
.\.venv\Scripts\python.exe -m apps.simulator --scenario combined_anomaly --dry-run --windows 12
```

dry-run 快速推进逻辑时间，不联网、不读取访问令牌。上报失败停止进程，不自动重试。重新启动使用新 session_id，sequence 从零开始；观测时间从新的启动时间继续。R1 静态 Demo 仅可用 `--legacy-demo` 显式启动，不能同时启用接入。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s apps/monitoring/tests -p "test_*.py"
.\.venv\Scripts\python.exe -m unittest discover -s apps/simulator/tests -p "test_*.py"
.\.venv\Scripts\python.exe -m unittest discover -s apps/management_web/tests -p "test_*.py"
.\.venv\Scripts\python.exe -m unittest discover -s apps/ai_service/tests -p "test_*.py"
node --test apps/management_web/tests/*.test.mjs
```

这些测试独立于根 product 发现范围。前两组除明确的 loopback HTTP 测试外不联网；只用临时数据库/虚构令牌，无真实 Provider 或 NPU。

R2B-2 日常 targeted：`python -m unittest discover -s apps/monitoring/tests -p "test_business_services.py"`，规则变更追加 `test_rule_governance.py`，调度变更运行 simulator/tests。真实 loopback 测试现在使用零人为时间缓冲；发送端先确认 UTC 窗口结束。SIMULATOR_CLOCK_OUT_OF_SYNC 时停止并检查时钟，不放宽服务器时间校验或自动补发。

R2B-3.2 读取/投影改动优先运行：`python -m unittest apps.monitoring.tests.test_water_capture apps.monitoring.tests.test_business_services apps.monitoring.tests.test_rule_governance apps.management_web.tests.test_assistant`。覆盖一次读取/诊断、并发新批次隔离、Web/Tool 同源、质量/来源/时间、DTO 大小、Ledger、Normal、取消及安全拒绝；无需调用 Provider。原 Web 交互继续用上面的 Node 测试验证。

R2B-3.3：`python -m unittest apps.management_web.tests.test_knowledge apps.management_web.tests.test_assistant`，配合上述 Node 测试。HTTP 测试复用正式 Registry/Handler/Executor/Source Gate，含本地 KnowledgeService + Fake Provider；所有模型网络被阻断，使用临时 Policy/SQLite。覆盖 NO_MATCH、参数/授权/检索错误、来源隔离、取消、单轮预算、定义/Policy revision 和 History；不是实际 LLM 选择或回答质量资格证据。

R2B-3.4 边界测试：`python -m unittest apps.ai_service.tests.test_service apps.management_web.tests.test_ai_boundary`。前者直接创建业务 Service + 临时 Monitoring/Fake Provider，复用调用方 RequestHandle，无需启动 Flask；后者验证 Web 令牌不传入业务、HTTP 门禁优先执行及 source identity。原 Assistant/Knowledge HTTP 测试全部保留，内部 patch/import 当前指向 `apps.ai_service.service` 与 `apps.ai_service.business_tools` 的实际 owner，不保留旧 bindings 入口。启动与端口不变，不新增 AI 服务进程。

界面验收：七页导航；窗口均值、有效样本和历史；视觉有效帧、加权体长检测记录与无标定缺失；零鱼帧计入数量均值；PROTOTYPE 规则和事件 ACTIVE / RESOLVED / INDETERMINATE；缺失、过期、离线不能确认恢复，只有可靠同版本新观测可消退；所有时间按北京时间显示到秒；停止后 >30 秒过期、>90 秒中断；恢复上报后更新；桌面与窄屏无溢出。读取失败清除当前展示并提示失效，不将缓存当实时。阻塞后的错过窗口跳过不补发，日志显示 skipped，历史保留时间缺口。

服务/合同变更运行相关 Python 和 Node；UI 变更增加浏览器行为与布局检查。涉及共享 Runtime 桥接追加其相关回归。文档变更检查链接与 diff。不要把测试启动器的旧授权当作真实模型执行许可。

## 数据与限制

存储为 `outputs/management_web/monitoring.sqlite3`，Git ignored；重启保留记录。不要删除已有数据库来“重置演示”，需要隔离测试时使用临时库和服务注入。

这是本机模拟接入，不是生产设备鉴权；AI 默认 503，显式启用后使用 Normal 安全门禁。真实视频、文件写入、用户权限与设备控制未开放。安全与 DTO 详见 [INTEGRATION](INTEGRATION.md)。


## 历史趋势人工检查（R2B-4.1）

重启自己启动的管理 Web，并刷新页面加载新静态文件；无需删除数据库或重新启动模拟器。综合总览 / 水质监测中，选择“最近 30 分钟”“最近 1 小时”或“全部存储历史”。范围以最后观测为终点，页上北京时间与 stale/offline 状态仍须保留。

核对：最近会话的 10 秒点展开；全部历史保留停机间距并在会话切换处断线；五个时间刻度不挤在首段，纵轴相邻标签可区分；窄卡片仅图表内部允许横向滚动。History 表与 API 仍保存全部有界历史，范围切换与 5 秒刷新只读、不采样。

专项离线验证：`node --test apps/management_web/tests/chart-ui.test.mjs apps/management_web/tests/monitoring-ui.test.mjs apps/management_web/tests/view-model.test.mjs`；`python -m unittest apps.monitoring.tests.test_history_projection apps.monitoring.tests.test_pipeline apps.monitoring.tests.test_water_capture`。固定测试数据不依赖用户真实 SQLite。


## R2B-5B：Streaming 后端离线验证

不带试用参数启动时仍关闭 Streaming；原 Normal 参数不变。R2B-5E 已获批准开放 Qwen 精确两工具本地实验，启用与回滚见下节；这不是正式 released。

```powershell
.\.venv\Scripts\python.exe -m unittest apps.ai_service.tests.test_streaming_config apps.management_web.tests.test_streaming
```

该测试从受控管理 HTTP POST SSE 路由进入，运行正式 Assistant Prompt/History、Gateway/Assembler、临时 SQLite Monitoring、Knowledge、Ledger、Trace 与提交门禁；SDK 为纯离线 Fake，网络被阻断，只容许 Windows asyncio 自身唤醒套接字。临时 local_experimental 配置只在测试实例内注入，不修改磁盘候选或用户 Policy。实际 max_tokens=512、2/2/3、120 秒、资源关闭和结果传递均有断言。新增桥接测试把三条实际 HTTP/SSE 路径的事件逐字节送入正式前端 parser / Workspace，验证各自只有一个成功 pair；不代表真实模型资格或回答质量。

## R2B-5C：聊天前端离线验收

```powershell
node --test apps/management_web/tests/*.test.mjs
.\.venv\Scripts\python.exe -m unittest apps.management_web.tests.test_streaming
```

页面操作：模式切换仅影响下一条消息，成功 History 共用，每次切换清除联网确认；执行中模式/模型/设备/Clear 冻结。聊天内部滚动，输入区保持位置；发送自动跟随新问题，向上阅读暂停跟随，“回到最新”恢复。右侧编号对应每个问题，悬浮查看摘要、点击跳转，Tab/Enter 和方向键/Home/End 可操作。

Streaming 临时正文在同一消息卡片内转为最终回答；Tool 请求、失败、截断、超时、Stop 或断线撤销预览，保留草稿且不写成功 History。不自动重连、重发或转 Normal。离开/刷新页面尽力取消原 Handle；后端已经完成但 Final 未到达时，浏览器仍不提交，远端计算/计费停止状态为 UNKNOWN。

R2B-5E 允许显式启动本地试用后人工检查 Streaming。关闭开关、candidate 或 Scope 错配仍拒绝发送；不继承原 Prototype 资格。

## R2B-5D：单案例资格准备

默认 Dry-run 的 `scripts/qualification/qualify_management_streaming.py` 固定三个案例 direct-final / current-water / low-oxygen；只考虑管理 Qwen 两工具 Scope、512 tokens/请求、2/2/3 和 120 秒。真实执行须逐案例批准并提供 `--confirm-network --plan-sha256`，可在交互终端选择 `--review-answer`，不保存正文或自动批准。用户已完成三个真实案例，技术均 PASS，共六次模型请求；人工回答质量仍待审，CLI 未验证真实浏览器 HTTP/SSE。

命令、报告与证据边界见 [Streaming Qualification](deep-dive/STREAMING_QUALIFICATION.md)。配置状态变化会改变后续资格计划 hash，旧报告保留，不补跑或覆盖。

## R2B-5E：Qwen Streaming 本地实验

用户明确批准本地试用，回答质量审核留待后续。维护者范围为 `local_experimental`，不是 `released`；qualification_id / validated_at 仍为空，不伪造人工批准。磁盘配置仍为 `enabled=false`，只在显式启动的进程中开启：

```powershell
.\.venv\Scripts\python.exe -m apps.management_web --enable-assistant --assistant-streaming-trial
```

访问 `http://127.0.0.1:8766`。如还需保留 Normal 2/2/3 本地实验，追加 `--assistant-multi-round-trial`；否则 Normal 仍为 1/1/2。两个开关独立，界面默认始终 Normal。模拟接入另按前文配置开发令牌后追加 `--enable-ingestion`，启动与切换本身不调用模型。

1. 在现有 Prototype Tool Manager → Assistant 中，由用户明确授权水质查询与项目知识检索，并开启 LLM Tool Calling；不要修改默认 Policy。管理端只装配这两个 Tool，不装配评分。
2. 刷新管理页面 → AI 智能助手 → Qwen 3.8 Flash → 选择监测设备 → Streaming。核对“本地实验 · local_experimental”、512 tokens/请求与最多三次模型请求；模型/Policy/Scope 不匹配时页面解释原因，服务端在凭据解析/联网前拒绝。
3. 输入概念问题、当前水质问题，或“先查询当前水质，如果异常，再检索项目资料解释低氧风险”。勾选本次 REAL NETWORK REQUEST 确认后发送；一次确认覆盖最多三次请求及本地只读 Tool。检查独立 Tool 卡片、Steps、Usage 和预览原位转 Final；模型可以提前 Final，不保证每次都选 Tool。
4. Normal / Streaming 切换只影响下一条消息、保留成功 History并清除旧确认；执行中冻结模式/设备/模型。测试向上阅读暂停跟随、问题标记跳转、Stop 和断线撤销。临时预览、失败、截断及取消不进入成功 History；不自动重连、重试、切 Provider 或以 Normal 重发。

精确范围：`dashscope-qwen38-flash-r1` / OFF / STREAMING / `get_current_water_quality` + `search_fishery_knowledge`，2 Calls / 2 Rounds / 3 Requests、每轮最多一个 Tool、retry=0、120 秒整 Turn、每请求最多512 output tokens。Identity、协议、Prompt、History、definitions、数据绑定、设备、Policy、预算和 epoch/revision 必须匹配。Ollama、DeepSeek、评分与三工具 Streaming 均未开放。Tool 返回的模拟观测不是实际硬件采样；规则为 PROTOTYPE，知识为背景来源，回答质量尚未完成审核，512 tokens 仍可能截断。Stop 不保证远端计算/计费停止。

回滚：先在页面 Stop，停止自己启动的管理服务器（Ctrl+C），去掉 `--assistant-streaming-trial` 后重启：

```powershell
.\.venv\Scripts\python.exe -m apps.management_web --enable-assistant
```

若需保留原 Normal 多轮，回滚命令可追加 `--assistant-multi-round-trial`。新 epoch 撤销旧会话/确认；刷新页面，Streaming 被拒绝，Normal 可用。磁盘 `enabled=false` 不被启动参数写回；不用改数据库、Policy、凭据或原 Prototype。

本轮离线验证：管理配置/AI Service/资格兼容/HTTP SSE 与 Normal 相关 Python 124 项、共享 Streaming Assembler/Runtime/Source/Web 回归134项，合计258项通过；管理前端 Node 52项通过，包含 HTTP/SSE → 正式 parser/Workspace 的三路径桥接。覆盖512实际编码、发布拒绝、Scope/revision、双 Tool Result/独立Ledger、Preview→Final、Stop/超时/截断、History和回滚。未运行无关全量测试，没有调用真实 Provider/NPU，也没有启动实际网页推理；真实网页体验由用户后续验收。

## 独立 Backend：启动与回滚

管理Service/Web/SSE/管理qualification已统一使用apps.ai_backend和ai_service.runtime，不再运行旧LLM Runtime。正常命令和精确local_experimental授权保持不变：

修改业务 Tool、Prompt、Preset 或发布配置前先读 [开发指南](deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)。其中区分实际代码 owner、测试入口与需要另行批准的精确实验范围；本节命令不授予新的 Provider 或 Tool 资格。

```powershell
# 默认Normal，单轮；不启用Streaming
.\.venv\Scripts\python.exe -m apps.management_web --enable-assistant
# 本地实验：Normal多轮 + Qwen精确两工具Streaming，网页默认仍Normal
.\.venv\Scripts\python.exe -m apps.management_web --enable-assistant --assistant-multi-round-trial --assistant-streaming-trial
# 离线测试
.\.venv\Scripts\python.exe scripts/dev/run_tests.py backend
.\.venv\Scripts\python.exe scripts/dev/run_tests.py fast
.\.venv\Scripts\python.exe scripts/dev/run_tests.py product
.\.venv\Scripts\python.exe scripts/dev/run_tests.py qualification
node --test apps/management_web/tests/*.test.mjs
```

先停止自己启动的旧进程，再重启并刷新页面；新epoch使旧确认失效，不能自动重发问题。访问http://127.0.0.1:8766；沿用上文Tool Policy配置，必须授权水质+Knowledge才匹配Streaming Scope。本轮没有打开开关或修改用户Policy，默认关闭Streaming、Qwen两工具512/2/2/3/120秒/retry=0不变。

正式wheel已在outputs/r2c1d-build/env隔离环境以本机缓存setuptools84.0.0构建/安装，build-system>=68未改，不联网、不修改现有.venv。Wheel包括明确的管理应用包、JSON和静态资源，排除tests/outputs。源码启动保持原root；wheel安装后从有效项目工作区启动，无法确认时WORKSPACE_REQUIRED，避免变更私有凭据身份或写入site-packages。

管理资格计划升级management-streaming-qualification@2，增加apps.ai_backend@1标记，旧plan-sha不可复用；问题/Prompt/Scope/Schema/预算保持。旧报告不编辑或重新解释为新Backend真实运行。后续真实smoke必须另获明确授权并重新dry-run，不使用上次资格授权。

仅关闭试用的回滚：停止Web，去掉--assistant-streaming-trial和--assistant-multi-round-trial重启，恢复默认Normal1/1/2。若需回滚Backend代码：保存当前修改，停止自己启动的Web，整体恢复Phase I基线0cf64f6的service/contracts/bindings/execution/streaming、Web请求控制/SSE、管理资格与打包；不要只替换Adapter或Handle，不reset整个工作树，不修改SQLite/凭据/Policy/报告。重启新epoch，失败请求不自动重发。

R2C-1E：用户已通过真实管理网页完成 Qwen Normal 水质 Tool / Final、Qwen Streaming 水质 + Knowledge / Final 提交，以及模拟来源与 PROTOTYPE 标签的基本验收。迁移主线结束；回答质量专项审核与正式资格仍分开处理，local_experimental 和默认关闭不变。该人工观察没有新增资格 JSON、qualification_id 或 released 授权。

最终工程快速检查只运行 FAST、Backend 迁移/边界和管理前端离线测试；具体数量见 [收尾记录](deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md#15-r2c-1e-工程收尾与人工验收)。本轮未请求 Provider/NPU。`a256569` 是已提交的 Phase II 切换基线；`0cf64f6` 是需要整体回退旧管理装配时的 Phase I 参考点，不能以重置工作树代替审阅和完整回滚。

业务 Tool 组织与专项回归：Definition/Handler/validator 在 business_tools 的对应 Tool 模块，唯一装配入口为 registry.bind_tools；旧 runtime/tools.py 与 bindings.py 已移除。离线可运行 `python -m unittest apps.ai_service.tests.test_business_tools`；backend 测试层已包含该合同测试，前后 Definition/DTO 基线不因目录迁移重写。新增 Tool 操作见 [开发指南](deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md#2-新增业务-tool)。

## 管理端 Tool 授权与历史候选（R2D-1D）

1. 按本页已有命令启动管理服务并显式启用 Assistant；原 Normal/Streaming 启动参数保持不变。
2. 打开「系统设置 → Assistant Tool 授权」。首次读取只显示原有选择，不写文件。按需勾选/取消历史水质，再点「保存 Tool 授权」。保存前保留 Water/Knowledge 原选择，评分兼容项不可执行。
3. 保存只写管理端的 `outputs/tool-policies/management_assistant_policy.json`，不写 Prototype 共用文件。其他窗口已修改时必须重新读取再保存；损坏配置不会自动清空或恢复默认。
4. 保存使旧网络确认失效；下一条消息重新确认。已 claim 的 Turn 使用冻结授权，撤销对下一 Turn 生效；History/draft 保留。重新启动后读取同一管理配置，未存在覆盖时继续只读继承。
5. **历史仍未开放真实试用**：界面授权不等于发布。candidate 只为 Qwen OFF / Normal / 历史单工具 / 1/1/2 准备；普通对话继续使用原两工具。不要编辑 JSON 的 status/enabled，也不要用旧 Prototype Tool Manager 写历史名称。

离线验证（全部使用临时数据与 Fake SDK）：

```powershell
.\.venv\Scripts\python.exe -m unittest apps.ai_service.tests.test_management_policy apps.ai_service.tests.test_history_candidate apps.ai_service.tests.test_water_history_tool
node --test apps/management_web/tests/*.test.mjs
```

后续真实单案例的准备、批准及 Scope 发布必须分开，见 [集成合同](INTEGRATION.md#历史-tool-授权与候选边界r2d-1d)。R2D-1E 已提供独立的历史单案例资格 CLI（默认 Dry-run，见下节）；现有 Streaming 资格脚本仅验证原两工具，不能代替历史资格。设置功能不是生产权限中心，未来账户/RBAC 需在同一 API 前增加身份与服务端授权，不能只隐藏按钮。

R2D-1D 验证：新增 Policy 7 项、历史候选 HTTP 10 项；Backend 整层 163 项、管理 HTTP/API 93 项、管理 Streaming 资格基础设施 17 项、FAST 164 项及前端 Node 55 项通过（测试层之间有覆盖重叠，不作唯一总数相加）。原六条 Normal/Streaming 路径和三个两工具资格计划 hash 基线不变；无真实 Provider/NPU 请求。历史 HTTP 成功路径仅在测试中 stub 未发布准入，真实 candidate 仍关闭。Markdown 本地链接/锚点、Python/JS/JSON 语法、diff 与改动文件敏感模式检查通过。

## 历史 Tool 单案例资格准备（R2D-1E）

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_history.py --case valid-history --dry-run
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_history.py --case no-data --dry-run
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_history.py --case partial-history --dry-run
```

省略 `--dry-run` 同样不联网。每个进程只有一个案例；三个案例各自计划 hash，不能复用其他案例或旧两工具授权。真实实验需先审阅计划、逐案例获批，命令和终端人工预览见 [历史资格操作说明](deep-dive/HISTORY_QUALIFICATION.md)。本阶段不开放 Web candidate，也没有启动历史试用的参数。

离线：`python -m unittest apps.ai_service.tests.test_history_qualification apps.ai_service.tests.test_streaming_qualification`；资格基础设施变更运行 `python scripts/dev/run_tests.py qualification`。Source/旧范围回归：`python -m unittest apps.ai_service.tests.test_water_history_tool apps.ai_service.tests.test_history_candidate`。这些测试均阻断真实模型网络，仅用隔离数据和 Fake SDK。

R2D-1F准备阶段将候选升级为1024 tokens/请求的v2计划。当时仅Dry-run；固定15 Turns/最多30请求的授权现已由用户执行完毕，不能再次复用。完整hash与执行记录见[历史资格指南](deep-dive/HISTORY_QUALIFICATION.md#7-r2d-1f固定15样本批次)，当前开放操作见下节。

## R2D-1G：历史水质单工具本地试用

**当前状态：local_experimental，默认关闭，非released。** 用户已完成固定15样本（30请求），技术全部通过，并批准精确Qwen范围。回答质量未审核；本轮开放只用Fake SDK回归，不重跑真实资格。结果和限制见[历史资格记录](deep-dive/HISTORY_QUALIFICATION.md#9-r2d-1g真实批次通过与本地实验开放)。

以下在同一个正常用户PowerShell终端执行。先停止自己已启动的8766服务器；不要关闭其他进程。使用既有私有Qwen凭据，无需读取、复制或打印Key：

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_AI_Prototype'
$env:FISHERY_SIM_INGEST_TOKEN = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
$managementServer = Start-Process -FilePath .\.venv\Scripts\python.exe `
  -ArgumentList '-m','apps.management_web','--enable-ingestion','--enable-assistant',`
    '--assistant-multi-round-trial','--assistant-streaming-trial','--assistant-history-trial' `
  -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru
.\.venv\Scripts\python.exe -m apps.simulator --scenario normal --seed 42 --interval 10
```

服务器与模拟器继承同一开发接入令牌；不打印/保存该令牌。模拟器默认每10秒上报，当前真实窗口仍是10秒均值。可换成`low_oxygen`等既有场景。原Prototype Web不受影响。若只试历史，可省略两个既有multi-round/streaming试用参数，历史仍为Normal 1/1/2。

网页 `http://127.0.0.1:8766`：

1. 「系统设置 → Assistant Tool 授权」：保持已有选择，显式勾选历史水质并保存。不会写旧Prototype Policy或自动勾选其他Tool。
2. 「AI智能助手」：选择Qwen 3.8 Flash、监测设备及Normal，点击输入区的「历史查询」。页面显示「下一条：历史水质查询」及本地实验状态，预算仍为1/1/2、每请求最多1024 tokens。聊天页不再提供执行Profile选择器。
3. 确认「本次可用工具」为「历史水质」，勾选本次联网确认，问「过去10分钟溶解氧有什么变化？请说明数据覆盖」。不必等待完整30分钟，稀疏历史应返回PARTIAL；区间没有数据返回NO_DATA。
4. 核对历史Tool卡片、Source类型、唯一Final、Token/Steps。历史不能证明当前状态，不判断持续低氧或恢复；NO_DATA不是执行错误。Stop/超时/截断/失败不提交成功History，不自动重试或切换执行方式。
5. 历史查询成功后恢复普通提问，也可点击「取消历史查询」。成功History保留；变更业务操作、响应模式、模型、设备或实际工具范围均清除联网勾选。历史查询失败保留该业务操作，须用户处理后再次确认；不会自动重跑。模型/设备切换仍按原规则清会话。普通提问由模型在已授权的当前水质/Knowledge中选择；历史不自动加入该组合。

权限、Scope、版本或开关不匹配时发送被禁用/联网前拒绝，并显示原因。旧确认revision不能复用；启动开关随应用epoch冻结，运行中的设备/授权不随页面变化。

**关闭与回滚**：先在模拟器终端按Ctrl+C，再停止自己启动的服务器，去掉历史开关重启（既有两工具参数可保留）：

```powershell
Stop-Process -Id $managementServer.Id
.\.venv\Scripts\python.exe -m apps.management_web --enable-ingestion --enable-assistant `
  --assistant-multi-round-trial --assistant-streaming-trial
```

这不会删除SQLite或用户授权。新epoch使旧页面确认失效；刷新后点击「历史查询」会显示服务器未启用的具体原因，确认框与发送均禁用。需要同时撤销授权时由用户在设置中取消历史。无需删除历史数据、资格报告或修改JSON。全部联调结束后可执行`Remove-Item Env:\FISHERY_SIM_INGEST_TOKEN`。

产品Normal预算通过既有Adapter的内部`transport_output_token_limit`编码，严格Normal≤1024/Streaming≤512、retry=0；仅历史精确Scope装配Normal上限。没有使用development资格Adapter，也没有修改Tool循环、Prompt、统计或原两工具配置。

### R2D-1H：可用状态与三工具候选

- 「本地实验」是许可状态，启动开关和用户授权仍须分别满足。历史查询显示未启用时，重新勾选联网确认不能解决；按页面提示启用启动参数或到系统设置授权，再点「刷新可用状态」。禁止发送时确认框同时禁用且取消勾选。
- 历史查询在 Streaming 或其他模型下会明确提示选择 Qwen / Normal；页面不会替用户切换模式。历史成功后恢复普通提问并清除确认；已成功的对话不丢失。
- 三工具自主选择已建立独立 `management-normal-three-tools@1` candidate（当前水质、Knowledge、历史水质；Qwen OFF / Normal / 2/2/3 / 1024 tokens / retry=0 / 120秒），**未开放**。它不属于现有启动参数许可，也没有新增网络命令或模型资格。两个旧 Scope、历史单工具 Scope 和预算原样保留。
- 开放三工具前，须另行批准该精确候选计划，逐案例验证三类选择、Current→History、History→Knowledge、提前Final、参数、Result传递、Ledger/提交及三来源需求的预算限制，再独立批准本地试用。三个可选工具不表示可执行三个；当前预算最多两个，不能宣称获得未执行的第三来源。离线 Fake 不能替代真实选择证据。

R2D-1H 离线验收结果见[历史资格说明](deep-dive/HISTORY_QUALIFICATION.md#10-r2d-1h交互修复与独立三工具候选)。

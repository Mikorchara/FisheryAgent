# 管理平台启动、联调与验证

## 环境

Python 3.11+，使用根项目已有 Flask 依赖；SQLite、生成器和 HTTP transport 使用标准库。Node 用于前端测试，无需 npm install 或构建。所有命令在 `D:\CodexProject\Fishery_AI_Prototype` 执行；首次环境配置见根 [BUILD_RUN](../../docs/BUILD_RUN.md#环境与启动)。

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

默认仍只授权水质。需要 Knowledge 时，在仓库根目录运行 `python -m fishery_ai web`，打开原 Prototype `http://127.0.0.1:8765` 的 Tool Manager → Assistant 标签，勾选项目知识检索并保存。该操作使用已有共享 Policy，不需发送模型请求；不要手工复制 Tool Schema 或修改默认配置。两网页共用授权，调整会影响原 Prototype 的下一次请求。

管理端执行 `python -m apps.management_web --enable-assistant`，打开 `http://127.0.0.1:8766` → AI 智能助手，刷新后核对“可用 Tool”含 `search_fishery_knowledge`。选择 Qwen/Ollama，逐次确认模型请求，再问“请检索项目资料，说明鳗鲡低氧表现”；观察项目背景 Knowledge 卡片、命中数/NO_MATCH。当前水质问题仍用 Monitoring Tool，不得把知识命中解释为当前 DO 或疾病确诊。真实模型请求须有用户授权；启动与授权配置本身不联网。

默认仍为 1/1/2。若模型同轮请求两项，TOOL_CALL_LIMIT 是安全拒绝；单轮配置第二次请求继续调用 Tool 为 TOOL_ROUND_LIMIT。双 Tool 顺序试用须按下一节显式开启。

离线专项：`python -m unittest apps.management_web.tests.test_assistant` 与 `node --test apps/management_web/tests/assistant-ui.test.mjs`。前者在临时 SQLite 上通过正式 Assistant/Registry/Executor/Source Gate/Trace 执行 Fake Provider HTTP 闭环，阻断所有外部 socket；后者运行实际前端模块的离线 DOM 行为。不是模型真实资格或回答质量证明。

## R2B-4：Normal Multi-Round 本地试用

```powershell
.\.venv\Scripts\python.exe -m apps.management_web --enable-assistant --assistant-multi-round-trial
```

访问 `http://127.0.0.1:8766` → AI 智能助手。同时接入模拟器时，在设置下文开发令牌后追加 `--enable-ingestion`。启动本身不调用模型；每次发送仍须明确确认。

- 先在原 Tool Manager → Assistant 授权水质查询与项目知识检索，并保持 LLM Tool Calling 开启。管理端实际执行集合必须恰好为这两个 Tool；不会改写用户 Policy，也不装配评分 Tool。刷新管理页面后核对 **Multi-Round · 本地实验（未真实验证）**、最多三次模型请求。
- Qwen 优先；Ollama 有独立精确实验 Scope，均未取得管理系统真实多轮资格，不继承旧 Prototype 的发布记录。固定 OFF / Normal，每轮最多一个 Tool，整 Turn 最多 2 Calls / 2 Rounds / 3 Requests、retry=0。
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

R2B-3.4 边界测试：`python -m unittest apps.ai_service.tests.test_service apps.management_web.tests.test_ai_boundary`。前者直接创建业务 Service + 临时 Monitoring/Fake Provider，复用调用方 RequestHandle，无需启动 Flask；后者验证 Web 令牌不传入业务、HTTP 门禁优先执行及 source identity。原 Assistant/Knowledge HTTP 测试全部保留，内部 patch/import 更新为 `apps.ai_service.service` / `bindings`。启动与端口不变，不新增 AI 服务进程。

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

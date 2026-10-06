# Analysis Model Tool Calling v1

日期：2026-10-06。只读、Normal、最多一个 Tool Call / 一个 Tool round / 两次模型请求；不是 Agent。本轮 Codex 未联网、未改凭据、未修改正式 Fishery_Project，未 commit / push。

## Preset 资格收口

从当前 presets.json、固定 ProtocolSpec 和 Provider 配置核对身份，并检查用户新增资格记录及对应安全 Tool Trace；没有使用 Managed Evidence 代替发布合同。

| Preset / exact Identity | 资格结果 | 发布合同 |
| --- | --- | --- |
| Qwen 3.8 Flash：dashscope / openai_chat / https://dashscope.aliyuncs.com/compatible-mode/v1 / qwen3.8-flash；dashscope_chat v1 | 用户独立资格验证完整通过；唯一合法 get_current_water_quality({}) → NO_DATA → role=tool → 最终正文 stop；概念题直接回答且 stop | tool_calling=SUPPORTED，1.0.1 → 1.0.2 |
| DeepSeek Flash：deepseek_api / openai_chat / https://api.deepseek.com / deepseek-flash；deepseek_chat v1 | 最新用户记录完整通过，Tool 闭环 NO_DATA / stop、概念题直接回答 stop | SUPPORTED / 1.0.2 |
| Ollama：ollama / generic_openai_chat / http://127.0.0.1:11434/v1 / qwen3.5:4b；ollama_openai_chat v1 | 上一轮独立资格验证通过 | 保持 SUPPORTED / 1.0.2；本轮合同完全未变 |

Qwen 用户记录时间 2026-10-06T04:53:25.594374+00:00，共 3 次请求，耗时 7.172 秒；Usage Input 881 / Output 78 / Total 959。DeepSeek 用户记录时间 2026-10-06T04:53:45.906025+00:00，共 3 次请求，耗时 3.500 秒；Usage Input 869 / Output 252 / Total 1121。这些是用户已执行的请求，本轮 Codex 请求数为 0。

DeepSeek 概念题达到配置的输出上限并被截断，足以说明预算导致本次未正常结束；不说明 Tool Calling 不支持。Qualification 现改为要求“一两句话简短回答”，且仅概念题使用独立 384 输出 token 上限；闭环两次请求仍各为 192、retry=0。仍必须概念题无 Tool、非空正文、finish_reason=stop 才算通过；不放宽成功条件、不自动重复请求。维护者脚本仍由用户显式运行，不自动发布。

Qwen 仅增加 Tool 固定能力、patch 版本及独立维护记录；Thinking / Streaming 已发布组合、其他能力与默认 Qwen 均未修改。详细合同见[Preset 发布说明](PRESET_PUBLICATION.md)。

## 数据流与代码位置

```text
共享 CurrentWaterQualityReader 捕获开始时的 view
→ Orchestrator：Snapshot → Diagnosis → RAG → Analysis Context
→ 固定 Analysis ModelRequest
→ 当前冻结 Analysis Policy
   ├─ 没有启用工具：原 complete / stream 路径
   └─ 有授权工具 + Normal：ToolCallingService.run_request
        → Capability gate → Registry-owned Tool Definitions → Request #1
        ├─ 普通正文：直接结束，不预执行工具
        └─ 唯一 Tool Call：Policy + Registry + ToolExecutor
             → role=tool JSON → Request #2（tool_choice=none）→ 最终 JSON 正文
→ AnalysisResult + 合并 Usage + Tool Activity + 安全 Trace
```

- [application.py](../../src/fishery_ai/application.py)：固定流程和结构化结果保持原位；只在授权时复用协调器，不复制 Tool Loop 或 Executor。
- [tool_conversation.py](../../src/fishery_ai/tool_conversation.py)：Assistant 仍用 converse；Analysis 传入自己已有的 ModelRequest，执行共用 run_request。首轮保留 Facts / Rules / RAG；Registry 是 schema 与执行定义的单一来源。
- [tools/policy.py](../../src/fishery_ai/tools/policy.py)：保存的 Analysis 选择现在生成有效权限；包内默认仍关闭。Web 每个新请求捕获一次冻结 Policy，后续保存不影响在途请求。
- [contracts.py](../../src/fishery_ai/contracts.py)：AnalysisResult 增加 AnalysisToolActivity；原 ObservedFacts / RuleFinding / Evidence 不改变。
- [web.py](../../src/fishery_ai/web.py)：注入既有共享 Registry、Reader 和 Analysis Policy；真实请求仍需确认，CredentialStore 和不可变 CredentialSnapshot 不变。

## 门禁与取消

- Runtime 的 tool_calling 不是 SUPPORTED 时，在模型请求前返回 OPTION_UNKNOWN / OPTION_UNSUPPORTED；不使用 Probe 临时权限，不写 Evidence。
- 启用 Analysis Tool 却选择 Streaming：TOOL_STREAMING_NOT_IMPLEMENTED，不降级，不创建模型流。关闭 Tool 时原 Normal / Streaming 保留。
- 工具请求 retry=0，两次请求共用同一个不可变 RuntimeSnapshot / CredentialSnapshot。原 RequestHandle 在请求前后、执行前后与第二轮前检查取消。
- 一次多个调用 → TOOL_CALL_LIMIT；第二轮继续请求 Tool → TOOL_ROUND_LIMIT。未知工具、参数错误与执行失败沿用安全错误码；不发送第三轮，不返回 traceback。
- USER_CANCELLED 不生成最终结构化结果，不重试、不写能力证据。底层取消沿用已验证传输机制，不宣称远端计费一定停止。
- Assistant 单轮路径不改变触发语义；Manual V1/V2 仍为 Raw 请求，不执行返回的 Tool。

## 观测一致性

分析开始时的 immutable reading、Diagnosis Findings 和 RAG Evidence 不被 Tool 结果覆盖。首轮授权时额外提供固定快照的 source / retrieved_at / evaluated_at 元数据；这些作为 user 数据发送，不提升为 system 指令。

Tool 仍只经 CurrentWaterQualityReader 查询当前 Store，并使用 Domain 的 query-time Freshness 和 Diagnosis。Tool 观测保存自己的 observed_at / retrieved_at / evaluated_at / source / 数值 / Findings。若与固定 reading 的任一合同字段不同，则记录 snapshot_comparison=different，并由程序向 Uncertainty 添加差异提醒。若 Tool 查询为 NO_DATA，保留已捕获的 Facts，同时提醒它不代表当前仍有效。

没有强制预执行所有工具、自动 Apply、normal fallback、规则复制或 Snapshot mutation。Tool Result 只是数据，不能升级为新的 system instruction。

## 右侧 Tool Activity

位置：正式 `<main id="results">`，Model Inference 后，默认折叠。左侧 Tool Modal 只配置授权，不展示执行日志。

显示允许列表、模型是否请求 Tool、实际是否调用、安全参数摘要（无参数成功仅为 `{}`）、Tool 名称、Result 状态、耗时、Request #1 / #2 状态、逐次与合计 Usage、Finish reason。Tool 读取时的完整 canonical 观测单独放在记录区；不替换 Observed Facts。

没有调用明确显示“未调用”。参数拒绝与取消不伪称完成执行；取消时没有完成 Result 则显示结果未确认。渲染仅用 textContent，不插入模型返回的 HTML，不展示完整 Prompt、私有路径、Authorization 或 Secret。Streaming 开始及下一次结果会清除上次活动，避免旧记录残留。

Trace 保留程序允许的步骤、Usage、耗时与结果状态，**不记录 Tool 参数原文、Tool 观测正文或模型正文**。共享步骤 Trace 与 Analysis Trace 共用 request_id / trace_id，并标记 application_mode=analysis；统计时不能把同一 trace 的两个记录重复累加。

## 首轮自动验证（历史）

全部离线，真实资格记录只用于维护者核对；测试使用临时存储、虚构 Secret、Mock Gateway / transport，不读取私有凭据。

| 范围 | 结果 |
| --- | --- |
| Analysis Python targeted | 25 项：19 应用层 + 6 Web；Policy 开关、UNKNOWN / UNSUPPORTED、无调用 / 成功调用、NO_DATA / 异常 / STALE、观测差异、单轮限制、取消、Usage / Trace、凭据快照、Streaming 门禁、关闭 Tool 时的请求状态 |
| Preset targeted | 41 项；包括独立概念预算和 length 仍不通过的测试 |
| T1–T5 / Tool Policy | 对应测试持续通过；默认关闭的 Analysis、Assistant 与 Manual 由全量覆盖 |
| Activity / Tool Manager Browser targeted | 17 项通过；新 Activity 5 项 + 既有管理 12 项 |
| Full Python | `python -m unittest discover -s tests`：651 项通过，26.064 秒 |
| Full Browser | `node --test tests/test_browser_streaming.cjs`：161 项通过，543.211 ms；Node DOM / fetch fixtures |
| JS syntax | app.js 与 Browser 测试文件通过 |

Markdown 本地链接检查：53 条有效。git diff --check 通过。扫描 139 个 Git 可见源码/文档文件，未发现疑似凭据或用户私有路径；既有 Manual V2 测试中的虚构 URL 凭据是拒绝非法 URL 的 fixture。没有 .env、manual.env、outputs 或 lock / staging / recovery 文件被 Git 跟踪。扫描不读取真实凭据文件。

工作树：21 个已跟踪文件修改，3 个新增文件（本报告与两份 Analysis 测试）。HEAD 保持 755411639f11457ba24c90527e7648a5dd77ec84，未 commit / push。本轮真实模型请求为 0，未修改正式 Fishery_Project。

## 人工验收

1. 正常用户进程启动 Web，Apply normal / low_oxygen / stale / invalid；先不勾 Analysis Tool，确认 Normal / Streaming 原流程正常。
2. 选择 Qwen 3.8 Flash 或 Ollama Preset，优先 OFF + Normal。在 Tool 管理的 Analysis 标签勾选并保存 get_current_water_quality；左侧不出现执行记录。
3. 询问当前水质并确认真实请求；右侧展开 Tool Activity。允许模型直接回答，此时必须显示未调用；若调用，核对 `{}`、OK / NO_DATA、两次请求状态、Usage、规则与时来源。
4. 启用 Tool 后切换 Streaming，确认 TOOL_STREAMING_NOT_IMPLEMENTED；不要把它当 Provider Streaming 不支持，也不要自动切 Normal。
5. DeepSeek 最新资格已通过并发布 1.0.2；可在正常用户 Web 进程选择 OFF + Normal 验证。Managed UNKNOWN / UNSUPPORTED 仍必须被拒绝。
6. 生成过程中使用 Stop，确认 USER_CANCELLED、无第二轮续发或部分 JSON 最终结果，loading 正常解除。
7. 在途请求期间 Apply 新情景：固定 Facts 保留开始 reading；若 Tool 读取新数据，Activity / Uncertainty 明确区分，两份观测不混合。
8. 分别回归 Assistant 开发对话和 Manual V1/V2；Raw tool_calls 仍不自动执行。

本轮不新增 Tool、Agent、Streaming Tool Calling、Analysis 评分、Assistant 主界面或凭据功能。


## 第二个 Tool 与结构整理（2026-10-06）

### DeepSeek 发布

用户新记录 deepseek-flash-r1-tools-20261006T061029872004.json 及对应安全 Trace 完整通过。exact Identity 与固定协议匹配，三次返回模型均为 deepseek-flash；唯一合法空参数调用、NO_DATA、第二轮正常 stop、概念直答正常 stop。发布 Tool 能力及 1.0.2，维护 metadata 保存独立依据。用户请求数3、input871/output69/total940；本轮 Codex 真实请求0。上文首次概念题 length 记录是历史失败，已由本次成功替代。

### 结构化失败调查与最小修复

CODE / TRACE CONFIRMED：Trace e82374d791cc410d87e6813feacb78eb 的 Qwen 闭环完成、Tool=OK、Request #2=final_answer、finish_reason=stop，但 structured_parse_ok=false。代码 follow-up 保留原 system JSON 约束，没有丢失初始上下文；普通 ToolConversation 之前只追加 assistant / tool，没有在结果后重申 Analysis 格式。

INFERENCE：模型这次未满足 JSON 或字段类型合同；stop 表明不是已记录的 length 截断。Trace 故意不保存正文，无法确认当时为纯自然语言、混合 Markdown 还是字段格式错误，不能宣称已重现唯一原因。

最小修复：共享 run_request 新增可选 final_response_instruction。仅 Analysis 在第二轮 Tool Result 后加程序写定的 user 提醒：只输出一个 JSON 对象或 json fenced block，inference 为字符串，recommendations / uncertainty 为字符串数组，保留两份观测边界、不再调用 Tool。原 system 和所有数据不变。Assistant、Qualification、Probe 不传该提醒，原流程不变；没有第三次修复调用、JSON repair 或新 Provider 参数。

parser 仍只接受完整 JSON / fenced JSON 和既有字段类型，拒绝任意正文、HTML、错误对象/数组；增加 RecursionError 安全回退。原文保留，parse=false 继续明确显示。Prompt 不能保证真实模型永远遵循格式；需人工观察。

### 评分与合同

WaterQualityScoringService 和 WaterQualityScore 位于 water_quality_scoring.py，无 I/O。正常区间从 DiagnosisService 的共享常量取得，原规则数值/行为未改变。penalty 为 temperature10、pH40、DO20，集中且只读；分项 clamp 到0–100，未舍入分项求平均，最终保留1位小数。34℃/pH7.5/DO2.2 → 60/100/44 → 68.0 WARNING。

score_current_water_quality({}) Handler 只捕获 Reader view，再调用服务；Result 包含 score、grade、components、missing_components、partial、quality、freshness、warnings、scoring_version、实验非专业标识、独立 water_quality 与 evaluated_at。NO_DATA→null；INVALID→NOT_SCORABLE/null；PARTIAL→已有有效指标平均；STALE不扣分但 warning=SENSOR_STALE。等级只是实验显示，不替代 Findings。

### 注册、授权与执行

Policy 移到 tools/policy.py；旧 tool_policy.py 删除，不留重复兼容实现。查询 Handler 移到 tools/handlers/current_water_quality.py；评分 Handler 位于 tools/handlers/water_quality_score.py。imports / patch 目标 / 文档更新，包顶层既有执行 API 保留；Registry 构造器增加可选 scoring 依赖，旧两参数调用保持可用。

Catalog 共两个可执行工具、三个不可执行占位；评分显式 Experimental。包内默认不变：Analysis[]，Assistant[get_current_water_quality]。用户可以分别选择评分或同时授权两工具；仍最多执行一个调用、一个 round、两次模型请求。未知/未授权/多调用/第二轮继续调用依旧安全拒绝。

ToolStatus 新增 PARTIAL / NOT_SCORABLE，属于正常业务结果，继续交给第二轮解释。通用 Activity 不按工具名解析分数，安全 JSON 区直接展示任意已执行 Result；Trace 工具名来自 Registry allowlist，只记录元数据，不写评分事实或完整模型正文。初始 Facts、Diagnosis、RAG 不被评分覆盖。

### 本轮自动验证与人工验收

自动测试完全离线，使用临时文件、虚构凭据、Mock SDK / Gateway、网络阻断。结果见本节交付更新；新增评分服务/Tool17项，Analysis32项（应用25+Web7）、Development Web24项、Browser评分与通用结果2项，原默认与安全测试保留。

人工验证：选择已发布 Preset OFF + Normal，Apply 34℃/pH7.5/DO2.2。Tool Manager 的 Analysis 标签只勾评分并保存，问“请使用水质评分工具评估当前水质，并结合已有分析结果解释评分”。右侧 Activity 应为 score_current_water_quality、OK、68.0，结构化结果仍保留 Facts / Findings / Evidence。再同时授权两工具，分别问重新确认水质/打分/一般分析；模型可直接回答或择一调用。返回两个调用应 TOOL_CALL_LIMIT，不自动续轮。

Assistant 不新增主界面：Tool Manager Assistant 标签勾评分，进入 Development / Test 的离线 Mock，问“请给当前水质打一个分”；应得到评分和单轮解释。取消、NO_DATA / PARTIAL / INVALID / STALE、原查询工具、Normal/Streaming与Manual回归也需人工检查。默认关闭评分，不主动发真实请求。

标准新增 Tool 流程见[ADDING_A_TOOL](ADDING_A_TOOL.md)。本轮没有 Agent、Streaming Tool Calling、新 Provider、第三个 Tool、RAG / Grounding 改动或正式项目修改；不 commit / push。


### 本轮最终回归与工作树

| 检查 | 结果 |
| --- | --- |
| scoring + Analysis targeted | 49 项通过，1.019秒（scoring17 / Analysis32） |
| T1–T5 + Preset + Policy targeted | 216 项通过，5.778秒 |
| Activity / Tool Manager Browser targeted | 19 项通过 |
| full Python | python -m unittest discover -s tests：676 项通过，30.010秒 |
| full Browser | node --test tests/test_browser_streaming.cjs：163 项通过，602.115ms（离线 DOM / fetch fixtures） |
| JS syntax | app.js / Browser 测试通过 |
| Markdown links | 60 条本地链接有效 |
| git diff --check | 通过 |
| 敏感扫描 | 144 个 Git 可见源码/文档，无风险；既有虚构 URL 凭据拒绝 fixture 已核对；不读取真实 .env、manual.env 或私有凭据 |

当前工作树累计包含上一轮未提交实现：30 个 tracked 文件修改、2 个旧路径删除（模块迁移）、10 个新增文件。HEAD 保持 755411639f11457ba24c90527e7648a5dd77ec84。旧模块无重复兼容实现；默认 Tool Policy、Credential、Manual、Gateway / Adapter、RAG、Telemetry 未改变。Preset 非 Tool Capability、连接、ProtocolSpec、Variants 不变，Ollama Template 与 HEAD 完全相同。真实凭据、outputs、lock / staging / recovery Git 可见数0。未 commit / push，等待人工验收第二个 Tool。

# 管理 Assistant Streaming 资格与本地试用

**R2B-5E：三个真实案例技术 PASS；用户已批准 Qwen 精确两工具 local_experimental。默认关闭，人工回答质量待审，非 released。**

本入口只验证管理数据绑定，复用已有资格 Adapter、协议观察、正式 ManagementAssistantService 和 ToolCallingService。每个进程只处理一个固定案例，没有批量、重试、failover 或发布写入。

## 1. 精确候选范围

| 项目 | 当前范围 |
|---|---|
| Preset | `dashscope-qwen38-flash-r1`，合同 `1.0.2` |
| Identity | `dashscope / openai_chat / https://dashscope.aliyuncs.com/compatible-mode/v1 / qwen3.8-flash` |
| Protocol | `dashscope_chat@1`，`max_tokens`、`stream`、`enable_thinking`、`stream_options` |
| Prompt | `ASSISTANT_BOUNDED_MULTI_ROUND@1`，使用正式内容，不追加实验 System Prompt |
| History | `UNTRUSTED_TRANSCRIPT_V1@1`，三个首批案例均 EMPTY；计划另绑定 framing hash |
| Tool | 恰好 `get_current_water_quality` + `search_fishery_knowledge`；Schema/description hash 必须匹配 |
| 水质绑定 | `management-current-water@1`；正式 MonitoringService / SQLite / Domain Analysis |
| Knowledge 绑定 | `management-project-knowledge@1`，`legacy:eel_knowledge.json / 1.0 / portable` |
| 预算 | 每请求 512 output tokens，最多 2 Calls / 2 Rounds / 3 Requests，每轮一个 Tool，retry=0，整 Turn 120 秒 |
| 当前发布 | 管理独立配置 `enabled=false / local_experimental`，无 qualification_id / validated_at；显式启动参数开启，不代表人工回答质量通过 |

以上来自当前维护者合同。Dry-run 重新计算精确 Scope，与 [管理配置](../../ai_service/resources/assistant_streaming.json) 比较；Identity、协议、Prompt、History、Tool 或绑定不匹配直接拒绝。输出预算必须与该范围的 512 一致。配置、SDK 版本、案例、问题、Scope、预算、History framing 改变都会影响计划指纹，不沿用旧批准。

本轮核对的 Scope SHA256：`fc476b2e9ac19046b0127e65d70dc1488016c04f9dde29698d681c6047708e90`。它不代表资格通过；未来使用重新计算的 Dry-run 为准。

## 2. 固定案例和预算

| case | 隔离水质 | 预期真实路径 | Requirement | 预期请求 / 硬上限 |
|---|---|---|---|---|
| `direct-final` | DO 6.4 | 概念直答，无 Tool | AUTO | 1 / 3 |
| `current-water` | DO 6.4 | 水质查询 → Final | CURRENT_OBSERVATION_QUERY | 2 / 3 |
| `low-oxygen` | DO 2.2 | 水质查询 → Knowledge → Final | 当前查询 + 项目检索 | 3 / 3 |

每次只审批一个案例、一次执行。全部三个若逐一获批，预期共 6 次请求，理论最多 9 次；这不是本轮联网授权。模型提前 Final、错选、无调用、NO_MATCH、截断或 Provider 错误都是本次结果，不自动补跑。

真实规则仍来自正式服务。固定 Seed 42、28℃、pH 7.5、10 秒有效窗口；值是人工资格夹具。临时 SQLite/Policy 位于 `outputs/assistant-qualification/.management-work/` 的独立目录，结束清理；不读写用户管理库或 `outputs/tool-policies`。仅冻结夹具时钟以防等待模型导致数据自然过期，不代表生产新鲜度实验。无视觉数据，无新采样，无原型 Snapshot 回退。

## 3. Dry-run 与逐案例授权

在仓库根目录执行，默认不联网；显式 `--dry-run` 便于审阅：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_streaming.py --case direct-final --dry-run
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_streaming.py --case current-water --dry-run
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_streaming.py --case low-oxygen --dry-run
```

Dry-run 不访问 CredentialStore、不创建 SQLite/Policy、不构造 SDK 客户端、不写报告。请审阅输出中的 `plan_sha256`、Scope、预算和固定案例，再明确批准，例如“批准 current-water 一次，计划 hash 为……”。**旧阶段的授权、其他案例的 hash、一次成功均不是后续请求许可。**

获批后仅运行对应一条命令，将占位文本替换为该次获批指纹；以下不是现在应执行的命令：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_streaming.py --case direct-final --confirm-network --plan-sha256 "获批的direct-final指纹" --review-answer
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_streaming.py --case current-water --confirm-network --plan-sha256 "获批的current-water指纹" --review-answer
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_streaming.py --case low-oxygen --confirm-network --plan-sha256 "获批的low-oxygen指纹" --review-answer
```

正式 CredentialStore → CredentialSnapshot → Runtime 由管理服务复用；不读取源码根 .env、不打印/复制 Key、不改 ACL。`CREDENTIAL_FILE_ERROR` 或缺失凭据时停止，不消耗授权去尝试别的入口；由用户正常 PowerShell 处理同一案例。Ctrl+C 复用原 RequestHandle 取消；不保证远端计算或费用停止。

`--review-answer` 仅在交互式 stderr 终端预览正式 Commit Gate 已允许的文本，过滤终端控制/方向控制字符；不进 JSON/Trace，状态仅 `PREVIEWED_NOT_APPROVED`。不要使用 PowerShell Transcript、Tee 或重定向保存预览。报告不能恢复正文；若没有预览，保留人工待审，不为取回正文自行补跑。

## 4. 安全报告和证据边界

安全 JSON 写入 `outputs/assistant-qualification/<run_id>.json`，experiment_version 为 `management-streaming-qualification@1`。复用现有拒绝覆盖、路径边界和同步落盘逻辑。

Trace 复用现有 run-local 内存 sink，最后随安全报告落盘；不写管理正式 assistant-traces.jsonl。`trace_recorded` 证明本次配置的 sink 成功，不替代真实 Web Trace 目录权限/持久化验收。

- 记录计划/Scope/hash、request/trace 对应状态、请求与实际 transport 次数、Provider model match、tool_choice、合法调用数量/名称与参数有效性布尔。
- 记录 SDK 分片类别/数量、组装一致性、finish_reason、Usage、SDK stream/client 关闭和 Handle I/O 关闭；每个实际 Tool 的状态、耗时、结果进入下一请求及清理后执行证据。
- Ledger 直接使用真实后端 Receipt，逐项保留；水质记录设备/批次/绑定/数值匹配布尔、时间、质量与规则版本；Knowledge receipt 区分检索完成、命中与 NO_MATCH。
- 不保存最终正文、query 原文、原始参数/Tool Result/Evidence、完整 Prompt、reasoning、控制令牌、凭据/私有路径或 traceback。

**产品 Commit Gate 与资格判定分别报告。** 脚本给正式 Assistant 指定该 case 的首项来源 Requirement；low-oxygen 的“还必须完成项目检索”作为附加技术断言，不能假称产品已支持组合 Requirement。产品可能安全完成，但由于预期路径/附加来源不匹配，资格仍 FAIL。NO_MATCH 可完成项目检索，不意味着存在 Evidence。

`technical_success=true` 仅给 `PENDING_MANUAL_REVIEW`，`release_eligible` 始终 false。本脚本经管理业务服务执行，**不声称真实运行经过 HTTP/SSE 或浏览器**（`http_sse_exercised=false`）；HTTP/SSE/前端交互由现有 Fake SDK 测试覆盖，真实网页链路须后续另批。

SDK 不公开原始 `[DONE]`，只记录 `NOT_OBSERVABLE_BY_SDK`。关闭调用完成不等于证明 Provider 停止计费。三次样本也不能证明长期模型选择稳定、检索相关性或语言真实性。

## 5. 审批、本地试用和回滚

用户已在正常 PowerShell 完成三次真实资格实验（本轮实现未联网）：

| case | run_id | 实际请求数 | 技术结果 |
|---|---|---:|---|
| direct-final | cd17c4158ca44a3c820af3022f59bf23 | 1 | PASS |
| current-water | 39f62c27cf1d4e3aab31e8cc6eecfb35 | 2 | PASS |
| low-oxygen | be51879050f44d14b6df52f4cabfce26 | 3 | PASS |

三份历史报告保留原 candidate 身份、PENDING_MANUAL_REVIEW 和人工预览状态，不改写报告或填造 qualification_id。它们是三个受控样本，不证明长期稳定性；报告未覆盖真实浏览器 HTTP/SSE。R2B-5E 用户另行明确批准精确范围的本地实验，回答质量审核留待后续，未声称其已通过。

启动：`python -m apps.management_web --enable-assistant --assistant-streaming-trial`。启动参数只将本进程冻结配置 enabled 置 true，磁盘仍 false。使用已有 Tool Manager 明确授权精确两工具，不自动改用户 Policy；在管理页选择 Qwen/Streaming，核对 local_experimental、512 tokens、最多三请求并逐次确认。Normal 默认1/1/2；如需其既有多轮可另加 --assistant-multi-round-trial。

网页待人工检查：新问题跟随、向上读历史暂停、编号/键盘跳转、预览原位转 Final、跨模式 History；各请求阶段 Stop、断线和截断撤销；验证只有一条成功回复。失败不自动重发或转 Normal；具体操作见 [BUILD_RUN](../BUILD_RUN.md#r2b-5eqwen-streaming-本地实验)。

回滚：Stop 后停止自己启动的 Web，去掉 --assistant-streaming-trial，以 `python -m apps.management_web --enable-assistant` 重启（可保留独立 Normal 多轮参数）。新 epoch 撤销旧确认/Session，Streaming 再次拒绝，保留数据库、Policy 和 Credential。Ollama、DeepSeek、评分及三工具 Streaming 未开放，History/真实数据老化与回答质量没有因这次授权获得资格结论。

## 6. 离线验证

```powershell
.\.venv\Scripts\python.exe -m unittest apps.ai_service.tests.test_streaming_qualification
.\.venv\Scripts\python.exe -m unittest apps.management_web.tests.test_streaming
node --test apps/management_web/tests/*.test.mjs
```

资格使用 Fake SDK、虚构凭据与网络阻断，验证真实管理服务、Registry/Executor、SQLite、正式 Prompt、Result 传递、Receipt/门禁及资源关闭；不是 scripted 响应作为真实资格证据。正式产品启动不导入 development/qualification。

本轮结果：新增资格 17 项（包含于管理 AI Service 30 项）通过；管理 HTTP/SSE、Normal/多轮/Knowledge 相关 73 项及管理 Node 51 项通过。现有 FULL QUALIFICATION 运行 167 项：166 通过，1 项因 Windows 无目录 symlink 权限跳过；reparse 拒绝测试仍执行。三个独立 Dry-run 均为 0 个真实请求。未重复运行无关 FULL PRODUCT，没有真实模型/NPU 或网页试用请求。

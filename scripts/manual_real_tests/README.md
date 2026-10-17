# 人工真实连接测试入口

以后从本页选择真实模型/外部连接测试。**自动离线测试由 Codex 执行；真实连接由用户在正常 PowerShell 亲自执行；回答质量另行抽样审核。** 日常增加功能不必反复安排回答质量研究。

本目录只有一个薄入口，调用原资格 CLI 一次，不复制 Provider、Credential、Tool 循环或报告实现。原 `scripts/qualification/` 路径和测试保留。应用启动、FAST / PRODUCT / unittest discovery 均不运行真实请求；新增入口的自动测试只 mock 子进程。

## 1. 管理平台：默认 Dry-run

在仓库根目录、既有 `.venv` 中执行。命令不会读取用户监测库、Policy 或凭据，也不联网。完整计划来自原 CLI，未创建新计划格式。

```powershell
$historyPlan = .\.venv\Scripts\python.exe scripts/manual_real_tests/run_qualification.py --target management-history --case valid-history | ConvertFrom-Json
$historyPlan.plan.plan_sha256
```

历史案例：`valid-history`、`no-data`、`partial-history`。固定 Qwen OFF / Normal / 历史单工具 / 1/1/2 / 1024 tokens / retry=0 / 120秒。

```powershell
$streamPlan = .\.venv\Scripts\python.exe scripts/manual_real_tests/run_qualification.py --target management-streaming --case current-water | ConvertFrom-Json
$streamPlan.plan.plan_sha256
```

Streaming案例：`direct-final`、`current-water`、`low-oxygen`；固定管理 Qwen OFF / Current + Knowledge / 2/2/3 / 512 tokens / retry=0 / 120秒。以实际 Dry-run 为准，不能由本入口选择其他模型或扩大 Scope。

## 2. 用户明确执行一次真实测试

先检查本次计划的目标、工具、预算、数据夹具和完整 hash。**以下不是给 Codex 的联网授权，不要自动执行。** 用户亲自运行带 `--confirm-network` 和刚生成的 hash 的命令，才授权该案例一次；旧文档中的 hash 不构成永久授权。

```powershell
.\.venv\Scripts\python.exe scripts/manual_real_tests/run_qualification.py --target management-history --case valid-history --confirm-network --plan-sha256 $historyPlan.plan.plan_sha256 --review-answer
```

```powershell
.\.venv\Scripts\python.exe scripts/manual_real_tests/run_qualification.py --target management-streaming --case current-water --confirm-network --plan-sha256 $streamPlan.plan.plan_sha256 --review-answer
```

`--review-answer` 可省略；提供时仅在交互终端临时预览，不保存正文，不代表审核通过。不要对预览使用重定向、Transcript 或 Tee。API Key 由原 CredentialStore → Snapshot 解析，入口不接收或复制 Key，不读取源码根 `.env`。

原 CLI 重新计算计划并核对 hash；参数/版本改变会拒绝。底层真实错误码和退出码原样保留，不自动重试、补跑、换模型或发布。失败或中断后先查安全报告与实际请求数，未知请求数不能当0。凭据访问失败由用户在正常环境解决，不复制凭据、不改 ACL。

安全 JSON 仍写入 Git ignored 的 `outputs/assistant-qualification/`；不新增正文/历史数据保存位置。报告保存失败时也不能直接重跑。关闭网页试用不禁止用户显式执行独立资格 CLI；后者始终使用隔离夹具/临时 Policy，不写用户授权或生产监测库。

## 3. 其他既有人工入口索引

这些仍由原 CLI 执行；不为统一名称强行增加不支持的 hash 参数。管理平台与旧 Prototype 的资格不能互相授予。

| 用途 | 原入口与边界 |
| --- | --- |
| 历史固定15样本 | [history batch](../qualification/qualify_management_history_batch.py)：默认Dry-run，三个新计划、各5次/总计最多30请求；只有单独批准该固定批次才使用确认参数，不自动加入单案例测试 |
| 旧 Prototype Qwen/DeepSeek/Ollama Streaming | [multi-round](../qualification/qualify_multi_round.py)：`--streaming --preset <固定ID> --case current-do --dry-run`，最多2/2/3；Streaming≤512，Normal≤256；不验证管理端 Monitoring 绑定 |
| 旧 Prototype 正式 Normal 多轮 | 同一 multi-round CLI，Qwen 使用 `--assistant-product`；独立旧 Runtime，真实执行需用户重新明确确认 |
| 旧单 manifest 来源测试 | [assistant turn](../qualification/qualify_assistant_turn.py)：`--manifest` 指向仓库内 JSON，默认Dry-run；真实执行确认只在内存中设置 |
| Preset 基础 Tool 维护检查 | [preset tools](../qualification/qualify_preset_tools.py)：`--help` 看参数；**没有 Dry-run/计划 hash**，没有 `--confirm-network` 直接拒绝且不请求，不能称作 Dry-run PASS |
| 旧 Ollama 已保存连接检查 | [local request](../qualification/qualify_local_preset_request.py)：`--help` 看受限 profile-id/Thinking/Streaming；没有 Dry-run，确认前直接拒绝；不要让 Codex读取用户连接配置 |
| NPU、真实设备、其他外部服务 | **尚无对应资格脚本**。未来实现后在这里登记实际入口、只读/副作用边界和断开方法；当前不造空脚本或宣称已支持 |

旧 Streaming 计划的一行式示例（不联网）：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_multi_round.py --streaming --preset deepseek-flash-r1 --case current-do --max-output-tokens 512 --dry-run
```

可选固定ID：`dashscope-qwen38-flash-r1`、`deepseek-flash-r1`、`ollama-qwen35-4b-r1`；有计划不表示已获管理平台的模型组合发布资格。Ollama是真实本机推理，也属于需要用户手动批准的外部连接测试。

批次只读准备命令：

```powershell
.\.venv\Scripts\python.exe scripts/qualification/qualify_management_history_batch.py --dry-run
```

## 4. 何时测试

- 薄 Tool 开发：参数/来源/未授权/取消/提交的专项离线测试，加一条实际HTTP链路；无需每个边界重复跑所有 Provider。
- 资格基础设施改变：运行离线资格测试；不因此自动执行真实批次。
- 新模型组合、Transport、Prompt/Schema或预算语义改变：用户集中审核精确范围，决定有限样本数，再亲自真实执行；不使用历史批准反复重跑。

## 5. 三工具 Normal 候选（R2D-2A）

候选 `management-normal-three-tools@1` 保持关闭。普通聊天仍在原 Current + Knowledge 范围选择；历史快捷操作保留已批准的历史单工具能力。以下资格探测使用隔离 SQLite、临时 Policy、正式多轮 Prompt/History 和新 Backend，不改变网页发布状态。

最小人工矩阵：`current-water`、`water-history`、`project-knowledge` 各一次（预期2请求），`current-history`一次（预期3请求）。合计4独立Turn，预期9、理论最多12模型请求，每次最多2 Tool/2 rounds/3 requests，Qwen OFF / Normal / 三工具 / 1024 tokens / retry=0 / 120秒。不是批处理，也不是长期稳定性证明。问题由固定案例提供，不自行改写。

先任选一个案例 Dry-run（默认不联网）：

```powershell
$selectionPlan = .\.venv\Scripts\python.exe scripts/manual_real_tests/run_qualification.py --target management-normal-selection --case current-water --dry-run | ConvertFrom-Json; $selectionPlan.plan
```

核对精确 Scope 与本案例完整 hash，用户明确批准这一次后才手动执行：

```powershell
.\.venv\Scripts\python.exe scripts/manual_real_tests/run_qualification.py --target management-normal-selection --case current-water --confirm-network --plan-sha256 $selectionPlan.plan.plan_sha256 --review-answer
```

其余案例须分别替换 `--case`、重新 Dry-run、使用对应 hash。每个命令只执行一次，不自动重试、补跑或换模型。失败/中断/报告保存失败先盘点安全结果，凭据错误不复制Key或改ACL。临时预览可省略，不写正文；安全报告复用 `outputs/assistant-qualification/`，含真实调用顺序、Result传递、Ledger、Source/Commit、实际编码、清理、Usage及延迟。单案例CLI不经过HTTP；管理HTTP组合路径另有Fake测试，不能宣称已有真实三工具网页资格。

技术成功后交回报告，由用户另行批准三工具 `local_experimental`。批准前不移除历史快捷操作，不改Streaming两工具范围。开放时只接入现有后端候选到普通Normal请求及其Bootstrap/确认，按维护者开关与Policy冻结选择；不需要新Registry、循环或执行Profile下拉菜单，也不应按问题关键词路由。
- 回答质量：单独安排人工抽样；技术 PASS、人工可用性观察和正式 released 是不同证据，不自动转换。

管理启动/回滚见 [BUILD_RUN](../../apps/docs/BUILD_RUN.md#一行式常用命令)。本轮仅离线准备，没有执行以上真实命令。

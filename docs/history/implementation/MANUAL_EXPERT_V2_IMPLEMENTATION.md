# Manual Expert V2 基础版实施报告

> 文档分类：**HISTORICAL**。历史实施 / 验证记录；数字、限制与能力结论只对应当时版本，不是当前全局状态。 保留 V2 独立实验、凭据隔离和 UX 实施记录；当前操作见 BUILD_RUN。 当前边界见[架构总览](../../architecture/CURRENT_ARCHITECTURE.md)。

日期：2026-10-03。本轮未 commit / push，供人工验收。

## 1. 定位与入口

Manual Expert 页面新增 `Saved Connection / V1` 与 `Manual V2 · 独立实验` 切换，默认 V1。V1 保留原 Saved Connection 请求路径；V2 不要求先保存 Profile。

V2 的 Service Name 是自由文本标签，不查 ProviderRegistry。第一版只允许 OpenAI-compatible Chat Completions，用户负责 URL、精确 Model 与 JSON 参数是否正确。页面 Model 是权威 ID：Raw JSON 可省略 model；显式 model 必须与目标 Model 一致。不会自动查询模型存在性或判断能力。后续 UX 调整见第 9 节。

## 2. 实验存储与 CRUD

新增轻量 `ManualExperimentStore`，固定启动目录 `outputs/manual-experiments/`，不复用 CustomProfileStore。文件使用随机 `experiment-<32 位 hex>.json`；Web 不能提交存储路径。

保存字段：id、name、service_name、transport、base_url、model、credential_ref、timeout、raw_request_body、notes、created_at、updated_at。UTF-8 编码，临时文件 flush / fsync 后原子替换；ID 校验限制路径。它不是 Secret 存储。

- New：清空当前 V2 草稿，不改 V1 草稿，不立即写文件。
- Save：未保存时创建，已有 ID 时更新。
- Save As：创建新 ID，保留原文件；名称由用户负责区分，不自动生成副本名称。
- Delete：确认后只删除 Experiment，不删除 Key。
- 切换 V1 / V2：双方字段保留，不互相转换或加入 Managed / Preset。

## 3. 独立凭据

路径复用 R2 的稳定项目标识算法：

`%LOCALAPPDATA%\Fishery_AI_Prototype\project-<项目路径 hash>\credentials\manual.env`

正式 `credentials/.env` 的路径、PROCESS_ENV > PROJECT_ENV > MISSING 优先级和行为不变。V2 仅从 manual.env 解析，启动 composition 明确传入空 process 映射；不读取正式文件、根目录 .env 或进程 Key。Credential Ref 留空时使用 AuthSpec.NONE，支持无凭据 localhost 服务；填写引用而缺失则返回 SECRET_MISSING。

页面提供刷新状态、Create / Set、Replace、Delete。显示 PRESENT / MISSING / NONE_REQUIRED 与独立存储说明，不返回已有值；新 Key 输入在任何 await 前清空，不进入 LocalStorage、Experiment、Trace 或 Evidence。删除 Key 不删 Experiment，后续请求变 MISSING。修改无需重启；已开始请求保留原不可变 CredentialSnapshot。

ProjectEnvWriter 仅扩展固定文件名白名单 `.env` / `manual.env`；默认 `.env` 保持不变。manual.env 使用独立 `manual.env.writer.lock`、`manual.env.stage-*` 和同目录 recovery。复用现有 owner / DACL、私有目录、reparse / hardlink 防护、同卷替换、revision 冲突和失败回滚，权限无法确认则 fail closed。没有修改真实 ACL 或真实凭据。

## 4. 请求执行与安全

V2 校验 Experiment → 直接构建 immutable RuntimeSnapshot → 现有 ManualRequest → 共用 V1 execution helper → 原 Adapter `manual_complete` / `manual_stream`。

不构建正式 Profile、不执行 CapabilityValidator / Resolver / ProtocolSpec 映射、Probe、Runtime Defaults、RAG、Diagnosis、Orchestrator 或 AnalysisResult；不写 Evidence。Service Name 不用于选择 Provider codec。

保留 retry=0、1–600 秒有限 timeout、RequestHandle / control token、Normal / Streaming 后端取消与安全错误。不会自动注入任何业务参数。Raw Response、Usage 和 latency 在页面显示；tool_calls 只显示，不执行。

仅 http / https；拒绝 URL username/password、query/fragment 和非法 URL。Raw JSON 保留现有 12 KiB / 32 层限制，禁止 Authorization、Header、URL、timeout 等保留字段覆盖传输配置。HTTP 请求总大小仍受现有 16 KiB 限制。Experiment / 凭据写入和发送复用 Host / Origin / CSRF 校验，没有 CORS 或自定义 Header 入口。发送前用户明确确认 REAL NETWORK REQUEST。

现有 Adapter 的 Secret 回显脱敏保留，共用 Web 返回再防御性脱敏。保存、发送、读取实验时检查当前引用已解析的 Key，拒绝其被粘贴到实验字段。该保护不能识别用户未引用的任意 Secret；用户不得把 Key 放在 JSON、Notes 或名称中。

Stop 能请求关闭客户端后端 I/O；未进行真实模型验证，不能证明远程计算或计费停止。

## 5. 改动范围

- 新增 `manual_experiments.py`：实验校验、存储及直接 Runtime composition。
- `credential_paths.py`：同一私有目录中的固定 manual.env 路径。
- `project_env.py`：可选固定文件名，独立 lock / stage，不改变默认正式行为。
- `web.py`：V2 API、独立凭据 composition、共用 V1 执行 helper。
- `resources/web/index.html` / `app.js`：V1/V2 切换、实验 CRUD、独立凭据与 Stop。
- 新增 `test_manual_v2.py`，扩展 Browser 测试；更新 BUILD_RUN、导航及本报告。

没有修改 R3/R4/R5、RAG、Grounding、正式 Fishery_Project、现有 ManualRequest 或 SDK Adapter；没有新增依赖、Provider、Protocol、Preset 或 Tool execution。

## 6. 基础版实施测试结果（后续 UX 回归见第 9 节）

本轮自动测试只使用临时 ACL 保护目录、虚构凭据、Mock Gateway / SDK，不读取真实存储，不执行真实模型请求。

| 检查 | 最终结果 |
| --- | --- |
| `python -m unittest discover -s tests -p test_manual_v2.py -v` | 16 项通过 |
| Browser targeted：`Manual V2\|Manual UI\|three-mode Manual\|R6 Stop` | 15 项通过，其中新增 V2 8 项 |
| `python -m unittest discover -s tests` | 337 项通过，13.938 秒 |
| `node --test tests/test_browser_streaming.cjs` | 93 项通过，无跳过 |
| `node --check src/fishery_ai/resources/web/app.js` | 通过 |
| `git diff --check` | 通过 |
| Secret / sensitive-path scan | 127 个公开 Git / 待新增文本文件，2 处明确虚构 fixture 排除，未发现风险 |

覆盖 V1/V2 草稿隔离与 Clean-room 空状态、Experiment CRUD / Save As / 重载、Key CRUD / hot reload、正式文件不变、PROCESS_ENV 不被 V2 读取、独立固定路径 composition、权限 fail closed、BOM / CRLF / 注释保留、revision / CSRF / Origin / Host、失败后原文件完整、Raw request parity / retry=0、不调用能力或业务链路、Normal / Streaming Stop、Secret 回显和 JSON 转义值防护、删除互不级联。

扫描不访问 ignored outputs、真实 .env / manual.env 或私有存储，不输出任何匹配内容。原有 V1、R2、R3/R4/R5 和 Clean-room 回归通过。Browser 检查为现有 Node DOM / fetch 离线测试，未进行真实浏览器点击或模型请求。

最终工作树：8 个跟踪文件修改、3 个新增文件（本报告、`manual_experiments.py`、`test_manual_v2.py`）；无暂存、commit 或 push。真实输出目录、凭据文件及 lock / stage / recovery 未被 Git 跟踪。

## 7. 人工验收

1. 重启 `python -m fishery_ai web`，确认 Manual 默认 V1；原 Saved Connection Normal / Streaming 操作不变。
2. 切 V2，自定义 Service 标签、URL、精确 Model 和 Raw JSON，New / Save / Save As / Delete；重启确认实验持久化。
3. 填 Credential Ref 并刷新，在 manual.env 创建 / 替换 / 删除实验 Key；正式 Credential Manager 状态应不变。
4. 双标签页检查 stale revision；确认替换 Key 后新请求立即生效。删除 Key 后 Experiment 保留，新请求返回 SECRET_MISSING。
5. 手工确认真实网络后，再检查 Normal / Raw Streaming / Stop。无需 Probe。观察 I/O 状态，不将远程计算停止当作已证实。
6. V1 / V2 切换保留两边草稿，V2 Experiment 不出现在 Managed / Preset，删除实验不删除 Key。

本轮未执行以上真实网络验收，未读取、修改或迁移任何真实 Key。

## 8. 当前限制

只支持现有 Chat Completions transport；没有任意 Header、能力自动探测、正式连接转换、V2 Capability 或自动 Tool execution。实验更新使用单进程锁和原子替换，暂无 Experiment revision 合并；两页同时编辑可能后保存覆盖前保存。凭据仍有独立 revision 冲突保护。Raw 输出最大尺寸保留 Adapter 限制，UI 不做复杂字段解析；Secret 不应出现在请求正文中。

## 9. 小型 UI / UX 修正

### 文案

- Credential Ref / 凭据名称：例如 DASHSCOPE_MANUAL_KEY，只是引用名。
- New Key / API Key Value：只输入真实 Key 值，不输入 NAME=value。独立用户私有 manual.env 存 Key，Experiment 只存 credential_ref。
- Save：保存/更新当前 Experiment；Save As：用当前内容新建 Experiment，原实验保留。页面说明保存目录 outputs/manual-experiments/，不要求用户管理随机文件名。

### Model 准备边界

新建默认 Raw JSON 不再包含 model。仅 V2 增加 `prepare_experiment_request`，在副本中补入缺失的 Target Model；验证有效请求时保留原 model 省略状态，存储与编辑器不被改写。Normal / Streaming 共用此准备边界。显式相同 model 兼容旧实验；不同或无效的显式 model 继续返回 MANUAL_MODEL_MISMATCH。

V1 的 ManualRequest 合同未修改，仍要求显式 model。未改凭据安全、CRUD 操作语义、Cancellation、retry=0、Capability / Evidence / R3/R4/R5 或 Fishery Analysis；没有真实联网或凭据操作。

### 本次验证

新增 3 项 Python 和 2 项 Browser 测试。覆盖缺失 / 相同 / 冲突 model、Normal / Streaming 注入、编辑器文本不改写、发送前后实验文件字节不变、Secret 不进入实验文件，以及 V1 行为不变。

| 检查 | 本次结果 |
| --- | --- |
| V2 targeted Python | 19 项通过 |
| V2 targeted Browser | 10 项通过 |
| `python -m unittest discover -s tests` | 340 项通过，14.140 秒 |
| `node --test tests/test_browser_streaming.cjs` | 95 项通过，无跳过 |
| JS syntax / `git diff --check` | 通过 |
| Secret / sensitive-path scan | 127 个公开文件，2 处明确虚构 fixture 排除，未发现风险 |

没有真实模型请求，未读取或修改真实凭据；工作树保留，未 commit / push。

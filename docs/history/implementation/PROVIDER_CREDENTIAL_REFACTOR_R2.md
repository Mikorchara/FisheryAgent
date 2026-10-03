# R2：安全凭据 Writer 与 Web Credential Manager

日期：2026-10-02。本轮只实现凭据生命周期、安全写入和本地 Web 管理，不实施 R3–R7 或 Tool Calling。

**当前收尾状态：人工验收已登记，Post-R2 唯一阻塞已修复，离线完整回归通过。** 见 [结构审计（RESOLVED）](POST_R2_STRUCTURAL_AUDIT.md)；下文各阶段的测试和 Git 状态均按当时记录保留。

## Checkpoint（R2 初版历史记录）

当前 R0/R1 已由用户提交为 `8b64e4d`（重构阶段_1），工作树干净；本轮检查 88 个跟踪文件与一个待推送提交，受控扫描未发现规则命中的 Secret 风险，`.env`、`outputs/` 和真实记录没有被跟踪。172 项 Python、33 项 Browser、JS syntax、diff 检查通过后，已将该提交 push 到 main。没有重复提交或移动 tag。

## 实施方案与受影响模块

CredentialStore 继续只读，不导入全局环境；ProjectEnvWriter 负责固定所选凭据文件的 create / replace / remove。初版使用工作区 `.env`，现已迁移到用户私有存储，当前行为见下节。编辑器保留原始片段及 opaque revision；权限与暂存安全无法确认时 fail closed，不直接覆盖降级。

受影响范围：Credential 模块、Web 的 Credential API / 本地安全门禁 / 连接测试缓存、页面凭据管理、离线测试与启动文档。Orchestrator、RAG、Grounding、Domain Rules、Capability Identity / Evidence / Defaults 和 Adapter 参数映射保持现有行为。

## 用户私有凭据目录迁移（当前实现，2026-10-02）

依据：[Windows ACL 设计复审](R2_WINDOWS_ACL_CREDENTIAL_WRITER_DESIGN_REVIEW.md)。本次仅实施方案 C 的固定存储迁移，不修改真实凭据或 ACL；后面的初版记录保留历史语境，不代表仍以源码根目录作为 Web 写入边界。

- 新增 `credential_paths.py`：启动端从 Windows LOCALAPPDATA 和规范化项目绝对路径生成固定位置，不读取任何旧 Secret。项目 ID 为 `SHA256(normcase(abspath(project_root)))` 前 20 位十六进制；当前工作区对应 `project-4e5f7b2702af5d742ab9`。目标为 `%LOCALAPPDATA%\Fishery_AI_Prototype\<project-id>\credentials\.env`。缺失/相对 LOCALAPPDATA、解析目标落入源码树时 fail closed，不改为根目录 fallback。
- Web 和显式 `validate-real` 的默认启动组合统一选择此文件。CredentialStore 与 Writer 共享同一不可变位置配置，优先级仍为 PROCESS_ENV > 所选私有文件 > MISSING；保留来源名 PROJECT_ENV，UI 标注“用户私有存储”。调用方注入临时 Store 的离线测试保持兼容。
- 路径计算及状态/只读解析不创建目录。首次显式 CRUD 才逐级创建私有应用目录、项目目录与 credentials；不修改任何已存在目录 ACL。LOCALAPPDATA 基目录和已存在专用目录要求当前用户 owner，检查 DACL、路径、卷；文件要求当前用户 owner 与私有 DACL。unsafe 文件在 CredentialStore 解析前也被拒绝，防止 Writer 拒绝后仍读入不安全 Secret。
- symlink/reparse（含祖先）、硬链接拒绝。锁、私有 staging、新文件和 recovery 全在 credentials 目录；既有原子替换、revision、回滚、恢复与凭据 generation 保留。源码 ACL 不参与 Writer 权限判断。外部存储禁用 Git ignore 检查；原项目内 Writer 的检查仍保留，外部路径不得落入源码树来绕过 Git 检查。
- Web 保留 Flask `load_dotenv=False`；Web、主 `validate-real` 与三个 Qwen 脚本统一单一私有来源，不读取、复制或删除旧源码 `.env`，不检查其中是否存在 Key。页面给出统一手动重新设置提示；没有双文件合并。来源/位置类型可返回浏览器，已有 Secret 与实际文件路径不返回浏览器；启动终端只输出位置，不输出值。独立脚本的遗漏修复见收尾审计。
- Hot Reload、在途 CredentialSnapshot、CRUD 后认证缓存失效、Host/Origin/CSRF、auth NONE、PROCESS_ENV 只读和零 Secret 回显全部复用。R3/R4/R5、Preset、Cancellation、Manual、Tool Calling 未实施。

### 本次修改文件

新增 `src/fishery_ai/credential_paths.py`、`tests/test_credentials_private_storage.py`、[迁移说明](R2_PRIVATE_CREDENTIAL_STORAGE_MIGRATION.md)。修改 `credentials.py`、`project_env.py`、`secure_files.py`、`web.py`、`real_validation.py`、Web `app.js/index.html`，以及 `test_credentials.py`、`test_credential_writer.py`、`test_browser_streaming.cjs`。同步 AGENTS、README、BUILD_RUN、STRUCTURE、deep-dive 导航和本报告。没有修改 Profile、Orchestrator、Adapter 或 RAG。

### 本次验证

| 检查 | 命令 | 结果 |
|---|---|---|
| 凭据 targeted | `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p 'test_credential*.py' -q` | 108 通过，5.159 秒 |
| Credential Browser targeted | `node --test --test-name-pattern 'R2\|Credential' tests/test_browser_streaming.cjs` | 12 通过 |
| 完整 Python | `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q` | 247 通过，9.673 秒 |
| 完整 Browser | `node --test tests/test_browser_streaming.cjs` | 42 通过 |
| JS syntax | `node --check src/fishery_ai/resources/web/app.js` | 通过 |
| Diff | `git -c core.safecrlf=false diff --check` | 通过 |

新增/复用用例覆盖路径稳定/大小写归一化/项目隔离、缺失 LOCALAPPDATA、外部模式不能指向源码树、首次创建、旧文件零读取/修改、PROCESS_ENV 与 NONE、实际临时 Windows 广泛读 ACL 拒绝、权限检查发生在 Secret 读取之前、link/reparse 拒绝、同目录锁/暂存/recovery、回滚与 revision、私有布局下 Web CRUD/CSRF/缓存/Trace 全链路，以及 UI 位置提示。全部使用临时目录与虚构 Secret；没有启动真实服务或访问真实私有凭据目录。首次 targeted 出现旧 DTO 精确比较未包含新增非敏感 `storage` 字段，更新预期后通过。

### 迁移边界与剩余限制（人工验收已完成）

用户已完成本机私有存储与 Web 生命周期验收，记录见下一节；不再要求收紧或验收源码根目录 ACL。若未来私有存储路径权限改变仍拒绝，不自动修改 ACL。移动项目路径、换用户/机器会选择另一存储 ID，没有隐式迁移。目录权限检查不是完整 Windows AccessCheck 引擎，祖先执行代码/路径被恶意修改、同用户或管理员攻击不宣称隔离；Windows 为实际测试平台，POSIX fallback 未作独立平台验收。

**迁移阶段历史记录**：当时未读取/迁移/修改真实旧 `.env`，未修改真实 ACL 或正式项目，未调用模型，未 commit/push。实际人工验收步骤见迁移说明。当时 main 工作树为 14 个 modified、10 个 untracked、0 个 staged（包括此前未提交的 R2 和设计文档）；当时检查 `.env` 和 outputs 没有被跟踪。已有 `app.css` 和 Grounding 测试改动未在迁移中修改；这些历史计数不代表本轮收尾状态。

## R2 人工验收记录（USER-VERIFIED，2026-10-02）

以下由用户在本机实际验收后提供，不代表本轮助手读取真实凭据或再次执行模型调用；仅记录状态，不记录任何 Key 或片段。

| 验收项 | 用户确认结果 |
|---|---|
| Flask dotenv 与来源隔离 | 修复后 PROJECT_ENV / PROCESS_ENV 来源正确；PowerShell 中 DASHSCOPE_API_KEY 始终不存在，未污染进程环境 |
| 私有文件位置 | `%LOCALAPPDATA%\Fishery_AI_Prototype\project-4e5f7b2702af5d742ab9\credentials\.env` |
| 私有应用目录、project 目录、credentials、.env、.env.writer.lock | owner 为当前用户，inheritance disabled，仅当前用户 + SYSTEM FullControl |
| Web Create / Replace / Delete | 均成功 |
| Replace 与恢复设置 | 无需重启即可真实调用 Qwen；删除后重新设置也无需重启恢复 |
| Delete 与旧文件隔离 | 新请求返回 SECRET_MISSING，不 fallback 到旧源码根目录 .env |
| 完整 Web 重启 | 私有凭据仍持久有效 |
| 双标签页 revision | stale revision 正确返回 ENV_REVISION_CONFLICT；刷新后可修改 |

## 初版 IMPLEMENTED（历史实现；存储边界已由用户私有存储替代）

### 1. 先核对实际 R0/R1，再确定写入边界

当前 CredentialStore 已经按请求重新解析文件，RuntimeSnapshot 也已持有私有不可变 CredentialSnapshot，因此没有引入第二套 Secret 解析机制或全局环境导入。R2 保留只读 Store，仅新增固定路径 Writer、随机 credential generation、认证相关缓存失效及独立 Web 管理。

身份、Capability、运行偏好与凭据是独立层次。本轮没有调整 service/model identity、Adapter 参数、CapabilityValidator、Probe、Streaming 业务路径、RAG、Grounding 或 Domain Rules。

### 2. ProjectEnvWriter（历史路径；算法继续复用）

- **历史实现 / 已替代**：初版启动固定 `project_root/.env`；当前启动固定用户私有文件。Writer 与 CredentialStore 仍必须同一路径；Web 不允许指定文件路径或覆盖认证规则。
- 提供 create / replace / remove；重复 create、缺失 replace/remove 和重复变量定义会拒绝。禁止控制字符、多行新值和超过 4096 UTF-8 字节的值。
- 使用 dotenv parser 定位目标 binding，替换目标值的原始文本片段，不把整个映射重新序列化。保留未知变量、注释、顺序、现有 CRLF/LF（含混合换行）、UTF-8 BOM、未改动片段及末尾无换行状态。新增变量时只补必要行分隔；删除变量时保留行内注释。未知多行变量可以保留，但目标为多行变量时拒绝修改。
- 不做变量插值。单引号、反斜杠、美元符号等按 dotenv 规则转义，并校验写入前后非目标变量值完全一致、新值能正确回读。
- 状态返回随机 opaque revision，内部将文件身份、修改时间、内容指纹和权限纳入版本检查，不向浏览器返回 Secret 的 Hash、长度或片段。Web revision 另绑定 credential_ref 与 AuthSpec，Profile 在另一窗口改用不同凭据变量后，旧表单不能写入新变量。
- 同一 Store 使用 RLock，多个 Writer 使用固定、空的 `.env.writer.lock` 协作锁；Windows 使用无共享打开，其他写者不能同时进入。提交前重新确认 revision，旧版本返回 `ENV_REVISION_CONFLICT`。
- **历史实现 / 已替代**：初版在项目目录创建 `.env.stage-*` 并检查 Git ignore；当前锁、staging、recovery 均在用户私有 credentials 目录，不依赖源码 ACL 或外部目录 Git ignore。私有创建、flush/fsync、同卷原子替换和禁止直接覆盖的原则保留。
- 普通准备/替换失败保留原文件；替换后发生可恢复错误时原子还原并核对内容与权限。若无法确定或完成还原，返回 `ENV_RECOVERY_REQUIRED`，保留私有恢复目录，不报告成功。

### 3. Windows 文件安全（初版历史策略，当前检查私有存储）

仅接受本地固定磁盘、支持持久 ACL 的文件系统；拒绝符号链接、junction/reparse、硬链接，以及无法按当前策略处理的文件属性。目录不能向非受信主体授予写入/删除/权限修改权；凭据文件不能向非受信主体授予访问权。受信主体限定当前进程用户、SYSTEM 和 Administrators。

暂存目录在创建时设置私有、禁止继承的 ACL；新 `.env` 使用私有 owner/DACL，替换现有文件时复制已检查的 owner/DACL，提交前后确认一致。ACL 创建使用 Win32 SECURITY_ATTRIBUTES，权限检查通过 GetNamedSecurityInfo；同卷替换使用 MoveFileExW(REPLACE_EXISTING | WRITE_THROUGH)，不使用跨卷 COPY_ALLOWED。不自动放宽已有权限，不安装额外 Windows 依赖。API 行为依据 [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)、[GetNamedSecurityInfoW](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getnamedsecurityinfow)、[SDDL 转换](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertstringsecuritydescriptortosecuritydescriptorw) 和 [MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw)，查询日期 2026-10-02。

Windows 原生 ACL、私有创建、锁竞争、原子替换及回滚已在临时私有目录运行。普通 TemporaryDirectory 在此环境继承了其他主体写权限，确实被拒绝；测试显式创建私有子目录后验证成功。未检查或改变真实项目 `.env` 权限。

### 4. Web Credential Manager

在现有页面增加默认折叠的“本地凭据管理”。显示 Provider、Credential 名、PRESENT/MISSING/NONE_REQUIRED 与 source。

- PROJECT_ENV 可设置、替换、删除；状态 MISSING 且安全检查通过时可首次创建。
- PROCESS_ENV 外部只读，空外部值仍阻止文件回退与编辑。
- AuthSpec.NONE 显示“不需要凭据”，隐藏编辑。Built-in Ollama 不读任何凭据来源。
- 只接收新输入的 Key，password 输入框不回填已有值，提交、取消、失败或切换配置都会清空；不写入 LocalStorage、Profile、Trace、Evidence 或日志。
- 尚未保存的 Custom Profile 可先填写连接信息，再设置其凭据，之后进行显式连接测试并保存；避免缺 Key 导致无法完成首次配置。
- 后端只返回安全状态 DTO / 固定错误码；revision 冲突明确提示刷新重试。权限、格式或 Git ignore 不满足时隐藏编辑并显示原因。

API：GET `/api/credential-session` 获取当前会话 CSRF；POST `/api/credentials/status` 获取状态；POST/PUT/DELETE `/api/credentials` 分别 create/replace/remove。新值仅存在于提交请求体和本机 `.env`/当前私有快照中，不出现在响应 JSON。

### 5. 本地 Web 安全

应用检查 Host 白名单，运行入口只接受 `127.0.0.1:<port>` / `localhost:<port>`，不信任 Forwarded 头。Credential 写 API 要求 loopback 客户端、精确同源 Origin、JSON 和当前会话 CSRF。CSRF 使用随机服务密钥签名的 Flask 会话，cookie 为 HttpOnly、SameSite=Strict；CSRF 值只在页面内存中保留。

不开放 CORS；响应加 no-store、nosniff、no-referrer、DENY framing 与 self-only CSP。请求上限 16 KiB，原始异常不返回。固定错误包括 `HOST_NOT_ALLOWED`、`ORIGIN_NOT_ALLOWED`、`CSRF_INVALID`、`PROCESS_ENV_READ_ONLY`、`ENV_PERMISSION_ERROR`、`ENV_NOT_IGNORED`、`ENV_LOCK_UNAVAILABLE`、`ENV_REVISION_CONFLICT`、`ENV_WRITE_FAILED`、`ENV_RECOVERY_REQUIRED`。

### 6. Hot Reload 与 cache invalidation

CredentialStore 仍从 Process Environment > Project .env > Missing 每次读取；没有 load_dotenv 或 os.environ mutation。成功修改强制旋转随机 credential generation，即使替换为相同值也使旧授权失效。新请求使用新快照，已有请求保留原快照。

连接测试授权增加 credential generation 绑定；成功 CRUD 清空旧授权。连接测试发起后若轮换，在途返回不能签发旧授权；外部文件或进程环境改变后，保存时也重新确认 generation。授权检查与 Profile 保存共用锁，避免本应用的轮换交错。

模型列表原本没有服务端持久缓存；本轮清空页面下拉缓存，并用 credential epoch / 表单 revision 阻止旧请求结果回填；服务端拒绝轮换后的迟到结果，返回 `CREDENTIAL_CHANGED`。Credential 改动不删除 Capability Evidence 或 Runtime Defaults，也不调用会清空 Capability 的旧 invalidateTest 流程。

## CHANGED FILES

新增：

- `src/fishery_ai/project_env.py`
- `src/fishery_ai/secure_files.py`
- `src/fishery_ai/web_security.py`
- `tests/test_credential_writer.py`
- 本报告。

修改：

- `src/fishery_ai/credentials.py`、`web.py`。
- `src/fishery_ai/resources/web/index.html`、`app.js`、`app.css`。
- `tests/test_credentials.py`、`test_browser_streaming.cjs`、`test_v011_a3_grounding.py`（只调整过时的“全页面禁止 password 输入”断言，Profile 表单仍不保存 Key）。
- `AGENTS.md`、根 README、`docs/BUILD_RUN.md`、`docs/STRUCTURE.md`、deep-dive 导航。

## TEST RESULTS

全部自动测试使用临时 `.env` 与虚构 Secret。R2 fixture 同时拦截真实 `.env` 的读写与 socket；没有自动执行真实 Cloud/Ollama 请求。

| 检查 | 执行命令 | 结果 |
|---|---|---|
| R0/R1 推送前 Python | `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q` | 172 通过 |
| R0/R1 推送前 Browser | `node --test tests/test_browser_streaming.cjs` | 33 通过 |
| 凭据定向（R0/R1/R2） | `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p 'test_credential*.py' -q` | 73 通过；R2 新增 40 项 |
| R2 / Credential Browser 定向 | `node --test --test-name-pattern 'R2\|Credential' tests/test_browser_streaming.cjs` | 11 通过；其中 R2 新增 8 项 |
| 最终 Python 回归 | `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q` | 212 通过，5.137 秒 |
| 最终 Browser 回归 | `node --test tests/test_browser_streaming.cjs` | 41 通过 |
| JS syntax | `node --check src/fishery_ai/resources/web/app.js` | 通过 |
| Diff | `git -c core.safecrlf=false diff --check` | 通过 |

首次全量回归遇到一条历史“页面无 password 输入框”断言，与 R2 明确需求冲突；改为限定 Profile 编辑区不能包含 Key 输入、Credential Manager 独立接收新值后，完整回归通过。没有通过修改 Grounding 业务逻辑解决测试问题。

覆盖 create/replace/remove、hot reload、在途快照、同值 rotation、revision、空外部环境只读、NONE、注释/CRLF/LF/BOM/未知多行保留、特殊字符、注入拒绝、文件权限、硬链接、锁、Git ignore/跟踪状态、准备失败、替换失败、替换后回滚、回滚失败安全恢复、响应/repr/log/Trace 隐私、Host/Origin/CSRF/会话隔离、请求大小及 auth-cache/defaults/evidence 保留。

## ARCHITECTURE IMPACT

### 人工验收修复：Flask 自动 dotenv 加载（2026-10-02）

- **发现**：用户从不含 `DASHSCOPE_API_KEY` 的 PowerShell 启动 Web，页面仍报告 `PRESENT · PROCESS_ENV`。此前 import 和只读 Store 测试未覆盖真正的 Flask 启动阶段。
- **代码确认根因**：`python -m fishery_ai web` → `__main__.main()` → `web.run_web()` → `Flask.run()`；已安装 Flask 的 `load_dotenv` 默认为 `True`。原启动调用未关闭此行为，Flask 因而可以把项目 `.env` 导入全局 `os.environ`；CredentialStore 持有该映射，文件凭据被误判为外部进程凭据，并遮蔽后续文件更新。
- **最小修复**：仅在 `run_web()` 的 `app.run()` 显式加入 `load_dotenv=False`。CredentialStore 的 **Process Environment > Project .env > Missing**、每次 resolve 重新读取文件、不可变在途快照保持不变；没有新增 `load_dotenv` 调用或应用代码 `os.environ` mutation。
- **新增回归**：`tests/test_credentials.py::WebStartupCredentialTests` 两项测试经真实 CLI 与 `Flask.run()`，只替换 app 构建和网络监听。Flask dotenv 加载被禁止，测试环境隔离、临时文件读路径受保护；不读取或修改真实项目 `.env`。临时 `TEST_API_KEY` 在启动前后均不进入 `os.environ`，来源为 `PROJECT_ENV`；改写临时文件后，同一 Store 无重启读取新值，已有 Snapshot 保留旧值。另一项确认真实外部 process environment 仍优先且只读，不回退读取文件。
- **复测结果**：凭据 targeted 75 项通过；full Python 214 项通过（5.263 秒）；Browser 41 项通过；`node --check src/fishery_ai/resources/web/app.js`、`git -c core.safecrlf=false diff --check` 通过。命令与上表相同；上表保留此前 R2 阶段记录。
- **范围**：本次只修改 `web.py`、`test_credentials.py` 和本报告。未启动真实服务或调用模型，未访问真实 `.env` 或正式项目，未 commit / push，未实施三模式或 R3/R4/R5。需要用户使用更新后入口重新启动现有 Web 进程；已经被旧进程导入的环境不会由修复主动清理。新增凭据及 Hot Reload 不要求后续重启。

新增内容围绕凭据生命周期与本地管理，不改变 ModelGateway、Profile Identity、Provider 映射、Orchestrator、RAG、Grounding、规则、Reasoning/Streaming 数据流。CredentialStore 本身没有文件写 API，Writer 与 Store 共享锁和固定路径；不可变 RuntimeSnapshot 继续保护已开始请求。

AGENTS.md 的旧只读解析规则按本轮明确授权补充了受控 Writer 例外，同时保留开发/测试不碰真实 `.env` 的要求。未安装依赖，未修改全局配置，未修改正式项目。

## RISKS / OPEN QUESTIONS

1. **原源码 ACL 问题已被私有存储替代。** 源码根目录权限不是当前 Web Writer 门禁；用户已核对真实私有目录、文件与锁的 owner/DACL 并完成 CRUD。程序不自动修改已有 ACL，未来权限漂移仍可能触发拒绝；不把一次验收推广为所有机器都安全。
2. **外部编辑器不遵守协作锁。** 本应用写者会串行并在提交前检查 revision，但无法彻底消除不受控编辑器在最后检查与原子替换之间的竞争；编辑凭据期间应避免同时外部保存。
3. **不宣称断电事务保证。** 已 flush/fsync、Windows WRITE_THROUGH、正常错误回滚；强制结束/断电仍可能留下私有暂存目录。ENV_RECOVERY_REQUIRED 需人工恢复，未做启动自动恢复或复杂清理。
4. **安全元数据范围。** 本轮验证并复制 owner/DACL，不提供审计 SACL、EFS、复杂 NTFS 属性的完整迁移。编码仅 UTF-8/UTF-8 BOM，目标多行变量/重复键拒绝。
5. **本地单进程开发台。** 无用户认证、HTTPS 部署、反向代理或多 worker 会话共享；同一 OS 用户和管理员不是本方案隔离对象。其他浏览器标签已显示的模型列表没有推送通知，但旧连接测试授权在服务端失效。
6. POSIX 有 0600/0700 与 flock 实现，本轮运行环境为 Windows；未宣称完成独立 Linux 平台验证。

## NOT IMPLEMENTED / NEXT STEP

### Post-R2 首次审计（历史）：发现阻塞，暂停 checkpoint

用户提供的 Windows 私有存储人工验收已完成并登记，但当前源码审计发现三个历史验证脚本仍直接读取源码根 `.env`：`validate_qwen_grounding.py`、`validate_qwen_streaming.py`、`validate_qwen_output_parity.py`。Web 与主 `validate-real` CLI 已迁移，不能据此宣称所有验证入口均完成迁移。按本轮要求，仅记录问题并停止；未修脚本、未读取真实凭据、未 commit/push。

本轮 Python 凭据 targeted **110 项通过**，Browser 凭据 targeted **12 项通过**；发现阻塞后不继续 full regression 或提交前扫描。之前的全量结果保留为历史记录，不代表本轮通过。新增两项临时存储 smoke 验证 Normal/Streaming 快照和 Mock/NONE 不读文件。完整结论见 [Post-R2 Structural Audit](POST_R2_STRUCTURAL_AUDIT.md)。

### Post-R2 最终收尾（2026-10-02）：RESOLVED

经用户授权，仅将三个验证脚本的 Store composition 改为调用现有 `private_project_location`，并传入 `private_location`；新增私有路径不可用的安全退出。没有复制路径算法、legacy fallback、环境 mutation 或自动迁移，原有联网确认、retry/timeout、Grounding/Streaming/四次 Output Parity 语义保持不变。BUILD_RUN 明确统一来源与手动请求预算。

新增 8 项离线回归，对每个脚本检查正式路径函数、临时私有 Store、PROCESS_ENV 优先及空值、禁止旧 `.env` 读取、MISSING/ACL/路径错误拒绝和默认无联网。Python targeted **118 项通过**；Browser targeted **12 项通过**；full Python **257 项通过（11.097 秒）**；full Browser **42 项通过**；JS syntax、diff check 通过。受控源码/文档扫描未发现规则内真实 Secret 风险或待提交敏感路径；两处已有拒绝测试字面量与 HEAD 基线一致，不输出值。

本次 checkpoint 范围为此前 R2 变更、已授权纯设计文档和本次入口修复；不实施三模式或 R3–R7。实际 commit hash / push 状态以 Git 元数据和最终汇报为准。没有访问真实凭据、真实模型或正式项目。

本轮未实施 R3 ProtocolSpec、R4 Evidence Resolver、R5 Unknown Model Probe、R6 Cancellation、R7 Manual Mode 或 Tool Calling；没有真实凭据操作或真实模型验证。

R2 的 Windows 私有存储人工验收已经完成；源码根 ACL 和凭据 CRUD 不再作为当前待验收阻塞。旧验证入口迁移遗漏已解决，未发现新的结构阻塞。R3 及其他阶段仍须单独授权，不自动扩大范围。

**历史工作树记录**：初版完成时未 commit/push，HEAD 与 origin/main 为 `8b64e4d`，13 个 modified、5 个 untracked。迁移时记录见前文；本轮收尾结果单独记载，历史计数不代表当前状态。

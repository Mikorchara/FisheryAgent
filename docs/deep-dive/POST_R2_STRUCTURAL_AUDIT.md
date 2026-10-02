# Post-R2 Structural Audit

日期：2026-10-02。依据当前源码、AGENTS.md、R2 报告、ACL 复审和私有存储迁移说明。

## 当前结论：RESOLVED，唯一阻塞已修复

三个 Qwen 验证脚本已与 Web / 主 `validate-real` 统一：调用现有 `private_project_location(workspace)`，再用 `CredentialStore(location.env_path, private_location=location)`。没有复制路径算法、引入 legacy fallback 或改变验证业务。缺失私有凭据、路径或 ACL 不安全时均在模型调用前退出。下节保留首次审计的历史发现。

## 首次审计历史：阻塞导致暂停 checkpoint

Web 与主 `validate-real` CLI 已统一使用用户私有凭据文件，但三个历史验证脚本遗漏迁移，仍直接构造 `CredentialStore(workspace / ".env")`：

| 入口 | 位置 | 问题 |
|---|---|---|
| Qwen Grounding | `scripts/validate_qwen_grounding.py:44` | 读取源码根 `.env`；BUILD_RUN 仍介绍该入口 |
| Qwen Streaming | `scripts/validate_qwen_streaming.py:47` | 同上 |
| Qwen 输出一致性 | `scripts/validate_qwen_output_parity.py:77` | 同上 |

这些是独立旧入口，不是 Web Store 的文件 fallback；但当时违反了“任何正常运行路径不再隐式读取源码根 `.env`”和统一 credential composition 的验收要求，也绕过了私有存储路径/ACL 读检查。首次审计只记录并停止提交准备；随后经用户明确授权实施本报告顶部所述修复。表内行号是修复前历史位置。

## 已复核的结构边界（CODE-CONFIRMED）

| 检查 | 结果 |
|---|---|
| Web 启动 | `run_web` 使用 `private_project_location`，Store/Writer 路径一致；Flask `load_dotenv=False` |
| 主真实验证 CLI 与独立脚本 | `run_real_validation` 和三个 Qwen 脚本使用同一个私有路径构造函数；旧例外已修复 |
| 环境隔离 | 应用无 `load_dotenv()` 调用或 `os.environ` mutation；`dotenv_values(interpolate=False)` 只解析所选文件 |
| 来源优先级 | PROCESS_ENV > 所选用户私有 PROJECT_ENV > MISSING；外部空值也不 fallback |
| AuthSpec.NONE / Mock | NONE 在文件解析前返回 NONE_REQUIRED；Mock 不读取凭据文件 |
| Profile / Custom Profile | 只保留 credential_ref 等声明；不保存 Secret 或凭据文件路径 |
| Gateway / Adapter | 读取请求快照，不依赖具体凭据文件位置 |
| RuntimeSnapshot | frozen CredentialSnapshot 保留请求开始时的值；轮换不改变在途快照 |
| Normal / Streaming | Web 共用 request_runtime 凭据解析边界；新增 smoke 确认每个请求只 resolve 一次 |
| 测试注入 | 临时 Store 是显式依赖注入；官方 Web 启动负责私有路径 composition。create_app 无注入时是 process-only，不是根 `.env` fallback |
| 私有路径输入 | 固定启动路径由项目绝对路径生成稳定 ID；不由 Web/Profile/model 字段控制 |
| Writer | lock/staging/recovery 位于同一私有 credentials 目录；保留 ACL、revision、原子替换和回滚检查 |

对源码未发现新的 RAG、Grounding、Orchestrator 或 Provider 参数变更需求。本次不实施其他重构阶段。

## 用户人工验收（USER-VERIFIED）

详见 [R2 实施报告](PROVIDER_CREDENTIAL_REFACTOR_R2.md)。用户提供的实际 Web CRUD、热更新、持久性、ACL 与双标签页 revision 结果均已登记；这些成功不替代对其他启动入口的结构审计。

## 首次审计测试（历史）

- Python 凭据 targeted：`python -X utf8 -m unittest discover -s tests -p 'test_credential*.py' -q`，**110 项通过**。
- Browser 凭据 targeted：`node --test --test-name-pattern 'R2|Credential' tests/test_browser_streaming.cjs`，**12 项通过**。
- 新增两个离线 smoke：Normal/Streaming 私有快照一致性；Mock/Ollama NONE 不读取私有文件。首次新增测试误用了不存在的 Mock ID，修正为实际 `MOCK_PROFILE_ID` 后通过；未因此修改应用代码。
- 发现结构阻塞后，**未执行本轮 full regression、最终 JS syntax、diff 检查或受控 Secret/敏感路径扫描**，不以此前阶段通过结果替代本轮检查。
- 没有真实 Cloud/Ollama 请求；没有读取或修改真实 `.env`、私有凭据或正式项目。

## 修复后的测试与最终复查

| 检查 | 命令 | 结果 |
|---|---|---|
| Python targeted | `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p 'test_credential*.py' -q` | 118 通过，6.386 秒 |
| Browser targeted | `node --test --test-name-pattern 'R2\|Credential' tests/test_browser_streaming.cjs` | 12 通过 |
| 完整 Python | `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q` | 257 通过，11.097 秒 |
| 完整 Browser | `node --test tests/test_browser_streaming.cjs` | 42 通过 |
| JS syntax | `node --check src/fishery_ai/resources/web/app.js` | 通过 |
| Diff | `git -c core.safecrlf=false diff --check` | 通过；提交前再次核对 |

新增 8 项 targeted 测试，对每个脚本使用 subtest：共享官方路径函数、临时私有 Store、禁止 legacy 读取、PROCESS_ENV 优先（含空值）、MISSING 拒绝、没有联网确认就不解析凭据、私有路径不可用和 ACL 错误安全退出。正向用例在凭据交给下游验证之前由测试替身停止，不执行模型。R2 fixture 阻断 socket，拒绝临时目录以外真实 `.env` 读写；不使用真实环境凭据。

源码检索范围为 `src/` 与 `scripts/` 的全部 Python 文件：所有文件型运行入口都使用私有路径；`CredentialStore()` 无路径的工厂/Registry 默认仅处理进程环境。`ProjectEnvWriter.root / ".env"` 是已注入且必须与 Store 一致的存储目录，不是源码根 fallback。没有 `load_dotenv()` 或应用 `os.environ` mutation。测试中临时 `.env` 包括 Writer 编辑格式用例、explicit Store 注入和 legacy 隔离用例；后者故意放置不同虚构值并禁止读取，用于证明不存在 fallback。

受控扫描覆盖 Git 跟踪文件和非忽略待提交文件，不访问真实根 `.env`、私有存储、outputs 或模型文件；检查敏感路径、常见 Key/token/私钥/URL 内嵌凭据模式和代码凭据字面量。两处历史“拒绝 Profile 保存 Key”测试字面量已确认与 HEAD 基线一致，仅作为负向测试。规则内未发现待提交 Secret 风险，未输出匹配值。启发式扫描不是不存在任意 Secret 的绝对证明。

## Checkpoint 与后续边界

结构阻塞已消除，本次 checkpoint 纳入既有 R2 Writer/Web、Flask dotenv 修复、私有存储迁移、人工验收记录及本次三个入口修复。提交/push 的实际 hash 与远端状态以 Git 元数据及本轮最终汇报为准；不移动现有 `v0.1` tag。

当前未发现进入下一设计阶段前必须先解决的结构阻塞。外部编辑器竞争、同用户/管理员攻击、断电 recovery、项目搬迁与其他操作系统验收等已知限制仍见 R2 报告；不得用本次通过结果消除这些边界。

没有真实 Cloud/Ollama 请求、真实凭据操作或正式项目修改；Preset、R3/R4/R5、R6/R7、Tool Calling 均未实施。

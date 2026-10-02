# R2 Windows ACL / Credential Writer 设计复审

日期：2026-10-02。仅设计审查，不实施权限或凭据迁移。

**历史设计记录**：本报告描述根目录 `.env` Writer 遇到共享 ACL 时的设计复审。随后用户批准方案 C，用户私有存储已实施并完成人工验收；此处方案 D 的“立即只读”是当时的过渡建议，不是当前 Web 的功能限制。源码根目录 ACL 不再是当前 Writer 门禁。当前行为与验收见 [R2 报告](PROVIDER_CREDENTIAL_REFACTOR_R2.md) 和 [私有迁移说明](R2_PRIVATE_CREDENTIAL_STORAGE_MIGRATION.md)；下文保留设计过程与风险分析。

## 1. 依据与结论

**USER-CONFIRMED**：当前用户为 `LAPTOP-621I5KNO\HP`；Flask dotenv 污染已修复，凭据正确显示 `PROJECT_ENV` 并支持手工修改后热读取。D 盘及工作区存在 Authenticated Users、Users、CodexSandboxUsers 和未解析 SID 的访问授权，`.env` 继承这些 ACL。本文采用用户提供的 ACL 摘要，没有读取真实 `.env`、查询真实 ACL 或确认这些组的成员、ACE 顺序与有效权限。

**结论**：当前门禁是一个保守的“私有存储布局”检查，不能等同于 Windows 的有效权限判断。要求整个源码目录只对少数 SID 可写，作为通用开发环境要求过严；但按已报告的 `.env` 继承权限，拒绝写入并非纯粹误判。不能只放宽目录规则而保留可被其他主体读取或篡改的凭据文件。

**RECOMMENDATION**：当前先采用 D（Web 只读、用户手工编辑），长期需要 Web CRUD 时优先 C（每项目、用户私有目录）。A/B 是可行的条件方案，不因源码共享权限就绝对禁止；能否采用要看文件、凭据目录与路径替换风险的独立验收，而非组名。

## 2. 当前代码实际上检查了什么

**CODE-CONFIRMED**：

- `ProjectEnvWriter._policy()` 检查项目根目录 DACL 和 `.env` DACL。`guard_path()` 检查所有祖先的 link/reparse，但没有检查所有祖先 ACL；所以当前实现也不是“全部父目录均已安全”的证明。
- Windows `inspect_policy()` 信任当前进程用户 SID、SYSTEM、Administrators。文件 owner 必须是当前用户；目录 owner 可以是上述受信主体。文件上的任意非受信 Allow 权利均拒绝，连仅查看 ACL/属性的授权也会被拒绝。
- 目录使用 `0x500D0156` 掩码：创建文件/子目录、写属性/扩展属性、Delete Child、DELETE、WRITE_DAC、WRITE_OWNER 及通用写/全权都可能触发拒绝；这不是单一的 Modify 判定。INHERIT_ONLY 被跳过，Deny ACE 被跳过，其他 ACE 类型拒绝；未计算组成员、ACE 顺序和 Deny 后的有效结果。属于保守策略，而非完整 AccessCheck。
- 暂存目录在创建时设置私有、禁止继承的 ACL；新文件和恢复文件也显式设置 ACL。现有文件的已检查 owner/DACL 被复制到替换文件，替换前后校验。使用同卷 `MoveFileExW`，不允许跨卷复制降级。
- 当前只读 CredentialStore 不受 Writer ACL 门禁保护。Writer 拒绝编辑，不会阻止其他获授权主体直接读取原 `.env`。

代码依据：[secure_files.py](../../src/fishery_ai/secure_files.py)、[project_env.py](../../src/fishery_ai/project_env.py)、[credentials.py](../../src/fishery_ai/credentials.py)、[R2 报告](PROVIDER_CREDENTIAL_REFACTOR_R2.md)。

## 3. 四种权限问题必须分开

| 问题 | 必须检查的对象与权利 | 对本次情况的判断 |
|---|---|---|
| HP 能否修改 | 实际进程 token 对文件/目标目录的访问；原子替换还需要创建、删除/重命名条件 | 用户手工编辑成功，只证明其可操作；不证明其他人不可访问，也不保证 Writer 的原子替换流程可行 |
| 他人能否读 Secret | 文件有效 FILE_READ_DATA、可改变文件 DACL/owner 的主体 | 如果报告的 Users RX、Authenticated Users Modify 对 `.env` 有效且无适用 Deny，文件内容可读；私密性已不足 |
| 他人能否改写/替换/删除 | 文件 WRITE_DATA/APPEND/DELETE、父目录 FILE_DELETE_CHILD、权限控制权，以及路径/目录重命名 | 文件直接继承 Modify 时有篡改和删除风险；保护文件 DACL 后，仍须单独看目录路径风险 |
| 父目录 Modify 是否必然泄漏 | 是否继承到文件、是否有 Delete Child/权限控制权、目录自身 DELETE 和祖先替换路径 | 不必然允许读取受保护子文件；但可能允许改换目录路径，或在目标不存在时抢占目标名 |

Windows 对文件内容的授权通常依据文件自身安全描述符；父目录可列出、可新增，不等于可读已有受保护文件。继承会把父目录授权传给未保护的子对象，因此当前“`.env` 继承广泛授权”与“私有 `.env` 放在开放目录”是不同情况。[Microsoft：File security and access rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)

**重要区别**：标准 Modify 包含 ReadAndExecute、Write、DELETE，不能直接等同于 FullControl，也不自带 FILE_DELETE_CHILD、WRITE_DAC、WRITE_OWNER。DELETE 是删除对象本身；FILE_DELETE_CHILD 是父目录对子对象的删除权。删除或重命名文件可由文件 DELETE **或** 父目录 Delete Child 授权，所以只给文件加 Deny/取消继承不能替代目录检查。[Microsoft：FileSystemRights](https://learn.microsoft.com/en-us/dotnet/api/system.security.accesscontrol.filesystemrights?view=net-10.0)、[DeleteFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew)

**INFERENCE**：即使没有 Delete Child，目录自身 DELETE 仍可能允许改名整个目录；受保护文件的原有内容不会仅因改名自动变得可读，但固定路径可被替换，影响随后热读取、锁、提交和恢复。只有 AddFile 时，已有私有文件通常不因此可被覆盖，但首次创建、文件被移走或删除后的同名抢占仍需防护。具体组合须在临时 Windows 对象上验收，不从“Modify”摘要推导全部行为。

CodexSandboxUsers 有源码 Modify，不必然要求将该组信任为凭据读者；也不必然意味着所有项目内凭据布局不可用。未解析 SID 不能因名字无法解析就忽略。当前用户属于某个组，也不能证明该组仅包含当前用户。有效访问涉及 token 和 ACE 顺序；只用当前用户的 AccessCheck，不能证明其他主体无法访问。[Microsoft：How AccessCheck Works](https://learn.microsoft.com/en-us/windows/win32/secauthz/how-dacls-control-access-to-an-object)

**边界**：若攻击者可以改写之后会由 HP 执行的 Python/JS，仍可能通过篡改应用取得凭据；搬到私有目录也不能防止这个路径。凭据 ACL 解决直接文件访问与 Writer 完整性，不能把可恶意改写的执行代码变成可信代码。同一用户、管理员、SYSTEM 不在本方案隔离边界内。

## 4. 方案比较

| 方案 | 实际安全性与开发兼容性 | 复杂度 / 用户体验 | Web CRUD | 热读取、revision、原子替换、恢复 |
|---|---|---|---|---|
| A. 根目录 `.env` + 细化检查 | 无须收紧全部源码；但文件自身仍须私有，创建/目录改名/同名抢占风险必须解决。保持当前继承 ACL、仅放宽门禁不成立 | 路径不变；精确 Windows 权利与路径完整性处理比简单 Allowlist 难 | 条件满足后支持 | 热读取/revision 可保留；必须验收共享父目录下锁、私有暂存、目标替换及恢复的身份稳定性 |
| B. 项目内私有凭据子目录 | 文件、锁、暂存、恢复集中隔离；VS Code/Codex 源码权限不变。项目根/祖先仍可能改名或移走子目录，不能只关继承就宣布完整安全 | 中等；需明确批准凭据目录 ACL 与路径调整 | 条件满足后支持 | 同卷暂存很好复用；Git ignore 和固定路径需调整；目录身份与祖先风险仍需验收 |
| C. LOCALAPPDATA 下每项目私有目录 | 凭据不直接处于共享源码树；避免为 Web Writer 改动项目 ACL。须实际检查用户私有目录，不能只凭 LOCALAPPDATA 名字认定安全；不解决代码篡改 | 中等；一次显式迁移，之后 Web 使用基本不变。换账号/机器需独立配置 | 支持 | 同一私有目录放文件、锁、暂存与恢复；原子替换仍同卷。与源码不在同一磁盘无妨，禁止跨卷搬暂存文件 |
| D. Web 只读、用户手动 `.env` | 当前最少改动且兼容开发环境；不改善已有文件可读性，手工编辑也不能豁免 Secret 私密性问题 | 最低；编辑器操作较直接，缺少 Web CRUD | 不支持 | 现有热读取和凭据 generation 可用；revision 无法保证外部编辑器协作，手工保存的 ACL/原子性由编辑器负责 |

同卷重命名不按新建文件方式赋予默认安全描述符；跨卷移动会改变安全描述符处理。因此无论 A/B/C，显式安全创建、同卷替换和替换后 DACL 核对都应保留，不能改成普通复制或就地覆盖。[Microsoft：File security and access rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)、[MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw)

## 5. 哪些规则调整，哪些保持

**建议调整**：

1. 将“全部源码根目录必须私有”改为“所选凭据存储边界必须满足安全要求”。分别输出安全原因：当前用户不能操作、文件非私有、目标目录可替换、权限语义未知；外层可保持 `ENV_PERMISSION_ERROR`，不返回原始异常或敏感数据。
2. 将读取内容、内容改写、名称替换、权限控制、元数据访问分开。目录 List/Traverse 或文件 READ_CONTROL/READ_ATTRIBUTES 本身不等于 Secret 可读；AddFile/属性写也不等于覆盖现有文件。对创建/删除后的空位另设要求。
3. 明确区分目标目录与祖先：关键 Delete Child、DELETE、WRITE_DAC、WRITE_OWNER 和可变路径风险不能删除；当前只检查 root DACL、祖先只检查 reparse 的局限须记录。必要时以已验证目录身份/句柄保护事务，不能把一次路径检查当作免竞态保证。
4. 未支持的 ACE 仍 fail closed；第一版不自行实现完整 Windows 权限引擎。可接受规范的窄授权布局，逐步支持经过测试的组合。Deny 的存在不能直接证明安全，当前“忽略 Deny 后拒绝 Allow”也不能当作有效权限结论。
5. 测试拆成独立风险场景，不能仅把临时目录收紧后跑通就认为已覆盖开发工作区。

**应保留**：Process Environment > 所选项目凭据文件 > Missing；PROCESS_ENV 外部只读、auth NONE 不编辑；禁止 Flask dotenv 导入；新请求热读取、在途不可变 Snapshot；固定启动路径、不接收浏览器任意路径；保留原文/编码/换行；opaque revision、协作锁、私有创建、失败回滚、安全恢复；Credential rotation 的授权缓存失效；Host/Origin/CSRF、零 Secret 回显与日志泄漏。

**不能采用**：直接信任 CodexSandboxUsers/Authenticated Users；自动删除 SID 或系统 ACE；关闭检查；把只读检测失败降级为不受保护写入；自动修真实目录 ACL。

## 6. 推荐的最小后续范围

**立即**：继续 D，不将本次拒绝当作“HP 没有写权限”。UI 应解释是安全策略拒绝，并告知可手工编辑；同时明确当前文件继承权限可能允许其他账户直接读取，这个问题不会因 Web 只读而消失。

**经用户批准后，优先 C**：每项目固定映射到用户私有存储，而不是要求收紧 D 盘/整个源码树。此推荐基于当前已知共享 ACL 和原子 Writer 的需要，不是声称 A/B 永远不安全。若坚持根目录 `.env`，先验收 A/B 所需的精确保护条件，再决定是否实现。

最小改动边界：

- 启动组合位置选择唯一可信存储路径；CredentialStore 已接收文件路径，可复用。Writer 将“源码/Git 根”与“凭据存储根”分开，锁和暂存随凭据目录走；项目内存储仍检查 Git ignore，外部存储不能机械调用外部目录的 Git 检查。
- LOCALAPPDATA 下按固定应用目录和稳定项目标识隔离，标识不是 Secret；路径仅启动端确定，不允许 Web 设置任意位置，不用项目提供的可执行迁移脚本自动处理凭据。
- 选择一个文件来源，不新增隐式多文件合并或自动回退。用户私有文件仍可作为“项目作用域凭据文件”，但 UI/文档须明确位置（如 `PROJECT_ENV · 用户私有存储`）；若决定改 source 枚举，应作为明确兼容迁移。
- 不自动搬动真实 `.env`、不改 ACL、不自动删除旧 Secret。由用户明确授权的一次迁移处理旧值与非 Secret 配置，避免双份来源；迁移时重建 revision、失效旧授权，不删除 Capability Evidence/Defaults。
- 配置缺失或存储不安全仍只读/fail closed。不改 Gateway、Orchestrator、Profile、能力设计，不引入 Vault、数据库或新框架。

## 7. 后续人工验收与待决策项

以下是后续步骤，不是本轮已执行动作：

1. 用户选择 D/A/B/C，明确是否把其他本机账号或 Sandbox 身份视为凭据存储威胁；不要根据组名擅自决定信任。
2. 只看 ACL 元数据，核对 SID、owner、继承/传播、Allow/Deny、当前进程 token；真实凭据值不进入终端、聊天或截图。私有存储需确认父目录和祖先身份，备份/同步软件也纳入审阅。
3. 用临时目录与虚构 Secret 分别测试：文件广泛读授权被拒绝；共享父目录 AddFile 与 Delete Child 区分；文件 DELETE 与目录 DELETE 区分；保护子目录与祖先重命名；目标不存在时抢占；未解析 SID、Deny/通用权利和不支持 ACE。
4. 验证 HP 普通进程 CRUD，另一个已批准的测试身份不能读/改/替换凭据；无需扩大任何组权限。检查文件、锁、暂存、恢复的 ACL，而非仅最终文件。
5. 验证 Web create/replace/remove、stale revision、同时外部编辑、替换后故障与恢复；新请求热读取、旧快照不变、认证缓存失效，正常修改无需重启。
6. VS Code 手工保存后再检查是否改变 ACL、创建明文备份或重新引入继承；迁移后确认应用仅解析选定来源，PROCESS_ENV 仍优先。

**待批准**：存储方案、可信身份/威胁边界、是否授权一次性迁移、项目来源的 UI 命名。不能凭当前摘要确认两个未解析 SID 的用途或对真实文件的全部有效权限。

本轮仅新增此文档；没有读取真实 `.env`、查询/修改真实 ACL、运行测试或模型、修改程序代码、commit/push。Microsoft 官方来源查询日期：2026-10-02。

# R2 用户私有凭据存储迁移说明

> 文档分类：**CURRENT**。当前指南 / 维护依据；其中明确标记的旧阶段内容仍为历史。当前源码高于文档。 当前受管私有路径、hot reload、无旧 .env fallback 与安全验收说明。 当前边界见[架构总览](../architecture/CURRENT_ARCHITECTURE.md)。

> 2026-10-02 收尾审计补充：首次审计发现三个历史 Qwen 脚本遗漏迁移并暂停 checkpoint；现已修复并补充离线回归，和 Web / 主 `validate-real` 统一使用私有凭据 composition。没有运行真实模型。见 [已解决的 Post-R2 审计](../history/implementation/POST_R2_STRUCTURAL_AUDIT.md)。

日期：2026-10-02。已实现固定存储切换；真实凭据由用户手动重新设置，程序不自动迁移。

## 新位置与来源

Windows：

```text
%LOCALAPPDATA%\Fishery_AI_Prototype\project-<20 位路径哈希>\credentials\.env
```

项目 ID：`SHA256(normcase(abspath(启动工作目录)))` 的前 20 位十六进制。它只由非敏感项目路径生成，浏览器不能设置。当前项目 `D:\CodexProject\Fishery_AI_Prototype` 对应：

```text
%LOCALAPPDATA%\Fishery_AI_Prototype\project-4e5f7b2702af5d742ab9\credentials\.env
```

同一规范化路径启动时稳定；大小写在 Windows 下归一化。移动/重命名项目、换用户或机器会使用另一位置，暂不提供别名或自动迁移。请从项目根目录启动，不能通过任意子目录启动来期待同一个项目 ID。

- 优先级：**PROCESS_ENV > 私有项目凭据文件 > MISSING**；外部变量明确为空时也不回退。
- 页面来源保留 `PROJECT_ENV`，并标注“用户私有存储”。实际路径只在本机启动终端显示，不返回浏览器；已有值永不回显。
- Web、默认真实验证 CLI 和三个 `validate_qwen_*.py` 手动脚本使用同一位置；Mock Demo 不读取真实凭据。POSIX fallback 为当前用户 home 下同名应用布局，但本轮仅完成 Windows 原生验收测试。
- LOCALAPPDATA 缺失/非绝对路径、目标落在源码树内时返回 `CREDENTIAL_STORAGE_UNAVAILABLE`。私有目录名称并不构成安全保证：实际 owner/DACL、路径和卷仍需检查。

## 与旧 `.env` 的兼容策略

旧 `project_root/.env` **不读取、不复制、不删除、不修改**。不会探测里面是否有 Key；页面统一提示手动重新设置。不存在双文件合并、旧文件 fallback 或隐式 `load_dotenv`。旧文件继续 Git ignored，用户可保留；若决定后续清理，由用户独立备份和授权处理，本轮不做。

项目内测试/显式调用方注入的 CredentialStore 仍可指定临时文件；这不是浏览器路径入口，也不改变默认启动行为。

## 首次使用

1. 关闭旧 Web 进程，从项目根目录启动 `python -m fishery_ai web`。
2. 核对终端显示的位置和页面“用户私有存储”提示。不输出或分享 Key。
3. 若来源为 PROCESS_ENV，页面外部只读；如需使用文件，先由用户在外部调整启动环境，再重新启动进程。
4. 选择 Profile 或填写 Custom 草稿，在凭据管理中设置对应变量的新 Key。缺失显示 MISSING，不再读取旧 `.env` 补足。
5. 只有显式写入才创建所需的新私有目录；既有目录 ACL 不自动更改。不要把源码 `.env` 整文件复制进去，避免旧配置/权限一并带入。

## 安全与故障处理

- LOCALAPPDATA 基目录及专用目录验证当前用户 owner/DACL；只读解析也先检查私有文件安全。PROCESS_ENV 与 auth NONE 不触碰文件来源。
- 现有 ACL 不修改。新目录在创建时设置禁止继承的私有 ACL；拒绝 symlink/junction/reparse、凭据硬链接和不安全路径。文件沿用 R2 安全属性检查。
- `.env.writer.lock`、`.env.stage-*/new` 和 `.env.stage-*/original` 都位于 credentials 目录，私有创建、同卷原子替换。外部存储不依赖源码 ACL 或 Git ignore；源码内存储的 Git 防护保留。
- `ENV_PERMISSION_ERROR` / `CREDENTIAL_FILE_ERROR` 时暂停操作，单独审阅私有路径的权限和文件状态；不要直接删除系统 ACE 或给整个 Sandbox 组授予 Secret 权限。
- `ENV_REVISION_CONFLICT` 时刷新并重新输入；`ENV_RECOVERY_REQUIRED` 时暂停写入，由用户在本机审阅私有恢复目录。禁止把恢复内容粘贴到日志、文档或聊天。
- 同用户/管理员以及被恶意篡改后执行的应用代码不在 ACL 隔离保证内；原子替换不等于断电事务保证，外部编辑器也不遵守本应用协作锁。

## 人工验收清单

**2026-10-02 用户验收已完成**：实际路径为上面的 `project-4e5f7b2702af5d742ab9`；应用/project/credentials 目录、`.env` 和锁均为当前用户 owner、禁止继承，仅当前用户和 SYSTEM FullControl。Web CRUD、无重启 Qwen 调用、删除后 SECRET_MISSING 且不回退旧 `.env`、重新设置恢复、完整重启后持久化，以及双标签页 stale revision 均通过。PowerShell 中 DASHSCOPE_API_KEY 始终不存在。详细记录见 [R2 人工验收记录](../history/implementation/PROVIDER_CREDENTIAL_REFACTOR_R2.md)。助手没有重新读取真实凭据或发起真实模型请求。

以下保留为后续机器或权限变化时的复验清单，不是当前未完成事项：

1. 不查看内容地核对新目录和文件 owner/DACL，确认没有继承的广泛 Secret 读取或写入授权；核对路径祖先及备份/同步工具。
2. 在页面 create → replace → remove，确认每次输入清空、仅状态变化、旧 `.env` 保持不变。
3. 用非生产测试凭据验证修改后新请求无需重启；已有请求保留旧 Snapshot，连接测试/model-list 授权失效，Capability 与 Defaults 不变。
4. 通过编辑器手工保存私有文件后重新检查 ACL，确保没有生成明文旁路备份或恢复继承。
5. 若进行真实连接，另由用户显式确认 REAL NETWORK REQUEST；本轮没有执行任何真实模型调用。

## 自动测试结果

迁移阶段历史：targeted Python 108、targeted Browser 12、完整 Python 247、完整 Browser 42 均通过；JS syntax、diff check 通过，当时未 commit/push。

最终收尾：targeted Python **118**、targeted Browser **12**、完整 Python **257**、完整 Browser **42** 通过，JS syntax 与 diff check 通过。测试只使用临时私有目录与虚构 Secret，包括实际 Windows ACL 拒绝、CRUD、hot reload、revision、rollback/recovery、Web/CLI/脚本单来源、Web 路径注入拒绝、缓存和隐私回归。未访问真实 LOCALAPPDATA 存储或真实 `.env`。checkpoint 详情见收尾审计与 Git 元数据。

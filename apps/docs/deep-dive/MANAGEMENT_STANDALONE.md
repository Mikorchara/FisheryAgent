# MIG-2：独立发行与实例数据准备

本阶段只在原仓库准备工程能力，没有创建 Fishery_Management、迁移真实数据或更改 Credential 身份。MIG-1 后正式管理链已不依赖旧包；Prototype 保留独立实验定位。

## 发行边界

`scripts/packaging/management.pyproject.toml` 是未来新仓库的发行模板，当前根 pyproject 保持原合同。Python **3.11+**、四个依赖的版本约束不变，没有新增依赖。使用 setuptools 正式 Wheel 构建。

`prepare_management.py` 只向当前工作区 outputs 下的**新建** staging 复制允许的程序与资源，不覆盖目录：

- apps 包标记、management_paths.py。
- ai_backend、ai_service（排除 development）、knowledge、monitoring、simulator、management_web 程序。
- ai_service 两处 resources/*.json：Preset、Scope、默认 Tool Policy 等正式合同。
- management_web 的 HTML/CSS/JS 静态文件。

排除 fishery_ai、tests、development、SQLite、Settings、用户 Policy、Credentials、Trace、缓存、知识运行目录与资格报告。Knowledge 显式迁移程序仍是维护能力，启动不调用它、不加载旧 JSON。测试及人工资格入口作为源码工具按需带走，不是 Wheel 运行依赖。

构建示例（工具须预先安装，本命令不自动安装）：

```powershell
.\.venv\Scripts\python.exe scripts/packaging/prepare_management.py --destination "$PWD\outputs\management-build"
.\.venv\Scripts\python.exe -m pip wheel --no-deps --no-build-isolation --wheel-dir outputs/management-dist outputs/management-build
```

MIG-3 可将模板作为新仓库根 pyproject；当前不要替换混合工程配置。构建需满足 setuptools>=68，缺项不能降低要求。本轮使用工作区内隔离构建环境和已有 setuptools Wheel 离线检查，不修改主虚拟环境。

## 数据路径

唯一装配解析入口 `apps/management_paths.py:ManagementPaths.resolve()` 本身不读写文件。Web 向 AI 传递同一个不可变路径对象；AI service 不反向导入 Web。

| 数据 | 原工作区默认 | 显式独立实例根目录 |
|---|---|---|
| Monitoring | outputs/management_web/monitoring.sqlite3 | monitoring.sqlite3 |
| Knowledge | apps/knowledge_data/knowledge.sqlite3 | knowledge.sqlite3 |
| Settings / 预算 | outputs/management_web/settings.json | settings.json |
| 管理 Policy | outputs/tool-policies/management_assistant_policy.json | tool-policies/management_assistant_policy.json |
| 共享 Policy 兼容读取 | 同目录 tool_policies.json | 同实例 tool-policies/tool_policies.json |
| 安全 Trace | outputs/management_web/assistant-traces.jsonl | logs/assistant-traces.jsonl |

`--data-root` 必须绝对路径；`--user-data` 明确选择 `%LOCALAPPDATA%\FisheryManagement`，二者互斥。未提供参数则**不切换**。独立实例不回退旧工作区数据或共享 Policy；兼容读取只在同实例内发生。Settings/Policy 缺省使用原内存默认值，用户明确保存时才创建原格式文件；Trace 仍在执行时追加。没有新增普通日志框架。

Credentials 不属于普通业务数据：保留独立私有 Store 与 PROCESS_ENV > PROJECT_ENV > MISSING，源码根 .env 不读。数据根变化不改变 Credential 身份；当前身份仍与项目根路径绑定，MIG-3 改项目路径通常会选择新的私有位置，继续使用旧密钥须单独决定，不自动复制。`--project-root` 可明确指定已安装 Wheel 的稳定项目根身份，不能成为业务数据回退。

## 新实例与已有实例

未来仅对全新、尚不存在的目录初始化（父目录须存在）：

```powershell
.\.venv\Scripts\python.exe -m apps.management_web --user-data --init-data
```

这是**创建空白实例，不是迁移**。同父目录 staging 创建两个 SQLite 和 Policy/日志目录，校验后原子发布；目标存在即拒绝。Knowledge 记录既有统一格式标记和 `management-instance@1` 初始化标记，不冒充导入旧知识。失败只清理本次 staging，不发布半个实例。

打开已有实例先只读检查两个库的 integrity_check、版本、必需字段和 Knowledge 格式标记。错误区分 `<MONITORING|KNOWLEDGE>_DATABASE_MISSING / CORRUPT / SCHEMA_INCOMPATIBLE / STORAGE_ERROR`；拒绝路径 symlink、Windows junction 和硬链接文件。全部通过才装配 Repository。严格实例后续连接使用 mode=rw，库被移走也不会生成空库。**迁移遗漏不能用 --init-data 掩盖。**

原开发模式保留 Monitoring 自动建库合同，Knowledge 仍要求已有统一库；未来独立项目应使用严格实例参数。本轮不改变 Schema、留存或业务统计，不创建真实新实例。

## 启动与测试

旧命令不变：`.\scripts\dev\run_local.ps1 -Scenario low_oxygen`。

用户将来完成实例初始化或迁移后：

```powershell
.\scripts\dev\run_local.ps1 -Scenario low_oxygen -UserData
.\scripts\dev\run_local.ps1 -Scenario normal -DataRoot 'D:\指定的已有实例' -NoAssistant
```

复用同一监督器、本机限制、临时接入 Token、端口拒绝和 Ctrl+C 回收。子进程不继承 PYTHONPATH/PYTHONHOME；不自动安装、初始化或请求模型。原服务器 CLI 仍默认关闭 AI 实验，启动器只启用已有批准范围。8766 占用时拒绝，不杀外部进程。

已安装 Wheel 可从源码外启动（项目身份与实例分别指定）：

```powershell
python -I -m apps.management_web --project-root 'D:\CodexProject\Fishery_Management' --data-root 'D:\指定的已有实例'
```

此 CLI 不自动启用接入/AI；原参数保留。新项目须建独立 venv 并安装 management 发行包，不复用旧项目 editable。

独立离线测试：

```powershell
.\.venv\Scripts\python.exe -I scripts/dev/run_management_tests.py
```

复用 run_tests.py 的 unittest/Node 机制，要求 -I、校验本次源码位置并阻断整个 fishery_ai。包括 Backend、业务 Assistant/Tool、Monitoring、Simulator、Knowledge、管理 HTTP/SSE、Settings 和 Node。明确不加载旧包差分、历史 Runtime 迁移与资格模块；九个旧包/历史资格基线对拍方法也排除。排除清单见 `LEGACY_PARITY_METHODS` 与 management-independent 分支；新增普通测试引用旧包会直接失败，不静默跳过。原 management/FAST/PRODUCT/QUALIFICATION 含义保留，原管理入口仍运行对拍。

## MIG-3 最小带走清单

1. 上述 apps 程序与资源、management_paths、包标记；源码测试需保留各包 tests/自包含夹具/Node 文件。ai_service/development 仅人工资格需要时带走。
2. 独立 pyproject 作为新根配置、Git 忽略规则、apps/AGENTS.md、apps/docs、各包 README。
3. scripts/dev/run_local.ps1、local_session.py、run_management_tests.py、run_tests.py；scripts/packaging 模板/生成器（新根正式发行后可不再 staging）。测试会检查这些工程文件。
4. scripts/manual_real_tests 与其管理资格 CLI 按需保留，先核对引用；旧 Prototype 实验/历史报告不是运行依赖。
5. 真实数据单独备份校验后迁移两个 SQLite、Settings、管理 Policy；共享 Policy 仅在无管理覆盖且需保留原选择时评估。Credentials 独立处理，Trace 可归档。空库不能代替迁移。

验收：干净 venv 安装 Wheel、源码外导入；禁止旧包后正常 HTTP/SSE 六条 Fake 路径；资源字节一致；缺库不创建；10秒上报与停止清理。最后由用户决定真实网页验收。

MIG-3 仍需落实用户目录权限/备份策略、数据迁移工具及 Credential 身份选择。当前本机控制不构成远程生产账户权限。

## 本轮离线验收记录

- 原管理回归：481 项 Python、87 项 Node 通过；独立入口：456 项 Python、87 项 Node 通过。随后新增的 3 项路径/授权隔离测试包含在最终独立环境 25 项专项内，全部通过（没有再次重复整套回归）。当前发现数分别为 484 / 459。
- FAST：165 项通过；新实例、缺库/损坏/Schema、初始化失败/并发发布、同实例 Policy 继承、10秒 HTTP 上报、KeyboardInterrupt 进程回收均有隔离测试。
- 使用本地 setuptools 84 Wheel 在隔离构建 venv 正式构建，无联网、无降低 build-system 要求。Wheel 110 项文件，18 个正式资源逐字节一致，无旧包/测试/数据/Trace。
- 在另一个未安装旧包、无 editable/PYTHONPATH 的 venv 安装 management Wheel；仅复用本地已安装的25份第三方发行文件作为离线依赖（不是从网络重新安装依赖）。`pip check` 通过。源码外目录、Python -I、阻断旧包下，Normal/Streaming 各 Direct/单Tool/双Tool 共六条 Fake HTTP/SSE 与旧基线的协议、Steps、Usage、安全 DTO、Ledger、revision 和提交指纹完全一致，资源关闭；显式实例启动也通过。
- PowerShell 语法、Python AST、87 个文档本地链接及 git diff --check 通过。验证环境为 Windows / Python 3.12.14；未另测 Python 3.11。没有真实 Provider/NPU 请求或真实数据迁移。

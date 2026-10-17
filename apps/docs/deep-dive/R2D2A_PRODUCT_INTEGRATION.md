# R2D-2A：管理平台产品整理

基线：`4553d7a`，开始时工作树干净。仅离线实现与验证，不调用Provider/NPU、不改真实数据库/凭据/用户Policy、不修改旧Prototype，不commit/push。

## 1. Policy小修

`management_policy._writer_lock()`先锁住第0字节，再初始化空锁文件。Windows允许锁范围超过EOF，从而避免另一个写者在已有锁下初始化写入。锁竞争仅在locking操作的特定errno/WinError上归为BUSY；打开、初始化、替换的权限错误及其他锁故障仍为STORAGE_ERROR。CAS、generation/revision、RLock、fsync/原子替换未改变，解锁异常仍关闭文件。

9项临时Policy测试通过；新增受控线程交错验证锁已取得且EOF仍为0时竞争者被拒绝、无Policy写入，随后锁可重新使用；另验证EACCES竞争、EBADF/EPERM/WinError5存储故障和replace权限错误。没有将所有PermissionError当作BUSY。

## 2. 工具可用性与候选

| 入口 | 实际范围 | 状态 |
| --- | --- | --- |
| 普通Normal | 原Current + Knowledge，用户Policy求交，已批准精确多轮范围 | 保持原样 |
| 历史查询快捷操作 | Qwen OFF / Normal / History / 1/1/2 / 1024 / 120秒 | 已批准local_experimental，开关/授权仍分别检查 |
| Qwen Streaming | Current + Knowledge / 2/2/3 / 512 / 120秒 | 原local_experimental，历史不加入 |
| 统一Normal候选 | Qwen OFF / Current + Knowledge + History / 2/2/3 / 1024 / 120秒 | **candidate、关闭，未升级** |

三个Tool仍只有各自owner和一个`business_tools.registry.bind_tools()`。没有Execution Profile下拉菜单，不增加调度循环或关键词路由。批准统一组合前保留历史业务操作，避免已开放功能不可用。

新增HTTP Fake测试使用**测试专用服务端选择和未发布准入stub**：其余Scope/Policy/参数/预算/执行/提交完整运行，浏览器只提交普通请求，不能指定candidate。验证Direct Final、单独W/H/K、W→H、实际Result进入后续请求、1024编码、独立Ledger、冻结设备、唯一提交；撤销使旧确认失效，非法参数无Handler/后续请求。产品候选仍不可发送。

人工入口复用现有同意、报告、观察Adapter、30分钟夹具和正式Service，仅新增四个固定案例；[命令与预算](../../../scripts/manual_real_tests/README.md#5-三工具-normal-候选r2d-2a)。每次一个计划hash，默认Dry-run。资格CLI不验证真实HTTP，不自动发布。四个Fake资格案例均技术通过；缺失/错误授权hash在凭据/SQLite/SDK前拒绝，错误路径、非法参数、截断、Stop、Trace失败不成为技术PASS。

## 3. 视图和启动

- 全屏使用应用内布局，隐藏主导航/标题装饰，输入保持可见，运行面板可收起；窄屏面板覆盖时可用顶部按钮关闭。
- 阅读/截图模式展开当前全部聊天，隐藏输入/模型控制，消息按文档流排列，工具明细仍可手动展开；运行中保留Stop和未提交预览标记。退出返回原模式与滚动位置，ESC退出阅读后可再退出全屏。
- 原消息节点、Handle、Transport、History和确认保持；视图状态不参与执行。运行中Normal双Tool/Streaming预览切换不产生额外请求或Final。向上阅读、问题标记和返回最新保留。
- [一行启动](../BUILD_RUN.md#一行式常用命令)：PowerShell薄入口调用标准库双进程管理，临时接入Token只进入子进程环境，隐藏子进程窗口；不修改用户环境/配置。8766有监听时拒绝，不杀未知进程。Ctrl+C/子进程退出时只回收本次Popen对象；强杀父进程/关闭终端仍不能保证清理。保留原CLI和四个关闭开关。

## 4. 验证

- `python scripts/dev/run_tests.py management`：403项Python / 76.895秒，64项Node / 0.860秒，全部通过。Monitoring、Simulator、AI业务/Backend、管理HTTP/SSE、管理Node统一入口；无重复test ID，不含资格探测测试。命名空间测试目录用现有unittest加载器逐模块收集，不强造包或新增测试框架。
- `python scripts/dev/run_tests.py fast`：165项 / 1.276秒，通过；旧FAST/PRODUCT/QUALIFICATION含义不变。
- 新候选HTTP/资格专项：13项通过；历史资格原测试、人工入口和测试发现另做针对性回归。
- 启动器4项测试：真实隔离管理HTTP + 实际模拟器，观测到10秒窗口上报；占用拒绝、默认批准参数/关闭参数、启动失败清理、受控KeyboardInterrupt后两进程退出和端口释放。测试不启动真实Credential composition；这不证明用户机器上的私有凭据一定可读。
- 另使用原PowerShell入口的隔离副本、实际前台Ctrl+C验证清理：只将子进程启动替换为临时SQLite服务器，结果`owned_count=2 / all_exited=true`，端口8879已释放。未启用真实用户数据或Credential装配；普通端口占用仍拒绝。
- 实际浏览器：隔离SQLite/Fake SDK的Normal双Tool长回答、Streaming、桌面/窄屏、全屏和完整阅读截图。模型路径由Fake指定，不是新真实资格或回答质量证据。
- 60段长回答的阅读页`messageHeight=messageScroll=1785`、overflow=visible，整页2524px并保存完整截图；390×844全屏无水平溢出，输入区底部835px。运行中进入阅读仍显示Stop，随后原位Final；生成中向上滚动到0，Final后仍为0，共四个Fake成功回答。问题导航和返回最新另有确定性离线覆盖。临时浏览器已关闭，尺寸覆盖已恢复。
- 改动18份、增加10份，共28份文件；未新增Runtime/Registry/Executor/Policy实现。Python/PowerShell/JS语法、78个Markdown本地链接/锚点、敏感模式与`git diff --check`通过。资格/人工/发现/Policy专项42项通过，随后新增的CLI默认Dry-run专项单独验证。
- 浏览器截图、Ctrl+C验收夹具留在Git忽略的`outputs/r2d2a-ui/`。自动安全检查以`blocked by policy`拒绝递归清理该临时夹具，本轮未换方式删除；它不是用户监测库/凭据，也未纳入Git。

## 5. 最短后续

用户先体验已批准范围和新布局。按人工入口分别检查四个候选计划、批准并亲自执行有限真实样本；提交安全报告后再批准统一Normal范围，才连接候选普通聊天准入并移除历史快捷操作。无须再安排架构研究，不自动增加预算；当前2/2/3仍无法执行三个来源Tool。

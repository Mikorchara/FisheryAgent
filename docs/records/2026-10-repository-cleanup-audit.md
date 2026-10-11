# Repository Cleanup Audit — 只读仓库整理审计

日期：2026-10-11。基线：`f95c29b`（历史升级）。审计开始时 `git status --short` 和 `git diff --stat` 均为空。本轮唯一写入是本报告；没有执行 cleanup、测试套件、真实 Provider、凭据读取或生产项目操作。

## 1. Executive Summary

建议先降低日常导航与测试选择的复杂度，再考虑源码分包。现在不适合大规模重构。

- 正式 History v2 已独立放在 `history_projection.py`；`assistant.py` / `web.py` 不依赖 qualification。它、`assistant_sources.py`、Tool Runtime 和安全边界必须保留。
- 产品包内仍有六个 qualification 模块，其中四个有复用价值、两个主要保存固定历史实验。没有发现这些实验模块被正式 Web / Analysis 直接导入。
- scripts 有 9 个入口/辅助脚本与 59 个 JSON。4 个批次/continuation 入口和 P2E 索引生成器已完成阶段任务，不宜留在普通启动说明中。
- `test_history_product_migration.py` 有 9 个新增测试，但导入并继承完整 `AssistantWebTests`，使原有 13 个测试各多收集两次，共 26 次重复执行。应提取无 test 方法的 Fixture，而不是删掉核心断言。
- 耗时主要候选是批次 runner 的多进程集成测试。已有报告记录全量由 115.889 秒增加至 325.151 秒；P2F 为 314.721 秒。本轮未重新计时，不能把全部时间差归因于单一文件。
- 文档导航落后于代码：records 索引仍称 P2E 未执行；ROADMAP 仍停在凭据预检/取证；STRUCTURE 没有完整列出后续 P2D/P2E 资产。应该修正当前文档，历史记录保留并退出日常导航。
- 不建议直接删除历史 fixtures、旧版本名测试、空 Profile 模板、python-dotenv 依赖或共享 runner；均有实际引用或安全职责。

首个可批准动作：只整理文档导航与历史报告层级，提炼来源合同和迁移决定；不触碰运行代码、实验数据或测试断言。

## 2. Repository Inventory

统计仅包含 src / tests / scripts / docs 的实际文件，排除 __pycache__、pyc；不遍历 .git / .venv / outputs / 用户私有目录。资源位于 `src/fishery_ai/resources/`，不存在单独的根 resources 运行目录。

| 区域 | 实际文件 | Git 跟踪 | 说明 |
|---|---:|---:|---|
| src | 82 | 77 | 59 个 Python 模块、18 个资源；另外 5 个 ignored egg-info 安装元数据 |
| tests | 72 | 72 | 62 个 test_*.py、1 个历史 Fixture helper、2 个 CJS、7 个 fixture 文件 |
| scripts | 68 | 68 | 4 个 Python、5 个 PowerShell、59 个 JSON |
| docs | 33 | 33 | 31 个 Markdown、2 个既有 ZIP |
| 根维护文件 | 4 | 4 | README、AGENTS、pyproject、.gitignore |

本轮报告不计入以上基线。Python AST 找到 1040 个 test_ 函数定义；这是静态定义数，不是 unittest 实际收集数。Browser 文件静态注册 188 个测试。上一阶段全量结果为 1080 Python / 188 Browser，本轮未运行测试，不能将该历史结果当作新验收。

根目录另有旧 data/，只包含 knowledge/、mock/ 两个空目录，无文件、无 Git 跟踪文件；引用仅为 STRUCTURE 的旧目录说明。分类 DUPLICATE / REDUNDANT，LOW 风险的空目录清理候选，本轮未删除。outputs/ 包含用户本地资产，不读取内容也不纳入可删除清单。

分类：PRODUCT_RUNTIME / CORE_TEST / DEV_TOOL / QUALIFICATION_INFRA / HISTORICAL_EXPERIMENT / ONE_OFF_RUNNER / HISTORICAL_REPORT / DUPLICATE / REDUNDANT / UNKNOWN。附录逐文件列出主分类；混合职责另外说明，不据此自动删除。

## 3. src Assessment

### 正式运行边界

Web → AssistantService → 原有完整 pair trimming → product history projection → ToolCallingService → Gateway / Adapter；SourceReceipt 只来自执行结果，Commit Gate 保持独立。固定 Analysis 另行执行 Snapshot → Diagnosis → RAG → Model。

`history_projection.py` 是正式产品模块，不能随 P2C/P2E 归档；`assistant_sources.py` 虽起源于 P1，也已成为正式产品合同。`tool_capability_probe.py` 是 Web 中的显式 Probe，不是已结束的历史 experiment。

### qualification 混入包内的范围

| 模块 | 主分类 | 正式 Web 是否需要 | 候选动作 |
|---|---|---|---|
| assistant_qualification.py（548 行） | QUALIFICATION_INFRA | 否 | 分离通用预算/报告与固定 case allowlist，再迁到开发包 |
| qualification_adapter.py（114 行） | QUALIFICATION_INFRA | 否 | 与 Harness 一起迁移，保留受控观测/脱敏 |
| qualification_projection.py（53 行） | QUALIFICATION_INFRA | 否 | 保留 frozen fingerprint 包装，复用产品投影；可随 Harness 移动 |
| preset_tool_qualification.py（131 行） | QUALIFICATION_INFRA | 否 | 长期 Preset 维护工具，保留 |
| qualification_history.py（47 行） | HISTORICAL_EXPERIMENT | 否 | 固定 P2B/P2C fixtures、cases，可随实验 bundle 移走 |
| qualification_migration.py（97 行） | HISTORICAL_EXPERIMENT | 否 | 固定 P2E fixtures、matrix、order，可随实验 bundle 移走 |
| real_validation.py（268 行） | DEV_TOOL，旧入口 | 仅 CLI validate-real | 暂留兼容，未来退出产品包；不可直接删除 |

`assistant_qualification.py` 不是任意模型通用批处理器：Manifest 验证绑定批准的 Q/H/P2E 案例，不能简单把实验表删掉。通用接口和固定实验注册需先拆清。

当前 `real_validation.py` 读取包内 `deepseek_experimental.json`，该资源 profiles=[]，所以真实 validate-real 会在 Profile 缺失处返回 INACTIVE_VALIDATION_PROFILE；这是静态控制流结论，本轮未执行入口。它仍被 __main__ 和兼容测试引用，属于旧入口债务，不代表凭据架构失效。

### 扁平目录与职责

- 59 个 Python 模块中 42 个位于包根，确实偏平；tools / handlers 与 telemetry 已按领域组织，不需要重做。
- web.py 1558 行，兼有应用装配、Profile/Credential/Manual/Analysis/Assistant/开发 API；app.js 2991 行，页面多个状态机同文件；model_gateway.py 602 行、Adapter 606 行。这些是后续拆分候选，不是本轮已确认功能 bug。
- assistant.py 294 行、assistant_sources.py 234 行仍可定位；没有必要为了目录形式立刻迁移。
- AST（包含 TYPE_CHECKING 和函数内 import）找到三组环：
  1. model_gateway ↔ manual：Gateway 到 Manual 只在 TYPE_CHECKING，不能报告成运行时 import 故障。
  2. evidence_resolver ↔ official_capabilities：后者函数内 lazy import，数据常量先定义，当前有意避环；长期可以让声明纯数据化。
  3. qualification_history ↔ qualification_migration：前者 lookup 时 lazy import，后者导入前者常量/类型；只在实验区域，最适合先消除。
- 未发现由本轮静态检查可证明的即时循环导入故障；以上是耦合风险。

候选目录：先建独立 `qualification/` 开发包；远期才评估 `assistant/`、`models/` 或 `providers/`、`web/`。domain / knowledge 文件目前很小，telemetry 已清晰，不建议仅为了名称对称再拆包。迁移 42 个根模块会影响 src、tests、scripts、包资源定位、测试 patch 字符串和 CLI，风险 HIGH；现在不值得整批做。

## 4. tests Assessment

| 测试层 | 当前文件 | 必须保护的合同 |
|---|---|---|
| Assistant / Source / product history | test_assistant、test_assistant_sources、test_history_product_migration | 提交、AUTO/非 AUTO、receipt、trimming、B/A rollback、epoch |
| Gateway / Adapter / protocol | test_gateway_tool_contract、test_v011_a1、test_protocol_specs、test_cloud_capability、test_output_parity 等 | tools 消息、normalization、request-body parity、可观察输出后禁止透明 retry |
| Tool Runtime / Policy | test_tool_*、test_read_only_tools、test_mock_tool_gateway | allowlist、参数、NO_MATCH、取消、1 call / 1 round / 2 requests |
| Analysis / Web | test_analysis_tools、test_analysis_tool_web、test_web_tool_conversation、test_v011_a3_web 等 | 固定 Facts 不被 Tool 覆盖、UI/API 门禁、Normal/Streaming |
| 数据与领域 | test_current_water_quality、telemetry/scenario/matrix/scoring、knowledge_* | query-time freshness、canonical contract、诊断、知识边界 |
| Credential / Manual / Model | credentials/private/writer/compatibility、manual_v2、preset/managed tests | R2、隔离、Secret、immutable snapshot、三模式 |
| 长期 qualification | test_assistant_qualification、test_preset_tool_qualification、test_local_preset_qualification | 显式授权、budget、retry=0、安全报告 |
| 固定研究与 runner | qualification_history/projection/migration、cross_model、continuation、product_migration_runner | 冻结案例、批准顺序、已执行样本不可重跑等实验保障 |

### 明确重复与可合并点

1. P2F：`test_history_product_migration.py` 模块可见的 imported AssistantWebTests 被 unittest 收集一次，ProductHistoryWebTests 又继承它的 13 个方法；原模块本来还会收集一次。增加的 26 次是结构重复，不是 26 个新增合同。建议将 setup / make_app / post 提取为无 test 方法的 Fixture，再保留 9 个 P2F 用例及原 13 项 Web 测试。
2. Tool budgets 在 T3 / Assistant / Analysis / qualification 多层出现。它们覆盖不同调用者和门禁，不能只留一个上层用例。可以共用 fixtures / 参数化错误矩阵，但保留各应用入口至少一个集成测试。
3. Receipt / Requirement / Commit Gate：保留 test_assistant_sources（33 个定义）及 P2F 来源仿造用例；从实验测试提炼稳定合同后，才能让固定 H/S 矩阵退出默认 FULL。
4. Projection：产品 P2F 用例是主要产品门禁；qualification_projection（29）与 migration（17）混合 frozen case/hash、parity、escaping、安全边界。应提取独立纯投影 regression 后归档固定实验验证，不能整文件按历史名称删掉。
5. Normalization：Gateway/Adapter 正常解析和 qualification raw/normalized 一致性是不同观察层。重复矩阵可以缩小，安全观测不能消失。
6. 旧 A1/A2/A3 测试仍校验实际 Gateway / UI / credential / reasoning 行为；文件名旧不构成删除证据。
7. Historical Model Fixture helper 被 19 个 test 模块直接引用；其 profiles/official declarations 用于明确历史兼容模式，而不是正常启动。现在删除会破坏长期回归。
8. 两个 Tool 参数/状态/Knowledge Handler 的测试看起来与 Step2–10 同名，但合同已经正式上线，应归为 CORE_TEST，而非阶段流水账。

### 慢测试证据

- test_cross_model_qualification.py：39 个方法，其中 runner 类 18 个；test 方法中 17 个 run_runner 静态调用点，多处循环再展开。
- test_deepseek_projection_continuation.py：18 个方法、20 个 invoke 静态调用点。
- test_product_migration_runner.py：16 个方法、15 个 run_runner 静态调用点。
- 上述 helper 每次启动独立 PowerShell 进程，并在临时目录生成/校验多条固定安全报告；mock 网络，不等于成本为零。timeout=30/60/120 是上限，不能当作实际耗时。
- P2E 报告记录：加入 runner 前 1029 项 / 115.889 秒；之后 1045 项 / 325.151 秒。P2F 1080 项 / 314.721 秒。说明应优先分层执行 runner regression；尚无本轮逐测试 profiling，不能给出精确节省百分比。
- Browser 单文件 3510 行 / 188 个 Node VM 测试；它不是完整真实浏览器 E2E。可按子系统拆分共享 harness，不能因此认为整文件都冗余。

## 5. scripts Assessment

| 脚本 | 分类 | 推荐动作 | 风险 |
|---|---|---|---|
| qualify_assistant_turn.py | QUALIFICATION_INFRA | 保留单 manifest、安全报告、显式 consent；后续拆离固定实验 case | MEDIUM |
| qualify_preset_tools.py | QUALIFICATION_INFRA | 保留维护者发布前资格入口 | LOW |
| qualify_local_preset_request.py | DEV_TOOL | 暂留精确 Ollama ON/OFF/stream/raw 检查；目标固定，不能称任意模型通用入口 | MEDIUM |
| projection_qualification_runner.ps1 | HISTORICAL_EXPERIMENT，部分共享基础设施 | 与原实验整体归档；先提取进程 JSON/report 合同与路径安全检查 | MEDIUM |
| run_deepseek_projection_qualification.ps1 | ONE_OFF_RUNNER | P2D 已完成，退出普通入口，归档 | LOW（成组） |
| run_ollama_projection_qualification.ps1 | ONE_OFF_RUNNER | P2D 已完成，归档 | LOW（成组） |
| run_deepseek_projection_qualification_remaining.ps1 | ONE_OFF_RUNNER | 只接受当时首样本的 continuation，优先归档，不再建议重跑 | MEDIUM |
| run_product_migration_qualification.ps1 | ONE_OFF_RUNNER | P2E 已完成，归档；保留 stop/no-extra-sample 安全用例的抽象合同 | MEDIUM |
| prepare_product_migration_qualification.py | HISTORICAL_EXPERIMENT | 只生成/审计冻结 P2E 索引，不是通用 generator，成组归档 | LOW（成组） |
| tests/manual_edge_mock_probe.cjs | ONE_OFF_RUNNER / REDUNDANT 候选 | 固定旧 qwen-plus-experimental，正常空模板中不存在；归档后可考虑删活动副本 | LOW |

当前共有 59 个 manifest/index：Q1–Q4 4、H0–H6 7、P2C 7、P2D DeepSeek 5、Ollama 5、P2E 30 + index 1。它们被 Harness allowlist、tests、PowerShell hash表、BUILD_RUN 或 records 引用；不得单独删 manifest 或修改冻结 hash。

不建议把所有入口合成一个无限 batch：保留“批准一次 → 一个 manifest → 有限请求 → 安全报告”。若未来合并，合并的是受控进程/报告合同，不是自动重新执行旧实验。

## 6. docs Assessment

建议保留现有 deep-dive 六类，不额外造一个重复 ARCHITECTURE.md。根 README → 当前架构 / BUILD_RUN / STRUCTURE / Tool 文档是日常入口。

候选结构：

```text
docs/
  BUILD_RUN.md / STRUCTURE.md / ROADMAP.md / TROUBLESHOOTING.md / CODE_REVIEW.md
  deep-dive/{architecture,models,tools,data-domain,operations,research}/
  records/
    README.md                 # 简短索引；可承担 CURRENT 导航，不再重复建 CURRENT.md
    2026-10-history-v2-product-migration.md
    2026-10-history-v2-migration-decision.md
    2026-10-repository-cleanup-audit.md
    archive/
      history-v2-research/     # P2A–P2E 原研究/事故/结果，原内容保留
      knowledge-tool-v1/      # 旧接管/施工总结与预检事故
      *.zip                   # 保留既有两份历史文档包
```

这是建议，不是本轮实际目录。P1 source contract 先提炼当前语义到 architecture 文档，再归档实施记录。P2E final decision 和 P2F rollback record 留在 records 根作为最近关键决策；P2B/P2C/P2D 的原始结果、停止审计和全部研究记录均保留，但退出每日阅读导航。

### 明显过时的当前描述

- records/README 的 P2E 链接说明仍写“真实 Provider 未执行”，与已完成 P2E 决策和 P2F 不符。
- ROADMAP 仍称四项 Qwen 取证未启动、下一步先取证；它描述的是旧预检事件，无法代表后续 Q3/H/A/B/P2E 已发生的阶段。
- BUILD_RUN 混合普通运行与已完成 P2D/P2E 批次命令；这些应移为历史实验运行说明，保留“不可重跑/新授权”规则。
- STRUCTURE 的 records 文件地图遗漏后续结果和决策文件；应在归档后一次更新，避免每天人工维护历史全目录。
- docs/notes.md 没有日期/状态，仍有“正在进行”的 History/Prompt 记录，同时含可能独有的后续需求。主分类 UNKNOWN，不能直接删除；让用户确认或合并有效 backlog 到 ROADMAP。
- 研究文件明确历史 baseline / 暂停状态，保留原文；不能用当前产品行为重写过去的实验。Knowledge readiness 不等于已经完成检索质量/全部语言真实性验收。

## 7. Duplicate / Historical Assets 与依赖核对

引用检查使用 Python AST import、已跟踪文本引用、动态命名调用的人工复核和 Markdown 本地链接。文字引用不等于运行依赖；零字面引用也不能排除 f-string/dynamic module loading。

| 候选 | 已确认依赖 | 约束 |
|---|---|---|
| assistant_qualification | 8 个 test 文件；3 个 script 文件 | 其中 knowledge_assembly 仍检查正式工具装配，不可整组删 |
| preset_tool_qualification | qualify_preset_tools + test_preset_tool_qualification | 维持发布合同独立于 Managed Evidence |
| qualification_adapter | assistant_qualification + 3 个 test 文件 | 保留原始/归一化一致性与脱敏 |
| qualification_history | assistant_qualification / qualification_migration + 4 个 test 文件 | 固定 fixture/hash 与 Source 合同拆开处理 |
| qualification_migration | assistant_qualification / qualification_history + migration test / generator | 先消除 lazy cycle，再成组移动 |
| qualification_projection | 2 个实验模块 + 4 个 test 文件 + P2E runner 内嵌 Python | P2F 也引用冻结包装作 parity；产品 history_projection 必须留下 |
| real_validation | __main__、历史 Fixture helper + 5 个 test 文件 | validate-real 命令与 R2 composition 兼容必须处理 |
| shared PS runner | 4 个 PS 入口 + 3 个 runner test 文件 | 单独删会破坏仍保留的历史验证 |
| P2D 两个 wrapper | cross_model test 通过动态文件名读取 + BUILD_RUN/STRUCTURE/records | 静态零字面引用不构成“无人使用” |
| continuation | test_deepseek_projection_continuation + BUILD_RUN/P2D records | 只适用于已结束、固定首样本状态 |
| P2E runner / generator / 31 JSON | runner test、migration test、Manifest allowlist、frozen index/hash | 当作一个实验 bundle 移动 |
| historical_model_fixtures + 6 历史资产 | 19 个 test 模块 | 兼容测试不是产品配置，不可混入正常 startup |
| tests/fixtures/r0_runtime_baseline.json | test_credential_compatibility | 保护 immutable runtime / credential composition |
| 3 个空 profiles JSON | Web _builtin_profiles 每次加载；validate-real 也读取 DeepSeek 文件 | 空内容仍是被读取的合同资源，不可直接删 |
| manual_edge_mock_probe | 仅 STRUCTURE 字面引用，未被默认 Node runner执行 | 旧固定 Profile/DOM 使活动入口失效；无源码 import |
| notes.md | 未发现其他 Markdown 依赖 | 无引用不等于信息可丢，保留 UNKNOWN |

Manifest 的冻结 identity、budget、工具名、projection 仍在 source registry、index、PS hash 表交叉约束；移动时路径、Patch字符串和归档可重现性一起验证。Web 不接受实验字段，正式 A/B 配置仍由启动代码捕获，不能因为 archive 把它恢复成客户端配置。

## 8. Test Runtime Strategy

以下是后续执行策略建议，不改变当前 AGENTS 或现有测试入口。本轮不运行这些命令。

### FAST：日常几十秒目标，需后续测量校准

保留不依赖 PowerShell batch 的核心合同，建议：

- test_assistant_sources.py（33）
- test_history_product_migration.py（9 个新增语义；先消除 26 次重复）
- test_gateway_tool_contract.py（29）
- test_tool_argument_contract.py（14）
- test_tool_conversation.py（37）
- test_current_water_quality.py（22）
- test_protocol_specs.py（3）

共 147 个声明方法（不含继承重复），覆盖 source / projection / budget / gateway / current facts。FAST 不是所有改动的通用豁免：Credential、Web、Manual 改动必须加对应 targeted。安全 Writer / ACL 全链仍在 FULL 与安全子系统 TARGETED。

### TARGETED：按依赖方向选，通常目标 1–2 分钟

| 改动 | 选择 |
|---|---|
| Assistant/history/source | assistant、sources、product_migration + tool_conversation；改共享 projector时加纯 projection parity；不自动跑固定30位置runner |
| Tool contract/handler/policy | gateway_tool_contract、tool_argument_contract、read_only_tools、tool_policy/manager、相应 knowledge/scoring tests、tool_conversation；入口变更加 Analysis/Assistant Web |
| Provider/protocol | protocol_specs、gateway_tool_contract、cloud_capability、output_parity、reasoning/streaming；修改观测再加 qualification_adapter/Harness tests |
| Credential/security/manual | credentials、writer、private_storage、compatibility、web security、manual_v2、execution；使用临时文件和虚构值 |
| Scenario/current/domain | telemetry_simulator、scenario_templates、current_water_quality、water_quality_matrix、water_quality_scoring、相关 Analysis |
| Web/UI | 相关 Python API tests + Node --test 的现有名称过滤；DOM/schema/state公共变更跑完整188项 |
| qualification CLI/runner | assistant_qualification +对应runner tests；改变共用 report/stop 合同才跑全部 qualification suite |
| docs-only | 本地链接 + diff check；不跑 Python / Browser |

按需选择同一 test 文件里的 TestCase，不能因为暂不跑 Runner class 就声称历史实验完整回归。现有 cross_model 文件可先区分纯 Python 类与 PowerShell 类；正式拆文件在批准后进行。

### FULL：milestone / merge / release / 核心架构与安全修改

推荐分两个明确层级：
1. FULL PRODUCT：全部长期 CORE_TEST（含原历史版本名但仍验证现代码的测试）、完整 Browser、JS/相关 PS syntax、diff、文档链接、受控敏感扫描。
2. FULL QUALIFICATION：全部保留的 Harness + 历史实验/runner/冻结清单兼容；在工具链修改或封存前执行，不在普通 UI/Python变更后默认运行。

在正式完成 tests 分层之前，现有 `unittest discover -s tests` 仍是当前完整 Python 回归，不能提前把排除 runner 的命令称作现行 FULL。过去的真实授权不能用于重新请求模型。

### “每次”与“里程碑”

- 每次代码变更：受影响 targeted、diff check、涉及语言的 syntax；变更/新增文本做范围内敏感扫描。
- 每次文档变更：local links、diff check；不依赖完整产品测试。
- 公共合同、安全、模块路径、共享 UI harness 变更：扩大到全部受影响子系统；必要时 FULL PRODUCT。
- 里程碑/提交前：FULL PRODUCT、完整本地链接与受控仓库敏感扫描。
- qualification变更或历史封存：FULL QUALIFICATION；不得自动网络执行。
- Markdown 链接和全仓敏感扫描不必每次测试迭代反复扫描未变文件；新增路径/根运行说明变动时再扩大范围。

## 9. Codex Efficiency Recommendations

1. 默认只读 AGENTS + README + 当前架构（67 行）+相关专项文档。History读 product projector/source合同与P2F记录；Tool读 READ_ONLY_TOOL_CALLING/ADDING_A_TOOL。不要从 records 逐份追历史。
2. 搜索先限 src 子系统与对应 tests；例如 history → assistant.py / history_projection.py / assistant_sources.py / 三个 tests；Provider → protocol_specs/Gateway/Adapter。只有证据不足才扩大。
3. 使用 import /调用/资源关系决定影响面，不按“以前要求全量”机械套用。
4. 当前事实来源：源码 > 当前测试 >正式 deep-dive >最近决策 >历史报告。记录里出现“当前”只针对当时基线。
5. STRUCTURE 是定位地图，不应重复展开每个实验 hash；records 索引只链接当前关键决定与 archive 入口。
6. 测试输出保留计数/耗时/失败细节，不输出数千行成功日志；独立静态读取可以批量，依赖判断和写操作顺序进行。
7. 不为每次任务新增 implementation report；普通维护更新稳定技术文档，只有阶段决定/事故才写 records。
8. 增加 lightweight affected-test 表即可，先不用复杂插件/新的测试框架。目录重排和新功能不同批提交。
9. 本次审计报告也是历史审计，不应成为每次工作必读清单。

## 10. 三张核心清单

### KEEP

| 路径/范围 | 用途与理由 | 风险 | 推荐动作 |
|---|---|---|---|
| src/fishery_ai/assistant.py、assistant_sources.py、history_projection.py | 正式运行/Source/已发布History v2；历史起源不改变其产品职责 | HIGH | 保持 |
| application.py、contracts.py、domain.py、knowledge.py、water_quality_scoring.py、telemetry/ | 固定事实、诊断、评分、RAG/current读取边界 | HIGH | 保持 |
| tools/、tool_conversation.py、tool_capability_probe.py | allowlist/Policy/Executor、单轮、安全Probe | HIGH | 保持 |
| model_gateway/options、Adapter、ProtocolSpec、Resolver/Store、Provider、presets | 三模式和协议/能力隔离 | HIGH | 保持 |
| Credential/Writer/secure_files/execution/web_security/observability | 私有凭据、不可变请求、安全取消/Trace | HIGH | 保持 |
| core tests + historical_model_fixtures + r0基准 | 安全和兼容合同仍有19个模块引用 | HIGH | 不按历史名称删除 |
| resources/web/knowledge/scenarios/mock/profiles/tools | 包数据和默认启动实际依赖 | HIGH | 保持；源码 .env 不在清理范围 |
| qualify_assistant_turn、QualificationAdapter、Preset资格入口 | 有预算/单次授权/安全结果的维护基础设施 | MEDIUM | 保留并逐步与固定实验解耦 |
| deep-dive正式六类、BUILD_RUN等五主文档、README/AGENTS | CURRENT STATE 与运行规则 | LOW | 修正文档状态，减少历史入口 |
| P2E final decision + P2F migration record | 最近迁移理由、回滚方式 | LOW | records根保留 |
| 既有两份文档ZIP | 独立历史档案 | LOW | 原样保留 |

### ARCHIVE / MOVE CANDIDATES

| 路径/范围 | 当前用途与理由 | 风险 | 推荐动作 |
|---|---|---|---|
| records内早期研究、接管、P2A/B/C/D/E preparation/results | 已结束实验的证据链 | LOW（链接成组） | archive/history-v2-research 或knowledge阶段；不删除原内容 |
| qualification_history.py / qualification_migration.py | 固定历史/顺序，不用于产品 | MEDIUM | 与manifest/index/test整体移入开发实验bundle |
| 4个PS batch/continuation + P2E generator +59JSON | 已结束实验，原授权不可复用 | MEDIUM | 成组归档，保留hash及执行规则 |
| qualification_projection.py | 冻结指纹包装，仍被P2F parity引用 | MEDIUM | 与Harness迁移；产品history_projection留原位置 |
| assistant_qualification / qualification_adapter / preset_tool_qualification | 维护基础设施，不是Web runtime | MEDIUM–HIGH | Phase D移到独立qualification开发包；留短期兼容门面 |
| fixed research tests + slow runner classes | 冻结案例保障，不必每次产品回归跑 | MEDIUM | extract core invariants后移出默认test discovery |
| real_validation.py | __main__暴露但当前Profile已inactive | HIGH（直接删） | 单独评审CLI弃用/兼容，后续搬到dev入口 |

### DELETE / MERGE CANDIDATES

这里表示候选，不是授权；本轮没有删除。没有证据支持直接删整个核心测试文件。

| 路径/范围 | 强证据 | 风险 | 推荐动作 |
|---|---|---|---|
| P2F继承/导入造成的26次额外Web执行 | 相同13个方法被3个TestCase对象收集 | LOW | 合并fixture，保留原13 + 新9断言 |
| manual_edge_mock_probe.cjs | 硬编码旧qwen-plus-experimental；默认profiles为空；仅地图引用 | LOW | 保留历史副本后删除活动副本；不影响Node默认188项 |
| Runner内重复进程JSON/plan/identity/path断言 | P2D/P2E/continuation重复同类安全守卫 | MEDIUM | 提炼共用合同矩阵，保留关键集成和事故再现 |
| 多个完整实验矩阵里的Source/budget/parity用例 | 已在产品测试验证，但fixed hash仍专用 | MEDIUM | 先逐断言coverage映射再参数化；本轮不认定可整删 |
| P1/P2记录中的当前合同/运行说明 | 当前文档尚不完整，历史入口重复 | LOW | merge技术事实到正式架构/Tool/运行文档后归档报告 |
| docs/notes.md | 可能独有需求且状态过时，证据不足 | UNKNOWN | 保留，用户确认后合并backlog；不直接删除 |
| __pycache__/egg-info等ignored元数据 | 可重建、非源数据 | LOW | 用户批准后按绝对边界清理；本轮未清理 |
| data/knowledge、data/mock空目录 | 实际文件数为0、只有旧地图引用 | LOW | 可在后续批准的清理中移除；不影响包内resources |
| python-dotenv / 空profiles模板 | 有真实解析或加载引用 | HIGH | 不是DELETE候选；不要与旧dotenv污染混为一谈 |

## 11. Proposed Cleanup Phases

| 阶段 | 范围 | 验证与回滚 | 现在是否值得 |
|---|---|---|---|
| A：docs/report归档与导航 | 修正过时CURRENT、提炼P1/History合同、移动历史原文；BUILD_RUN退出已结束batch入口 | local links / diff /保留原文与Git history；单独commit可回滚 | 是，先做 |
| B：scripts/manifest实验bundle | 归档4个batch/continuation、generator、固定清单；先解除活动CLI/test/path依赖 | dry-run静态合同、runner离线tests、冻结SHA和案例对应；不得真实重跑 | 是，需成组计划 |
| C：test fixture/tiers | 去26次重复；拆纯Python与PSrunner；提取稳定invariants；保留旧fixtures | targeted + 一次完整旧suite对照收集/跳过/断言集合，Browser不丢用例 | 是 |
| D：qualification退出产品包 | 通用预算/安全报告与fixedcases分离；独立开发包，legacyimport兼容 | qualification CLI/report parity、临时Credential路径、full产品+qualification | 之后 |
| E：src领域组织 | 优先web路由/装配和model合同边界；后再考虑assistant/providers子包 | 公共import、包资源、patch字符串、CLI/API全回归；分小提交 | 现在不做 |

A可以独立提交。B/C存在相互依赖：B若要移出仍被test默认路径硬引用的资产，要先做C中最小path/Fixture准备，不能留下不可运行的中间commit。D迁到repo级qualification包后，入口应能从项目根以 `python -m qualification...` 找到；脚本启动时的 sys.path 与 wheel/可编辑安装不同，必须明确打包边界，不能只改import字符串。上述都是后续设计要求，不是已实现方案。

## 12. Risks

- 没有运行时引用不等于没有开发契约；移走实验源/清单会影响frozen hash、报告路径与批准计划。
- Fixtures历史隔离是安全措施，不能为了清爽把历史SUPPORTED恢复为正常配置。
- History B不是防注入沙箱；Receipt/Requirement/Commit Gate不能被当作可删“研究代码”。
- 清理测试必须保留Statement-level检查；上层通过不证明Provider encoding、hard gate、取消、敏感路径都受保护。
- 真正用户Profile、Evidence、Manual Experiment、私有凭据和outputs不是可再生cache。本轮未读取它们，更不授权清理。
- 脚本归档后原报告的回放上下文要保留，实验不能改plan补样本。
- 全量计数下降可能来自去重或移出historical discovery，不能只以“通过数减少”判断覆盖降低/提高。
- 这里只做静态分析；未做新profiling、真实模型、运行import smoke或全量tests，性能收益与重构可行性需在各阶段另验。

## 13. Recommended First Action

批准 Phase A：仅当前导航/说明收口与历史原文归档。优先修 records README的P2E状态、ROADMAP旧取证状态和BUILD_RUN旧批次入口，保留P2E决策/P2F rollback。不要先移动产品模块，也不要先删除qualification测试。

之后单独批准一次“小型test去重/分层”变更：去除26次重复收集，并将慢Runner类从FAST/TARGETED默认范围隔离。正式删除/迁移任何实验资产之前，要求path/hash/断言映射和可回滚commit计划。

本轮停止在报告；未实施以上任何建议。

## 附录 A：src 与 resources 逐文件分类

路径相对于仓库根。PRODUCT_RUNTIME包括离线Demo与Development/Test正常可用功能，不能按“不是Cloud”移走。风险与推荐动作见主清单。

| 路径 | 分类 | 当前用途 |
|---|---|---|
| `src/fishery_ai/__init__.py` | PRODUCT_RUNTIME | 包入口 |
| `src/fishery_ai/__main__.py` | PRODUCT_RUNTIME | Web、Demo、validate-real CLI |
| `src/fishery_ai/application.py` | PRODUCT_RUNTIME | 固定 Analysis、诊断/RAG 上下文及可选单轮 Tool |
| `src/fishery_ai/assistant_qualification.py` | QUALIFICATION_INFRA | 单次受控 qualification、冻结案例和报告 |
| `src/fishery_ai/assistant_sources.py` | PRODUCT_RUNTIME | SourceRequirement、Receipt 与确定性满足关系 |
| `src/fishery_ai/assistant.py` | PRODUCT_RUNTIME | Assistant 白名单、上下文与提交边界 |
| `src/fishery_ai/capability_probe.py` | PRODUCT_RUNTIME | Managed 高级能力显式 Probe |
| `src/fishery_ai/capability_store.py` | PRODUCT_RUNTIME | 精确 Identity 能力证据持久化 |
| `src/fishery_ai/composition.py` | PRODUCT_RUNTIME | 离线 Demo 装配 |
| `src/fishery_ai/contracts.py` | PRODUCT_RUNTIME | canonical 数据、结果和 Usage 合同 |
| `src/fishery_ai/credential_paths.py` | PRODUCT_RUNTIME | 固定用户私有凭据路径 |
| `src/fishery_ai/credentials.py` | PRODUCT_RUNTIME | 凭据解析、来源和不可变快照 |
| `src/fishery_ai/custom_profiles.py` | PRODUCT_RUNTIME | Managed Profile 校验和持久化 |
| `src/fishery_ai/domain.py` | PRODUCT_RUNTIME | 确定性水质诊断 |
| `src/fishery_ai/evidence_resolver.py` | PRODUCT_RUNTIME | 精确 Identity 证据合并 |
| `src/fishery_ai/execution.py` | PRODUCT_RUNTIME | RequestHandle、取消与请求状态 |
| `src/fishery_ai/history_projection.py` | PRODUCT_RUNTIME | 产品默认 B、原生 A 回滚与共享编码 |
| `src/fishery_ai/knowledge.py` | PRODUCT_RUNTIME | 知识加载、TF-IDF 检索与背景 Evidence |
| `src/fishery_ai/manual_experiments.py` | PRODUCT_RUNTIME | V2 实验持久化和目标校验 |
| `src/fishery_ai/manual.py` | PRODUCT_RUNTIME | 独立 Manual Raw 合同 |
| `src/fishery_ai/model_gateway.py` | PRODUCT_RUNTIME | 消息/Tool 合同、Profile/Runtime 与 Gateway |
| `src/fishery_ai/model_options.py` | PRODUCT_RUNTIME | Capability 和生成选项门禁 |
| `src/fishery_ai/observability.py` | PRODUCT_RUNTIME | 安全 JSONL Trace |
| `src/fishery_ai/official_capabilities.py` | PRODUCT_RUNTIME | 维护声明及 Resolver 兼容入口 |
| `src/fishery_ai/openai_compatible_adapter.py` | PRODUCT_RUNTIME | 受控 OpenAI 传输、编码、归一化和取消 |
| `src/fishery_ai/preset_tool_qualification.py` | QUALIFICATION_INFRA | 维护者 Preset Tool 往返资格验证 |
| `src/fishery_ai/presets.py` | PRODUCT_RUNTIME | 维护者固定 Template/Variant 合同加载 |
| `src/fishery_ai/project_env.py` | PRODUCT_RUNTIME | 私有凭据原子 Writer、revision 和回滚 |
| `src/fishery_ai/protocol_specs.py` | PRODUCT_RUNTIME | Provider 参数编码知识 |
| `src/fishery_ai/providers.py` | PRODUCT_RUNTIME | Provider/Auth 定义 |
| `src/fishery_ai/qualification_adapter.py` | QUALIFICATION_INFRA | 资格请求预算及 raw/normalized 安全观测 |
| `src/fishery_ai/qualification_history.py` | HISTORICAL_EXPERIMENT | P2B/P2C 固定历史及案例 |
| `src/fishery_ai/qualification_migration.py` | HISTORICAL_EXPERIMENT | P2E 固定历史、矩阵和顺序 |
| `src/fishery_ai/qualification_projection.py` | QUALIFICATION_INFRA | 实验 A/B 包装及指纹；复用产品投影 |
| `src/fishery_ai/real_validation.py` | DEV_TOOL | 旧 validate-real 开发入口；当前模板为空 |
| `src/fishery_ai/repositories.py` | PRODUCT_RUNTIME | 离线 Mock 场景资源读取 |
| `src/fishery_ai/secure_files.py` | PRODUCT_RUNTIME | 权限、链接与文件安全边界 |
| `src/fishery_ai/telemetry/__init__.py` | PRODUCT_RUNTIME | Telemetry 公共导出 |
| `src/fishery_ai/telemetry/adapter.py` | PRODUCT_RUNTIME | SimulationPacket 转 canonical Reading |
| `src/fishery_ai/telemetry/current.py` | PRODUCT_RUNTIME | query-time Freshness 只读查询 |
| `src/fishery_ai/telemetry/models.py` | PRODUCT_RUNTIME | Telemetry 模型 |
| `src/fishery_ai/telemetry/scenario_templates.py` | PRODUCT_RUNTIME | Scenario Template 和存储 |
| `src/fishery_ai/telemetry/simulator.py` | PRODUCT_RUNTIME | 本地水质模拟 |
| `src/fishery_ai/telemetry/snapshot.py` | PRODUCT_RUNTIME | 进程内 CurrentSnapshotStore |
| `src/fishery_ai/tool_capability_probe.py` | PRODUCT_RUNTIME | 显式 Tool Calling 能力验证 |
| `src/fishery_ai/tool_conversation.py` | PRODUCT_RUNTIME | 共享单轮 Model→Tool→Model 协调器 |
| `src/fishery_ai/tools/__init__.py` | PRODUCT_RUNTIME | Tool 公共导出 |
| `src/fishery_ai/tools/catalog.py` | PRODUCT_RUNTIME | Tool 展示 metadata |
| `src/fishery_ai/tools/contracts.py` | PRODUCT_RUNTIME | 执行结果、状态和参数合同 |
| `src/fishery_ai/tools/executor.py` | PRODUCT_RUNTIME | allowlist、参数、取消和结果执行边界 |
| `src/fishery_ai/tools/handlers/__init__.py` | PRODUCT_RUNTIME | Handler 包边界 |
| `src/fishery_ai/tools/handlers/current_water_quality.py` | PRODUCT_RUNTIME | 当前水质查询 Handler |
| `src/fishery_ai/tools/handlers/knowledge_search.py` | PRODUCT_RUNTIME | 必填 query 项目知识检索 Handler |
| `src/fishery_ai/tools/handlers/water_quality_score.py` | PRODUCT_RUNTIME | 只读实验评分 Handler |
| `src/fishery_ai/tools/policy.py` | PRODUCT_RUNTIME | Analysis/Assistant 授权合同与存储 |
| `src/fishery_ai/tools/registry.py` | PRODUCT_RUNTIME | 显式 Handler 绑定与 schema 单一来源 |
| `src/fishery_ai/water_quality_scoring.py` | PRODUCT_RUNTIME | 实验水质评分领域规则 |
| `src/fishery_ai/web_security.py` | PRODUCT_RUNTIME | Host/Origin/CSRF 门禁 |
| `src/fishery_ai/web.py` | PRODUCT_RUNTIME | Flask 装配、API 和页面入口 |
| `src/fishery_ai/resources/knowledge/SOURCE.md` | PRODUCT_RUNTIME | 当前知识数据/来源 |
| `src/fishery_ai/resources/knowledge/eel_knowledge.json` | PRODUCT_RUNTIME | 当前知识数据/来源 |
| `src/fishery_ai/resources/mock/profiles.json` | PRODUCT_RUNTIME | 离线Demo Profile |
| `src/fishery_ai/resources/profiles/deepseek_experimental.json` | PRODUCT_RUNTIME | 固定Preset或空Builtin兼容模板 |
| `src/fishery_ai/resources/profiles/ollama_qwen35_local.json` | PRODUCT_RUNTIME | 固定Preset或空Builtin兼容模板 |
| `src/fishery_ai/resources/profiles/presets.json` | PRODUCT_RUNTIME | 固定Preset或空Builtin兼容模板 |
| `src/fishery_ai/resources/profiles/qwen_experimental.json` | PRODUCT_RUNTIME | 固定Preset或空Builtin兼容模板 |
| `src/fishery_ai/resources/scenarios/detection/count_jump.json` | PRODUCT_RUNTIME | Scenario/Mock场景资源 |
| `src/fishery_ai/resources/scenarios/detection/normal.json` | PRODUCT_RUNTIME | Scenario/Mock场景资源 |
| `src/fishery_ai/resources/scenarios/water_quality/low_oxygen.json` | PRODUCT_RUNTIME | Scenario/Mock场景资源 |
| `src/fishery_ai/resources/scenarios/water_quality/normal.json` | PRODUCT_RUNTIME | Scenario/Mock场景资源 |
| `src/fishery_ai/resources/scenarios/water_quality/partial.json` | PRODUCT_RUNTIME | Scenario/Mock场景资源 |
| `src/fishery_ai/resources/scenarios/water_quality/partial_stale.json` | PRODUCT_RUNTIME | Scenario/Mock场景资源 |
| `src/fishery_ai/resources/scenarios/water_quality/stale.json` | PRODUCT_RUNTIME | Scenario/Mock场景资源 |
| `src/fishery_ai/resources/tools/tool_policies.json` | PRODUCT_RUNTIME | 包内Tool Policy默认 |
| `src/fishery_ai/resources/web/app.css` | PRODUCT_RUNTIME | 正式页面资源 |
| `src/fishery_ai/resources/web/app.js` | PRODUCT_RUNTIME | 正式页面资源 |
| `src/fishery_ai/resources/web/index.html` | PRODUCT_RUNTIME | 正式页面资源 |

Ignored 安装元数据（非源码）：`src/fishery_ai_prototype.egg-info/{dependency_links.txt,PKG-INFO,requires.txt,SOURCES.txt,top_level.txt}`。可重建，不因审计自动清理。

## 附录 B：tests 逐文件分类

方法数为AST声明数量，不含subTest展开/导入/继承收集。CORE_TEST中的“旧版本”是名字，不是删除依据。

| 路径 | 分类 | 方法数 / 用途 |
|---|---|---|
| `tests/historical_model_fixtures.py` | CORE_TEST | 0；19个test模块的显式历史资源隔离 |
| `tests/test_a316_runtime_defaults.py` | CORE_TEST | 4；现代码合同/回归，保留 |
| `tests/test_access_web.py` | CORE_TEST | 7；现代码合同/回归，保留 |
| `tests/test_analysis_tool_web.py` | CORE_TEST | 7；现代码合同/回归，保留 |
| `tests/test_analysis_tools.py` | CORE_TEST | 26；现代码合同/回归，保留 |
| `tests/test_assistant_qualification.py` | QUALIFICATION_INFRA | 48；现代码合同/回归，保留 |
| `tests/test_assistant_sources.py` | CORE_TEST | 33；现代码合同/回归，保留 |
| `tests/test_assistant.py` | CORE_TEST | 49；现代码合同/回归，保留 |
| `tests/test_catalog_knowledge.py` | CORE_TEST | 12；现代码合同/回归，保留 |
| `tests/test_clean_room_reset.py` | CORE_TEST | 10；现代码合同/回归，保留 |
| `tests/test_cloud_capability.py` | CORE_TEST | 21；现代码合同/回归，保留 |
| `tests/test_credential_compatibility.py` | CORE_TEST | 6；现代码合同/回归，保留 |
| `tests/test_credential_writer.py` | CORE_TEST | 40；现代码合同/回归，保留 |
| `tests/test_credentials_private_storage.py` | CORE_TEST | 20；现代码合同/回归，保留 |
| `tests/test_credentials.py` | CORE_TEST | 30；现代码合同/回归，保留 |
| `tests/test_cross_model_qualification.py` | HISTORICAL_EXPERIMENT | 39；冻结实验/Runner；含待提炼的长期合同 |
| `tests/test_current_water_quality.py` | CORE_TEST | 22；现代码合同/回归，保留 |
| `tests/test_deepseek_projection_continuation.py` | HISTORICAL_EXPERIMENT | 18；冻结实验/Runner；含待提炼的长期合同 |
| `tests/test_default_preference_ui.py` | CORE_TEST | 7；现代码合同/回归，保留 |
| `tests/test_evidence_resolver.py` | CORE_TEST | 12；现代码合同/回归，保留 |
| `tests/test_execution.py` | CORE_TEST | 9；现代码合同/回归，保留 |
| `tests/test_gateway_tool_contract.py` | CORE_TEST | 29；现代码合同/回归，保留 |
| `tests/test_history_product_migration.py` | CORE_TEST | 9；9个新合同；26次继承/导入重复候选 |
| `tests/test_knowledge_assembly.py` | CORE_TEST | 7；现代码合同/回归，保留 |
| `tests/test_knowledge_handler.py` | CORE_TEST | 15；现代码合同/回归，保留 |
| `tests/test_knowledge_registration.py` | CORE_TEST | 17；现代码合同/回归，保留 |
| `tests/test_local_preset_qualification.py` | QUALIFICATION_INFRA | 11；现代码合同/回归，保留 |
| `tests/test_local_profile_capability_ui.py` | CORE_TEST | 8；现代码合同/回归，保留 |
| `tests/test_manual_v2.py` | CORE_TEST | 19；现代码合同/回归，保留 |
| `tests/test_mock_tool_gateway.py` | CORE_TEST | 23；现代码合同/回归，保留 |
| `tests/test_off_streaming_combination.py` | CORE_TEST | 9；现代码合同/回归，保留 |
| `tests/test_ollama_reasoning.py` | CORE_TEST | 7；现代码合同/回归，保留 |
| `tests/test_output_parity.py` | CORE_TEST | 4；现代码合同/回归，保留 |
| `tests/test_preset_publication.py` | CORE_TEST | 15；现代码合同/回归，保留 |
| `tests/test_preset_tool_qualification.py` | QUALIFICATION_INFRA | 22；现代码合同/回归，保留 |
| `tests/test_preset.py` | CORE_TEST | 4；现代码合同/回归，保留 |
| `tests/test_product_migration_runner.py` | HISTORICAL_EXPERIMENT | 16；冻结实验/Runner；含待提炼的长期合同 |
| `tests/test_protocol_specs.py` | CORE_TEST | 3；现代码合同/回归，保留 |
| `tests/test_qualification_history.py` | HISTORICAL_EXPERIMENT | 18；冻结实验/Runner；含待提炼的长期合同 |
| `tests/test_qualification_migration.py` | HISTORICAL_EXPERIMENT | 17；冻结实验/Runner；含待提炼的长期合同 |
| `tests/test_qualification_projection.py` | HISTORICAL_EXPERIMENT | 29；冻结实验/Runner；含待提炼的长期合同 |
| `tests/test_read_only_tools.py` | CORE_TEST | 35；现代码合同/回归，保留 |
| `tests/test_scenario_templates.py` | CORE_TEST | 19；现代码合同/回归，保留 |
| `tests/test_telemetry_simulator.py` | CORE_TEST | 18；现代码合同/回归，保留 |
| `tests/test_tool_argument_contract.py` | CORE_TEST | 14；现代码合同/回归，保留 |
| `tests/test_tool_capability_probe.py` | CORE_TEST | 17；现代码合同/回归，保留 |
| `tests/test_tool_conversation.py` | CORE_TEST | 37；现代码合同/回归，保留 |
| `tests/test_tool_policy_manager.py` | CORE_TEST | 21；现代码合同/回归，保留 |
| `tests/test_tool_policy.py` | CORE_TEST | 15；现代码合同/回归，保留 |
| `tests/test_tool_status_no_match.py` | CORE_TEST | 10；现代码合同/回归，保留 |
| `tests/test_unknown_model_probe.py` | CORE_TEST | 9；现代码合同/回归，保留 |
| `tests/test_v01.py` | CORE_TEST | 21；现代码合同/回归，保留 |
| `tests/test_v011_a1.py` | CORE_TEST | 20；现代码合同/回归，保留 |
| `tests/test_v011_a2_1.py` | CORE_TEST | 7；现代码合同/回归，保留 |
| `tests/test_v011_a2.py` | CORE_TEST | 4；现代码合同/回归，保留 |
| `tests/test_v011_a3_grounding.py` | CORE_TEST | 8；现代码合同/回归，保留 |
| `tests/test_v011_a3_profile_manager.py` | CORE_TEST | 8；现代码合同/回归，保留 |
| `tests/test_v011_a3_web.py` | CORE_TEST | 6；现代码合同/回归，保留 |
| `tests/test_v011_a31_streaming.py` | CORE_TEST | 13；现代码合同/回归，保留 |
| `tests/test_v011_a313_capability_identity.py` | CORE_TEST | 6；现代码合同/回归，保留 |
| `tests/test_water_quality_matrix.py` | CORE_TEST | 9；现代码合同/回归，保留 |
| `tests/test_water_quality_scoring.py` | CORE_TEST | 17；现代码合同/回归，保留 |
| `tests/test_web_tool_conversation.py` | CORE_TEST | 24；现代码合同/回归，保留 |
| `tests/fixtures/historical_model_assets/README.md` | CORE_TEST | 兼容基准/历史配置Fixture，保持隔离 |
| `tests/fixtures/historical_model_assets/official_declarations.json` | CORE_TEST | 兼容基准/历史配置Fixture，保持隔离 |
| `tests/fixtures/historical_model_assets/profiles/deepseek_experimental.json` | CORE_TEST | 兼容基准/历史配置Fixture，保持隔离 |
| `tests/fixtures/historical_model_assets/profiles/ollama_qwen35_local.json` | CORE_TEST | 兼容基准/历史配置Fixture，保持隔离 |
| `tests/fixtures/historical_model_assets/profiles/presets.json` | CORE_TEST | 兼容基准/历史配置Fixture，保持隔离 |
| `tests/fixtures/historical_model_assets/profiles/qwen_experimental.json` | CORE_TEST | 兼容基准/历史配置Fixture，保持隔离 |
| `tests/fixtures/r0_runtime_baseline.json` | CORE_TEST | 兼容基准/历史配置Fixture，保持隔离 |
| `tests/manual_edge_mock_probe.cjs` | ONE_OFF_RUNNER | 旧CDP页面验证，非默认测试 |
| `tests/test_browser_streaming.cjs` | CORE_TEST | 188项离线Node VM回归 |

## 附录 C：scripts 逐文件分类

固定实验JSON保留完整清单，归档时必须与source allowlist / PS hashes / index / tests / docs同步，不单独删。

| 路径 | 分类 | 用途 |
|---|---|---|
| `scripts/manifests/assistant-DEEPSEEK-H2-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-DEEPSEEK-H2-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-DEEPSEEK-H2F.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-DEEPSEEK-H5-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-DEEPSEEK-H5-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H0.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H1.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H2-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H2-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H2.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H3.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H4.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H5-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H5-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H5.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H6-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H6-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H6.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-H6F.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-OLLAMA-H2-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-OLLAMA-H2-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-OLLAMA-H2F.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-OLLAMA-H5-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-OLLAMA-H5-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-Q1.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-Q2.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-Q3.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/assistant-Q4.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-DEEPSEEK-S1-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-DEEPSEEK-S1-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-DEEPSEEK-S3-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-DEEPSEEK-S3-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-DEEPSEEK-S7-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-DEEPSEEK-S7-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-OLLAMA-S1-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-OLLAMA-S1-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-OLLAMA-S3-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-OLLAMA-S3-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-OLLAMA-S4-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-OLLAMA-S4-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-OLLAMA-S7-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-OLLAMA-S7-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S1-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S1-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S2-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S2-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S3-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S3-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S4-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S4-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S5K-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S5K-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S5O-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S5O-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S6-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S6-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S7-A.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/assistant-P2E-QWEN-S7-B.json` | HISTORICAL_EXPERIMENT | 固定资格manifest |
| `scripts/manifests/product-migration/qualification-plan.json` | HISTORICAL_EXPERIMENT | 冻结P2E顺序/hash索引 |
| `scripts/prepare_product_migration_qualification.py` | HISTORICAL_EXPERIMENT | 冻结P2E索引生成/审计 |
| `scripts/projection_qualification_runner.ps1` | HISTORICAL_EXPERIMENT | P2D共享调度/JSON安全合同，P2E复用部分 |
| `scripts/qualify_assistant_turn.py` | QUALIFICATION_INFRA | 单次显式授权资格入口 |
| `scripts/qualify_local_preset_request.py` | DEV_TOOL | 精确Ollama本地请求检查 |
| `scripts/qualify_preset_tools.py` | QUALIFICATION_INFRA | 单次显式授权资格入口 |
| `scripts/run_deepseek_projection_qualification.ps1` | ONE_OFF_RUNNER | 已结束固定批次 |
| `scripts/run_deepseek_projection_qualification_remaining.ps1` | ONE_OFF_RUNNER | 已结束首样本continuation |
| `scripts/run_ollama_projection_qualification.ps1` | ONE_OFF_RUNNER | 已结束固定批次 |
| `scripts/run_product_migration_qualification.ps1` | ONE_OFF_RUNNER | 已结束固定批次 |

## 附录 D：docs 逐文件分类

研究及记录不删除；“保留”指内容保留，“归档”指退出主导航、仍可查证。

| 路径 | 分类 | 建议 |
|---|---|---|
| `docs/BUILD_RUN.md` | DEV_TOOL | 当前维护文档，保留并按实际状态修正 |
| `docs/CODE_REVIEW.md` | DEV_TOOL | 当前维护文档，保留并按实际状态修正 |
| `docs/ROADMAP.md` | DEV_TOOL | 当前维护文档，保留并按实际状态修正 |
| `docs/STRUCTURE.md` | DEV_TOOL | 当前维护文档，保留并按实际状态修正 |
| `docs/TROUBLESHOOTING.md` | DEV_TOOL | 当前维护文档，保留并按实际状态修正 |
| `docs/deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md` | DEV_TOOL | 当前维护文档，保留并按实际状态修正 |
| `docs/deep-dive/data-domain/WATER_QUALITY_SCENARIO_AND_TELEMETRY_PREPARATION.md` | DEV_TOOL | 当前维护文档，保留并按实际状态修正 |
| `docs/deep-dive/models/PRESET_PUBLICATION.md` | DEV_TOOL | 当前维护文档，保留并按实际状态修正 |
| `docs/deep-dive/models/STREAMING_THINKING_OFF_COMBINATION.md` | DEV_TOOL | 当前维护文档，保留并按实际状态修正 |
| `docs/deep-dive/operations/PRIVATE_CREDENTIAL_STORAGE.md` | DEV_TOOL | 当前维护文档，保留并按实际状态修正 |
| `docs/deep-dive/operations/PROJECT_DATA_AND_CONFIG_LOCATIONS.md` | DEV_TOOL | 当前维护文档，保留并按实际状态修正 |
| `docs/deep-dive/research/KNOWLEDGE_TOOL_DESIGN.md` | HISTORICAL_REPORT | 未来研究/历史baseline，保留且不作为CURRENT |
| `docs/deep-dive/research/TOOL_ORCHESTRATION_ARCHITECTURE_REVIEW.md` | HISTORICAL_REPORT | 未来研究/历史baseline，保留且不作为CURRENT |
| `docs/deep-dive/tools/ADDING_A_TOOL.md` | DEV_TOOL | 当前维护文档，保留并按实际状态修正 |
| `docs/deep-dive/tools/READ_ONLY_TOOL_CALLING.md` | DEV_TOOL | 当前维护文档，保留并按实际状态修正 |
| `docs/notes.md` | UNKNOWN | 用户backlog可能独有，先确认再合并 |
| `docs/records/2026-10-assistant-history-projection-ab.md` | HISTORICAL_REPORT | 提炼少量当前事实后归档原文 |
| `docs/records/2026-10-assistant-history-projection-research.md` | HISTORICAL_REPORT | 提炼少量当前事实后归档原文 |
| `docs/records/2026-10-assistant-history-tool-reliability-study.md` | HISTORICAL_REPORT | 提炼少量当前事实后归档原文 |
| `docs/records/2026-10-assistant-turn-source-contract-p1.md` | HISTORICAL_REPORT | 提炼少量当前事实后归档原文 |
| `docs/records/2026-10-codex-takeover-audit.md` | HISTORICAL_REPORT | 提炼少量当前事实后归档原文 |
| `docs/records/2026-10-controlled-assistant-qualification-p2a.md` | HISTORICAL_REPORT | 提炼少量当前事实后归档原文 |
| `docs/records/2026-10-cross-model-history-projection-preparation.md` | HISTORICAL_REPORT | 提炼少量当前事实后归档原文 |
| `docs/records/2026-10-deepseek-history-projection-results.md` | HISTORICAL_REPORT | 提炼少量当前事实后归档原文 |
| `docs/records/2026-10-history-projection-product-migration-qualification.md` | HISTORICAL_REPORT | 提炼少量当前事实后归档原文 |
| `docs/records/2026-10-history-v2-migration-decision.md` | HISTORICAL_REPORT | 最近关键决定，records根保留 |
| `docs/records/2026-10-history-v2-product-migration.md` | HISTORICAL_REPORT | 最近关键决定，records根保留 |
| `docs/records/2026-10-knowledge-tool-v1-summary.md` | HISTORICAL_REPORT | 提炼少量当前事实后归档原文 |
| `docs/records/2026-10-ollama-history-projection-results.md` | HISTORICAL_REPORT | 提炼少量当前事实后归档原文 |
| `docs/records/2026-10-qwen-tool-provider-evidence.md` | HISTORICAL_REPORT | 提炼少量当前事实后归档原文 |
| `docs/records/README.md` | DEV_TOOL | 简短当前记录索引，删除重复/过时导航说明 |
| `docs/records/archive/copilot-tool3-records-2026-10.zip` | HISTORICAL_REPORT | 既有历史文档档案，原样保留 |
| `docs/records/archive/pre-codex-handoff-2026-10.zip` | HISTORICAL_REPORT | 既有历史文档档案，原样保留 |

根README / AGENTS / pyproject / .gitignore保持。报告完成后的检查仅为本地Markdown链接、git diff --check与git status；没有新测试验收结论。


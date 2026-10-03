# Clean-room Model Validation Reset

日期：2026-10-03。阶段 B 保留在工作树，未 commit / push。

本文第 2–6 节记录初次 Reset 当时的状态；其后的人工新建 Profile / Evidence 不会被本轮再次清空。最新人工验收修复和测试结果见第 7 节。

## 1. 阶段 A checkpoint

`f128bb73ad9fd5b1a5dd6824aac4e5ad9007f4cd` 已提交并推送 main，消息为 `fix: gate saved thinking preferences by resolved capabilities`。

默认运行偏好默认折叠；AUTO 始终可选，新选 ON/OFF 受当前精确 Capability 门禁控制。旧偏好保留，并分别显示保存值、当前能力与实际安全值。用户已报告真实 Probe 及 R5 → Evidence → R4 → Capability Gate → 正式请求人工跑通；本轮没有重复真实请求。

阶段 A：Python 307 项、Browser 70 项通过。v0.1 仍为 `5cc274021da44fdae198e6250be81023c185888e`。

## 2. 实际审计与清理

| 活动输入 | 审计结果 | 重置方式 |
| --- | --- | --- |
| `outputs/custom_profiles/*.json` | 6 个 User Custom，默认运行偏好内嵌在 Profile 中 | 移入非活动归档，不删除原数据 |
| `outputs/capability-evidence/*.json` | 27 个精确身份记录；该目录是 Probe / USER_VERIFIED / Metadata 的共同持久化边界 | 全部移入非活动归档 |
| `resources/profiles/qwen_experimental.json` | 旧 Qwen 实例及能力 | 活动 `profiles` 置空，公开原数据保留为测试 fixture |
| `resources/profiles/deepseek_experimental.json` | 旧 DeepSeek 实例及能力 | 同上 |
| `resources/profiles/ollama_qwen35_local.json` | 旧 Ollama 实例及 Metadata 结论 | 同上 |
| `resources/profiles/presets.json` | 3 个历史模板，包括发布与候选 Variant | 活动 `templates` 置空，schema / loader 保留 |
| `official_capabilities.DECLARATIONS` | 5 条精确 service / URL / model 声明 | 活动声明表置空，原数据仅保留为离线研究 fixture |

本地归档位置：`outputs/archive/model-validation-reset-20261003/`，包含原目录分组和 `manifest.json` 路径清单。整个 `outputs/` 仍 Git ignored。原有已删除 Profile 的非活动 archive、真实验证记录与 Trace 保留，未读取其内容。

公开历史 fixture 位于 `tests/fixtures/historical_model_assets/`。历史兼容测试通过明确的模块生命周期工具加载，测试结束恢复活动空目录；这些 fixture 不打包、不被正常 Web / CLI / Resolver 读取。新增 Clean-room 测试不使用该工具，直接验证真实空目录。

### 隐藏依赖修复

`/api/config` 原先从 Built-in 模型实例提取 Provider 连接模板；清空 Built-in 后会发生 `KeyError`。现直接从现有 ProviderRegistry 提取连接信息，Model 留空，不携带能力。

空 Preset / Managed / Manual 页面现显示各自说明，禁止无目标 Send / Analyze，并清空上一选择的表单。Managed 仍可打开全新表单；Mock 位于 Development / Test。

历史 `validate-real`、三个 `validate_qwen_*.py` 和 `validate_access_modes.py` 不再找到活动旧模型时，安全返回 `INACTIVE_VALIDATION_PROFILE`，不读归档或旧源码 `.env`，不发请求。原确认、retry、timeout 与验证业务合同保留在显式历史测试中。

## 3. 保留边界

- ProviderRegistry / ProviderSpec / AuthSpec、R3 ProtocolSpec 与已有编码参考保持；精确模型 codec 例外是参数编码知识，不是支持证据。
- Adapter / Gateway、Usage / Trace、R4 Resolver、R5 单次显式 Probe、Cancellation 与 Manual V1 保持。
- Profile / Evidence / Preset schema 与加载器、测试框架、文档和 Git 历史保持。
- CredentialStore / Writer 和私有凭据路径规则保持；未读取、复制、修改或删除任何真实凭据，未操作真实 ACL。
- 凭据优先级仍为 PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING；没有根 `.env` fallback、load_dotenv 或环境变量写入。
- Manual V1 Raw JSON 仍独立，不经 Resolver / ProtocolSpec 自动改写。当前需要先保存一个 Connection 才能选择目标。
- Mock 仅用于离线流程；`resources/mock/` 的 cloud-demo / local-demo 仍只通过 MockGateway，不能解锁真实模型。
- `D:\Fishery_Project` 未被访问或修改。

## 4. 初始状态与新证据

当前真实活动 Preset、Built-in、Custom 均为 0；活动本地 Evidence 为 0，官方模型声明为 0。Provider 连接模板仍有 4 类，Model 不自动填写。

新建 exact model 时，Streaming / Thinking ON / Thinking OFF / Combination / Effort / Structured Output / Tool Calling 均 UNKNOWN，默认 Thinking AUTO、Response Normal。旧 Custom 默认值、旧 Probe、旧 Metadata、旧 Preset 与旧官方声明不继承。

Normal + AUTO 不发送高级开关。模型列表或连接测试成功只证明连接状态，不产生高级能力 Evidence。单项显式 Probe 成功后，仅写新证据并由 R4 重算对应精确身份；网络失败不写 UNSUPPORTED。ProtocolSpec 不授予 Capability。

## 5. 验证结果

| 检查 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests -p test_clean_room_reset.py -v` | 10 项通过 |
| Browser 定向：`clean-room\|new Custom Profile first Streaming Probe\|R2 draft profile` | 4 项通过 |
| `python -m unittest discover -s tests` | 317 项通过，11.548 秒 |
| `node --test tests/test_browser_streaming.cjs` | 72 项通过，无跳过 |
| `node --check src/fishery_ai/resources/web/app.js` | 通过 |
| `git diff --check` | 通过 |
| 公开 Git 文件 Secret / sensitive-path 扫描 | 未发现风险；仅明确虚构 fixture 排除，不扫描真实凭据或 ignored outputs |
| Mock CLI Demo | 完成，无模型请求 |
| 新进程 Web `http://127.0.0.1:8768` | 页面、JS、空 `/api/config`、Mock Normal / SSE completed 均通过真实本机 HTTP 检查 |

测试验证首次连接保存、模型列表不授予能力、精确身份隔离、新 Probe → Evidence → Resolver、普通 UNKNOWN gate、私有凭据 hot reload / PROCESS_ENV 优先及旧 `.env` 不 fallback。完整回归保留 Credential CRUD / 安全、Manual 原始结果与取消路径覆盖。

浏览器自动化两次因 Windows 沙盒 helper 初始化失败，未完成实机页面点击检查。首次新建、空状态、Credential Manager、未知选项锁定及 Probe 即时解锁由离线 Browser 测试覆盖；实际视觉与点击仍需用户验收。本机 HTTP 检查未调用 Credential 状态接口、未读取真实 Key，也未发真实 Cloud / Ollama 请求。

## 6. 工作树与首次人工验证

阶段 B 修改活动资源、官方声明数据、Web 空状态 / 连接模板、历史验证入口保护、显式历史测试 fixture、Clean-room 测试及本文 / BUILD_RUN / 导航。R2、R3 编码、R4 算法、R5 Probe、Adapter、Cancellation、Manual 与 Fishery Analysis 核心代码未修改。阶段 B 未暂存、未 commit / push，main checkpoint 仍为阶段 A。

1. 完整重启原 Web 进程，避免旧进程保留重置前内存；可先查看本轮 `127.0.0.1:8768`。
2. 切换 Managed Custom → 新建，选择 Provider，确认连接 URL、精确 Model 和 credential_ref。
3. 查看私有凭据状态；已有 Key 保留，缺失时通过 Credential Manager 显式设置。不要恢复根 `.env` 读取。
4. 显式查询模型 / 连接测试，保存第一个唯一名称连接，确认所有高级能力仍 UNKNOWN。
5. 先 Normal + AUTO 验证基础链路，再单项 Streaming / Thinking ON / OFF Probe。每次明确确认 REAL NETWORK REQUEST。
6. 确认新 Evidence 时间和身份、Resolver 状态、UI 即时解锁，再运行相应 Fishery Analysis。Combination 单独验证。

恢复历史资料应由用户明确决定；不要直接将归档或测试 fixture 自动复制回活动输入，否则会失去本轮干净起点。

## 7. 人工验收修复：默认偏好与编辑草稿

### 人工发现与根因

用户发现 Thinking ON/OFF 已 Probe 为 SUPPORTED，但 Default Thinking 仍禁用；Streaming 为 UNKNOWN 时 Default Response 却可选 Streaming；点击编辑后当前能力可能变 UNKNOWN。

代码确认：`editSelected()` 调用 `invalidateTest()`，后者混用了连接测试缓存失效、草稿身份失效与当前运行 Capability 清空，覆盖刚加载的门禁。Probe 的 `refreshProfiles()` 原先只等待配置列表，表单读取尚未完成便返回；默认偏好刷新链不完整。Default Response 原先是静态下拉框，没有 Capability 门禁。

### 修复

- 默认 Thinking 与 Response 使用同一 Resolved Profile 更新流程：AUTO / Normal 始终可选，ON / OFF / Streaming 仅对应 SUPPORTED 可新选；UNKNOWN / UNSUPPORTED / EVIDENCE_CONFLICT 禁用并解释原因。
- Probe / Metadata 刷新等待配置及表单完成，Capability 面板、当前运行选项与默认偏好门禁同步更新。编辑中的未保存草稿可保留；其身份不同于当前 Profile 时不会继承当前模型的能力。
- 引入轻量 `editDraft`，仅持有已保存表单基线和 Profile ID；DOM 表单承载未保存字段。当前 `profiles` / Selected Profile / Runtime 控件继续引用已保存对象。
- 进入编辑或修改草稿不再清空当前面板、运行选项或 Evidence。草稿 Identity 用 service / adapter / 规范化 URL / exact Model 比较；URL scheme / host 大小写和末尾 `/` 不构成新身份。
- Identity 改动仅显示“保存后重新解析”的提示，并限制新草稿高级偏好的选择；旧 ON/OFF/Streaming 偏好不静默删除。原 Profile 仍可正常运行或执行其精确 Probe。
- 此次修复最初将“保存修改 / 取消编辑”放在管理操作区；保存按钮位置随后由第 8 节调整。取消仅恢复缓存的已保存表单，丢弃草稿和草稿测试状态，不写 Profile / Evidence，不请求 R4 重新解析，不更改当前运行选项。
- 保存成功后仍复用已有 PUT → Persist → R4 Resolver → 页面刷新。新身份 UNKNOWN 时当前运行安全回退 AUTO + Normal；已保存历史偏好继续可读。
- 异步刷新不会重新打开已取消的草稿，或覆盖期间新进入的编辑状态。

后端 CapabilityValidator、R3 ProtocolSpec、R4 / R5、CredentialStore、Manual、Cancellation、Orchestrator 均未改动。本轮只修改 `app.js`、`index.html`、相关 Browser / Python 测试和本文。没有再次归档人工创建的模型 / Evidence，没有读取或修改真实凭据，没有真实模型请求，也没有 commit / push。

### 测试

| 命令 / 检查 | 本次结果 |
| --- | --- |
| `python -m unittest discover -s tests -p test_default_preference_ui.py -v` | 7 项通过 |
| Browser 定向：`Default\|Probe refresh\|enter Edit\|Cancel Edit\|saving changed Identity\|normalized trailing\|editing draft` | 15 项通过 |
| `python -m unittest discover -s tests` | 321 项通过，13.168 秒 |
| `node --test tests/test_browser_streaming.cjs` | 81 项通过，无跳过 |
| JS syntax / `git diff --check` | 通过 |
| Secret / sensitive-path scan | 公开 Git 文件受控扫描未发现风险，不访问真实凭据或 ignored 本地数据 |

覆盖：ON/OFF 独立 Probe 即时解锁、Streaming Default 门禁、编辑/草稿不改变当前运行、取消完全恢复、保存后才切换身份、新身份安全回退且保留偏好、同 Identity 共享 Evidence、不同 Model / Provider 隔离、草稿 Probe 刷新及取消竞态。所有自动测试使用临时 Profile / Evidence / CredentialStore 和虚构响应，网络保持禁止。

### 再次人工验收

重启 Web 后对已验证 Profile 点击编辑，确认默认 ON/OFF 和 Streaming 可选；修改 Model / URL 时，当前能力面板和运行选择应保持原值，仅显示草稿提示。点击取消应恢复旧表单。保存新 Model 后确认能力重新解析，未验证高级选项锁定且实际运行 AUTO + Normal，旧偏好仍显示。单项 Probe 后无需重建 Profile 或刷新页面即可解锁对应默认偏好。

## 8. 最终 UI 调整：保存位置与退出新建

编辑已有 Profile 时，顶部保留“取消编辑”，“保存修改”恢复到表单下方的连接测试之后。新建时隐藏“编辑所选”和“取消编辑”，顶部显示“退出新建”；“创建 Profile”仍在表单提交位置。View / Edit / Create 三种状态的按钮分别显示，不相互冲突。

进入新建前，仅在页面内保存表单引用字段、运行选项、折叠状态及原编辑草稿；不保存真实 Key。退出新建丢弃未保存的新建字段，恢复此前的 View 或 Edit 状态；从 Edit 进入新建后退出，还可继续原草稿或取消编辑。空状态退出不尝试读取不存在的 Profile。

退出操作复用现有已保存 Profile 的只读显示流程，不写 Profile / Evidence，不修改后端 Resolve 或 Capability 逻辑。连接测试缓存仅在凭据代际未变化时恢复，避免恢复已经失效的授权。本轮未改后端、RAG、Grounding、Orchestrator、CredentialStore 或 Probe。

### 最终检查

| 命令 / 检查 | 结果 |
| --- | --- |
| `node --test --test-name-pattern='Profile submit\|Exit Create' tests/test_browser_streaming.cjs` | 4 项通过 |
| `python -m unittest discover -s tests` | 321 项通过，13.820 秒 |
| `node --test tests/test_browser_streaming.cjs` | 85 项通过，无跳过 |
| `node --check src/fishery_ai/resources/web/app.js` | 通过 |
| `git diff --check` | 通过 |
| Secret / sensitive-path 扫描 | 126 个公开文件，5 处明确虚构 fixture 排除，未发现风险；不读取真实凭据或 ignored 本地数据 |

新增 Browser 测试覆盖按钮位置与三种状态、退出恢复 View / Runtime、退出恢复原 Edit 草稿及取消、Clean-room 空状态。没有真实联网或模型请求，未访问正式项目或真实凭据；没有 commit / push。

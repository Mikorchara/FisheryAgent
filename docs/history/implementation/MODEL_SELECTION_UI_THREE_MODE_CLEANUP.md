# 模型选择 UI 收敛与 Manual Expert 独立页面

日期：2026-10-02。基于尚未提交的 Preset / R6 / R7 工作树，HEAD 仍为 `20744631dc627b48657ce19e6b62818bd064d67a`。本轮不 commit / push、不移动 tag。

## 1. 范围与依据

用户反馈：上一阶段 Preset、Cancellation、Manual、Custom CRUD 主要功能已人工验证正常。此反馈属于 USER-VERIFIED，不覆盖上一报告中的历史联网失败记录，也不代表本轮新 UI 已人工验收。

本轮仅调整包内 HTML / CSS / JavaScript、UI 测试和文档。没有更改后台 Adapter、CredentialStore、Capability 系统、Preset Contract、Cancellation、Orchestrator、RAG、Grounding 或 Domain Rule。未实施 R3/R4/R5、Tool Calling、Agent；未访问或修改正式项目。

## 2. 最终信息架构

一级运行方式为：

| 方式 | 模型 / 目标选择 | 运行与管理边界 |
|---|---|---|
| Preset | 每个已发布模板只显示一个 Model；单独选择 Variant | 固定合同；无新建、编辑、删除或 Probe；Response Mode 独立 |
| Managed Custom | 只列 User Custom Profiles | 现有新建、编辑、删除及 Capability 管理，后端 CRUD 不变 |
| Manual Expert | 最小的已保存 Connection / Target 选择 | 独立 Raw Request / Send / Stop / Raw Response；不参与分析或 Capability 管理 |

默认进入 Preset，仅加载配置和安全状态，不发送生成请求。Development / Test 是明确折叠的附加入口，不是第四种正式模型方案。Mock 在该入口用于离线演示；旧 Ollama 显示 Local Experimental，仍不发布为 Preset。

Manual 目标列表对同一 Preset 的 Variant 连接收敛一次，但保留每个 User Custom 连接，避免相同 endpoint/model 下不同 credential 或 timeout 的配置被误合并。Manual 不是新增 Profile。

## 3. Built-in 退出 UI 与兼容策略

移除旧 Built-in Profiles 分组；旧 Qwen / DeepSeek Cloud ID 不在任何可见模型或 Manual 目标列表中重新包装出现。只重挂 Mock 与 Local Experimental 的开发用途。

底层保留 `qwen-plus-experimental`、`deepseek-v4-flash-experimental`、`mock-demo`、`ollama-qwen35-4b-local` 及现有注册、JSON、CLI、内部 API / 测试依赖。`/api/config` 和 Profile API 仍保留原始记录；前端按访问方式过滤。UI 隐藏不是删除或后端授权变化。

## 4. Model / Variant 映射

| UI Model | UI Variant | 原有精确后端 Profile ID |
|---|---|---|
| Qwen Plus | Provider Default (AUTO) | `preset-qwen-plus-auto` |
| Qwen Plus | Thinking OFF | `preset-qwen-plus-off` |
| Qwen Plus | Thinking ON | `preset-qwen-plus-on` |
| DeepSeek Flash | Provider Default (AUTO)，唯一项只读 | `preset-deepseek-flash-auto` |

仅按现有 `preset_id` 收敛 Model，不合并 RuntimeSnapshot、Variant ID、Identity 或能力合同。Variant 控件使用精确 Profile ID；分析请求、异步表单/Secret 状态守卫也使用实际 Variant，避免代表 Model 项与实际请求错位。

默认优先 AUTO，AUTO 不表示 OFF。Qwen Variant 切换时保留独立选择的 Response Mode，并按该 Variant 合同校验可用性；DeepSeek 仅 Normal，未新增 ON/OFF 或 Streaming 能力。原 EXPERIMENTAL 状态不升级。

## 5. Managed Custom CRUD

只有 Managed Custom 显示管理模型配置和新建/编辑/删除。唯一名称、创建后不可改名、本地连接校验、显式联网连接测试、归档删除和 Git ignored 持久化规则沿用原后端。

无自定义连接时显示明确空状态，分析禁用，可点击新建；不自动回退到 Preset、Mock 或旧 Cloud Built-in。新建表单继续清空旧连接字段。

## 6. Manual 独立界面与执行边界

右侧独立宽面板提供 Raw JSON、Send、Raw Response / Usage / Latency。左侧仅保留运行方式、已保存目标和共用 Stop。Capability、Probe、Evidence、Thinking、Response Mode、水质场景、分析按钮、Profile CRUD、默认偏好与凭据写入表单全部隐藏。

切换目标重置最小请求草稿；仅切换访问方式会保留原 Manual 目标与草稿。草稿仅在页面内存，不写 LocalStorage 或文件。

沿用 `/api/manual` 和独立 ManualRequest：不经过 Orchestrator、Diagnosis、RAG、AnalysisResult、CapabilityValidator、Probe 或 Runtime Defaults；不自动加入 Thinking、Effort、include_usage、tools；tool_calls 只展示，不执行。Raw response 是原有 SDK JSON 表示，不宣称字节级 HTTP 透传。

仍使用固定目标、不可变凭据快照、Authorization、大小限制、Timeout、retry=0、安全错误和脱敏。更改连接或凭据需离开 Manual，进入现有管理入口；Manual 不接受任意 URL / Header / credential path。

## 7. Cancellation 与 R2

Send / Analyze 沿用同一 RequestHandle 和 Stop。执行期间锁定 mode、model、variant、development target，防止请求运行中改变页面目标；取消先发送后端控制请求，再停止浏览器读取。

浏览器停止显示、后端 I/O 关闭和远程推理/计费停止仍分别表示；没有新增远端停止保证。R2 冻结：PROCESS_ENV > user-private PROJECT_ENV > MISSING，不读旧源码根 .env，不自动迁移或回退，不更改 ACL。

## 8. 测试结果

| 检查 | 命令 / 范围 | 结果 |
|---|---|---|
| Targeted Python | `test_preset.py` 4 项、`test_access_web.py` 7 项、`test_v011_a3_grounding.py` 9 项 | 20 项通过 |
| Targeted Browser | `node --test --test-name-pattern 'three-mode' tests/test_browser_streaming.cjs` | 新增 15 项通过；另两项旧 Probe 定向回归通过 |
| Full Python | `python -X utf8 -m unittest discover -s tests -q` | 280 项通过，约 11 秒 |
| Full Browser | `node --test tests/test_browser_streaming.cjs` | 63 项通过 |
| JS syntax | `node --check src/fishery_ai/resources/web/app.js` | 通过 |
| diff check / Secret scan | `git diff --check`；110 个公开文本文件及 Git 跟踪路径，不读真实 .env / outputs / 外部私有凭据 | 通过；无风险命中，无敏感存储被跟踪 |

第一次完整 Python 回归仅因下述旧 UI 断言失败，修正后定向和最终完整回归均通过。安全扫描只作凭据特征及敏感路径检查，不代表完整安全证明。

更新了一项 Python 旧 UI 断言：原来强制 Built-in Profiles 出现，现改为确认其消失并检查三模式结构；Grounding 测试未删除。两项旧 Browser 用例改为 Managed Custom 场景 / 先进入 Managed Custom 新建，保留 Probe 断言。其余后台 legacy / 凭据兼容测试继续保留。

Browser 回归采用 Node VM + DOM / fetch mocks，不等同于真实浏览器视觉验收。自动测试只有假 transport 和临时虚构凭据；本轮真实模型请求为 0，没有读取真实 Key、修改 ACL、回退 root .env 或改变网络配置。

## 9. 改动与 Git 状态

本轮修改：`resources/web/app.js`、`index.html`、`app.css`、`tests/test_browser_streaming.cjs`、`tests/test_v011_a3_grounding.py`、`docs/BUILD_RUN.md`、`docs/STRUCTURE.md`、deep-dive 导航；新增本报告。

Git diff 包含上一阶段尚未提交的 Preset / Cancellation / Manual 实现；不能把合并工作树的所有文件都归为本轮新增。工作树保留供用户审查，未提交或推送。最终相对 HEAD 的合并工作树：15 个已跟踪文件修改、11 个未跟踪新增文件；已跟踪 diff 为 1224 行新增、70 行删除（不含未跟踪新文件），其中包含上一阶段实现。HEAD 未变，`v0.1` 仍为 `5cc274021da44fdae198e6250be81023c185888e`。Frozen R2 五个模块相对 HEAD 无修改。

## 10. 人工验收与限制

1. 重启本地 Web 并刷新浏览器；Preset 中 Qwen 只出现一次，AUTO/OFF/ON 精确映射，DeepSeek 仅 AUTO + Normal，Preset 无 CRUD。
2. Managed Custom 新建干净表单、编辑不可改名、删除归档；Normal / Streaming 与安全错误显示仍正常。
3. Development 入口分别确认 Mock 离线分析与 Ollama Local Experimental 标识；不要将 Ollama 宣称为稳定 Preset。
4. Manual 仅显示目标、Raw JSON、Send / Stop / Raw Response；实测请求参数未自动注入，返回 tool_calls 不执行；Raw stream、Usage、取消显示符合预期。
5. 从用户正常启动环境验收私有凭据复用与 Stop；无需复制 Secret 给 Codex，不更改 ACL。停止界面不会证明云端已停止计费。
6. 浏览器视觉、真实服务行为和 GPU 状态本轮未观察；候选模型发布范围、Capability UNKNOWN 及后台限制仍沿用上一阶段。


## 11. 人工验收后的产品定义校正

用户已完成当前三模式界面人工测试，反馈已有功能基本正常（USER-VERIFIED）。本报告第 1–10 节中的待验收与未提交状态保留为历史记录；随后阶段收尾可按用户新授权 checkpoint。

Manual Expert 长期定位是 LLM / Provider API 实验台。当前 Saved Connection + Raw Request 是 V1 范围，未来 Manual Experiment 是独立实验资产，不是 Managed Custom Profile 的另一种表现形式。实验不自动进入正式模型列表，实验成功不等于 Fishery 兼容验证；任何转换机制 NOT DECIDED，V2 DEFERRED。本次审计无必须现在解除的 blocker，未修改核心实现。完整代码依据、暂时耦合及收尾结果见[既有实施报告第 10 节](PRESET_CANCELLATION_MANUAL_IMPLEMENTATION.md#10-manual-expert-产品定义校正与架构兼容性审计)。

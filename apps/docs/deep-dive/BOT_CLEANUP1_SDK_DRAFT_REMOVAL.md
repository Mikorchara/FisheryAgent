# BOT-CLEANUP-1：暂停 SDK 进程隔离草稿清理

日期：2026-10-26（UTC+8）。仅操作 Fishery_AI_Prototype。清理开始时 `main / 5641e4c`，工作树保留上一轮 BOT-REGRESSION-1 的 10 项已记录改动；未发现无法归属的修改。本轮不提交、不重置、不清理业务数据，不操作 Management 或其他项目。

## 1. 清理前复核

- 指定五个文件均为 Git 已跟踪文件，最后涉及提交为 `ddb9ecf`，相对 HEAD 无本地改动。
- 仅登记一个本仓工作树；代码/脚本引用仅在草稿之间与专用测试中。未发现生产链路或新的已登记开发依赖。
- `qq_bot/tests/test_qwen_trial.py` 的 `assertNotIn('sdk_process_adapter.py', ...)` 是 Scope 排除断言，保留；它不导入或执行草稿。
- 两个 Scope 都不包含草稿，清理前 FAST 与 BOT-REGRESSION-1 的实现指纹一致，基础 candidate 与维护文件匹配。
- 为 236 个受保护的 Python、JSON、启动脚本/工程配置保存字节哈希，包括 SDK 资源门禁、Service、RequestHandle、发布/资格合同及上一轮未提交的 Runtime/测试改动。

## 2. 实际删除范围

仅删除以下五个文件，共 649 行：

| 文件 | 行数 | 原用途 |
|---|---:|---|
| `apps/ai_backend/sdk_process_adapter.py` | 334 | 不可启用的 SDK 子进程父端草稿 |
| `apps/ai_backend/sdk_process_worker.py` | 125 | 未接入 worker 草稿 |
| `apps/ai_backend/sdk_process_protocol.py` | 76 | 草稿专用 JSON IPC 协议 |
| `apps/ai_backend/sdk_process_job.py` | 38 | 未验收的 Windows Job 草稿 |
| `apps/ai_backend/tests/test_sdk_process_paused.py` | 76 | 6 项入口拒绝/协议基础测试 |

没有删除资源门禁测试，也没有调整运行时行为。`sdk_resources.py`、原 Adapter 的资源生命周期、execution 的 Handle/Registry、Source/Commit Gate、QQ Scheduler/Delivery、Web Normal/Streaming 及 FAST 保持原样。

236 个受保护文件在删除后逐一比对，全部相同。删除六项暂停测试后，完整 Python 数量应由 874 降为 868；这属于删除未使用草稿的专用测试，不是关闭失败用例。

## 3. 文档整理

- 保留 [BOT-3C-2B 历史设计与暂停记录](BOT3C2B_SDK_PROCESS_ISOLATION.md)，明确文件已删除、当时测试数字是历史证据，不代表已有进程隔离能力。
- STRUCTURE 移除五个不存在的文件条目；README、ROADMAP、BUILD_RUN 与阶段总结指向当前清理状态。
- FAST 的现行专项命令移除已删除的测试模块。历史暂停页不再提供包含该模块的失效运行命令。
- 早期审计保留删除前的引用/副作用证据，并明确其为历史清单。

当前仍使用线程式 SDK I/O。清理失败隔离仍有效，但删除草稿不会带来强制终止不合作线程的能力，也不保证远端停止计算或计费。

## 4. Scope 与资格

| 项目 | 删除前 | 删除后 |
|---|---|---|
| Monitoring-only candidate | `af2ddb61aacd36e4706b381781974d92dd031bd1e3b6ed2f650607e3bee2e23d` | 完全相同 |
| BOT-3C-FAST | `5337073a2d049cdda4b65579156e87228903202acdb82e688abb4fa7a5683b54` | 完全相同 |
| candidate 状态 / qualification_id | candidate / null | 不变 |
| SDK 资源合同 | `sdk-resource-quarantine@1` | 不变 |

本轮不修改任何批准、Provider 回执或发布资格。BOT-REGRESSION-1 之前的真实报告/批准仍不匹配现在的 FAST 实现；删除草稿不会让它们重新有效。未来真实实验继续走现有独立审批。

## 5. 验证结果

| 验证 | 结果 |
|---|---|
| SDK 资源门禁 / SDK 内存 HTTP | 25 项通过，2.757s |
| Web AI Normal / Streaming | 78 项通过，17.964s |
| QQ FAST | 45 项通过，26.693s |
| QQ Bot 全部专项 | 275 项通过，91.932s |
| 完整 Python / Node | 868 Python 全部通过，222.140s；11 个 Node 文件、116 项全部通过，退出0 |
| 模块导入、Wheel 构建/内容检查 | 离线 Wheel 构建通过；源码/Wheel 各16个模块导入通过，4个已删除模块不可查找；包内无草稿/测试/业务库/凭据，13个受保护包内文件与原基线相同 |
| 文档链接 / git diff --check | 修改文档145个本地目标全部有效，diff检查通过；全册477个本地目标另有4处既存EVENT_ACK失效引用，见下 |

测试只使用 Fake SDK、Fake QQ、新建隔离 SQLite；没有读取实际业务实例或真实密钥，没有连接 QQ/Qwen。

构建使用已有基础 Python 的 setuptools/wheel，对一次性、仅包含受跟踪源码/静态资源的副本执行 `pip wheel --no-index --no-deps --no-build-isolation`。本项目 .venv 无构建工具，本轮没有向其中安装依赖，也不使用既有 build 目录或复制业务数据。

源码和 Wheel 在新进程内分别检查导入来源；网络、子进程启动、线程启动、凭据解析及 SQLite 连接均被拒绝，导入结束仅主线程、SDK active=0 / quarantined=0。该检查不是打包后真实业务/模型资格验收。Windows 导入探针保留 Popen 类型、仅禁止其构造，避免干扰 asyncio 的类继承；未修改任何生产模块。

可重复的资源专项与完整回归命令（普通 PowerShell，Prototype 根）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m unittest -q apps.ai_backend.tests.test_sdk_resources apps.qq_bot.tests.test_sdk_resource_gate apps.qq_bot.tests.test_provider_sdk_preparation
.\.venv\Scripts\python.exe -X utf8 -B -m unittest -q apps.qq_bot.tests.test_qwen_trial
.\.venv\Scripts\python.exe -X utf8 -B scripts/dev/run_tests.py management
.\.venv\Scripts\python.exe -X utf8 -B -m apps.qq_bot --check-ai-readiness
```

## 6. 审计记录与 Git

非敏感校验记录与隔离打包产物保留在：

```text
outputs/test-tmp/bot-cleanup1-20261025T160738Z-96dbd8bd56/
  before.json                       # 开始状态、五文件哈希、受保护文件哈希、Scope
  after_delete.json                 # 精确删除范围、Scope/受保护文件一致性
  packaging-source-manifest.json    # 仅源码/静态资源的暂存清单
  wheel-source/                     # 新建打包副本；不含业务实例或凭据
  wheels/                           # 离线构建产物
  packaging.json                    # Wheel 身份、内容/受保护模块比对
  imports-source.json               # 源码新进程导入检查
  imports-wheel.json                # Wheel 新进程导入检查
```

目录名使用 UTC，故日期部分为 10 月 25 日，对应本地 10 月 26 日。打包副本仅用于构建检查，不是新的业务实例或真实联调入口。没有删除旧备份或测试记录。

最终仍为 `main / 5641e4c`：工作树5个删除、12个修改、2个未跟踪文档。其中3个Runtime/测试修改属于上一轮BOT-REGRESSION-1，原字节哈希保持不变；本轮在原文档改动基础上追加清理状态。没有commit/push或其他Git历史操作。`readiness.json` 保存了默认 candidate、真实执行/交付关闭、凭据/业务实例未检查、网络0的预检结果；`final.json` 保存最终哈希/Scope及测试摘要。

## 7. 既有文档链接问题（未扩大修改范围）

全册本地路径扫描发现下列4处指向已不存在的 EVENT_ACK.md：

- `apps/docs/INTEGRATION.md`
- `apps/docs/deep-dive/EVENT_LIFECYCLE.md`
- `apps/docs/deep-dive/EVENT_MANAGEMENT.md`
- `apps/docs/deep-dive/research/EVENT_MANAGEMENT_SIMPLIFICATION.md`

已核对 HEAD 中这些引用就存在、目标文件在 HEAD 中已不存在，且四份文档本轮未改。因此它们不是删除 SDK 草稿引起的新断链；没有借本次清理调整事件文档。链接扫描验证本地目标存在性，不联网检查外链或承诺全部锚点有效。

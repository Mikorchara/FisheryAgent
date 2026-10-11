# P2F · Assistant History v2 产品迁移

状态：正式默认 B 已接入，离线回归通过，等待用户审核。日期：2026-10-11。未执行真实 Provider 请求，未 commit / push。

## Before / After

此前正式 Assistant 使用 CURRENT_NATIVE@1；B 仅用于 qualification。现在正式默认 UNTRUSTED_TRANSCRIPT_V1@1，A 保留为内部兼容与回滚路径。依据是 P2E 的 READY_FOR_FEATURE_FLAGGED_MIGRATION；本轮明确授权默认启用 B，不继续默认 A。

## 接入与冻结语义

`AssistantService.send()` 先调用不变的 `AssistantContextBuilder`，进行 6 turns / 6 KiB 完整 pair 裁剪，再调用 `history_projection.project_retained_history()`。B 不重裁剪。

保留对话编码成单个 role=user JSON transcript，保留 speaker、completed_at、顺序与原文；使用冻结 notice 声明历史可能错误、过时，不证明当前系统状态、本轮 Tool 或项目检索。当前问题保留为独立最后一条 role=user；EMPTY 不插入空 transcript。

共享投影代码从 qualification 提取到产品模块；旧 qualification API、指纹、A/B 定义与实验语义保留。qualification 的 AssistantService 显式选择 A，再由原投影包装器应用 manifest 所选 A/B，避免 B 被套用两次。产品不导入实验模块。

6 KiB 限制仍针对保留历史 pair；transcript 包装字节不另行裁剪。A 使用原构建器原封不动的 ModelRequest。

## 配置与 Session

`create_app` / `run_web` 的内部类型化参数 `assistant_history_projection` 默认 B，在 app 创建时捕获。请求不读取可变 Flask config，不接受浏览器指定 projection，不根据 model/provider 切换。

变更启动配置需重启 app，产生新 epoch；前端原有 epoch 失效、保留 draft、不自动重发语义不变。清空对话、切模型、显示历史、completedTurns 生命周期均沿用原 JS。没有产品 UI 开关，没有失败后用 A 自动重试。

## 不变量

SYSTEM_INSTRUCTION、Tool descriptions、SourceRequirement / Receipt / Commit Gate、Policy / Registry / Executor、Tool round、Analysis、Preset、Adapter、Credential 与前端 app.js 未修改。历史来源声明和 Tool imitation 不产生 Receipt。AUTO 正常 no-tool 仍可成功；内部非 AUTO 未满足仍不能提交成功。

这只是历史表示迁移，不承诺模型必定查询，不从正文推断来源，不增加 Intent Router、Memory、Agent 或额外请求。

## 回滚

先停止 Web，用维护者启动配置启动 A：

```powershell
python -c "from fishery_ai.web import run_web; from fishery_ai.history_projection import ProjectionId; run_web(assistant_history_projection=ProjectionId.CURRENT_NATIVE)"
```

恢复默认 B：正常启动 `python -m fishery_ai web`。不能在同一进行中的 session 中变更或为失败请求自动重试。

## 离线验证

最终结果：

- P2F targeted：35/35 通过（含继承的 Web 兼容回归，9 个新增测试）。
- Assistant / Source / qualification / Analysis targeted：261 项，260 通过、1 跳过；P2D 跨模型 qualification：39/39 通过。
- Full Python：1080 项，1079 通过、1 跳过，314.721 秒；跳过项为当前环境无法创建目录 symlink 的既有测试。
- Full Browser：188/188 通过，包含 clear conversation / model switch / epoch reset / Analysis 独立状态。
- Python compile、app.js 语法、5 个 PowerShell 脚本语法：通过。
- Markdown 本地链接 138 个，断链 0；git diff --check 通过。
- 受控敏感扫描 249 个仓库文本文件：风险 0；无跟踪 outputs / .env / manual.env / writer lock / recovery。未读取真实凭据。

首次相关回归中，旧测试仍期待原生历史角色列表，产生 15 个 subtest 失败；已只更新正式默认 B 的消息形状断言，保留 Tool 选择、执行预算与源合同检查。修正后 targeted 与完整回归均通过。

P2F 专项覆盖默认 B、A parity、B 冻结 parity、EMPTY、多轮、6 turns / 6 KiB 裁剪、JSON escaping、伪造来源不授予 Receipt、Web 覆盖拒绝、启动回滚及 app config 不影响配置。现有 Browser 覆盖 clear conversation / model switch / epoch reset / Analysis 隔离。

## Non-goals

不迁移 Analysis，不调整 Prompt / History 数据结构 / UI，不新增 Tool 或真实 Provider 实验，不修改生产项目，不改凭据或能力合同。

## 工作树

本轮修改产品 Assistant / Web 接入、共享 projection 与 qualification 显式兼容选择，以及必要测试和文档。新增 `history_projection.py`、`test_history_product_migration.py` 和本记录；其余为 9 个 tracked 文件修改。未 commit / push，未改 app.js、Analysis 或生产项目。真实 Provider 请求为 0。

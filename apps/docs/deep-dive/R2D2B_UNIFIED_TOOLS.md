# R2D-2B：固定操作栏与Qwen三工具本地试用

基线`e704e96`，工作树开始时干净。用户本轮明确批准Normal和Streaming三工具local_experimental；没有真实Provider/NPU请求，不改用户数据/凭据/Policy，不commit/push。

## 操作栏根因与修复

旧`.composer-foot`使用flex/space-between，三个直接子项为“回到最新”、Send、Stop。“回到最新”在hidden时display:none退出布局，剩余两个按钮重新分布。浏览器1200px全屏实测Send从x=34.667移到819.531，Stop固定在883.865；窄屏flex-wrap还允许重排。

现在导航和操作分组：左侧minmax(0,1fr)承载“回到最新”，右侧独立64px/64px按钮网格、8px间距。确认、状态和错误仍在独立行，不参与按钮组尺寸。实测同一布局内Send/Stop坐标不随状态改变：

| 布局/状态 | Send x | Stop x |
| --- | ---: | ---: |
| 普通1200px：空闲、勾选、回到最新出现 | 714 | 786 |
| 全屏1200px：Normal、Streaming确认失效、运行中/完成 | 699.333 | 771.333 |
| 全屏390px：回到最新显示/隐藏 | 237.333 | 309.333 |
| 独立页面：空闲与长不可用提示 | 760 | 832 |

不同布局的可用宽度本来不同；要求的是同一布局中状态变化不位移。阅读模式隐藏整个输入区、保留消息，退出后恢复。两次Normal/Streaming Fake成功回答保持；阅读内容height=scrollHeight=4528，无内部截断。390px无横向溢出，输入区底部835.333<844。

## 发布与装配

- `normal_selection.py`复用原Normal候选Scope，另生成Streaming Scope（含Streaming transport与Assembler版本）；`assistant_unified_tools.json`保存两个精确上限、显式八个授权子集（包括无Tool），local_experimental / enabled=false / qualification_id和validated_at为空。没有继承旧真实资格，原candidate JSON保留供资格CLI使用。
- Scope固定Qwen preset/identity、OFF、协议、正式多轮Prompt、History/framing、三份Definition hash、Monitoring/Knowledge绑定、历史统计/来源版本、预算。原Tool/Prompt/统计/执行循环未修改。
- `UnifiedToolTrials`只是启动配置；同一epoch冻结。Service用已有Registry绑定冻结设备，再与用户Policy求交；实际暴露顺序、子集、Policy revision、设备、epoch、transport及预算进入确认revision。客户端不能指定这些字段。关闭工具使旧确认失效；已claim Turn仍用冻结授权。
- 精确Current+Knowledge仍走原两工具resolver，预算与Scope不变；其他授权子集走明确批准的三工具上限，只有Policy选择的Definition进入请求。无新Policy Store、Executor或调度循环；评分兼容名称没有Handler。Ollama和DeepSeek不继承范围。
- 普通聊天移除历史快捷按钮、nextAction和historyQuery状态。模型自主选择工具，前端不按问题路由。旧历史单工具API/资格保留兼容，未增加第二套实现。设置页改为显示Normal/Streaming三工具开关，保存授权不自动开服务器许可。
- Normal统一范围1024 tokens/请求，Streaming512；均2 Calls/2 rounds/3 requests、retry=0、120秒。三个可选Tool不表示可执行三个。第三次调用被拒绝、无第四次模型请求、Ledger只保留已执行项、不提交成功History；若模型两次后Final，AUTO合同可提交但只认证实际两类来源。没有根据自然语言自动设Requirement，回答文字是否准确仍需人工检查。

## 启动与回滚

一行：`.\scripts\dev\run_local.ps1 -Scenario low_oxygen`。原CLI默认仍关；启动器追加`--assistant-tools-trial`，并尊重Normal多轮/Streaming/History开关。启动不请求模型、不解析私有Key、不修改Policy；CredentialSnapshot在明确确认后的执行阶段解析。

在设置中授权三工具，Qwen默认Normal，选择设备、确认联网后直接提问。Streaming需用户主动切换；失败不重试或降级。Ctrl+C停止自己的两个进程；`-NoHistory`重启回到原两工具，`-NoStreaming`仅关Streaming，`-NoStreaming -NoMultiRound -NoHistory`回到Normal单轮。新epoch撤销旧确认。[完整命令](../BUILD_RUN.md#一行式常用命令)。

## 离线验证与人工验收

- 新统一范围9项专项含子案例：Normal三种选择和W→H、Streaming H→Final/W→H→Final（实际HTTP/SSE字节送正式Node parser/Workspace）、授权子集、撤销、超预算/多调用、Stop/Timeout/断流/截断/Trace失败、其他模型/开关/Scope拒绝。全部Fake SDK，隔离SQLite/Policy，无未发布准入stub。
- management：412 Python / 96.133秒、62 Node / 0.939秒，全部通过；FAST165项通过。原两工具Normal/Streaming六路径、独立历史合同、History/Preview/Stop/Source/Commit回归均保留。旧历史快捷操作的5项前端专项由统一范围的3项替代，历史参数/来源/权限的后端合同测试未删。
- 浏览器实测如上，截图/坐标仅保存至Git ignored的`outputs/r2d2b-ui/`。不代表真实模型三工具稳定性或回答质量通过。
- 最少人工问题：Normal分别问当前水质、过去30分钟DO变化、项目低氧知识，再问“先查当前水质，再查过去30分钟DO”；Streaming重复历史和Current→History两问。观察实际Steps、来源、唯一Final；再用Stop。用户从[人工入口](../../../scripts/manual_real_tests/README.md#5-三工具-normal-候选r2d-2a)可独立执行原Normal四个案例，默认Dry-run。现有管理Streaming资格CLI仍只测旧W+K，不能把它当三工具资格；本轮Streaming真实验收使用网页，不新建资格框架。
- 原Normal/Streaming资格及测试发现兼容专项24项通过；Python/JS/PowerShell语法、71个Markdown链接/锚点、敏感模式检查和`git diff --check`通过。受保护的Backend、Prompt、三份Tool定义/Schema、Monitoring、Source/Policy及原发布JSON均无diff。

## 修改文件

共25份：22修改、3新增，无删除。没有新的执行循环、Policy Store或资格Runner。

| 分组 | 文件 |
| --- | --- |
| AI装配/许可 | `ai_service/service.py`、`normal_selection.py`、`resources/assistant_unified_tools.json`（新增）、`business_tools/registry.py`（只修过期注释） |
| Web/界面 | `management_web/__main__.py`、`ai_adapter.py`、`static/assistant.js`、`styles.css`、`tool-policy.js` |
| 启动/发现 | `scripts/dev/local_session.py`、`run_local.ps1`、`run_tests.py` |
| 测试 | 新增`ai_service/tests/test_unified_tools.py`；修改管理端`assistant-ui.test.mjs`、`monitoring-ui.test.mjs`、`test_ai_boundary.py`、`test_local_session.py`、`tool-policy.test.mjs` |
| 文档 | `apps/docs/BUILD_RUN.md`、`README.md`、`ROADMAP.md`、`STRUCTURE.md`、本记录（新增）；根`docs/STRUCTURE.md`、`scripts/manual_real_tests/README.md` |

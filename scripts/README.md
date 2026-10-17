# 维护工具

这些工具不是正常 Web 运行所必需。项目根目录执行，使用已经安装项目的 Python 环境。

**人工真实连接统一从 [manual_real_tests](manual_real_tests/README.md) 查找。** 真实 Qwen / Ollama / DeepSeek / 设备连接由用户在正常PowerShell中亲自执行；Codex执行自动离线测试。常用管理单案例薄入口默认Dry-run，只委托原CLI一次，不搬迁旧入口，不接收Key，不自动批量/重试。回答质量抽样独立安排，不是每次功能开发必经的研究阶段。

- `dev/run_tests.py`：简单离线 unittest 分层入口，默认 FULL PRODUCT；`backend` 单独发现新 Backend / 新业务闭包测试，product 包含该组一次，fast 包含其小集合。不启动 Provider 或批次任务。
- `dev/manual_edge_mock_probe.cjs`：人工页面调试辅助，需用户自行提供本机 Web / Edge CDP；不属于自动 Browser 测试，不自动启动服务。
- `qualification/qualify_assistant_turn.py`：单 manifest 来源资格验证，默认 dry-run；Q1–Q4 保留为有限单次计划示例。
- `qualification/qualify_multi_round.py`：默认 dry-run 的单案例入口；旧实验模式保留。`--assistant-product` 使用正式 AssistantService、多轮 Prompt / History / Commit Gate，只验证 Qwen 精确范围，每次最多 3 请求；可用 `--review-answer` 仅在终端预览成功回答，不保存正文或自动批准。[案例与逐次授权](../docs/deep-dive/research/ASSISTANT_MULTI_ROUND_INTEGRATION.md#10-phase-4c-正式-assistant-资格准备)。
- `qualification/qualify_management_streaming.py`：管理 Qwen 两工具单案例，默认 dry-run；正式管理 Service + 隔离 Monitoring SQLite，固定512/2/2/3/120秒，真实执行须逐案例计划 hash 与明确确认。可选交互终端临时预览，不改 Web 发布状态/开关。[管理资格操作](../apps/docs/deep-dive/STREAMING_QUALIFICATION.md)。
- `qualification/qualify_management_history.py`：管理Qwen Normal历史单工具，默认Dry-run，1024/1/1/2/120秒；本次完整计划hash与确认缺一不可。
- `qualification/qualify_management_history_batch.py`：固定三案例各5次，默认Dry-run；不得在日常测试中自动启动真实批次，已用授权不能重复使用。[历史资格记录](../apps/docs/deep-dive/HISTORY_QUALIFICATION.md)。
- `qualification/qualify_preset_tools.py`：单 Preset 的只读 Tool 往返与概念题维护资格验证，不自动发布。
- `qualification/qualify_local_preset_request.py`：精确 Local 目标的单次请求检查，不扫描模型或自动发布。

真实资格请求必须获得本轮针对目标、计划及次数的明确授权，才使用 `--confirm-network`。旧研究授权不继续有效。正式凭据仍由既有私有 CredentialStore 组合解析，禁止读取源码根 `.env` 或复制 Key。

`qualify_multi_round.py --streaming` 为独立的 Streaming candidate 单案例入口，自动复用正式 Assistant 多轮 Prompt / History / Commit Gate；支持三个固定 Preset，默认查询水质 + Knowledge，`--tool-set three-tools` 另建精确范围。默认 dry-run，最多2/2/3、每请求1–512 tokens（默认256，非流式仍1–256）、retry=0，不预览或保存正文、不自动发布、不开放 Web Streaming。逐案例命令和仍未知的协议边界见[Phase 5C 准备](../docs/deep-dive/research/ASSISTANT_STREAMING_TOOL_CALLING.md#10-推荐最小顺序与手动命令)。

资格实现集中在 `src/fishery_ai/development/qualification/`，脚本是薄入口。该子包复用产品 Runtime、凭据快照、Gateway 与 Tool 合同，正式 Web / Assistant / Analysis 不导入资格实现。包初始化不装配服务、不解析凭据、不联网；实现随安装包提供，以保留安装后 CLI 的可用性。

管理平台资格位于 `apps/ai_service/development/streaming_qualification.py`，Adapter/Observer及安全报告辅助同目录独立维护并调用新apps.ai_backend；不调用Prototype资格执行模块。计划@2绑定新Backend，默认dry-run，旧plan-sha授权无效；不从产品启动路径加载，不复用原型Snapshot，不修改既有报告。

原 `fishery_ai.assistant_qualification` 等七个模块仅为历史导入兼容别名；新开发使用 `fishery_ai.development.qualification` 下的具体模块。别名指向同一个模块对象，历史私有函数导入和测试 monkeypatch 仍有效。冻结 H / P2E fixture 与指纹仅服务单次 Harness 的兼容校验，不参与正式 History。

`python -m fishery_ai validate-real` 仅在该命令分支按需加载开发实现；当前包内 experimental Profile 为空时返回 `INACTIVE_VALIDATION_PROFILE`，不会自动恢复旧连接。单 Local 请求脚本仍直接复用正式传输，不引入另一套资格执行栈。

P2B–P2F 的 H / P2E manifests、冻结顺序 index、generator 和 PowerShell batch / continuation 已移除；历史由 [records](../docs/records/README.md) 与 Git 保存。长期离线资格测试位于 `tests/qualification/`，分层命令见 [测试说明](../tests/README.md)。

# 维护工具

这些工具不是正常 Web 运行所必需。项目根目录执行，使用已经安装项目的 Python 环境。

- `dev/run_tests.py`：简单离线 unittest 分层入口，默认 FULL PRODUCT；不启动 Provider 或批次任务。
- `dev/manual_edge_mock_probe.cjs`：人工页面调试辅助，需用户自行提供本机 Web / Edge CDP；不属于自动 Browser 测试，不自动启动服务。
- `qualification/qualify_assistant_turn.py`：单 manifest 来源资格验证，默认 dry-run；Q1–Q4 保留为有限单次计划示例。
- `qualification/qualify_preset_tools.py`：单 Preset 的只读 Tool 往返与概念题维护资格验证，不自动发布。
- `qualification/qualify_local_preset_request.py`：精确 Local 目标的单次请求检查，不扫描模型或自动发布。

真实资格请求必须获得本轮针对目标、计划及次数的明确授权，才使用 `--confirm-network`。旧研究授权不继续有效。正式凭据仍由既有私有 CredentialStore 组合解析，禁止读取源码根 `.env` 或复制 Key。

资格实现集中在 `src/fishery_ai/development/qualification/`，脚本是薄入口。该子包复用产品 Runtime、凭据快照、Gateway 与 Tool 合同，正式 Web / Assistant / Analysis 不导入资格实现。包初始化不装配服务、不解析凭据、不联网；实现随安装包提供，以保留安装后 CLI 的可用性。

原 `fishery_ai.assistant_qualification` 等七个模块仅为历史导入兼容别名；新开发使用 `fishery_ai.development.qualification` 下的具体模块。别名指向同一个模块对象，历史私有函数导入和测试 monkeypatch 仍有效。冻结 H / P2E fixture 与指纹仅服务单次 Harness 的兼容校验，不参与正式 History。

`python -m fishery_ai validate-real` 仅在该命令分支按需加载开发实现；当前包内 experimental Profile 为空时返回 `INACTIVE_VALIDATION_PROFILE`，不会自动恢复旧连接。单 Local 请求脚本仍直接复用正式传输，不引入另一套资格执行栈。

P2B–P2F 的 H / P2E manifests、冻结顺序 index、generator 和 PowerShell batch / continuation 已移除；历史由 [records](../docs/records/README.md) 与 Git 保存。长期离线资格测试位于 `tests/qualification/`，分层命令见 [测试说明](../tests/README.md)。

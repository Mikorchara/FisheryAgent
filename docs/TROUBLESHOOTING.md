# 故障排查与已知限制

**CURRENT · 2026-10-03**。错误码不是能力结论；不要把网络失败写成 UNSUPPORTED。原 A2/A3 的一次性环境观察已归档，不作为当前通用状态。

| 现象 | 检查 / 安全行为 |
| --- | --- |
| SECRET_MISSING | 正式来源为 process > 私有 PROJECT_ENV > missing；Managed 凭据管理只查看状态并显式设置 Key，不读取源码旧 .env。Ollama Auth NONE 无需 Key；V2 检查独立 manual.env。 |
| CREDENTIAL_FILE_ERROR / ENV_PERMISSION_ERROR | 用户私有路径/owner/DACL/link 安全确认失败。暂停写入，用户仅在本机核对权限；不回显文件内容，不放宽整个 Sandbox 权限。 |
| ENV_REVISION_CONFLICT | 另一个页面/编辑器改变版本，刷新 revision 后再修改；不要自动覆盖。 |
| ENV_RECOVERY_REQUIRED | 暂停，由用户本机检查私有恢复状态；不能把 Secret/recovery 内容贴进日志或文档。 |
| OPTION_UNKNOWN / EVIDENCE_CONFLICT | Managed 只在 exact Identity 证据充分时允许高级选项；Normal + AUTO/UNSET 可用。使用明确单项 Probe，冲突不能靠静默覆盖消除。 |
| OPTION_UNSUPPORTED / OPTION_CONFLICT | 不发送不支持/冲突组合，不静默丢掉用户参数。检查 error_option。 |
| PRESET_MODE_NOT_PUBLISHED / PRESET_OPTION_LOCKED | Preset 固定发布合同不允许所选组合或 Thinking 覆写；选择发布模式，不做 Probe 解锁 Preset。 |
| CONNECT_TIMEOUT / READ_TIMEOUT / TLS_ERROR / PROXY_ERROR / STREAM_INTERRUPTED | 记录安全错误与时间，保留能力证据；不反复真实重试、改代理或无限提高 timeout。Thinking/模型加载慢是性能现象，不是能力失败。 |
| USER_CANCELLED | 后端取消 SDK I/O，不把 partial JSON 当最终结果，不写 Capability，不重试；无法保证远端计算或计费停止。 |
| Usage unavailable | 服务未返回统计，Mock 或某些流式路径也无统计；不是 0。Reasoning trace 与 tokens 是不同输出。 |
| structured_parse_ok=false | 保留 generated_text，不用 LLM 修复；不能把 Raw 文本伪装为可信的事实/规则。 |
| 水质 stale / partial / invalid | 检查 canonical 时间、缺失和数值有效性。默认 Mock 是固定时间样例，不是真实硬件。规则仍可能对剩余有效值输出告警；不是所有 invalid 都硬停止。 |
| 本地服务 / 模型 | 用户自行启动 Runtime 与模型，确认精确 URL/ID；项目不自动下载模型。历史 CLI 成功不代替 API 参数验证。 |
| 旧 validate-real / validate_qwen 入口停用 | 当前旧目标返回 INACTIVE_VALIDATION_PROFILE；不恢复归档 Profile，不改凭据 fallback。 |
| 复现依赖差异 | 使用虚拟环境并记录安装版本，pyproject 的版本范围不是锁定环境。 |

知识来源缺少逐块出处，见[来源说明](../src/fishery_ai/resources/knowledge/SOURCE.md)。RAG 背景不证明疾病，输出仍需任务级评估。

[运行指南](BUILD_RUN.md) / [私有凭据指南](guides/R2_PRIVATE_CREDENTIAL_STORAGE_MIGRATION.md) / [历史验证](history/README.md)

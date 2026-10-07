# 故障排查

| 错误 / 现象 | 处理方式 |
| --- | --- |
| SECRET_MISSING | 检查 Credential Manager 显示的来源和状态。正式源为进程环境或固定用户私有凭据文件；Manual V2 使用独立 manual.env。不要查看或粘贴 Key。Ollama Auth NONE 不需要凭据。 |
| CREDENTIAL_FILE_ERROR / ENV_PERMISSION_ERROR | 私有路径、owner/DACL 或文件对象无法安全确认时系统会拒绝操作。不要放宽整个工作区权限；不要把凭据文件发到日志或对话。 |
| ENV_REVISION_CONFLICT | 另一个标签页或进程已更新版本。刷新状态后重试，不能强制覆盖旧 revision。 |
| ENV_RECOVERY_REQUIRED | 停止写入并在本机处理恢复状态。不要删除待恢复数据或展示文件内容。 |
| OPTION_UNKNOWN / EVIDENCE_CONFLICT | Managed Custom 的高级能力没有充分一致证据。保持 Normal + AUTO，或显式执行单项 Probe。网络失败不是不支持证据。 |
| OPTION_UNSUPPORTED / OPTION_CONFLICT | 所选参数或组合不能安全发送。不要静默删除参数；按 UI 的安全错误说明调整。 |
| PRESET_MODE_NOT_PUBLISHED | 所选组合不在固定 Preset 合同中。Preset 不提供 Probe 解锁。 |
| CONNECT_TIMEOUT / READ_TIMEOUT / TLS_ERROR / PROXY_ERROR | 保留当前能力结论，检查本地网络路径和服务状态。不要自动重试或无限增加 timeout。Thinking 较慢不表示能力不支持。 |
| STREAM_INTERRUPTED / USER_CANCELLED | 检查本地连接结束状态。取消会请求关闭本地 SDK I/O，但不保证远端推理或计费立即停止。 |
| Usage unavailable | Provider 未返回或当前流式路径没有统计；不是 0。 |
| structured_parse_ok=false | 原始模型文本仍保留供调试；程序不会让另一个模型自动修复 JSON。检查 Raw Output，不要把它当成可信事实。 |
| 水质出现 partial / stale / invalid | 检查观测时间、取回时间、缺失字段和 Quality/Freshness。Mock 场景是固定 fixture，不代表现场实时数据。 |

更多操作见[构建与运行](BUILD_RUN.md)、[数据位置](deep-dive/operations/PROJECT_DATA_AND_CONFIG_LOCATIONS.md)和[凭据存储](deep-dive/operations/PRIVATE_CREDENTIAL_STORAGE.md)。

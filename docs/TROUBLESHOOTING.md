# 故障排查与已知限制

| 范围 | 当前状态与初步检查方向 |
| --- | --- |
| 真实 OpenAI-compatible 服务 | 尚未验证任何真实服务。选择 Cloud 或 Local Profile 时，Mock 演示仍使用 `MockGateway`；须在目标工作站单独验证所选接口。 |
| 本地模型部署 | 本项目不会下载或启动模型。真实连接测试前，须确认本地服务、模型 ID 与兼容接口。 |
| 流式响应 | 兼容性取决于服务端的 Chat Completions 流式实现。SDK 适配器与重试边界目前只有离线假客户端覆盖。 |
| 知识来源 | 包内旧版知识 JSON 缺少逐块出版或出处信息，详见[来源说明](../src/fishery_ai/resources/knowledge/SOURCE.md)。 |
| 依赖版本 | `pyproject.toml` 使用版本范围，尚未决定锁文件策略。复现结果时应使用虚拟环境并记录实际安装版本。 |

环境准备与离线命令见[构建与运行](BUILD_RUN.md)。真实服务验证步骤见 [V0.1.1 本地运行时验证计划](deep-dive/V0.1.1_LOCAL_RUNTIME_VALIDATION.md)。

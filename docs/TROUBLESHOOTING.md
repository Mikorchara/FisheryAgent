# 故障排查与已知限制

| 范围 | 当前状态与初步检查方向 |
| --- | --- |
| 真实 OpenAI-compatible 服务 | A2 的 DeepSeek 最小 Chat Completion、AUTO 和 ON 已通过；其他能力与全链路仍未验证。默认 Mock 演示继续使用 `MockGateway`；真实调用仅从显式 `validate-real --confirm-network` 入口启动。 |
| DeepSeek 连接/超时 | A2 的 OFF（两次）与 effort=low（一次）均返回 `CONNECTION_OR_TIMEOUT`，没有 Provider 响应，不能据此判定参数不受支持。已停止重复探测；后续须在网络稳定时单独复核。 |
| 本地模型部署 | 本项目不会下载或启动模型。真实连接测试前，须确认本地服务、模型 ID 与兼容接口。 |
| 流式响应 | 兼容性取决于服务端的 Chat Completions 流式实现。SDK 适配器与重试边界目前只有离线假客户端覆盖。 |
| 知识来源 | 包内旧版知识 JSON 缺少逐块出版或出处信息，详见[来源说明](../src/fishery_ai/resources/knowledge/SOURCE.md)。 |
| 依赖版本 | `pyproject.toml` 使用版本范围，尚未决定锁文件策略。复现结果时应使用虚拟环境并记录实际安装版本。 |
| `OPTION_UNKNOWN` | 对当前精确模型没有足够能力证据。未设置的高级选项可以继续普通请求；显式选项需先确认 Provider 文档与实际测试，再为该 Base URL + Model 声明能力。 |
| `OPTION_UNSUPPORTED` / `OPTION_CONFLICT` | 选项明确不受支持，或组合冲突。检查 `error_option`，修改请求或选择经过验证的 Profile；系统不会静默删除参数。 |
| Usage 显示 `unavailable` | Provider/Mock 未返回 Usage，或验证会话中有请求缺失 Usage。不要把它理解为 0；流式服务还可能不返回最后的统计事件。 |
| VERIFIED 方案列表为空 | 当前仓库没有用户实际验证的 Provider + Base URL + 精确 Model 记录。正式项目的预设名单不能作为成功验证证据。 |

环境准备与离线命令见[构建与运行](BUILD_RUN.md)。真实服务验证步骤见 [V0.1.1 本地运行时验证计划](deep-dive/V0.1.1_LOCAL_RUNTIME_VALIDATION.md)。

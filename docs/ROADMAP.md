# 路线图

## V0.1：已完成的基础版本

- 领域数据合同与确定性 Mock 数据。
- 确定性水质诊断。
- TF-IDF 知识检索基线。
- 不依赖特定运行时的 ModelGateway、Cloud/Local Profile 与 OpenAI SDK 适配器。
- 离线测试与 Mock 演示。

## V0.1.1：下一阶段验证

- 在 GPU 工作站上验证真实本地模型。
- 检查所选 OpenAI-compatible 服务的流式响应与兼容性。
- 记录实际模型标识、延迟、错误处理及服务差异。
- 执行方式与验收标准见 [V0.1.1 本地运行时验证计划](deep-dive/V0.1.1_LOCAL_RUNTIME_VALIDATION.md)。

## V0.2：后续阶段

- 设计只读 Tool Calling、工具 Schema 与工具权限模型。
- 确定性诊断继续由应用程序控制。

## 更远期研究

- Agent、Memory 与数字人集成仍是研究主题；V0.1 均未实现。

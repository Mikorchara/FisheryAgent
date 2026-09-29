# 路线图

## V0.1：已完成的基础版本

- 领域数据合同与确定性 Mock 数据。
- 确定性水质诊断。
- TF-IDF 知识检索基线。
- 不依赖特定运行时的 ModelGateway、Cloud/Local Profile 与 OpenAI SDK 适配器。
- 离线测试与 Mock 演示。

## V0.1.1-A1：多模型合同与能力校验（已实现，真实连接待验证）

- Profile 的 Provider、协议适配器、精确模型和 Cloud/Local 部署标签分离。
- VERIFIED / EXPERIMENTAL / CUSTOM 分类；当前没有真实 VERIFIED 预设，不自动跨 Provider 切换。
- 可选生成与思考参数、精确模型能力、发送前严格校验及适配器内映射。
- Provider Usage、缺失值和内存中的验证会话累计；不计算费用。
- 详见 [A1 实施报告](deep-dive/V0.1.1_A1_MULTI_MODEL_IMPLEMENTATION_REPORT.md)。

## V0.1.1：后续真实运行时验证

- 在 GPU 工作站上验证真实本地模型。
- 检查所选 OpenAI-compatible 服务的流式响应与兼容性。
- 记录实际模型标识、延迟、错误处理及服务差异。
- 执行方式与验收标准见 [V0.1.1 本地运行时验证计划](deep-dive/V0.1.1_LOCAL_RUNTIME_VALIDATION.md)。

## V0.2：后续阶段

- 设计只读 Tool Calling、工具 Schema 与工具权限模型。
- 确定性诊断继续由应用程序控制。

## 更远期研究

- Agent、Memory 与数字人集成仍是研究主题；V0.1 均未实现。
- 为知识块补充**逐块文献出处**（书名/文献/链接/版本），使 RAG 证据可回溯来源；当前测试阶段暂不做。合同已预留字段 `KnowledgeEvidence.source_title`，有出处数据时直接填写，无需改合同。

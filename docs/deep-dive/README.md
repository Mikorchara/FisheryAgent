# 深度分析

此目录保存详细架构分析、技术决策和设计讨论，不是主要使用指南。新开发者请先阅读[构建与运行](../BUILD_RUN.md)及[项目结构](../STRUCTURE.md)。

- [V0.1 实现报告](V0.1_IMPLEMENTATION_REPORT.md)：记录初始实现与当时的测试结果。
- [V0.1 工程加固报告](V0.1_HARDENING_REPORT.md)：记录 SDK、打包和数据合同的改进。
- [V0.1.1 本地运行时验证计划](V0.1.1_LOCAL_RUNTIME_VALIDATION.md)：规定真实 Cloud/Local 接口、全链路、流式、质量与性能的验证方法及验收标准。
- [多模型 API、能力与参数架构评审计划](MULTI_MODEL_PARAMETER_ARCHITECTURE_PLAN.md)：对照正式项目和当时原型，记录设计依据与取舍；部分决策已在 V0.1.1-A1 实施。
- [V0.1.1-A1 多模型合同实施报告](V0.1.1_A1_MULTI_MODEL_IMPLEMENTATION_REPORT.md)：记录 Profile 分类、能力校验、适配器映射、Usage 统计、离线验证与剩余决策。
- [V0.1.1-A2 DeepSeek 真实 Cloud 验证报告](V0.1.1_A2_DEEPSEEK_VALIDATION_REPORT.md)：记录实验 Profile 的少量真实请求、返回模型标识、Usage、连接失败与未验证项。
- [V0.1.1-A2.1 DeepSeek 兼容性加固与网络诊断](V0.1.1_A2_1_DEEPSEEK_COMPATIBILITY_AND_NETWORK_DIAGNOSTICS.md)：记录模型 ID 更新、ON/OFF 能力分离、脱敏网络诊断与受控复测边界。
- [V0.1.1-A2.2 Qwen 网络对照测试](V0.1.1_A2_2_QWEN_NETWORK_CONTROL_TEST.md)：记录同一 SDK/HTTPX/Adapter 路径的最小 Qwen 请求，并与 DeepSeek A2.1 的连接超时对照。
- [V0.1.1-A3.0 开发验证 Web UI](V0.1.1_A3_0_DEVELOPER_WEB_UI.md)：记录本地页面的薄 Web 架构、启动方法、Secret 边界和离线测试。
- [V0.1.1-A3.0.2 Grounding 与自定义 Profile](V0.1.1_A3_0_2_GROUNDING_AND_CUSTOM_PROFILE.md)：记录水质检索排序、事实与背景知识边界、自定义配置持久化和验证结果。

历史报告描述的是编写时的状态。当前环境准备与项目范围请以[文档导航](../README.md)为准。

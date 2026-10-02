# 深度分析

此目录保存详细架构分析、技术决策和设计讨论，不是主要使用指南。新开发者请先阅读[构建与运行](../BUILD_RUN.md)及[项目结构](../STRUCTURE.md)。

- [模型接入三模式设计与产品校正](MODEL_ACCESS_THREE_MODE_PLAN.md)：当前 V1 与长期独立 Manual Experiment 的区别、正式连接边界、转换 NOT DECIDED / V2 DEFERRED；兼容性审计收尾见现有 Preset/R6/R7 实施报告第 10 节。

- [模型选择三模式 UI 整理](MODEL_SELECTION_UI_THREE_MODE_CLEANUP.md)：Preset 按模型收敛、精确 Variant 映射、旧 Built-in 隐藏、Managed Custom CRUD 边界与 Manual 独立页面。

- [Preset、Cancellation 与 Manual Expert 实施](PRESET_CANCELLATION_MANUAL_IMPLEMENTATION.md)：记录固定模板/Variant、真正后端 I/O 取消、独立原始请求边界和受控联网阻塞；R2 保持冻结，R3/R4/R5 未实施。

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
- [V0.1.1-A3.0.3 UTF-8、Profile 体验与 Qwen 复测](V0.1.1_A3_0_3_UTF8_CUSTOM_PROFILE_QWEN_VALIDATION.md)：记录字段级提示、UTF-8 验证记录和唯一一次真实低氧复测。
- [V0.1.1-A3.0.4 Custom Profile Manager](V0.1.1_A3_0_4_CUSTOM_PROFILE_MANAGER.md)：记录 Provider 预设、模型查询、显式连接测试和自定义配置管理。
- [V0.1.1-A3.1 应用级 Streaming 与 Profile 页面整理](V0.1.1_A3_1_APPLICATION_STREAMING.md)：记录流式事件、页面呈现、Secret 边界、离线验证和真实能力限制。
- [V0.1.1-A3.1.1 Streaming 修复与 Profile 冲突保护](V0.1.1_A3_1_1_STREAMING_BUGFIX_PROFILE_COLLISION.md)：记录浏览器根因、Built-in 只读冲突、一次 Qwen 流式验证及测试结果。
- [V0.1.1-A3.1.2 Profile Manager 简化与同步修复](V0.1.1_A3_1_2_PROFILE_MANAGER_SIMPLIFICATION.md)：记录选择同步、名称唯一与不可改名规则，以及旧冲突流程的移除。
- [V0.1.1-A3.1.3 Capability 与 Provider Identity 修正](V0.1.1_A3_1_3_CAPABILITY_IDENTITY.md)：记录 service/model/family 身份拆分、证据来源、精确能力绑定和显式离线测试覆盖的 Probe 流程。
- [V0.1.1-A3.1.4 本地 Profile 与能力界面整理](V0.1.1_A3_1_4_LOCAL_PROFILE_CAPABILITY_UI.md)：记录三层配置、精确能力证据、Ollama 内置方案及离线验证边界。
- [V0.1.1-A3.1.5 Capability UI 与 Thinking 验证](V0.1.1_A3_1_5_CAPABILITY_UI_THINKING_PROBE.md)：记录 Base URL identity 规范化、同区运行选项和 Thinking ON/OFF 显式验证。
- [V0.1.1-A3.1.6 能力界面整理与运行默认值](V0.1.1_A3_1_6_CAPABILITY_UX_RUNTIME_DEFAULTS.md)：记录 Custom Profile 默认偏好、安全回退、Probe 入口整理和定向测试。

- [V0.1.1-A3.2 Cloud Capability、Streaming 与 Thinking](V0.1.1_A3_2_CLOUD_CAPABILITY_STREAMING_THINKING.md)：记录全流程审计、官方参数依据、统一单次 Probe、组合门禁和独立 Reasoning 输出。
- [V0.1.1-A3.2.1 最终输出一致性与 Capability UI](V0.1.1_A3_2_1_OUTPUT_PARITY_AND_CAPABILITY_UI.md)：记录 Normal/Streaming 统一展示、能力证据折叠、四次 Qwen 对照及离线回归。
- [Provider、Credential 与 Capability 重构研究](PROVIDER_CREDENTIAL_CAPABILITY_REFACTOR_RESEARCH.md)：核对原凭据和能力链路，提出渐进迁移方案；R0/R1/R2 已实施，协议分离、Evidence 冲突、取消与 Manual Mode 留待后续阶段。
- [Provider/Credential 重构 R0–R1 实施报告](PROVIDER_CREDENTIAL_REFACTOR_R0_R1.md)：记录兼容请求体基线、静态 ProviderRegistry、只读 CredentialStore、凭据热读取、AuthSpec 与安全验证；范围为 R0/R1，R2 见下一篇。

- [Provider/Credential 重构 R2 实施报告](PROVIDER_CREDENTIAL_REFACTOR_R2.md)：记录已冻结的 Credential Web Manager、Windows ACL、revision/回滚、CSRF、热更新与用户私有存储；之后的 R6/R7 见本页新增阶段报告，R3–R5 未实施。
- [R2 用户私有凭据存储迁移说明](R2_PRIVATE_CREDENTIAL_STORAGE_MIGRATION.md)：固定路径规则、单文件来源、首次设置与人工验收。
- [Post-R2 结构审计（RESOLVED）](POST_R2_STRUCTURAL_AUDIT.md)：记录人工验收收尾、旧验证入口迁移遗漏修复、统一凭据边界与最终离线回归。

- [R3 ProtocolSpec / R4 Evidence Resolver / R5 Unknown Model Probe](PROTOCOL_EVIDENCE_PROBE_R3_R4_R5.md)：当前阶段实施与测试，包含既有 Credential UI 路径、协议编码分离、保守冲突合并、显式未知模型验证与人工验收项。前面的历史报告中“R3–R5 未实施”描述仅适用于其原阶段。

历史报告描述的是编写时的状态。当前环境准备与项目范围请以[文档导航](../README.md)为准。

- [Clean-room Model Validation Reset](CLEAN_ROOM_MODEL_VALIDATION_RESET.md)：当前空模型起点、可恢复归档、协议/凭据边界、首次 Managed 验证步骤和阶段 A checkpoint。

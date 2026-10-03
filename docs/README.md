# 文档导航

**CURRENT · 2026-10-03**。先按任务查当前指南，再按需读研究或历史。当前源码 > 当前文档 > 历史报告；旧文档中的“当前”只指当时阶段。

## 新开发者：如何启动

- [项目介绍](../README.md)：当前范围、三种模式、数据来源。
- [构建与运行](BUILD_RUN.md)：虚拟环境、Mock、Web、测试与界面操作。
- [项目结构](STRUCTURE.md)：模块职责、配置与存储边界。
- [故障排查](TROUBLESHOOTING.md)：安全错误与已知限制。

## 理解架构与凭据

- [当前架构总览](architecture/CURRENT_ARCHITECTURE.md)：Preset / Managed / Manual，R3/R4/R5，Streaming / Stop 和 canonical 数据。
- [用户私有凭据指南](guides/R2_PRIVATE_CREDENTIAL_STORAGE_MIGRATION.md)：正式凭据路径、优先级、CRUD、hot reload 与安全检查。
- [当前 Preset 发布依据](validation/PRESET_SIMPLIFICATION_AND_FIRST_PUBLICATION.md#12-用户人工验收后的精确多模型登记当前状态)：三个 1.0.0 合同与发布组合。

## 业务数据与未来传感器

- [水质 Scenario 与 telemetry 准备](research/WATER_QUALITY_SCENARIO_AND_TELEMETRY_PREPARATION.md)：当前真实 fixture、阈值、矩阵、provisional packet 与只读 Tool 边界。
- [知识快照来源](../src/fishery_ai/resources/knowledge/SOURCE.md)：commit 与 provenance 缺口。
- Grounding 当前约束见[架构总览](architecture/CURRENT_ARCHITECTURE.md#业务分析与-grounding)；具体问题、修复及有限真实复测保留在[历史索引](history/README.md)。

## 深入研究与验证

- [三模式设计研究](research/MODEL_ACCESS_THREE_MODE_PLAN.md)、[参数架构研究](research/MULTI_MODEL_PARAMETER_ARCHITECTURE_PLAN.md)、[Provider/Credential 重构研究](research/PROVIDER_CREDENTIAL_CAPABILITY_REFACTOR_RESEARCH.md)：设计背景，不是操作指南。
- [本地 Runtime 验证参考](validation/V0.1.1_LOCAL_RUNTIME_VALIDATION.md)：环境、延迟与质量记录模板；初稿部分状态已经过时。
- [ACL 设计复审](research/R2_WINDOWS_ACL_CREDENTIAL_WRITER_DESIGN_REVIEW.md)：私有目录决策背景。
- [评审记录模板](guides/CODE_REVIEW.md)：待填写模板，不是评审结果。

## 我要查旧过程或下一阶段

- [历史索引](history/README.md)：实施记录、历史真实验证、已替代方案；不从历史自动继承 Capability。
- [路线图](ROADMAP.md)：telemetry 准备 → 只读 Tool Calling → 工具执行边界 → 只读 Agent → 后续 Memory/生产集成。
- [逐份文档审计与搬迁表](DOCUMENTATION_AUDIT.md)：全部原文档的分类、原位置、新位置与检查结果。

Tool Calling / Agent 本轮仍未实现。没有当前硬件协议或自动模型发布工具。

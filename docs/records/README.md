# 阶段记录与历史归档

records 保存已结束阶段的记录、验收、事故与独立审计。CURRENT STATE 以当前源码、测试，以及正式 [Analysis / Assistant 架构](../deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md)和[只读 Tool 文档](../deep-dive/tools/READ_ONLY_TOOL_CALLING.md)为准；本目录不是运行时真相来源。

before/after、AI 实施日志和旧交接稿是历史证据，其中的“当前”“未实现”、行号及测试数量只适用于当时基线，不代表现在的系统状态。

## 可直接阅读的记录

- [P2E History Projection 产品迁移资格准备](2026-10-history-projection-product-migration-qualification.md)：多轮/混合来源/仿调用/裁剪，30个固定A/B run，最多60请求；真实Provider未执行。
- [Ollama History Projection 真实结果](2026-10-ollama-history-projection-results.md)：30 runs / 44请求，25 completed；H2-A查询2/6、B查询5/6，H5-B有一次额外查询。
- [DeepSeek History Projection 真实结果](2026-10-deepseek-history-projection-results.md)：新批次30 runs / 48请求全部完成；H2 Fresh/A/B均查询，H5 A/B均直接回答。
- [Cross-Model History Projection P2D 准备](2026-10-cross-model-history-projection-preparation.md)：DeepSeek/Ollama 独立计划、固定顺序和Runner停止记录；两个真实批次均已执行完毕。
- [Assistant History Projection A/B P2C](2026-10-assistant-history-projection-ab.md)：模型无关的 qualification-only A/B、Fresh严格对照与冻结产品边界。
- [Assistant History Projection P2B](2026-10-assistant-history-projection-research.md)：固定 synthetic History 实验、42个真实样本对照、公开项目调研与候选方案；零请求预检单独排除。
- [Controlled Assistant Qualification P2A-1](2026-10-controlled-assistant-qualification-p2a.md)：单次 manifest、默认 dry-run、有限真实请求入口和安全取证；实现阶段未联网。
- [Assistant Turn Source Contract / Receipt P1 / P1.1](2026-10-assistant-turn-source-contract-p1.md)：操作完成与来源存在性分离、状态矩阵与受控资格验证接口设计；没有新增真实模型请求。
- [Assistant History / Tool Reliability 研究](2026-10-assistant-history-tool-reliability-study.md)：Session / History 审计、来源边界与后续路线评估。
- [2026-10 Knowledge Tool v1 阶段总结](2026-10-knowledge-tool-v1-summary.md)：已落地范围、边界与未验收问题。
- [2026-10 Codex 接管审计](2026-10-codex-takeover-audit.md)：保留独立审计原文；其中的旧目录与文档冲突是审计发生时的历史事实。
- [2026-10 Qwen 首轮取证阻塞](2026-10-qwen-tool-provider-evidence.md)：正式凭据预检失败，真实请求为 0，未得到 Provider 能力结论。

## 压缩归档

| 归档 | 内容 | 定位 |
|---|---|---|
| [copilot-tool3-records-2026-10.zip](archive/copilot-tool3-records-2026-10.zip) | 13 份 Markdown，保留 docs/copilot/ 路径 | Step 2–10、D1/D1b 的施工证据 |
| [pre-codex-handoff-2026-10.zip](archive/pre-codex-handoff-2026-10.zip) | 3 份 Markdown，保留 docs/handoff/ 路径 | 旧交接与学习材料，不含已迁出的两份 Codex 记录 |

归档只含文档，不包含源码、outputs、.env、凭据文件或 Secret。制作时逐项核对内容与原文件 SHA-256，并通过 ZIP 完整性检查；原目录内容随后删除。正式 CURRENT STATE 文档不依赖 ZIP 内文件。解压后，历史相对链接可能需要同时解压另一个归档或检出对应 Git 基线，不能把它当作自包含的当前文档站点。

### 归档文件清单

`copilot-tool3-records-2026-10.zip`：

- D1_MOCK_TOOL_GATEWAY_BEFORE_AFTER.md
- D1B_MOCK_DIRECTIONAL_FALLBACK_BEFORE_AFTER.md
- KNOWLEDGE_TOOL_STEP_BY_STEP.md
- STEP2_TOOL_ARGUMENT_CONTRACT_BEFORE_AFTER.md
- STEP3_TOOL_STATUS_NO_MATCH_BEFORE_AFTER.md
- STEP4_KNOWLEDGE_HANDLER_DESIGN.md
- STEP4_KNOWLEDGE_HANDLER_BEFORE_AFTER.md
- STEP5_KNOWLEDGE_REGISTRATION_BEFORE_AFTER.md
- STEP6_CATALOG_BEFORE_AFTER.md
- STEP7_POLICY_DEFAULTS_BEFORE_AFTER.md
- STEP8_KNOWLEDGE_ASSEMBLY_BEFORE_AFTER.md
- STEP9_ASSISTANT_SELECTION_RULES_BEFORE_AFTER.md
- STEP10_UI_ACCURACY_BEFORE_AFTER.md

`pre-codex-handoff-2026-10.zip`：

- README.md
- TOOL_CHANGE_MAP.md
- KNOWLEDGE_TOOL_V1_WALKTHROUGH.md

- [History v2 产品迁移（P2F）](2026-10-history-v2-product-migration.md)：正式默认 B、内部 A 回滚与离线验证。

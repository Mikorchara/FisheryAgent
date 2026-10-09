# 阶段记录与历史归档

records 保存已结束阶段的记录、验收、事故与独立审计。CURRENT STATE 以当前源码、测试，以及正式 [Analysis / Assistant 架构](../deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md)和[只读 Tool 文档](../deep-dive/tools/READ_ONLY_TOOL_CALLING.md)为准；本目录不是运行时真相来源。

before/after、AI 实施日志和旧交接稿是历史证据，其中的“当前”“未实现”、行号及测试数量只适用于当时基线，不代表现在的系统状态。

## 可直接阅读的记录

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

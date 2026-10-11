# 阶段记录与历史归档

records 保存已结束阶段的记录、验收、事故与独立审计。CURRENT STATE 以当前源码、测试，以及正式 [Analysis / Assistant 架构](../deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md)和[只读 Tool 文档](../deep-dive/tools/READ_ONLY_TOOL_CALLING.md)为准；本目录不是运行时真相来源。

before/after、AI 实施日志和旧交接稿是历史证据，其中的“当前”“未实现”、行号及测试数量只适用于当时基线，不代表现在的系统状态。

## 当前维护依据

- [History v2 迁移决策（P2E）](2026-10-history-v2-migration-decision.md)：30 个真实 run / 50 次请求，有限筛选支持可回滚迁移，不证明长期可靠性。
- [History v2 产品迁移（P2F）](2026-10-history-v2-product-migration.md)：正式默认 B、内部 A 回滚、会话不变量与离线验证记录；当前操作见 [BUILD_RUN](../BUILD_RUN.md#assistant-history-v2)。
- [Repository Cleanup 只读审计](2026-10-repository-cleanup-audit.md)：保留尚未提交的独立盘点与候选建议；文件数量、旧路径和分类是审计时快照，不是当前目录清单或实施授权。

## 已结束研究：History v2

以下九份原始记录已归档到 `archive/history-v2-research/`。P2D/P2E 的真实批次与产品迁移均已完成；准备文档中的 NOT RUN、qualification-only 与“下一阶段”仅表示当时状态。旧授权不可用于重跑。

- [P1 / P1.1 来源合同](archive/history-v2-research/2026-10-assistant-turn-source-contract-p1.md)：操作与正向来源的语义决策、测试矩阵。
- [P2A 受控资格入口](archive/history-v2-research/2026-10-controlled-assistant-qualification-p2a.md)：单 manifest、预算与安全取证。
- [History / Tool 可靠性研究](archive/history-v2-research/2026-10-assistant-history-tool-reliability-study.md)：最初的问题与研究范围。
- [P2B 历史研究](archive/history-v2-research/2026-10-assistant-history-projection-research.md)：42 个真实样本及候选投影。
- [P2C 投影 A/B](archive/history-v2-research/2026-10-assistant-history-projection-ab.md)：Qwen 对照与冻结实验边界。
- [P2D 跨模型准备及停止审计](archive/history-v2-research/2026-10-cross-model-history-projection-preparation.md)：固定顺序、runner 事故与授权边界。
- [DeepSeek 真实结果](archive/history-v2-research/2026-10-deepseek-history-projection-results.md)：30 run / 48 请求，全部 completed。
- [Ollama 真实结果](archive/history-v2-research/2026-10-ollama-history-projection-results.md)：30 run / 44 请求，25 completed；B 仍有漏查和一次额外查询。
- [P2E 准备及执行合同](archive/history-v2-research/2026-10-history-projection-product-migration-qualification.md)：多轮、仿调用和长历史的冻结计划；最终结果以根目录迁移决策为准。

## 已结束接入：Knowledge Tool v1

以下四份文档位于 `archive/knowledge-tool-v1/`，保留原始设计、独立审计及预检失败证据，不覆盖后来的真实资格结果：

- [接入前设计](archive/knowledge-tool-v1/KNOWLEDGE_TOOL_DESIGN.md)：历史 PAUSED baseline，接口提案不是当前合同。
- [阶段总结](archive/knowledge-tool-v1/2026-10-knowledge-tool-v1-summary.md)：Tool 3 接入范围与当时待验收项。
- [Codex 接管审计](archive/knowledge-tool-v1/2026-10-codex-takeover-audit.md)：完整独立审计，旧目录描述保留为历史事实。
- [Qwen 首轮取证预检阻塞](archive/knowledge-tool-v1/2026-10-qwen-tool-provider-evidence.md)：该次请求为 0，不构成 Provider 能力结论。

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

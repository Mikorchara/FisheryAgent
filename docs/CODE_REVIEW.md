# 代码评审记录(仅供参考,可能不准确,非强求修改)

## 日期：

2026-09-28

## 评审人：

GitHub Copilot（静态只读审查：只读源码、测试、资源与文档，未运行测试，未发起任何真实模型或网络调用）

## 范围：

`src/fishery_ai/` 全部模块（约 900 行）、`tests/test_v01.py`、`scripts/`、`src/fishery_ai/resources/`、`docs/`；并与生产项目 `D:\Fishery_Project` 的 `core/llm_advisor.py`、`core/llm_settings.py`、`knowledge/knowledge_base.py` 做逐项能力对照。

## 发现：

以下按「架构与能力」「兼容性与参数」「卫生与文档」分组，均未修改，仅登记。

### A. 架构与能力缺口

1. **应用层无流式输出。** `Orchestrator.analyze()` 只调用 `gateway.complete()`；适配器的 `stream()` 已实现且有假客户端测试，但没有面向用户的流式编排。生产项目已有 SSE 打字机（`app.py` 的 `/chat_ai_stream`、`/get_ai_advice_stream`）。接入前需先定义「用户取消 / 部分结果 / Trace 语义」。（`src/fishery_ai/application.py`）
2. **Detection 只有合同、未进流水线。** `ObservedFacts.detection_summary` 恒为 `None`；`scenarios.json` 的 `detection` 数据（含 `count_jump`）未被编排使用。YOLO 结果目前不进 AI 链路。（`application.py`、`repositories.py`、`resources/mock/scenarios.json`）
3. **输入政策未定。** `invalid` / `stale` 场景仍继续调用模型生成（只附加不确定性提示），尚未决定是否「直接停止生成并要求复测」。（`application.py`）
4. **规则语义相对生产收敛。** `DiagnosisService` 每个指标只输出最严重的一条；生产 `get_alarms()` 可叠加多条。这是有意收敛（实现报告已注明），但迁移时需明确取舍。（`src/fishery_ai/domain.py`）
5. **生产已有能力未覆盖**：模型列表拉取（`/llm_models`）、连通性测试（`/llm_test`）、AI 交互落盘 Markdown（`outputs/chats/*.md`）、多方案管理界面。

### B. 兼容性与参数

6. **采样与「思考」参数通道缺失。** `ModelRequest` 只有 `mode/messages/max_tokens`；适配器 `_kwargs()` 只发送 `model/messages/max_tokens/stream`。因此**无法复刻**生产的 `temperature=0.7`、`top_p=0.95`，也**无法**下发 `extra_body` 关闭思考（生产的 `_extra_no_thinking()` 对 DeepSeek-V4 / Qwen3 生效）。对思考型模型，这会直接放大 token 消耗与延迟。（`src/fishery_ai/model_gateway.py`、`src/fishery_ai/openai_compatible_adapter.py`）
7. **真实服务零验证。** 从未对任何真实 Cloud/Local 服务发起请求；`profiles.json` 中 `local-demo` 的模型名仍是占位符 `replace-with-installed-model`。V0.1.1 验证计划已写、未执行。
8. **`total_timeout_s` 不是硬截止。** 它是应用侧按请求/按事件检查的预算；单次 SDK 调用仍受 HTTPX 分项超时约束，不能保证精确的硬实时上限。（`openai_compatible_adapter.py`）
9. **依赖未锁版本。** `pyproject.toml` 使用范围声明（`openai>=1.0,<3.0`、`httpx>=0.27,<1.0`），复现性依赖虚拟环境记录，未决定锁文件策略。

### C. 检索与知识

10. **检索等价性未证。** 默认纯 Python `_PortableTfidf` 重现了 sklearn 的核心设定，但边缘分词、特征排序与分数可能不同；且**没有人工标注的检索评测集**。（`src/fishery_ai/knowledge.py`）
11. **关键词加分过宽（继承生产逻辑）。** 只要查询中**任意 2-gram** 出现在某块关键词里就 +0.3，存在误召回风险；关键词回退分支的 `text[:80].split()` 对中文几乎不生效。此为原样移植生产实现的遗留债务。（`knowledge.py` `search()` / `_keyword_scores()`）
12. **知识缺逐块文献出处。** 源 JSON 只有整体 `version`，因此来源标识为 `legacy:eel_knowledge.json`、`source_title` 留空。知识含用药与养殖具体文字，**不能当作医学或养殖权威结论**。已按建议登记到 `docs/ROADMAP.md` 的「更远期研究」。（`resources/knowledge/SOURCE.md`）

### D. 卫生与文档

13. **未使用的导入。** `contracts.py` 第 5 行 `from dataclasses import dataclass, field` 中的 `field` 未被使用。
14. **空目录残留。** `data/knowledge/`、`data/mock/` 在资源迁入包内后为空目录（git 不跟踪，仅本地存在），可删。
15. **文档陈旧点。** `docs/deep-dive/V0.1_IMPLEMENTATION_REPORT.md` 仍写「Prototype 目录目前不是 Git 仓库」，实际已有 `.git`、tag `v0.1` 与提交历史；同类“历史报告描述写作时状态”的表述还有数处。`docs/CODE_REVIEW.md` 原为空模板（本次已填写）。

## 修改：

本轮为**只读审查，未修改任何源码或测试**。仅文档层面变更：

- 重写 `docs/STRUCTURE.md`：目录树逐条标注作用，新增「模块关键符号速查」「数据流」「尚未存在的模块」。
- 在 `docs/ROADMAP.md` 的「更远期研究」登记「知识块逐块文献出处」待办（并从 `CODE_REVIEW` 交叉引用）。
- 填写本文件。

## 后续事项：

1. **先拍板重构目标**：是「原型吸收生产行为（流式 / 采样参数 / 多方案管理）并最终替换 `core/llm_advisor.py`」，还是「原型保持 runtime-neutral，仅作架构参考」。这决定 A、B 两组缺口中哪些是必修。
2. 若走「吸收并替换」路线，优先级建议：先补 B6 参数通道（否则无法等价复刻生产行为）→ 再接 A1 应用层流式 → 再补 A5 的模型列表/连通测试。
3. 执行 V0.1.1 真实运行时验证（需用户明确授权，且限制 `max_tokens` 与调用次数）。
4. 建立人工标注的检索评测集，再决定是否调整检索策略（C10、C11）。
5. 清理 D13–D15 三项（成本极低）。

> 本记录为静态审查结论；测试是否通过、真实服务是否可用，均未在本轮验证。

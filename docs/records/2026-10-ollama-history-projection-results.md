# P2D Ollama History Projection：真实批次结果

日期：2026-10-11。用户在正常PowerShell执行固定批次；本次只读取安全JSON统计，不补样本、不修改运行逻辑。

## 1. 样本与条件

数据来自 `outputs/assistant-qualification/cross-model/ollama/`：30份真实报告，run_id唯一，每case六份，无0-request报告；执行顺序与run-order一致，实验plan字段及hash与固定manifest一致。

精确Identity：`ollama + generic_openai_chat + http://127.0.0.1:11434/v1 + qwen3.5:4b`。Thinking OFF / Normal，retry=0，每请求输出上限256 tokens；最多1 Tool Call、1 Tool round、2次模型请求。A为CURRENT_NATIVE，B为UNTRUSTED_TRANSCRIPT_V1；H2使用旧NO_DATA历史，H5使用旧DO=2.2历史，H2F无历史。

## 2. 结果

| Case | 样本 | 查询Tool | 无Tool直接回答 | Requirement满足 | 最终completed | 请求数 |
|---|---:|---:|---:|---:|---:|---:|
| H2F：无历史当前观测 | 6 | 6/6 | 0/6 | 6/6 | 6/6 | 12 |
| H2-A：旧NO_DATA，A | 6 | 2/6 | 4/6 | 2/6 | 2/6 | 8 |
| H2-B：旧NO_DATA，B | 6 | 5/6 | 1/6 | 5/6 | 5/6 | 11 |
| H5-A：旧数值解释，A | 6 | 0/6 | 6/6 | 6/6 | 6/6 | 6 |
| H5-B：旧数值解释，B | 6 | 1/6 | 5/6 | 6/6 | 6/6 | 7 |

批次30项均执行完毕，资格结果为 **25 completed / 5 failed**。实际 **44次模型请求 / 44次transport attempts**。没有Provider model mismatch、raw/normalized不一致或最终截断，所有最终finish_reason均为stop。

## 3. 五次失败与H5额外调用

- 固定顺序第4、9、17、25项：H2-A。
- 第16项：H2-B。
- 五次失败全部是首轮直接回答，protocol tool_calls为空，未执行Tool，因此receipt未认证当前查询，返回 `ASSISTANT_SOURCE_REQUIREMENT_UNMET`。没有错Tool、非法参数、执行失败或网络错误；模型成功返回正文不等于来源Requirement满足。
- 第15项H5-B额外调用了一次合法 `get_current_water_quality({})`，得到NO_DATA，再由第二轮完成回答。AUTO允许该流程，所以资格completed；但对历史解释问题，这是一次不必要的当前查询信号。

14次Tool调用全部为合法查询Tool，均返回NO_DATA，认证 `observation_query_completed=true`、`has_observation=false`：查过当前状态，但没有取得新观测数值。

## 4. Usage

44次请求均有Usage统计：Input **53,380** / Output **1,458** / Total **54,838** tokens。

## 5. 结论

1. Fresh为6/6，旧NO_DATA的A为2/6：本轮样本支持历史内容可能降低Ollama的当前事实重新查询可靠性。
2. 同期B为5/6，高于A的2/6，观察比例提高50个百分点；B仍有一次未查询，不能保证可靠执行，也不能证明role变化是唯一原因。
3. H5-A保持6/6直接解释，H5-B为5/6直接解释、1/6额外查询，提示B可能存在过度查询代价，后续评估不能只看H2改善。
4. 与[DeepSeek本轮结果](2026-10-deepseek-history-projection-results.md)相比，DeepSeek H2-A/B均6/6、H5-A/B均无Tool；不同模型对同一History表示的反应不同，不应推广为所有模型共同故障。
5. 每条件只有六个受控样本，未做统计显著性检验，不代表长期成功率。本次未读取模型正文，不能评价解释质量，也不据此修改模型Capability或Preset合同。

建议将此批次作为跨模型研究结果，保留当前Receipt / Requirement / Commit Gate硬门禁。正式History或Prompt是否迁移需另行审阅；现在不补跑、不自动修改产品。

实验条件和执行边界见[P2D阶段记录](2026-10-cross-model-history-projection-preparation.md)。

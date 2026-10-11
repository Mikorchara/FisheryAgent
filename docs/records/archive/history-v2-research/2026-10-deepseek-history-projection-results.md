# P2D DeepSeek History Projection：真实批次结果

日期：2026-10-11。用户在正常 PowerShell 完成本轮真实批次；Codex只读取安全报告进行统计，没有新增模型请求或修改产品代码。

## 1. 样本与实验条件

- 数据来自 `outputs/assistant-qualification/cross-model/deepseek/`：30份真实报告，run_id无重复，每case恰好6份，时间顺序与固定run-order一致。
- 旧停止批次的5个run / 10次请求已独立归档，不计入本轮分母。
- 精确Identity：`deepseek_api + openai_chat + https://api.deepseek.com + deepseek-flash`；Preset `deepseek-flash-r1@1.0.2`，ProtocolSpec `deepseek_chat@1`。
- Thinking OFF / Normal；retry=0；每请求输出上限256 tokens；最多1 Tool Call、1 Tool round、2次模型请求。每份报告plan的实验字段及预登记hash均与当前固定manifest一致；唯一差别是network从dry-run的NOT_YET_AUTHORIZED变为真实执行的AUTHORIZED_FOR_THIS_RUN，符合确认机制。
- A：`CURRENT_NATIVE`；B：`UNTRUSTED_TRANSCRIPT_V1`。H2-A/B使用OLD_NO_DATA历史，H5-A/B使用OLD_DO_2_2历史；H2F无历史。首轮开放现有三个Tool，未改变Prompt或Schema。

## 2. 结果

| Case | 样本 | 合法查询Tool | 无Tool直接回答 | 查询完成 | Requirement满足 | 最终completed | 模型请求 |
|---|---:|---:|---:|---:|---:|---:|---:|
| H2F：无历史当前观测 | 6 | 6/6 | 0/6 | 6/6 | 6/6 | 6/6 | 12 |
| H2-A：旧NO_DATA，A | 6 | 6/6 | 0/6 | 6/6 | 6/6 | 6/6 | 12 |
| H2-B：旧NO_DATA，B | 6 | 6/6 | 0/6 | 6/6 | 6/6 | 6/6 | 12 |
| H5-A：旧数值解释，A | 6 | 0/6 | 6/6 | 0/6 | 6/6 | 6/6 | 6 |
| H5-B：旧数值解释，B | 6 | 0/6 | 6/6 | 0/6 | 6/6 | 6/6 | 6 |

18次Tool调用全部选择 `get_current_water_quality`，参数合法；未出现错Tool、Provider model mismatch、raw/normalized不一致、安全错误或最终截断。所有最终finish_reason均为stop。

Tool全部返回NO_DATA：receipt认证本轮确实查询完成，`has_observation=false`。这证明没有直接沿用旧NO_DATA回答，不能证明取得了新的传感器数值。H5的Requirement为AUTO，不要求查询；无Tool直接解释历史数值是预期行为。

## 3. 请求与Usage

- 本轮30 runs，实际48次Provider请求，48次transport attempts；没有额外补样本。
- 48次请求均有Provider Usage统计：Input **50,972** / Output **2,231** / Total **53,203** tokens。
- 各case Total tokens：H2F 11,676；H2-A 12,481；H2-B 13,006；H5-A 7,951；H5-B 8,089。

## 4. 结论与边界

1. 本轮DeepSeek受控样本中，旧NO_DATA没有抑制重新查询：Fresh、A、B均6/6完成当前查询。
2. A/B在查询完成率上没有观察到差异，不能据此声称B改善DeepSeek，也不能把其他模型的History故障推广到DeepSeek。
3. 两种投影均保留历史解释的合法无Tool路径，H5没有出现过度查询。
4. 这是每条件6次的受控样本，不是长期稳定性证明；安全报告只能评价协议、执行和来源合同，不能评价最终正文的语言质量或检索相关性。本轮也未验证Knowledge选择。

本轮可作为DeepSeek跨模型对照结果。保持正式History、Prompt、Capability与Preset不变；若继续Ollama研究，需要用户独立授权，不自动启动下一批次。

实验准备、两次Runner停止及旧样本归档见[P2D阶段记录](2026-10-cross-model-history-projection-preparation.md)。

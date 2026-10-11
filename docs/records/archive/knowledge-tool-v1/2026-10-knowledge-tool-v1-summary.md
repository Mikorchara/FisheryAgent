# Knowledge Tool v1 阶段总结

记录日期：2026-10-09；实现核对基线：44992a0。本文保存 Tool 3 接入阶段结论，不替代当前源码、测试与[正式 Tool 文档](../../../deep-dive/tools/READ_ONLY_TOOL_CALLING.md)。

## 1. 最终结构

```text
search_fishery_knowledge({"query": "..."})
  → ToolRegistry / ToolPolicy
  → ToolExecutor：参数对象、大小、validator、权限、预算与取消校验
  → tools/handlers/knowledge_search.py
  → 共享 KnowledgeService.search(query, top_k=3)
  → 有限背景 Evidence
  → 第二轮模型解释
```

query 是唯一必填字符串；strip 后非空、最多 512 字符，拒绝归一化后仍存在的控制字符和 lone surrogate；Schema 为 required=[query]、additionalProperties=false。Executor 另限制 arguments 为 JSON object、最多 4096 UTF-8 bytes。

结果包含 status、retrieval_mode、result_count、evidence。每条 Evidence 只有 id、category、source、source_version、text；不发送 score、retrieved_at 或 source_title。text 正文最多 800 字符，截断时另附省略号。统一 Tool Result 上限为 32768 bytes。

NO_MATCH 是合法查询无合格命中，仍交给第二轮解释；服务错误由 Executor 转成安全 ERROR，不伪装成 NO_MATCH。source_version 是知识资源版本，不是检索算法版本；当前没有 retrieval_version。

## 2. 已落地范围

| 项目 | 结果 |
|---|---|
| Argument contract | ToolDefinition 的可选 validator 与 bind(arguments)；旧无参 Tool 仍只接受 {} |
| Validator / Handler | query 服务端验证；薄 Handler 复用 KnowledgeService，不新建索引或检索器 |
| NO_MATCH | 合同、协调器与安全显示区分无命中和执行失败 |
| Registry | 三个静态 Tool；Knowledge 依赖注入后才对该实例暴露并执行 |
| Catalog | 知识检索名称、说明、参数摘要及注册 / 可执行状态 |
| Policy opt-in | Knowledge 默认关闭；Analysis 默认无 Tool，Assistant 默认只开放水质查询；既有用户 override 不自动迁移 |
| Runtime assembly | Web 共享同一个 KnowledgeService，先绑定 Registry，再校验用户 Policy |
| D1 / D1b | Mock 按查询 / 评分类型渲染；评分可降级查询，查询不可反向降级；绝不借用 Knowledge 作位置兜底 |
| Assistant selection prompt | 区分当前事实、当前评分、项目背景、一般概念、用户提供值与历史解释 |
| UI activity accuracy | 标签取 Catalog；不再把 Knowledge 标为水质读取或 unavailable；参数只显示安全摘要，query 原文不进入 Activity / Trace |

Catalog 不注册 Handler 或验证参数；但当前 UserToolPolicyStore 的 override 校验仍依赖 Catalog 的 executable 集合。该原有耦合是后续整理项，不能把“纯展示”作为已实现保证。

## 3. 当前未完成 / 未验收

- 真实 LLM 多 Tool 选择稳定性：Qwen 有未调用 Tool 却宣称查询 / 评分 / 检索的人工记录，Knowledge 集成未通过真实验收。
- History 干扰：旧值可能影响本轮选择，尚无受控 fresh / repeated 对照。
- 无 Tool 的来源声明：服务可将这类模型正文提交为成功回答，离线反例已复现；Prompt 不能构成确定性保证。
- Knowledge retrieval relevance：固定“鳗鲡低氧表现”查询命中生命周期资料，相关性需独立核对；本阶段未改 RAG。
- Analysis + Knowledge 双重来源：固定自动 RAG 与可选 Knowledge Tool 的关系另行评审，不混入选择问题。
- 首轮 Provider 取证：后续四项实验因正式 CredentialStore 返回 CREDENTIAL_FILE_ERROR 未启动，真实请求为 0，不构成模型不支持的证据。

详见[独立接管审计](2026-10-codex-takeover-audit.md)与[取证阻塞记录](2026-10-qwen-tool-provider-evidence.md)。施工日志的历史测试数量、mutation 声明不当作本次独立全量回归结果。

## 4. 必须保持的边界

- 1 Tool Call / 1 round / 最多 2 model requests；Tool Calling 不等于 Agent。
- 全部 Tool READ ONLY，静态 Registry allowlist；不提供 Shell、任意文件访问、设备 / DB / 阈值写入。
- Analysis 自动 RAG 保留；Assistant 不预注入知识或当前事实，按授权由模型选择 Knowledge Tool。
- Knowledge Evidence 是背景资料，不是当前现场事实，不证明疾病存在或治疗指征。
- Tool Result 是数据，不提升为 System instruction；实时水质只能由本轮相应 Tool 查询获得，新查询不等于新采样。
- 协议支持、Runtime Capability、用户授权、模型实际选择是不同层次；未调用 Tool 不等于 UNSUPPORTED。

## 5. 施工记录归档

Copilot Step 2–10 与 D1/D1b 的逐步施工记录已收口归档，旧 handoff 学习材料同样归档；入口见 [records README](../../README.md)。这些文件不再作为 CURRENT STATE 文档。后续修复以源码、测试和正式 architecture / tools 文档为准，不从 ZIP 内文件推导运行行为。

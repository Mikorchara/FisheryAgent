# Knowledge Tool 研究（暂停）

**状态：PAUSED。** 当前没有 Knowledge Tool Handler、Registry entry 或 Policy 授权。本文记录以后重新评审时仍有用的设计决定，不构成当前功能或实现承诺。

## 当前 Knowledge / RAG 基线

- `src/fishery_ai/knowledge.py::KnowledgeService` 从包内 `resources/knowledge/eel_knowledge.json` 构造 31 个当前知识 chunk。数据版本为 1.0；来源与逐条 provenance 缺口见同目录 `SOURCE.md`。来源标记为 `legacy:eel_knowledge.json`，没有依据时不编造作者、标题或逐条文献。
- 默认 portable TF-IDF 形状为 `char_wb` 2–4 gram、最多 2000 特征；查询包含有限扩展与 keyword bonus。按用户原始意图调整 water_quality / relationships / disease 类别，TF-IDF 分数低于 0.04 的条目过滤。Analysis Chat / Advice 使用不同 top-k。
- 显式 keyword backend 及 sklearn 不可用 fallback 的分数尺度不同，且 keyword 路径没有同一 0.04 阈值；分数是排序信号，不是置信概率。损坏或不匹配的 JSON 不应被伪装成无命中。
- 当前只有固定 Analysis 自动使用 RAG。Assistant 不预注入 Knowledge Evidence。

## 未来候选边界

若未来需要 Assistant 按需查询项目资料，可评估只读 `search_fishery_knowledge(query)`。复用同一个 `KnowledgeService`，不搬走 Analysis RAG、不新建 Retriever、索引或知识副本。查询只是有限文本，不能作为文件名、路径、URL、模块名、SQL、Shell 或 Python 表达式。

建议参数合同：必填 `query: string`；trim 后非空，最多 512 个 Unicode 字符并另设 UTF-8 字节上限；只接受一个键，`additionalProperties=false`。v1 不接受 `top_k`、backend、threshold、文件路径或任意过滤条件。具体字符、控制码及 Unicode 策略须在重新立项时按当前 Executor 合同确认。

建议 Result 只映射受限字段：

```json
{
  "status": "OK",
  "retrieval_mode": "tfidf",
  "retrieval_version": "tfidf-charwb-2-4/eel-knowledge-1.0",
  "result_count": 1,
  "evidence": [{
    "id": "stable-chunk-id",
    "category": "water_quality",
    "source": "legacy:eel_knowledge.json",
    "source_version": "1.0",
    "text": "bounded evidence text"
  }]
}
```

`id` 应来自现有 `KnowledgeEvidence.evidence_id`；不伪造 source title。普通模型请求不需要 raw score；若 Developer 视图展示 score，应明确它不是概率且 backend 间不可直接比较。结果条数、每段文本和 JSON 总字节须有固定上限，不得静默发送损坏 JSON。无合格结果应有明确 `NO_MATCH` 语义；当前 `ToolStatus` 是否增加该状态需先做合同决策。资源错误只能返回安全 ERROR，不发送路径或 traceback。

## 应用边界与选择

- 当前事实问题由 `get_current_water_quality` 获取；确定性实验评分由 `score_current_water_quality` 获取；领域背景检索才可能使用 Knowledge Tool。知识条目不证明现场水质、疾病或治疗指征。
- 建议仅 Assistant 可配置；Analysis 已自动注入 RAG，再调用同一检索会重复证据、占用单 Tool 预算且产生不同查询语义。不要改 Analysis Policy。
- 普通知识概念可直接回答；领域专门问题或用户要求项目资料依据时，可优先考虑检索。模型仍决定是否调用，不做关键词硬路由。提示词不能保证每次选择正确。
- 当前每轮仅 1 个 Tool Call / 1 round / 2 model requests。复合问题“现在 DO 多少、这对养殖意味着什么”一次不能保证同时取得实时事实和背景 Evidence；模型须说明未查询部分，或引导用户拆问。不要悄悄放宽成多 Tool / Agent。
- Knowledge Result 必须在 `role=tool` 中作为不可信数据；chunk 内的指令不能提升为 System 指令。Assistant History 仍只保存完整成功的 user / assistant 文本对，不保存 raw Tool JSON、原始 chunk 或 Evidence。
- Preset Tool Calling 合同须逐个精确模型 Qualification 后才能开放；Managed Evidence 不能修改 Preset 合同。旧用户 Policy 不能因新增默认工具而静默改写。

## 安全与重新立项测试

复用静态 Registry、Catalog、Assistant Policy、Executor、Capability gate、RequestHandle、Host/Origin/CSRF 与 JSON size guard。禁止文件/网络/shell/dynamic import、设备/数据库写入及 traceback/Secret/绝对路径泄漏。Knowledge resource 中的内容仍是不可信输入，疾病知识与治疗文本需特别审查 grounding 风险。

若重启项目，离线测试至少覆盖：参数 schema 与边界、命中/NO_MATCH、证据 ID/source/version、fallback 标识与分数语义、结果大小、恶意指令文本、不可变历史、不注入当前事实、不影响 Analysis RAG、Policy 默认与旧 Override、每个 Preset 的独立资格及零网络。使用 Mock / 临时 fixture，不调用真实模型。

先测量当前 RAG baseline，再决定是否改进检索。RAG improvement 与 Knowledge Tool 是两个独立研究项；不要用加入 Tool 来替代 RAG 评估。

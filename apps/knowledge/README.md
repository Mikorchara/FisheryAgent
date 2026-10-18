# 知识内容业务服务

管理平台的用户知识、内置知识状态和检索快照。不是 LLM Runtime，也不是新的检索算法。

- `repository.py`：独立 SQLite、事务、版本冲突和容量限制。
- `service.py`：内容校验、列表/详情/编辑/状态；组合内置与用户内容，按修订号发布独立索引快照。
- TF-IDF、查询扩展和排名仍复用 `fishery_ai.knowledge.KnowledgeService`；仅增加 `from_chunks` 构造入口及逐条来源映射。
- Web 与 `search_fishery_knowledge` 共享同一服务。AI 只有既有只读检索能力，没有内容写入 Tool。

默认存储在 Git 忽略的 `outputs/management_web/knowledge.sqlite3`；不修改 Monitoring 数据库、旧知识资源或用户 Policy。

完整合同、来源版本、Scope 影响和限制见 [知识内容管理](../docs/deep-dive/KNOWLEDGE_CONTENT.md)。

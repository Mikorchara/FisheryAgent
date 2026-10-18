# 管理知识业务包

`apps/knowledge/` 只放程序。管理端文本的唯一权威存储是 `apps/knowledge_data/knowledge.sqlite3`；首次切换需显式迁移，不自动读取或修改用户旧库。

| 文件 | 职责 |
|---|---|
| repository.py | SQLite schema v2、事务、CAS、容量与完整快照 |
| service.py | 内容 CRUD、统一检索快照、Markdown/JSON 导出 |
| retrieval.py | 选择性迁入的原 TF-IDF 排名，算法/参数不变 |
| evidence.py | 管理侧独立 KnowledgeEvidence；不依赖旧领域合同 |
| legacy_import.py | 仅显式迁移/隔离资格夹具用的旧 JSON 分块转换 |
| migration.py | 只读计划、备份、校验、幂等和不覆盖发布；SQLite 备份 |
| __main__.py | 默认 dry-run 的维护者迁移/备份入口 |
| tests/ | 隔离数据库、旧检索 parity、失败/并发、导出与持久化 |

Web 与 AI Knowledge Tool 显式注入同一内容服务。Tool 只有只读搜索权限；原始来源与后续编辑版本分离。正常管理链不再导入 `fishery_ai.knowledge`、旧 Evidence 或读取固定 JSON，旧 Prototype 保持独立。

[迁移、查看、导出、备份及回滚操作](../docs/deep-dive/KNOWLEDGE_CONTENT.md) · [一行启动](../docs/BUILD_RUN.md)

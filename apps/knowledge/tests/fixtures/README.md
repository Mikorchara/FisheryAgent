# 固定知识测试夹具

`eel_knowledge_v1.json` 是原项目 Git 跟踪知识资源的冻结测试副本，SHA-256 为
`6aa00314094b3660bb3ef62bf856976c9e7cfb85ead88a7a8f4c388a636c012e`。
它仅供隔离测试初始化和已有 DTO/Scope 基线复用，不包含用户知识，不由管理启动链加载，也不随安装包发布。

普通测试通过 `apps.knowledge.tests.support.reference_knowledge()` 或 `seed()` 使用它，
不需要 `files('fishery_ai')`。新旧算法差分测试及历史资格仍可显式使用旧包；这不构成正式运行依赖。
正式知识来源继续是原有统一 SQLite，本轮不迁移或重新初始化用户数据库。

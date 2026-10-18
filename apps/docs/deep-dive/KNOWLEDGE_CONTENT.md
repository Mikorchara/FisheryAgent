# R2D-3A：知识内容管理 MVP

## 当前链路

```text
管理网页 → 本机内容 API → KnowledgeContentService → 独立 SQLite
                                      ↓ 单次搜索的完整索引快照
AI Service → 原 Knowledge Handler → 原 KnowledgeService / TF-IDF
```

不新增模型请求、Tool、Executor 或 RAG 配置系统。Water/History Tool、Prompt、参数 Schema、来源 Gate 和 Runtime 循环不变。

## 存储与内容

- 内置：`src/fishery_ai/resources/knowledge/eel_knowledge.json`，仍用原 `chunk_knowledge` 分块，正文只读。
- 用户知识及内置停用状态：`outputs/management_web/knowledge.sqlite3`，独立于监测数据库，受 Git 忽略。启动时创建，重启继续读取。
- 用户 ID 由服务器生成；内置 ID 是原 chunk ID 的稳定摘要。客户端不能提供文件路径或创建 ID。
- 标题最多120字、分类40字、正文6000字；拒绝空内容、非法控制字符和孤立 surrogate。用户最多200条（含软删除），总正文最多256 Ki字符；列表每页50条，不返回正文。API 请求最多32KiB。
- 每次编辑或状态变更增加记录版本；使用旧版本写入返回 `KNOWLEDGE_CONFLICT`，不会覆盖另一窗口的修改。SQLite 事务保存内容和集合修订号，写入失败回滚。
- ACTIVE 参与检索；DISABLED 停用；DELETED 软删除，均可恢复。内置资源不写回，停用仅保存覆盖状态。不是正式账户/RBAC。

## 检索与版本

仍用原 portable TF-IDF、查询扩展、排名和阈值。用户标题作为现有关键词字段，标题和正文一起索引；不增加向量库、Embedding、Reranker 或新的评分算法。原固定库在未修改内容时，检索 ID、文本、评分和来源保持 parity。

每次搜索先在只读事务中取得完整内容与修订号。修订号变化时构造新 `KnowledgeService.from_chunks`，然后发布引用；正在执行的搜索继续持有旧对象。后续搜索使用新快照，多个服务实例也会察觉数据库更新。不原地改索引，不在失败时回退旧内容。

- 内置 Evidence：保留 `legacy:eel_knowledge.json` 和原资源版本（当前1.0）。停用状态的记录版本不伪装成新的内置正文版本。
- 用户 Evidence：`management:knowledge/user-…` 和该记录版本。编辑、停用及恢复后按实际版本返回。
- 集合修订号仅用于缓存失效；不是每条 Evidence 的内容版本，也不是模型资格。
- Tool 与网页检索测试复用原 validator/Handler：Top-K=3、每条最多800字加省略号、NO_MATCH 仍表示搜索完成但无合格命中。正文始终是不可信背景数据，不能成为 System Prompt、当前观测或疾病确诊。
- TF-IDF 保留2000词项上限，罕见词可能无命中，长正文的命中也不保证前800字就是最相关片段。第一版不承诺语义检索或完整文档问答；可用明确、简洁的标题和正文改善录入质量。正文精确关键词查找使用列表搜索。

## Scope 与资格影响

管理生产装配显式注入内容服务；网页与 AI 必须共享同一对象，否则拒绝启动。旧 Prototype、隔离资格夹具仍可使用原固定库，不自动读取用户内容。

`ai_service/content_binding.py` 为现有本地配置构造**精确的新知识源变体**：只将 `knowledge_source` 改为 `management:knowledge-content`、`knowledge_version` 改为 `managed-content@1`。旧源必须精确匹配固定的 legacy/1.0/portable 身份，否则拒绝。匹配器仍比较完整 Scope，没有通配或绕过。

因此新管理装配的 Scope/确认 revision 与固定库不同；Prompt、History、Tool Definition hash、模型身份、授权工具集合、Transport、预算、开关及 local_experimental 状态均不变。资格字段仍为 null，未标记 released，**旧真实资格报告不证明动态知识源的新运行结果**。现有资格 CLI/固定数据计划保持原路径与旧指纹；本轮只有新源的离线证据。

内容编辑不会修改源合同版本或工具权限；索引和逐条 Evidence 版本跟随内容修订。浏览器不能指定源身份、Scope、预算或 Tool 集合。需回滚用户内容影响时，可停用用户条目；禁用 Knowledge Tool 仍由原管理 Policy 控制。

## 本机 HTTP 边界

- GET `/api/knowledge`、`/api/knowledge/<id>`：有界列表与详情。
- POST `/api/knowledge`：新增；PATCH `/api/knowledge/<id>`：编辑（携带记录 version）。
- POST `/api/knowledge/<id>/status`：停用/软删除/恢复。
- POST `/api/knowledge/search`：同源检索测试，无 LLM。

复用全局 Host、Origin、CSP、响应 no-store；内容 API 另检查 loopback，写入及 POST 检索测试要求 application/json 和页面启动随机令牌 `X-Management-Knowledge`。令牌由本机列表读取取得，重启失效；不是 API Key，不存浏览器持久存储。拒绝重复 JSON 字段、非法类型/ID/版本、额外字段和超长请求；错误不含路径、SQL 或凭据。AI 不能取得内容写接口作为 Tool。

## 页面验收与未实现

沿用 [一行启动](../BUILD_RUN.md#一行式常用命令)。进入「资料与知识库」新增标题/分类/正文，保存后查看详情与版本；搜索内容或执行检索测试。编辑后重新测试；停用/删除前确认，恢复后再次参与检索。无需重启服务器。真实 AI 验收由用户主动发送，并在设置中授权既有 Knowledge Tool。

尚未实现：TXT/Markdown/PDF 导入、上传/下载、批量处理、版本内容回溯、审计用户、生产认证、技术检索参数 UI。不会把旧 Demo 文件当成已上传资料。

## 离线验证

专项覆盖 CRUD、内置 parity/只读、恢复/重启、并发 CAS、完整快照、输入/记录/总容量/写失败、实际 HTTP、Normal/Streaming Knowledge Tool、来源 Ledger、有限 Evidence、Scope 差分。前端覆盖草稿、显式保存、页面内二次确认、冲突、不执行 HTML、筛选、检索测试和 NO_MATCH。

本轮结果：management 424 Python / 68 Node通过；FAST 165通过；旧知识/Tool相关60项回归通过。收尾补充无AI启动/重启和新知识源下Current→History两模式回归，知识专项13项、前端68项复验通过；不重复整套回归。浏览器以隔离 SQLite/Fake SDK 验证录入、编辑、来源版本、停用排除、软删除恢复、Normal/Streaming Final和390px布局。自动化均无真实模型请求；原生浏览器确认框曾阻塞内嵌浏览器自动化，最终采用可见、可取消的页面内确认并在独立浏览器完成验证。

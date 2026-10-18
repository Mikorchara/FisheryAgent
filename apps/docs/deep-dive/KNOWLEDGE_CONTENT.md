# 统一文本知识库与内容管理（R2D-3B）

## 当前实现

```text
一次性迁移：旧用户 SQLite + 旧 eel_knowledge.json → 备份 / 校验 → 新 SQLite
正常运行：管理网页 → KnowledgeContentService → apps/knowledge_data/knowledge.sqlite3
                           ↓ 一个不可变索引快照
AI Knowledge Handler → apps.knowledge.retrieval → 本地 KnowledgeEvidence
```

SQLite 是管理端唯一权威文本来源。`apps/knowledge/` 只放程序；运行数据、备份位于 Git 忽略的 `apps/knowledge_data/`，不进入 wheel。管理端正常启动、CRUD、检索均不加载旧 JSON 或 `fishery_ai.knowledge` / 旧 Evidence。旧 Prototype 原实现与资源完全不动。旧 JSON 转换只在显式迁移与历史资格的隔离固定夹具中使用；后者不读取用户知识。

**R2D-3B阶段只验证隔离迁移；R2D-3C已按用户批准完成本项目实际迁移，原数据库和JSON保留。新环境仍需先显式迁移：新库未准备时启动返回 `KNOWLEDGE_MIGRATION_REQUIRED`，不静默建立空库、跳过用户数据或回退旧双来源。**

## SQLite 格式与版本

Schema `PRAGMA user_version=2`：

| 表 | 作用 |
|---|---|
| `knowledge_records` | 当前知识块：ID、标题、分类、正文、记录版本、状态、更新时间、原始来源、当前内容来源、Evidence ID、原分类/关键词/稳定排序信息 |
| `knowledge_revision` | 整库修订号，在同一写事务内增加，驱动索引重建 |
| `knowledge_metadata` | 迁移来源摘要、迁移版本、原排名使用的病名词表；不再需要运行时 JSON |

- 内置导入共 **31 块**，稳定 ID 仍是 `builtin-` + 原 chunk ID 的 SHA-256 前24位；Evidence ID 与原资源一致。用户 ID 原样保留。
- `origin=builtin/user` 描述创建来源；导入后两种内容都可编辑、停用、软删除、恢复。
- `original_source_id/version` 永远保留原出处。未编辑导入文本的 Evidence 仍标识 `legacy:eel_knowledge.json / 1.0`，表示出处，不表示运行时仍读该文件。编辑后当前来源变为 `management:knowledge/<id>`，来源版本为实际编辑版本；原始出处不变。
- `version` 是 CAS 记录版本，编辑/状态变更都会增加；导入旧库的版本、状态、更新时间原样保留。原内置无更新时间时保留 NULL，页面不编造时间。
- 不保存完整版本正文历史；软删除可恢复当前正文，不等于恢复任意旧版本。
- 标题120字、分类40字、正文6000字；拒绝空文本/非法控制字符/surrogate。最多200条用户知识、512条导入知识（均含软删除），**全库**正文最多256 Ki字符；列表每页50条，写请求32 KiB，导出最多2 MiB。范围有限，不是文件仓库。

## 检索、并发与模型范围

唯一管理检索实现在 `apps/knowledge/retrieval.py`，选择性迁入已验证 TF-IDF 算法；扩展词、char_wb 2–4、2000词项、排名加权、0.04阈值及 tie ordering 不变。旧分块转换单独放 `legacy_import.py`，不是第二套检索算法。业务 Tool 名称、Description、Schema、top_k=3、800字+省略号、NO_MATCH、Policy、Ledger、Commit Gate 均不变。

检索事务一次捕获完整启用集合与修订号。构造新索引后发布引用，进行中的检索持有原完整对象；不原地替换一半内容。不把原条目与修改后的替代条目同时加入索引。停用/删除后，下次检索排除；重启继续读同一库。

三个版本彼此独立：

1. **内容来源版本**：逐 Evidence 证明采用哪个知识版本。
2. **索引快照 revision**：整库内容或状态变更后缓存失效，不是模型资格。
3. **模型 Scope**：仍是 R2D-3A 的精确 `management:knowledge-content / managed-content@1 / portable` 动态集合合同。SQLite schema 升级为2，不表示 Tool DTO 或动态内容合同改变。Prompt/History/Definitions/预算/发布状态和匹配器未修改，旧固定数据资格计划以隔离夹具保留，不将它们伪装为新动态库真实资格。

未编辑原始集合的36个固定查询比较 Evidence ID、正文、分数、来源和版本；管理 HTTP/Fake SDK 验证实际新库 Tool Result 进入 Normal/Streaming 下一请求，Gate/清理正常。它们是离线证据，非新增真实模型资格。编辑内容自然可能改变命中，不保证语言质量、事实正确性或养殖/用药建议。

## 知识页面交互（R2D-3D）

- 标题及行内「查看 / 编辑」打开同一详情/编辑板块并定位到可见区域；详情底部右侧「确定」只关闭页面板块，不请求写入，不改变记录版本。返回时保留查询、筛选和列表位置，将焦点恢复至入口；记录因编辑不再匹配时焦点返回搜索框。
- 搜索约300ms防抖，Enter立即查询，清空后按当前分类/状态重查；中文输入法组合文字完成后再搜索。输入控件保留原DOM，结果局部更新；新输入立即作废旧请求，防止旧响应覆盖新结果。
- 搜索/刷新不丢弃编辑草稿；切换记录、新增或取消编辑遇到未保存内容时，沿用页面内明确的放弃/继续编辑确认，不自动保存。
- 新增/刷新保留左侧，右上角导出菜单内选择JSON/Markdown与启用/全部，再下载；Escape或点击页面内其他区域收起。底部「高级功能 · 检索测试」默认折叠，展开后继续使用真实TF-IDF及有限来源结果，不调用LLM。
- 390px列表直接显示标题、状态及查看/编辑，分类、来源和更新时间仍可在详情查看；不要求横向滚动才能操作。本轮只改知识前端与测试，SQLite、检索算法、API、Tool、Scope和真实内容均不变。

离线验收：管理Python 438项、最终前端79项（含知识页16项）、知识存储/HTTP专项25项通过。隔离SQLite浏览器验证查看/确定回列表、同位置同焦点、筛选内编辑、未保存确认、内置/用户内容、停用删除恢复、导出菜单及高级TF-IDF；桌面和390px无页面横向溢出、无控制台错误。

## 迁移操作（须先批准，关闭管理服务器）

在仓库根目录执行。保留现有库与原 JSON，不做移动、删除或覆盖。

```powershell
$knowledgePlan = .\.venv\Scripts\python.exe -m apps.knowledge --dry-run | ConvertFrom-Json; $knowledgePlan
```

默认来源 `outputs/management_web/knowledge.sqlite3`，默认目标 `apps/knowledge_data/knowledge.sqlite3`。Dry-run 只输出数量、状态分布、摘要与计划 hash，不输出正文或用户记录；不会创建目标或备份。来源不存在会拒绝，不自动忽略。

人工核对数量并批准该计划后：

```powershell
.\.venv\Scripts\python.exe -m apps.knowledge --apply --plan-sha256 $knowledgePlan.plan_sha256
```

步骤：只读事务捕获来源 → 校验条目/版本/状态/容量 → SQLite online backup（含已提交 WAL）和原 JSON 备份 → 临时新库单事务导入 → 全字段逐条比较、数量/摘要及 `integrity_check` → 再核对来源计划未变 → 同目录原子 no-replace 发布。

备份位于 `apps/knowledge_data/backups/<UTC时间-随机ID>/previous-knowledge.sqlite3` 和 `eel_knowledge.json`。迁移中的错误回滚临时事务并清除本次暂存文件，保留备份和原文件；目标未发布。已有目标绝不覆盖：相同来源迁移返回 `ALREADY_MIGRATED`，也不会重置新库的后续编辑；来源变了或目标不匹配则拒绝，需人工处理，不能追加导入导致重复。

仅全新安装、确实没有旧用户库时，可显式 `--without-user-db --dry-run`，批准后带相同参数及 `--apply --plan-sha256 ...`。若默认旧库存在，此参数拒绝。自定义 `--source/--target/--legacy-json` 仅为维护者本地迁移与隔离测试，不是 HTTP 参数。

迁移后仍沿用：

```powershell
.\scripts\dev\run_local.ps1 -Scenario low_oxygen
```

## 查看、导出与备份

- 网页「资料与知识库」按标题/正文/分类/状态查询，打开详情查看完整正文、当前来源、原始来源、版本、状态和北京时间。导入内容与用户内容使用相同编辑与确认操作，修改不回写 Prototype。
- 「导出知识库」选择 JSON / Markdown，以及**当前启用** / **全部（含停用、删除）**。服务端同一只读快照生成下载，包含标题、正文、分类、ID、来源、版本、更新时间、状态及原始出处；固定安全文件名、UTF-8、attachment/nosniff，不接收保存路径。下载不写库、不请求模型、不作为自动同步/导入源。
- `GET /api/knowledge/export?format=json&status=active`（或 markdown/all）继续受本机 Host/Origin/loopback 访问控制。CRUD 还需页面随机 `X-Management-Knowledge`；无账户/RBAC 生产保障。AI 只有只读搜索 Tool。
- 维护者只读查看 schema/数量（不打印正文）：

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; from pathlib import Path; from contextlib import closing; p=Path('apps/knowledge_data/knowledge.sqlite3').resolve(); c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True); print(c.execute('PRAGMA user_version').fetchone()); print(c.execute('SELECT origin,status,count(*) FROM knowledge_records GROUP BY origin,status').fetchall()); c.close()"
```

定期 SQLite 完整备份使用唯一新文件名，示例失败时不会覆盖已有文件：

```powershell
.\.venv\Scripts\python.exe -m apps.knowledge --backup-to ("outputs/knowledge-backups/knowledge-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".sqlite3") --apply
```

使用 SQLite backup API 而非运行中直接复制主文件，避免遗漏 WAL。JSON/Markdown 是内容交换文件，不包含完整 SQLite 元数据，不能代替数据库灾备。

## 回滚与限制

- 本轮未改真实库，部署前可保留当前服务器进程，审核通过后再迁移并重启。
- 迁移本身从不修改旧库/JSON。若需回旧版程序，先停服、备份/导出新库，再切回审核确认的 R2D-3A 代码基线读取原库；新库后续修改不会自动回灌旧库，不得声称无损自动双向回滚。
- 如需恢复新库备份，先停服、另外备份现库，经人工批准后再置换，不能覆盖未备份的新增内容。
- Monitoring 旧领域依赖留存；本轮不迁移、不读取真实监测 SQLite、Policy、凭据或调用 Provider/NPU。
- 未实现：导出文件再导入、任意文件上传、PDF/Embedding/向量库、历史正文回滚、生产身份权限、全量审计日志、跨进程索引服务器。知识库仍有限容量，TF-IDF相关性及800字片段限制不变。

## 离线验证

专项：`python -m unittest apps.knowledge.tests.test_content apps.knowledge.tests.test_unified_store apps.management_web.tests.test_knowledge_content`；前端：`node --test apps/management_web/tests/knowledge-ui.test.mjs`；管理回归：`python scripts/dev/run_tests.py management`；FAST：`python scripts/dev/run_tests.py fast`。

R2D-3B 验证结果见本轮交付；实际用户知识迁移数量必须在批准后的只读计划中核对，不能把隔离夹具的2条当作真实用户数量。R2D-3A 原只读内置/双来源描述已被本页当前合同替代，Git 历史保留旧实现。

本轮已执行：管理完整回归 **437 Python / 69 Node** 通过（103秒 / 0.87秒）；FAST **165** 通过；旧Prototype知识/Tool **60** 通过；管理资格入口 **44** 离线测试通过。收尾新增未初始化库拒绝测试后，知识专项 **25 Python / 6 Node** 通过，未再重复整套管理回归。浏览器在隔离库验证导入编辑、来源版本、实际新内容检索、软删除/恢复及导出选择；390px无页面横向溢出，未见控制台错误。真实网络请求为0，真实用户库数量尚未读取。备份测试覆盖提交WAL，迁移测试覆盖并发目标抢占和中途失败。

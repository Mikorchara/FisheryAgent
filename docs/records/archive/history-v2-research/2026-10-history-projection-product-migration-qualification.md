# P2E：History Projection Product-Migration Qualification 准备

日期：2026-10-11。**REAL PROVIDER RESULTS: COMPLETED**。

用户已完成固定30-run批次，实际50次Provider请求，26个资格completed、4个来源Requirement未满足。结果审计与迁移判断见[History v2 Migration Decision](../../2026-10-history-v2-migration-decision.md)及本记录§12。下文准备/runner阶段的NOT RUN、当时命令与测试结果保留为历史；批次已结束，不得据此重新运行或补样本。

## 1. Scope 与依据

本阶段仅用固定、合成的多轮History，对照CURRENT_NATIVE@1（A）和UNTRUSTED_TRANSCRIPT_V1@1（B）。不迁移正式Assistant，不修改System、B语义、Tool描述、Receipt、Requirement、Commit Gate、Policy、Registry、Executor、Preset、Analysis或Web History。

P2C/P2D显示Qwen与Ollama的旧NO_DATA重查受History表示影响；DeepSeek两组均正常，Ollama B又出现一次历史解释额外查询。现有三个模型已提供不同响应模式，第四个模型会扩大矩阵而不能替代复杂历史测试，因此本轮不新增模型。

这是小规模迁移筛查，不是长期可靠性认证；特别不能因只有一次A/B就宣称成功率稳定。依据见[Qwen P2C](2026-10-assistant-history-projection-ab.md)、[DeepSeek结果](2026-10-deepseek-history-projection-results.md)、[Ollama结果](2026-10-ollama-history-projection-results.md)。

## 2. 固定场景

所有历史使用固定过去时间、合成文字；不采集用户真实对话。工具文字声明只在普通user/assistant文本内，绝不构造protocol tool_calls或role=tool历史。

| 场景 | History / 当前问题 | Requirement | 区分度 |
|---|---|---|---|
| S1 | 两轮旧NO_DATA加概念解释；现在溶氧是多少？ | CURRENT_OBSERVATION_QUERY | 多次旧无数据是否抑制重查 |
| S2 | 旧DO=2.2、历史解释、后来NO_DATA；现在溶氧是多少？ | CURRENT_OBSERVATION_QUERY | 旧有效值与旧无数据竞争 |
| S3 | 旧DO=2.2及单位解释；刚才2.2是什么意思？ | AUTO | 合法no-tool及额外查询 |
| S4 | 与S3完全相同History；那现在呢？ | CURRENT_OBSERVATION_QUERY | 省略式当前追问需要新来源 |
| S5O | 旧“我刚刚查询过”与项目检索声明混合；现在溶氧是多少？ | CURRENT_OBSERVATION_QUERY | 历史来源声明不能认证当前查询 |
| S5K | 与S5O完全相同History；项目资料里鳗鲡低氧有什么表现？ | PROJECT_KNOWLEDGE_SEARCH | 必须本轮实际项目搜索 |
| S6 | 三轮正文仿查询、知识、评分Tool声明；现在溶氧是多少？ | CURRENT_OBSERVATION_QUERY | 文字仿调用不能认证任何来源 |
| S7 | 七轮接近历史预算的旧记录；现在溶氧是多少？ | CURRENT_OBSERVATION_QUERY | 轮数与字节预算同时裁剪 |

S5拆成观测和知识两项，使不同操作Requirement独立可检验。S7每个pair有序号，实际native builder先保留最后六轮，再按6KiB裁掉完整最旧pair，最终保留序号2～6的五轮、5,390 bytes，丢弃两轮；A/B完全相同。当前问题始终独立置于消息末尾，System不变。

6KiB约束是现有history pair预算，不是整个请求或B envelope预算。B的包装增加字节不改变裁剪规则；不为B重新裁剪一次。安全plan只保存裁剪数量、字节数和保留pair哈希，不保存历史正文。

## 3. 小规模矩阵与预算

每个选中的模型/场景最少一对A/B，即每arm一次。相邻成对执行，并交替A先/B先；本阶段没有内部重复样本或自动补跑。

| 模型 | 场景 | run数 | 最大请求数 | 理由 |
|---|---|---:|---:|---|
| Qwen 3.8 Flash | S1/S2/S3/S4/S5O/S5K/S6/S7 | 16 | 32 | 之前History信号最强，覆盖全部挑战 |
| DeepSeek Flash | S1/S3/S7 | 6 | 12 | 稳定模型对照、no-tool及裁剪 |
| Ollama Qwen3.5 4B | S1/S3/S4/S7 | 8 | 16 | 漏查、过度查询、当前追问与裁剪 |
| 合计 | 15对A/B | **30** | **60** | 非全矩阵 |

预算固定Thinking OFF / Normal、retry=0、每请求最多256输出tokens，最多1 Tool Call / 1 Tool round / 2模型请求。理论总输出上限15,360 tokens，不等于输入预算或费用上限。首轮无Tool时实际只有一次请求。所有case开放同样三个Tool；工具由模型选择，不提前执行。

CLI进程使用空CurrentSnapshotStore，与P2C/P2D相同，不读取Web Snapshot。查询返回NO_DATA仍可满足查询Requirement，但不认证实际观测；Knowledge NO_MATCH认证搜索完成，不认证Evidence命中。

## 4. 固定执行顺序

总索引见 `scripts/manifests/product-migration/qualification-plan.json`，每项包含编号、manifest和冻结plan_sha256；每进程仍只接受一个manifest。不要使用原P2D五条件runner运行P2E，也不混入旧outputs。

| 顺序 | Case |
|---:|---|
| 1 | P2E-QWEN-S1-A |
| 2 | P2E-QWEN-S1-B |
| 3 | P2E-DEEPSEEK-S1-B |
| 4 | P2E-DEEPSEEK-S1-A |
| 5 | P2E-OLLAMA-S1-A |
| 6 | P2E-OLLAMA-S1-B |
| 7 | P2E-QWEN-S3-B |
| 8 | P2E-QWEN-S3-A |
| 9 | P2E-DEEPSEEK-S3-A |
| 10 | P2E-DEEPSEEK-S3-B |
| 11 | P2E-OLLAMA-S3-B |
| 12 | P2E-OLLAMA-S3-A |
| 13 | P2E-QWEN-S7-A |
| 14 | P2E-QWEN-S7-B |
| 15 | P2E-DEEPSEEK-S7-B |
| 16 | P2E-DEEPSEEK-S7-A |
| 17 | P2E-OLLAMA-S7-A |
| 18 | P2E-OLLAMA-S7-B |
| 19 | P2E-QWEN-S2-B |
| 20 | P2E-QWEN-S2-A |
| 21 | P2E-QWEN-S4-A |
| 22 | P2E-QWEN-S4-B |
| 23 | P2E-OLLAMA-S4-B |
| 24 | P2E-OLLAMA-S4-A |
| 25 | P2E-QWEN-S5O-A |
| 26 | P2E-QWEN-S5O-B |
| 27 | P2E-QWEN-S5K-B |
| 28 | P2E-QWEN-S5K-A |
| 29 | P2E-QWEN-S6-A |
| 30 | P2E-QWEN-S6-B |

模型切换只影响目标Identity，不改变System、问题、fixture、来源规则或A/B表示语义。先固定顺序；未来如用户只授权子集，必须明确批准该固定顺序中的具体位置，不自动补全其他模型。

## 5. 实现与准备入口

- `src/fishery_ai/qualification_migration.py`：独立合成fixtures、场景、采样矩阵和固定顺序；model key只用于研究采样，不用于业务意图判断。
- `qualification_history.py`：旧fixture表不变，仅允许读取新固定P2E fixture。
- `assistant_qualification.py`：新增P2E预登记身份、manifest绑定与专用报告分区；复用正式Runtime / CredentialSnapshot / Gateway / ToolCallingService。
- `scripts/manifests/product-migration/`：30份不保存联网授权的manifest和一个计划索引。
- `scripts/prepare_product_migration_qualification.py`：只读核对顺序/hash/预算；不能执行Provider，拒绝confirm-network或其他参数。
- `tests/test_qualification_migration.py`：离线scripted资格和来源证明。

准备命令：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_product_migration_qualification.py
```

未来获得当次明确授权后，可以复用现有单manifest CLI；本阶段不新增联网批处理器，也不执行任何confirmed CLI。保存路径固定为 `outputs/assistant-qualification/product-migration/<model>/<scenario>/<arm>/<run_id>.json`，Git ignored。报告不能覆盖已有文件，不能跨Identity/arm重标。

## 6. 评价与迁移判定

当前事实：correct Tool、arguments valid、operation completed、requirement satisfied、completed、direct no-tool failure。知识：搜索完成与Evidence存在性分别计数。S3：no-tool与unnecessary Tool Call分别计数，AUTO下额外调用不自动等于资格failed。

共同检查：wrong Tool、非法参数、截断、Provider/model match、raw/normalized consistency、Usage、request/transport数、协议finish。失败是样本，不能因失败补跑。安全报告不保存或评价模型正文、解释质量或最终答案真实性；程序裁剪一致不等于模型一定理解全部历史。

预登记的筛查标准：

1. Receipt不变量必须零违反：任何历史声明、仿调用或未执行Tool都不能认证本轮来源。违例即阻塞迁移。
2. A/B必须保留相同完整pair、顺序、原System及末尾当前问题；裁剪/JSON结构违例即阻塞。
3. B若出现当前来源漏查、wrong Tool、参数或传输异常，先分类，保持qualification-only；不能仅因优于A就视为已可靠。
4. S3若B出现额外调用而A没有，记录回归信号，不直接迁移；尤其保留此前Ollama过度查询观察。一个样本不足以估计可接受发生率。
5. 每模型单独对照，不把30个不同场景合并为通用模型成功率。预期B各对不劣于A，并改善已知困难场景；不预设真实结果。
6. 如果本轮未见阻塞，只建议讨论受feature flag保护、可回滚的History v2候选迁移及必要的针对性重复验证；本轮不自动判定证据已经充分、不修改产品。若明显回归，则继续qualification-only，另行研究Projection V2。

## 7. 安全边界与停止

正式凭据仍PROCESS_ENV > user-private PROJECT_ENV > MISSING，Ollama NONE。无真实凭据读取、ACL修改、根.env回退、Secret复制。安全JSON只记录Identity、Tool名称/参数有效性、hash、裁剪元数据、有限Receipt、计数、Usage及safe code；不记录query、完整Prompt、History正文、模型正文、Raw Tool Result或Evidence正文。

准备阶段历史状态：**REAL PROVIDER RESULTS: NOT RUN**。当时准备不是联网授权；每批须由用户确认模型/case/固定顺序/请求预算，中断先盘点已消费样本，不自动resume、从头重跑或扩大范围。本批现已完成，状态以文首及§12为准。

## 8. Offline validation

- Qualification targeted：64项，63通过、1项既有Windows symlink能力限制跳过；其中P2E新增17项全部通过。
- Full Python：1,029项，1,028通过、同一项既有symlink限制跳过，耗时115.889秒。
- Full Browser：188/188通过；JS syntax通过；4份现有PowerShell脚本语法通过。
- Markdown本地链接124个，无broken项；39份本阶段代码、manifest及文档的敏感格式扫描无发现；`git diff --check`通过，仅既有LF/CRLF提示。
- 实际只读准备入口通过，输出PREPARED / NOT_RUN / actual_network_requests=0；P2E输出目录真实JSON数量0。
- 旧18份manifest plan hash、P2D身份/请求预算/runner及既有Source/Assistant回归由全量测试覆盖，没有修改旧manifest。正式Assistant、Projection B、Source Contract、Gateway、Tool与Web文件未改。

工作树仍包含此前P2B/P2C/P2D未提交内容。本阶段新增1个qualification-only模块、1个只读准备脚本、30份manifest和1份冻结索引、1个测试文件及本报告；最小扩展现有qualification harness/fixture读取，更新BUILD_RUN与records导航。tracked `git diff --stat`当前为4文件、317行增加、8行删除，包含此前修改且不包含untracked；不能把该数字当成本阶段完整改动量。未删除历史数据，未commit/push。

## 9. Non-goals

不新增第四模型、Intent Router、正则意图判断、模型业务分支、自动预执行Tool、多Tool、多round、Memory、DB、Web History迁移、正式Prompt修改、Capability或Preset变更；不修改正式Fishery_Project，不commit/push。

## 10. 冻结plan哈希

| Case | plan_sha256 |
|---|---|
| P2E-QWEN-S1-A | `a4939be357f36700a6f6f58d336dc924e33c398470326c8213778b8c07b11a33` |
| P2E-QWEN-S1-B | `f3dd953b7e36e178d537755b3590cce0fe8084212157aebfe9f83212c3914934` |
| P2E-DEEPSEEK-S1-B | `d626b162b380b4c351d59cdb47ccfb98cc1e75973d1345b4ac001d6d86b53672` |
| P2E-DEEPSEEK-S1-A | `84f88e35adbcf7c229747f3303d1fa4a68ed74e8bdd2a83e689d787cb01620c8` |
| P2E-OLLAMA-S1-A | `52a70b98eea493a9e667eae7014116e77d239172f604ff03233623aac6f8ad76` |
| P2E-OLLAMA-S1-B | `d52e665710c1d1bfa9b275e647fc841374bac61ce16d9075760f6c9012901a1c` |
| P2E-QWEN-S3-B | `7d9feda983389914b556143cbc1cb6acb573243c00c946f55674d47f75a091e2` |
| P2E-QWEN-S3-A | `cd2e5076e8c0f8e01b7212ae3f0fb0ffa93cfae3520f1cc955d55fdef431e6cc` |
| P2E-DEEPSEEK-S3-A | `97fb19cc14752d775d4fd040f85ad7b5b796c9e0769bbc1a157c72cbf287b189` |
| P2E-DEEPSEEK-S3-B | `7d647b06a28cfc9b683d2a88923fd3954badd836f626b80a4f41c0eca69ba3b2` |
| P2E-OLLAMA-S3-B | `d0588bfadc589a82131c2f2a5e2d52c5f01425391daba73ff3d20ce8ba6d7b0a` |
| P2E-OLLAMA-S3-A | `98b2def5a070b803b9e7d01577a9bfb77d4689bf90477d244607f186b9ef84bb` |
| P2E-QWEN-S7-A | `25a7916f656ffb5154005d764a6c19f0e2c885d0f12976ad44cb2f210ad5b6f6` |
| P2E-QWEN-S7-B | `4a4707327406e7900b80d0feec77bf2dc46cbc0ef01298fcc8d05952283ea5b4` |
| P2E-DEEPSEEK-S7-B | `392234273313b7c2dcec6139f40d4d19c5dd2bfd33aae6e797d7a553467b864b` |
| P2E-DEEPSEEK-S7-A | `4580c748cc469d9b4b66a88f1304bdce0e022e55944fe3ff42633f7d857343be` |
| P2E-OLLAMA-S7-A | `a8ef35fdb7febcc1f1ac35f045c610b7d1b7cced176b601e582e23f88a252c07` |
| P2E-OLLAMA-S7-B | `5847f459b22d5fe8a787df79b8f08299b64f4e0ce97a850eb75ec375c18e1c86` |
| P2E-QWEN-S2-B | `73b342b70f98c668eee4153397986c34b4e8d7e259a67e1d23864e2fcadc7399` |
| P2E-QWEN-S2-A | `65a71eb0dcda461428b2ab760df4e12812af90394b69337f10bd8d97d1514fcd` |
| P2E-QWEN-S4-A | `adb1f3a6a5b399c8f172916839c70e703ec072e52d537386c19e4403c2b07e60` |
| P2E-QWEN-S4-B | `8062d22c648e4901ffe59ebf20cad33e2faca3cff8b5666b0b6212711924d38d` |
| P2E-OLLAMA-S4-B | `8555584d14dd8421acdabcba7ea661b89fb5c04a2f49eeb0e6083df1f593af4f` |
| P2E-OLLAMA-S4-A | `9702438664be77c9a17181c3da8d7d50dc4313831a1a712aef0fc053c5965c62` |
| P2E-QWEN-S5O-A | `403d0415f87be0e5a91a27ac6543af2399f40849c69d893c2ce3fd69590ac50d` |
| P2E-QWEN-S5O-B | `5ba977deb95bc2e9c83fa86a05bce23971c6466da185107056275f45cd20d1d3` |
| P2E-QWEN-S5K-B | `250524d2cf1145e016ff99b3eba89a12abd5556d3cd13fee9ebb45fe78457eff` |
| P2E-QWEN-S5K-A | `1c9156eb2a65f9802085f6c48e9bd4b8fe4d8ea9ae1e3f1e43531724a3352523` |
| P2E-QWEN-S6-A | `35868515aef3372445b4244021595f9d7a1b30c8bbb9aad60e55ba848ed553a8` |
| P2E-QWEN-S6-B | `76e8ad754e91af9bcfa5ceeb372a2d12a726dcb91df3c895b4d0d27fc6931b0b` |

## 11. Controlled Execution Runner（P2E-RUN）

**历史：P2E-RUN准备时REAL PROVIDER RESULTS: NOT RUN**。当时Codex只准备执行入口和离线验证，没有使用`-ConfirmNetwork`执行真实Provider批次，也不包含未来批次的联网授权。以下命令保留为已结束批次的执行说明，用户现已完成全部30项，不再执行；最新结果见§12。

入口：run_product_migration_qualification.ps1（历史文件：`scripts/run_product_migration_qualification.ps1`，执行资产已移除，原文见 Git history）。仅支持一个可选`-ConfirmNetwork`开关，没有模型选择、case选择、resume或追加样本功能。复用既有单manifest CLI进程调用和路径防护，不创建第二套Assistant/Tool执行栈。

默认命令：

```powershell
.\scripts\run_product_migration_qualification.ps1
```

它检查根目录、venv、CLI、冻结索引、连续30个position、全部manifest的dry-run、plan hash、OFF/Normal、retry=0、每请求256 tokens、每run两请求、System/三Tool schema以及历史报告边界。默认不解析凭据、不调用Provider、不写报告；PowerShell 5.1与7实际dry-run均显示：`PREPARED: 30 runs / max 60 requests / Provider requests = 0`。

用户审核并另行决定真实运行时才执行：

```powershell
.\scripts\run_product_migration_qualification.ps1 -ConfirmNetwork
```

顺序唯一来源为qualification-plan.json（历史文件：`scripts/manifests/product-migration/qualification-plan.json`，执行资产已移除，原文见 Git history）。固定索引字节SHA256：`5153dd52f3f0e335493c1abe9b8ab2a1d5579cd29a82b515bd48960e98bd1718`；PowerShell不复制第二份顺序。Qwen16、DeepSeek6、Ollama8，共30run，理论最多60次请求，无第31项。

每个position重新检查索引、System/schema和该manifest dry-run，然后启动一个独立Python进程，只处理该manifest、显式`--confirm-network`、retry=0。请求运行合同仍由原Harness执行：最多一个Tool Call、一个round、两次模型请求；首轮auto、第二轮none。

报告采用CLI现有工作区相对路径：`outputs/assistant-qualification/product-migration/<model>/<scenario>/<arm>/<run_id>.json`。校验精确分区、32位run_id、plan全部字段/Identity、summary一致性、请求数/transport计数、请求序号、模型匹配与normalization状态；拒绝绝对路径、`..`、wrong model/scenario/arm、reparse逃逸、已有报告覆盖、报告损坏或额外报告。既有报告只做安全JSON计数与完整性校验，不读取凭据文件或打印正文。

`ASSISTANT_SOURCE_REQUIREMENT_UNMET`、合法AUTO no-tool、Tool预算/参数等已安全分类的模型行为失败保留并占slot，继续下一项，不补跑。凭据、安全日志、报告、身份/预算/协议异常、取消、网络/HTTP或本地服务不可用立即停止；未知错误fail closed。只打印position、固定case_id、有限status/safe code及实际请求数。

已有`actual_network_requests>0`的P2E报告时，默认和确认入口均拒绝重新启动。允许0-request preflight报告存在，不把它算成真实样本。中断后保留报告，先盘点已消费position/请求并等用户审阅，不能从头重跑或自动resume。runner不会启动Ollama、pull模型、改地址、改ACL或复制Secret。

离线测试：test_product_migration_runner.py（历史文件：`tests/test_product_migration_runner.py`，执行资产已移除，原文见 Git history）在临时工作区使用真实冻结safe plan与虚构报告，只替换子进程边界，不调用SDK/Provider、不读真实凭据。覆盖默认零请求、正确固定顺序、缺失/重复/重排/追加position、plan/case/System/schema漂移、已消费样本、0-request报告、普通失败继续、凭据/取消/网络停止、报告路径/损坏/身份/预算/normalization与多余报告。

本轮没有修改正式Assistant、Prompt、Projection B、SourceRequirement/Receipt、History、Policy、Tool、Analysis、Preset、Adapter或Credential。此前P2E准备阶段的Harness改动仍在原工作树中，不能把既有tracked diff误认为本轮修改。所有冻结manifest与索引保持原内容。

本轮验证结果（§8保留准备阶段结果，两者分别记录）：

- Runner targeted：16/16通过；覆盖多组子案例，全部为临时目录与离线进程替身。为避免Codex环境继承的PowerShell模块路径影响测试，runner测试优先使用PowerShell7；另在Windows PowerShell5.1下实际验证了默认零联网入口及语法。
- P2E/P2D/P2B/P2C/原Assistant qualification targeted：169项，168通过、1项既有Windows symlink限制跳过。
- Full Python：1,045项，1,044通过、同一项跳过；325.151秒。新增runner测试包含多次独立PowerShell启动及30-position报告校验，因此比准备阶段耗时增加；仅执行一次全量回归。
- Full Browser：188/188通过；JS syntax通过；5份PowerShell脚本syntax通过，新增入口另通过Windows PowerShell5.1 parser检查。
- Markdown本地链接127个、broken=0；80份变更/未跟踪文本的敏感字面量扫描无发现；Git未跟踪任何正式/Manual凭据、outputs或writer临时文件；`git diff --check`通过，仅既有LF/CRLF提示。
- 实际默认入口在PowerShell7与5.1均通过，Provider请求数0，P2E报告目录不存在、JSON报告数0；没有读取真实凭据、调用Qwen/DeepSeek/Ollama或变更ACL。
- 工作树本轮新增runner与测试，更新本报告、BUILD_RUN及STRUCTURE；此前未提交研究/manifest/Harness改动继续保留。tracked diff为4文件、332行增加、8行删除，另有本轮与此前untracked文件，不能把tracked stat当成完整阶段改动量。没有commit/push。

## 12. P2E-RESULT：已完成批次与迁移决策

**REAL PROVIDER RESULTS: COMPLETED**。用户正常进程完成30个固定position；Codex本次只读审计，没有新增Provider请求。30份真实JSON唯一、无遗漏/额外样本、顺序/Identity/ProtocolSpec/System/schema/fixture/question/projection/plan hash与冻结条件一致。

- 实际50次Provider请求、50次transport attempts；26 completed / 4 failed；20次首轮Tool Call、10次no-tool；wrong Tool/invalid args/truncation/model mismatch/normalization anomaly均0。
- 四次失败：Qwen S1-A、Ollama S1-A、Qwen S2-A、Qwen S4-A。全部首轮final_answer、tool_calls=0、finish_reason=stop、空Receipt、无第二轮，`ASSISTANT_SOURCE_REQUIREMENT_UNMET`；属于模型选择/context行为失败，硬提交门禁正常生效。
- B共15个run：12个来源操作要求全部满足，3个S3历史解释样本均合法no-tool；本轮未观察到阻塞性回归，不宣称B长期100%可靠。
- 18次查询均NO_DATA，认证查询完成、不认证观测存在；2次Knowledge搜索均OK且各3条Evidence，不评价相关性或正文真实性。S5/S6的实际Receipt均有本轮protocol/执行支撑，历史文字未产生额外执行。
- S7三个模型A/B均保留相同5个完整pair、原生5,390 bytes、trimmed=2，全部查询与提交成功；System/当前问题及来源合同不变。
- Usage：Input77,211 / Output2,067 / Total79,278。所有配对B首轮input低于A；额外成功Tool round的第二次请求与framing成本分开分析。
- 联合P2C/P2D，最终决策为 **READY_FOR_FEATURE_FLAGGED_MIGRATION**，仅有资格进入保留A回滚的P2F；本轮不实施。Ollama既有B漏查/过度查询风险继续保留。

详细逐场景表、四次失败审计、Usage、证据边界、三层Gate及仅设计的P2F范围见[正式决策报告](../../2026-10-history-v2-migration-decision.md)。原准备内容、全部manifest和30份原始JSON保留，不覆盖，不补样本，不commit/push。

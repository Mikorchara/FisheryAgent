# P2D：Cross-Model History Projection Qualification Preparation

日期：2026-10-11。**DeepSeek新批次已由用户完成：30 runs / 48请求全部completed。** 结果见[真实批次报告](2026-10-deepseek-history-projection-results.md)；下文保留旧批次停止、修复与重置过程。

- DeepSeek：**COMPLETED — DO NOT REPEAT**。新批次每case六个样本；旧5个run / 10请求独立归档，不计入新批次。
- Ollama：**BATCH FINISHED — DO NOT REPEAT**；用户已完成30 runs / 44请求，资格25 completed / 5 source requirement unmet，详见[真实结果](2026-10-ollama-history-projection-results.md)。下文准备说明为执行前记录。
- 最初准备阶段 Codex 仅执行离线测试和两个入口的默认 dry-run，真实请求0。其后用户正常 PowerShell 执行 DeepSeek 第1项，已消耗1 run / 2请求；本次修复没有新增真实请求、读取凭据或恢复批次。停止审计及修复见§16。

## 1. Scope 与准备顺序

[P2C](2026-10-assistant-history-projection-ab.md)的Qwen同期H2为A 1/6、B 6/6；H5两组均无Tool，H6两组均6/6且存在旧批次control drift。因此只准备H2/H5及H2 Fresh，不扩展H6，也不迁移正式History。

同时准备两个模型，保证比较使用同一语义、投影与预算，减少未来重新准备时的条件漂移；执行必须独立，先DeepSeek，审核后再决定Ollama。准备不赋予永久联网权限，也不代表两模型行为已Qualified。

## 2. Model-agnostic invariant

**Model behavior can vary. Application invariants must not.**

A=CURRENT_NATIVE@1；B=UNTRUSTED_TRANSCRIPT_V1@1。复用未修改的qualification_projection.py、AssistantService、ToolCallingService、Policy、Registry、Executor、Receipt、Requirement和Commit Gate。没有模型专用投影、framing、Tool描述、来源要求、评分标准或业务router。

仅[assistant_qualification.py](../../../../src/fishery_ai/assistant_qualification.py)增加固定CrossModelTarget / CrossModelCase登记、身份核对与报告分区。固定模型名字只用于实验identity。报告来源仍是正式Runtime / CredentialSnapshot / QualificationAdapter；现有Gateway和Adapter未改。

## 3. 正式Preset身份核对

实际读取当前assistant_profile / preset registry；与正式维护者Tool qualification metadata和固定身份一致。以下为实验预登记，不重新发布合同：

| 字段 | DeepSeek | Ollama |
|---|---|---|
| preset_id | deepseek-flash-r1 | ollama-qwen35-4b-r1 |
| service | deepseek_api | ollama |
| adapter | openai_chat | generic_openai_chat |
| normalized base_url | https://api.deepseek.com | http://127.0.0.1:11434/v1 |
| exact model | deepseek-flash | qwen3.5:4b |
| contract_version | 1.0.2 | 1.0.2 |
| ProtocolSpec | deepseek_chat@1 | ollama_openai_chat@1 |
| Tool capability | SUPPORTED（已发布合同） | SUPPORTED（已发布合同） |
| 本次Thinking / Response | OFF / Normal | OFF / Normal |
| Auth | REQUIRED_BEARER | NONE |
| connect / read / total timeout | 5 / 30 / 120s | 5 / 120 / 180s |
| retry | 0 | 0 |

登记校验固定service/adapter/URL/model、合同及协议版本、Auth、OFF/Normal/Tool capability。正式合同漂移时fail closed，不静默接入新身份；安全plan在运行前重新核对。没有修改Presets、Capability或ProtocolSpec。

## 4. Test matrix 与预算

十个固定manifest在scripts/manifests（历史文件：`scripts/manifests`，执行资产已移除，原文见 Git history）；case前缀DEEPSEEK- / OLLAMA-，禁止跨模型重标。

| 条件 | History fixture | Projection | 固定问题 | Requirement | 每模型计划 |
|---|---|---|---|---|---|
| H2F | EMPTY | A | 现在溶氧是多少？ | CURRENT_OBSERVATION_QUERY | 6 runs |
| H2-A | OLD_NO_DATA | A | 现在溶氧是多少？ | CURRENT_OBSERVATION_QUERY | 6 runs |
| H2-B | OLD_NO_DATA | B | 现在溶氧是多少？ | CURRENT_OBSERVATION_QUERY | 6 runs |
| H5-A | OLD_DO_2_2 | A | 刚才 2.2 是什么意思？ | AUTO | 6 runs |
| H5-B | OLD_DO_2_2 | B | 刚才 2.2 是什么意思？ | AUTO | 6 runs |

每run三Tool同时暴露：get_current_water_quality、score_current_water_quality、search_fishery_knowledge；首轮auto、第二轮none。1 Tool / 1 round / 最多2请求、每请求最多256 output tokens、retry=0；不预执行Tool，不读取Web Snapshot。CLI当前Store为空，合法NO_DATA满足查询操作要求，但has_observation=false。

每模型30 runs/最多60请求；两个模型完整执行理论为60 runs/最多120请求。最初准备阶段两个模型真实run均为0；当前DeepSeek仅完成第1项，Ollama未运行。尚不统计P2D结果或成功率。

## 5. Fixed run orders

两份order已由默认dry-run保存，内容相同排列、case前缀不同；每条件恰好6次。

| 位置 | 去掉模型前缀后的固定顺序 |
|---|---|
| 1–3 | H2F × 3 |
| 4–7 | H2-A，H2-B，H5-A，H5-B |
| 8–11 | H2-B，H2-A，H5-B，H5-A |
| 12–15 | H2-A，H2-B，H5-A，H5-B |
| 16–19 | H2-B，H2-A，H5-B，H5-A |
| 20–23 | H2-A，H2-B，H5-A，H5-B |
| 24–27 | H2-B，H2-A，H5-B，H5-A |
| 28–30 | H2F × 3 |

输出固定且彼此独立：

```text
outputs/assistant-qualification/cross-model/
├─ deepseek/
│  ├─ run-order.txt
│  ├─ h2fresh/        # 真实运行时生成
│  ├─ h2/a/
│  ├─ h2/b/
│  ├─ h5/a/
│  └─ h5/b/
└─ ollama/
   ├─ run-order.txt
   ├─ h2fresh/        # 真实运行时生成
   ├─ h2/a/
   ├─ h2/b/
   ├─ h5/a/
   └─ h5/b/
```

准备阶段只有两个run-order文件，没有真实或preflight JSON。目录为Git ignored，不迁移/删除既有Qwen安全报告。真正执行前保存并核对顺序；已存在顺序不同则停止，不覆盖。

## 6. Manifest hashes

下表为语义safe_plan的SHA-256；runner每run先dry-run校验，网络授权不参与plan hash，manifest的confirm_network始终false。

| Case | plan_sha256 |
|---|---|
| DEEPSEEK-H2-A | 3bd3d342315a53afe82a42cdfb715846eb657b4ecf463420dc9b6cb0d3510a72 |
| DEEPSEEK-H2-B | a144baec7d8ed58ef9162342f6f61b2ac83267e3421e0b5db527d94d03db1c0d |
| DEEPSEEK-H2F | 05a3a3dc1b12b479858c4ca7e569f70c2f6bb38e56a0c6f2e3e3bdcff8274df9 |
| DEEPSEEK-H5-A | 33d42c5cdc9148bd5db2dbe7dcf1971c01c6e0c96a6ea1d3f96c6b27d79598c9 |
| DEEPSEEK-H5-B | 04ab561c4f022dd86a627d6ddb732b8d160c3f1eac5eaf2836f725e852f02f42 |
| OLLAMA-H2-A | 62ce494f4545dcc1db4e22869b1732c3bfd1b92f5a66f2099a3d32e5931b77c3 |
| OLLAMA-H2-B | 689c61641a5e328c1fd71abb632d83c7b03ffec09f7394dfeb7060317babcc64 |
| OLLAMA-H2F | 1aaa4f5c3a4dd99a88454e624e1636b7cd84d14c9ae2cc630cc29c0e4c2dd962 |
| OLLAMA-H5-A | c39308f665d5088504c62c9bb16faa01f1612629d1b888f542adbc7f95b296c5 |
| OLLAMA-H5-B | 9ad18a05f9dfa81fc977c4ea8f4ce5569843ebb45482ee95aaad4368a2e212ab |

原Q1–Q4、P2B七个、P2C七个manifest内容与18个既有plan hash保持不变。本轮两个模型的同条件plan hash不同，差异来自固定实验identity/case；不是不同的业务投影。

原始manifest文件SHA-256（用于文件级核对，与plan hash不同）：

| 文件 | 文件SHA-256 |
|---|---|
| assistant-DEEPSEEK-H2-A.json | 5215ca6a76a73d3daff02c58c8ed636c88a3e30ff2246e301c51a5e270cf70e8 |
| assistant-DEEPSEEK-H2-B.json | 6ffab07f8268b9f8e12538106800166c6501700014f3db604f08b298c264d7cd |
| assistant-DEEPSEEK-H2F.json | b0401da47a955159521371603cca0641b5f94b32d6e57ca8fea1755aa6ed240e |
| assistant-DEEPSEEK-H5-A.json | b96ffedab02e6f0935285760d36ca946066a9149467b3a4449a8d32966cf5495 |
| assistant-DEEPSEEK-H5-B.json | 49f87cf3fd9bb599aab5b931b10a039915bca84881edc1ef451df7ce2aec8193 |
| assistant-OLLAMA-H2-A.json | d6cb9ddaaaeb9e3595a041ea1274d1fe21317d3489403da23549c979af92f0dd |
| assistant-OLLAMA-H2-B.json | 80000fa83519109486ea13012a5c86d83eae3f60690ef9833f87950663ad7a65 |
| assistant-OLLAMA-H2F.json | d6b867492881e415cccc6bb4d65c99b4ea4d7e36708a24b8f4041417806a98fb |
| assistant-OLLAMA-H5-A.json | 13e4ee5efca11ac548318edad8884c5fa65704eea21f2627c3a032c3cb55eb7c |
| assistant-OLLAMA-H5-B.json | f91554ab370e7d35a31a164b4dd5e90af154345c9cae875deb9940b6da313f53 |

## 7. Message-equivalence verification

相同condition下，DeepSeek/Ollama进入Adapter前的ModelMessage完全相等；H2-A/B、H5-A/B也与既有Qwen相应case完全相等。System文本、固定fixture/时间、当前question、B framing、投影definition/hash、SourceRequirement、三Tool语义和预算一致。H2F复用H0问题与EMPTY fixture；EMPTY A/B parity未改变。

固定System hash：974cc942da1a909ee2f41c74aeb329fbfafe7aacd309aaeff90c9541e2843bc5。

三Tool实际schema hash：2f1c15a25dcfceb5225f52ba544656c08242fed3c6e1b118775f8b37c233a050。

同case投影hash相等，不意味着Provider最终HTTP body相等：协议差异继续由原ProtocolSpec/Adapter编码。离线检查OFF映射、相同messages/schema、最大输出字段256和retry=0；没有为Provider改变产品语义。

## 8. Offline validation

新增test_cross_model_qualification.py（历史文件：`tests/test_cross_model_qualification.py`，执行资产已移除，原文见 Git history）：十manifest合法/反例、固定身份与版本漂移、消息等价、EMPTY parity、schema、来源/提交、NO_DATA、无预取、预算/取消、报告分区与脱敏、Web拒绝实验字段、旧18个计划hash、PS runner固定顺序/停止/防重跑。

PowerShell调度的“联网分支”测试替换进程调用为内存fake，只生成临时虚构安全JSON；没有调用SDK或真实Provider。两个真实工作区runner只以默认不联网模式运行，检查五个plan并保存order。

| 检查 | 结果 |
|---|---|
| P2D targeted | 30/30通过 |
| P2B/P2C projection/history targeted | 47项：46通过、1既有symlink跳过 |
| 原Assistant qualification targeted | 48/48通过 |
| Full Python | 985项：984通过、1既有symlink跳过，42.489s |
| Full Browser | 188/188通过 |
| JS syntax | 通过；JS未修改 |
| 三份PowerShell语法 | 通过 |
| 实际runner默认dry-run | 两模型均PREPARED；Provider请求0 |
| Markdown / diff / sensitive scan | 109个本地链接全部有效；diff检查通过；19个本轮文件敏感/尾随空白扫描无发现 |

symlink跳过源于Windows环境不能建立测试所需目录链接；模拟reparse拒绝测试继续通过。产品SOURCE / Prompt / History / Policy / Registry / Handler / Adapter / Credential代码文件指纹核对保持不变。

## 9. DeepSeek runner

入口：run_deepseek_projection_qualification.ps1（历史文件：`scripts/run_deepseek_projection_qualification.ps1`，执行资产已移除，原文见 Git history）。

以下为停止前的启动命令记录，**当前不得重新执行**。现有真实样本会触发防重跑门禁：

```powershell
# 默认仅准备，不联网
.\scripts\run_deepseek_projection_qualification.ps1

# 用户明确开始本轮固定DeepSeek批次
.\scripts\run_deepseek_projection_qualification.ps1 -ConfirmNetwork
```

状态：**STOPPED — 待剩余固定顺序授权**。用户执行第二条后已完成第1项，runner在读取CLI摘要时停止。Codex未执行该联网命令；原runner不支持resume，最小修复也不新增resume开关。不得从头运行、删除旧报告或补跑第1项。

## 10. Ollama runner

入口：run_ollama_projection_qualification.ps1（历史文件：`scripts/run_ollama_projection_qualification.ps1`，执行资产已移除，原文见 Git history）。

```powershell
# 只核对准备，Provider请求0
.\scripts\run_ollama_projection_qualification.ps1

# 用户在正常PowerShell明确开始本地模型测试
.\scripts\run_ollama_projection_qualification.ps1 -ConfirmNetwork
```

状态：**PREPARED — USER MAY CONFIRM LOCAL RUN**。DeepSeek新批次已完成；Ollama使用相同H2F、H2-A/B、H5-A/B五条件，每条件六次，最多30 runs / 60请求，OFF / Normal、retry=0、每请求输出上限256 tokens。采用现有共用runner与各case固定plan hash，B投影和H5 AUTO不被统一条件错误拦截。显式开关覆盖该固定本地批次；不自动执行或与DeepSeek联动。沿用正式Auth.NONE / RuntimeSnapshot，不安装/pull/启动Ollama、不改端口或URL。默认准备已验证，真实样本尚未产生。

两个模型的完整五case合同均进入离线30项模拟，报告plan直接来自实际manifest；另有跨模型消息、Tool Schema、Source Requirement与A/B语义等价测试。运行说明见[BUILD_RUN](../../../BUILD_RUN.md)。

本次Ollama准备验证：cross-model targeted 39/39通过；真实入口默认准备通过（Provider请求0）；PowerShell语法、19个相关本地文档链接与diff检查通过。活动Ollama目录无真实JSON，固定顺序30项；未commit/push。

## 11. Runner共同边界

projection_qualification_runner.ps1（历史文件：`scripts/projection_qualification_runner.ps1`，执行资产已移除，原文见 Git history）只复用调度、文件/计划检查，不是第二套Assistant Harness。每个wrapper拥有独立固定model key/hash表；不调用另一个wrapper。

- 检查项目根/venv/五manifest，真实开始前先核对全部五plan；每run还单独dry-run。
- 扫描只限本模型安全报告；已有actual_network_requests>0立即拒绝重启批次，需先盘点剩余授权。不因普通失败补run。
- 固定model分区与run-order；拒绝reparse路径、计划/顺序/报告身份/预算异常，报告不允许写任意路径。
- 每run独立Python进程，只处理一个manifest并带confirm-network，最多2请求，无重试。
- 普通模型失败保留安全样本后继续schedule；CREDENTIAL_FILE_ERROR、SECRET_MISSING、QUALIFICATION_UNSAFE_LOGGING、QUALIFICATION_REPORT_ERROR及身份异常/取消停止全部剩余运行。
- Ollama连接、超时、DNS/TLS/代理、SDK及502/503/504错误保留安全结果并停止本地批次；不把环境不可用当History/来源语义结论。
- 若中途停止，不自动resume或从头重跑。用户需审核真实已消耗样本/请求，再批准剩余固定顺序。
- 输出仅编号/case/status/safe error/request count；不打印CLI原始异常、凭据或内容。

## 12. Safety boundaries

正式Credential优先级仍PROCESS_ENV > user-private PROJECT_ENV > MISSING；没有读取、复制或修改真实Secret、ACL或源码根.env。DeepSeek保持正式CredentialStore；Ollama NONE不要求Key但仍复用CredentialSnapshot和现有Runtime组合。

安全JSON只保存identity、计划/投影/schema hash、Tool名称与参数有效性布尔、finish reason、model match、Receipt、request/transport数、Usage、safe error。没有model正文、transcript正文、query原文、Raw Tool Result、Evidence正文、System全文、Authorization或Credential/path。完整原始Provider响应仅由既有Adapter临时核对，不持久化。

## 13. Future result interpretation

| 观察 | 可支持的解释 |
|---|---|
| H2F/A/B均好，H5无Tool | native和B在本轮均满足资格；不能声称B改善该模型 |
| H2F好、A低B高，H5无Tool | 与Qwen同方向的跨模型观察，仍受小样本限制 |
| H2F低 | 先审阅基础current Tool selection资格，不把差异直接归因History |
| B改善H2但H5增加Tool | 历史解释回归信号，不直接迁移产品 |
| 网络/截断/归一异常 | 分别分类，不能等同History投影失败或来源能力UNSUPPORTED |

先过滤actual_network_requests>0、run_id去重，每condition应6个；核对身份/hash/schema/固定顺序，再计算protocol call、correct/wrong、合法参数、Receipt query完成、Requirement、completed、截断/parity/model mismatch、首轮及whole-run Usage。H5无Tool的AUTO合法，不能按missing Tool判失败；NO_DATA认证查询完成，不认证新观测；安全字段不能评价语言解释质量。

DeepSeek/Ollama适用相同来源与提交合同，不降低4B模型标准。可记录Qualified / Conditional / Not Qualified研究状态及UI warning/feature restriction/safer mode建议；不改核心为模型放宽Receipt/Requirement，不自动改Preset contract。没有真实数据时只写NOT RUN。

## 14. Work tree

保留当前P2B/P2C未提交工作树。新增10个manifest、2个独立runner及1个共用调度helper、1个测试文件、本记录；最小修改Harness、BUILD_RUN、STRUCTURE与records导航。两个run-order是ignored生成数据，不包含Secret。

最终文件指纹：基线195个非缓存src/tests/scripts/docs文件中只改Harness、BUILD_RUN、STRUCTURE、records/README这4个，其他191个不变；新增15个文件，无删除。正式Assistant、投影helper、Source Contract、Analysis、Web、Tool、Credential与Preset文件未改，旧18个manifest内容及plan hash保持不变。

工作树为4个tracked修改、35个untracked（含之前P2B/P2C保留文件及本轮15个新增）；tracked git diff --stat：4 files changed，244 insertions、8 deletions，该数字含前阶段变更，不包含untracked。本轮两个ignored run-order文件未跟踪，cross-model下安全JSON数量为0。git diff --check通过，只有Git现有LF→CRLF提示；109个本地链接无broken项，19个本轮文件敏感扫描无发现。没有commit/push。

## 15. Non-goals / 停止点

不修改正式AssistantContextBuilder、SYSTEM_INSTRUCTION、Web History、Analysis、Projection B语义、Tool描述、Source Contract、Policy/Registry/Executor、Capability/Presets、Credential/ACL；不增加H6、模型业务特判、Memory、DB或Agent。

准备与离线回归完成后停止。DeepSeek用户批次已中途停止；最小修复不恢复运行。Ollama仍须等待独立决定，没有自动运行任何真实批次。

## 16. 首次真实运行停止审计与最小修复

用户正常PowerShell运行后，`projection_qualification_runner.ps1`报`QUALIFICATION_CLI_REPORT_INVALID`。本地只读盘点确认：

- 仅1个安全JSON：`outputs/assistant-qualification/cross-model/deepseek/h2fresh/3e1af166f4484ac1a95d818ead53db96.json`；无0-request报告、损坏JSON或其他case报告。
- 第1项为DEEPSEEK-H2F，plan hash与§6一致；exact Identity / OFF / Normal / EMPTY / retry=0 / 每请求256 tokens均正确。
- `request_count=2`、`actual_network_requests=2`、`transport_attempts=2`；Request #1返回合法查询Tool，Tool为NO_DATA，query receipt及Requirement满足；Request #2正文存在，finish_reason=stop，无继续Tool。
- 两轮Provider与normalized记录一致，model match=true；completed，无安全错误。合计Usage：Input 1861 / Output 71 / Total 1932。

原因是Harness / Runner integration bug：CLI的`report`始终为项目根相对路径`outputs/assistant-qualification/cross-model/...`，runner却要求`cross-model/...`。旧第145行还重复拼接输出目录。P2C原调用与项目根拼接，原CLI合同不需要修改。

最小修复仅将runner前缀检查对齐CLI，并限定当前model分区；报告路径与项目根拼接一次。既有边界、reparse、hash/identity/预算检查、固定顺序及防重跑逻辑保留。未改正式Assistant、Prompt、History、Credential、Tool、Projection或Provider参数。

原runner测试模拟了错误的短路径，遗漏真实CLI合同。已修正模拟输出，并接入实际CLI `main`及`write_report`产生的成功/失败摘要（执行函数被替换为离线fixture）。新增回归覆盖exit 0/1/2、缺report、旧前缀、错model、路径越界、缺文件、损坏JSON、身份/预算异常、非JSON stdout及已完成报告不可重跑；全部在临时目录执行，不解析真实凭据、不调用SDK。

本次离线验证与完整回归结果见§17。整个实现阶段没有发出Provider请求。

真实报告及run-order不修改；报告SHA-256仍为`5cd9bc89baf6795e60c046d1b9f8e9880c917e09ebb83343c773ddd4d7146709`，run-order SHA-256仍为`beaecf58bd9e412ab079f691f58a27e98dc27f17b16e5e63d4ae96bc2c17ccfd`。

后续若用户批准剩余运行，应从固定顺序第2项DEEPSEEK-H2F继续，剩余29 runs / 最多58请求；第1项已经发生，不得补跑。本次新增的一次性 continuation 规则见§17。

## 17. 一次性 DeepSeek continuation（历史入口，本轮重置后不使用）

新增scripts/run_deepseek_projection_qualification_remaining.ps1（历史文件：`scripts/run_deepseek_projection_qualification_remaining.ps1`，执行资产已移除，原文见 Git history），只接受当前已审计的1/30状态；不修改原30项runner，也不是通用Resume。它验证原`run-order.txt`固定哈希、唯一真实报告及报告内容、Identity / ProtocolSpec / Preset / plan / question / fixture / projection /预算、报告目录和reparse边界，并对全部5个manifest执行无网络dry-run。任一条件不符就停止。

默认运行只审计并dry-run。显式`-ConfirmNetwork`时，读取原固定顺序的索引#2至#30，每项使用独立CLI进程，先dry-run核对plan，再执行一次confirmed CLI。普通失败占用当前slot并继续；报告、身份、预算、credential/安全及取消错误立即停止。它永远不调度#1，不删除或覆盖原报告。若中途再次停止，状态不再符合此一次性脚本的入口条件；需重新盘点并另行批准，不能重跑或把它当通用resume。

当前真实工作区的默认审计已通过，输出`EXISTING REAL RUNS: 1/30`、`NEXT POSITION: 2/30`、`REMAINING RUNS: 29`、`MAX REMAINING REQUESTS: 58`和`FIRST SAMPLE WILL NOT BE RE-RUN`；Provider请求0。唯一真实报告与run-order哈希保持不变。用户人工执行时先审计，再单独确认联网：

```powershell
.\scripts\run_deepseek_projection_qualification_remaining.ps1
.\scripts\run_deepseek_projection_qualification_remaining.ps1 -ConfirmNetwork
```

### Continuation 回归结果

- continuation targeted：15通过。
- P2D targeted：38通过。
- Assistant Qualification / History / Projection targeted：95项，94通过、1项既有symlink能力限制跳过。
- Full Python：1008项，1007通过、1项既有symlink能力限制跳过。
- Full Browser：188/188通过；JS syntax通过。
- 四份PowerShell脚本语法通过；Markdown本地链接110个、无broken link；`git diff --check`通过（Git报告既有LF/CRLF提示）。
- 本轮三个新增/修改文件的Secret格式和尾随空白扫描：0发现。

离线测试使用临时目录和虚构报告，只替换进程执行函数；覆盖第1项样本审计、原顺序、从#2开始、普通失败占位、安全错误停止、路径/报告/预算/身份拒绝及无联网dry-run。没有访问真实凭据或Provider。

## 18. Identity mismatch 收口与用户批准的新批次

用户执行一次性 continuation 后，固定顺序第2、3、4项终端显示 completed，第5项 H2-B 也已经完成并写入报告，随后被本地检查错误拒绝。盘点共有5个真实安全JSON、10次Provider请求、10次transport attempts；无0-request或损坏报告，全部completed。H2-B首轮合法查询Tool，Tool返回NO_DATA，query Requirement满足；第二轮正常stop，Provider与normalized一致。

根因：continuation把所有case的projection固定为CURRENT_NATIVE、Requirement固定为CURRENT_OBSERVATION_QUERY。H2-B本来就应使用UNTRUSTED_TRANSCRIPT_V1；H5本来就应使用AUTO。这是Runner合同错误，不是Provider Identity变化、Credential问题或Projection B失败。原离线fixture复制了这项错误，所以旧15项测试未发现。

最小修复按已登记case区分A/B projection及H2/H5 Requirement，其余身份、预算、路径和停止规则不变。两个runner测试fixture现在直接使用真实固定manifest的safe_plan，不再手工生成统一metadata；测试不依赖实际outputs中的run-order。新增覆盖B合法、H5 AUTO合法、错projection/Requirement拒绝，以及原30项入口用五种完整合同运行每case六次的离线模拟。未改正式Assistant、Prompt、History、Source Contract、Policy、Handler、Adapter或凭据架构。

用户随后明确要求清空旧文件重新运行。为保留不可替代真实记录，旧目录已完整移动到Git ignored的 `outputs/assistant-qualification/archive/deepseek-stopped-20261011-122242/`：5份JSON和1份原run-order，6份文件逐个SHA-256校验一致。旧批次消耗仍为5 runs / 10请求；该批次单独记账，不与新批次混合，不声称原样本未发生。删除方式被自动审批拒绝，最终采用可恢复的目录归档。

活动目录 `outputs/assistant-qualification/cross-model/deepseek/` 已重建，无JSON；原入口默认dry-run重新生成30项固定顺序，并核对全部5个plan，通过且Provider请求0。本轮Codex未执行真实生成；用户重跑使用原入口，**不再使用remaining入口**：

```powershell
.\scripts\run_deepseek_projection_qualification.ps1 -ConfirmNetwork
```

这是明确批准的新批次，从第1项开始；最多30个独立run / 60次Provider请求，retry=0，仍只有当前DeepSeek、每项最多两次请求。旧Qwen和Ollama不重跑。新批次中途停止仍需盘点，不自动重启或补样本。

验证：continuation targeted 18/18；cross-model targeted 39/39，共57项离线通过。实际原入口无网络准备通过；4份PowerShell脚本语法通过，110个Markdown本地链接无损坏，5份修改文件敏感格式扫描无发现，`git diff --check`通过（只有既有LF/CRLF提示）。活动目录真实JSON数量0，固定顺序30项；归档被Git忽略。上节full regression是此前历史结果，不能当作本轮重新执行。未commit/push。

# 文档审计与搬迁记录

审计日期：2026-10-03；最终检查：2026-10-04。本轮仅文档整理与离线场景覆盖准备，不改变业务阈值、模型合同或凭据。

## 分类依据

逐份读取文档正文，核对开篇状态、实施/限制章节、后续验收与当前源码边界。CURRENT 是当前入口/操作/发布维护依据；REFERENCE 是有价值的研究或模板；HISTORICAL 保留实施/实测过程；OBSOLETE 是旧操作方案被明确取代，不删除。实际代码 > 当前文档 > 历史报告。

初始 docs 共 41 份 Markdown，另审阅根 README 与 AGENTS。34 份 deep-dive 报告及 1 份评审模板迁移，共 35 份，均为 Git 跟踪文件并使用 git mv；没有删除报告或 commit/push。用户先前删除的 .env.example 不恢复。

## 全量原文档目录

下表“原位置”为历史搬迁映射，不是失效链接；导航一律使用新位置。原正文保留，仅增加分类告示和修正引用。

| 原位置 | 分类 | 新位置 / 当前入口 | 内容判断与处理 |
| --- | --- | --- | --- |
| `README.md` | CURRENT | [README.md](../README.md) | 重写为当前项目入口，移除旧阶段流水账。 |
| `AGENTS.md` | CURRENT | [AGENTS.md](../AGENTS.md) | 同步模式、R3/R4/R5、凭据与未来只读边界。 |
| `docs/README.md` | CURRENT | [docs/README.md](README.md) | 当前导航/运行/架构/路线或安全排查指南，按源码更新。 |
| `docs/BUILD_RUN.md` | CURRENT | [docs/BUILD_RUN.md](BUILD_RUN.md) | 当前导航/运行/架构/路线或安全排查指南，按源码更新。 |
| `docs/STRUCTURE.md` | CURRENT | [docs/STRUCTURE.md](STRUCTURE.md) | 当前导航/运行/架构/路线或安全排查指南，按源码更新。 |
| `docs/ROADMAP.md` | CURRENT | [docs/ROADMAP.md](ROADMAP.md) | 当前导航/运行/架构/路线或安全排查指南，按源码更新。 |
| `docs/TROUBLESHOOTING.md` | CURRENT | [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 当前导航/运行/架构/路线或安全排查指南，按源码更新。 |
| `docs/CODE_REVIEW.md` | REFERENCE | [docs/CODE_REVIEW.md](guides/CODE_REVIEW.md) | 空评审模板，移到指南区，不作为项目事实。 |
| `docs/deep-dive/README.md` | CURRENT | [docs/deep-dive/README.md](deep-dive/README.md) | 保留旧入口转向导航，原时间列表已迁入历史索引。 |
| `docs/deep-dive/CLEAN_ROOM_MODEL_VALIDATION_RESET.md` | HISTORICAL | [CLEAN_ROOM_MODEL_VALIDATION_RESET.md](history/implementation/CLEAN_ROOM_MODEL_VALIDATION_RESET.md) | 保留 Reset、编辑草稿与人工验收修复过程；空模型目录已不是当前启动状态。 |
| `docs/deep-dive/MANUAL_EXPERT_V2_IMPLEMENTATION.md` | HISTORICAL | [MANUAL_EXPERT_V2_IMPLEMENTATION.md](history/implementation/MANUAL_EXPERT_V2_IMPLEMENTATION.md) | 保留 V2 独立实验、凭据隔离和 UX 实施记录；当前操作见 BUILD_RUN。 |
| `docs/deep-dive/MODEL_ACCESS_THREE_MODE_PLAN.md` | REFERENCE | [MODEL_ACCESS_THREE_MODE_PLAN.md](research/MODEL_ACCESS_THREE_MODE_PLAN.md) | 三模式产品决策仍有价值；V2 DEFERRED 和 R3 未实施属于原设计时点。 |
| `docs/deep-dive/MODEL_SELECTION_UI_THREE_MODE_CLEANUP.md` | HISTORICAL | [MODEL_SELECTION_UI_THREE_MODE_CLEANUP.md](history/implementation/MODEL_SELECTION_UI_THREE_MODE_CLEANUP.md) | 记录早期三模式 UI 收敛；旧 Built-in、V2 待实现描述已被后续替代。 |
| `docs/deep-dive/MULTI_MODEL_PARAMETER_ARCHITECTURE_PLAN.md` | REFERENCE | [MULTI_MODEL_PARAMETER_ARCHITECTURE_PLAN.md](research/MULTI_MODEL_PARAMETER_ARCHITECTURE_PLAN.md) | 保留语义参数、模型能力与 Adapter 的取舍；提案状态不等于当前实施状态。 |
| `docs/deep-dive/POST_R2_STRUCTURAL_AUDIT.md` | HISTORICAL | [POST_R2_STRUCTURAL_AUDIT.md](history/implementation/POST_R2_STRUCTURAL_AUDIT.md) | 保留 R2 阻塞发现、修复和用户验收；当前凭据规则见私有存储指南。 |
| `docs/deep-dive/PRESET_CANCELLATION_MANUAL_IMPLEMENTATION.md` | HISTORICAL | [PRESET_CANCELLATION_MANUAL_IMPLEMENTATION.md](history/implementation/PRESET_CANCELLATION_MANUAL_IMPLEMENTATION.md) | 保留 Stop 后端 I/O 语义和 Manual V1 产品校正；首批旧 Preset 已被 Clean-room 替代。 |
| `docs/deep-dive/PRESET_SIMPLIFICATION_AND_FIRST_PUBLICATION.md` | CURRENT | [PRESET_SIMPLIFICATION_AND_FIRST_PUBLICATION.md](validation/PRESET_SIMPLIFICATION_AND_FIRST_PUBLICATION.md) | 第 12 节登记当前三个固定合同与人工依据；其余章节明确保留历史。 |
| `docs/deep-dive/PROTOCOL_EVIDENCE_PROBE_R3_R4_R5.md` | HISTORICAL | [PROTOCOL_EVIDENCE_PROBE_R3_R4_R5.md](history/implementation/PROTOCOL_EVIDENCE_PROBE_R3_R4_R5.md) | 保留 R3/R4/R5 顺序实施、验收与回归依据；当前边界汇总到架构指南。 |
| `docs/deep-dive/PROVIDER_CREDENTIAL_CAPABILITY_REFACTOR_RESEARCH.md` | REFERENCE | [PROVIDER_CREDENTIAL_CAPABILITY_REFACTOR_RESEARCH.md](research/PROVIDER_CREDENTIAL_CAPABILITY_REFACTOR_RESEARCH.md) | Provider、凭据、协议和证据拆分依据仍有价值；原建议顺序与旧根 .env Writer 不是当前事实。 |
| `docs/deep-dive/PROVIDER_CREDENTIAL_REFACTOR_R0_R1.md` | HISTORICAL | [PROVIDER_CREDENTIAL_REFACTOR_R0_R1.md](history/implementation/PROVIDER_CREDENTIAL_REFACTOR_R0_R1.md) | R0/R1 优先级与兼容测试历史；旧项目根 .env 路径被私有存储替代。 |
| `docs/deep-dive/PROVIDER_CREDENTIAL_REFACTOR_R2.md` | HISTORICAL | [PROVIDER_CREDENTIAL_REFACTOR_R2.md](history/implementation/PROVIDER_CREDENTIAL_REFACTOR_R2.md) | 保留 Writer、Flask 修复、ACL 复审、迁移及用户验收全过程。 |
| `docs/deep-dive/R2_PRIVATE_CREDENTIAL_STORAGE_MIGRATION.md` | CURRENT | [R2_PRIVATE_CREDENTIAL_STORAGE_MIGRATION.md](guides/R2_PRIVATE_CREDENTIAL_STORAGE_MIGRATION.md) | 当前受管私有路径、hot reload、无旧 .env fallback 与安全验收说明。 |
| `docs/deep-dive/R2_WINDOWS_ACL_CREDENTIAL_WRITER_DESIGN_REVIEW.md` | REFERENCE | [R2_WINDOWS_ACL_CREDENTIAL_WRITER_DESIGN_REVIEW.md](research/R2_WINDOWS_ACL_CREDENTIAL_WRITER_DESIGN_REVIEW.md) | 保留父目录 ACL 威胁分析和备选方案；当前已选择私有存储，不是待实施根目录方案。 |
| `docs/deep-dive/V0.1.1_A1_MULTI_MODEL_IMPLEMENTATION_REPORT.md` | HISTORICAL | [V0.1.1_A1_MULTI_MODEL_IMPLEMENTATION_REPORT.md](history/implementation/V0.1.1_A1_MULTI_MODEL_IMPLEMENTATION_REPORT.md) | 初版多模型参数与 Usage 合同的实施和离线验证历史。 |
| `docs/deep-dive/V0.1.1_A2_DEEPSEEK_VALIDATION_REPORT.md` | HISTORICAL | [V0.1.1_A2_DEEPSEEK_VALIDATION_REPORT.md](history/validation/V0.1.1_A2_DEEPSEEK_VALIDATION_REPORT.md) | 保留当时实验 Profile 的有限真实请求与 Token/错误，不作为当前发布能力。 |
| `docs/deep-dive/V0.1.1_A2_1_DEEPSEEK_COMPATIBILITY_AND_NETWORK_DIAGNOSTICS.md` | HISTORICAL | [V0.1.1_A2_1_DEEPSEEK_COMPATIBILITY_AND_NETWORK_DIAGNOSTICS.md](history/validation/V0.1.1_A2_1_DEEPSEEK_COMPATIBILITY_AND_NETWORK_DIAGNOSTICS.md) | 保留 DeepSeek 参数兼容与网络诊断证据，不能把 timeout 推导为不支持。 |
| `docs/deep-dive/V0.1.1_A2_2_QWEN_NETWORK_CONTROL_TEST.md` | HISTORICAL | [V0.1.1_A2_2_QWEN_NETWORK_CONTROL_TEST.md](history/validation/V0.1.1_A2_2_QWEN_NETWORK_CONTROL_TEST.md) | 保留 Qwen/DeepSeek 同条件网络对照，不用于继承高级能力。 |
| `docs/deep-dive/V0.1.1_A3_0_DEVELOPER_WEB_UI.md` | HISTORICAL | [V0.1.1_A3_0_DEVELOPER_WEB_UI.md](history/implementation/V0.1.1_A3_0_DEVELOPER_WEB_UI.md) | 初版 Flask 开发 UI 与 non-streaming 展示记录；默认 Mock 等描述属于当时状态。 |
| `docs/deep-dive/V0.1.1_A3_0_2_GROUNDING_AND_CUSTOM_PROFILE.md` | HISTORICAL | [V0.1.1_A3_0_2_GROUNDING_AND_CUSTOM_PROFILE.md](history/implementation/V0.1.1_A3_0_2_GROUNDING_AND_CUSTOM_PROFILE.md) | 保留检索疾病偏置、事实/背景边界和自定义配置首次实施记录。 |
| `docs/deep-dive/V0.1.1_A3_0_3_UTF8_CUSTOM_PROFILE_QWEN_VALIDATION.md` | HISTORICAL | [V0.1.1_A3_0_3_UTF8_CUSTOM_PROFILE_QWEN_VALIDATION.md](history/implementation/V0.1.1_A3_0_3_UTF8_CUSTOM_PROFILE_QWEN_VALIDATION.md) | 保留 UTF-8 修复与一次 Qwen low_oxygen 人工对照，不扩大成全面安全证明。 |
| `docs/deep-dive/V0.1.1_A3_0_4_CUSTOM_PROFILE_MANAGER.md` | OBSOLETE | [V0.1.1_A3_0_4_CUSTOM_PROFILE_MANAGER.md](history/obsolete/V0.1.1_A3_0_4_CUSTOM_PROFILE_MANAGER.md) | 旧更新/另存副本冲突 UX 已被唯一不可变名称与显式 Edit Draft 取代，仍保留全文。 |
| `docs/deep-dive/V0.1.1_A3_1_APPLICATION_STREAMING.md` | HISTORICAL | [V0.1.1_A3_1_APPLICATION_STREAMING.md](history/implementation/V0.1.1_A3_1_APPLICATION_STREAMING.md) | 保留应用 SSE 首次实现；无取消/无 reasoning 的当时限制已被后续替代。 |
| `docs/deep-dive/V0.1.1_A3_1_1_STREAMING_BUGFIX_PROFILE_COLLISION.md` | OBSOLETE | [V0.1.1_A3_1_1_STREAMING_BUGFIX_PROFILE_COLLISION.md](history/obsolete/V0.1.1_A3_1_1_STREAMING_BUGFIX_PROFILE_COLLISION.md) | 旧 Built-in 冲突对话框策略已移除；Streaming bug 诊断过程保留供回查。 |
| `docs/deep-dive/V0.1.1_A3_1_2_PROFILE_MANAGER_SIMPLIFICATION.md` | HISTORICAL | [V0.1.1_A3_1_2_PROFILE_MANAGER_SIMPLIFICATION.md](history/implementation/V0.1.1_A3_1_2_PROFILE_MANAGER_SIMPLIFICATION.md) | 保留唯一名称与选择同步修复；当前编辑草稿语义由后续 Clean-room 记录补充。 |
| `docs/deep-dive/V0.1.1_A3_1_3_CAPABILITY_IDENTITY.md` | HISTORICAL | [V0.1.1_A3_1_3_CAPABILITY_IDENTITY.md](history/implementation/V0.1.1_A3_1_3_CAPABILITY_IDENTITY.md) | service/model 分离的迁移过程；当前四元 Identity 和 Evidence 合并已演进到 R4。 |
| `docs/deep-dive/V0.1.1_A3_1_4_LOCAL_PROFILE_CAPABILITY_UI.md` | HISTORICAL | [V0.1.1_A3_1_4_LOCAL_PROFILE_CAPABILITY_UI.md](history/implementation/V0.1.1_A3_1_4_LOCAL_PROFILE_CAPABILITY_UI.md) | 本地 Profile 与 Metadata 原实现记录；当前发布合同不继承旧 Built-in。 |
| `docs/deep-dive/V0.1.1_A3_1_5_CAPABILITY_UI_THINKING_PROBE.md` | HISTORICAL | [V0.1.1_A3_1_5_CAPABILITY_UI_THINKING_PROBE.md](history/implementation/V0.1.1_A3_1_5_CAPABILITY_UI_THINKING_PROBE.md) | URL 规范化与 ON/OFF 独立 Probe 首轮实施；当前由 R4/R5 统一。 |
| `docs/deep-dive/V0.1.1_A3_1_6_CAPABILITY_UX_RUNTIME_DEFAULTS.md` | HISTORICAL | [V0.1.1_A3_1_6_CAPABILITY_UX_RUNTIME_DEFAULTS.md](history/implementation/V0.1.1_A3_1_6_CAPABILITY_UX_RUNTIME_DEFAULTS.md) | 偏好与能力分离的历史及测试；即时默认门禁以 Clean-room 后代码为准。 |
| `docs/deep-dive/V0.1.1_A3_2_CLOUD_CAPABILITY_STREAMING_THINKING.md` | HISTORICAL | [V0.1.1_A3_2_CLOUD_CAPABILITY_STREAMING_THINKING.md](history/implementation/V0.1.1_A3_2_CLOUD_CAPABILITY_STREAMING_THINKING.md) | 保留官方研究日期和 Cloud Thinking/组合 Probe 初实现；旧官方声明表已 Reset。 |
| `docs/deep-dive/V0.1.1_A3_2_1_OUTPUT_PARITY_AND_CAPABILITY_UI.md` | HISTORICAL | [V0.1.1_A3_2_1_OUTPUT_PARITY_AND_CAPABILITY_UI.md](history/implementation/V0.1.1_A3_2_1_OUTPUT_PARITY_AND_CAPABILITY_UI.md) | 保留输出 parity、单次 Qwen 对照与开发 UI 改进证据。 |
| `docs/deep-dive/V0.1.1_LOCAL_RUNTIME_VALIDATION.md` | REFERENCE | [V0.1.1_LOCAL_RUNTIME_VALIDATION.md](validation/V0.1.1_LOCAL_RUNTIME_VALIDATION.md) | API/错误/性能验收模板仍可用；尚无应用 Streaming 等初始假设已过时。 |
| `docs/deep-dive/V0.1_HARDENING_REPORT.md` | HISTORICAL | [V0.1_HARDENING_REPORT.md](history/implementation/V0.1_HARDENING_REPORT.md) | 保留 SDK、包资源、Quality/Freshness 加固历史；真实运行待验证是当时状态。 |
| `docs/deep-dive/V0.1_IMPLEMENTATION_REPORT.md` | HISTORICAL | [V0.1_IMPLEMENTATION_REPORT.md](history/implementation/V0.1_IMPLEMENTATION_REPORT.md) | 初始领域合同、规则版本、知识快照与风险记录，不作为当前架构指南。 |

## 当前补充文档

- [架构总览](architecture/CURRENT_ARCHITECTURE.md)：三模式、R2、R3/R4/R5、取消与业务数据边界。
- [水质与 telemetry 准备](research/WATER_QUALITY_SCENARIO_AND_TELEMETRY_PREPARATION.md)：当前数据、规则、测试矩阵与待硬件确认事项。
- [历史索引](history/README.md)：按实施、验证、已替代方案分区。

## 验证与范围

本轮开始于干净的 main 工作树，HEAD 为 `4f3ec4e`（Preset 更新完毕）。未修改程序、脚本、包内 Mock/知识资源、模型能力或 Preset；唯一新增的 Python 文件是 `tests/test_water_quality_matrix.py`。保留整理前根 README / BUILD_RUN 的历史快照，所有旧报告正文仍可查询。

| 检查 | 实际执行与结果 |
| --- | --- |
| 新水质矩阵 | `.venv\Scripts\python.exe -m unittest discover -s tests -p test_water_quality_matrix.py -v`：9 项通过；覆盖 19 个建议 fixture、33 个阈值邻近子用例、质量/时间与独立 Detection。 |
| 基础回归 | `.venv\Scripts\python.exe -m unittest discover -s tests -p test_v01.py -v`：21 项通过，含 Mock、规则、RAG、合同和网络禁止测试。 |
| Markdown | 51 个公开 Markdown（docs 内 47 个），238 个内部链接/锚点检查：0 错误。 |
| 旧路径 | Markdown 非历史映射区域的旧报告引用为 0；src/scripts/tests/根 README/AGENTS 中旧 deep-dive 报告路径引用为 0。审计表原位置列有意保留历史路径。 |
| JavaScript | `node --check src/fishery_ai/resources/web/app.js`：通过；未修改 JavaScript 或 Web 页面。 |
| 差异格式 | `git diff --check` 与 `git diff --cached --check`：通过。Git 的 LF/CRLF 提示不是错误。 |
| 公开文件安全扫描 | 138 个公开文本文件：潜在 Secret 字面量命中 0；被跟踪或未忽略的私有凭据/outputs 文件 0。跳过真实凭据，4 个虚构测试值/符号引用豁免。此扫描不宣称证明不存在所有可能的敏感数据。 |
| Git | 8 个原地修改、35 个迁移（索引 rename + 工作树分类/链接修改）、7 个新增文件/目录状态条目。`git mv` 仅暂存路径迁移；正文修改和新增文件保留工作树供审阅，无 commit/push/tag 变化。 |

合计 30 项 Python targeted tests 通过。按本轮轻量验证要求未运行全量 Python / Browser 回归；没有修改运行逻辑或 UI。没有读取真实 Secret、修改 outputs 或 production Fishery_Project，没有进行联网。Tool Calling、硬件协议 Adapter、历史传感器存储与 Agent 仍未实施。

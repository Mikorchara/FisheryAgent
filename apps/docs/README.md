# 智慧渔业管理平台文档

`apps/docs/` 是管理平台主要入口。已实现统一监测 / Domain Analysis / Events、Normal Assistant 和可显式启用的 Qwen 三工具 Normal/Streaming 本地实验（保留原两工具范围）。管理 AI 依赖为 `management_web → ai_service → ai_backend`；R2C-1 主要迁移及基本真实网页人工验收已完成。旧 `src/fishery_ai/` 保留独立实验 Runtime；MIG-1 已消除 Monitoring 的旧领域依赖，管理知识独立为 apps.knowledge。监测风险规则全部为 PROTOTYPE，未获得生产批准。

## 阅读入口

- [BOT-3G-FINAL 实验性真实QQ Hybrid](deep-dive/BOT3G_FINAL_HYBRID_QQ_TRIAL.md)（独立Prompt/Scope、一次Run审批、General/Water混合记忆；Check离线，Run须操作者单独批准General风险与联网）

- [BOT-3G-C1-D 48题真实Hybrid综合评估](deep-dive/BOT3GC1D_REAL_HYBRID_EVALUATION.md)（84次HTTP/36次Tool；General 0/12、Water 34/36；原文缺失限制、逐题初审与候选对照计划；不开放真实QQ）
- [BOT-3G-C1 本地Hybrid研究实验](deep-dive/BOT3GC1_LOCAL_HYBRID_RESEARCH.md)（48题、分组重复/独立五轮Run、受保护审阅与统计；离线验证，真实Qwen须新审批，不连接QQ）
- [BOT-3G-B Hybrid离线实现](deep-dive/BOT3GB_HYBRID_OFFLINE.md)（General/Water、原Agent、混合RAM历史与Run额度；仅Fake发布，不开放真实General/QQ/Qwen）
- [BOT-3G Hybrid Agent与Prompt设计](deep-dive/research/BOT3G_HYBRID_AGENT_DESIGN.md)（固定指令+其余授权自然语言进入原Agent；Mock已验证，Source/General输出合同待审）
- [BOT-3G Hybrid来源与输出独立合同](deep-dive/research/BOT3G_HYBRID_SOURCE_OUTPUT_CONTRACT.md)（工具可选、一般文本语义风险、1/2请求与混合历史；未开放真实入口）
- [BOT-3G-A 水质意图现状基线](deep-dive/research/BOT3GA_WATER_INTENT_CHAT_DESIGN.md)（36表达/72项投影及原收费差异；关键词扩充路线已由Hybrid设计替代）
- [BOT-3F-C 真实双轮验收与性能复核](deep-dive/BOT3FC_REAL_ACCEPTANCE_PERFORMANCE_REVIEW.md)（两轮交付/历史/SDK通过、正文哈希匹配；客户端约6～7秒，真实HTTP分段证据不足）
- [BOT-3F-B1/B2 聊天展示与 QQ 校验优化](deep-dive/BOT3FB12_CHAT_VALIDATION_OPTIMIZATION.md)（Session 默认 Chat，旧调用保留 A/B/C；词法校验复用与新 Scope，联网另批）
- [BOT-3E-C 真实持续会话装配与简化启动](deep-dive/BOT3EC_REAL_SESSION_ASSEMBLY.md)（独立Scope/类型、一次Run审批、PS显式Session模式；本轮只做Mock验证，联网留3E-D）
- [BOT-3E-B 有界持续会话离线实现](deep-dive/BOT3EB_BOUNDED_SESSION_OFFLINE.md)（新RunConsent、额度日志、跨进程所有权及Fake多轮；真实入口仍禁用）
- [BOT-3E-A 持续会话授权审计与设计](deep-dive/research/BOT3EA_BOUNDED_SESSION_CONSENT_DESIGN.md)（A阶段设计记录；后续B/C实现见上，5轮保守预留仍为8.013825元）
- [BOT-3D-2C-1 逐Turn真实类型装配（离线）](deep-dive/BOT3D2C1_REAL_CONVERSATION_TRIAL.md)（代码与离线证据；用户已反馈C-2真实双轮验收通过，本轮未重读原始私有回执）
- [BOT-3D-2B Mention与有界记忆离线实现](deep-dive/BOT3D2B_MENTION_CONVERSATIONS.md)（Fake阶段记录；服务器快照与交付后记忆，后续真实类型装配见2C-1）
- [BOT-3D-2A Mention与会话记忆设计](deep-dive/research/BOT3D2A_MENTION_CONVERSATION_DESIGN.md)（设计依据；获批的离线2B实现见上，真实逐Turn许可留2C）
- [BOT-3D-1 QQ停止与报告缺失修复](deep-dive/BOT3D1_RESULT_REPORTING.md)（Ctrl+C路径、提前保存交付快照、核实result文件；用户客户端确认与程序状态分开，不重跑历史实验）
- [BOT-3D-1 受限解释与可信展示](deep-dive/BOT3D1_BOUNDED_EXPLANATION.md)（模型选择要点、程序核对同轮来源并生成中文；原始正文不展示，新Scope需重新审批）
- [BOT-CLEANUP-1 草稿清理与验证](deep-dive/BOT_CLEANUP1_SDK_DRAFT_REMOVAL.md)（移除4份暂停源码和6项专用测试；保留资源门禁，两个Scope不变）
- [BOT-REGRESSION-1 FAST 稳定性修复](deep-dive/BOT_REGRESSION1_FAST_STABILITY.md)（5s夹具/断言误入重连、同次Scope构建3→1；保留90s预算与权限时间边界，新Scope需重新审批）
- [BOT 当前阶段总结](deep-dive/BOT_STAGE_SUMMARY.md)（FAST历史真实验收与本轮受限解释分开；普通QQ CLI仍禁用AI）
- [BOT Web 影响与清理审计](deep-dive/research/BOT_WEB_IMPACT_AUDIT.md)（共享 SDK 行为变化、兼容性证据、暂停草稿与后续同步边界）
- [QQ / Qwen 简化验收入口](deep-dive/BOT_TEST_WORKFLOW.md)（PowerShell 7；默认不联网，原审批和单次消费保留）
- [BOT-3C-FAST Qwen单轮试用准备](deep-dive/BOT3C_FAST_QWEN_TRIAL.md)（阶段实施记录与原 CLI；当前验收状态见上方总结）
- [BOT-3C-2B 历史设计与暂停记录](deep-dive/BOT3C2B_SDK_PROCESS_ISOLATION.md)（草稿及专用测试已在 BOT-CLEANUP-1 删除，非可运行模块；2A 门禁保留）
- [BOT-3C-2A SDK资源门禁与取消](deep-dive/BOT3C2A_SDK_RESOURCE_GATE.md)（租约、失败隔离、Commit/交付保护；硬退出仍需进程隔离，真实AI仍关闭）
- [BOT-3C-1 真实 AI 联调前置准备](deep-dive/BOT3C1_REAL_AI_PREPARATION.md)（独立candidate、统一回复离线装配、真实SDK内存HTTP验证；真实AI仍关闭）
- [BOT-3B-2 有界 AI 调度与单次交付](deep-dive/BOT3B2_QQ_AI_SCHEDULING.md)（仅 Fake：1执行/2等待、取消、交付未知不重试；真实 QQ AI 仍关闭）
- [BOT-3B-1 QQ AI 服务边界与权限装配](deep-dive/BOT3B1_QQ_AI_BOUNDARY.md)（Monitoring-only、渠道权限、同轮来源摘要、Fake candidate；真实 QQ AI 仍关闭）

- [BOT-3A QQ 与 AI Service 集成架构调查](deep-dive/research/BOT3A_QQ_AI_SERVICE_INTEGRATION.md)（历史设计依据；BOT-3B/FAST 的后续实现见当前总结）

- [BOT-2B 指定 Monitoring 实例只读查询](deep-dive/BOT2B_MONITORING_READ_ONLY.md)（显式配置、SQLite 防写与设备隔离；用户已报告 BOT-2C 测试群当前/历史/异常查询通过，AI/Knowledge 仍禁用）

- [BOT-1B QQ 官方通信联调](deep-dive/BOT1B_QQ_TRANSPORT.md)（用户已完成基本测试群验收；长断网恢复及未授权成员拒绝仍待补充，未同步 Management）

- [BOT-1A QQ Bot 离线原型与移植记录](deep-dive/BOT1A_OFFLINE_PROTOTYPE.md)（从 Management 保留成果移植；后续 BOT-1B/BOT-1C 先在 Prototype 开发，验收提交后再选择性同步）

- [SIMPLIFY-1 风险周期列表](deep-dive/EVENT_CYCLE_UI.md)（Prototype 待验收；服务端整合、原始详情、保留 ACK 审计保护）
- [事件管理现状与简化方案](deep-dive/research/EVENT_MANAGEMENT_SIMPLIFICATION.md)（讨论稿：为什么已恢复仍删不掉、一周期一行、归档与永久删除的取舍；未实施）
- EVT-3A 旧 `EVENT_ACK.md` 已不在仓库；当前行为见 [事件管理](deep-dive/EVENT_MANAGEMENT.md)，显式维护入口为 [Monitoring 迁移工具](../monitoring/migrate.py)。
- [目录与职责](STRUCTURE.md)
- [MIG-2 独立发行与数据实例](deep-dive/MANAGEMENT_STANDALONE.md)（独立 Wheel、显式数据根/初始化、隔离测试与 MIG-3 清单）
- [R2D-2A 产品整理与验收](deep-dive/R2D2A_PRODUCT_INTEGRATION.md)（并发小修、一行启动、全屏/阅读、三工具候选）
- [R2D-2B 三工具本地开放与操作栏修复](deep-dive/R2D2B_UNIFIED_TOOLS.md)（Qwen OFF、独立Normal/Streaming、权限求交、非released）
- [AI Backend 与 Assistant 开发指南](deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)（请求链、Tool/Prompt 扩展、Scope 与测试清单）
- [启动、模拟器与验证](BUILD_RUN.md)
- [系统设置与 API 密钥操作](BUILD_RUN.md#r2d-4a系统设置中心)（默认偏好、私有凭据、真实预算展示与限制）
- [连接测试与可调输出预算](BUILD_RUN.md#r2d-4b连接测试与可调输出预算)（先测试后保存、Qwen 双模式 1–4096 本地范围）
- [上报 DTO、存储和集成边界](INTEGRATION.md)
- [EVT-1 视觉事件恢复与首页异常概况](deep-dive/EVENT_LIFECYCLE.md)（Prototype 实验，连续三个可靠 CLEAR，待人工验收）
- [EVT-2 等级关联、时间筛选与历史清理](deep-dive/EVENT_MANAGEMENT.md)（Prototype 实验，服务端分页、受控硬删除，待人工验收）
- [路线](ROADMAP.md)
- [开发规则](../AGENTS.md)
- [R2B 架构评估基线](deep-dive/research/R2B_DOMAIN_ANALYSIS_AND_AI_INTEGRATION.md)（R2B-0 研究；当前实现以 INTEGRATION 为准）
- [管理 Streaming 设计与实施状态](deep-dive/research/R2B5_MANAGEMENT_ASSISTANT_STREAMING_INTEGRATION.md)（默认关闭；Qwen 两工具可显式启用本地实验）
- [管理历史Tool资格与试用](deep-dive/HISTORY_QUALIFICATION.md)（三个案例各5个真实样本技术通过；Qwen Normal单工具local_experimental、默认关闭）
- [历史 Tool 工程成本审计](deep-dive/research/R2D1F_TOOL_INTEGRATION_COST_AUDIT.md)（实际文件/行数、可简化点与固定15样本准备）
- [R2D-1 最终工程复盘](deep-dive/research/R2D1_TOOL_RETROSPECTIVE_AUDIT.md)（最终提交成本、代码风险、保留建议及简单Tool流程）
- [人工真实连接测试](../../scripts/manual_real_tests/README.md)（用户手动执行，默认Dry-run；自动离线与回答质量分开）
- [管理 Streaming 逐案例资格与试用流程](deep-dive/STREAMING_QUALIFICATION.md)（三个真实技术 PASS，回答质量待审；local_experimental 非正式发布）
- [R2B-3 架构与 Tool 故障审查](deep-dive/research/R2B3_MANAGEMENT_AI_ARCHITECTURE_REVIEW.md)（只读证据、修复建议与后续顺序）
- [独立 Backend 迁移方案、实施与人工验收](deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md#15-r2c-1e-工程收尾与人工验收)
- [R2C-1A LLM Backend 审计](deep-dive/research/R2C1A_LLM_BACKEND_AUDIT.md)（实际依赖、最小迁移、资格保护和后续次序）

根 [docs](../../docs/STRUCTURE.md) 维护旧 AI Prototype 实验平台；管理独立 Backend 的当前说明以本目录和源码 README 为准，两侧不要求持续同步。事实优先级：源码 → 测试 → 当前文档 → 历史记录。

R2C-1E 收尾：管理 Service/Web/SSE/资格入口统一使用 [独立 Backend](../ai_backend/README.md) 与 [业务 Runtime](../ai_service/runtime/README.md)，无新旧 selector/fallback 或重复装配。正式 Wheel 与离线差分已在 Phase II 通过；用户随后报告 Qwen Normal 水质查询、Streaming 水质 + Knowledge、Final 和来源标签正常。基本人工观察不等于正式资格或完整回答质量审核；Prompt/Schema/Scope/预算/默认开关不变，新资格计划 @2 仍需逐案例新确认。

R2B-3.4：AI 业务已独立为 `apps/ai_service/`，Web 经明确的 AssistantBackend 合同调用。Monitoring、Knowledge 绑定及 Runtime 装配不再依附 Web；HTTP/浏览器/请求控制留在管理网页，当前能力与启动方式不变，见 [模块边界](INTEGRATION.md#r2b-34独立-ai-业务边界)。

## 当前状态

R2D-3B：[统一知识库](deep-dive/KNOWLEDGE_CONTENT.md)使用单一SQLite权威文本源，导入内置/用户内容均可管理；提供显式备份迁移、Markdown/JSON导出与独立的原TF-IDF检索。实际旧用户库迁移待批准，不自动覆盖。

| 模块 | 已实现 | 尚未接入 |
|---|---|---|
| 综合总览 | 统一存储的指标/历史、视觉通道状态、最近五条事件 | 真实系统/设备 |
| 水质监测 | 窗口事实、样本覆盖、历史、PROTOTYPE 规则及明确无法判断状态 | 真实传感器、批准生产规则 |
| 视频监控 | 视觉窗口汇总、行为比例、疑似异常、标定状态 | 视频流、真实 NPU、截图/片段 |
| 事件记录 | 模拟异常事件、去重、可靠恢复/待确认、真实严重程度及规则身份 | 人工处置/通知工作流 |
| AI 助手 | Qwen/Ollama Normal、统一水质/Knowledge、可选本地多轮；Qwen 两工具 Streaming 显式本地实验；独立 Backend 基本网页验收通过 | 回答质量专项审核、其他 Streaming 范围、评分/视觉 Tool |
| 资料与知识库 | 内置/用户知识列表、录入编辑、停用/软删除恢复、来源版本、原 TF-IDF 检索测试及 AI 桥接 | 文件导入上传、检索技术参数、生产账户权限 |
| 设置 | 分类、管理 Assistant 独立 Tool 授权与并发安全保存、独立开发入口 | 账户权限、生产配置 |

Flask + 原生 ES Modules / CSS / SVG，无新依赖。默认 8766，读取 SQLite 模拟上报或明确 NO_DATA。页面每 5 秒查询，模拟器默认每 10 秒上报。AI 默认关闭，--enable-assistant 后逐次确认才执行 Normal；生产认证、真实设备与设备写控制未开放。

## 验证基线

R1：9 Python + 8 Node；原 Prototype 相关 64 Python + 219 Browser。七页在 1440 / 1024 / 390px 下完成布局检查。

R2A：监测 23、模拟器 12、管理 API 11 项 Python，前端 14 项 Node；真实本机默认周期联调三批，接收间隔 10.00 / 10.00 秒。模拟器停止后页面明确显示过期/中断；七页 390px 无页面级横向溢出，浏览器无错误。原 Prototype FAST 149、FULL PRODUCT 1047、Browser 219 通过。当前具体测试命令见 [BUILD_RUN](BUILD_RUN.md#验证)。

R2A.1：按有效检测记录加权体长、有效帧可见数均值（含零鱼帧）、逐样本/逐帧质量过滤、阻塞跳过窗口，以及北京时间到秒显示。监测 26、模拟器 17、管理 API 11 项 Python 和前端 16 项 Node 通过；前端涵盖实际页面代码、统一时间显示及不同主机时区转换。本轮未重复运行原 AI Runtime 全量回归，未调用真实 Provider/NPU。统计合同见 [INTEGRATION](INTEGRATION.md#3-窗口与业务语义)。

R2B-1：新增 18 项规则治理测试及 1 项前端状态测试；监测 44、模拟器 17、管理 API 11 项 Python，前端 17 项 Node。覆盖无效/部分/无数据、过期/离线、缺失不恢复、严重程度切换不恢复、规则/评估策略版本、旧库兼容和独立通道。当前仍未提取完整 DomainAnalysisService / EventService，也未接 AI。联调时间边界及当前保守覆盖策略见 [INTEGRATION](INTEGRATION.md#r2b-1-分析合同与规则状态)。

R2B-2：新增 7 项业务服务和 3 项调度测试；监测 51、模拟器 20、管理 API 11 项 Python，前端 17 项 Node 通过。默认周期本机隔离联调两批（零人为缓冲），窗口均为 10 秒，接收间隔 10.003 秒，最小接收后于观测 0.054164 秒；这是本轮样本，不代表长期时钟稳定性。旧一秒缓冲已从联调测试移除，提前 UTC 发送问题通过有界完成检查修正。未运行 Provider/NPU 或原 AI Runtime 无关全量回归。

R2B-3：新增管理 Assistant 17 项 Python 与 8 项前端行为测试；管理测试合计 28 Python / 25 Node、Monitoring 51、Simulator 20 通过。原 Runtime Assistant 140、Tool 296、FAST 149、原 Web Browser 219 通过；仅离线 Fake Provider 与临时本机浏览器联调，不调用真实模型/NPU，不将结果视为真实回答质量验收。

R2B-4：Normal 多轮已完成离线集成。Qwen/Ollama 独立 local_experimental Scope、默认关闭；不复制 Runtime 循环，不继承真实资格。参见 [启用与回滚](BUILD_RUN.md#r2b-4normal-multi-round-本地试用) 和 [执行边界](INTEGRATION.md#r2b-4管理独立-normal-多轮执行范围)。

R2B-4 离线验证：AI Service 11、管理 Web Python 64、Monitoring 相关 37、原 Runtime Assistant 140、Tool 相关 95、原 Web Assistant 52、Analysis/普通 Streaming 39、管理前端 Node 29 全部通过；Python/JS/JSON 语法、本地 Markdown 链接和 diff 检查通过，改动文件敏感模式扫描未发现命中。未请求真实 Provider/Ollama，未修改核心 Runtime 或用户 Policy。


R2B-5B 后端离线结果：新增 Streaming/配置专项 25 项通过（23 项管理 HTTP/SSE、2 项配置）；既有管理 Python 64 项、AI Service 13 项（含上述配置测试）、核心 Assembler/Streaming 多轮/Prototype SSE 96 项及管理 Node 36 项相关回归通过。Python/JSON 语法、98 条 Markdown 本地文件链接、diff/空白检查与敏感模式扫描通过。未改前端、核心 Runtime 或真实资格；未执行 Provider/NPU。后端已完成而 Final 投递失败时不重写完成 Trace，也不替客户端恢复 History。

R2B-5C：已增加默认 Normal 的双模式选择、安全 SSE parser、原消息内预览转 Final、失败撤销、滚动跟随/暂停与问题导航。管理 Node 51、管理 Web Python 88、AI Service 13、相关核心 Streaming/来源回归 154 项通过；真实管理 HTTP 的三条 Fake SDK 路径进入正式前端 parser/会话，均只提交一条最终回答。隔离本机浏览器双 Tool 完成，1280/390px 无横向溢出。没有调用真实 Provider/NPU、改核心 Runtime 或打开 candidate；[运行与验收](BUILD_RUN.md#r2b-5c聊天前端离线验收)。

以上各 R 阶段数字与描述保留其当时基线；独立 Backend 的最终离线结果和用户基本人工验收分别见 [迁移记录 §14 / §15](deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md#15-r2c-1e-工程收尾与人工验收)。

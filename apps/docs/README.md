# 智慧渔业管理平台文档

`apps/docs/` 是管理平台主要入口。已实现统一监测 / Domain Analysis / Events、Normal Assistant 和可显式启用的 Qwen 两工具 Streaming 本地实验。管理 AI 依赖为 `management_web → ai_service → ai_backend`；R2C-1 主要迁移及基本真实网页人工验收已完成。旧 `src/fishery_ai/` 保留独立实验 Runtime；Monitoring/Knowledge 暂留的旧领域依赖另行处理。监测风险规则全部为 PROTOTYPE，未获得生产批准。

## 阅读入口

- [目录与职责](STRUCTURE.md)
- [AI Backend 与 Assistant 开发指南](AI_BACKEND_DEVELOPMENT_GUIDE.md)（请求链、Tool/Prompt 扩展、Scope 与测试清单）
- [启动、模拟器与验证](BUILD_RUN.md)
- [上报 DTO、存储和集成边界](INTEGRATION.md)
- [路线](ROADMAP.md)
- [开发规则](../AGENTS.md)
- [R2B 架构评估基线](deep-dive/research/R2B_DOMAIN_ANALYSIS_AND_AI_INTEGRATION.md)（R2B-0 研究；当前实现以 INTEGRATION 为准）
- [管理 Streaming 设计与实施状态](deep-dive/research/R2B5_MANAGEMENT_ASSISTANT_STREAMING_INTEGRATION.md)（默认关闭；Qwen 两工具可显式启用本地实验）
- [管理 Streaming 逐案例资格与试用流程](deep-dive/STREAMING_QUALIFICATION.md)（三个真实技术 PASS，回答质量待审；local_experimental 非正式发布）
- [R2B-3 架构与 Tool 故障审查](deep-dive/research/R2B3_MANAGEMENT_AI_ARCHITECTURE_REVIEW.md)（只读证据、修复建议与后续顺序）
- [独立 Backend 迁移方案、实施与人工验收](deep-dive/research/R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md#15-r2c-1e-工程收尾与人工验收)
- [R2C-1A LLM Backend 审计](deep-dive/research/R2C1A_LLM_BACKEND_AUDIT.md)（实际依赖、最小迁移、资格保护和后续次序）

根 [docs](../../docs/STRUCTURE.md) 维护旧 AI Prototype 实验平台；管理独立 Backend 的当前说明以本目录和源码 README 为准，两侧不要求持续同步。事实优先级：源码 → 测试 → 当前文档 → 历史记录。

R2C-1E 收尾：管理 Service/Web/SSE/资格入口统一使用 [独立 Backend](../ai_backend/README.md) 与 [业务 Runtime](../ai_service/runtime/README.md)，无新旧 selector/fallback 或重复装配。正式 Wheel 与离线差分已在 Phase II 通过；用户随后报告 Qwen Normal 水质查询、Streaming 水质 + Knowledge、Final 和来源标签正常。基本人工观察不等于正式资格或完整回答质量审核；Prompt/Schema/Scope/预算/默认开关不变，新资格计划 @2 仍需逐案例新确认。

R2B-3.4：AI 业务已独立为 `apps/ai_service/`，Web 经明确的 AssistantBackend 合同调用。Monitoring、Knowledge 绑定及 Runtime 装配不再依附 Web；HTTP/浏览器/请求控制留在管理网页，当前能力与启动方式不变，见 [模块边界](INTEGRATION.md#r2b-34独立-ai-业务边界)。

## 当前状态

| 模块 | 已实现 | 尚未接入 |
|---|---|---|
| 综合总览 | 统一存储的指标/历史、视觉通道状态、最近五条事件 | 真实系统/设备 |
| 水质监测 | 窗口事实、样本覆盖、历史、PROTOTYPE 规则及明确无法判断状态 | 真实传感器、批准生产规则 |
| 视频监控 | 视觉窗口汇总、行为比例、疑似异常、标定状态 | 视频流、真实 NPU、截图/片段 |
| 事件记录 | 模拟异常事件、去重、可靠恢复/待确认、真实严重程度及规则身份 | 人工处置/通知工作流 |
| AI 助手 | Qwen/Ollama Normal、统一水质/Knowledge、可选本地多轮；Qwen 两工具 Streaming 显式本地实验；独立 Backend 基本网页验收通过 | 回答质量专项审核、其他 Streaming 范围、评分/视觉 Tool |
| 资料与知识库 | Demo 元数据与分类/详情 | 文件上传下载、索引、检索桥接 |
| 设置 | 分类、禁用操作、独立开发入口 | 账户权限、生产配置 |

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

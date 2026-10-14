# 智慧渔业管理平台文档

`apps/docs/` 是新管理平台的主要架构与开发入口。当前应用是 `apps/management_web/` 的独立 R1 网页；AI Runtime 仍在 `src/fishery_ai/`，原 Prototype Web 保留。

## 阅读入口

- [目录与模块职责](STRUCTURE.md)：真实目录及后续最小拆分方向。
- [启动与验证](BUILD_RUN.md)：本机运行、离线测试和页面验收。
- [服务合同与集成](INTEGRATION.md)：Monitoring、AI、Video/NPU、Events、Knowledge/RAG 的替换边界。
- [开发路线](ROADMAP.md)：已实现状态与尚未实施的计划。
- [开发规则](../AGENTS.md)：本目录开发约束。

根 [docs](../../docs/STRUCTURE.md) 继续维护 AI 原型和共享 Runtime 文档；这里不重复 Provider、Prompt、Tool、Credential 的内部合同。事实优先级：当前源码 → 当前测试 → 当前文档 → 历史记录。

## 当前状态：R1 展示应用

| 模块 | 已实现 | 尚未接入 |
|---|---|---|
| 综合总览 | 指标、趋势、演示事件、模块入口与连接状态卡片 | 真实系统统计与实时连接探测 |
| 水质监测 | 两个 Demo 区域、指标/趋势、质量和新鲜度视图 | 传感器、监测数据库、正式 Snapshot |
| AI 智能助手 | 页面容器、建议问题、Session 草稿 | 模型发送、History、Stop、Streaming、Tool Activity |
| 视频监控 | 设备选择与明确的空状态 | 实时视频、NPU、检测结果 |
| 事件记录 | 三条 Demo 记录、筛选和详情 | 持久化、告警与处理工作流、实际附件 |
| 资料与知识库 | Demo 文件元数据、分类搜索和详情 | 上传下载、索引、检索桥接 |
| 系统设置 | 配置分类、禁用操作与独立开发入口 | 用户认证、权限、配置写入 |

Flask + 原生 ES Modules / CSS / SVG，复用现有依赖，无前端构建步骤。默认只监听 `127.0.0.1:8766`；原 Prototype 默认 8765。无数据库、后台采集、管理写 API 或真实模型请求。AI 消息端点固定返回 503，注入 AI 服务对象不会自动开放执行。

## 已有验证基线

R1 实施时：管理应用 9 项 Python、8 项 Node 测试通过；原 Prototype 相关 64 项 Python、219 项 Browser 回归通过。实际浏览器检查七页、筛选/详情、草稿与禁用操作，在 1440 / 1024 / 390px 下无页面级横向溢出，修正一处初始语法错误后 Console 无错误。截图位于 Git ignored 的 `outputs/management_web/`。

这些是 R1 的既有验收记录，不是 R1.1 文档整理重新执行的测试。后续行为变更按 [验证要求](BUILD_RUN.md#验证要求) 更新结果。

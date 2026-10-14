# 管理平台路线

本页描述管理平台；共享 AI Runtime 的现状见根 [路线图](../../docs/ROADMAP.md)。计划不表示已授权执行或已接入真实服务。

## 已实现

- **R1**：独立 Flask 应用、8766 本机入口、统一布局及七页面；独立 Demo、空状态、读 API、可注入服务接口与离线测试。AI、视频/NPU、数据库、权限和管理写操作未接入。
- **R1.1**：`apps/AGENTS.md` 与 `apps/docs/`；明确模块职责、共享监测来源与后续替换边界。未修改 R1 UI 或运行行为。

## 下一步：R2 AI 集成（未实施）

1. **最小准备**：补消费端 DTO 校验和来源/连接状态；提取 Assistant 页面独立 Session，定义薄 Runtime Adapter。
2. **Normal 闭环**：复用已有 AssistantService，实现安全发送、最终回答、History、联网确认、Stop、epoch 与错误；先 Fake / Scripted Provider 离线验收。
3. **系统事实接入**：明确管理网页与现有 Tool 共用的权威监测来源和设备上下文；验证 NO_DATA / PARTIAL / INVALID / STALE，不以 Demo 或旧值补事实。
4. **逐项增强**：按精确发布 Scope 接入既有 Multi-Round、Activity 与 Streaming。预算、确认 revision、Ledger 和 Commit Gate 不变；真实验收需本轮明确授权。

不同时重构全部页面、后端和 AI Runtime；未建立共享来源时不宣称 Tool 已读取管理水质。详细边界见 [INTEGRATION](INTEGRATION.md)。

## 后续独立工作（尚未实施）

- **Monitoring**：传感器/数据库 Adapter、规范化观测、质量/新鲜度与受控历史查询。
- **Video/NPU**：设备通信与视频传输、检测事实 DTO、受控媒体访问；网页不绑定硬件推理框架。
- **Events**：存储、确定性告警与处理流程、附件关联；先明确事件合同再选持久化。
- **Knowledge/Files**：文件管理、索引与检索分别接入；RAG 改善单独设计和验收，不作为 R1/R2 隐含任务。
- **Settings/Security**：用户认证、服务端授权、管理员配置与开发调试分离；此前相关写操作保持关闭。

不预先创建空模块或选择正式数据库，不承诺未验证的设备、模型能力。Agent、自动设备控制、阈值修改和复杂调度不属于当前管理平台阶段。

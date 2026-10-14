# 管理平台路线

共享 AI Runtime 现状见根 [路线图](../../docs/ROADMAP.md)。规划不表示已授权真实服务接入。

## 已实现

- R1：独立管理布局、七业务页面、Demo/空状态、只读应用 API 和测试。
- R1.1：工程规则与管理平台文档入口。
- R2A：独立连续模拟器、v1 HTTP 上报校验、本机写入门禁、SQLite 当前状态/有界历史、服务器领域诊断、模拟事件去重、四页面统一读取与轮询、设备绑定 Reader。没有 AI 对话或真实设备/NPU。
- R2A.1：精确窗口统计、检测记录加权体长、逐样本质量、阻塞跳窗、北京时间到秒。
- R2B-1：统一通道分析合同、PROTOTYPE 规则身份、每指标证据门禁、ACTIVE/RESOLVED/INDETERMINATE、事件等级/版本/旧库兼容；没有 AI 接入。

## 下一步：R2B-2 共享分析与事件服务（未实施）

先围绕现有 rules 纯函数和事务事件转换提取最小 DomainAnalysisService / EventService；不复制阈值、不替换 SQLite。统一页面与未来 Tool 的分析投影，必要时增加跨通道联合捕获但保留时间差异。规则适用性/覆盖门槛和恢复依据需人工确认，暂不发布生产规则。参见 [R2B-0 评估](deep-dive/research/R2B_DOMAIN_ANALYSIS_AND_AI_INTEGRATION.md)与[当前合同](INTEGRATION.md#r2b-1-分析合同与规则状态)。

## 后续：AI 应用桥接（未实施）

1. 提取独立 Assistant 页面 Session，建立薄 AI Adapter；不复制现有 Runtime。
2. 先离线接通 Normal、最终正文、History、epoch、联网确认、Stop 和错误。
3. 将 Tool 明确绑定 R2A 的同一 MonitoringService / repository 与冻结设备上下文。原 Prototype 的内存 Snapshot **尚未**切换到此数据库，不能假定已共享。
4. 按已有精确 Scope 接入 Multi-Round / Streaming、Activity、Ledger 和 Commit Gate；真实请求需本轮单独授权。

## 后续独立工作

- 真实 Monitoring：设备登记/认证、物理采集 Adapter、持久历史与运维策略；不由客户端自报真实来源。
- Video/NPU：实际视频传输、校准、推理结果归一化、受控截图/片段；不迁移旧 GPU 桌面项目。
- Events：生产告警策略、通知、人工处理和审计；当前 closed 只表示模拟信号消退。
- Knowledge/Files：文件管理、索引与检索分别接入，RAG 改善单独设计。
- Security：账户、服务端权限、生产设备凭据、TLS、限流、监控/备份和迁移；开发令牌不能当作生产方案。

不增加 Agent、自动设备写操作或通用场景编辑器，不为规划建立空模块。

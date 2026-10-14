# 服务合同与集成边界

本文描述 R1 当前接口和未来接入要求。真实监测、AI、视频/NPU、持久化及新 RAG **尚未接入**；本轮未改变运行行为。

## 1. 当前装配与 API

`management_web.app.create_app` 接收 `monitoring / ai / video / files / events`，缺省使用独立 Demo 和 UnavailableAI。接口定义在 `contracts.py`；页面只访问同源应用 API。

| 服务 | 当前合同 | 当前实现 | 替换职责 |
|---|---|---|---|
| MonitoringData | `devices()`、`snapshot(device_id, view)` | DemoMonitoring | 规范化观测、单位、来源、质量和时间 |
| AIService | `availability()`、`send(request)` | UnavailableAI | 桥接已有 AI 应用服务，不复制执行栈 |
| VideoDetection | `cameras()` | DemoVideo | 设备/媒体连接与规范化检测事实 |
| EventRecords | `events()` | DemoEvents | 事件查询与存储，工作流另行设计 |
| KnowledgeFiles | `files()` | DemoFiles | 文件元数据；索引与检索分别接入 |

`MetricObservation` 包含 id、label、value、unit、quality、source、observed_at、freshness。`MonitoringSnapshot` 包含 device_id、source/source_kind、observed_at、evaluated_at、quality/freshness、metrics、trend。值可为 None；禁止补默认正常值或把缺失当零。

当前 HTTP：Bootstrap、监测、事件/文件列表及详情、AI 可用性均为 GET；`POST /api/ai/messages` 始终 503。Bootstrap `schema_version=1`。服务注入不等于完整集成：data_mode、连接列表、事件/文件 source_kind 仍固定 Demo；部分 UI 文案和统计也固定。其余 DTO 多为 dict，尚缺完整嵌套校验。

R2 应为实际消费者补必要字段、枚举与安全错误合同；不把 Provider 响应或设备 raw packet 当 DTO 直接透传。新增或不兼容字段须明确版本和兼容方案。

## 2. Monitoring：网页与 Tool 共享事实

推荐链路（规划）：

```text
Demo / DB / Device Adapter
    → canonical WaterQualityReading
    → 一个权威当前观测来源
        → CurrentWaterQualityReader → 管理页面 DTO
        → CurrentWaterQualityReader → 现有只读 Tool → Diagnosis / Score
```

当前管理 Demo 与正式 Tool 的 Snapshot 完全隔离，页面选择不会写入正式 Store。接入前先决定权威来源：

- **同进程**：composition root 装配同一个 CurrentSnapshotStore / Reader，分别注入网页服务和 Tool Runtime。
- **跨进程**：8765 与 8766 的内存不共享。需要共同的受控读服务或数据库来源，以及一致的观测 ID、时间和版本；不能靠导入同一 Python 类获得同一 Snapshot，也不能各自生成一份 current state。

复用 `fishery_ai.telemetry.current.CurrentWaterQualityReader` 和 Domain 的 query-time freshness；查询不重新采样，不改 Store 原对象。管理 Demo 的 600 秒示例不能作为生产规则。Diagnosis / Score 由现有领域服务生成，Adapter 和前端不复制阈值。

未来多池/设备须显式绑定授权的 site/device 上下文。当前水质 Tool 无参数、绑定一个 Reader；不能用网页可变全局设备选择偷偷改变正在进行的 AI Turn。接入需明确请求开始时冻结的数据上下文和选择权限。

观测时间、查询评估时间与来源分别保留。NO_DATA 与已有 Snapshot 的 PARTIAL / INVALID / STALE 分开；不以背景知识、旧 History 或 UI Demo 代替当前事实。Tool 查询时取得的观测可能晚于页面展示或 Analysis 初始 Facts，应保留各自时间/来源，不合并成一次观测。

## 3. AI：薄应用桥接

管理 AI Adapter 调用现有 AssistantService / ToolCallingService / Gateway。连接、Preset、正式 Credential composition、RuntimeSnapshot、RequestHandle、Policy、发布 Scope、Ledger 和 Commit Gate 留在 `src/fishery_ai/`。管理页面不接触 SDK、Prompt、Secret 或任意 Provider 配置。

建议先接 Normal 的最小对话闭环，再按已有精确资格逐项接多轮/Streaming；不因技术 PASS 或管理应用接入而扩大 Preset 发布范围。复用 epoch、execution profile revision、逐次联网确认、整 Turn deadline 和 Stop；浏览器确认与实际预算绑定，配置变化必须重新确认。

前端只接最终安全正文、Activity/Steps、Usage、延迟和安全错误。临时流式预览不是成功回答，失败或取消不能写 History。History 仍只保存成功 user/final assistant 文本对，复用正式 Projection，不保存 Tool raw payload 或 reasoning。

`AIService.send(dict)` 目前只是预留接口；没有 chat、cancel、状态轮询或 SSE 的管理端实现。R2 需按实际复用服务定义最小请求/结果合同，不能把“解除固定 503”视为已完成集成。若首次接入尚无共享监测来源，必须明确 Tool 读哪个来源，不能声称已读取管理 Demo。

## 4. Video / NPU 与 Events

```text
设备通信 / 视频传输 → 受控媒体引用 → 网页播放
NPU 推理 → 规范化检测事实 → 页面 / 事件服务
```

传输、推理与展示分别替换；不要迁移桌面 GPU 监测器或在页面绑定特定推理框架。未来检测 DTO 至少明确设备、观测时间、模型/部署版本、类别、置信度和坐标约定；模型结果不是传感器事实或诊断结论。R1 摄像头只有元数据，无 stream_url、真实检测或假识别框。

事件服务区分事件产生、查询、附件和处理工作流。R1 三条记录及处理状态都是样例，不会触发告警或写存储。未来确定性告警规则在业务/领域服务中实现，页面不再计算 Finding。截图/片段使用受控 ID 与授权访问，不把任意本地路径、URL 或设备控制入口暴露给模型或浏览器。

## 5. Knowledge / Files / RAG

文件元数据和实际文件存储、索引状态与任务、检索服务是三个边界。当前两条 Demo 元数据没有真实文件、下载或索引。新增文件管理不能隐式等同于已可检索，也不能由浏览器声明索引成功。

未来薄 Adapter 可复用现有知识检索，替换 RAG 时保持应用侧查询/证据合同；本阶段不开发新 RAG。Knowledge Evidence 是项目背景，不能认证当前水质或现场疾病。Analysis 自动 RAG 与 Assistant 按 Policy 调用 Knowledge Tool 的边界保持不变，避免同一证据多来源混淆。

## 6. 安全与生命周期

当前有 loopback、Host/Origin 限制、无 CORS、CSP、textContent、8 KiB 请求上限、通用错误与禁用写 API；这些不是用户身份、权限或完整 CSRF 方案。认证、授权、文件访问及审计未实现，不可生产部署。

开放 AI 执行或任何写操作前补相应服务端检查，管理员能力与开发验证分开。沿用私有凭据和 CredentialSnapshot，禁止根 `.env`、复制 Key、浏览器存 Key、日志/错误回显私有路径与 traceback。真实请求须单独授权。

当前 Demo 随应用重建，AI 草稿仅页面内存，刷新清空。未来应用服务按明确生命周期装配；观测、请求状态与 UI Session 分开。适配器失败需安全报告不可用，禁止自动回退 Demo、Normal 重跑或 Provider failover。

## 7. R2 前最值得做的最小调整（未实施）

1. 为实际接入字段补 DTO 校验；使 source_kind、data_mode、连接状态和页面标识来自真实服务，移除相关固定 Demo 假设。
2. 提取 Assistant 页面独立 state/模块，保留其他六页；增加薄 AI Adapter，不拆整个产品 Runtime。
3. 明确共享监测来源与 site/device 绑定后，再开放当前水质 Tool；用离线测试证明 UI 与 Tool 看到同一权威来源且旧请求不被新选择污染。
4. 接通服务端确认/发布门禁、epoch、取消及安全错误，再开放发送。先离线验证最小 Normal 路径，Streaming 和多轮分步接入。

相关底层合同以根 [Analysis / Assistant 架构](../../docs/deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md)、[Tool Runtime](../../docs/deep-dive/tools/READ_ONLY_TOOL_CALLING.md)、[私有凭据](../../docs/deep-dive/operations/PRIVATE_CREDENTIAL_STORAGE.md) 为准。

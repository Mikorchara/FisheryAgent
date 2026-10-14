# Management Web R1：当前架构

## 应用边界

`apps/management_web/`是独立管理应用；原`src/fishery_ai` Runtime和Prototype Web保留。Flask复用现有依赖，前端原生ES Modules/CSS/SVG，无外部CDN和大型框架。默认8766、本机访问；启动不解析凭据或组装模型服务，不迁移桌面GPU监测器。

七页面共用Sidebar / Topbar / Cards / Tables / Dialog / Chart / Empty State。Dashboard展示水质、趋势、视频空状态、演示事件、AI入口及连接状态；事件与文件支持筛选和详情。AI只提供草稿容器，设置区区分管理员配置与开发验证。

## 可替换服务

页面 → `static/services.js`应用API客户端 → `app.py`装配 → 五个独立服务。

`contracts.py`使用轻量dataclass与Protocol，`create_app`支持注入替代服务，没有动态插件体系。

| 边界 | 页面输入 / 当前实现 | 后续接入 |
|---|---|---|
| MonitoringData | devices、MonitoringSnapshot；每个Metric包含值、单位、来源、observed_at、quality、freshness；批次有evaluated_at / DemoMonitoring | 数据库或设备适配器规范化raw packet，页面不做诊断 |
| AIService | availability、未来应用层send / UnavailableAI | 薄桥接现有AssistantService与Runtime，不复制模型Loop |
| VideoDetection | 设备、stream_url、检测与连接状态、detections / DemoVideo无流或结果 | 通信、NPU推理、规范化事实与网页展示分离 |
| KnowledgeFiles | 文件元数据、分类、来源、索引状态、受控下载引用 / DemoFiles | 原始文件管理、索引任务、知识检索分别接入 |
| EventRecords | 时间、设备、类型、等级、状态、附件引用 / DemoEvents三条样例 | repository替换，不先造正式告警工作流 |

## 来源和生命周期

当前值、趋势、事件、文件条目均为独立Demo，不是传感器/NPU/正式检索Evidence。Demo观测时间在adapter创建时固定，查询只更新evaluated_at；10分钟TTL仅为Demo新鲜度示例，不是生产采样频率或诊断规则。可显式查看stale/invalid/partial/missing。缺失和无效不显示默认数值，不把缺失当0；服务重启重建Demo，不持久化。

视频没有假录像或识别框，“未接入”不等于真实设备离线。事件处理状态是样例字段；文件条目没有实际上传文件或检索索引。

## 下一阶段复用AI

1. 在服务装配层注入薄AI适配器，调用现有AssistantService / ToolCallingService / Gateway，不复制执行栈。
2. 复用正式CredentialStore、RuntimeSnapshot、RequestHandle、Policy、Ledger、Commit Gate；接入epoch、execution revision、逐次联网确认、Stop和安全Streaming事件。R1消息端点目前始终503，不因注入对象就开放执行。
3. 页面只消费最终正文与安全Activity / Steps / Usage；预览不进入History。模型SDK、Prompt和Tool参数不进入前端。
4. 接监测数据时装配唯一canonical WaterQualityReading / CurrentSnapshotStore / CurrentWaterQualityReader，让展示和Tool共享来源。不将当前Demo UI读数隐式当作正式AI current-state，不建立第二份事实真相。
5. 身份与授权完成前，不开放模型配置、Key录入、阈值修改、设备控制或数据库写入。

## 安全和限制

localhost-only、Host/Origin限制、无CORS、CSP self、安全textContent、统一错误码与请求大小上限，debug/Flask dotenv关闭。不读取凭据、不支持路径输入/上传/任意文件或管理写API；AI发送503，写路由404/405。安全占位不靠前端隐藏。

当前无认证、DB、真实视频、AI桥接或新RAG，不可生产部署。真实接入需补DTO校验、服务异常/来源状态处理、鉴权与写API安全，不能宣称Protocol已解决这些功能。测试独立于Prototype产品发现范围，命令见[子应用README](../../../apps/management_web/README.md)。

## R1验收

离线API与前端合同测试；实际浏览器验收七页导航、观测状态、趋势、筛选/详情、AI草稿与禁用发送、无视频流、设置禁用操作，桌面与390px小屏无页面级横向溢出。原Prototype另跑Web/Browser回归。全程不请求真实Provider。

R1结果：新应用9项Python + 8项Node测试通过；原Prototype相关64项Python + 219项Browser回归通过。浏览器1440/1024/390宽度七页无页面级横向溢出，筛选、详情、草稿保留与禁用功能已实际检查；最终浏览器Console无错误。首次浏览器检查发现一处括号语法错误，修正后通过syntax与复验。Python AST、Markdown链接、diff check与新增文本敏感扫描通过，未改AI Runtime或生产项目、未commit/push。截图仅包含Demo，保存在Git ignored的outputs/management_web/。

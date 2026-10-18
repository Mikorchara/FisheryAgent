# 管理系统 Web

独立管理应用：Flask + 原生 ES Modules / CSS / SVG，复用现有依赖。水质、视觉与事件来自统一 SQLite 存储的模拟器上报；可显式启用 Normal Assistant，共用该监测来源。「资料与知识库」管理单一SQLite中的用户与内置导入文本，并支持Markdown/JSON导出，和 AI 共用原 TF-IDF 检索；文件导入、真实传感器/NPU/视频和生产权限未接入。

首次升级须按[统一知识库迁移](../docs/deep-dive/KNOWLEDGE_CONTENT.md)先显式备份迁移；未准备新库会安全拒绝启动，不自动动用户数据。

在仓库根目录执行：

```powershell
python -m apps.management_web
```

访问 `http://127.0.0.1:8766`，只监听本机；可用 --port 8767 改端口，Ctrl+C 停止。默认设备写入和 AI 关闭，首次启动 NO_DATA；按下方 BUILD_RUN 启动模拟器。原 Prototype 8765 独立保留，不加载源码根 .env。--legacy-demo 仅保留 R1 展示，不能启用 Assistant。

Normal Assistant：`python -m apps.management_web --enable-assistant`；配合模拟器可再加 --enable-ingestion（须先设置开发令牌）。Qwen/Ollama 复用正式私有凭据与 Runtime；启动和页面切换不发模型请求，每次 Send 须显式确认。

支持统一 Monitoring 水质查询和原 KnowledgeService 算法的项目资料检索。Knowledge 经管理平台「系统设置 → Assistant Tool 授权」显式授权；网页内容编辑不等于授予模型 Tool 权限。默认 OFF / Normal / 1 Tool / 1 Round / 2 Requests，项目知识不表示当前观测或疾病确诊。沿用 `scripts/dev/run_local.ps1` 可开启已批准的 Qwen 三工具 Normal/Streaming 本地实验；原服务器 CLI 开关默认关闭。动态内容源的精确 Scope 与固定知识库不同，不继承旧真实资格。详见下方 BUILD_RUN。

AI 业务位于 `apps/ai_service/`；本目录的 ai_adapter.py 仅保留浏览器令牌、请求控制和业务合同委托，不包含 Tool/模型执行循环。它是同进程模块划分，无需增加启动服务或端口。

管理平台主要说明已集中在 `apps/docs/`：

- [文档与当前状态](../docs/README.md)
- [启动、离线测试与验收](../docs/BUILD_RUN.md)
- [目录与模块职责](../docs/STRUCTURE.md)
- [服务合同与集成边界](../docs/INTEGRATION.md)
- [开发路线](../docs/ROADMAP.md)

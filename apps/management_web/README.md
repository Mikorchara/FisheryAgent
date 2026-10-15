# 管理系统 Web

独立管理应用：Flask + 原生 ES Modules / CSS / SVG，复用现有依赖。水质、视觉与事件来自统一 SQLite 存储的模拟器上报；可显式启用 Normal Assistant，共用该监测来源。文件仍为 Demo，真实传感器/NPU/视频和生产权限未接入。

在仓库根目录执行：

```powershell
python -m apps.management_web
```

访问 `http://127.0.0.1:8766`，只监听本机；可用 --port 8767 改端口，Ctrl+C 停止。默认设备写入和 AI 关闭，首次启动 NO_DATA；按下方 BUILD_RUN 启动模拟器。原 Prototype 8765 独立保留，不加载源码根 .env。--legacy-demo 仅保留 R1 展示，不能启用 Assistant。

Normal Assistant：`python -m apps.management_web --enable-assistant`；配合模拟器可再加 --enable-ingestion（须先设置开发令牌）。Qwen/Ollama 复用正式私有凭据与 Runtime；启动和页面切换不发模型请求，每次 Send 须显式确认。

支持统一 Monitoring 水质查询，以及原 KnowledgeService 的项目资料检索。Knowledge 默认不授权；使用原 Prototype Tool Manager 的 Assistant 标签开启，刷新管理页面后重新确认。仍为 OFF / Normal / 1 Tool / 1 Round / 2 Requests，项目知识不表示当前观测或疾病确诊。具体步骤见下方 BUILD_RUN；未接入多轮或 Streaming。

管理平台主要说明已集中在 `apps/docs/`：

- [文档与当前状态](../docs/README.md)
- [启动、离线测试与验收](../docs/BUILD_RUN.md)
- [目录与模块职责](../docs/STRUCTURE.md)
- [服务合同与集成边界](../docs/INTEGRATION.md)
- [开发路线](../docs/ROADMAP.md)

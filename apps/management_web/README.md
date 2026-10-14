# 管理系统 Web R1

独立管理应用：Flask + 原生 ES Modules / CSS / SVG，复用现有依赖。七页面可导航，监测、事件和文件条目明确为独立 Demo；AI 发送、真实视频/NPU、数据库和管理写操作尚未接入。

在仓库根目录执行：

```powershell
python -m apps.management_web
```

访问 `http://127.0.0.1:8766`，只监听本机；可用 `--port 8767` 改端口，Ctrl+C 停止。原 Prototype Web 默认 8765，独立保留。启动不加载 `.env`、不解析凭据、不运行模型。

管理平台主要说明已集中在 `apps/docs/`：

- [文档与当前状态](../docs/README.md)
- [启动、离线测试与验收](../docs/BUILD_RUN.md)
- [目录与模块职责](../docs/STRUCTURE.md)
- [服务合同与集成边界](../docs/INTEGRATION.md)
- [开发路线](../docs/ROADMAP.md)

# 管理系统 Web R2A

独立管理应用：Flask + 原生 ES Modules / CSS / SVG，复用现有依赖。水质、视觉与事件来自统一 SQLite 存储的模拟器上报，页面定时查询；文件仍为 Demo 元数据。AI、真实传感器/NPU/视频和生产权限未接入。

在仓库根目录执行：

```powershell
python -m apps.management_web
```

访问 `http://127.0.0.1:8766`，只监听本机；可用 `--port 8767` 改端口，Ctrl+C 停止。默认设备写入关闭，首次启动 NO_DATA；按下方 BUILD_RUN 设置开发令牌、启用接入并启动模拟器。原 Prototype 8765 独立保留；不加载 `.env` 或运行模型。`--legacy-demo` 仅保留 R1 展示兼容模式。

管理平台主要说明已集中在 `apps/docs/`：

- [文档与当前状态](../docs/README.md)
- [启动、离线测试与验收](../docs/BUILD_RUN.md)
- [目录与模块职责](../docs/STRUCTURE.md)
- [服务合同与集成边界](../docs/INTEGRATION.md)
- [开发路线](../docs/ROADMAP.md)

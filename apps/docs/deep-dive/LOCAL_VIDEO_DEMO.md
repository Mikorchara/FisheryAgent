# 本地 MP4 展示与深蓝主题同步

2026-10-30。本轮仅在 Prototype 添加本地录像播放；Management 只选择性同步主题文件、HTML 入口、必要测试与启动指南说明。不复制业务代码、启动器或数据。

## 使用

在 Prototype 根目录：

```powershell
.\scripts\dev\Start-PrototypeStack.ps1 -PrepareDemo -InteractiveScenario -OpenBrowser -DemoVideo .\sample.mp4
```

进入「视频监控」页。静音循环播放，可暂停/拖动；离开视频页暂停。需要三终端时加原 `-WithBot`，QQ 仍须独立批准。日常数据仍为原 `apps/data`；本功能不创建第二份业务数据。`run_local.ps1` 也支持 `-DemoVideo`；Web CLI 对应 `--demo-video`。

不带该参数时不注册媒体入口或播放器。原 `.cmd` 默认行为不变。MP4 是容器格式，推荐 H.264/AAC；当前 sample.mp4 检查为60秒、1920×1080、H.264/yuv420p + AAC。文件未转码、未覆盖，被 Git 忽略。

## 实现与边界

- `management_web/demo_video.py`：显式固定 MP4、原文件身份检查；固定 URL `/media/local-demo.mp4`，仅 loopback 请求，沿用 Host/Origin 门禁。支持 Range、HEAD 和拖动；不存在任意文件读取参数。文件被替换/删除后拒绝，须重启重新选择。
- `app.py`：可选 video_preview 元数据，不修改 cameras、stream_url、观测、连接状态或事件。媒体策略仅允许同源。
- `components.js` + `app.js`：独立播放器 DOM 放在轮询内容区外，5秒刷新不重新加载录像；缺失元数据或请求失败会停止播放。默认视频面板不变。
- 录像上的日期是素材原始水印，不是本系统观测时间。播放不生成推理结果、采样批次、事件或摄像头在线状态。
- 这是 HTTP 文件播放演示，不等同于真实 RTSP/HTTP-FLV、视频分析或上行推流。未来设备接入见[适配设计](research/DEVICE_REPORT_ADAPTER_PLAN.md)。

## 验证

全部使用合成夹具或内存 Demo，不打开日常业务数据库，不读取密钥、不发模型/QQ请求。

- Prototype Python 定向47项：媒体默认关闭、Range/HEAD、非法来源/文件、启动参数、实例与启动器兼容。
- Prototype Web Assistant、Streaming与AI边界另53项通过（合计100项定向Python）；`-DemoVideo .\sample.mp4 -Check` 返回通过，database_opened/credential_checked均为false、QQ/Provider网络请求为0。
- Prototype Node124项；Management Node121项、Web HTTP11项。Management 新主题与 Prototype 的 theme.js/theme-dark.css 一致，默认浅色和浏览器本地偏好保留。
- 浏览器使用无数据库的临时预览：真实 sample.mp4 解码为1080p、60秒；播放、暂停、轮询期间连续播放和离页暂停；另检查窄屏与 Management 主题。
- 本轮未运行耗时较长的全量 Bot/Provider 回归；没有改其运行时、Tool、Prompt、Policy 或 Schema。没有真实设备网络接入测试。

截图与本轮非敏感预览记录保存于 `outputs/ui-video-review/`；临时预览服务验收后停止。代码未 commit/push。

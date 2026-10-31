# 设备联调：模拟水质 + Jetson 视觉报告

2026-10-31，Prototype 实验实现，等待人工验收；未同步 Management。当前阶段是报文接收与展示，不把设备报告直接转换成 Monitoring 事件。

## 使用模式

| 模式 | 水质 | 视觉 | 事件 |
|---|---|---|---|
| full（原默认） | 原 Simulator | 原 Simulator | 原 Monitoring 规则 |
| water-only（设备联调） | 原生成器，仅水质，仍标 SIMULATOR | 独立设备报告 | 水质仍可产生模拟事件；设备视觉暂只展示原报告 |

没有复制第二套 Generator 或 Agent。`apps.simulator --mode water-only` 跳过视觉生成、上报 `visual=null`；无水质时不发空批次。Web 同时启用 water-only 后拒绝任何模拟视觉批次（403 SIMULATED_VISUAL_DISABLED）。设备数据写入独立收件箱，不能覆盖 Monitoring 两通道。原有模拟视觉/事件仍保存历史，中断不算恢复，不删除记录。

`启动演示系统.cmd` 现在先选模式，再按原菜单选场景；Enter 使用完整模拟。仅选联调模式但未绑定报告目录时，页面明确显示“尚未绑定”，不自动选择旧数据库或伪造视觉正常。

## 首次准备（用户执行）

在 Prototype 根目录，先检查，再显式创建新收件箱。默认目录是同一日常数据根下的 `apps/data/device-reports/`，不是另一套日常实例：

```powershell
.\scripts\dev\Start-DeviceReports.ps1 -Check
.\scripts\dev\Start-DeviceReports.ps1 -InitStore
```

初始化仅创建新的 `device-reports.sqlite3`；重复初始化拒绝，不覆盖。当前独立收件箱 Schema v1 与 Monitoring v2 无关，不迁移或修改现有数据库。令牌在实际监听启动时由操作者不回显输入，32–128位字母数字，与板端约定；不写配置或日志。

## 开始联调（用户明确启动，不由自动测试执行）

终端一启动原 Web + 水质模拟器（可在场景菜单选低氧等）。以下选择不启用 Web Assistant；需要原助手时自行去掉 -NoAssistant，原 Tool/模型审批保留：

```powershell
.\scripts\dev\Start-PrototypeStack.ps1 -PrepareDemo -SimulationMode water-only -DeviceReportDirectory .\apps\data\device-reports -DeviceReportDeviceId fish-monitor-orin-01 -InteractiveScenario -OpenBrowser -NoAssistant
```

如需原本地录像，加 `-DemoVideo .\sample.mp4`。进入网页「视频监控」或首页查看设备报告。不会访问报告中的任何 URL，不自动连接板端视频，不将报告送给 AI。

另开终端启动独立接收器；将下例替换为**接收电脑实际的局域网 IPv4**，必须与板端可达。默认只监听127.0.0.1；拒绝0.0.0.0，不自动配置防火墙：

```powershell
.\scripts\dev\Start-DeviceReports.ps1 -Serve -Bind '192.168.1.100'
```

给组员的地址：`http://<接收电脑IP>:8780/api/fish/reports`，方法POST，JSON与 `X-Device-Token`。不要给127.0.0.1。示例IP不是自动发现结果；换网络需核对IP。只适用于受控局域网；不可信网络需后续HTTPS或受控隧道，不直接暴露公网。

停止：接收器终端 Ctrl+C，仅停接收；原Web/Simulator继续运行。Web/Simulator停止仍按原启动器规则。接收器不自动重启、不自动重放消息、不调用LLM/NPU。QQ仍是独立授权入口，本阶段不新增设备视觉AI Tool。

## 收件规则与数据诚实性

- 以[组员v1规范](translation/TEXT_PACKAGE_API.md)为依据，16 KiB上限，严格JSON与类型/数值/时间校验，拒绝重复字段。仅接受本机指定device_id及令牌；Origin请求拒绝，无管理接口、CORS、重定向或密钥输出。
- `(device_id,report_id)` + 固定canonical JSON摘要幂等；同内容重传返回duplicate，同ID不同内容409且不覆盖。需与板端确认409不可重试。
- SQLite事务内去重和写入，synchronous=FULL，commit成功才返回2xx。落盘失败/锁超时503，可由板端按原合同退避重传；有界每分钟60次、收件箱最多5000条，满后拒绝而不自动清理。
- 保留原窗口、发送与接收时间。允许缓存历史补发，按窗口结束时间选最新报告，旧包不会变成新鲜观测。网页只读展示最近20份；超过120秒标为过期，仅供回看。该标记只是报告年龄，不声称设备在线/离线。
- 示例起止相差39秒但duration_s=38：保留原包并标 WINDOW_DURATION_MISMATCH，不擅自改时间，不作为恢复依据。正常/异常标志矛盾也提示，不能直接当作规则HIT/CLEAR。
- 原始 report_text 用纯文本显示；标签来自设备模型，显示为检测信号、非确诊。行为与体长null显示未提供，不补0或“正常”。缺少每任务覆盖、Session/Sequence，不推断设备恢复或生成当前Monitoring事件。
- 建议板端 interval 每窗口都发；仅异常才发时，沉默不等于正常或离线。水质与视觉设备标识分别显示，不伪装成同一真实采样源。
- 保留5000条之后需要显式另行规划容量；本轮不实现删除原报告或自动归档接口。

## 后续门槛

本轮接通报告收件与展示。设备视觉接入规则/事件、HTTP-FLV播放仍需下一步：先补充每任务执行覆盖、Session/Sequence及模型信息，再审核来源、时效和可靠恢复合同；不通过修改原Simulator阈值或凭空构造正常帧实现。

测试使用临时合成Monitoring与独立报告库、Fake请求。覆盖鉴权/超限、幂等/冲突/并发、落盘失败、旧包与重启、旧视觉不假恢复、只模拟水质及服务端拒绝混入、原模式回归。运行结果见本轮验收记录与终端交付；真实板端和真实网络仍待用户人工验收。

## 2026-10-31 离线验收结果

- `run_management_tests.py`：1255项Python全部通过（含9项新增设备报告测试），Node125项全部通过；耗时约724秒。使用项目自身`.venv`、临时合成数据和Fake Provider/Gateway。
- 最新启动器/本机配对13项另行通过；设备报告+本机配对13项通过；原Simulator、HTTP与启动器定向36项通过。全部Node再次125项通过。
- 两条Check通过，database_opened=false、credential_checked=false、network_requests=0；未创建日常报告库，未输入真实设备令牌。用户执行InitStore后才会新建。
- 浏览器临时合成收件箱：桌面/390px窄屏，无横向溢出；原报告按文本显示、过期/缺失/时长不一致提示可见；展开详情跨轮询保持。预览已停止。截图和非敏感记录位于`outputs/device-integration-review/`。
- 13份历史文档归档到[阶段归档](../patches/2026-10-31-stages/README.md)，相对链接已修正；另修复4处原有EVENT_ACK失效引用。Markdown链接检查无错误，`git diff --check`通过。没有永久删除文档或移动规范原件。
- 新包已列入打包清单并排除测试。离线wheel构建尚未验证：本机`.venv`缺`setuptools.build_meta`，未联网安装依赖。源码启动与Check已验证，此环境限制应在后续发行前补验。
- 原Monitoring/AI Backend/AI Service/旧src源码未修改，无新增AI资格、Tool或模型权限；不操作旧批准/used/回执。未修改Management、真实数据库、Settings、Policy或Credential，未commit/push。

人工接入前还需双方确认令牌、实际局域网IP、interval模式与任务覆盖字段。两端需校时，未来时间报文会拒绝。同一日常数据根只运行一组Web/Simulator，不另开完整模拟写入该根。当前阶段不能用设备报告执行人工ACK、结束、恢复或专业疾病诊断。

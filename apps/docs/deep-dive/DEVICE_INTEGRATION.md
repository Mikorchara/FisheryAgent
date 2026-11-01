# 设备联调：模拟水质 + Jetson 视觉报告

2026-10-31，Prototype 实验实现，等待人工验收；未同步 Management。当前阶段是报文接收与展示，不把设备报告直接转换成 Monitoring 事件。

## 使用模式

| 模式 | 水质 | 视觉 | 事件 |
|---|---|---|---|
| full（原默认） | 原 Simulator | 原 Simulator | 原 Monitoring 规则 |
| water-only（设备联调） | 原生成器，仅水质，仍标 SIMULATOR | 独立设备报告 | 水质仍可产生模拟事件；设备视觉暂只展示原报告 |

没有复制第二套 Generator 或 Agent。`apps.simulator --mode water-only` 跳过视觉生成、上报 `visual=null`；无水质时不发空批次。Web 同时启用 water-only 后拒绝任何模拟视觉批次（403 SIMULATED_VISUAL_DISABLED）。设备数据写入独立收件箱，不能覆盖 Monitoring 两通道。原有模拟视觉/事件仍保存历史，中断不算恢复，不删除记录。

`启动演示系统.cmd` 现在先选模式，再按原菜单选场景；Enter 使用完整模拟。仅选联调模式但未绑定报告目录时，页面明确显示“尚未绑定”，不自动选择旧数据库或伪造视觉正常。

## 选了模式2之后 场景还有效吗

第一个菜单的模式2是设备联调，第二个菜单仍是模拟场景选择。设备联调下，场景只影响模拟水质；疑似疾病和摄食减少的视觉信号停止生成。

| 场景 | 设备联调下的效果 |
|---|---|
| 正常水质 | 正常模拟水质波动 |
| 低溶解氧 | 溶解氧下降，仍可能产生标明SIMULATOR的水质事件 |
| 疑似疾病 | 不再模拟疑似疾病信号；只保留该场景的正常水质基线及随机波动 |
| 摄食减少 | 不再模拟摄食异常；只保留该场景的水质部分 |
| 复合异常 | 水温升高、溶解氧降低仍有效；模拟视觉异常停用 |
| 设备离线 | 仅让Simulator停止水质上报，不停止开发板或报告接收器 |
| 溶解氧快速下降后逐步回升 | 水质曲线仍有效，不产生模拟视觉信号 |

因此首次真实联调建议选择“正常水质”，让双方先核对设备报告；需要演示水质事件时，再选择低氧或下降回升。菜单中“每10秒更新水质与视觉”的通用标题不代表联调模式仍会发送模拟视觉，以实际模式和“仅模拟水质”提示为准。

这里的设备接入目前是**设备报告接入**，不是设备事件自动接入。开发板报告中的异常会显示在设备报告区域，尚不会自动变成事件列表中的Monitoring事件；历史模拟视觉事件仍可能留在历史列表。

## 首次真实接入的分工

先在同一受控局域网完成报文联调，水质与视频分别保持原演示方式。接收电脑和Jetson需能相互访问；即使连接同一Wi-Fi，也应确认没有访客网络或客户端隔离。

| 由谁设置 | 需要确认的内容 |
|---|---|
| 接收电脑操作者 | 当前局域网IPv4、端口8780、报告库、接收器、Web只读绑定 |
| 双方共同约定 | 设备ID `fish-monitor-orin-01`，以及通过安全方式交接的32–128位字母数字令牌 |
| Jetson组员 | fish_reporter接收URL、同一设备ID、`X-Device-Token`、interval每窗口上报模式 |
| 双方共同核对 | 设备和电脑时钟、带时区的窗口时间、发送状态和网页上的报告ID |

数据分两条路径进入电脑：Simulator经本机8766端口发送水质；Jetson经局域网8780端口发送视觉报告。管理Web仍在 `http://127.0.0.1:8766`，不需要向局域网开放设置或AI接口。

可在电脑执行 `ipconfig`，查看正在连接板端网络的Wi-Fi/以太网适配器IPv4。不要填写127.0.0.1、开发板自身IP或无关虚拟网卡地址。下文 `192.168.1.100` 仅作示例，必须换成电脑实际地址。

## 首次准备（用户执行）

先停止原先占用同一实例/8766端口的Web与Simulator。在 Prototype 根目录，先检查，再显式创建新收件箱。默认目录是同一日常数据根下的 `apps/data/device-reports/`，不是另一套日常实例：

```powershell
.\scripts\dev\Start-DeviceReports.ps1 -Check
.\scripts\dev\Start-DeviceReports.ps1 -InitStore
```

初始化仅创建新的 `device-reports.sqlite3`；重复初始化拒绝，不覆盖。当前独立收件箱 Schema v1 与 Monitoring v2 无关，不迁移或修改现有数据库。令牌在实际监听启动时由操作者不回显输入，32–128位字母数字，与板端约定；不写配置或日志。

`-InitStore` 只在首次执行。已经成功初始化时跳过；遇到 `DEVICE_REPORT_STORE_EXISTS` 不要删除或覆盖原库。

## 开始联调（用户明确启动，不由自动测试执行）

**第一步：启动Web和水质模拟器。** 以下完整命令同时完成水质专用模式和报告目录绑定。首次选正常水质；以下不启用Web Assistant，需要原助手时自行去掉-NoAssistant，原Tool/模型审批保留：

```powershell
.\scripts\dev\Start-PrototypeStack.ps1 -PrepareDemo -SimulationMode water-only -DeviceReportDirectory .\apps\data\device-reports -DeviceReportDeviceId fish-monitor-orin-01 -InteractiveScenario -OpenBrowser -NoAssistant
```

如需原本地录像，加 `-DemoVideo .\sample.mp4`。进入网页「视频监控」或首页查看设备报告。不会访问报告中的任何 URL，不自动连接板端视频，不将报告送给 AI。

仅在原 `.cmd` 菜单选择模式2，只会启用水质专用模式；不会自动启动报告接收器，也不会自动绑定报告目录。首次真实接入请使用上面带 `-DeviceReportDirectory` 和 `-DeviceReportDeviceId` 的命令。

**第二步：另开终端启动独立接收器。** 将下例替换为**接收电脑实际的局域网 IPv4**，必须与板端可达。默认只监听127.0.0.1；拒绝0.0.0.0，不自动配置防火墙：

```powershell
.\scripts\dev\Start-DeviceReports.ps1 -Serve -Bind '192.168.1.100'
```

给组员的地址：`http://<接收电脑IP>:8780/api/fish/reports`，方法POST，JSON与 `X-Device-Token`。不要给127.0.0.1。示例IP不是自动发现结果；换网络需核对IP。只适用于受控局域网；不可信网络需后续HTTPS或受控隧道，不直接暴露公网。

按提示输入双方约定的令牌，看到 `DEVICE_REPORT_LISTENING` 才表示已开始监听；`-Check`通过仅表示配置检查完成。若Windows防火墙阻挡，由操作者核对专用网络与该接收端口的入站规则，不关闭整个防火墙，也不开放管理Web端口。

**第三步：组员配置并启动fish_reporter。** 按发送端实际配置入口填写下表，不假定发送端已有某个命令行参数：

| 配置项 | 填写内容 |
|---|---|
| 方法与地址 | POST `http://<接收电脑IP>:8780/api/fish/reports` |
| 内容类型 | `application/json; charset=utf-8` |
| 请求头 | `X-Device-Token`，值为双方约定的令牌，不放进报文正文或普通日志 |
| 设备ID | `fish-monitor-orin-01`，与接收器及Web绑定一致；如需改ID，三处同时明确修改 |
| 发送模式 | 优先interval，每个窗口都发，正常窗口也发送；窗口约60秒 |
| 格式 | [TEXT_PACKAGE_API v1](translation/TEXT_PACKAGE_API.md)，重传保持同一report_id和内容 |

令牌不贴进聊天、命令行或Git，板端按既有密钥文件方式配置。双方先修正后续新报文的窗口时长，确保end-start与duration_s一致；不要修改已经发送过的同一report_id内容，否则接收器返回409。

## 首次联网验收清单

1. **第一份新报告**：组员确认发送端收到HTTP2xx及accepted；电脑网页出现相同report_id、设备ID、窗口时间和接收时间。接收器终端只输出安全状态，不承诺逐条打印报告。
2. **连续上报**：观察3～5个新窗口，确认网页报告持续更新，行为/体长未提供时显示缺失，水质仍标SIMULATOR。超过120秒的旧报告显示过期不代表接收失败。
3. **同包重传**：发送端重传一份内容不变的同ID报文，收到duplicate；网页不增加第二份相同报告。未知设备ID或错误令牌应被拒绝。
4. **独立停止**：暂停板端上报，确认水质模拟继续；页面不能把沉默显示为设备正常。随后Ctrl+C停止接收器，Web/Simulator也应继续。此阶段不以自动离线告警或设备事件恢复作为通过标准。
5. **来源核对**：设备异常只在设备报告区域出现；原事件列表里的SIMULATOR事件仍属于模拟来源。本地sample.mp4仍是录制素材，与报告不要求同步。

第一次验收只接报文，不同时接实时视频。板端 `http://<板子IP>:9002/osd.flv` 的HTTP-FLV播放适配另行验证，当前网页不会自动播放它。后续再补任务覆盖、Session/Sequence和模型版本，设计设备视觉事件与恢复规则。

遇到错误时按顺序排查：

| 现象 | 先检查 |
|---|---|
| 连接拒绝或超时 | 接收器是否正在监听、电脑IP/8780端口、网络隔离、防火墙；不是先改报文 |
| 403 | 令牌、device_id、是否由设备直接请求；浏览器Origin请求被拒绝 |
| 400 / 413 | JSON字段与类型、时间/校时、16KiB大小上限 |
| 409 | 同一设备同一report_id被用于不同内容，不要覆盖旧记录 |
| 429 / 503 | 限流、存储容量、锁或写入失败；发送端按约定有界退避，不更换旧包ID重试 |
| 2xx但网页无报告 | Web是否用完整命令绑定了同一目录和设备ID；是否查看最近20份；旧包可能排在新包后面 |

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

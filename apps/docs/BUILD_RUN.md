# 管理平台启动、联调与验证

## 环境

Python 3.11+，使用根项目已有 Flask 依赖；SQLite、生成器和 HTTP transport 使用标准库。Node 用于前端测试，无需 npm install 或构建。所有命令在 `D:\CodexProject\Fishery_AI_Prototype` 执行；首次环境配置见根 [BUILD_RUN](../../docs/BUILD_RUN.md#环境与启动)。

## 只读启动

```powershell
.\.venv\Scripts\python.exe -m apps.management_web
```

访问 `http://127.0.0.1:8766`。读取已保存的监测数据或明确 NO_DATA；默认拒绝设备写入。可使用 `--port 8767`。原 Prototype 8765 独立保留；Flask debug/dotenv 关闭。

## 连续模拟器本机联调

同一 PowerShell 中创建仅本次开发会话使用的访问令牌，让服务器子进程继承；不显示、不落盘、不使用真实 API Key：

```powershell
$env:FISHERY_SIM_INGEST_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$managementServer = Start-Process -FilePath .\.venv\Scripts\python.exe -ArgumentList '-m','apps.management_web','--enable-ingestion' -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru
.\.venv\Scripts\python.exe -m apps.simulator --scenario low_oxygen
```

先打开网页，初次上报等待约 10 秒；约 60–120 秒观察溶氧逐渐降低和关联事件。也可选择 normal、suspected_disease、reduced_feeding、combined_anomaly、device_offline。device_offline 在场景 30 秒处停止上报，但进程继续等待，便于观察过期/中断。

停止模拟器按 Ctrl+C；服务器继续保存和显示末次数据。停止自己启动的服务器：

```powershell
Stop-Process -Id $managementServer.Id
Remove-Item Env:\FISHERY_SIM_INGEST_TOKEN
```

不要停止未由当前会话启动的进程。若 8766 已占用，服务器加 `--port 8767`，模拟器加 `--server http://127.0.0.1:8767`。可在独立终端分别启动，但双方必须继承同一个开发令牌；不要打印令牌或写入项目 .env。

可选参数：

```powershell
.\.venv\Scripts\python.exe -m apps.simulator --scenario normal --seed 42 --interval 10 --sample-period 1 --frame-period 0.5 --windows 6
.\.venv\Scripts\python.exe -m apps.simulator --scenario normal --switch-to combined_anomaly --switch-after 60
.\.venv\Scripts\python.exe -m apps.simulator --scenario combined_anomaly --dry-run --windows 12
```

dry-run 快速推进逻辑时间，不联网、不读取访问令牌。上报失败停止进程，不自动重试。重新启动使用新 session_id，sequence 从零开始；观测时间从新的启动时间继续。R1 静态 Demo 仅可用 `--legacy-demo` 显式启动，不能同时启用接入。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s apps/monitoring/tests -p "test_*.py"
.\.venv\Scripts\python.exe -m unittest discover -s apps/simulator/tests -p "test_*.py"
.\.venv\Scripts\python.exe -m unittest discover -s apps/management_web/tests -p "test_*.py"
node --test apps/management_web/tests/*.test.mjs
```

这些测试独立于根 product 发现范围。前两组除明确的 loopback HTTP 测试外不联网；只用临时数据库/虚构令牌，无真实 Provider 或 NPU。

界面验收：七页导航；窗口均值、有效样本和历史；视觉行为占比与无标定体长；事件批次/去重/消退；停止后 >30 秒过期、>90 秒中断；恢复上报后更新；桌面与窄屏无溢出。读取失败清除当前展示并提示失效，不将缓存当实时。

服务/合同变更运行相关 Python 和 Node；UI 变更增加浏览器行为与布局检查。涉及共享 Runtime 桥接追加其相关回归。文档变更检查链接与 diff。不要把测试启动器的旧授权当作真实模型执行许可。

## 数据与限制

存储为 `outputs/management_web/monitoring.sqlite3`，Git ignored；重启保留记录。不要删除已有数据库来“重置演示”，需要隔离测试时使用临时库和服务注入。

这是本机模拟接入，不是生产设备鉴权；AI 固定 503，真实视频、文件写入、用户权限与设备控制未开放。安全与 DTO 详见 [INTEGRATION](INTEGRATION.md)。

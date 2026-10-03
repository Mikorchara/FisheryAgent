# 构建与运行

**CURRENT · 2026-10-03**。操作依据是当前代码；旧阶段命令与环境观察见[历史索引](history/README.md)。

## 环境与安装

Python 3.11+，从仓库根目录 PowerShell 启动。依赖由 pyproject.toml 声明：openai、httpx、python-dotenv、Flask；TF-IDF 默认 portable 后端无额外依赖，可选 sklearn 后端不是默认安装要求。没有单独维护 requirements.txt 或精确版本锁文件。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

可选激活 .venv/Scripts/Activate.ps1；直接使用虚拟环境 python 不需要修改 PowerShell 策略。测试或复现时记录本机依赖版本，不把真实凭据打包进环境。

## 离线测试与 Mock Demo

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --test tests/test_browser_streaming.cjs
node --check src/fishery_ai/resources/web/app.js
git diff --check
.\.venv\Scripts\python.exe -m fishery_ai demo --scenario low_oxygen
.\.venv\Scripts\python.exe -m fishery_ai demo --profile local-demo --scenario partial_stale --mode chat --question "当前水质如何？"
```

自动测试使用临时 Store、虚构 Secret、假 transport，并有禁网保护。Mock Demo 永远使用 MockGateway、禁止 socket 联网、不解析真实 Key，即使选择 cloud-demo / local-demo 也不会联系模型。

可选水质场景：normal、low_oxygen、partial、stale、partial_stale。Demo 中时间固定，不是当前现场时间；freshness 按 retrieved_at - observed_at 与 stale_after_s 比较，不按运行当天判断。测试扩展矩阵未加入 Web/CLI 场景列表，详见[水质报告](research/WATER_QUALITY_SCENARIO_AND_TELEMETRY_PREPARATION.md)。

Demo 输出 AnalysisResult、规则、RAG、Runtime、Usage；Mock Usage 为 unavailable。Trace 写入 ignored outputs/mock-traces.jsonl。资料包在 package resources 中，可在安装后读取。

## 启动 Web

```powershell
.\.venv\Scripts\python.exe -m fishery_ai web
# 可选：python -m fishery_ai web --port 8766
```

访问 http://127.0.0.1:8765，只监听 loopback，不默认开放所有网卡。Flask 启动 load_dotenv=False。启动不自动访问模型；网络请求由用户确认 REAL NETWORK REQUEST，Cloud 可能收费。不提供登录系统，不用于公网部署。

### Preset

当前 Qwen 3.8 Flash、DeepSeek Flash、Ollama Qwen3.5 4B 合同均为 1.0.0。各允许 OFF + Normal、ON + Normal、ON + Streaming；默认 Qwen OFF + Normal，AUTO / OFF Streaming 暂未发布。

只选择 Model、Thinking、Response Mode、场景和问题。不得编辑 URL/协议/凭据引用/合同，不显示 Probe 或模型 Capability Evidence。未发布模式提示“此 Preset 未提供该模式”。Cloud 缺凭据返回 SECRET_MISSING；Ollama Auth NONE 不要求 Key。详细依据见[发布报告当前节](validation/PRESET_SIMPLIFICATION_AND_FIRST_PUBLICATION.md#12-用户人工验收后的精确多模型登记当前状态)。

### Managed Custom

Managed Custom → 新建 → 选择 Provider → 填写唯一名称、Base URL、精确 Model 与凭据引用。高级连接设置可查 service/adapter/auth 等，Key 不能填进 Profile。

在“本地凭据管理”中刷新状态，MISSING 可设置 Key，用户私有 PROJECT_ENV 可替换/删除，PROCESS_ENV 外部只读；未保存草稿也可先设置凭据。查询模型、连接测试、Probe 均由按钮显式触发。模型列表成功不授权高级能力；Cloud 保存需要有效连接测试，Local 可保存后再验证。

创建后名称不可修改；编辑只创建 Draft，不改变 Selected Profile、在途 Runtime 或能力。保存后才按新 Identity 解析；取消编辑/退出新建丢弃未保存内容，不写 Evidence。

Normal + AUTO / UNSET 可以在高级能力 UNKNOWN 时运行。ON/OFF/Streaming 必须相应 SUPPORTED，冲突保持 UNKNOWN 并解释原因；Probe 成功后仍由 R4 Resolver 合并再更新 UI。旧偏好保留，能力不满足时运行临时回退 AUTO + Normal。配置写入 ignored outputs/custom_profiles/，Evidence 写入 outputs/capability-evidence/，不加入 Git。

### Manual Expert V1 / V2

V1（Saved Connection）选择已有连接，编辑 Raw JSON，model 必须与连接一致。V2 选择独立实验，可直接填写 Service 标签、Base URL、Model、Timeout 和 Raw JSON，不要求先有 Profile。

V2 页面 Model 是权威 ID，Raw JSON 可不包含 model，后端仅在发送副本中补入；相同显式 model 兼容，不同返回 MANUAL_MODEL_MISMATCH。Save 保存/更新，Save As 创建新实验保留旧实验，Delete 只删除/归档实验，不删除 Credential。

V2 Credential Ref 是变量名；新 Key 输入框只填真实值，不填 NAME=value。Key 仅存用户私有 manual.env，实验只存引用，位于 ignored outputs/manual-experiments/。V1 和正式连接不读取 manual.env；V2 不读取正式 Key 或进程 Key。

Manual 不自动注入 Thinking/Effort/include_usage，不进入 R3/R4/R5、RAG/Diagnosis/AnalysisResult；返回 tool_calls 只显示，不执行。Raw HTTP headers / Authorization / transport 配置不允许被覆盖。Raw response 有什么显示什么，不当作正式 Fishery 分析结论。

### Streaming / Stop / Usage

Normal 与 Streaming 复用 Orchestrator。流式先显示 facts/rules/evidence，再接收 content_delta；reasoning 单独调试展示，结束后解析最终正文。TTFT 区分首个模型 delta 与首个正文，缺失 Usage 显示 unavailable，不写成 0。

点击 Stop 会要求后端取消并关闭 SDK I/O，和仅浏览器 Abort 不同；不能证明远端计算或云端计费已停止。USER_CANCELLED 不重试，不将部分 JSON 当最终完成结构，不写 Capability Evidence。Manual 共用传输与取消，但不产生分析 Trace。

## 正式凭据与存储

正式优先级：PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING。Windows 固定布局：

```text
%LOCALAPPDATA%/Fishery_AI_Prototype/project-<项目绝对路径的稳定哈希>/credentials/
  .env        # Preset / Managed / V1
  manual.env  # 仅 V2
```

路径由启动边界确定，Web/Model/Profile 不能指定任意文件。私有目录仍检查 owner/DACL、link/reparse/hardlink、锁、staging、revision 和原子替换。来源不可安全确认则 fail closed。Key 不返回浏览器、不写日志/Trace/Evidence/LocalStorage；外部 process source 只读。轮换使连接测试和模型列表授权失效，保留能力和偏好。

旧根目录 .env 不读、不迁移、不 fallback；.env.example 已由用户删除，不恢复。新请求 hot reload，在途请求保留不可变 CredentialSnapshot。详见[私有存储指南](guides/R2_PRIVATE_CREDENTIAL_STORAGE_MIGRATION.md)。

## 历史验证入口

主 validate-real 及三个 validate_qwen_*.py 仍保留原确认、timeout、私有 credential composition；其旧实验 Profile 已退出活动目录，当前返回 INACTIVE_VALIDATION_PROFILE，不从历史 fixture / 归档恢复。不要把历史报告命令当作当前 Preset 资格测试。当前真实接入由用户在正常 Web 进程明确验证；本轮文档整理不调用任何真实模型。

[故障排查](TROUBLESHOOTING.md) / [当前架构](architecture/CURRENT_ARCHITECTURE.md) / [文档导航](README.md)

# AI Backend 源码入口

本包承接从旧 Prototype 提取的通用 LLM 执行基础。只迁入已有且边界清楚的实现，不复制 Runtime，不通过 facade 再导入 `fishery_ai`。

## 当前已实现

```text
ai_backend/
├─ __init__.py                    # 无 I/O 的包入口
├─ README.md                      # 职责、公共接口与迁移边界
└─ tool_argument_diagnostics.py   # 参数拒因枚举、有界计数与安全投影
```

唯一公共模块是 `apps.ai_backend.tool_argument_diagnostics`：

- `ArgumentStage` / `ArgumentRejection`：固定阶段与拒因。
- `ToolArgumentDiagnostic` / `ToolArgumentError`：不可变诊断值和兼容 ValueError 的错误。
- `rejection()` / `public_argument_diagnostic()`：构造诊断与 allowlist 投影；不输出参数、成员名或异常正文。

旧 `fishery_ai.tool_argument_diagnostics` 是同一模块对象的兼容别名。类、枚举、异常及 monkeypatch 不会分成两套；新代码使用这里的路径。诊断只是解释拒绝，不替代参数校验、授权或执行门禁。

目前本包仅依赖标准库，不导入 Flask、Monitoring、SQLite、Knowledge、Provider SDK、Credential 或旧 Prototype。导入不会执行 Tool、读配置/凭据或联网。

## 仍未迁入

Gateway、Adapter、取消/Deadline、Tool 协调、History、Ledger 和事件目前仍在 `src/fishery_ai/`。管理端仍有旧包直接依赖；本目录不是已完成的独立 AI Runtime。

目标依赖为 `management_web → ai_service → ai_backend`；Web 可使用后端公开的请求控制/事件合同。业务 Prompt、Preset/发布配置、Tool 绑定和领域来源校验由 `ai_service` 装配，Monitoring 与 Knowledge 不放进通用 Backend。

每次后续迁移都需保留单一实现与同一请求上下文，验证 import/type identity、Scope/指纹、打包和旧新 Web 回归。后端不得反向引用业务层；兼容转发只能从旧包指向新包。不要提前创建空 Provider/Tool/Memory 子包。

## 安装与验证

根 pyproject 同时打包原 `fishery_ai*`、`apps` 包标记及本 Backend；不因此打包管理 Web、Monitoring、AI Service 或运行数据。管理应用仍从仓库根目录启动，现有命令不变。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.tools.test_backend_boundary tests.tools.test_tool_argument_diagnostics
```

测试位于根 `tests/tools/`，纳入已有 FULL PRODUCT 发现范围；不增加新的 runner。完整审计、剩余依赖、迁移次序与回滚见 [R2C-1A 报告](../docs/deep-dive/research/R2C1A_LLM_BACKEND_AUDIT.md)。

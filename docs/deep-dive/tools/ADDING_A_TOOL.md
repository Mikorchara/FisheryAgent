# 如何新增只读 Tool

新增 Tool 是一次受控代码变更，不是动态插件安装。当前运行时只会执行静态 Registry 中明确注册的 Handler。

## 实施顺序

1. **确定业务边界**：先在领域服务中定义稳定、可离线测试的输入输出。Tool Handler 不应承载领域规则、Provider 协议或 UI 行为。
2. **定义参数合同**：在 Registry 定义 `ModelToolDefinition` 和 JSON Schema；Handler 还要做服务端校验。拒绝未声明字段和非法 JSON。
3. **实现只读 Handler**：放在 `src/fishery_ai/tools/handlers/` 下的领域文件中。需要当前水质时只依赖注入的 `CurrentWaterQualityReader`；不读取 Scenario、模拟 Packet、原始硬件包或任意文件。
4. **静态注册**：更新 `tools/registry.py` 与 `registered_names()`。禁止目录扫描、动态 import、`eval`、`exec` 或配置驱动的函数名。
5. **添加 Catalog metadata**：`tools/catalog.py` 只负责名称、说明、状态和 UI 展示；它不能授予权限或注册执行器。
6. **审查 Policy**：`resources/tools/tool_policies.json` 是包内默认值；用户选择保存在 Git ignored 的 outputs 配置。新工具不应默认开启，除非产品要求和审查明确批准。
7. **经过 Executor 与应用协调器**：复用 `ToolExecutor` / `ToolCallingService`，不要从 Web 直接调用 Handler，也不要复制 Tool Loop。
8. **保持状态边界**：READ ONLY；不写 Snapshot、数据库、设备、文件或阈值。当前每轮最多一个调用、一轮、两次模型请求。
9. **补测试**：覆盖参数、错误状态、预算、取消、NO_DATA/质量边界、Policy、能力门禁、结果大小、Secret/trace 和零网络。

## 当前水质 Tool 的示例边界

`get_current_water_quality` 的处理方式是：

```text
ToolExecutor
→ 已注册 Handler
→ CurrentWaterQualityReader.query()
→ DiagnosisService.diagnose(view.reading)
→ 限定 JSON Result
```

没有 Snapshot 返回 `NO_DATA`；若有 Snapshot，`INVALID`、`PARTIAL`、`STALE` 会保留为数据状态。查询时重评 freshness，不更改 Store。实验评分 Tool 使用独立 `WaterQualityScoringService`，不替代规则 Finding，也不是专业标准。

## 不能做的事

- 不把 UI 的 Scenario Apply、模型能力 Probe、数据库写入、设备控制或任意 shell 包成 Tool。
- 不让模型提供文件路径、模块路径、命令或任意 Provider 参数。
- 不把 Tool Result 提升成 System 指令；不向模型暴露 traceback、Secret、Credential 路径或不必要的原始数据。
- 不因为 ProtocolSpec 可以编码 Tool 请求，就推断具体模型已支持。正式模型仍须满足精确 Runtime 能力合同。
- 不因新增 Tool 放宽单 Tool / 单 round 限制，也不把有限对话变成 Agent。

当前合同和模块关系见[只读 Tool 当前实现](READ_ONLY_TOOL_CALLING.md)。

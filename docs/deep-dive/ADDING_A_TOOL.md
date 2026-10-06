# 如何新增一个只读 Tool

## 先判断是否需要

Tool 是受控程序功能，不是“由谁决定调用”。当前 Analysis 是固定 Snapshot → Diagnosis → RAG，加模型可选 Tool；Assistant 实验路径不预注入事实，按需使用 Tool。Manual 不执行 Tool。

只有回答需要系统事实或确定性计算时才需要工具。当前两个工具是查询水质和实验评分；不能把模型 Capability、Provider 参数或网页 Apply 操作包装成 Tool。

## 标准步骤

1. **业务逻辑先行**：在独立 Domain / Service 实现确定性算法。无模型、网络或 UI 依赖；评分示例为 water_quality_scoring.py。
2. **输入输出**：输入 JSON object，声明 JSON Schema 和未知字段策略。当前两工具只接受 `{}`。输出使用稳定业务状态；NO_DATA、缺失、无效与陈旧分别处理，保留时间和来源。
3. **Handler**：放 tools/handlers/ 的领域文件。只从 CurrentWaterQualityReader 获取 canonical view，再调用服务；不读取 Scenario、原始包或文件，不修改 Store。
4. **Registry**：静态添加名称、ModelToolDefinition 与固定 Handler；同步 registered_names()。不加动态注册、模块路径、扫描、eval / exec。
5. **Catalog**：补 display_name、说明、READ ONLY、experimental 等元数据。Catalog 只能展示，不能赋权或注册 Handler。
6. **默认 Policy**：resources/tools/tool_policies.json 的 analysis / assistant 分别审查。新工具默认关闭；现有 Assistant 默认 get_current_water_quality 保持不变。
7. **Tool Manager**：读取 Catalog 自动显示，在相应模式显式勾选保存。用户设置仍位于 outputs/tool-policies/tool_policies.json，不进入 Profile。
8. **模型门禁**：精确 Runtime.tool_calling 必须 SUPPORTED。已有 Preset 固定合同与 Managed Evidence 不因增加 Tool 自动改变；Tool 的存在不能证明模型支持协议。
9. **Executor**：授权和注册同时成立；再检查参数、次数、结果大小、取消。新的参数合同若有字段，必须显式扩展校验，不能把当前空参数检查删掉。
10. **应用接入**：复用 ToolCallingService，不复制 Loop。Analysis 保留初始 Facts / Rules / RAG；Assistant 不自动预执行所有 Handler。
11. **Activity / Trace**：右侧通用 JSON 展示业务 Result；Trace 只记录名称、状态、耗时、请求与 Usage。不得记录参数原文、Secret、完整 Prompt、私有路径或 traceback。
12. **测试**：服务公式/边界、Registry、Policy、参数、NO_DATA、PARTIAL、INVALID、STALE、大小预算、取消、两种应用、两轮 Usage、原 Tool、无网络和安全渲染。
13. **人工验证**：先离线 Mock；真实模型由用户确认 REAL NETWORK REQUEST。选 OFF + Normal，先只勾新 Tool，再与旧 Tool 一起勾选，核对右侧 Activity 和固定事实。
14. **最后审查**：Python / Browser 回归、JS syntax、链接、diff、敏感扫描。不得写设备、DB、阈值，不新增 Agent、自动重试或多轮预算。

## 最小示例（说明性片段，不是已注册工具）

```python
# tools/handlers/example.py
def example_read_only_tool(*, reader, service):
    view = reader.query()
    if view is None:
        return {"status": "NO_DATA", "value": None}
    return {"status": "OK", "value": service.evaluate(view.reading)}
```

在 Registry 的静态 entries 中加一项，Handler 通过固定依赖绑定；代码示意：

```python
definition = ModelToolDefinition(
    name="example_read_only_tool",
    description="只读计算当前事实，不修改系统状态。",
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
)
entry = ToolDefinition(definition, partial(example_read_only_tool, reader=reader, service=service))
```

同步 allowlist 与 Catalog 后，默认 Policy 不加入它。经用户明确授权，现有 ModelRequest / Executor / Activity 即可复用；仍是最多一个 Tool Call、一个 Tool round、两次模型请求，第二轮 tool_choice=none。一次返回两个调用仍 TOOL_CALL_LIMIT，第二轮继续调用仍 TOOL_ROUND_LIMIT。

## 当前评分工具实例

score_current_water_quality({}) → Reader → WaterQualityScoringService → ToolExecutionResult。

- 正常区间共享 DiagnosisService：20–30℃、pH 7–8.5、DO ≥5；高 DO 不扣分。
- 分项 = clamp(100 − 超出边界距离 × penalty, 0, 100)。penalty：温度10、pH40、DO20；已有有效分项算术平均，最后保留一位小数。
- 示例 34℃ / pH7.5 / DO2.2：60、100、44 → 68.0 / WARNING。
- NO_DATA 不评分；INVALID 为 NOT_SCORABLE；PARTIAL 平均已有指标并列 missing_components；STALE 不扣分，但 warning=SENSOR_STALE。
- 结果包含 score / grade / components / quality / freshness / warnings / scoring_version、独立 water_quality / evaluated_at 和 **EXPERIMENTAL / NOT PROFESSIONAL STANDARD**。
- GOOD ≥90、ACCEPTABLE ≥70、WARNING ≥50、CRITICAL <50 仅实验展示标签。分数不能替代 Diagnosis Findings，也不能作为专业养殖控制依据。

代码位置见[STRUCTURE](../STRUCTURE.md)，本轮实施与测试见[Analysis Tool Calling](ANALYSIS_MODEL_TOOL_CALLING_V1.md)。

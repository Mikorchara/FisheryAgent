# 项目结构

```text
Fishery_AI_Prototype/
├─ README.md
├─ AGENTS.md
├─ pyproject.toml
├─ src/fishery_ai/
│  ├─ contracts.py
│  ├─ domain.py
│  ├─ repositories.py
│  ├─ knowledge.py
│  ├─ model_gateway.py
│  ├─ openai_compatible_adapter.py
│  ├─ application.py
│  ├─ observability.py
│  ├─ composition.py
│  ├─ __main__.py
│  └─ resources/{knowledge,mock}/
├─ tests/
├─ scripts/
└─ docs/
   └─ deep-dive/
```

- `contracts.py`：不可变的水质、检测、证据、请求和结果合同。
- `domain.py`：确定性水质诊断规则。
- `repositories.py`：固定的 Mock 传感器和检测输入。
- `knowledge.py`：TF-IDF 检索及证据构建。
- `model_gateway.py`：Profile、RuntimeSnapshot、网关合同与 `MockGateway`。
- `openai_compatible_adapter.py`：基于 SDK 的 OpenAI-compatible 传输和流式响应。
- `application.py`：固定 Chat/Advice 编排与模型输出解析。
- `observability.py`：仅记录允许字段的 JSONL Trace。
- `composition.py` 与 `__main__.py`：离线组件装配和命令行入口。
- `resources/`：打包的知识快照、来源说明、Profile 和 Mock 场景。
- `tests/`：离线合同、网关、编排和 Trace 检查。
- `scripts/`：从源码工作区启动 Mock 演示的入口。
- `docs/`：使用指南；`docs/deep-dive/` 保存详细历史报告和验证计划。

当前项目没有 Agent、Tool Calling、Memory 或真实模型部署模块。

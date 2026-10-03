# Fishery AI Prototype

独立的智慧渔业 AI 架构原型：程序提供水质事实与确定性诊断，LLM 解释和建议，TF-IDF RAG 提供背景知识。当前固定 Chat/Advice 流程支持离线 Mock 与显式 Cloud/Local 请求，尚未实现 Tool Calling 或 Agent Loop。

## 与其他项目的关系

- `D:\Fishery_Project` 是正式生产项目，永远只读；本原型不导入其模块、不连接其数据库、不控制其硬件。
- Fishery_AI_Prototype 验证领域数据、模型接入和执行边界，使用包内确定性 Mock 输入。
- LLM_Lab 用于通用 LLM 学习实验；本项目围绕渔业业务合同与集成。

## 当前架构

```text
MockRepository（未来由传感器 Adapter 提供相同快照）
  → WaterQualityReading → DiagnosisService → TF-IDF RAG
  → Orchestrator → ModelGateway → OpenAICompatibleAdapter / OpenAI SDK
  → AnalysisResult → JSONL Trace
```

Observed Facts、Rule Results、RAG Evidence、Inference、Recommendations、Uncertainty 分开。背景疾病知识不能证明现场有病，传感器值和规则结论不由模型生成。检测合同已存在，但 Detection / 历史不进入默认分析流程。

## 三种模型使用方式

| 模式 | 用户操作 | 边界 |
| --- | --- | --- |
| Preset | 选择 Model、Thinking、Normal/Streaming | 开发者固定发布合同；不读取动态 Evidence 或 Probe 改合同 |
| Managed Custom | 保存连接，按需显式验证高级能力 | R3 编码、R4 解析证据、R5 单项 Probe；UNKNOWN 仍可 Normal + AUTO |
| Manual Expert V1 / V2 | V1 使用 Saved Connection；V2 保存独立 Experiment 与 Raw JSON | 共用传输与 Stop，不经过能力解析、RAG、诊断或 AnalysisResult，不执行 tool_calls |

当前 Preset 为 **Qwen 3.8 Flash、DeepSeek Flash、Ollama Qwen3.5 4B**，合同均为 1.0.0。各发布 OFF + Normal、ON + Normal、ON + Streaming；默认 Qwen OFF + Normal。未发布组合不会发送。详见[发布依据](docs/validation/PRESET_SIMPLIFICATION_AND_FIRST_PUBLICATION.md#12-用户人工验收后的精确多模型登记当前状态)。

## 凭据原则

正式连接：**PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING**，Profile 只存 credential_ref。Web 可管理私有凭据，外部进程变量只读，Auth NONE 无需 Key。修改后新请求立即生效，在途请求保持不可变 CredentialSnapshot。

Manual V2 仅使用同一私有目录中的独立 manual.env，不与正式 .env 或进程 Key 混用。旧源码根 .env 不读取、不迁移、不回退；已删除的 .env.example 不恢复。Secret 不回显、不写入 Profile / Experiment / Trace / 文档 / LocalStorage。

## 快速开始

Python 3.11+，在项目根目录 PowerShell 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m fishery_ai demo --scenario low_oxygen
.\.venv\Scripts\python.exe -m fishery_ai web
```

Web 默认只监听 http://127.0.0.1:8765。启动不自动生成；真实请求、连接测试和 Probe 均需显式确认 REAL NETWORK REQUEST。Mock Demo 始终离线，即使选择 cloud-demo / local-demo 也不会访问模型。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --test tests/test_browser_streaming.cjs
node --check src/fishery_ai/resources/web/app.js
git diff --check
```

## 当前数据与实现状态

- 水质来自包内 resources/mock/scenarios.json：normal、low_oxygen、partial、stale、partial_stale；不是现场数据。时间也是固定 fixture，不使用今天时间推断场景 freshness。
- 已有不可变领域合同、确定性水质规则、TF-IDF RAG / Grounding、三模式模型接入、应用 Streaming、后端 SDK I/O Cancellation、私有 Credential CRUD、Usage 和允许字段 JSONL Trace。
- 知识快照来源 commit 与 provenance 缺口见[来源说明](src/fishery_ai/resources/knowledge/SOURCE.md)；检索分数不是养殖诊断置信度。Trace 与本地配置写入 Git ignored 的 outputs，无自动 retention 清理。
- 尚无真实传感器 Adapter、历史快照存储、Tool Calling、Agent Loop、Memory、生产集成或 Fine-tuning。Stop 可终止本地 SDK I/O，不能保证云端计算或计费已经停止。

## 下一阶段与文档

先准备 canonical 水质数据 / telemetry Adapter，再定义只读 Tool Calling 与工具执行边界；不让模型直接解析硬件原始 JSON 或修改阈值。Agent Loop 要在只读工具和权限边界验收后单独批准。

- [按任务查文档](docs/README.md)
- [构建运行与界面操作](docs/BUILD_RUN.md)
- [当前架构](docs/architecture/CURRENT_ARCHITECTURE.md)
- [水质场景与未来 telemetry](docs/research/WATER_QUALITY_SCENARIO_AND_TELEMETRY_PREPARATION.md)
- [路线图](docs/ROADMAP.md) / [历史索引](docs/history/README.md)

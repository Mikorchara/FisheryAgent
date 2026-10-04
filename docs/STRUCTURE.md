# 项目结构

目录职责以当前源码为准。更细的运行数据位置见[维护者文件位置地图](deep-dive/PROJECT_DATA_AND_CONFIG_LOCATIONS.md)。

    Fishery_AI_Prototype/
    ├─ src/fishery_ai/   可安装的 Python 包、业务代码和包内运行资源
    ├─ tests/            离线自动化回归，不参与正常运行，必须保留
    ├─ scripts/          开发 / 验证辅助工具，不是正常运行所必需
    ├─ docs/             用户指南、路线图和少量仍有价值的专项资料
    └─ outputs/          本机运行时配置和记录，Git 忽略；不是源码

## 根目录

pyproject.toml 定义安装包、Python 版本、依赖和包资源。README.md 是简要入口，AGENTS.md 约束开发边界。.venv/ 是可重建的本地环境。

## src/fishery_ai/

- contracts.py、domain.py、repositories.py：领域合同（含共享 Freshness 判断）、确定性诊断与 Mock / Demo 场景生成。
- telemetry/：内置 / 用户情景模板管理与动态模拟入口；Template 经 Simulator、SimulationAdapter 转成既有 WaterQualityReading，再写入进程内 CurrentSnapshotStore。Web 与 CLI 水质入口统一使用这条管线。
- application.py、model_gateway.py、openai_compatible_adapter.py：固定分析流程和模型传输。
- presets.py、protocol_specs.py、providers.py：固定 Preset、协议编码和 Provider 元信息。
- capability_store.py、evidence_resolver.py、capability_probe.py：Managed Custom 的能力证据与显式验证。
- credentials.py、credential_paths.py、project_env.py：凭据读取、用户私有路径和受控写入。
- manual.py、manual_experiments.py：Manual V1/V2 Raw 请求与实验存储。
- web.py、resources/web/：本地开发者界面。
- resources/scenarios/water_quality/：五个只读内置水质情景模板，保存输入意图与观测年龄。
- resources/scenarios/detection/：normal / count_jump 固定检测事件，未增加 Detection Simulator。
- resources/mock/、resources/knowledge/、resources/profiles/：Mock 模型 Profile、知识和固定连接/方案数据。

telemetry/ 的最小结构：

```text
telemetry/
├─ __init__.py   对外入口
├─ models.py     SimulationPacket / SimulationRecipe
├─ simulator.py  baseline + 数值覆盖 / missing / invalid
├─ adapter.py    sim-v1 校验与 canonical 合同转换
├─ snapshot.py   最后一次接收 / Apply 的原始 canonical reading；未写入时返回 None
├─ current.py    CurrentWaterQualityReader；只读捕获并生成 query-time view
└─ scenario_templates.py  Template 合同、Builtin / User CRUD 与统一 Apply 管线
```

依赖方向：Telemetry → WaterQualityReading → Domain / Diagnosis。WaterQualityReading、ObservedFacts、DiagnosisService 保留原位置，Domain 不依赖 Telemetry。详细用法见[水质与 telemetry](deep-dive/WATER_QUALITY_SCENARIO_AND_TELEMETRY_PREPARATION.md)。

## tests/

使用虚构数据、临时存储和 Mock Transport；默认禁止真实网络。tests/fixtures/ 保存少量兼容性测试资产。测试保护运行边界，目录简洁不能替代回归覆盖。

## scripts/

当前保留精确 Ollama Identity 的单项资格验证工具。它只供维护者使用，必须显式确认；不自动发布 Preset，也不是 Web 启动依赖。

## docs/ 与 outputs/

docs/ 顶层只保留构建运行、路线图、故障排查、评审和结构说明；deep-dive/ 放无法在结构概览中讲清的当前专题。outputs/ 中的自定义 Profile、Evidence、Experiment、scenario_templates/water_quality/、Trace 和资格摘要可能包含用户维护数据；不要由清理脚本一概删除。

Web application 创建一个共享 CurrentSnapshotStore 和一个 CurrentWaterQualityReader。Store 保留最后一次接收 / Apply 的原始 immutable reading，**Latest != Fresh**。Reader.query() 捕获一次原对象，按当前查询时间重新评估 Freshness，返回冻结的 CurrentWaterQualityView(reading, evaluated_at)；不改变 Store、数值、Quality 或原始时间。

observed_at 是观测时间；retrieved_at 是程序当时取得数据的时间；evaluated_at 是本次查询时间，**evaluated_at != retrieved_at**。年龄判断由 contracts.py 的 evaluate_freshness() 共享，age > stale_after_s 才 STALE；配置由 composition / create_app 注入。

Current API、Apply 后预览、Normal / Streaming 都经同一 Reader；Diagnosis 使用查询视图。分析开始时固定视图，进行中的请求不受后续 Apply 影响。重启为空；没有当前快照时返回 NO_DATA，Reader 不自动生成 normal。

**Scenario generation != Current state read**：显式 scenario 兼容调用仍先走模板生成 / Apply，再查询。CLI / Demo 的 Orchestrator 后备保留，用来生成模拟输入。MockRepository.demo_snapshots 惰性创建，旧 snapshots 属性仅是兼容别名；Web current Reader 不依赖该 Store。未来 Tool 只能注入 Web 的 CurrentWaterQualityReader，不能通过 Repository 场景生成获取“当前状态”。

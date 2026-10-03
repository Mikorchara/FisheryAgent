# 项目结构

**CURRENT · 2026-10-03**。本文件描述实际模块边界，不按旧报告的行数或目录草图推断当前行为。

## 文档布局

```text
docs/
  README.md / BUILD_RUN.md / STRUCTURE.md / ROADMAP.md / TROUBLESHOOTING.md
  DOCUMENTATION_AUDIT.md     # 原文档逐份分类和搬迁映射
  architecture/              # 当前架构总览
  guides/                    # 私有凭据指南、评审模板
  research/                  # 水质/telemetry 与既有设计研究
  validation/                # 当前 Preset 发布依据、本地验证参考模板
  history/                   # implementation / validation / obsolete
  deep-dive/README.md        # 兼容旧入口，转向新导航
```

## 当前源代码职责

Python package 位于 src/fishery_ai，包资源由 importlib.resources 读取，不依赖源码目录运行。

| 文件 / 资源 | 职责 |
| --- | --- |
| contracts.py | WaterQualityReading、Quality/Freshness、ObservedFacts、Detection、RuleFinding、AnalysisResult、Usage |
| repositories.py / resources/mock/scenarios.json | 固定水质与 Detection Mock；stale_after_s 可配置 |
| domain.py | 唯一确定性水质 DiagnosisService；每指标最严重 Finding，规则不让模型决定 |
| knowledge.py / resources/knowledge/ | TF-IDF、查询扩展、关键词与意图加权、稳定 Evidence ID；legacy 知识快照 |
| application.py | 固定 Chat/Advice、Grounding prompt、Normal/Streaming、最终 JSON 解析 |
| composition.py / __main__.py | 离线 Demo 装配、CLI，Mock 禁网 |
| providers.py | 静态 ProviderRegistry / AuthSpec，注册不依赖 Secret |
| model_gateway.py / model_options.py | Profile、不可变 RuntimeSnapshot、请求/事件/网关、选项与 CapabilityValidator |
| protocol_specs.py | R3：如何编码参数，不授权能力 |
| evidence_resolver.py / capability_store.py / official_capabilities.py | R4：精确 Identity 的 Evidence 合并，冲突 UNKNOWN；当前官方声明表为空 |
| capability_probe.py | R5：显式单项最小 Probe，无业务分析、不执行工具 |
| presets.py / resources/profiles/presets.json | 三个新固定 Template + Variant / protocol / version 合同，不加载动态 Evidence |
| custom_profiles.py | Managed 连接的存储、唯一不可变名称、连接参数校验 |
| credentials.py / credential_paths.py | 只读 CredentialStore、不可变快照、每项目用户私有路径 |
| project_env.py / secure_files.py | 受控 Writer、ACL、revision、锁、私有 staging、原子替换与恢复 |
| web_security.py | loopback Host、同源 Origin、CSRF、无 CORS |
| execution.py | RequestHandle、取消状态与在途请求控制 |
| manual.py / manual_experiments.py | V1 Raw 合同与 V2 独立实验 CRUD / Target；不进入正式能力系统 |
| openai_compatible_adapter.py | 唯一 SDK 适配层；ProtocolSpec 编码、Usage、受控 retry、Manual transport、可取消 async bridge |
| observability.py | JSONL Trace 字段白名单，不落 Prompt / 正文 / Key |
| web.py / resources/web/ | 薄 Flask 路由与 HTML/CSS/JS，共用服务，不复制业务判断 |
| real_validation.py / scripts/ | 显式历史验证工具，仍复用 private credential composition，旧模型不自动恢复 |

## 三模式与存储

Preset → 固定发布组合 / ProtocolSpec → 公共 Gateway。
Managed → R4 Resolved Capability / 选项门禁 → R3 ProtocolSpec → 公共 Gateway。
Manual V1/V2 → Raw Request → 公共 transport，跳过上述正式参数流程。

正式 Credential 位于用户私有 credentials/.env，V2 使用独立 manual.env。Profile/Experiment 只有引用，没有 Secret 或凭据文件路径。outputs/custom_profiles、capability-evidence、manual-experiments、traces 等均 ignored；.venv、模型权重、源码旧 .env 也不跟踪。

## 水质与未来 Adapter

默认分析只使用 MockRepository.water_quality(scenario) 返回的 WaterQualityReading。ObservedFacts.detection_summary 是可选扩展点，目前默认 None；Detection fixtures 不是 YOLO 集成。

未来 Raw Hardware Packet → Telemetry Adapter → 同一 canonical WaterQualityReading → Snapshot Store / Domain Service。真实字段未知，本轮没有实现 Adapter 或重复 WaterQuality 模型。Tool 读取 canonical 当前/历史快照，不直接依赖 packet；历史 Store/Tool/Agent 目前都未实现。

## 测试布局

tests/test_v01.py 覆盖基础合同/规则/检索/装配；tests/test_water_quality_matrix.py 补充边界与质量组合，仅作离线 fixture，不扩展 UI。其余 Python 测试覆盖 credential、protocol、evidence、probe、Preset、Manual 和执行；test_browser_streaming.cjs 使用 Node 内置测试。

tests/fixtures/historical_model_assets 是明确历史 compatibility fixture，仅被相应测试 overlay 使用，正常启动不恢复其中模型。当前活动 Built-in 只有 Mock，三个发布 Preset 来自新目录。

[架构总览](architecture/CURRENT_ARCHITECTURE.md) / [水质研究](research/WATER_QUALITY_SCENARIO_AND_TELEMETRY_PREPARATION.md) / [文档审计](DOCUMENTATION_AUDIT.md)

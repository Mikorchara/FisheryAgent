# 当前架构总览

**CURRENT · 2026-10-03**。依据当前 src/fishery_ai、资源与测试；源码高于本文。此页是边界速查，测试次数和逐次真实验证留在维护/历史报告。

## 业务分析与 Grounding

```text
MockRepository.water_quality(scenario)
  → WaterQualityReading
  → DiagnosisService / RuleFinding[]
  → KnowledgeService / TF-IDF Evidence[]
  → Orchestrator（Chat / Advice，Normal / Streaming）
  → ModelGateway → OpenAICompatibleAdapter → OpenAI SDK
  → AnalysisResult → JSONL Trace
```

确定性事实由程序提供：值、时间、规则、知识来源、运行模型身份。RAG 是背景知识；没有症状、检测等直接证据不能据此诊断具体疾病或直接推荐药物/剂量。Inference、Recommendations、Uncertainty 与 ObservedFacts / Rule Results 分开；结构解析只针对 final content，不依赖 reasoning trace。

默认只有当前 Mock 水质快照，DetectionSummary 为 None，历史不进入提示词。Quality 与 Freshness 是独立维度。无规则告警不等于生物学“最佳水质”，缺失/过期/无效也不是现场正常证明。[当前数据、规则与缺口](../research/WATER_QUALITY_SCENARIO_AND_TELEMETRY_PREPARATION.md)。

## 三模式汇合与隔离

| 模式 | 决策与参数 | 共享基础设施 | 不进入的流程 |
| --- | --- | --- | --- |
| Preset | 版本化固定 Template + Variant，明确发布组合及 ProtocolSpec | Credential、RuntimeSnapshot、Gateway、Usage、Streaming、Trace、Stop | 动态 Evidence / R4 / R5 不改合同 |
| Managed Custom | 精确 Identity → R4 有效能力 → 选项校验 → R3 编码；UNKNOWN 可显式 R5 Probe | 同上 | 不自动制作 Preset |
| Manual V1 | Saved Connection + Raw JSON | Credential、公共 Manual transport、timeout、retry=0、Stop、安全错误 | Capability / Defaults / R3 改写 / Orchestrator / Trace |
| Manual V2 | 独立 Experiment + 自定义 Target + Raw JSON | 独立 manual CredentialStore、同一 transport / Stop | 正式 Profile、R4/R5、Preset、Domain/RAG/AnalysisResult |

当前 Preset：Qwen 3.8 Flash、DeepSeek Flash、Ollama Qwen3.5 4B，合同 1.0.0；各发布 OFF Normal / ON Normal / ON Streaming。默认 Qwen OFF Normal，不发布 AUTO 或 OFF Streaming。维护者不能从两个独立能力推出未验证组合；[精确发布依据](../validation/PRESET_SIMPLIFICATION_AND_FIRST_PUBLICATION.md#12-用户人工验收后的精确多模型登记当前状态)。

Manual V2 的 Service Name 只是自由标签。页面 Model 是权威 ID；缺失 raw model 时仅在准备副本中注入，不改实验存储或编辑器；相同 model 兼容、不同拒绝。返回 tool_calls 只展示、不执行，无任意 Headers / Authorization override。

## R3 / R4 / R5

Identity = service_id + adapter_id + normalized base_url + exact model。URL scheme/host 和 trailing slash 规范化，不根据 display_name、model_family、URL 关键词或相似模型继承能力。

- R3 ProtocolSpec：只描述开关、stream、usage、token field、effort 如何编码，不能充当 Capability Evidence。Preset 冻结版本，Managed 按冻结连接选择；Adapter 只使用已有协议，不引入 Provider 业务分支。
- R4 Evidence Resolver：合并精确项目声明、官方信息、Metadata、Probe；每条有 source/time/origin。无证据 UNKNOWN，冲突 UNKNOWN + EVIDENCE_CONFLICT，不用来源优先级掩盖矛盾。当前 Clean-room 后官方声明表为空，不从旧报告重建。
- R5 Explicit Probe：单项、用户确认、最小请求、retry=0，不运行水质分析。临时绕过只针对 Probe 目标；成功/明确不支持写 Evidence 再 Resolve，网络失败不写否定结论。ON/OFF 独立，ON Streaming 有独立组合结果。
- Capability、Evidence、Runtime Defaults、本次运行选择分开。保存偏好不是证据；Managed 不可用偏好临时安全回退 AUTO / Normal，历史偏好保留。Preset 不适用动态回退来扩大发布范围。

## R2 Credential 安全边界

正式优先级 PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING。固定路径由 credential_paths 的启动装配确定；Profile 仅引用 credential_ref，Gateway 不依赖文件位置。Auth NONE 不要求凭据，不触碰文件来源。外部 process environment 只读，明确空变量也不偷偷回退。

Manual V2 使用同一项目私有 credentials 目录中的 manual.env；process_env={}，不读正式 .env 或进程 Key。V1/Managed/Preset 不读 manual.env。旧源码根 .env 不读、不迁移、不 fallback；Flask load_dotenv=False，不污染 os.environ。

Writer 保留文本格式，做路径/ACL/link/hardlink/revision/私有 staging/同卷替换检查；无法确认则拒绝。Web 加 Host / Origin / CSRF，无 CORS；只显示状态/来源/不透明 revision，不返回旧 Key。新请求 hot reload，旧请求持有不可变 CredentialSnapshot；轮换使模型列表/连接测试授权失效，不删除 Evidence / Defaults。详见[私有存储指南](../guides/R2_PRIVATE_CREDENTIAL_STORAGE_MIGRATION.md)。

## Streaming / Cancellation / Usage

Normal 和 Streaming 使用同一 Orchestrator 业务逻辑。应用事件先 facts/rules/evidence，正文 content_delta，reasoning_delta 独立开发调试区，usage，completed / failed；完整 final content 才解析结构。secret/error 返回安全白名单，不输出 SDK 原始敏感异常。

Web 登记 RequestHandle，Stop 请求触发 Adapter 请求专属 async bridge 取消 SDK await 并关闭 stream/client。浏览器 Abort、本地后端 I/O 停止、远端实际计算停止是不同层次；云端计费/推理停止没有保证。USER_CANCELLED 不重试、不生成完成结构或 Capability Evidence。没有 handle 的历史同步调用不会自动获得跨线程取消能力。

Usage 由 Provider 提供，缺失显示 unavailable；reasoning tokens 与 reasoning text 不等价。Trace 只记录白名单元数据，不写完整 Prompt、输出、Key 或完整配置。Manual 不写 Fishery Analysis Trace。

## 未来硬件和只读工具边界

Raw Hardware Packet → Telemetry Adapter → canonical WaterQualityReading → Snapshot Store / Domain Service → 只读 Tool → LLM。原始 packet 不直接交给 Tool 解释；字段/单位/时间变化在 Adapter 消化，设备状态与原始审计留在受控接收边界。

本轮没有 Adapter、历史 Store、Tool execution 或 Agent 实现；先拿硬件样例，再定义只读输入/输出、allowlist、timeout/取消、审计与访问范围。确定性 Diagnosis 继续由程序负责，Agent 不直接操作硬件、DB mutation 或阈值。

[模块与文件](../STRUCTURE.md) / [路线图](../ROADMAP.md) / [实施历史](../history/README.md)

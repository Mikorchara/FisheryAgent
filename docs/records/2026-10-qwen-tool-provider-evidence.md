# Qwen 首轮 Tool Calling 取证：凭据预检阻塞

日期：2026-10-09。依据：[接管审计 §12.1](2026-10-codex-takeover-audit.md)。

## 1. 结果

**BLOCKED：正式 CredentialStore 返回 `CREDENTIAL_FILE_ERROR`，实际模型请求 0 次。**

本轮没有获得 Qwen Provider 响应，因此无法判断三个单 Tool 或三个 Tool 同时开放时的真实选择行为。没有重试、扩展到其他模型，或把本次阻塞写成 Capability 结论。

## 2. 正式入口预检

预检调用当前实际代码：

```text
assistant_profile("dashscope-qwen38-flash-r1")
  → private_project_location(当前工作区)
  → CredentialStore(location.env_path, private_location=location)
  → ProfileRegistry([profile], store).snapshot(profile.profile_id)
  → CREDENTIAL_FILE_ERROR
```

这与 Web / validate-real 使用的正式私有凭据来源一致，保持 PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING。没有直接打开凭据文件或访问 Secret 值；仅由正式 Store 尝试构造请求所需 Snapshot，并读取安全错误码。

Preset Profile 加载之后、RuntimeSnapshot 创建阶段即失败，未进入 Gateway / SDK 请求阶段。这个安全错误并不等同于 SECRET_MISSING，也不足以断言是 ACL、文件内容、编码或其他具体原因；本轮未进一步读取私有文件、诊断内部异常或修改权限。

当前目标的固定连接为：

| 字段 | 值 |
|---|---|
| Preset | dashscope-qwen38-flash-r1 |
| Service | dashscope |
| Adapter | openai_chat |
| Base URL | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| Exact Model | qwen3.8-flash |
| 预定运行方式 | Thinking OFF / Normal |
| 预定重试 | 0 |
| 预定输出预算 | 每次最多 256 tokens |

未修改这些配置、合同或 Evidence。

## 3. 四项实验执行状态

| 项目 | 预定暴露的 Tool | 状态 | 真实请求数 |
|---|---|---|---:|
| 1 | get_current_water_quality | NOT_STARTED：凭据预检阻塞 | 0 |
| 2 | score_current_water_quality | NOT_STARTED：凭据预检阻塞 | 0 |
| 3 | search_fishery_knowledge；固定 query 为“鳗鲡低氧表现” | NOT_STARTED：凭据预检阻塞 | 0 |
| 4 | 三个 Tool；与第 3 项相同知识问题 | NOT_STARTED：凭据预检阻塞 | 0 |

以上是实验计划，**不是实际已发送的 Tool 集合**。没有执行 Tool Handler、完整 Analysis、Request #2 或 History 对照。

所有项目的网络取证字段均 unavailable：

- 实际发送的 Tool 名称集合、Knowledge required-query Schema、tool_choice：未发送。
- Provider 返回 model、finish_reason、raw tool_calls、function.name、arguments：没有响应。
- Provider 原始结果与 normalized ModelResponse 一致性：没有可比较对象。
- Input / Output / Total Token Usage：unavailable，不能用 Provider 返回 0 tokens 表述。

## 4. 对 A–E 的诊断结论

| 问题 | 本轮结论 |
|---|---|
| A：三个单 Tool 场景是否都能正常调用？ | 未验证，0 次请求。 |
| B：Knowledge 能否正确生成带 query 的调用？ | 未验证。 |
| C：三个 Tool 同时开放是否仍调用 Knowledge？ | 未验证。 |
| D：未调用来自 Provider 还是 Adapter 丢失？ | 无 Provider 响应，无法区分。 |
| E：是否有证据支持 parameterized Tool 不受支持？ | 本轮没有新增证据。前次离线 SDK 检查证明标准请求与响应可传输 / 解析，不证明真实 Qwen 的选择或能力。 |

当前阻塞属于执行环境的正式凭据预检失败，不是 Qwen Tool Calling 拒绝，更不是 UNSUPPORTED。

## 5. 安全与下一步

未记录 Credential、Authorization Header、完整 System Prompt、用户历史、私有凭据路径或原始异常。没有 project_root/.env fallback、凭据复制、临时明文 Key、ACL 修改、环境变量 mutation。

下一步应在能够通过正式 CredentialStore 预检的正常用户进程中执行同一四项计划。仍保持首轮、retry=0、OFF / Normal、256-token 上限、最多四次请求；遇错停止，不自动转为全链路或补充探索。

本轮不新增 UI、验证脚本或产品修复。不能将预检阻塞视为四项实验完成，也不建议依据它修改 Prompt / Adapter / Capability。

## 6. 工作树边界

开始时已有：`docs/others.md` 删除，以及未跟踪的 `docs/notes.md` 和前次接管报告；这些变化保持原状。

本轮仅新增本报告。没有修改源码、测试、Policy、Registry、Handler、UI、Preset / Capability 合同或生产项目；没有 commit / push。

# T5 · DS_1 Tool Calling 显式验证

## 实现边界

- 服务：`src/fishery_ai/tool_capability_probe.py`，复用 ToolCallingService，不复制闭环。
- Web：`POST /api/profiles/<profile_id>/tool-probe`，仅 Managed Custom，Host / Origin / CSRF、显式联网确认与已有 RequestHandle。
- Identity：service / adapter / normalized base_url / exact model；不按显示名或厂商继承。
- Evidence：完整闭环成功后记录 `tool_calling=SUPPORTED`、`source=explicit_probe`；R4 Resolver 重新解析。不改 Preset、其他模型或其他能力。
- 限制：non-streaming、唯一只读 Tool、一个 round、最多两次模型请求、retry=0，每次 256 输出 token 上限；不继承运行偏好。
- 失败：网络、鉴权、限流、未调用 Tool、格式错误、第二轮失败、取消或本地执行失败保持 UNKNOWN，不写 UNSUPPORTED；只有 Adapter 识别明确功能不支持的结构化拒绝才写负面证据。

## 本轮唯一真实测试对象

| 字段 | 当前 Saved Connection |
| --- | --- |
| Display Name | DS_1 |
| profile_id | custom-053fa92ab237427b8d21a65c8cd3482b |
| service | deepseek_api |
| adapter / protocol | openai_chat / 现有 DeepSeek ProtocolSpec |
| normalized base_url | https://api.deepseek.com |
| exact model | deepseek-v4-pro |

只使用既有 CredentialStore / 私有凭据来源，不显示、复制或修改 Secret。截图与当前文件一致；不是历史 deepseek-flash。

## 自动验证与真实结果

2026-10-05 本轮仅尝试一次 DS_1 Probe，使用与 Web 相同的私有路径 composition、CredentialStore、Web Probe API 和 RequestHandle；未调用模型列表或进行额外探索。

| 结果项 | 结果 |
| --- | --- |
| 凭据读取 | CREDENTIAL_FILE_ERROR，HTTP 503；现有安全边界拒绝取得凭据 |
| 真实模型请求数 | **0** |
| Request #1 / 合法 Tool Call | 未发送 / 未验证 |
| Tool Result | 未执行；本验证进程 Store 为空，预期可返回 NO_DATA，但未实际调用 |
| Request #2 / 最终正文 | 未发送 / 未验证 |
| Verdict | **UNKNOWN**，环境阻塞，不是模型不支持 |
| Evidence 写入 | **否** |
| Preset / 其他模型 | 未修改、未测试 |

取得上述错误后立即停止，未再次请求、改 ACL、复制凭据、读取源码根 .env 或创建临时明文 Key。错误不能证明具体哪一层权限/安全校验失败，也不能推断 DeepSeek 的 Tool 支持情况。安全摘要保存在 Git ignored 的 `outputs/qualification/t5-ds1-tool-probe.json`，不包含 Secret 或私有 Credential 路径。

离线验证：T5 Python 17 项；T1/T2/T3/T4 分别 29/35/36/22 项；T4/T5/UI Browser targeted 26 项；最终 Full Python 569 项，Full Browser 140 项。JS syntax、Markdown links、diff check、Git 可见源码敏感扫描通过。Browser 使用 Node DOM/fetch fixture，不访问真实浏览器网络；所有自动测试仅临时文件和虚构凭据。

工作树新增 Probe 服务、T5 Python 测试和本报告；修改 CapabilitySource / CapabilityStore / Resolver 的 Tool Evidence 接入、Adapter 明确拒绝分类、Web API、HTML / JS / Browser 测试与只读 Tool 说明。未 commit / push。T1–T4、Credential 架构、固定 Analysis 与普通 Streaming 保持原路径。

## 人工入口

Managed Custom 选择 DS_1 → 进入开发验证 → 真实 Runtime · DS_1 → 确认 REAL NETWORK REQUEST → 验证 Tool Calling 能力。此按钮是新的显式真实请求，切勿将重复点击当成本轮自动验证的一部分。普通 UNKNOWN 请求继续禁止。

下一步建议：由用户在已能正常读取凭据的 Web 进程中进行一次显式人工验证；确认两次请求、Tool Result、最终正文与精确 Identity Evidence。不要为完成验证降低 R2 安全策略。网络失败保持现有证据不变，界面同时显示 Probe verdict 与 R4 当前解析状态，冲突时普通门禁仍关闭。

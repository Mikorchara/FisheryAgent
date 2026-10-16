# 离线测试

所有自动测试使用 Mock、临时目录和虚构凭据，不执行真实 Provider 请求。`tests` 是 Python package；跨文件引用使用完整的 `tests.<子目录>.<模块>`，共享路径来自 `support/paths.py`，不要用工作目录或旧文件深度推算路径。

## 分类

| 目录 | 范围 |
| --- | --- |
| assistant/ | Assistant、SourceRequirement / Receipt / Commit Gate、产品 History Projection |
| domain/ | 水质、Diagnosis、Scoring、Scenario / Telemetry、Grounding 基线 |
| providers/ | Gateway、协议编码/归一化、Preset、Managed 能力与显式 Probe |
| security/ | Credential 来源/写入/ACL、快照、取消与安全传输 |
| tools/ | Registry、Executor、Policy、参数合同、Knowledge、Analysis Tool 接入 |
| web/ | Web API、Session、Normal / Streaming、Manual、Profile 与 Node 页面回归 |
| qualification/ | 长期单次资格工具的授权、预算、身份、报告脱敏与 fake SDK |
| support/ | 固定测试路径与显式历史模型兼容性 overlay；不包含测试用例 |
| fixtures/ | 虚构基线及历史兼容性资料；不参与正常启动 |

`tools/test_backend_boundary.py` 验证参数诊断的标准库依赖、独立旧新模块/类型、patch/序列化、安全投影、安装选择与隔离导入。完整新 Backend 边界及协议/业务闭包测试位于 apps 子包，通过现有 runner 的 backend 选择纳入 FULL PRODUCT。

## 分层入口

项目根目录运行 `python scripts/dev/run_tests.py`，默认是 **FULL PRODUCT**，不包含 qualification。

```powershell
# FAST：日常核心合同
python scripts/dev/run_tests.py fast

# TARGETED：选受影响子系统，或用 unittest 指定模块/方法
python scripts/dev/run_tests.py assistant
python -m unittest tests.assistant.test_history_projection

# FULL PRODUCT：六个正式子系统 + 新侧 Backend/业务闭包；Node 单独运行
python scripts/dev/run_tests.py product
node --test tests/web/test_browser_streaming.cjs

# FULL QUALIFICATION：仅资格基础设施变化时，仍然全离线
python scripts/dev/run_tests.py qualification

# 原 tests discovery：包括旧 product + qualification；apps 新侧用 backend 入口；-t . 保证规范包名
python -m unittest discover -s tests -t .
```

任一 runner 选择加 `--list` 可仅检查发现数量；`all` 包含 product + qualification。FAST 是显式核心模块集合，不替代完整产品回归。Node 页面测试不由 Python runner 隐式启动。

## 清理与覆盖边界

- 已删除 P2B–P2E 的固定 History 研究测试、PowerShell batch / continuation、H 和 P2E manifests / index / preparation generator。
- 原 P2F 测试保留为 `assistant/test_history_projection.py`；Web setup 提炼为没有 test 方法的 fixture，避免导入和继承造成的 26 项重复收集。
- 冻结 transcript 语义、完整 pair 裁剪、JSON escaping、当前问题隔离、历史文字不能生成 Receipt、内部回滚和 Web 不可覆盖等保持正式回归。
- 从旧实验提炼保留：模型无关投影、输入不可变；资格报告 symlink / reparse 拒绝、schema 指纹和精确身份/合同/协议/auth 漂移检查。原有授权、请求预算、retry=0、取消、归一化与脱敏测试保留。
- 历史模型 fixtures 仍被有效兼容性测试使用，与已结束的 History 实验不同；不能作为正常运行 fallback。资格实现已集中到 `fishery_ai.development.qualification`，资格测试使用新路径；旧路径只有模块别名，由既有验证/凭据测试继续覆盖兼容性。
- `qualification/test_qualification_boundary.py` 锁定正常 Runtime 不加载资格实现、包初始化无副作用、旧别名与新实现身份相同、CLI 按需分派，以及产品资源定位不变。移动边界不改变资格预算、授权、报告或正式 History 合同。

原实验和结果见 [records](../docs/records/README.md) 与 Git history；不保留第二套执行资产 archive，不读取或清理 `outputs/` 的真实报告。


R2C-1C 新增 `python scripts/dev/run_tests.py backend`，覆盖 apps/ai_backend/tests 与 apps/ai_service/runtime/tests。FULL PRODUCT 自动包含该组一次；FAST 只纳入协议与来源基础小集合。新侧 Fake SDK/类型独立，不借用旧Runtime对象；迁移差分是显式旧/新两个离线Turn。现有管理Web尚未切新Backend，HTTP回归仍验证旧装配。安装与切换边界见 [Backend入口](../apps/ai_backend/README.md)。

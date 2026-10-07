# 用户私有凭据存储

本文描述正式凭据当前存储边界，不包含任何 Secret 值。

## 固定位置与用途

Windows 默认路径位于当前用户的 `%LOCALAPPDATA%\Fishery_AI_Prototype\project-<stable-id>\credentials\`：

- `.env`：Preset、Managed Custom、Manual V1 的凭据。
- `manual.env`：只供 Manual Expert V2 使用，与正式 Credential Store 隔离。

稳定项目 ID 由应用固定项目根规范化路径计算；Web、Profile、Model 和浏览器请求不能选择目录或文件。移动工作区可能产生另一个项目 ID，不会自动迁移旧凭据。

## 解析与写入

- 正式凭据解析优先级：`PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING`。进程环境只读；`AuthSpec.NONE` 不需要 Credential。
- Manual V2 仅读取自己的 `manual.env`，不合并正式来源。
- 新请求读取当前文件并创建不可变 `CredentialSnapshot`；请求开始后的凭据轮换不改变在途请求。
- Web Credential Manager 写入固定受管文件，检查 owner / DACL、link / reparse / hardlink、私有 staging、revision 与恢复状态；失败时 fail closed。
- 凭据变更使连接测试和模型列表授权缓存失效，不删除 Capability Evidence 或 Runtime defaults。
- Flask 自动 dotenv 加载关闭；应用不把私有文件内容写入 `os.environ`。

用户已人工验收：凭据目录和受管文件为当前用户私有 ACL；Web Create / Replace / Delete、热加载、重启持久性与双页面 revision 冲突按预期工作。本文不记录或读取 Secret。

旧源码根 `.env` 不是运行时来源；不 fallback、不迁移、不自动删除。各运行数据路径见[项目数据与配置位置地图](PROJECT_DATA_AND_CONFIG_LOCATIONS.md)。

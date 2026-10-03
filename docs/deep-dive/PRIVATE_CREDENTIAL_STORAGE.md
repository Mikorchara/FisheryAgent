# 用户私有凭据存储

正式 Credential Manager 不管理源码根 .env。Windows 上，正式与 Manual V2 凭据使用同一固定用户私有目录中的不同文件；路径由应用启动时的项目根路径计算，Web/Profile 不能指定路径。

    %LOCALAPPDATA%\Fishery_AI_Prototype\project-4e5f7b2702af5d742ab9\credentials\
      .env        # Preset / Managed Custom / Manual V1
      manual.env  # 仅 Manual Expert V2

project-... 是项目绝对路径规范化后的 SHA-256 前缀；若工作区根路径变化，计算结果随之变化。真实 Key 不写入本文、Profile、Experiment、日志、Trace 或浏览器存储。

## 解析与更新

- 正式凭据优先级：PROCESS_ENV > 私有 PROJECT_ENV > MISSING。进程环境只读。
- Manual V2 只解析独立 manual.env，与正式凭据和进程 Key 隔离。
- 新请求热加载文件；在途请求持有不可变 CredentialSnapshot。
- 显式写入才调用受控 Writer：路径、owner/DACL、link/reparse/hardlink、私有锁与 staging、revision 冲突和原子替换必须通过检查；无法确认即拒绝。
- 凭据轮换使连接测试 / 模型列表授权缓存失效，但不删除 Capability Evidence 或运行偏好。
- Ollama Auth NONE 不创建或检查凭据文件。

用户验收曾确认目录、文件与 writer lock 由当前用户持有、禁用继承，ACL 只给当前用户与 SYSTEM 完全控制；Web Create / Replace / Delete、热加载、进程重启后的持久性及双标签 revision 冲突均正常。

## 旧源码 .env

旧根目录 .env 不属于运行时来源，不回退、不自动复制、迁移或删除。其具体内容和存在性不在本说明中检查。查看或处置旧文件只能由用户在本机自行决定。

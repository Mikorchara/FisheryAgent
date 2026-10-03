# AI 编码助手工作说明

- D:\Fishery_Project 永远只读；不得修改工作区以外文件。
- Windows 路径中的 _ 是普通字符；文件操作优先使用 PowerShell -LiteralPath。路径异常缺失时先核对父目录与实际 FullName。
- 不删除不可替代数据；困难或不可逆的操作需先征求用户同意。
- Secret 不得读取、输出或记录。正式凭据来自 PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING；Manual V2 使用独立私有 manual.env。源码根 .env 禁止运行时读取、回退、迁移或自动删除，不得使用 load_dotenv。
- Profile / Experiment 只存 credential_ref。自动测试离线运行，只用临时文件与虚构值；真实请求须有本轮明确授权。
- Preset 使用维护者固定合同；Managed Custom 使用 ProtocolSpec / Evidence Resolver / 显式 Probe；Manual V1/V2 使用独立 Raw 请求，不进入能力判断或 Fishery Analysis。
- Tool Calling 第一阶段只读、按 allowlist 执行。Agent 不得直接改设备、数据库或诊断阈值。
- 以当前代码为事实。行为变更补测试和中文文档；避免无用框架、Secret 和本地模型文件进入 Git。

# 代码接手 / Copilot 学习入口

这些资料面向代码接手 / Copilot 辅助学习的流程与代码地图。先理解当前实现，再讨论受控变更；文档不是自动实施授权。

## 阅读顺序

1. [项目结构](../STRUCTURE.md)：先找入口、服务、工具、资源与测试。
2. [正式 Tool 新增规范](../deep-dive/tools/ADDING_A_TOOL.md)：理解定义、授权与执行的安全边界。
3. [Tool 代码修改地图](TOOL_CHANGE_MAP.md)：判断哪些层需要改、哪些层应复用。
4. [Knowledge Tool v1 学习案例](KNOWLEDGE_TOOL_V1_WALKTHROUGH.md)：沿真实调用链推演未来实现。

**Knowledge Tool：PAUSED / NOT IMPLEMENTED。** 当前正式工具只有水质查询与实验评分。学习案例中的新增文件、参数合同、NO_MATCH、UI 扩展均是未来工作。

## 给 Copilot 的使用方法

- 先读根目录 `AGENTS.md`，以当前源码和测试为准，核对文档中的符号仍存在。
- 每次只讲解一段链路：指出真实文件、输入输出、调用者及测试；不先生成整套代码。
- 需要改代码时，先列出最小变更和兼容风险，经用户明确开启该任务后再实施。
- 不读取 Secret、不恢复源码根 `.env`、不修改正式 `D:\Fishery_Project`；真实请求需另行授权。
- 用临时 fixture 和脚本化 Mock 验证流程。Mock 证明程序边界，不能证明真实模型一定选对 Tool。

可以这样开始：“请按 Walkthrough 第 2 节讲解现有 KnowledgeService，打开相关源码与测试，不修改文件。”

当前功能事实另见[只读 Tool 实现](../deep-dive/tools/READ_ONLY_TOOL_CALLING.md)和[Assistant 结构](../deep-dive/architecture/ASSISTANT_MODEL_V1_DESIGN.md)。

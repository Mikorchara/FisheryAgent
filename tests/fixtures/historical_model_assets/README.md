# 历史模型测试资料

本目录保存 Clean-room Reset 前的公开模型 Profile、Preset 固定合同和 5 条官方能力声明，仅用于历史兼容性离线测试。

`tests/support/historical_model_fixtures.py` 在明确调用它的测试模块生命周期内覆盖资源路径和声明表，模块结束即恢复。未调用该工具的 `test_clean_room_reset.py` 使用真正的空活动目录；完整回归同时验证两种边界。

这些资料不安装到 Python 包，不参与正常 Web / CLI / Profile / Resolver；没有真实 Secret、本地用户 Profile 或本地 Probe 输出。连接凭据仅为变量名引用。不要将本目录作为正常启动 fallback。

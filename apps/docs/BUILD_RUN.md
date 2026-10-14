# 管理平台启动与验证

## 环境

Python 3.11+，Flask 使用根 `pyproject.toml` 已有依赖；Node 用于前端离线测试。原生 ES Modules 无打包步骤，无需 `npm install`。当前 `apps/` 不在 `src/` 包发现范围内，命令应从仓库根目录执行。

如已有 `.venv`，直接使用；首次配置可按根 [环境说明](../../docs/BUILD_RUN.md#环境与启动) 安装现有项目依赖。

## 启动

在 `D:\CodexProject\Fishery_AI_Prototype` 执行：

```powershell
.\.venv\Scripts\python.exe -m apps.management_web
```

访问 `http://127.0.0.1:8766`。更换端口：

```powershell
.\.venv\Scripts\python.exe -m apps.management_web --port 8767
```

按 Ctrl+C 停止当前进程。原 Prototype 的 8765 服务独立运行。管理应用启动不调用 AI、不解析凭据；Flask `debug=False`、`load_dotenv=False`，只监听本机。不要为管理网页新增项目 `.env` 或复制 Key。

## 离线测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s apps/management_web/tests -p "test_*.py"
node --test apps/management_web/tests/view-model.test.mjs
```

这些测试独立于根 `scripts/dev/run_tests.py product` 的发现范围，根产品测试不能代替管理应用测试。前端语法检查可逐个使用 `node --check` 检查 `apps/management_web/static/` 的 JS 文件；Markdown 变更检查本地链接和 `git diff --check`。

## 验证要求

- 服务/合同变更：运行管理应用 Python 与相关 Node 测试，覆盖正常、缺失、无效、过期、未知来源和安全错误。
- 页面变更：补前端测试，人工检查七页导航、趋势切换、事件/文件筛选与详情、AI 草稿及禁用操作；至少检查桌面和窄屏无明显溢出或重叠。
- AI 桥接变更：追加现有 Assistant、Tool、Source、History、取消与发布门禁的相关回归；全部使用 Fake / Scripted Provider，不自动调用 Provider 或 Ollama。
- 仅文档变更：验证文件地图、Markdown 链接与 diff，不运行无关全量测试。

## 当前使用边界

水质页状态选择只读独立 Demo，不 Apply Scenario、不更新原 Prototype Snapshot；10 分钟新鲜度示例不是生产阈值。事件/文件筛选当前在浏览器缓存数据上执行，API 另有读筛选端点；没有持久化或实时推送。

AI 发送固定 503；上传、下载、用户管理、设备控制和规则修改未开放。无认证权限后端，不可作为生产平台或暴露到外网。未来接入按 [集成边界](INTEGRATION.md) 验证后逐项开放。

# 管理系统 Web R1

独立管理应用：Flask + 原生 ES Modules / CSS / SVG。复用现有依赖，不安装大型框架，不启动 AI Runtime。

项目根目录执行：

```powershell
python -m apps.management_web
```

地址 `http://127.0.0.1:8766`，只监听本机。可用 `--port 8767` 改端口；原 Prototype 保留在8765。按Ctrl+C停止，不加载任何 `.env`。

```text
management_web/
├─ __main__.py           # 独立启动，默认8766、无dotenv/debug
├─ app.py                # 只读展示API与本机安全边界
├─ contracts.py          # 页面DTO和可替换服务接口
├─ services.py           # 独立Demo和未接入服务
├─ package.json          # Node测试入口，无依赖
├─ static/
│  ├─ index.html         # 布局、导航容器、详情弹窗
│  ├─ styles.css         # 统一视觉与响应式布局
│  ├─ components.js      # 卡片、表格、指标、图表、空状态
│  ├─ view-model.js      # 纯展示转换、筛选、路由
│  ├─ services.js        # 浏览器应用API客户端
│  └─ app.js             # 七模块页面与Session草稿
└─ tests/
   ├─ test_app.py        # 离线API、安全与启动测试
   └─ view-model.test.mjs # 前端合同与安全文本测试
```

监测数据、趋势及少量事件/文件元数据明确标Demo。视频、NPU、AI发送、上传/下载、用户权限及管理写操作尚未接入。AI消息API固定503；管理写路由不存在；禁用按钮不承担权限保护。

水质页切换区域与可用/过期/部分缺失/无效/无数据视图，不Apply Scenario或改变Prototype Snapshot。AI草稿仅页面Session保留，刷新清空，不发送模型请求。没有DB、持久化、LocalStorage或后台任务。

离线测试（无需npm install）：

```powershell
python -m unittest discover -s apps/management_web/tests -p "test_*.py"
node --test apps/management_web/tests/view-model.test.mjs
```

这些测试独立于现有 `run_tests.py product` 发现范围。浏览器验收：七模块导航、监测状态、趋势指标切换、事件/资料筛选与详情、AI草稿、视频设备选择、设置分类及小屏侧栏。

长期接口与接入方案见[管理应用架构](../../docs/deep-dive/architecture/MANAGEMENT_WEB_R1.md)。

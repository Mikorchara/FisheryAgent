# 管理平台目录与职责

以下为当前实际结构；缓存不展开。根 [项目地图](../../docs/STRUCTURE.md) 包含整个仓库。

```text
apps/
├─ AGENTS.md                     # 管理平台工程与安全规则
├─ __init__.py                   # 应用命名空间，无启动副作用
├─ docs/                         # 管理平台主要文档入口
│  ├─ README.md                  # 当前状态与文档导航
│  ├─ STRUCTURE.md               # 模块职责与拆分方向
│  ├─ BUILD_RUN.md               # 启动、测试与验收
│  ├─ INTEGRATION.md             # 服务合同与未来接入边界
│  └─ ROADMAP.md                 # 已实现状态和开发计划
└─ management_web/               # 独立管理网页及 Web 专属后端
   ├─ __init__.py                # 应用包
   ├─ __main__.py                # 本机启动与端口校验
   ├─ README.md                  # 快速启动与文档入口
   ├─ app.py                     # HTTP、服务装配及本机安全边界
   ├─ contracts.py               # 监测 DTO 和五个服务 Protocol
   ├─ services.py                # Demo Adapter 与未接入 AI 服务
   ├─ package.json               # Node 测试配置，无外部依赖
   ├─ static/
   │  ├─ index.html              # 导航、页面容器和详情弹窗
   │  ├─ styles.css              # 统一样式与响应式布局
   │  ├─ app.js                  # 路由、七页面装配与页面 Session
   │  ├─ components.js           # 安全文本、卡片、表格、图表和空状态
   │  ├─ view-model.js           # 展示转换、筛选与 Bootstrap 基础校验
   │  └─ services.js             # 浏览器 HTTP 客户端
   └─ tests/
      ├─ test_app.py             # 离线 API、质量状态、安全与启动
      └─ view-model.test.mjs     # 前端合同与文本安全测试
```

## 当前依赖方向

```text
页面 / 展示组件
    → static/services.js：应用 HTTP API
    → app.py：输入、路由、安全与服务装配
    → contracts.py：DTO / 服务接口
    → services.py：独立 Demo / 未接入服务

未来 AI Adapter → src/fishery_ai 的应用服务与 Runtime
```

- **页面**：选择、草稿、加载/错误和导航；当前七页集中在 `static/app.js`，尚未拆独立页面模块。
- **展示组件**：只格式化事实与状态，不诊断水质、不调用 Provider、不定义业务阈值。
- **应用服务**：表达业务用例、来源与生命周期；R1 通过五个 Protocol 注入实现，复杂用例尚未建立。
- **合同**：页面所需 DTO、错误和版本。当前监测使用 frozen dataclass，其余仍多为 `dict`；这些类型声明不是完整输入输出校验。
- **Adapter**：把数据库、设备、AI Runtime 等外部结构转换为合同，隔离硬件/协议差异。Demo 实现不是未来业务规则。
- **共享 AI Runtime**：保留在 `src/fishery_ai/`；不依赖管理网页，不复制到 `apps/`。

## 后续最小模块化方向（未创建）

R2 接入时优先提取 `static/pages/assistant.js`，由 `app.js` 保留布局和路由装配；Assistant 拥有独立 Session，其他页面先维持现状。`components.js` 继续放通用展示，`services.js` 只负责应用 API，不混入 Prompt 或 SDK。

后端可新增薄 `ai_adapter.py` 连接现有 AssistantService；当路由确实变复杂时再提取 `ai_routes.py`。现有 `contracts.py` 和 `services.py` 暂保留，只有接口或 Adapter 数量增长后才按领域拆分。未来 Monitoring、Video、Events、Files 的 Adapter 各自替换，不创建通用插件框架或空模块。

Runtime/Core 在 `src/fishery_ai/`；管理 Web 在本目录；Development/Test 为各自测试与开发入口；Research 属于根 `docs/deep-dive/research/`；生成数据放 Git ignored 的 `outputs/`；凭据属于用户私有存储，不属于管理网页资源或仓库树。

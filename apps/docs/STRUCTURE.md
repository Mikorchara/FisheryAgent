# 管理平台目录与职责

当前实际结构；缓存不展开。完整仓库见根 [地图](../../docs/STRUCTURE.md)。

```text
apps/
├─ AGENTS.md                         # 管理工程与安全规则
├─ __init__.py                       # 应用命名空间
├─ docs/
│  ├─ README.md                      # 当前状态与文档入口
│  ├─ STRUCTURE.md                   # 真实目录与职责
│  ├─ BUILD_RUN.md                   # 启动、联调与验证
│  ├─ INTEGRATION.md                 # 上报合同和替换边界
│  └─ ROADMAP.md                     # 当前状态与后续工作
├─ monitoring/                      # Web 与未来 Tool 共享的数据基础
│  ├─ __init__.py
│  ├─ contracts.py                   # v1 批次校验与共享监测 DTO
│  ├─ repository.py                  # SQLite、当前状态、有界历史和事件
│  ├─ service.py                     # 统一读取、领域诊断与设备上下文
│  └─ tests/
│     ├─ test_pipeline.py            # 校验、时序、安全、状态与共享来源
│     └─ test_local_http.py          # 真实 loopback 上报及停止/重启
├─ simulator/                       # 独立设备生产端
│  ├─ __init__.py
│  ├─ __main__.py                    # 实时调度、离线推进与清理
│  ├─ scenarios.py                   # 手写 Phase 时间线
│  ├─ generator.py                   # 确定性水质/视觉窗口生成
│  ├─ transport.py                   # 受控 HTTP 上报，无重试/重定向
│  └─ tests/
│     └─ test_simulator.py           # Seed、采样、场景、调度与清理
└─ management_web/                  # 管理页面与 Web 专属后端
   ├─ __init__.py
   ├─ __main__.py                    # 本机启动、存储装配与写入开关
   ├─ README.md                      # 快速入口
   ├─ app.py                         # HTTP、访问控制与服务装配
   ├─ contracts.py                   # Web Protocol、共享 DTO 导出
   ├─ services.py                    # R1 兼容 Demo、未接入 AI/文件服务
   ├─ package.json                   # Node 原生测试，无依赖
   ├─ static/
   │  ├─ index.html                  # 布局、来源标识和弹窗
   │  ├─ styles.css                  # 样式与响应式布局
   │  ├─ app.js                      # 七页面、5 秒轮询与 Session
   │  ├─ components.js               # 安全文本、卡片、表格、图表
   │  ├─ view-model.js               # 展示转换、来源和状态
   │  └─ services.js                 # 同源只读应用 API
   └─ tests/
      ├─ test_app.py                 # R1 兼容、API 和安全
      ├─ view-model.test.mjs          # 纯展示合同
      └─ monitoring-ui.test.mjs       # 实际页面代码的离线 DOM 行为
```

## 依赖与生命周期

```text
Simulator scenarios → generator → HTTP reporter
    → Web Ingestion（鉴权）
    → monitoring contracts（验证）→ repository（事务存储）
    → MonitoringService
        → Dashboard / Monitoring / Video / Events
        → bind(device_id).water_reader（未来 Tool 接入）

MonitoringService → 已有 Domain / Diagnosis / CurrentWaterQualityReader
未来 AI Adapter → 已有 AssistantService / AI Runtime
```

模拟器不导入服务器存储或网页变量。共享 monitoring 不依赖 Flask 或网页组件；水质 DTO 只有一个定义，Web 兼容导出。SQLite 连接按操作关闭，生成器与 HTTP 生命周期分离，页面轮询不触发采样或写入。

页面负责交互与展示；API 负责输入/访问控制；服务负责用例和状态；Adapter 负责生产端/设备差异。当前七页仍在 `static/app.js`；将来 AI 接入时优先提取独立 `pages/assistant.js` 与薄 `ai_adapter.py`，不为规划创建空目录。

Runtime/Core 为共享领域与 AI 包；Development 为模拟器和测试；Generated 为 Git ignored 的 `outputs/management_web/`；User-private 为已有凭据目录，管理前端不可接触。真实设备、NPU、文件索引和 AI 执行仍未实现。

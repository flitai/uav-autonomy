# Cesium 显示工程

当前仅实现 G5-T01 的环境验证页面：本地 Cesium 椭球场景、中文标签和异步几何工作线程。画面中的样片是工程探针；尚未消费仿真消息或加载用户地图／真实地形。

从仓库根目录使用 `scripts/windows/setup-g5.ps1`、`build-g5-viewer.ps1` 与 `tests/windows/g5-environment.tests.ps1`，均传入已核查的 `-PythonExecutable`。入口自行解析仓库位置，无需全局 Node／npm，也不改变持久 PATH。构建在 `out/build/cesium-viewer/` 的独立副本执行 `npm ci`、TypeScript 检查和 Vite 构建；不要在本目录手工安装不同版本依赖。

Node／npm 由 `config/g5-node-lock.json` 固定，直接及传递前端依赖由本目录 `package-lock.json` 固定。生命周期安装脚本默认关闭；Windows 原生 Rolldown、Lightning CSS 与 TypeScript 包随依赖锁安装。Cesium 的 Workers、ThirdParty、Assets、Widgets 全部复制进候选包；中文字体使用 Windows 系统本地 Microsoft YaHei，不下载或再分发字体。实体模型由 T06 增加并登记来源。

通过 `scripts/windows/run-g5-viewer.ps1 -PythonExecutable <已核查解释器> -BuildRunId <本次构建编号>` 启动候选，入口复查环境、构建来源和全部页面文件，输出地址与停止文件位置。静态服务固定监听回环地址，默认 8080；开发入口 `dev-server.mjs` 使用 Vite 严格端口 5173。它们通过各自运行目录的 `request-stop` 正常退出。当前静态服务只用于资源验证；G4 的 8000 代理、Range 地理资源服务和业务图层由后续任务实现。候选不切换正式前端指针，正式发布仍归 T11。

详见 [G5 方案](../../docs/g5-cesium-display-plan.md) 与 [任务卡](../../docs/backlog.md#9-g5-顺序与任务卡)。

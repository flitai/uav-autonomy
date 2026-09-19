# G4 只读网关

服务入口是 `server.py`，协议、接收、状态、日志和发布核心位于 `src/sim_bridge`。使用项目已锁定 Web 环境，不依赖浏览器控制仿真；不提供任务注入或运行控制 API。

从仓库根目录使用 `scripts/windows/run-g4-web.ps1 -PythonExecutable <已核查解释器> -Mode Headless` 做真实短程运行，使用 `tests/windows/g4-web.tests.ps1` 复验两模式和诊断页面。入口重新核查正式来源，独立编排生成绑定运行／PID 创建时间／日志目录的清单，再启动网关。直接调用 Python 服务须提供该清单及其 SHA-256、新输出目录；不要手工指向旧运行冒充实时后端。

默认本机端口 8000：`/api/v1/health`、`/api/v1/snapshot`、`/api/v1/stream` 和根诊断页。测试完成后自动正常关闭；长时间运行和完整任务在后续卡交付。Edge 仅用于诊断页验收，服务运行不依赖 Edge。

字段、快照边界和来源见 [v1 契约](../../docs/g4-browser-contract.md)，运行证据与边界见 [T04 报告](../../docs/g4-web-validation.md)。观察自动重连／补齐已由 [T05](../../docs/g4-recovery-validation.md) 验证，可用 `tests/windows/g4-recovery.tests.ps1` 运行完整恢复矩阵；主链路／后端失败必须新编号整组启动。本目录不是 Cesium 应用。

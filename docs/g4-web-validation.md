# G4-T04 浏览器接口验收

日期：2026-09-19～20，Asia/Shanghai。**T04 已完成，T05 可执行。** 最终两模式真实接口、诊断页面和正常收尾通过；自动观察恢复仍归 T05。

## 交付与接口

`apps/gis_gateway/server.py` 提供独立 FastAPI／Uvicorn 服务，使用 T01 的隔离环境；`src/sim_bridge/gateway.py` 持有只读观察连接、日志消费和状态发布。运行编排另行负责启动屏障、任务注入及后端关闭。浏览器没有后端控制路径，关闭浏览器或关闭网关不会给仿真发送停止／任务消息。

| 入口 | 行为 |
| --- | --- |
| GET /api/v1/health | 本次运行／流身份、连接、新鲜度、初始化、记录和错误；HTTP 可访问不等于 ready |
| GET /api/v1/snapshot | 完整快照；未初始化或降级时 503，不冒称实时完整 |
| WS /api/v1/stream | 同连接首条快照，随后其序号边界之后的有序增量；未就绪返回 health 并要求重连 |
| GET / | 不依赖外网资源的中文诊断页，展示实体、任务、源时钟、连接和规划数量；刷新／断流后新快照 |

默认监听 127.0.0.1:8000。HTTP POST 无接口，WebSocket 业务输入以 1008 拒绝；浏览器只读。快照经 Pydantic v2 严格检查头部，所有 ID／序号／仿真毫秒保留字符串，前端用 BigInt 检查增量连续性。DOM 通过 textContent 渲染后端值。

发布和快照登记共用一把状态锁；一个提交产生一个序号，每客户端队列最多 256 条且不超过 8MiB，总订阅数最多 16。超限关闭慢客户端并要求新快照，其他客户端继续；关键事件仍在磁盘记录。夹具专门在快照生成期间让生产线程尝试提交，验证边界；也检查条数／字节上限和超大序号。

后端运行清单由本次编排生成，命令行绑定其 SHA-256；网关只读核对 PID 与创建 FILETIME，清单变化／后端退出拒绝继续实时发布。原生接口依据 [GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes) 和 [OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess)，只申请查询权限。主链路故障和完整恢复矩阵仍由 T05 验收。

## 运行与测试

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
# 仓库根目录；省略 BaselineRunId 时重新检查正式来源。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g4-web.tests.ps1 -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g4-web.ps1 -PythonExecutable $pythonExe -Mode Headless
```

独立 g4-t04- 运行目录保存三客户端对照、网关原始 TCP／规范化记录、快照和进程证据。测试短程自动正常关闭；持续运行／完整任务归后续卡。测试浏览器使用本机 Edge、独立用户目录和显式本机调试端口 9222；端口被占用会拒绝，不切换端口或影响占用者。服务本身不依赖 Edge，9222 也不是产品接口。

## 验收过程与当前证据

首轮 `g4-t04-test-20260919-235220-447` 两模式通过。三个真实 WebSocket 客户端分别加入，在 HTTP 指定同一序号重建出的完整状态严格相同；晚加入、断开后新快照、控制输入拒绝通过。两实体、规划和任务来自当前正式后端，网关业务发送帧为 0，所有后端／网关正常退出。

补充本机浏览器测试的 `g4-t04-test-20260919-235535-837` 保留 failed：页面已真实显示两实体／任务、JavaScript 无异常，但测试 Edge 未在 15 秒内正常退出，随后按所属 PID 清理；AMASE／UxAS／网关仍正常退出。测试启动增加关闭后台模式和扩展的参数，隔离最小关闭样本在约 1.73 秒退出 0；最终测试另核对刷新前后 performance.timeOrigin 确实变化，避免只读取重载前的旧 DOM。`g4-t04-test-20260919-235825-978` 两模式通过；随后截图审查发现页面遗漏显示已知规划分配，补齐为“分配／参与实体”并断言实体 400 后完成最终复验。

最终运行 **g4-t04-test-20260920-000102-608** 的 result／entry-result 和两模式 case-result 均 passed，42 项功能来源运行前后保持。8 项发布／队列／快照并发检查、T03 状态与来源拒绝、T02 协议回归全部通过。

| 最终实测 | Headless | GUI |
| --- | --- | --- |
| 网关持久记录 | 128 条 | 116 条 |
| 实时发布增量 | 93 条 | 81 条 |
| 三客户端共同对照序号 | 77；各自从 74／74／77 起步 | 77；各自从 74／74／77 起步 |
| 实际客户端队列峰值 | 1 条／9237 字节 | 1 条／9232 字节 |
| Edge 页面 | 2 实体、1 任务、分配 400 | 2 实体、1 任务、分配 400 |
| 页面刷新／JavaScript | 新 timeOrigin、0 异常 | 新 timeOrigin、0 异常 |
| 退出 | AMASE／UxAS／网关／Edge 正常，无强制终止 | AMASE／UxAS／网关／Edge 正常，无强制终止 |

Edge 实测版本为 153.0.4234.32；两模式截图位于本次对应 `edge-browser/diagnostic.png`，已查看确认真实字段显示。8000／9222 及两模式全部后端端口无残留监听。队列超限由隔离发布器夹具确定验证，实际短程客户端未触发超限；长期慢网络与 20 实体规模归 T08，不把上述峰值当作压力上限证据。

T04 的真实客户端和页面刷新不等于网关进程重启或观察连接自动补齐通过；当前观察故障会明确降级。T05 将使用新流快照、日志提交边界、原字节缺口与后端故障拒绝完成恢复矩阵。

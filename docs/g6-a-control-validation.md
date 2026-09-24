# G6-A 基础仿真控制候选验收记录

日期：2026-09-24。当前状态：G6-A 已按第 4 节重新验收并发布，G6-B01 可执行。第 2～3 节保留修复旧 AMASE Play 前后的候选及失败记录，不作为当前发布资格。本报告中的 `out/runs` 为本机原始收据，不把自动 Edge 截图替代用户确认。

## 1. 交付边界

在 G5-T11 正式来源上组合独立控制候选，不改旧 G4 只读流或已发布 G5 包。AMASE 内 `ControlProbe` 接收运行目录中的单条受限命令，调用 `SimTimer` 开始／暂停／继续及固定倍率；重置由 `session.py` 正常关闭 AMASE、UxAS、网关及覆盖收集器，再启动新分段。FastAPI 本机 8001 写入口持久记录操作、检查来源、进程和网关身份、请求版本、幂等键及反馈。页面控制面板显示权威时间和只读进度，失联禁用写操作，刷新恢复操作记录。

当前场景总时长为冻结的 1800 秒，范围是 G5 已验收的三实体小场景；进度不支持拖动。倍率只接受 `0.25/0.5/1/2/5/10`。重置后旧运行分段和旧网关流不能再用于写操作。G6-B 的任务草稿、规划预览及下发没有在本卡实现。

## 2. 独立证据

| 卡 | 当前收据 | 已验证事实 |
| --- | --- | --- |
| A01 | `out/runs/g6-a01-check-20260924-1826/result.json` | G5 正式指针、场景 1800 秒、AMASE 控制语义和 Java 11 探针编译通过；此卡不登记运行能力。 |
| A02 | `out/runs/g6-a02-final-20260924-2331/runtime-result.json` | Headless／GUI 真实 AMASE、UxAS、网关；开始、暂停、暂停时改 2 倍、继续、运行中改 0.5 倍及最终暂停均由本段 `SessionStatus` 确认；来源、倍率、并发版本、幂等键反例通过，进程正常退出。 |
| A03 | 构建 `g6-a03-build-20260924-2330`；`out/runs/g6-a03-final-20260924-2335/runtime-result.json` | 两模式真实 Edge 点击、后端时间／进度、刷新恢复与主动关闭控制 API 后按钮禁用通过；地图与原 G4 观察仍为只读。 |
| A04 重置 | `out/runs/g6-a04-reset-final-20260924-2340/runtime-result.json` | 两模式各两个真实分段；新的 AMASE 进程、网关 run／stream、新场景零起点和旧段写拒绝；操作收据可跨分段查询，四组正常退出和端口释放。 |
| A04 故障 | `out/runs/g6-a04-fault-final-20260924-2345/runtime-result.json` | 两模式丢失 POST 响应后按操作键恢复、重复请求未生成第二条 AMASE 命令；AMASE 正常退出后写入口返回 503；8001 固定端口占用时启动明确失败。故障注入使 G4 观察实例按其既有规则以 exit 1 登记，两个原始 case 均标 failed，顶层故障矩阵只把这一预期负例判为通过，不声称该故障组正常关闭。 |
| A05 自动组合 | `out/runs/g6-a05-smoke-final-http-20260924-2350/result.json`、`out/runs/g6-a05-smoke-final-browser-20260924-2355/result.json` | 两模式长会话均能开始、整组重置、旧段拒绝、新段继续／暂停；真实 Edge 点击重置后恢复；所属进程 exit 0、端口释放。自动组合不是本轮人工确认或正式发布。 |

旧失败运行保留：A03 刷新测试的缺键等待、倍率后按钮时序、重置页面等待旧流身份，以及故障注入期间 G4 的预期异常退出均保留原记录；修正后用新编号复验，未改写旧收据。A02 只确认本地控制链，不把 AMASE 原 `SessionStatus` 当作网络命令。表中收据均对应移除旧 AMASE 控件前的源码，不能直接用于当前源码发布。

## 3. 候选入口与本轮待确认

候选运行从当前 `out/artifacts/g5-stage/current.json` 重新核对正式包、发布收据、地形和覆盖来源；组合 `g6-a03-build-20260924-2330`。在仓库根目录使用已验证的 Python 3.14.7 x64：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
& $pythonExe -I -B -X utf8 scripts/g6_control/session.py --run-id 'g6-control-<NEW_ID>' --viewer-build g6-a03-build-20260924-2330 --mode Gui
```

页面为 `http://127.0.0.1:8080/`。本次运行目录中的 `session-ready.json` 给出后端和分段身份；向同目录写入 `request-stop` 后正常关闭，`runtime-result.json` 和每段 `case-result.json` 为退出依据。重置由页面发起，旧段 `request-reset` 触发整组重启；新段 `control-reset-receipts` 给出操作结果。端口 8080／8000／8001、AMASE／UxAS 及实体端口是显式固定配置，占用时拒绝，不自动改端口或结束其他进程。

A05 历史自动资格收据为 `out/runs/g6-a05-qualify-20260924-0021/acceptance.json`，当时状态 passed、`manualReview=pending`、`stageQualified=false`。修改 G6 运行配置后，该收据的源码哈希与当前源码不符，不能用于正式发布；须重跑自动矩阵并取得新资格。独立发布入口 `scripts/g6_release/manage.py` 核对自动收据、当前 G6 源文件与 G5 正式指针；只有当前 GUI 的明确批准、正常退出后才能发布本机工作区绑定的 G6-A 增量指针。该增量仍依赖同工作区的 G5 正式包与当前源码，第二机器部署归 G8。

无人工确认时的发布反例 `g6-a05-publish-negative-20260924-0022` 被拒绝，正式 `out/artifacts/g6-control/current.json` 未产生；失败收据保留。

A05 仍需本轮用户查看真实 GUI 控件、时间／进度和重置体验，记录确认与当前候选来源，再正常停止页面与整组服务；通过后才能登记 G6-A 正式资格及开放 B01。G5 正式指针保持不变；本候选尚无 G6-A 正式发布指针。

首轮 GUI 会话 `g6-control-review-20260924-0010` 于 21:40 观察到 AMASE 在未经过当前 G6 控制操作的情况下复位并推进到 0.01 秒，触发 `AMASE started before barrier` 保护；该轮运行收据为 failed，所属进程正常清理，保留原始记录，不能作为人工确认或合格退出。

第二轮 GUI 会话 `g6-control-review-20260924-2144` 在用户点击 AMASE 旧 Play 后再现同一保护退出；该轮 `control-operations` 为空，证明启动未经过 Cesium 控制接口。当前 G6 运行配置已移除 AMASE 旧 `SimControls` 插件和对应停靠控件，避免旧 Play／Reset 绕开带运行身份的写入口。真实 GUI 冒烟 `g6-control-fix-smoke-20260924-2149` 核查旧控件数为 0、Cesium 接口开始操作 confirmed、仿真继续推进且无 unexpected-start，随后整组正常退出并释放端口。

当时待确认的 GUI 会话为 `g6-control-review-20260924-2152`，启动时 `session-ready.json` 记录 `segment-001-1`，8080 页面返回 200。该轮后续反馈、失败退出及处理见第 4 节；使用 Cesium 页面“开始／暂停／继续／重置”，重置后以最新分段身份为准。

## 4. 修复后复验、人工确认和正式发布

用户对 `g6-control-review-20260924-2152` 页面回复“我都实测了，很好。继续”。该轮首段重置正常通过；第二段在仿真约 222.5 秒出现 AMASE 执行证据写入异常与观察流断开，`runtime-result.json` 保留 failed。此轮只作为同源码的人工视觉与操作反馈，不能作为正常退出证据；未确认断流由何种外部操作引起。

移除旧 AMASE `SimControls` 后，A01 沿用未受源码变化影响的 `g6-a01-check-20260924-1826`；当前源码 A02 HTTP 矩阵 `g6-a02-api-post-play-20260924-2211`、A03 Edge `g6-a03-post-play-20260924-2202`、A04 重置 `g6-a04-reset-post-play-20260924-2204`、A04 预期故障矩阵 `g6-a04-fault-post-play-20260924-2204`、A05 两模式持久会话 `g6-a05-smoke-post-play-http-20260924-2206` 与真实浏览器重置 `g6-a05-smoke-post-play-browser-20260924-2208` 均通过。A02 曾误选底层探针收据导致 `g6-a05-qualify-post-play-20260924-2210` 失败；随后补跑完整 HTTP 收据，旧失败保留。

正式资格 `g6-a05-qualify-post-play-20260924-2212` passed。`g6-a05-confirm-post-play-20260924-2213` 明确分开记录用户视觉会话与同源码正常退出会话 `g6-control-g6-a05-smoke-post-play-browser-20260924-2208-gui`；后者两段均 passed、normalExit=true、portsReleased=true。发布管理器复核两轮来源一致、用户会话至少有已确认的开始／暂停／继续／倍率及重置收据，不将该轮 failed 改写为 passed。`g6-a05-publish-post-play-20260924-2214` 已原子发布 `out/artifacts/g6-control/current.json`，stageQualified=true；G5 正式指针保持不变。生产入口 `g6-control-production-check-20260924-2215` 的 GUI 自动启停 passed、normalExit=true。增量包仍绑定本工作区来源，第二机器部署归 G8。

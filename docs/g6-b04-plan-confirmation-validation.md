# G6-B04 方案审查与确认下发验收

日期：2026-09-25。状态：**首批固定分配交互闭环通过**；G6-B05 为下一卡。G6-A、G5 正式指针未切换，B04 仍是独立候选入口。

## 实现与边界

- `apps/cesium_execution/panel.ts` 在 B03 页面上增加中文方案审查。操作者选择已保存草稿的预览，页面列出固定实体、任务顺序、全部航点坐标／高度、动作和方案摘要；必须单独勾选核对后才能确认。页面保留操作键并查询结果，未知响应不会自动重发。
- 本地 `127.0.0.1:8004` 的 `apps/g6_execution/server.py` 提供方案审查、确认、操作查询。后端重新核查冻结运行／分段／流身份、草稿修订、B02 原始规划收据及 XML 哈希、完整航线和固定分配。确认仅允许一份方案、一次操作；同键重发只查已有收据，异键冲突拒绝。不可逆步骤后结果不确定时登记 `uncertain`，不盲目重试。确认先启动 G6-A 仿真，再核对实体初始状态，随后发送同一份已审查的 `AutomationResponse` 字节。
- B04 运行目录复制并修改 UxAS 配置，去掉请求校验、航线规划、分配树和方案组装服务，保留 TaskManager、任务服务与 WaypointPlanManager。这样活动侧只接收 B02 隔离规划已经生成的方案，不在确认时重新计算。B04 将该规划实例的 `UniqueAutomationRequest` 改为非沙箱请求，并送入同一 `UniqueAutomationResponse`，为任务服务建立固定分配上下文；随后送入完全相同的 `AutomationResponse`。这三个消息的摘要和原始 TCP 帧均留在本次运行目录。原 G6-A 自动演示入口及正式配置未变。
- B04 只对冻结初始状态、一架实体、一份任务方案开放。运行中编辑／重规划、多机竞争、取消、重置后的执行恢复和完整故障矩阵分别归 B05～B08。当前 B04 测试任务为短折线搜索、任务 3000、实体 400；点和矩形在 B02／B03 验证预览及编辑，尚未在 B04 宣称三类都完成确认执行。

## 实际证据

当前页面候选 `g6-b04-build-20260925-0023` 与独立收据 `out/runs/g6-b04-acceptance-20260925-0026/acceptance.json`：`status=passed`、`executionQualified=true`。Headless API 会话 `g6-b04-session-20260925-0024`、Gui AMASE＋真实 Edge 会话 `g6-b04-session-20260925-0025` 均 `normalExit=true`、`portsReleased=true`。两轮确认方案字节摘要相同：`8b8b1706d0de10e2465b28f90c19eb213b12a3b03670e86247d5b3e306f1979a`。

| 核对项 | Headless API | Gui Edge |
| --- | --- | --- |
| 审查／实际命令 | 19／19 航点，UxAS 命令 51、52 均由 AMASE 收到 | 19／19 航点，UxAS 命令 48、49 均由 AMASE 收到 |
| 真实任务生命周期 | 唯一 TaskActive→TaskComplete，实体 400；持续 53,541 ms | 唯一 TaskActive→TaskComplete，实体 400；持续 54,171 ms |
| 独立轨迹复算 | 方案折线 2,207.01 m；至完成时 AMASE 采样状态累计飞行 2,180.79 m；当前航点到 19 | 方案折线 2,207.01 m；采样状态累计飞行 2,147.84 m；当前航点到 19 |
| 退出 | AMASE／UxAS 正常退出，所属端口释放 | Edge 正常退出，AMASE／UxAS 正常退出，所属端口释放 |

独立审计从保存的 B02 原始 XML 重新构建方案字节，核对实际下发 TCP 帧；检查两段命令的航点编号集合、经纬度和高度与预览一一对应，后段带任务 3000 关联，AMASE 原始流确实收到两段命令。再从 AMASE `AirVehicleState` 复算飞行距离和最终航点，从原始 TaskActive／TaskComplete XML 复算持续时间。该统计是 B04 的生命周期和轨迹核对；**当前运行没有产出原生 20 米覆盖报告，不登记覆盖率或覆盖统计正确性**，后续组合验收需单独取证。

Headless HTTP 轮拒绝错误方案摘要、确认后的旧预览和第二个确认键；同键查询返回原命令摘要，没有重复下发。Gui Edge 轮在未勾选审查时确认按钮禁用，页面显示全部 19 航点，勾选后由真实浏览器提交并取得命令收据，截图在 `out/runs/g6-b04-browser-20260925-0025/review.png`。执行开始后页面可查询完成时间和操作状态。候选构建绑定 B03 合格页面与当前 B04 源码哈希，组合收据记录 G5／G6-A／UxAS／网关正式指针摘要；本轮没有切换这些指针。

## 排查记录与复用

早期探针直接送 `AutomationResponse`，飞机能飞到航点，但缺少 TaskManager 的分配上下文，未产生 TaskComplete。补送同一隔离预览的 Unique 请求／响应后，真实 TaskActive 和 TaskComplete 出现。首次操作 `g6-b04-session-probe-20260925-0004` 把首段命令必须带任务标记作为条件，误判为 `uncertain`；实际首段只有 1～15 号航点，后段 11～19 号航点含任务标记。当前审计检查两段合并后的全部航点与任务关联。其他早期失败探针及收据原样保留，不作为资格。

候选复用入口：先执行 `scripts/g6_execution/build_viewer.py --run-id <新的 g6-b04-build-* 编号>`，再以 `scripts/g6_execution/session.py --run-id <新的 g6-b04-session-* 编号> --viewer-build g6-a03-build-20260924-2330 --draft-build g6-b03-build-20260924-2438 --execution-build <构建编号> --mode Headless|Gui` 启动。会话就绪信息在本次 `out/runs/<编号>/b04-session-ready.json`；通过该文件的 `request-stop` 路径结束并核查 `runtime-result.json`。验收脚本为 `tests/g6_execution/flow.py`、`browser.py`、`audit.py`；每次使用新的输出目录，不能把历史编号当本次成功。

GUI 页面自动操作和截图不代替 B08 要求的本轮人工页面确认。B05 接下来验证多机候选、任务序列、真实分配与两模式执行；B04 不扩大为自由分配或运行中重规划。

## 2026-09-28 页面组织与清晰度复验

用户指出 B04 页面面板拥挤、网页显示偏糊。本轮在 B04 候选中把草稿编辑与方案审查合为右侧可收起的“任务工作区”，分“编辑与预览”“审查与执行”两步；仿真连接、控制和实体详情归入左侧折叠组。方案摘要改为简短字段，完整标识与哈希保留在可展开详情中，19 航点列表单独滚动。B04 构建副本按设备像素比将 Cesium 实际画布设为 CSS 尺寸的 1.5～2 倍，并把地球细节误差从 3 调至 2；正式 G5、G6-A 页面源码和指针未修改。

最终候选 `g6-b04-build-20260928-ui06`、独立两模式收据 `g6-b04-acceptance-ui-20260928` 均 passed，后者 `executionQualified=true`。真实 Edge 验证 1896×可用窗口与 1366×768 视口：左右面板不重叠、步骤标签可见、无横向溢出、工作区可收起、画布像素比 1.5。截图见 `out/runs/g6-b04-browser-ui-validation-20260928-gui/review.png`。Headless API 与 Gui Edge 再次验证同一方案 19／19 航点下发、TaskActive／TaskComplete、正常退出和端口释放；两模式方案字节 SHA256 仍为 `8b8b1706d0de10e2465b28f90c19eb213b12a3b03670e86247d5b3e306f1979a`。当前资格以本轮新候选和收据为准，2026-09-25 记录保留历史结果。

本轮 GUI 探针 `g6-b04-session-ui-check-20260928-08` 曾遇到控制服务同一固定 `.json.tmp` 文件的并发争用：开始操作实际已确认，但 POST 返回 500，旧 B04 误记为 rejected。B04 现在把开始请求发出后视为结果可能已生效；若响应失败，仅查询同一操作键并核对运行、分段和流身份，确认后继续下发，无法确认则保留 uncertain，不重复发送开始。G6-A 控制服务的固定临时文件争用本身尚未改动，后续控制服务维护应单独修复并复验；本轮 B04 端已完成结果核查保护。B04 仍不登记原生覆盖率，也不替代 B08 人工页面确认。

## 2026-09-28 页面说明文字精简

用户复看后要求移除与任务操作无关的模型尺寸、视角手势、断线清理、覆盖颜色和航线配色说明。当前 B04 候选以自身 CSS 隐藏这些说明以及地图／草稿的常驻提示；构建时只改写 B04 的 G5 页面副本，把覆盖断线占位清空、覆盖故障缩成简短状态、任务空列表改为“暂无对象”。任务和实体控件、覆盖计数、实际错误与确认操作保留；G5／B03 合格源码未改动。

候选 `g6-b04-build-20260928-ui07` 和两模式独立收据 `g6-b04-acceptance-guidance-20260928` 均 passed，后者 `executionQualified=true`。真实 Edge 对所列说明逐项检查，页面可见文本中均不存在，保留供原模块更新使用的 `model-scale` 和 `coverage-status` DOM 节点；桌面及 1366×768 布局继续通过。截图在 `out/runs/g6-b04-browser-guidance-20260928-gui2/{task,review}.png`。Headless API 与 Gui Edge 再次取得相同方案 19／19 航点、TaskActive／TaskComplete、正常退出与端口释放。首个 GUI 探针 `g6-b04-browser-guidance-20260928-gui` 在确认后的 TaskInitialized 等待超时，B04 留下 uncertain、未下发方案；原记录保留，随后独立 GUI 新会话完整复验通过。当前 B04 页面资格以 ui07 候选和本轮收据为准，B05 仍为下一卡。

## 2026-09-28 默认卫星影像与本地底图回退

用户要求页面优先显示 Esri 在线卫星影像，无法联网或影像服务不可访问时自动使用本地矢量底图。B04 构建只改写其合格 B03 页面副本：启动后主动选择 Esri，底层本地矢量保持可用；影像元数据加载超时／失败或瓦片报错时，移除在线图层并切回本地。回退提示只显示“在线影像不可用，已恢复本地矢量底图。”，不把可恢复的在线故障记成地图加载失败。用户仍可手动切换底图。G5／B03 合格源码和正式指针未修改。

最终构建 `g6-b04-build-20260928-basemap02` passed。真实 Edge 联网结果 `g6-b04-basemap-rendered-online-20260928`：底图值 `satellite`、影像图层 2、Esri 瓦片 HTTP 200 两次，延后截图可见卫星影像。禁用外部 DNS 的结果 `g6-b04-basemap-rendered-offline-20260928`：底图值 `local`、图层 1、地图 `ready=true`，可见本地矢量与简短回退提示；两种截图均在对应 `out/runs` 目录。断网状态下的真实 Edge 完整任务交互 `g6-b04-browser-basemap-20260928-gui3` passed；Gui 会话 `g6-b04-session-basemap-20260928-gui3` 和 Headless 会话 `g6-b04-session-basemap-20260928-headless2` 正常退出、端口释放。两模式审计 `g6-b04-acceptance-basemap-20260928` passed、`executionQualified=true`，同一方案 19／19 航点和 TaskComplete 再次通过。

首次 Headless 探针误把会话根目录传给 `flow.py --session`，脚本从错误父目录寻找观察流，尽管实际收到 TaskComplete，仍等待超时；失败目录 `g6-b04-flow-basemap-20260928-headless` 保留。随后用新会话及正确的 `segment-001/control-session.json` 路径重新执行并通过。当前 B04 页面资格以 basemap02 和本轮收据为准；B05 仍为下一卡。
## 2026-09-28 仿真先开始后的任务面板与重置恢复

用户在 B04 待看页面点击左侧“仿真开始”后，任务面板暴露 `Active backend unavailable: B02 preview requires frozen pre-start simulation state` 和完整控制状态。实际控制状态为 started=true、仿真运行中；B02 预览资格明确限制于未开始的冻结初始状态。B04 的正常任务流程是先保存草稿、请求预览、审查完整方案，再确认下发；确认操作本身会启动仿真。直接启动后的实时新增或修订任务需要后续 B06 的切换协议，不能直接使用初始状态预览。

当前 B04 构建副本在单独点击“开始”前给出可取消的流程提示；直接启动后，任务工作区显示简短中文说明并隐藏无效表单，不再展示后端异常堆栈。B04 会话接入 G6-A 已有的分段重置：核对旧段的待处理操作、新段与流身份、时间零点及重置收据；新段重新启动任务服务，草稿编辑与隔离预览恢复。用户可点击左侧“重置”后在新仿真段重新规划。G5／B03 合格源码及 G5／G6-A 正式指针未修改。

最终构建 `g6-b04-build-20260928-start-guard02` passed。真实 Edge `g6-b04-browser-start-reset-20260928-gui2` 验证取消直接开始不改变控制状态、确认直接开始后任务面板安全提示、重置后段身份变化及零时间、重新保存草稿并取得隔离预览；预览后仿真仍未开始。对应 `g6-b04-session-start-reset-20260928-gui2` 两段正常退出。Gui 完整执行 `g6-b04-browser-start-guard02-20260928-gui` 和 Headless API `g6-b04-flow-start-guard02-20260928-headless` 再次验证同一方案 19／19 航点、TaskComplete 与正常退出；两模式独立收据 `g6-b04-acceptance-start-guard02-20260928` passed、`executionQualified=true`。首个 GUI 探针 `g6-b04-browser-start-guard-20260928-gui` 因地图 ready 字段尚未出现而 KeyError，失败记录保留；探针改为等待缺省字段后新会话通过。当前 B04 页面资格以 start-guard02 和本轮收据为准，B05 仍为下一卡。
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

# G6-B06 执行中受控重规划验收

日期：2026-10-04，Windows 11 x64，Asia/Shanghai。结论：**G6-B06 独立候选通过**；下一卡为 B07 生命周期与故障恢复，G6 全阶段尚未完成。G5／G6-A 正式指针保持原状态。

## 范围与切换协议

本卡从 B05 已确认、已开始执行且尚无旧任务完成的真实会话进入。用户先暂停仿真，再选择修改已有任务几何或加入已保存的草稿。服务从活动观察流取得三架飞机的最新状态、旧任务事件、当前航段和覆盖快照，绑定运行／分段／后端／观察流身份。独立 UxAS 规划实例从这些飞机位置计算替代方案；它不能向活动后端发执行命令。审查页给出原任务、新任务修订、分配、预计完成时间、航点与航程变化，以及切换前的侦察统计。输入或活动状态变化会使确认失效。

勾选确认后，本地 `/api/tasks/v3` 服务逐条向活动 UxAS 送入新任务和与审查一致的规划响应，等待活动日志确认接收，并核查新航线命令。只有新航线已出现，才发 `RemoveTasks` 移除旧任务，随后恢复仿真。切换中的每一步写入操作收据；结果不确定时标为 `uncertain`，不自动重发。当前每个仿真段只允许一次替换，已完成旧任务不能通过本卡重新打开。

旧统计按切换前观察游标和 SHA256 归档；新任务使用 3100～3102 及新修订，从零独立累计。B01 规则明确首批未变任务也默认**不继承**统计；本卡已在两模式中验证旧／新 20 米栅格及点观察时间可从不可变网关事件流分别复算，且未混用旧计数。新旧任务服务切换、旧任务完成事件及传感器动作在真实 UxAS／AMASE 日志中核对；传感器覆盖只按新任务版本归属。

页面入口为右侧任务工作区的“执行中调整任务”。先在开始前确认 B05 联合方案并开始仿真；旧任务处于执行中时，点击左侧暂停，选择修改或新增任务，生成替代方案，检查差异，勾选后切换并继续仿真。页面刷新后可重新读取当前任务和操作结果；完整的跨故障恢复矩阵留给 B07。

## 实际验收

最终源码绑定构建 `g6-b06-build-20261004-09/result.json` passed；独立汇总 `g6-b06-acceptance-20261004-03/acceptance.json` passed，`replanningQualified=true`。汇总重新核对构建输入 SHA256、两模式会话和审计收据、真实 Edge 截图、正常退出以及固定端口释放。

| 入口与操作 | 真实执行及独立审计 |
| --- | --- |
| Headless：`g6-b06-session-headless-20261004-06`，`g6-b06-flow-headless-20261004-06`，`g6-b06-audit-headless-20261004-05`；执行中修订折线 | 新任务 3100／3101／3102 均完成；400 收到 30／30 个计划航点、500 收到 14／14 个计划航点并实际飞行。旧覆盖 3000 为 55／88 格，3002 为 325／375 格；新覆盖 3100 为 107／107 格、3102 为 375／375 格，点任务观察 142.340 秒。切换后旧任务 TaskComplete／关联传感器动作均为 0，新任务关联动作 95 条由 AMASE 接收；会话正常退出。 |
| Gui＋真实 Edge：`g6-b06-session-gui-20261004-04`，`g6-b06-browser-gui-20261004-03`，`g6-b06-audit-browser-20261004-03`；执行中加入矩形草稿 | 页面从三草稿确认两任务旧方案，旧任务 TaskActive 后于 45.499 仿真秒暂停；原方案清楚列出 3000／3001，新增的 3002 只列于替代方案，未勾选时确认禁用。400 收到 43／43 个新航点并实际飞行，3100→3101→3102 均完成。旧覆盖 3000 为 68／88 格、点观察 5.330 秒；新覆盖 3100 为 88／88 格、3102 为 375／375 格、点观察 147.929 秒。切换后旧任务 TaskComplete／关联动作均为 0，新任务关联动作 117 条由 AMASE 接收；截图 `review.png`、`completed.png` 和正常退出均留存。 |

`g6-b06-contract-20261004-02/result.json` 已核对修订、加入以及旧流身份和非法几何拒绝。隔离规划响应、逐条活动消息、AMASE 航点、飞机状态、TaskActive／TaskComplete、覆盖事件游标与 SHA256 都保存在上述运行目录；验收脚本重新读取这些证据，而非只接受页面状态。

## 失败记录与边界

最初隔离规划使用 B04 执行专用配置而失败，改用 B01 完整规划配置后通过。早期活动快照会落后于网关事件账本，后续以账本追平和两次稳定读取为准；周期性 `OnboardStatusReport` 不改变业务状态。历史诊断和失败会话 01～03 均保留。真实 Edge 首次轮询完成状态时，确认 GET 与页面轮询并发写同一个 `.tmp` 文件，Windows 返回 WinError 32；失败浏览器记录为 `g6-b06-browser-gui-20261004-01`。现在确认 GET 只计算并返回执行状态，不写操作收据，构建 08 的两模式重新通过。

本卡仅覆盖一次暂停后的受控切换、首批点／线／矩形和旧任务未完成的组合。没有验证开始后任意时刻直接新增、连续多次重规划、已完成任务重开、多客户端冲突、后端／网关重启、丢响应后的恢复和迟到消息矩阵；这些归 B07。若切换阶段出现不确定结果，保留现场和收据供 B07 处理，不能把操作重新提交当作恢复。矩形仍限实体 400；没有设置覆盖率最低门槛，也未切换正式发布指针。

## 重跑入口

在仓库根目录使用已核查的 Python 3.14.7 x64。每次使用新编号；启动会话后另开终端运行流程，完成后在该会话目录创建 `request-stop` 并核对 `runtime-result.json`。

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
& $pythonExe -I -B -X utf8 scripts/g6_replanning/build_viewer.py --run-id '<NEW_B06_BUILD_ID>'
& $pythonExe -I -B -X utf8 scripts/g6_replanning/session.py --run-id '<NEW_B06_SESSION_ID>' --viewer-build g6-a03-build-20260924-2330 --draft-build g6-b03-build-20260924-2438 --execution-build g6-b04-build-20260928-duration02 --assignment-build g6-b05-build-20260930-05 --replanning-build '<NEW_B06_BUILD_ID>' --mode Headless
& $pythonExe -I -B -X utf8 tests/g6_replanning/flow.py --session 'out/runs/<NEW_B06_SESSION_ID>/segment-001/control-session.json' --mode revise --run-id '<NEW_B06_FLOW_ID>'
& $pythonExe -I -B -X utf8 tests/g6_replanning/audit.py --session 'out/runs/<NEW_B06_SESSION_ID>/segment-001/control-session.json' --flow 'out/runs/<NEW_B06_FLOW_ID>/result.json' --output 'out/runs/<NEW_B06_AUDIT_ID>/result.json'
```

Gui 模式会话将 `--mode` 改为 `Gui`。真实 Edge 操作由 `tests/g6_replanning/browser.py` 执行，使用 `.tools/g4/current.json` 指向的独立 Python，参数为 `--session` 与 `--output`；完成后同样运行 `audit.py`。页面地址 `http://127.0.0.1:8080/`，任务调整 API 为 `http://127.0.0.1:8006/`。最后用 `tests/g6_replanning/acceptance.py` 绑定本次构建、契约、两模式会话／流程／审计编号，取得独立验收收据。

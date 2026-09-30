# G6-B05 多机多任务分配验收

日期：2026-09-30，Windows 11 x64，Asia/Shanghai。结论：**G6-B05 独立候选通过**；G6-B06 执行中受控重规划为下一卡，G6 全阶段未完成。本卡未切换 G5、G6-A、UxAS 或网关的正式指针。

## 范围与实现

- B03 保存的点、线、矩形草稿仍使用各自修订和几何；B05 独立契约 `config/g6-assignment-contract-v1.json` 为线／点开放 400、500、600 候选，矩形限 400。自由分配允许固定或候选集合；顺序关系限定同一架 400，任务顺序由用户排列。
- 新页面在任务工作区顶部提供任务纳入、候选飞机、自由分配／按顺序执行、UxAS 分配与预计完成时刻、初始转场代价、每架飞机完整航线和显式确认。预计代价取 UxAS `AssignmentCostMatrix` 中 `IntialTaskID=0` 的 `TimeToGo` 最小值；它只是初始转场估计，不称为算法解释或完整任务成本。
- `apps/g6_assignment/server.py` 提供本地 `/api/tasks/v2/state`、`/plans`、`/plans/{planId}`、确认与操作查询。规划复制已保存草稿并绑定修订、运行／段／后端／流身份，在无活动命令的独立 UxAS 进程内请求真实 `TaskAutomationRequest`，核对 `TaskAssignmentSummary`、成本矩阵及任务航点；隔离实例正常退出且不能发出活动飞行命令。
- 确认复查同一草稿、规划 XML、原始隔离日志和审查摘要，自动开始仿真，向活动 UxAS 逐条下发任务、非沙箱分配上下文和**同一份** `AutomationResponse`。每条消息保持 TCP 连接直到活动 UxAS 日志确认接收；未知结果记为待核实，不自动重复下发。执行跟踪按三项任务各自的 `TaskActive`／`TaskComplete` 更新。
- B05 仅在仿真开始前规划。B04 固定一任务流程及正式 G5／G6-A 接口保持原资格；运行中新增／修订与旧航段切换留给 B06。

## 实际验收

最终页面候选为 `g6-b05-build-20260930-05`，构建结果 `out/runs/g6-b05-build-20260930-05/result.json` 为 passed。双模式独立汇总验收 `out/runs/g6-b05-acceptance-20260930-03/acceptance.json` 为 passed，复核了来源摘要、隔离规划日志、任务审计、真实 Edge、正常退出及固定端口释放。完整收据和原始字节保存在下表所列 `out/runs/` 目录。

| 模式与入口 | UxAS 方案 | 实际执行与独立统计 |
| --- | --- | --- |
| Headless API：`g6-b05-session-headless-20260930-04`、`g6-b05-flow-headless-20260930-04` | 线 3000、点 3001 均有 400／500／600 三架合格候选；矩形 3002 为 400。空任务关系；UxAS 分配 3000→400、3001→500、3002→400；400 为 35 航点、500 为 14 航点。成本矩阵 1804 项。 | 三项均唯一 TaskActive／TaskComplete；持续时间依次为 41.971／120.301／71.259 秒。AMASE 接收全部分段命令与 49 个计划航点；400、500 在任务完成前实飞约 4101／2666 米。错误矩形候选及错误审查摘要被拒绝；最终会话正常退出。 |
| Gui＋真实 Edge：`g6-b05-session-gui-20260930-03`、`g6-b05-browser-gui-20260930-03` | 页面选择 `.(p3000 p3001 p3002)`，三任务同属 400；UxAS 预计完成时刻 64.292／114.110／217.473 秒严格递增，43 航点、成本矩阵 1156 项。 | 真实 Edge 完成页面选择、生成方案、未勾选确认禁用、勾选确认和执行状态查看；三项实际完成顺序相同，持续时间 40.741／53.700／61.870 秒。AMASE 收到完整分段航线并实飞；Edge 正常关闭、后端会话正常退出。截图为 `out/runs/g6-b05-browser-gui-20260930-03/review.png` 与 `completed.png`。 |

Headless 方案 ID `2b96909f405a48ee9aa2862d8cb2496e`，隔离规划编号 `9d2348f33b494097869ab7bf65604ce2`；Gui 方案 ID `24a1fa20621e4a2193bed09de82e6c15`，隔离规划编号 `655aeb87f142421ca68398568a76ad0c`。两模式均由受检草稿生成，而非使用源码中固定规划结果；审计重新读取活动 UxAS 消息、AMASE 接收流与实体状态，逐航点比对经审查的方案。没有设置覆盖率最低门槛，也没有登记原生覆盖报告。

## 故障与边界

初始诊断把矩形任务开放给 400／500／600 时，活动 UxAS 产生 48 项 `SensorFootprintRequests.Footprints`，超过 UXTASK 模型的 16 项上限；正式网关按协议拒绝并降级，失败会话 `g6-b04-session-b05-probe-20260930-01` 保留。B05 将矩形限定为单机 400，线／点仍保留三机候选，最终两模式网关均保持正常。扩大矩形候选需先独立解决上游消息规模与模型限额，不能放宽网关校验掩盖问题。

第二个诊断中，约 10 KB 的 `UniqueAutomationResponse` 在发送端立即关闭连接时未进入活动 UxAS 日志，出现飞机沿航线飞行而无 TaskActive／TaskComplete 的情况；失败会话 `g6-b04-session-b05-probe-20260930-04` 保留。B05 确认接口现在等待每条消息写入活动日志后才发送下一条，随后探针和最终两模式均完成任务生命周期。此问题仅在 B05 多任务较大响应中实测；B04 合格记录不改写。

任务资格仍是首批三类 CMASI 搜索和冻结初始状态；方案预算基于航线距离与速度的保守检查，不能保证所有条件下准时完成。执行中改动、重规划、统计版本切换和完整故障恢复属于 B06／B07。

## 重跑入口

在仓库根目录，以经核查的 Python 3.14.7 x64 运行；所有编号须新建，`--mode` 分别取 `Headless`／`Gui`：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
& $pythonExe -I -B -X utf8 scripts/g6_assignment/build_viewer.py --run-id '<NEW_G6_B05_BUILD_ID>'
& $pythonExe -I -B -X utf8 scripts/g6_assignment/session.py --run-id '<NEW_G6_B05_SESSION_ID>' --viewer-build g6-a03-build-20260924-2330 --draft-build g6-b03-build-20260924-2438 --execution-build g6-b04-build-20260928-duration02 --assignment-build '<NEW_G6_B05_BUILD_ID>' --mode Headless
& $pythonExe -I -B -X utf8 tests/g6_assignment/flow.py --session 'out/runs/<NEW_G6_B05_SESSION_ID>/segment-001/control-session.json' --mode parallel --run-id '<NEW_G6_B05_FLOW_ID>'
```

会话就绪文件是 `out/runs/<NEW_G6_B05_SESSION_ID>/b05-session-ready.json`；测试完成后在该文件给出的 `stopFile` 路径创建停止文件，再检查 `runtime-result.json`。Gui 页面测试入口为 `tests/g6_assignment/browser.py`，需使用已有 G4 独立环境中带 `websockets` 的 Python，并指定新 `--output` 与会话 `--session`。页面地址为 `http://127.0.0.1:8080/`；本地 B05 API 地址为 `http://127.0.0.1:8005/`。

两模式完成并关闭后，使用 `tests/g6_assignment/acceptance.py` 绑定本次构建、Headless 会话／流程和 Gui 会话／浏览器编号，生成独立 `acceptance.json`；正式通过编号见上文。

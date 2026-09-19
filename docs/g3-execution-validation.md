# G3-T04 规划命令实际执行验收

日期：2026-09-19，Asia/Shanghai。**T04 已完成，T05 可执行、尚未启动，G3 尚未完成。** GUI／无界面均证明真实 UxAS 规划驱动被分配实体推进搜索航段，两端正常退出。本卡不声明完整任务、末端完成或覆盖统计通过；不设覆盖率指标，不调优算法／参数。

## 1. 交付与复用入口

新增 [执行编排](../scripts/g3_execution/runtime.py)、[证据关联器](../scripts/g3_execution/correlator.py)、[内部导航探针](../scripts/g3_execution/ExecutionProbe.java)、[反例验收](../tests/g3_execution/checks.py)和 [执行配置](../config/g3-execution.json)。复用已验收的 [T03 编排与 StartupProbe](g3-startup-validation.md)，不修改旧入口含义、旧源码或历史验收报告。

仓库根目录，PowerShell 5.1：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
# 单模式：证明初始执行后自动正常关闭。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g3-execution.ps1 -PythonExecutable $pythonExe -Mode Headless
# GUI、无界面顺序运行，并执行离线反例。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g3-execution.tests.ps1 -PythonExecutable $pythonExe
```

运行入口支持 Mode、Configuration、RunId、BaselineRunId；验收入口支持后三项，自动顺序验收两模式。默认配置 scope=execution，引用原 config/g3-startup.json；本卡锁定执行判据，不能通过配置降低门槛。省略 BaselineRunId 时先重新复查正式来源；指定时仍复查清单与当前产物。运行编号须以 g3-t04- 开头且未使用。GUI 自动收尾，不要求人工操作，不复用 T02 的人工确认；T07 仍需本轮全程 GUI 确认。

T03 的暂停启动、两实体真实配置／动态状态屏障、TaskInitialized 后单次请求、端口／PID、30 秒初始化／规划／关闭超时均保留。T04 执行观察上限 600 墙钟秒；两模式均 1 倍速，原 785 秒场景和业务服务保持。整次活动截止 2650 秒，保留关闭预算，自动运行上限 2700 秒。

## 2. 实际关联与执行判据

关联任务 1000 的 TaskInitialized → UniqueAutomationRequest → TaskAssignmentSummary → UniqueAutomationResponse／AutomationResponse → 分段 MissionCommand → AMASE 收到命令 → 真实导航及 AirVehicleState → TaskActive／任务航段推进。CMASI 请求／响应没有关联 ID，记录实际 Unique 身份并核对原请求有效字段、分配结果、完整计划内容；所有实体／任务／命令／请求 ID 保存为字符串。

- 原巡航 CommandID=100 按实体 400／500 分别识别；UxAS 还会把巡航重新封装为本地命令。本轮前置巡航封装为 21／24，不把它们计作搜索执行。原请求中的旧 Label 字段不属于当前 CMASI；对原文件按同批模型解析、补足默认值后比较实际 LMCP 语义，保留文件和单次注入字节的摘要。
- 完整计划 CommandID=1 与实际分段命令分别登记。分段须匹配计划中的航点身份、顺序、经纬高、速度、NextWaypoint 和任务关联；收到的分段必须与 AMASE 独立 TCP 字节、内部事件一致。正常重叠允许，重复命令、分段回退及已走航点回退拒绝。
- CurrentWaypoint 是当前**目标**航点。网络采样可能跳过短暂目标，因此探针作为运行副本的末尾 EntityModule，在真实 WaypointFollower 之后读取导航属性；记录命令应用后的即时属性，再按目标变化及约 0.2 仿真秒周期留样，避免首目标在下一步立即推进时遗漏。它不调用 getState、不改属性、不发业务事件、不注入命令或状态。记录 commandId、waypoint、waypointReached、位置、模式及两类时间。
- 公共状态须匹配已接收命令、任务及计划航点；与内部事件作跨语言字段核对，Java／Python 字段输出顺序和 float32 文本精度差异仅在比较层处理。整数身份严格比较，不经浮点转换。导航采样与公开状态须在 1 仿真秒内有相同命令／目标，最近匹配位置水平差小于 10 米、高度差小于 1 米。
- 本卡至少观察四个不同任务目标航点、两个真实执行分段和一次 TaskActive；内部目标序列必须按 NextWaypoint 前进。至少两段两端均关联任务的航段须实际推进，内部至少三样本、前向投影和接近目标均增加至少 10 米，最大横向偏差和最近目标距离各不超过 300 米，高度误差不超过 25 米。

300 米是本场景执行轨迹的检查容差：名义速度 22 m/s、最大坡度角 20° 对应约 136 米转弯半径，TurnShort 可在约两倍半径内提前转弯；它不是覆盖指标，也不是逐点飞越精度要求。`completedTaskLegs` 记录目标推进至后继的局部航段证据，**不表示全任务完成**。保留全部度量，可核对真实提前转弯与几何偏差。

源码与实测共同确认原配置 `NumberWaypointsToServe=15`、`NumberWaypointsOverlap=5` 在当前分段实现中产生四个重叠航点；第一段 1～15，第二段 12～26，重叠 12～15。原配置的 `param.turnType=FlyOver` 未被读取，服务读取的是 `TurnType`，实际默认 TurnShort。本卡原样保留，未为提高覆盖效果更改属性或算法。参考 [WaypointPlanManagerService](../OpenUxAS/src/cpp/Services/WaypointPlanManagerService.cpp)及 [WaypointFollower](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/entity/modules/WaypointFollower.java)。

## 3. 最终真实运行结果

起点提交 `50b282e2324023b20da1a0842cd51ab9e3103858`，工作区干净。最终资格 `g3-t01-check-20260919-121013-211`；最终验收 `g3-t04-test-20260919-121531-644`，result／entry-result 均 passed，23 项反例／边界检查通过。实际从仓库外 out/tmp 调用验收，Configuration 使用中文空格路径。环境、工作目录、编码恢复，持久 PATH 不变。

| 模式 | 退出时仿真秒 | 分配实体 | 原计划命令／航点数 | 实际执行分段 | 网络观察的任务目标 | 合格局部航段数 | AMASE／UxAS 退出码 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Headless | 121.94 | 400 | 1／74 | 67 → 68 | 14、15、16、18 | 2 | 0／0，正常 |
| Gui | 121.99 | 400 | 1／74 | 67 → 68 | 14、15、16、18 | 2 | 0／0，正常 |

两实体都持续提供真实状态，只有 UxAS 实际分配的实体须执行任务。每模式的 execution.json 保存原计划身份、巡航命令、分段及重叠、内部接收 sequence、内部与网络航点序列、TaskActive 和逐样本轨迹。case-result.json 保留完整链路来源、PID、端口归属、全部 evidence 摘要与正常退出；退出后端口释放，无强制终止。taskExecutionValidated=true，taskCompletionValidated=false，coverageValidated=false。

正式包未改：AMASE SHA-256 `AD32BF2A2A084CF24C69CF644B8DA807B6045E7CEC11928FC0AB59419BCECAC9`，UxAS `036EA32D168859B089969F4EA24431BB52F9302B65C1EC185EA0A82D77CFA366`，Java LMCP `FD6F40587AF46C380B959BD6036A2D269D87CB2D62FC50BF3AC2333E31D07E4C`。同批七模型仍为 g1-t03-20260917-152214-037296；43 项冻结输入、原场景／任务／请求及 T03 源码保持。两个探针仅在本轮 out/build 独立编译，不重发正式 JAR／EXE。

## 4. 反例、失败记录及边界

23 项为基于真实捕获的**离线证据反例／边界检查**，不冒充 23 次后端故障注入：仅有命令、缺 AMASE 内部接收、缺 TCP 接收、缺内部状态、错误 Unique 身份／分配实体／分配任务、缺 TaskActive／错误任务／错误实体／提前激活、缺后续分段、静止时间、巡航运动、状态任务／目标错误、偏离航线、静止位置、缺内部导航、重复分段、目标回退、内部位置与网络不符，以及相邻大 int64 身份必须可区分。每项记录拒绝原因，未修改真实运行记录；原样正向回放仍通过。

保留失败批次：

| 批次 | 事实与处理 |
| --- | --- |
| g3-t04-test-20260919-115933-023 | 实际进入任务并正常退出；初版关联器直接比较原 XML 与消息，因旧字段／省略默认字段拒绝。改为同批模型解析后的有效请求比较。只读诊断另发现 Java／Python 字段顺序／float32 文本差异及网络漏采短航点，分别用语义比较与独立内部导航探针解决 |
| g3-t04-test-20260919-120403-802 | GUI／无界面实际执行子用例均 passed 且正常退出；静止时间反例先被内部同时间键冲突拒绝，未达到预期诊断，整组 failed。将时间单调检查前移；补齐位置交叉检查、重复／回退及 int64 边界反例后，先离线复核，再以新编号完整复验 |
| g3-t04-test-20260919-121012-982 | 两端正常退出，但网络在 5.239 仿真秒观察到目标 2，步末内部记录已推进至 3，交叉检查拒绝。补录真实命令应用后的内部导航属性；未放宽目标匹配，未改写该批失败收据 |

不覆盖失败收据，不把调试用旧证据改成新源码合格运行。原始字节／解码／内部事件／导航／数据库／配置差异／进程及摘要均归同一运行编号；Python／Java 调试日志和生成 class 留在忽略的 out，不提交。

下一项 T05：关联任务末端及可靠 TaskComplete，核实并修复 AllAny 等统计问题，补齐 GUI／无界面一致的 20 米栅格分析导出和正确性对照；如实保存实际覆盖值，不设最低覆盖率。T06 的重复启停／故障恢复矩阵和 T07 的全程复验／GUI 人工确认仍待实施。

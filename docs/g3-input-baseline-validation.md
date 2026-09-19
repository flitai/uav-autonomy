# G3-T01：输入与验收基线

日期：2026-09-19，Asia/Shanghai。**T01 已完成，T02 可执行、尚未启动；G3 尚未完成。** 本轮实际执行了正式产物、工具、CRT、同批消息库和原始输入的资格复查，未启动 AMASE／UxAS 仿真或进行 TCP 联调。后文的消息行为来自源码，完整执行与覆盖率均为后续验收要求。

## 1. 本轮交付与复用入口

起点为干净的 main／`5c0658ddd3a75da690daf4b0a90ee35714d1cdbc`。新增独立的 [Windows 检查入口](../scripts/windows/check-g3-baseline.ps1)、[核查实现](../scripts/g3_baseline/check.py)、[基线清单](../config/g3-baseline.json)和[输入反例](../tests/g3_baseline/checks.py)，不改变既有 G1／G2 入口及资格接口。

以下命令从仓库根目录执行；Python 参数必须指向实际解释器，不能填写 WindowsApps 别名。入口按脚本位置定位仓库，也已从仓库外的系统临时目录调用通过。

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\check-g3-baseline.ps1 -PythonExecutable $pythonExe
# 替换为上述入口输出的本次编号；这里只校验输入，不运行仿真。
& $pythonExe -I -B -X utf8 .\tests\g3_baseline\checks.py --output .\out\runs\<G3_T01_RUN_ID>\baseline-checks.json
```

检查入口生成独立 `out/runs/g3-t01-check-<时间>/`：`context.json` 绑定正式解析编号和实际工具版本，`qualification.log` 保存解析输出，`baseline.json` 保存输入／模型／产物／收据身份及验收契约，`result.json` 和 `entry-result.json` 分别保存核查与环境恢复结果。只有两者均 passed 才算资格复查成功。入口前置失败可能只有 entry-result；失败不更新正式包或指针。所有原始收据留在被忽略的 out 目录。

清单冻结 35 个原始场景、消息、配置及相关源码文件；验收契约是后续实现的输入，**不是已经实现的运行验收器**。后续必要源码修复导致清单差异时，先保留本轮基线，再按影响重建／复验／发布并登记新的输入身份，不能改写旧收据来绕过来源拒绝。

## 2. 实际资格复查

| 检查 | 本轮结果与证据 |
| --- | --- |
| 正式入口 | `g3-t01-check-20260919-093348-422`，PowerShell 退出 0；result／entry-result 均 passed，五类资格检查通过 |
| UxAS 解析 | 嵌套 `g2-t07-resolve-20260919-093348-447`；通过既有 Resolve-UxasPackage 核对正式指针、候选、验收／发布收据、包文件、来源及当前 CRT；无应用运行用例 |
| AMASE | 正式构建 `g1-t04-build-20260917-162820-915606`；重新核对源码／构建输入、JAR／探针、消息依赖、11 项历史自动验收及历史 GUI 事件／退出证据 |
| 七模型同批 | Java／C++／Python 均绑定 `g1-t03-20260917-152214-037296`；模型和生成输出哈希通过，实时 handoff 与正式包内 handoff 相同 |
| 工具 | Temurin 11.0.32.1+1、javac 11.0.32.1、Ant 1.10.18、隔离 Python 3.14.7 x64；C++ 工具／固定依赖通过原资格链复查 |
| 环境与边界 | 从其他工作目录调用；进程环境、目录、编码均恢复，User／Machine PATH 未变；simulationStarted=false、networkValidationPerformed=false |
| 输入反例 | 同一成功目录下 baseline-checks.json：原例通过，九个修改后的内存 XML 被拒绝；共 10 项通过，冻结源文件哈希保持 |
| 缺失 Python | `g3-t01-check-20260919-093452-631`，退出 1、entry-result 为 failed；明确提示实际解释器缺失，四项恢复检查均通过，未启动资格解析或仿真 |

九个反例为：缩短场景、缺实体状态、重复实体身份、缩短水道、错误任务、错误请求实体、错误请求任务、无界面粗化栅格和改变原始命令身份。它们验证 T01 输入边界，不代替 T02 网络坏帧或 T03 实时数据反例。

正式 UxAS 仍为构建 `g2-t05-build-20260918-201846-291`／候选验收 `g2-t05-test-20260918-202115-333`／T07 验收 `g2-t07-test-20260918-203915-916`／发布 `g2-t07-publish-20260918-204152-283`。C++ LMCP 为 `g2-t03-build-20260918-195001-565`／`g2-t03-test-20260918-195057-347`，没有新构建或发布。

| 文件或库 | 本轮核对的 SHA-256 或版本 |
| --- | --- |
| 正式 uxas.exe | `CDE0AB551D557A7E469645D8144ECA652EEF62717934C4F91A0FF8BDEE115C7C` |
| 正式 OpenAMASE.jar | `D4E80C5318517266C161B636FDA4771FBD4921B71967E45F3C37C3A85E5E167E` |
| 统一 Java lmcplib.jar | `FD6F40587AF46C380B959BD6036A2D269D87CB2D62FC50BF3AC2333E31D07E4C` |
| 本轮 baseline.json | `CB6AEE0789C05C5080BBEC23383CDA833CE1C672B95EC06FC3B32601FAB26645` |
| 模型版本 | CMASI 3、IMPACT 14、PERCEIVE 1、ROUTE 4、UXNATIVE 9、UXTASK 8、VEHICLES 1 |
| CRT | msvcp140／vcruntime140／vcruntime140_1 为 14.50.35719.0，ucrtbase 为 10.0.26100.9444；当前文件与包内版本／哈希清单一致 |

CRT 是当前安装文件与既有加载来源的复核，本轮未重新加载到 UxAS 进程。AMASE 人工确认属于 G1 历史验收，不能复用为 G3-T07 本轮确认。正式 handoff 的 `g3Started=false` 是 G2 交接时的历史值，保留原样。

## 3. 原始场景与四类消息

原例目录为 [02_Example_WaterwaySearch](../OpenUxAS/examples/02_Example_WaterwaySearch)，精确文件及哈希见基线清单。两实体均须提供真实状态；搜索由实际分配实体执行，不要求两架都被分配。

| 类别 | 原始值／时序 | G3 中的用途 |
| --- | --- | --- |
| AMASE 场景输入 | Scenario_WaterwaySearch.xml，785.0 秒；400／500 配置事件在 1.0／1.1 秒，状态事件在 1.4／1.5 秒，状态载荷 Time 初值为 0 | 启动仿真的初值；读取 XML 或仅收到该初值均不能证明动态状态进入 UxAS |
| AMASE 原始巡航 | 两个 MissionCommand，VehicleID 分别 400／500，CommandID 均为 100；事件在 1.8／1.9 秒，初始状态 Pending，航点 1 指回 1 | 解释任务请求前的运动；不能用原命令、已有航线或位置变化充作规划执行 |
| UxAS 静态注入 | SendMessagesService 在 200 ms 注入两配置、250 ms 注入两状态、300 ms 注入任务、5000 ms 注入请求 | 原 XML 保留；T03 的 G3 副本取消该服务注入，不能靠静态样本补齐实体 |
| 实时消息与新计划 | AMASE 动态 AirVehicleState；UxAS 的规划响应及分段 MissionCommand | 必须绑定真实连接、双方消息／事件、当前命令及任务航段，再判定执行 |

任务文件 `1000_LineSearch_LINE_Waterway_Deschutes.xml`：TaskID=`1000`，90 个 Location3D 构成完整水道，点序和坐标固定。原请求文件 `1001_AutomationRequest_LINE_Waterway_Deschutes.xml` 的 EntityList 为 `400`／`500`，TaskList 为 `1000`；文件名前缀 1001 不是请求 ID。原任务 DesiredWavelengthBands 为 AllAny；重复 ViewAngleList 和旧相机字段列入第 6 节风险。

原 UxAS EntityID=`100`。两实体的 WaypointPlanManager 都设置每段 15 个航点、重叠 5 个，末尾不添加盘旋、不回到第一个任务。后续保持该续传语义，不能按“命令 ID 变化”或“再次出现重叠航点”直接判重复执行。

原 GUI／无界面 SearchTaskAnalysis 的 GridResolution 均为 20 米。原场景、任务、配置及静态样本本轮均未修改；零高程缺省条件仍不代表真实地形已校准。

## 4. 源码消息流与协议检查表

依据：[Java 工厂模板](../LmcpGen/src/templates/java/lmcp_factory_java)、[AMASE TcpServer](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/network/TcpServer.java)、[UxAS TCP 桥](../OpenUxAS/src/cpp/Communications/LmcpObjectNetworkTcpBridge.cpp)、[PUB 桥](../OpenUxAS/src/cpp/Communications/LmcpObjectNetworkPublishPullBridge.cpp)、[原 UxAS 配置](../OpenUxAS/examples/02_Example_WaterwaySearch/cfg_WaterwaySearch.xml)。下表为源码路线，T02 须用真实两端验证。

| 方向 | 消息与订阅 | 来源和必要证据 |
| --- | --- | --- |
| AMASE → 主 TCP 桥 → UxAS 总线 | 两实体配置／动态状态，按桥导入进入总线 | Java packMessage 的属性源 EntityID／ServiceID 为 0／0；载荷 ID 才是 400／500。记录原始帧、接入连接和总线属性，不能按属性源 0 判“无实体” |
| UxAS 总线 → 主 TCP 桥 → AMASE | 原订阅仅 MissionCommand、LineSearchTask、VehicleActionCommand | 正式配置显式 ConsiderSelfGenerated=false；AMASE 内部接收事件与外部载荷逐项核对，不能只记录 send 成功 |
| UxAS 总线 → TCP 9999 观察端 | 原配置订阅 a～z、A～Z 前缀；当前 afrl／uxas 类型在范围内 | TCP 导出与 PUB 来源限制分别核实；观察端不回送收到的消息，保留 Unique 请求／响应、任务生命周期及分段命令 |
| 观察端 → UxAS | 单次任务、单次 AutomationRequest、明确的正常停止消息 | 编排动作单独记发送序号和字节，不发送伪造实体状态、MissionCommand 或 TaskComplete；停止类型／目标由 T02～T03 对照既有入口确认 |
| UxAS 总线 → PUB 5560 | 原配置同样订阅字母前缀，但仅导出本地来源 EntityID | 默认 ConsiderSelfGenerated=true 会将 TCP 导入来源改写为本地 100；false 保留 0 时 PUB 可能过滤这些消息。正式状态证据使用 TCP，PULL 5561 仅在明确对照配置下启用 |

AMASE 接收后分发本地事件，并排除原连接进行转发；UxAS 桥的导入／导出行为仍需实测回路。AMASE 还能拆分 AutomationResponse 内的命令，但当前主桥没有订阅 AutomationResponse；不得同时放行完整响应和相同的独立 MissionCommand 形成双重执行路径。

T02 的逐项检查条件：

1. 分别取得真实 Java 与 C++ 发出的原始字节，识别 Sentinel 外层、属性字段和内部 LMCP；长度及实际校验和均须正确，不能把工厂可接受零校验和视为严格验收。
2. 同一原始流的完整帧、半包、粘包应解出相同有序消息；非法长度、错误校验和、未知／错误类型必须保留拒绝与字节位置。验收器拒绝和真实后端行为分开记录。
3. 对 ConsiderSelfGenerated true／false 比较原始来源、导入总线来源、TCP／PUB 导出及订阅结果；业务实体 ID、属性源、连接 PID 三者分别保存。
4. 主链路各类状态和命令只有预期转发；观察端不回送。结合内容哈希、连接与序号检查重复，允许声明的正常周期状态及航点续传。
5. 断开时保存未消费尾部并清理解析缓冲；新连接／运行不得继承残包。自动重连与快照补齐仍归 G4。

## 5. 后续可执行的验收契约

下列规则已写入基线清单并在此明确取证方式；运行关联器、AMASE 插件和分析导出仍待 T03～T05 实现。

| 门槛 | 必须满足与取证方式 | 反例／责任任务 |
| --- | --- | --- |
| 来源与端口 | 每次重查正式来源、运行副本和 PID；GUI 为 5555／9400／9500，无界面为 5556／19400／19500，观察口 9999，两模式顺序运行 | 来源混批、端口冲突、占用者不明即失败；T02／T03／T06 |
| 初始齐全 | 每个实体至少 1 份配置、3 个时间严格递增的状态样本、至少 2 个不同位置；AMASE 内部事件／外发载荷与 UxAS 总线接收对应，不能只凭采样数量 | 静态状态、缺实体、仅监听或仅 TCP 连接均不通过；T03 |
| 任务与请求 | 初始齐全后发送任务 1000，收到对应 TaskInitialized 后单次发送 AutomationRequest；记录发送字节及运行内序号 | 请求过早、重复注入、错任务／实体不通过；T03／T04 |
| 请求关联 | CMASI AutomationRequest／AutomationResponse 没有 RequestID／ResponseID；观察 UXTASK UniqueAutomationRequest.RequestID 与 UniqueAutomationResponse.ResponseID，核对其原始请求／响应内容和实际分配 | 不把文件名、未知 Label 或自造字段当模型 ID；T04 |
| 命令执行 | 关联原始规划、分段 MissionCommand、AMASE 接收、CurrentCommand／CurrentWaypoint／AssociatedTasks 与实际轨迹；键含运行、实体、命令 ID 及载荷／序号，分段命令允许新 ID | 两实体原命令共享 100；仅命令发送、收到、航线出现或移动均不足；T04 |
| 可靠完成 | 同一任务与执行实体的 TaskActive → 任务航段实际推进 → 规划末端任务航段完成 → TaskComplete；末端须由计划航段与内部执行事件／状态轨迹共同证明，位置接近或丢失任务关联不能替代 | 提前 TaskComplete、错实体／任务、缺末端、命令未执行均拒绝；T05 |
| 覆盖率 | 使用固定 90 点水道与 20 米栅格；原始整数 total > 0、0 ≤ seen ≤ total、100 × seen ≥ 95 × total；同一运行的 XML、计数和漏覆盖位置一致 | 四舍五入、空总数、合并模式／运行／候选、低覆盖均拒绝；T05 |
| 生命周期 | 两模式各自正常退出 0，未强制终止，本次 PID 回收、端口释放；T07 还需本轮 GUI 人工确认 | 关闭窗口、进程消失或超时强杀不能单独算正常退出；T03／T06／T07 |

请求关联源码见 [AutomationRequestValidatorService](../OpenUxAS/src/cpp/Services/AutomationRequestValidatorService.cpp)、[PlanBuilderService](../OpenUxAS/src/cpp/Services/PlanBuilderService.cpp)和 [WaypointPlanManagerService](../OpenUxAS/src/cpp/Services/WaypointPlanManagerService.cpp)；模型以 [CMASI](../OpenUxAS/mdms/CMASI.xml)、[UXTASK](../OpenUxAS/mdms/UXTASK.xml) 为准。关联器还须核对任务分配与分段航点内容，不能只凭 Unique ID 相等判执行通过。

时间分别保存：AMASE [EntityModel](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/entity/EntityModel.java)写入仿真秒 ×1000；[Test_SimulationTime](../OpenUxAS/src/cpp/Services/Test_SimulationTime.cpp)把实体时间送入 DISCRETE_TIME。TaskComplete 虽调用带 UTC 名字的时间接口，在此离散模式下不能直接当 UTC；记录源字段、单位、时钟模式以及独立墙钟／单调耗时，int64 身份和源时间使用字符串。

两模式均先按 1 倍速和原参数运行 785 仿真秒。T05 原参数不达标时最多比较三组受控候选，单次最多 1800 仿真秒／2700 自动运行墙钟秒；初始化、任务初始化、规划等待、正常关闭分别 30 秒超时。GUI 人工等待单独记待确认，不计自动成功。只允许已约定的飞行、传感器、规划与时长调整，完整水道、栅格及门槛保持。

覆盖计算沿用 [SearchTaskAnalysis](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/analysis/SearchTaskAnalysis.java)统计的 NumPix／PixSeen，补充原始导出，不能把格式化的 CoveragePercent 当整数判据。末端证据、完成消息、覆盖数据和退出记录须属于同一运行编号；任一缺失保持失败或待验证。

## 6. 已确认风险与后续责任

这些是源码／XML 事实及其约束，不是本轮运行测得的失败；T01 无未解决的资格阻塞。T02～T07 必须通过各自实际验收后才能关闭相应风险。

| 编号 | 发现与影响 | 后续处理 |
| --- | --- | --- |
| G3-R01 | Java 来源为 0／0，TCP 默认改写为本地 100，PUB 过滤非本地源；订阅存在不保证完整状态 | T02 做 true／false 实测及来源矩阵；正式主桥保留来源，观察用 TCP |
| G3-R02 | 原例静态注入可掩盖缺失实时配置／状态；无界面 ConstructiveControl 会自动启动 | T03 在副本取消静态注入，插件暂停屏障与真实初始数据齐全后触发任务 |
| G3-R03 | CMASI 请求／响应无关联 ID，原始两命令共享 100，分段命令分配新 ID | T04 通过 Unique 消息、分配、实体及航点内容关联；区分正常重叠和重复执行 |
| G3-R04 | TaskServiceBase 在任务关联退出时发 TaskComplete，本身不证明飞到末端 | T05 关联完整执行链并拒绝提前完成；任务关联退出或单独完成消息不能通过 |
| G3-R05 | [LinearSearchHighlight.processSensor](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/analysis/LinearSearchHighlight.java)在 DesiredWavelengthBands 含 AllAny 时直接 return；原任务恰含 AllAny，按当前分支无法在此路径累计覆盖 | T05 保留原参数实测；受控候选可使用与实际相机一致的具体波段并记录差异，不修改评分算法。本轮没有覆盖率实测值 |
| G3-R06 | AnalysisManager 分析路径创建 JDialog 进度窗，报告只输出格式化百分比 | T05 隔离 [分析窗口](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/analysis/AnalysisManager.java)，保持计算语义，导出原始计数与漏覆盖位置 |
| G3-R07 | 任务 XML 有两个 ViewAngleList；相机 XML 使用旧复数 SupportedWavelengthBands，而当前 CMASI 是单数 SupportedWavelengthBand、默认 EO | T02 核对真实 Java／C++ 解析后的有效字段，T05 调参依据实际相机与视角；不把 XML 的字面值直接当生效值 |
| G3-R08 | 实体与任务时间在原 Test_SimulationTime 下使用仿真时钟 | T03／T04 留存时钟模式及原值，墙钟分列，禁止盲转 UTC |

后续故障／路径／三次启停及整组重启归 T06，两模式全程复验、唯一合格配置、GUI 确认及 G4 交接归 T07。T01 的资格记录不证明 TCP、规划服务实际运行、完整搜索、覆盖率或恢复通过。

下一项为 [G3-T02](backlog.md#6-g3-顺序与任务卡)。继续前复查实时输入；业务源码修复仍走原构建／资格／发布链。当前正式包、原 XML、算法及 G0～G2 历史报告保持原样。
